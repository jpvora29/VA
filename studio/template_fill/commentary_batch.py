"""Write a whole BOOK's commentary in one call, verify it in one more.

The per-column writer (:func:`studio.template_fill.commentary.write_column`) makes two model
calls for every textbox on a slide: an author call and a verifier call. A six-product,
one-country Entire QBR has 27 commentary fields, so it made about 54 of them — and that
arithmetic, not the analytics and not the rendering, is what a two-hour build was made of.

Nothing about those 27 calls needed to be 27 calls. Every column on a sub-deck argues from
the SAME evidence pack and under the SAME voice rules; only the brief, the question set and
the bullet count differ. So a section is written as a section:

    group the deck's pending columns by the evidence pack they argue from
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

**The grouping key is the evidence, not the sub-deck.** Two sub-decks whose packs render
byte-identically are describing one book — a single-country run's overall block and its
country block do exactly that — and writing them as two concurrent calls is what let one
finding reach both pages with nothing able to see it. One book, one call, one editorial
plan (:mod:`studio.template_fill.editorial`) across every page of it.

**Order.** Results are written back by TARGET — the value set and the role — never by
position or completion, so which section a model answered first cannot change a deck.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from logger import get_logger

logger = get_logger(__name__)

#: Bumped when the prompt below changes in a way that should invalidate cached commentary.
#: Read by :mod:`studio.template_fill.commentary_cache` — a better prompt must not be
#: shadowed by yesterday's answer.
PROMPT_VERSION = "icg-argument-v6"

#: How many repair rounds a section gets.
#:
#: This was one, on the reasoning that a third identical request would not do better than
#: the first two. That reasoning held while the repair WAS identical. It now carries the
#: verdicts that emptied the field (see :class:`Failure`), so a second round is a second
#: piece of information rather than a second roll of the same dice — and in
#: ``COMMENTARY_MODE=ai_required`` the alternative to one more call on one field is a
#: refused deck. Repairs only ever run for fields that failed, so the cost is bounded by
#: how rare that is.
MAX_REPAIRS = 2


# ── what one batched call is asked for ───────────────────────────────────────


@dataclass(frozen=True)
class Target:
    """Where one written column lands: which value set, and the role inside it.

    The value set has to travel WITH the role now that a section can span sub-decks. A
    role is only unique inside its own set — ``note:2:34:0`` names slide 2, shape 34 of
    whichever template that sub-deck was built from, and two sub-decks built from
    templates that share a page carry the identical string for two different boxes.
    """

    value_set: int
    role: str


@dataclass(frozen=True)
class Column:
    """One commentary field inside a section: where it goes, and what it is for."""

    field_id: str                    # stable within the section; what the model echoes back
    targets: Tuple[Target, ...]      # every place this column's text is written to
    topic: str
    node: str
    bullets: int                     # maximum number of independent findings
    draft: Tuple[str, ...] = ()      # explicit deterministic preview/fallback only

    @property
    def draft_text(self) -> str:
        return "\n".join(self.draft)


@dataclass(frozen=True)
class Failure:
    """One column the gates emptied, and the reasons they gave for emptying it.

    The reasons travel twice. Into the REPAIR call, so the second attempt is told what was
    wrong with the first instead of re-rolling the same dice — an identical retry of a
    field a model has already failed is a coin flip, and one that costs a call. And into
    the strict-mode REFUSAL, so a build that stops says why it stopped rather than only
    which field it stopped on.
    """

    column: "Column"
    reasons: Tuple[str, ...] = ()
    #: The lines that DID clear every check. A field is usually rejected for being one
    #: line short, not for being worthless, so these are the ground it already won —
    #: repair tops them up rather than rewriting over them, and the salvage pass can
    #: ship them as they stand.
    kept_lines: Tuple[str, ...] = ()

    @property
    def missing(self) -> int:
        """How many more lines this field needs before it can ship."""
        return max(self.column.bullets - len(self.kept_lines), 1)

    def brief(self) -> str:
        """One line naming the field and, when known, what happened to it."""
        if not self.reasons:
            return self.column.node
        return f"{self.column.node}: {'; '.join(self.reasons)}"


@dataclass(frozen=True)
class Section:
    """One BOOK's worth of columns, written from one evidence pack in one call.

    A book, not a sub-deck. A section used to be a sub-deck, and that boundary was wrong
    in the one case where it mattered: on a single-country run the overall block and the
    country block describe the SAME book down to the last figure, so the two pages both
    reached for the peer gap and, being written by two concurrent calls, nothing could
    see that both had. Identical evidence is the honest definition of one book — two
    sub-decks whose packs render byte-identically are reporting the same thing — and once
    they are one section the editorial plan allocates their findings between them and the
    gate holds them to it.
    """

    label: str
    subject: str
    style: str
    facts: Mapping[str, Any] = field(default_factory=dict, compare=False)
    columns: Tuple[Column, ...] = ()

    @property
    def field_ids(self) -> Tuple[str, ...]:
        return tuple(c.field_id for c in self.columns)

    @property
    def value_sets(self) -> Tuple[int, ...]:
        """The sub-decks this section's columns land in, in order — for the log line."""
        return tuple(dict.fromkeys(t.value_set for c in self.columns for t in c.targets))


