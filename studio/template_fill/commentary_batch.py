"""Write a whole sub-deck's commentary in one call, verify it in one more.

The per-column writer (:func:`studio.template_fill.commentary.write_column`) makes two model
calls for every textbox on a slide: an author call and a verifier call. A six-product,
one-country Entire QBR has 27 commentary fields, so it made about 54 of them — and that
arithmetic, not the analytics and not the rendering, is what a two-hour build was made of.

Nothing about those 27 calls needed to be 27 calls. Every column on a sub-deck argues from
the SAME evidence pack and under the SAME voice rules; only the brief, the question set and
the bullet count differ. So a section is written as a section:

    group the deck's pending columns by (sub-deck, evidence pack)
        -> one AUTHOR call per section        (all its fields, one answer)
        -> deterministic number checking      (free, per bullet, first)
        -> one VERIFIER call per section      (every surviving bullet, one verdict list)
        -> one REPAIR call per section        (only the fields the gates emptied)
        -> the accepted text, back on the role it was composed for

Eight sections instead of 27 columns, and roughly 9 to 16 calls instead of 54. Sections are
independent, so they still run concurrently (:mod:`studio.parallel`) — batching reduces the
number of round trips, parallelism overlaps the ones that remain, and they are different
savings that multiply.

**What has not changed.** Every bullet still cites the facts behind it, still has its figures
checked against those facts before any model reads it, and still clears
:func:`studio.template_fill.commentary.accept_column` for shape and reading. A batched column
is held to the identical bar; if it were not, "batched" would quietly mean "cheaper because
it checks less".

**Order.** Results are written back by ROLE, never by position or completion, so which
section a model answered first cannot change a deck.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from logger import get_logger

logger = get_logger(__name__)

#: Bumped when the prompt below changes in a way that should invalidate cached commentary.
#: Read by :mod:`studio.template_fill.commentary_cache` — a better prompt must not be
#: shadowed by yesterday's answer.
PROMPT_VERSION = "section-v2"

#: How many repair rounds a section gets. One: a field the author and one repair both failed
#: to write acceptably is not going to be written on a third identical request, and the
#: budget is better spent failing fast with an actionable message.
MAX_REPAIRS = 1


# ── what one batched call is asked for ───────────────────────────────────────


@dataclass(frozen=True)
class Column:
    """One commentary field inside a section: where it goes, and what it is for."""

    field_id: str                    # stable within the section; what the model echoes back
    roles: Tuple[str, ...]           # every value-set key this column's text is written to
    topic: str
    node: str
    bullets: int                     # how many sentences the column wants
    draft: Tuple[str, ...] = ()      # the rule composers' answer — fallback, and (in
    #                                  ``auto`` mode) the claim selection shown to the model

    @property
    def draft_text(self) -> str:
        return "\n".join(self.draft)


@dataclass(frozen=True)
class Section:
    """One sub-deck's worth of columns, written from one evidence pack in one call."""

    label: str
    subject: str
    style: str
    facts: Mapping[str, Any] = field(default_factory=dict, compare=False)
    columns: Tuple[Column, ...] = ()
    #: Which value set this section's text belongs to — how a result finds its way home.
    value_set: int = 0

    @property
    def field_ids(self) -> Tuple[str, ...]:
        return tuple(c.field_id for c in self.columns)


# ── grouping the deck's pending columns into sections ────────────────────────


def group_sections(value_sets: Sequence[Mapping[str, Any]]) -> List[Section]:
    """The deck's :class:`~studio.template_fill.rewrites.PendingRewrite` columns, batched.

    Grouped by ``(value set, the evidence it renders to)``. The value set is the sub-deck;
    the evidence is keyed by a digest of the rendered :class:`EvidencePack`, which is what
    the model is actually shown. Keying on the facts dict's IDENTITY instead was nearly
    right and cost a call per sub-deck: the two prose providers each build their own facts
    for the same scope, so a page carrying both a commentary column and a feedback panel
    produced two groups holding the same book and asked the same evidence twice.

    Columns are de-duplicated by pending identity on the way in. ``commentary.values``
    answers one question per topic and puts that one answer in every box asking it, so a
    topic on two pages arrives as one object under two roles — and the per-column writer
    used to write it twice and pay for it twice.
    """
    from studio.template_fill import rewrites

    # One pack per distinct facts OBJECT, so grouping never builds the same pack twice.
    # Local to this call rather than a module global: it is a scratch pad for one deck, and
    # an ``id`` key only means anything while the objects behind it are alive.
    keys: Dict[int, str] = {}
    sections: List[Section] = []
    for index, values in enumerate(value_sets):
        groups: Dict[str, List[Tuple[str, Any]]] = {}
        for role, pending in rewrites.pending_items(values):
            groups.setdefault(_evidence_key(pending.facts, keys), []).append((role, pending))
        for gi, items in enumerate(groups.values()):
            columns = _columns_from(items)
            if not columns:
                continue
            first = items[0][1]
            sections.append(Section(
                label=f"set{index}.{gi}", subject=first.subject,
                style=first.style or "balanced", facts=first.facts or {}, columns=columns,
                value_set=index,
            ))
    return sections


