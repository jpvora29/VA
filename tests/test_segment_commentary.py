"""Segment findings as commentary — evidence, sentences, altitude and the gates.

The unit tests for the classifiers live in ``test_segment_findings.py``. This file covers
the join: that a finding reaches the model as citable evidence, that the sentence built
from it survives every gate that would otherwise send a whole column back to its draft,
and that a finding is said on the page it belongs to rather than on all of them.

Deterministic: seed DB, ``STUDIO_AI=off``.
"""
from __future__ import annotations

import pytest

from studio import segments as S
from studio.ai.verifier import _violations, allowed_numbers
from studio.compute import compute_overall
from studio.data import get_engine
from studio.template_fill import commentary as CM
from studio.template_fill import commentary_metrics as MET
from studio.template_fill import feedback as F
from studio.template_fill import segment_prose as P
from studio.template_fill.commentary_evidence import build_pack

ENG = get_engine()
_COLUMNS = ("working", "challenges", "growth", "key_messages", "thesis")

_PRODUCTS = ("Financial Lines", "Casualty", "Cyber", "Property", "Marine", "Energy")
_COUNTRIES = ("Singapore", "Japan", "Australia", "Hong Kong")


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    monkeypatch.setenv("STUDIO_AI", "off")


def _facts(**filters):
    filters.setdefault("carrier", "Zurich")
    filters.setdefault("year", 2025)
    return F.facts_for(compute_overall(flow="gpr", engine=ENG, filters=filters))


@pytest.fixture(scope="module")
def line_facts():
    return F.facts_for(compute_overall(flow="gpr", engine=ENG, filters={
        "carrier": "Zurich", "country": "Singapore",
        "product_line": "Financial Lines", "year": 2025}))


# ── the decomposition reaches the fact set ──────────────────────────────────


def test_the_fact_set_carries_the_decomposition(line_facts):
    found = line_facts["segments"]
    assert found, "the commentary writer still sees the scope as one number"
    assert all(isinstance(v, S.SegmentFindings) for v in found.values())


def test_a_fact_set_built_without_segments_composes_exactly_as_it_did(line_facts):
    """The decision-5 regression guard: the new lines REPLACE generic ones, they do not
    depend on a key every older caller and test constructs without."""
    bare = {k: v for k, v in line_facts.items() if k != "segments"}
    for column in _COLUMNS:
        assert F.points(column, bare), f"{column} produced nothing without segments"


def test_a_scope_pinned_to_a_dimension_never_decomposes_by_it():
    """A page filtered to one industry that cut by industry could only report itself back."""
    facts = _facts(country="Singapore", industry="Manufacturing")
    assert "SIC_Major_Class" not in facts["segments"]


# ── the number contract (commentary_verify.check_numbers) ───────────────────


def test_every_number_a_column_prints_is_backed_by_a_cited_fact():
    """The gate that silently eats good lines.

    ``check_numbers`` scopes the allowed values to the facts a sentence cites, so a figure
    a composer prints that the pack does not carry costs the whole bullet. Asserted across
    every product and market rather than trusted as a convention, because the failure is
    invisible at runtime: the column simply falls back to its draft.
    """
    unsupported = []
    for product in _PRODUCTS:
        for country in ("Singapore", "Japan"):
            facts = _facts(country=country, product_line=product)
            allowed = allowed_numbers(*build_pack(facts).rendered_values())
            for column in _COLUMNS:
                for line in F.points(column, facts):
                    for issue in _violations(line, allowed, ()):
                        unsupported.append(f"{product}/{country}/{column}: {issue} in {line}")
    assert not unsupported, "\n".join(unsupported[:10])


def test_the_top_five_benchmark_is_quotable():
    """``_TOKEN_RE`` reads the "-5" in "top-5 peer average" as a number and ``_norm`` drops
    the sign, so a sentence naming the benchmark needs a "5" among its allowed values. It
    is carried in the rendered value; without it every peer sentence was dropped."""
    pack = build_pack({"subject": "Zurich", "peer": {"sow": 10.8}, "carrier": {},
                       "marsh": {}, "rank": {}, "sow": {}})
    allowed = allowed_numbers(*pack.rendered_values())
    assert not _violations("The book sits below the top-5 peer average of 10.8%.", allowed, ())