# ── grouping the deck's pending columns into sections ────────────────────────


def group_sections(value_sets: Sequence[Mapping[str, Any]]) -> List[Section]:
    """The deck's :class:`~studio.template_fill.rewrites.PendingRewrite` columns, batched.

    Grouped by THE EVIDENCE ALONE — a digest of the rendered :class:`EvidencePack`, which
    is what the model is actually shown. Keying on the facts dict's IDENTITY instead was
    nearly right and cost a call per sub-deck: the two prose providers each build their own
    facts for the same scope, so a page carrying both a commentary column and a feedback
    panel produced two groups holding the same book and asked the same evidence twice.

    **The value set is deliberately NOT part of the key.** It used to be, which made a
    section a sub-deck, and that is how the same finding reached two pages of a shipped
    deck: on a single-country run the overall block's ranking page and the country block's
    SWOT page describe one book, they were written by two concurrent calls, and neither
    could see what the other had said. Two sub-decks only land in one group when their
    packs render byte-identically, which does not happen unless they really are reporting
    the same book — a product or country whose figures differ at all keys differently and
    is grouped on its own, exactly as before.

    Groups come out in first-appearance order and their columns in deck order, so the
    editorial plan (which reads "earlier in the deck" off that order) still sees the deck
    the way a reader does.

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
    groups: Dict[str, List[Tuple[int, str, Any]]] = {}
    for index, values in enumerate(value_sets):
        for role, pending in rewrites.pending_items(values):
            groups.setdefault(_evidence_key(pending.facts, keys), []).append(
                (index, role, pending))

    sections: List[Section] = []
    for gi, items in enumerate(groups.values()):
        columns = _columns_from(items)
        if not columns:
            continue
        first = items[0][2]
        sections.append(Section(
            label=f"book{gi}", subject=first.subject, style=first.style or "balanced",
            facts=first.facts or {}, columns=columns,
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
            keys[marker] = cache.evidence_digest((pack.as_brief(),))
        except Exception as exc:  # noqa: BLE001 — a grouping key must never break a build
            logger.warning("commentary_batch: could not read evidence (%s)", exc)
            keys[marker] = f"unreadable-{marker}"
    return keys[marker]


def _columns_from(items: Sequence[Tuple[int, str, Any]]) -> Tuple[Column, ...]:
    """``(value set, role, pending)`` triples as columns, one per distinct pending.

    Folding is by pending IDENTITY, which is what keeps "one answer in several boxes"
    one column — and, just as deliberately, keeps two sub-decks' own copies of the same
    question TWO columns even when they are now in one section. They are two boxes on two
    pages, a reader sees both, and the whole point of merging them into one section is
    that the plan can give them different findings to make.
    """
    by_pending: Dict[int, Tuple[Any, List[Target]]] = {}
    for value_set, role, pending in items:
        by_pending.setdefault(id(pending), (pending, []))[1].append(Target(value_set, role))
    out: List[Column] = []
    for i, (pending, targets) in enumerate(by_pending.values()):
        draft = tuple(ln for ln in pending.draft.splitlines() if ln.strip())
        if not draft:
            continue
        out.append(Column(field_id=f"{pending.topic or 'column'}.{i}", targets=tuple(targets),
                          topic=pending.topic, node=pending.node,
                          bullets=len(draft), draft=draft))
    return tuple(out)


# ── the prompt ───────────────────────────────────────────────────────────────


def _column_block(column: Column, *, show_draft: bool, rejected: Sequence[str] = (),
                  keep: Sequence[str] = (), editorial_brief: str = "") -> str:
    """One column's ask, inside the section request.

    ``keep`` turns the ask into a TOP-UP: the lines already verified are shown as final
    and the model writes only what is missing. Without it a repair re-asks for the whole
    field, which puts lines that already passed every check back at risk of a worse
    second answer.

    ``editorial_brief`` is this field's job in the deck's argument
    (:mod:`studio.template_fill.editorial`) — the findings it is the home for, and the
    ones another field on the page owns. It sits directly under the topic brief because
    the two are read together: the brief says what the column is FOR, and this says which
    of the facts in front of it are its to spend.
    """
    from studio.template_fill import commentary as C

    remaining = max(column.bullets - len(keep), 1)
    lines = [
        f"--- FIELD {column.field_id} ---",
        C.top_up_rules(column.topic, remaining) if keep
        else C.column_rules(column.topic, column.bullets),
        editorial_brief,
        "LEAD FROM these fact families: " + ", ".join(C.evidence_focus(column.topic))
        if C.evidence_focus(column.topic) else "",
    ]
    if keep:
        lines += [f"ALREADY WRITTEN AND VERIFIED for this field — these {len(keep)} line(s) "
                  "are final and will be kept. Write the missing line(s) to follow them, "
                  "and do not make a point any of them already makes:",
                  *(f"- {line}" for line in keep)]
    if rejected:
        # What the checks said about the last answer for this field. Stated as the
        # verdict, not as prose to edit: the model writes the field again from the
        # evidence, avoiding what the checks rejected.
        lines += ["YOUR PREVIOUS ANSWER FOR THIS FIELD WAS REJECTED. Write it again and "
                  "do not repeat these problems:",
                  *(f"- {reason}" for reason in rejected)]
    if show_draft and column.draft:
        lines += ["A DETERMINISTIC DRAFT of this field, for the claims it selected and their "
                  "priority order. You are not editing it — write the field properly from "
                  "the evidence:",
                  *(f"- {line}" for line in column.draft)]
    return "\n".join(part for part in lines if part)


def section_payload(section: Section, pack, glossary_brief: str, *,
                    show_draft: bool = True,
                    rejected: Optional[Mapping[str, Sequence[str]]] = None,
                    keep: Optional[Mapping[str, Sequence[str]]] = None,
                    plan=None) -> str:
    """The user message: the evidence once, the definitions once, then each field's ask."""
    from studio.template_fill import editorial, commentary_findings

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
    plan = plan if plan is not None else editorial.EMPTY_PLAN
    blocks += [_column_block(c, show_draft=show_draft,
                             rejected=(rejected or {}).get(c.field_id, ()),
                             keep=(keep or {}).get(c.field_id, ()),
                             editorial_brief=commentary_findings.brief(pack, c.topic)
                             + "\nAvoid repeating another field's finding; section relevance takes priority over variety.")
               for c in section.columns]
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


