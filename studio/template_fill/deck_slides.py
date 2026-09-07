"""Which template slides a deck includes — the author's own answer, slide by slide.

Setup used to ask "how much of the deck should we build?" and offer four answers (the whole
QBR, or just the overall / product / country block). That is a coarse question standing in
for the one an author actually has: *this* page belongs in the deck and *that* one does not.
A scope choice could not drop the SWOT page and keep the ranking page, and it could not say
so at all — the panel listing the deck's sections was a read-out, not a control.

So the scope choice is gone and the panel is the control. Every slide of every registered
sub-template is listed with a checkbox, and what this module holds is the answer:

    :func:`catalog`      what a sub-template CONTAINS — one entry per slide, from the
                         template itself (no hard-coded indices, no static list)
    :class:`DeckSlides`  which of those the author excluded, and everything the builder
                         needs to read off that — the axes to assemble, the pages to drop

Both are pure: a template path in, a value out. Nothing here renders, queries or builds.

The selection is stored as EXCLUSIONS rather than inclusions on purpose. "Nothing excluded"
is the default a fresh form starts from, an author who never opens the panel gets the whole
deck, and a slide ADDED to a template later joins the deck instead of silently going missing
from every saved selection.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

from logger import get_logger

logger = get_logger(__name__)

# The axes a deck assembles from, in deck order. The Carrier Survey block rides along with
# the country blocks on the survey data basis (see :func:`studio.template_fill.assemble`),
# so it is listed here but gated by the basis rather than chosen on its own.
DECK_AXES: Tuple[str, ...] = ("overall", "product", "country", "survey", "end")


@dataclass(frozen=True)
class SlideEntry:
    """One slide of one sub-template: where it sits, what it is, what it is called."""

    axis: str
    index: int
    section: str                    # the :class:`~studio.template_fill.sections.Section` value
    title: str

    @property
    def key(self) -> str:
        """The id the form checkbox is keyed on."""
        return f"{self.axis}:{self.index}"


@lru_cache(maxsize=16)
def catalog(axis: str) -> Tuple[SlideEntry, ...]:
    """Every slide of ``axis``'s template, in deck order — ``()`` when it cannot be read.

    Cached per axis: the templates are a fixed, author-made set that does not change while
    the app runs, and this is read on every repaint of the Setup panel.

    A template that will not parse answers ``()`` rather than raising. The panel then simply
    lists nothing for that axis, which is what the rest of Setup already does with an
    unreadable template — a form that still draws beats a blank page.
    """
    from studio.template_fill.analyze import analyze
    from studio.template_fill.binding_map import template_path
    from studio.template_fill.sections import classify_sections

    try:
        template = analyze(template_path(axis))
        sections = classify_sections(template)
    except Exception as exc:  # noqa: BLE001 — an odd template must never break Setup
        logger.warning("deck_slides: %r could not be read (%s)", axis, exc)
        return ()
    return tuple(
        SlideEntry(axis=axis, index=slide.index,
                   section=sections[slide.index].value, title=slide.title().strip())
        for slide in template.slides
    )


def slide_count(axis: str) -> int:
    """How many slides ``axis``'s template carries."""
    return len(catalog(axis))