def _evidence_key(facts, keys: Dict[int, str]) -> str:
    """A digest of the evidence these facts render to — the grouping key.

    Two columns with the same digest see byte-identical evidence in their prompt, which is
    the only thing that has to be true for one call to answer both. ``keys`` memoises the
    pack per facts object for the caller's own run.
    """
    from studio.template_fill import commentary_cache as cache
    from studio.template_fill import commentary_evidence as E

    marker = id(facts)
    if marker not in keys:
        try:
            pack = E.build_pack(dict(facts or {}))
            keys[marker] = cache.evidence_digest(pack.rendered_values())
        except Exception as exc:  # noqa: BLE001 — a grouping key must never break a build
            logger.warning("commentary_batch: could not read evidence (%s)", exc)
            keys[marker] = f"unreadable-{marker}"
    return keys[marker]


def _columns_from(items: Sequence[Tuple[str, Any]]) -> Tuple[Column, ...]:
    """``(role, pending)`` pairs as columns, one per distinct pending, roles folded in."""
    by_pending: Dict[int, Tuple[Any, List[str]]] = {}
    for role, pending in items:
        by_pending.setdefault(id(pending), (pending, []))[1].append(role)
    out: List[Column] = []
    for i, (pending, roles) in enumerate(by_pending.values()):
        draft = tuple(ln for ln in pending.draft.splitlines() if ln.strip())
        if not draft:
            continue
        out.append(Column(field_id=f"{pending.topic or 'column'}.{i}", roles=tuple(roles),
                          topic=pending.topic, node=pending.node,
                          bullets=len(draft), draft=draft))
    return tuple(out)


# ── the prompt ───────────────────────────────────────────────────────────────


def _column_block(column: Column, *, show_draft: bool) -> str:
    """One column's ask, inside the section request."""
    from studio.template_fill import commentary as C

    lines = [
        f"--- FIELD {column.field_id} ---",
        C.column_rules(column.topic, column.bullets),
        "LEAD FROM these fact families: " + ", ".join(C.evidence_focus(column.topic))
        if C.evidence_focus(column.topic) else "",
    ]
    if show_draft and column.draft:
        lines += ["A DETERMINISTIC DRAFT of this field, for the claims it selected and their "
                  "priority order. You are not editing it — write the field properly from "
                  "the evidence:",
                  *(f"- {line}" for line in column.draft)]
    return "\n".join(part for part in lines if part)


def section_payload(section: Section, pack, glossary_brief: str, *,
                    show_draft: bool = True) -> str:
    """The user message: the evidence once, the definitions once, then each field's ask."""
    blocks = [f"CARRIER: {section.subject}", "",
              "EVIDENCE — the only facts you may use across every field below. Every "
              "figure you write must appear here, and every line must cite the fact ids it "
              "rests on:",
              pack.as_brief()]
    if glossary_brief:
        blocks += ["",
                   "ICG DEFINITIONS — what each term means, how this system computes "
                   "it, and the NEVER it carries. The NEVER lines are bans, not advice:",
                   glossary_brief]
    blocks += ["", f"Write {len(section.columns)} field(s). Return one entry per field, with "
                   "its field_id copied exactly. Read every field's brief before writing any "
                   "of them: they are read on the SAME slide deck by the same people, so no "
                   "two fields may make the same point in different words. When one fact "
                   "could serve two fields, give it to the field whose brief owns it and "
                   "make the other earn its place on something else.", ""]
    blocks += [_column_block(c, show_draft=show_draft) for c in section.columns]
    return "\n".join(blocks)


# ── writing one section ──────────────────────────────────────────────────────


def _pack_for(section: Section):
    """This section's evidence pack, or ``None`` when there is nothing citable."""
    from studio.template_fill import commentary_evidence as E

    pack = E.build_pack(dict(section.facts or {}))
    return pack if pack.items else None