def test_the_reporting_year_is_quotable():
    """Almost every column dates its figures, and the year is a number to the verifier."""
    pack = build_pack({"subject": "Zurich", "carrier": {"current": 1e6, "current_year": 2025},
                       "marsh": {}, "rank": {}, "sow": {}})
    allowed = allowed_numbers(*pack.rendered_values())
    assert not _violations("Zurich wrote $1M with Marsh in 2025.", allowed, ())


# ── the prose gates (commentary._accept) ────────────────────────────────────


def _every_sentence():
    for product in _PRODUCTS:
        facts = _facts(country="Singapore", product_line=product)
        for findings in facts["segments"].values():
            for row in findings.rows:
                for lead in (True, False):
                    line = P.sentence(row, "Zurich", lead=lead)
                    if line:
                        yield line


def test_no_segment_sentence_reads_as_a_metric_read_out():
    """``_accept`` throws away an ENTIRE rewrite containing one, so a single careless
    opening costs the column its voice and nobody sees why."""
    offenders = [s for s in _every_sentence() if MET.is_restatement(s)]
    assert not offenders, offenders[:3]


def test_no_segment_sentence_trips_the_generated_prose_gate():
    offenders = [(s, CM._AI_TELLS.search(s).group(0))
                 for s in _every_sentence() if CM._AI_TELLS.search(s)]
    assert not offenders, offenders[:3]


def test_every_segment_sentence_is_a_whole_sentence():
    assert all(CM._is_whole_sentence(s) for s in _every_sentence())


def test_only_one_segment_can_be_the_one_placed_best():
    """Two "places best" lines in a column is a contradiction a reader sees immediately."""
    for product in _PRODUCTS:
        facts = _facts(country="Singapore", product_line=product)
        for column in _COLUMNS:
            lines = F.points(column, facts)
            assert sum("places best" in line for line in lines) <= 1, (product, column, lines)


# ── the voice split (decision 2) ────────────────────────────────────────────


_BARE_IMPERATIVE = ("defend cyber", "scale financial lines", "fix casualty",
                    "selectively pursue property", "the call is to defend")


def test_no_column_issues_a_bare_product_instruction():
    """"Across the book the call is to defend Cyber, scale Financial Lines, fix Casualty"
    named six products, carried no figure, and would have been true of any carrier."""
    for country in _COUNTRIES:
        facts = _facts(country=country)
        for column in _COLUMNS:
            for line in F.points(column, facts):
                low = line.lower()
                assert not any(bad in low for bad in _BARE_IMPERATIVE), line


def test_an_instruction_carries_a_figure():
    """Decision 2: an imperative names a segment and what is at stake, or it is a slogan."""
    for country in _COUNTRIES:
        facts = _facts(country=country)
        for line in F.points("key_messages", facts):
            if "the call here is to" in line.lower():
                assert "$" in line or "%" in line, line


def test_the_diagnostic_columns_are_told_to_diagnose_and_key_messages_to_instruct():
    """The rule the model is actually held to, asserted in the prompt it is given."""
    growth = CM._style_system("balanced", topic="growth", wanted=4, subject="Zurich")
    messages = CM._style_system("balanced", topic="key_messages", wanted=4, subject="Zurich")
    assert "diagnose, do not instruct" in growth
    assert "diagnose, do not instruct" not in messages
    assert "'defend Cyber'" in messages


def test_every_column_carries_its_hidden_question_set():
    """The questions shape the prose; they must never reach a slide."""
    for topic in ("working", "challenges", "growth", "key_messages"):
        rule = CM._questions_rule(topic)
        assert rule and "never print a question" in rule
        assert all(q.endswith("?") for q in CM._TOPIC_QUESTIONS[topic])
        assert rule in CM._style_system("balanced", topic=topic, wanted=4, subject="Zurich")