def _author(section: Section, pack, glossary_brief: str, *, columns=None,
            rejected: Optional[Mapping[str, Sequence[str]]] = None,
            keep: Optional[Mapping[str, Sequence[str]]] = None, plan=None,
            established: Optional[Mapping[str, str]] = None):
    """One author call over ``columns`` (default: the whole section). Returns the model's answer."""
    from studio.ai import client
    from studio.ai.models import CommentarySections
    from studio.commentary_mode import show_draft_to_author
    from studio.template_fill import commentary as C

    wanted = tuple(columns if columns is not None else section.columns)
    ask = Section(section.label, section.subject, section.style, section.facts, wanted)
    payload = section_payload(ask, pack, glossary_brief, show_draft=show_draft_to_author(),
                              rejected=rejected, keep=keep, plan=plan)
    if established:
        payload += "\nALREADY ACCEPTED IN OTHER FIELDS — do not repeat these findings:\n" + "\n".join(
            f"{fid}: {body}" for fid, body in established.items())
    return client.structured(
        CommentarySections,
        C.deck_voice(section.style, section.subject),
        payload,
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

    wanted = {c.field_id: c for c in columns}
    out: Dict[str, List[Any]] = {}
    for entry in getattr(answer, "sections", None) or ():
        field_id = (entry.field_id or "").strip()
        if field_id not in wanted:
            logger.info("commentary_batch: ignoring unrequested field %r", field_id)
            continue
        bullets = [V.Judged(text=(b.text or "").strip(), fact_ids=tuple(b.fact_ids or ()),
                            topic=wanted[field_id].topic)
                   for b in (entry.bullets or ()) if (b.text or "").strip()]
        action = (entry.action or "").strip()
        if action and _wants_action(field_id, columns):
            # The action IS the last line of an imperative column — the brief for
            # ``key_messages`` and ``priorities`` says to end on the ask. Landing it in its
            # own schema field and then dropping it would be asking for work and binning it.
            bullets.append(V.Judged(text=action, fact_ids=(), topic=wanted[field_id].topic))
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
                    *, label: str, plan=None,
                    ) -> Tuple[Dict[str, List[str]], Dict[str, List[str]]]:
    """Three gates over a whole section: numbers, then claims, then repetition.

    The deterministic number pass stays per bullet because it is free and exact. The model
    pass — the expensive one — sees every surviving bullet in the section at once and
    returns one verdict list, which is the same judgement it made per column and one call
    instead of however many columns there were.

    The repetition gate runs LAST, on what survived both verifiers
    (:func:`studio.template_fill.editorial.dedupe`). Last because a bullet dropped for an
    unsupported figure must not consume its topic on the way out — the field that would
    have been made to write about something else has then been made to write about
    something else by a hallucination. Its drops are reasons like any other, so a field
    emptied by it goes into the repair round and comes back on a point the page has not
    made.
    """
    from studio.template_fill import editorial
    from studio.template_fill import commentary_verify as V

    kept: Dict[str, List[str]] = {fid: [] for fid in by_field}
    dropped: Dict[str, List[str]] = {fid: [] for fid in by_field}
    flat: List[Tuple[str, Any]] = [(fid, j) for fid, items in by_field.items() for j in items]
    if not flat:
        return kept, dropped

    numeric = V.check_numbers([j for _, j in flat], pack)
    numeric.log(f"section-{label}")
    survivors: List[Tuple[str, Any]] = []
    for (fid, _), judged in zip(flat, numeric.judged):
        if judged.kept:
            survivors.append((fid, judged))
        else:
            dropped[fid].append(judged.reason or "unsupported figure")
    if not survivors:
        return kept, dropped

    claims = V.check_claims([j for _, j in survivors], pack, glossary_brief=glossary_brief,
                            node=f"section-{label}")
    claims.log(f"section-{label}")
    verified: List[Tuple[str, str, Tuple[str, ...]]] = []
    for (fid, judged), verdict in zip(survivors, claims.judged):
        if verdict.kept:
            verified.append((fid, verdict.text, tuple(judged.fact_ids or ())))
        else:
            dropped[fid].append(verdict.reason or "unsupported claim")

    unique, repeats = editorial.dedupe(verified, plan=plan or editorial.EMPTY_PLAN)
    for fid, lines in unique.items():
        kept.setdefault(fid, []).extend(lines)
    for repeat in repeats:
        dropped.setdefault(repeat.field_id, []).append(repeat.reason)
        logger.info("commentary_batch: section %s dropped a repeat in %s — %.70r",
                    label, repeat.field_id, repeat.text)
    return kept, dropped