def _glossary_brief(pack) -> str:
    """The ICG definitions for the terms this section's evidence uses."""
    try:
        from core.definitions import get_glossary

        return get_glossary().brief(pack.terms())
    except Exception as exc:  # noqa: BLE001 — definitions sharpen prose, they do not gate it
        logger.warning("commentary_batch: glossary unavailable (%s)", exc)
        return ""


def _author(section: Section, pack, glossary_brief: str, *, columns=None):
    """One author call over ``columns`` (default: the whole section). Returns the model's answer."""
    from studio.ai import client
    from studio.ai.models import CommentarySections
    from studio.commentary_mode import show_draft_to_author
    from studio.template_fill import commentary as C

    wanted = tuple(columns if columns is not None else section.columns)
    ask = Section(section.label, section.subject, section.style, section.facts, wanted)
    return client.structured(
        CommentarySections,
        C.deck_voice(section.style, section.subject),
        section_payload(ask, pack, glossary_brief, show_draft=show_draft_to_author()),
        tier=C._COMMENTARY_TIER, node=f"section-{section.label}",
        phase="author", fields=ask.field_ids,
    )


def _judged_by_field(answer, columns: Sequence[Column]) -> Dict[str, List[Any]]:
    """The model's answer as ``{field_id: [Judged]}``, keyed back to the fields asked for.

    An entry naming a field that was not asked for is dropped rather than guessed at: a
    model that invents a field id has not answered the question, and mapping it onto a
    column by position is how one page's commentary lands on another.
    """
    from studio.template_fill import commentary_verify as V

    wanted = {c.field_id for c in columns}
    out: Dict[str, List[Any]] = {}
    for entry in getattr(answer, "sections", None) or ():
        field_id = (entry.field_id or "").strip()
        if field_id not in wanted:
            logger.info("commentary_batch: ignoring unrequested field %r", field_id)
            continue
        bullets = [V.Judged(text=(b.text or "").strip(), fact_ids=tuple(b.fact_ids or ()))
                   for b in (entry.bullets or ()) if (b.text or "").strip()]
        action = (entry.action or "").strip()
        if action and _wants_action(field_id, columns):
            # The action IS the last line of an imperative column — the brief for
            # ``key_messages`` and ``priorities`` says to end on the ask. Landing it in its
            # own schema field and then dropping it would be asking for work and binning it.
            bullets.append(V.Judged(text=action, fact_ids=()))
        out[field_id] = bullets
    return out


def _risk_flags(answer, columns: Sequence[Column]) -> Dict[str, str]:
    """``{field_id: risk_flag}`` for the fields that raised one.

    ``none`` is dropped, so what comes back is only what somebody would want to read. The
    flag never reaches a slide — the templates have no slot for it, and inventing one would
    put an unverified judgement on the page — but it is the model's own read of how much
    trouble a section describes, and that belongs in the audit line beside the authorship
    label rather than being asked for and then thrown away.
    """
    wanted = {c.field_id for c in columns}
    return {entry.field_id: (entry.risk_flag or "").strip().lower()
            for entry in getattr(answer, "sections", None) or ()
            if entry.field_id in wanted
            and (entry.risk_flag or "none").strip().lower() not in ("", "none")}


def _wants_action(field_id: str, columns: Sequence[Column]) -> bool:
    """True when this field's topic is one the deck allows to instruct."""
    from studio.template_fill.commentary import _IMPERATIVE_TOPICS

    topic = next((c.topic for c in columns if c.field_id == field_id), "")
    return topic in _IMPERATIVE_TOPICS


def _verify_section(by_field: Dict[str, List[Any]], pack, glossary_brief: str,
                    *, label: str) -> Dict[str, List[str]]:
    """Both verifiers over a whole section: numbers per bullet, then ONE claim call.

    The deterministic pass stays per bullet because it is free and exact. The model pass —
    the expensive one — sees every surviving bullet in the section at once and returns one
    verdict list, which is the same judgement it made per column and one call instead of
    however many columns there were.
    """
    from studio.template_fill import commentary_verify as V

    flat: List[Tuple[str, Any]] = [(fid, j) for fid, items in by_field.items() for j in items]
    if not flat:
        return {fid: [] for fid in by_field}

    numeric = V.check_numbers([j for _, j in flat], pack)
    numeric.log(f"section-{label}")
    survivors = [(fid, j) for (fid, _), j in zip(flat, numeric.judged) if j.kept]
    if not survivors:
        return {fid: [] for fid in by_field}

    claims = V.check_claims([j for _, j in survivors], pack, glossary_brief=glossary_brief,
                            node=f"section-{label}")
    claims.log(f"section-{label}")
    kept: Dict[str, List[str]] = {fid: [] for fid in by_field}
    for (fid, _), verdict in zip(survivors, claims.judged):
        if verdict.kept:
            kept[fid].append(verdict.text)
    return kept