def test_the_growth_questions_ask_for_all_three_opportunity_kinds():
    asked = " ".join(CM._TOPIC_QUESTIONS["growth"]).lower()
    assert "nothing of" in asked          # ABSENT
    assert "below the average it achieves" in asked   # THIN
    assert "top-5 peer average" in asked  # BEHIND


def test_the_judge_is_told_an_absence_is_a_placement_observation():
    """Rule 4 drops appetite claims. "The book writes none of it" is not one, and without
    this clause the judge drops the finding the Growth column is built on."""
    from studio.template_fill.commentary_verify import _JUDGE_SYSTEM

    assert "OBSERVATION ABOUT PLACEMENT" in _JUDGE_SYSTEM
    assert "writes none of it" in _JUDGE_SYSTEM


# ── confidentiality ─────────────────────────────────────────────────────────


def test_no_segment_sentence_names_a_carrier():
    """Peers stay aggregate (decision 4). Industry names must not smuggle one in either."""
    carriers = {c.lower() for c in (
        "AIG", "Chubb", "Allianz", "AXA XL", "Tokio Marine", "Liberty Specialty",
        "QBE", "Sompo", "MS&AD", "Berkshire", "Swiss Re")}
    for line in _every_sentence():
        low = line.lower()
        assert not any(name in low for name in carriers), line


# ── altitude (the repetition the ledger cannot see) ─────────────────────────


def test_a_portfolio_wide_finding_is_not_repeated_on_every_page():
    """The three industries this book writes none of are absent in all four markets and
    all six lines. Left to each page, all twenty-four product pages opened their Growth
    column on the same one — and ``ClaimLedger`` could not catch it, because each page
    renders a different premium figure and so a different string.
    """
    naming = 0
    for country in _COUNTRIES:
        for product in _PRODUCTS:
            facts = _facts(country=country, product_line=product)
            if "Renewable Energy" in " ".join(F.points("growth", facts)):
                naming += 1
    assert naming == 0, f"{naming} of 24 product pages repeat the portfolio's own finding"


def test_the_finding_still_lands_on_the_page_that_owns_it():
    """Narrowing must not simply delete it — the overall page has no parent to defer to."""
    facts = _facts(country=list(_COUNTRIES))
    assert "Renewable Energy" in " ".join(F.points("growth", facts))


def test_a_product_page_keeps_what_is_distinctive_to_it():
    """Financial Lines in Singapore is thin in Technology & Telecom in a way the product is
    not across the book, so that finding belongs here."""
    facts = _facts(country="Singapore", product_line="Financial Lines")
    assert "Technology & Telecom" in " ".join(F.points("growth", facts))


def test_a_scope_that_tracks_its_parent_says_so():
    """The honest answer, and the one the user asked for: knowing there is no local anomaly
    is a finding. Inventing a difference to fill the column is what the deck did before."""
    facts = _facts(country="Singapore")
    assert F._tracks_parent(facts)
    assert "tracks the wider portfolio" in " ".join(F.points("growth", facts))


def test_the_tracking_note_differs_between_markets():
    """Otherwise the ledger drops it everywhere after the first page."""
    notes = set()
    for country in _COUNTRIES:
        facts = _facts(country=country)
        notes |= {line for line in F.points("growth", facts) if "tracks the wider" in line}
    assert len(notes) > 1, notes


# ── no column ever ships blank ──────────────────────────────────────────────


def test_every_column_of_every_page_still_fills():
    for country in _COUNTRIES:
        for product in (None,) + _PRODUCTS:
            filters = {"country": country}
            if product:
                filters["product_line"] = product
            facts = _facts(**filters)
            for column in _COLUMNS:
                assert F.points(column, facts), (country, product, column)


def test_a_failing_decomposition_leaves_the_old_commentary_standing(monkeypatch):
    """A decomposition sharpens a column; it never gates one."""
    monkeypatch.setattr(S, "compute_breakdown", lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("warehouse down")))
    S.reset_cache()
    facts = _facts(country="Singapore", product_line="Financial Lines")
    assert facts["segments"] == {}
    for column in _COLUMNS:
        assert F.points(column, facts), column
    S.reset_cache()