def _accepted(kept: Mapping[str, Sequence[str]], columns: Sequence[Column],
              *, subject: str = "",
              dropped: Optional[Mapping[str, Sequence[str]]] = None,
              ) -> Tuple[Dict[str, str], List[Failure]]:
    """``({field_id: text}, [failures])`` after the shape/reading gate.

    A failure carries every reason the field lost its lines — the verifiers' drops as well
    as this gate's — because the two are read together: "one figure it could not cite, and
    that left it a line short" is the whole story, and either half alone is not.
    """
    from studio.template_fill import commentary as C

    text: Dict[str, str] = {}
    failed: List[Failure] = []
    for column in columns:
        verdict = C.judge_column(kept.get(column.field_id, ()), wanted=column.bullets,
                                 node=column.node, subject=subject)
        if verdict.text:
            text[column.field_id] = verdict.text
        else:
            reasons = tuple((dropped or {}).get(column.field_id, ())) + verdict.reasons
            failed.append(Failure(column, reasons or ("the model returned nothing for it",),
                                  kept_lines=verdict.lines))
    return text, failed


def cache_key(section: Section, column: Column, pack, plan=None):
    """The key one column's written text is stored under. See :mod:`commentary_cache`.

    The editorial brief is part of the key. A field that owned the peer gap yesterday and
    is asked to leave it to another field today is being asked a different question, and
    serving it yesterday's answer would put the repetition straight back on the page.
    """
    from studio.template_fill import commentary as C
    from studio.template_fill import commentary_cache as cache
    from studio.template_fill import editorial

    plan = plan if plan is not None else editorial.EMPTY_PLAN
    return cache.CacheKey(
        subject=section.subject, topic=column.topic, bullets=column.bullets,
        evidence=cache.evidence_digest((pack.as_brief(), _glossary_brief(pack))),
        brief=C.column_rules(column.topic, column.bullets) + plan.brief(column.field_id),
        style=section.style, prompt_version=PROMPT_VERSION, tier=C._COMMENTARY_TIER,
        deployment=_deployment(), draft=cache.evidence_digest(column.draft),
    )