def _accepted(kept: Mapping[str, Sequence[str]], columns: Sequence[Column],
              *, subject: str = "") -> Tuple[Dict[str, str], List[Column]]:
    """``({field_id: text}, [columns that did not survive])`` after the shape/reading gate."""
    from studio.template_fill import commentary as C

    text: Dict[str, str] = {}
    failed: List[Column] = []
    for column in columns:
        accepted = C.accept_column(kept.get(column.field_id, ()), wanted=column.bullets,
                                   node=column.node, subject=subject)
        if accepted:
            text[column.field_id] = accepted
        else:
            failed.append(column)
    return text, failed


def cache_key(section: Section, column: Column, pack):
    """The key one column's written text is stored under. See :mod:`commentary_cache`."""
    from studio.template_fill import commentary as C
    from studio.template_fill import commentary_cache as cache

    return cache.CacheKey(
        subject=section.subject, topic=column.topic, bullets=column.bullets,
        evidence=cache.evidence_digest(pack.rendered_values()),
        brief=C.column_rules(column.topic, column.bullets),
        style=section.style, prompt_version=PROMPT_VERSION, tier=C._COMMENTARY_TIER,
        deployment=_deployment(), draft=cache.evidence_digest(column.draft),
    )


def _deployment() -> str:
    """Which model would write this column — part of the key, so a tier change invalidates."""
    from studio.ai.client import deployment_for
    from studio.template_fill import commentary as C

    return deployment_for(C._COMMENTARY_TIER)


def _from_cache(section: Section, pack) -> Tuple[Dict[str, str], List[Column]]:
    """``({field_id: text}, [columns still to write])`` — the cache read, done once.

    A section whose columns are ALL cached makes no model call at all, which is the case
    that matters: an export, a formatting change, or a rebuild after a temp sweep asks the
    same questions of the same evidence and should not pay for the answers twice.
    """
    from studio import telemetry
    from studio.template_fill import commentary_cache as cache

    hits: Dict[str, str] = {}
    misses: List[Column] = []
    for column in section.columns:
        text = cache.get(cache_key(section, column, pack))
        if text:
            hits[column.field_id] = text
        else:
            misses.append(column)
    telemetry.count("commentary_cache_hits", len(hits))
    telemetry.count("commentary_cache_misses", len(misses))
    return hits, misses


def _to_cache(section: Section, pack, written: Mapping[str, str]) -> None:
    """Store what THIS run wrote, so the next run does not write it again.

    Only the newly written columns: re-storing a cache hit would refresh its TTL on every
    export and let a section live for ever without its evidence ever being re-read.
    """
    from studio.template_fill import commentary_cache as cache

    for column in section.columns:
        text = written.get(column.field_id)
        if text:
            cache.put(cache_key(section, column, pack), text)


def write_section(section: Section) -> Dict[str, str]:
    """One section's columns, written and verified — ``{role: text}``.

    Every column that cannot be written by a model keeps its deterministic draft in ``auto``
    mode and raises in ``ai_required`` (:mod:`studio.commentary_mode`) — the decision lives
    there, so this function never has to know which mode it is in.
    """
    from studio import telemetry
    from studio.commentary_mode import refuse

    pack = _pack_for(section)
    if pack is None:                       # nothing citable — a model would be inventing
        refuse(f"section {section.label} has no citable evidence", retryable=False)
        return _drafts(section.columns)

    text, pending = _from_cache(section, pack)
    if not pending:                        # wholly cached — not one model call
        logger.info("commentary_batch: section %s served entirely from cache (%d field(s))",
                    section.label, len(text))
        return _text_by_role(section.columns, text)

    glossary_brief = _glossary_brief(pack)
    answer = _author(section, pack, glossary_brief, columns=pending)
    if answer is None:
        refuse(f"the author returned nothing for section {section.label}", retryable=True)
        return _text_by_role(section.columns, text)

    kept = _verify_section(_judged_by_field(answer, pending), pack, glossary_brief,
                           label=section.label)
    written, failed = _accepted(kept, pending, subject=section.subject)
    if failed:
        repaired = _repair(section, pack, glossary_brief, failed)
        written.update(repaired)
        failed = [c for c in failed if c.field_id not in repaired]
    _to_cache(section, pack, written)
    text.update(written)
    telemetry.count("commentary_fields_written", len(text))
    _log_section(section, text, failed, risks=_risk_flags(answer, pending))
    if failed:
        refuse(f"{len(failed)} field(s) in section {section.label} could not be written",
               retryable=True,
               detail=", ".join(c.node for c in failed))
    return _text_by_role(section.columns, text)