@dataclass(frozen=True)
class DeckSlides:
    """The slides the author took OUT of the deck, per axis.

    The value the Setup panel writes and the assembler reads. Everything the builder used to
    ask the scope choice is answered from here instead:

        which axes to assemble   ->  :meth:`wants`  (an axis with no slides left is not built)
        which pages to drop      ->  :meth:`hidden` (merged with the assembler's own pruning)

    Frozen, and normalised on the way in — sorted pairs of sorted indices — so two
    selections that mean the same thing compare and hash the same.
    """

    excluded: Tuple[Tuple[str, Tuple[int, ...]], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "excluded", _normalise(self.excluded))

    # ── building one ──

    @classmethod
    def everything(cls) -> "DeckSlides":
        """The default: every slide of every registered axis."""
        return cls({})

    @classmethod
    def only(cls, *axes: str) -> "DeckSlides":
        """Every page of ``axes``, and none of any other sub-template.

        The whole-sub-deck answer, for the callers that want one — a script, a test, a
        future "just the overall block" shortcut on the form. The back cover is always
        kept: it closes every deck, and a deck that stops mid-page is not a shorter deck.
        """
        from studio.template_fill.binding_map import available

        keep = {str(a) for a in axes} | {"end"}
        return cls({axis: [e.index for e in catalog(axis)]
                    for axis in available() if axis not in keep})

    @classmethod
    def from_store(cls, raw: Any) -> "DeckSlides":
        """The browser store's ``{axis: [index…]}``, or everything when it holds nothing.

        Tolerant by design — this reads a value that persists in local storage across
        releases, so a stored shape from an older build must degrade to "the whole deck"
        rather than take Setup down with it.
        """
        try:
            return cls(raw) if raw else cls.everything()
        except Exception as exc:  # noqa: BLE001 — a stored shape we cannot read is not a crash
            logger.warning("deck_slides: unreadable stored selection (%s) — building it all", exc)
            return cls.everything()

    def as_store(self) -> Dict[str, list]:
        """The JSON-safe form the browser store and the selection carry."""
        return {axis: list(idxs) for axis, idxs in self.excluded}

    # ── reading one ──

    def includes(self, axis: str, index: int) -> bool:
        """Whether this slide is in the deck."""
        return int(index) not in self.hidden(axis)

    def hidden(self, axis: str) -> Tuple[int, ...]:
        """The slide indices of ``axis`` to drop — what a :class:`SubDeck` carries."""
        return next((idxs for name, idxs in self.excluded if name == axis), ())

    def kept(self, axis: str) -> Tuple[SlideEntry, ...]:
        """``axis``'s slides that survive this selection, in deck order."""
        return tuple(e for e in catalog(axis) if self.includes(axis, e.index))

    def wants(self, axis: str) -> bool:
        """Whether ``axis`` is built at all.

        An axis whose slides are ALL unticked is not a shorter sub-deck, it is no sub-deck:
        the builder skips it, and a product/country axis skipped that way costs none of its
        per-entity blocks. This is what replaces the old scope choice — "Overall only" is
        now "untick the product and country pages", and it means the same thing to the
        builder because it is read in the same place.

        An axis whose template cannot be read answers False: there are no slides to build.
        """
        entries = catalog(axis)
        return bool(entries) and any(self.includes(axis, e.index) for e in entries)

    def axes(self, registered: Iterable[str] = DECK_AXES) -> Tuple[str, ...]:
        """The axes to assemble, in deck order — registered, and with slides left."""
        order = {axis: i for i, axis in enumerate(DECK_AXES)}
        wanted = [a for a in registered if self.wants(a)]
        return tuple(sorted(wanted, key=lambda a: order.get(a, len(order))))

    @property
    def empty(self) -> bool:
        """True when nothing has been excluded — the whole deck."""
        return not self.excluded


def _normalise(raw: Any) -> Tuple[Tuple[str, Tuple[int, ...]], ...]:
    """``((axis, (index…)), …)`` — sorted, de-duplicated, integers only, empty axes dropped.

    Accepts either shape it can be handed: the ``{axis: [index…]}`` a store holds, or the
    pairs a previous instance normalised to.
    """
    items = (raw or {}).items() if isinstance(raw, Mapping) else (raw or ())
    out: Dict[str, Tuple[int, ...]] = {}
    for axis, values in items:
        idxs = sorted({int(v) for v in (values or ()) if _is_index(v)})
        if idxs:
            out[str(axis)] = tuple(idxs)
    return tuple(sorted(out.items()))


def _is_index(value: Any) -> bool:
    try:
        return int(value) >= 0
    except (TypeError, ValueError):
        return False


def from_selection(selection: Optional[Mapping[str, Any]]) -> DeckSlides:
    """The slide selection a Setup selection carries (``selection["slides"]``).

    One place reads that key, so what a build assembles and what Setup previewed cannot
    drift into two readings of the same dictionary.
    """
    return DeckSlides.from_store((selection or {}).get("slides"))