def _deployment() -> str:
    """Which model would write this column — part of the key, so a tier change invalidates."""
    from studio.ai.client import deployment_for
    from studio.template_fill import commentary as C

    return deployment_for(C._COMMENTARY_TIER)


def _from_cache(section: Section, pack, plan=None) -> Tuple[Dict[str, str], List[Column]]:
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
        text = cache.get(cache_key(section, column, pack, plan))
        if text:
            hits[column.field_id] = text
        else:
            misses.append(column)
    telemetry.count("commentary_cache_hits", len(hits))
    telemetry.count("commentary_cache_misses", len(misses))
    return hits, misses


def _to_cache(section: Section, pack, written: Mapping[str, str], plan=None) -> None:
    """Store what THIS run wrote, so the next run does not write it again.

    Only the newly written columns: re-storing a cache hit would refresh its TTL on every
    export and let a section live for ever without its evidence ever being re-read.
    """
    from studio.template_fill import commentary_cache as cache

    for column in section.columns:
        text = written.get(column.field_id)
        if text:
            cache.put(cache_key(section, column, pack, plan), text)


def write_section(section: Section, plan=None) -> Dict[Target, str]:
    """One section's columns, written and verified — ``{target: text}``.

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

    text, pending = _from_cache(section, pack, plan)
    if not pending:                        # wholly cached — not one model call
        logger.info("commentary_batch: section %s served entirely from cache (%d field(s))",
                    section.label, len(text))
        return _placed(section.columns, text)

    glossary_brief = _glossary_brief(pack)
    answer = _author(section, pack, glossary_brief, columns=pending, plan=plan, established=text)
    if answer is None:
        refuse(f"the author returned nothing for section {section.label}", retryable=True)
        return _placed(section.columns, text)

    kept, dropped = _verify_section(_judged_by_field(answer, pending), pack, glossary_brief,
                                    label=section.label, plan=plan)
    kept = _exclude_established(kept, text, dropped)
    written, failed = _accepted(kept, pending, subject=section.subject, dropped=dropped)
    if failed:
        repaired, failed = _repair(section, pack, glossary_brief, failed, plan=plan,
                                   established={**text, **written})
        written.update(repaired)
    if failed:
        # Last resort, after every repair round: a verified line beats the draft.
        salvaged, failed = _salvage(failed, subject=section.subject, label=section.label)
        written.update(salvaged)
    _to_cache(section, pack, written, plan)
    text.update(written)
    telemetry.count("commentary_fields_written", len(text))
    _log_section(section, text, failed, risks=_risk_flags(answer, pending))
    _report_repeats(section, text)
    if failed:
        refuse(f"{len(failed)} field(s) in section {section.label} could not be written",
               retryable=True,
               detail="; ".join(f.brief() for f in failed))
    return _placed(section.columns, text)


def _report_repeats(section: Section, text: Mapping[str, str]) -> None:
    """Log any repetition still standing in this book's finished prose.

    The gate has already run and this is the safety net behind it — a bullet that cited
    nothing, or a finding the claim identity could not connect. Report-only, and scoped to
    the BOOK rather than the sub-deck, which is the scope
    :func:`studio.template_fill.commentary_qa.check` cannot reach: two pages of one book
    can sit in two sub-decks, and that is precisely where the repetition was found.
    """
    from studio.template_fill import commentary_qa

    nodes = {c.field_id: c.node for c in section.columns}
    try:
        issues = commentary_qa.check_book(
            {nodes.get(fid, fid): body for fid, body in text.items()})
    except Exception as exc:  # noqa: BLE001 — a report must never cost us the deck
        logger.warning("commentary_batch: repeat report failed for %s: %s",
                       section.label, exc)
        return
    commentary_qa.log_issues(issues, label=f"book {section.label}")


def _repair(section: Section, pack, glossary_brief: str, failed: Sequence[Failure],
            *, plan=None, established: Optional[Mapping[str, str]] = None
            ) -> Tuple[Dict[str, str], List[Failure]]:
    """Repair the failed fields ONLY — never the whole section, never the deck.

    Re-running the section would throw away the fields that passed and pay to write them
    again, and a second answer for a field already accepted is a second chance to make it
    worse. So repair asks for exactly what is missing — and it says what was wrong with the
    last answer, which is the difference between a repair and a re-roll.

    Two things this gets right that it used to get wrong.

    **Every round is used by every field that still needs one.** It used to return the
    moment ANY field succeeded (``if text or not still_failing: return text``), so three
    failing fields of which the first round fixed one left the other two with their second
    round unspent — and in ``ai_required`` that is a refused deck. Successes accumulate
    now, and the loop carries on with whatever is still short.

    **A field is topped up, not rewritten.** Each failure arrives carrying the lines it
    already won (:attr:`Failure.kept_lines`); those are shown to the model as final and it
    writes only what is missing. The kept lines are not re-verified — they already cleared
    both verifiers — so a retry meant to help a field can no longer cost it a good line.

    Returns the text it repaired and the failures that are still outstanding, so the
    caller sees the up-to-date survivors rather than the ones it passed in.
    """
    from studio import telemetry

    repaired: Dict[str, str] = {}
    outstanding = list(failed)
    for _ in range(MAX_REPAIRS):
        if not outstanding:
            break
        telemetry.count("commentary_repairs", len(outstanding))
        columns = [f.column for f in outstanding]
        keep = {f.column.field_id: f.kept_lines for f in outstanding if f.kept_lines}
        answer = _author(section, pack, glossary_brief, columns=columns,
                         rejected={f.column.field_id: f.reasons for f in outstanding},
                         keep=keep, plan=plan, established={**(established or {}), **repaired})
        if answer is None:
            break                      # keep whatever the earlier rounds repaired
        fresh, dropped = _verify_section(_judged_by_field(answer, columns), pack,
                                         glossary_brief, label=f"{section.label}-repair",
                                         plan=plan)
        fresh = _exclude_established(fresh, {**(established or {}), **repaired}, dropped)
        text, outstanding = _accepted(_merged(keep, fresh), columns,
                                      subject=section.subject, dropped=dropped)
        repaired.update(text)
    return repaired, outstanding


def _exclude_established(fresh, established, dropped):
    """A repair or partial cache miss cannot repeat a finding already accepted."""
    from studio.template_fill import editorial

    owners = {editorial.claim_key(line): fid for fid, body in established.items()
              for line in body.splitlines() if editorial.claim_key(line)}
    out = {}
    for fid, lines in fresh.items():
        out[fid] = []
        for line in lines:
            owner = owners.get(editorial.claim_key(line))
            if owner and owner != fid:
                dropped.setdefault(fid, []).append(f"finding already accepted in field {owner}; choose a distinct finding")
            else:
                out[fid].append(line)
    return out


def _merged(keep: Mapping[str, Sequence[str]],
            fresh: Mapping[str, Sequence[str]]) -> Dict[str, List[str]]:
    """Verified lines a field already had, then the new ones — in that order.

    Priority order is the kept lines' order, so a top-up lands after what it is topping
    up. A field the repair answer omitted entirely still keeps what it had, which is why
    this unions the keys rather than iterating either side alone.

    A repeated line is dropped. The top-up prompt tells the model the kept lines are final
    and not to restate them, but a model that echoes one back anyway would otherwise have
    its copy counted as the missing second bullet — and the field would ship the same
    sentence twice, which is worse than the short column this exists to avoid.
    """
    out: Dict[str, List[str]] = {}
    for fid in {*keep, *fresh}:
        lines = list(keep.get(fid, ()))
        seen = {_normalised(line) for line in lines}
        for line in fresh.get(fid, ()):
            if _normalised(line) in seen:
                logger.info("commentary_batch: dropping a repeated line in %s top-up", fid)
                continue
            seen.add(_normalised(line))
            lines.append(line)
        out[fid] = lines
    return out


def _normalised(line: str) -> str:
    """A line reduced to what makes it the same line — for the repeat check only."""
    return " ".join(str(line).split()).casefold().rstrip(".")


def _salvage(failed: Sequence[Failure], *, subject: str,
             label: str) -> Tuple[Dict[str, str], List[Failure]]:
    """Ship a SHORT column rather than lose it, once repair is out of rounds.

    A field rejected only for being a line short still holds lines that cleared every
    check there is. Refusing it means the slide gets deterministic prose instead — or, in
    ``ai_required``, no deck at all — which is a worse outcome than a field that makes one
    well-evidenced point. Where the evidence genuinely carries no second point, no number
    of further rounds will produce one.

    The gate is unchanged; only the floor moves (:data:`commentary.SALVAGE_FLOOR`), so a
    salvaged line has passed exactly what a normal one passed. The fill engine drops the
    surplus paragraph, so the slide shows one bullet rather than one bullet and a gap.
    """
    from studio import telemetry
    from studio.template_fill import commentary as C

    text: Dict[str, str] = {}
    outstanding: List[Failure] = []
    for failure in failed:
        verdict = C.judge_column(failure.kept_lines, wanted=failure.column.bullets,
                                 node=failure.column.node, subject=subject,
                                 floor=C.SALVAGE_FLOOR)
        if verdict.text:
            text[failure.column.field_id] = verdict.text
            telemetry.count("commentary_short_fields", 1)
            logger.info("commentary_batch: section %s shipping %s short — %d of %d "
                        "line(s), all verified", label, failure.column.node,
                        verdict.kept, failure.column.bullets)
        else:
            outstanding.append(failure)
    return text, outstanding


def _drafts(columns: Sequence[Column]) -> Dict[Target, str]:
    """Every column as its deterministic draft, keyed by target — the ``auto`` fallback."""
    return {target: column.draft_text for column in columns for target in column.targets}


def _placed(columns: Sequence[Column], text: Mapping[str, str]) -> Dict[Target, str]:
    """Written text where there is any, the draft where there is not — keyed by target."""
    return {target: text.get(column.field_id) or column.draft_text
            for column in columns for target in column.targets}


def _log_section(section: Section, text: Mapping[str, str], failed: Sequence[Failure],
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
    for failure in failed:
        logger.warning("commentary_batch: section %s could not write %s", section.label,
                       failure.brief())
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
    Results are placed by ``Target`` — value set AND role — so completion order cannot
    reach the deck, and a section spanning two sub-decks still lands each column in the
    one it came from.
    """
    from studio import telemetry
    from studio.ai import client
    from studio.commentary_mode import refuse
    from studio.parallel import gather_list
    from studio.template_fill import editorial

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
    # The editorial plan is built over the WHOLE deck and built FIRST, before any section
    # is written: which field is the home for the peer gap is a question about the deck,
    # and the sections that would otherwise each answer it for themselves run
    # concurrently. Deterministic and model-free, so it costs nothing and cannot reorder
    # anything — see :mod:`studio.template_fill.editorial`.
    plan = editorial.plan_deck([section.columns for section in sections])
    logger.info("commentary_batch: %d section(s), %d field(s) across %d value set(s)",
                len(sections), sum(len(s.columns) for s in sections), len(value_sets))
    _log_plan(plan, sections)
    with telemetry.phase("commentary"):
        written = gather_list([lambda s=section: write_section(s, plan)
                               for section in sections])
    for texts in written:
        for target, text in texts.items():
            out[target.value_set][target.role] = text
    return out


def _log_plan(plan, sections: Sequence[Section]) -> None:
    """Who owns what, once per deck — the line to read when a page repeats another."""
    for section in sections:
        owned = [(c.node, plan.fields[c.field_id].owns) for c in section.columns
                 if c.field_id in plan.fields]
        if owned:
            logger.info("editorial plan: section %s — %s", section.label,
                        "; ".join(f"{node} owns {', '.join(topics) or 'nothing'}"
                                  for node, topics in owned))