def _repair(section: Section, pack, glossary_brief: str,
            failed: Sequence[Column]) -> Dict[str, str]:
    """One more call for the failed fields ONLY — never the whole section, never the deck.

    Re-running the section would throw away the fields that passed and pay to write them
    again, and a second answer for a field already accepted is a second chance to make it
    worse. So repair asks for exactly what is missing.
    """
    from studio import telemetry

    if not failed:
        return {}
    for _ in range(MAX_REPAIRS):
        telemetry.count("commentary_repairs", len(failed))
        answer = _author(section, pack, glossary_brief, columns=failed)
        if answer is None:
            return {}
        kept = _verify_section(_judged_by_field(answer, failed), pack, glossary_brief,
                               label=f"{section.label}-repair")
        text, still_failing = _accepted(kept, failed, subject=section.subject)
        if text or not still_failing:
            return text
        failed = still_failing
    return {}


def _drafts(columns: Sequence[Column]) -> Dict[str, str]:
    """Every column as its deterministic draft, keyed by role — the ``auto`` fallback."""
    return {role: column.draft_text for column in columns for role in column.roles}


def _text_by_role(columns: Sequence[Column], text: Mapping[str, str]) -> Dict[str, str]:
    """Written text where there is any, the draft where there is not — keyed by role."""
    return {role: text.get(column.field_id) or column.draft_text
            for column in columns for role in column.roles}


def _log_section(section: Section, text: Mapping[str, str], failed: Sequence[Column],
                 *, risks: Optional[Mapping[str, str]] = None) -> None:
    """The audit line the plan asks for: who wrote this section, and how it was judged."""
    from studio import telemetry
    from studio.commentary_mode import authorship

    flagged = ", ".join(f"{fid}={flag}" for fid, flag in sorted((risks or {}).items()))
    logger.info("commentary_batch: section %s subject=%r fields=%d written=%d failed=%d "
                "authorship=%s prompt=%s%s",
                section.label, section.subject, len(section.columns), len(text), len(failed),
                authorship(bool(text)), PROMPT_VERSION,
                f" risk[{flagged}]" if flagged else "")
    for flag in (risks or {}).values():
        telemetry.count(f"commentary_risk_{flag}")


# ── the whole deck ───────────────────────────────────────────────────────────


def _all_drafts(value_sets: Sequence[Mapping[str, Any]]) -> List[Dict[str, str]]:
    """Every pending column as its deterministic draft — the no-model answer."""
    from studio.template_fill import rewrites

    return [{role: pending.draft for role, pending in rewrites.pending_items(values)}
            for values in value_sets]


def write_deck(value_sets: Sequence[Mapping[str, Any]]) -> List[Dict[str, str]]:
    """Every section in the deck, written concurrently — one ``{role: text}`` per value set.

    The unit of concurrency is the SECTION rather than the column, which is the point: a
    section is one round trip that used to be six, and the sections that remain overlap.
    Results are placed by ``value_set`` and by role, so completion order cannot reach the
    deck.
    """
    from studio import telemetry
    from studio.ai import client
    from studio.commentary_mode import refuse
    from studio.parallel import gather_list

    out: List[Dict[str, str]] = [{} for _ in value_sets]
    if not client.llm_available():
        # Asked and answered before any work: grouping builds an evidence pack per book and
        # the cache reads a file per column, and both are pure waste on a run that was never
        # going to call a model. ``ai_required`` still refuses here rather than shipping.
        refuse("no model client is available to write commentary", retryable=True)
        return _all_drafts(value_sets)

    sections = group_sections(value_sets)
    if not sections:
        return out
    logger.info("commentary_batch: %d section(s), %d field(s) across %d value set(s)",
                len(sections), sum(len(s.columns) for s in sections), len(value_sets))
    with telemetry.phase("commentary"):
        written = gather_list([lambda s=section: write_section(s) for section in sections])
    for section, texts in zip(sections, written):
        out[section.value_set].update(texts)
    return out
