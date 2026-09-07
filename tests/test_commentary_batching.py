"""Section-level commentary: the batching, the strict mode, the cache, the telemetry.

The plan these cover ("QBR AI Commentary, Chatbot Quality, and Performance") is about one
number — how many model calls a build makes — and three guarantees that must survive
cutting it:

  * a batched deck maps every requested field EXACTLY once, in the deck's own order;
  * ``COMMENTARY_MODE=ai_required`` never lets deterministic prose reach a slide;
  * a re-export of unchanged evidence makes no model call at all.

No LLM and no database. The model is a stub that answers the structured schema, so what is
under test is the orchestration rather than the writing.
"""
from __future__ import annotations

import pytest

from studio import commentary_mode as mode
from studio import telemetry
from studio.ai.models import CommentaryBullet, CommentarySection, CommentarySections
from studio.template_fill import commentary_batch as B
from studio.template_fill import rewrites
from studio.template_fill.rewrites import PendingRewrite


# ── fixtures: one book, enough of it to build a real evidence pack ───────────


def _facts() -> dict:
    """A fact dict of the shape ``feedback.facts_for`` returns, big enough to cite.

    The key names matter: :func:`studio.template_fill.commentary_evidence.build_pack` reads
    ``current``/``pct``/``delta`` off each family, and a plausible-looking dict with the
    wrong names builds a pack of two facts and makes every evidence assertion vacuous.
    """
    return {
        "subject": "Zurich",
        "carrier": {"current": 44_000_000.0, "pct": 12.8, "delta": 5_000_000.0,
                    "current_year": 2025},
        "marsh": {"current": 900_000_000.0, "pct": 6.2},
        "sow": {"current": 4.9, "delta": 0.5},
        "rank": {"current": 4, "of_n": 31, "delta": 1},
        "peer": {"sow": 6.1, "current": 55_000_000.0},
    }


def _pending(topic: str, draft: str, facts: dict) -> PendingRewrite:
    return PendingRewrite(draft=draft, node=f"commentary-{topic}", topic=topic,
                          subject="Zurich", style="balanced", facts=facts)


def _value_set(facts: dict, topics=("working", "challenges", "growth")) -> dict:
    return {f"note:{i}:{i}:0": _pending(t, f"{t} line one.\n{t} line two.", facts)
            for i, t in enumerate(topics)}


@pytest.fixture(autouse=True)
def _no_cache(tmp_path, monkeypatch):
    """Point the on-disk cache at a throwaway directory for every test in this file."""
    monkeypatch.setenv("STUDIO_COMMENTARY_CACHE", str(tmp_path / "commentary"))
    monkeypatch.delenv("COMMENTARY_MODE", raising=False)
    monkeypatch.delenv("STUDIO_AI", raising=False)


#: What the stubbed model writes. Whole sentences, no figures, no phrase the reading gate
#: refuses — so a failed assertion below is about the batching, not about the prose.
_SENTENCES = (
    "The book grew faster than the pool it was written in, and that gap is the story.",
    "Defending that position now matters more than adding to it.",
    "Growth of this kind rarely survives a hard renewal season without a plan behind it.",
    "The team should treat the coming quarter as a test of whether the gain holds.",
)


@pytest.fixture
def stub_model(monkeypatch):
    """A model that answers every requested field with two citable sentences.

    Returns the call log, so a test can assert on HOW MANY calls a deck made — which is
    the number the whole plan is about.
    """
    import studio.ai.client as client

    calls = []

    def structured(model, system, user, *, tier="balanced", node="ai", phase="other",
                   fields=(), **kw):
        calls.append({"node": node, "phase": phase, "fields": tuple(fields), "user": user})
        if model is CommentarySections:
            asked = [line.split()[2] for line in user.splitlines()
                     if line.startswith("--- FIELD ")]
            # Deliberately figure-free whole sentences: the verifiers and the shape gate
            # are under test elsewhere, and a stub that trips them would make every
            # call-count assertion here really an assertion about the gates. Four of them,
            # because a real template's columns ask for up to four and ``_accept`` trims a
            # generous answer but refuses a short one.
            return CommentarySections(sections=[
                CommentarySection(field_id=fid, bullets=[
                    CommentaryBullet(text=line, fact_ids=[]) for line in _SENTENCES
                ]) for fid in asked])
        return None                      # every other schema: the verifier keeps everything

    monkeypatch.setattr(client, "structured", structured)
    monkeypatch.setattr(client, "llm_available", lambda: True)
    return calls


# ── grouping: one call per sub-deck, one entry per field ────────────────────


def test_a_sub_decks_columns_are_grouped_into_one_section():
    facts = _facts()
    sections = B.group_sections([_value_set(facts)])
    assert len(sections) == 1
    assert len(sections[0].columns) == 3
    assert sections[0].subject == "Zurich"


def test_two_sub_decks_are_two_sections_and_keep_their_own_value_set():
    first, second = _facts(), _facts()          # distinct objects: two scopes, two books
    sections = B.group_sections([_value_set(first), _value_set(second)])
    assert [s.value_set for s in sections] == [0, 1]


def test_columns_sharing_one_pending_are_written_once_and_land_on_every_role():
    """``commentary.values`` answers one question per topic and puts that answer in every
    box asking it — the same object under several roles. Writing it once per role paid for
    the same column twice."""
    facts = _facts()
    shared = _pending("working", "one line.", facts)
    sections = B.group_sections([{"note:1:1:0": shared, "note:2:2:0": shared}])
    assert len(sections[0].columns) == 1
    assert set(sections[0].columns[0].roles) == {"note:1:1:0", "note:2:2:0"}


def test_every_requested_field_id_is_returned_exactly_once(stub_model):
    facts = _facts()
    values = _value_set(facts)
    written = rewrites.write_all([values])[0]
    assert set(written) == set(values)
    assert all(isinstance(v, str) and v.strip() for v in written.values())


def test_a_field_the_model_invents_is_ignored_rather_than_mapped_by_position(stub_model,
                                                                            monkeypatch):
    import studio.ai.client as client

    def structured(model, system, user, *, tier="balanced", node="ai", phase="other",
                   fields=(), **kw):
        if model is CommentarySections:
            return CommentarySections(sections=[CommentarySection(
                field_id="not.a.field",
                bullets=[CommentaryBullet(text="A sentence about nothing.", fact_ids=[])])])
        return None

    monkeypatch.setattr(client, "structured", structured)
    facts = _facts()
    values = _value_set(facts, topics=("working",))
    written = rewrites.write_all([values])[0]
    # Nothing was written, so the deterministic draft stands — not another field's text.
    assert list(written.values()) == ["working line one.\nworking line two."]


# ── the call count: the whole point of the change ───────────────────────────


def test_a_sub_deck_costs_one_author_call_not_one_per_column(stub_model):
    facts = _facts()
    rewrites.write_all([_value_set(facts, topics=("working", "challenges", "growth",
                                                  "priorities", "key_messages"))])
    authored = [c for c in stub_model if c["phase"] == "author"]
    assert len(authored) == 1, "five columns must cost one author call"
    assert len(authored[0]["fields"]) == 5


def test_three_sub_decks_cost_three_calls_not_fifteen(stub_model):
    # Three DIFFERENT books. Identical ones would be three sections racing for one cache
    # entry, and the call count would depend on which finished first.
    books = []
    for i in range(3):
        book = _facts()
        book["carrier"]["current"] += i * 1_000_000.0
        books.append(book)
    rewrites.write_all([_value_set(f, topics=("working", "challenges", "growth",
                                             "priorities", "key_messages"))
                        for f in books])
    assert len([c for c in stub_model if c["phase"] == "author"]) == 3


# ── strict mode: no deterministic prose, ever ───────────────────────────────


def test_ai_required_refuses_rather_than_shipping_the_draft(monkeypatch):
    import studio.ai.client as client

    monkeypatch.setenv("COMMENTARY_MODE", "ai_required")
    monkeypatch.setattr(client, "llm_available", lambda: True)
    monkeypatch.setattr(client, "structured",
                        lambda *a, **kw: None)          # the author answers nothing
    with pytest.raises(mode.CommentaryUnavailable) as raised:
        rewrites.write_all([_value_set(_facts())])
    assert raised.value.retryable is True
    assert "ai_required" in str(raised.value)


def test_auto_mode_keeps_the_draft_when_the_author_answers_nothing(monkeypatch):
    import studio.ai.client as client

    monkeypatch.setattr(client, "llm_available", lambda: True)
    monkeypatch.setattr(client, "structured", lambda *a, **kw: None)
    written = rewrites.write_all([_value_set(_facts(), topics=("working",))])[0]
    assert list(written.values()) == ["working line one.\nworking line two."]


def test_preflight_refuses_before_any_analytics_when_ai_is_not_configured(monkeypatch):
    monkeypatch.setenv("COMMENTARY_MODE", "ai_required")
    monkeypatch.setattr("core.llm.clients.available", lambda tier="balanced": False)
    with pytest.raises(mode.CommentaryUnavailable) as raised:
        mode.preflight()
    assert raised.value.retryable is False, "a missing key is not fixed by trying again"


def test_preflight_is_silent_in_auto_mode(monkeypatch):
    monkeypatch.setattr("core.llm.clients.available", lambda tier="balanced": False)
    mode.preflight()                                    # no raise


def test_the_kill_switch_beats_the_strict_mode(monkeypatch):
    monkeypatch.setenv("STUDIO_AI", "off")
    monkeypatch.setenv("COMMENTARY_MODE", "ai_required")
    assert mode.mode() == mode.OFF
    assert not mode.ai_required()
    mode.preflight()                                    # and refuses nothing


def test_an_unreadable_mode_reads_as_auto(monkeypatch):
    monkeypatch.setenv("COMMENTARY_MODE", "sort-of-required")
    assert mode.mode() == mode.AUTO


def test_strict_mode_withholds_the_finished_draft_from_the_author(monkeypatch, stub_model):
    monkeypatch.setenv("COMMENTARY_MODE", "ai_required")
    rewrites.write_all([_value_set(_facts(), topics=("working",))])
    prompt = [c for c in stub_model if c["phase"] == "author"][0]["user"]
    assert "working line one." not in prompt, "strict mode must not show prose to imitate"
    assert "EVIDENCE" in prompt and "FIELD" in prompt


def test_auto_mode_still_shows_the_draft(stub_model):
    rewrites.write_all([_value_set(_facts(), topics=("working",))])
    prompt = [c for c in stub_model if c["phase"] == "author"][0]["user"]
    assert "working line one." in prompt


# ── the cache: an export must not re-write the deck ─────────────────────────


def test_a_second_identical_build_makes_no_author_call(stub_model):
    facts = _facts()
    first = rewrites.write_all([_value_set(facts, topics=("working", "challenges"))])[0]
    calls_after_first = len([c for c in stub_model if c["phase"] == "author"])

    second = rewrites.write_all([_value_set(facts, topics=("working", "challenges"))])[0]
    assert len([c for c in stub_model if c["phase"] == "author"]) == calls_after_first
    assert list(first.values()) == list(second.values())


def test_changed_evidence_invalidates_the_cached_section(stub_model):
    rewrites.write_all([_value_set(_facts(), topics=("working",))])
    moved = _facts()
    moved["carrier"]["current"] = 51_000_000.0
    rewrites.write_all([_value_set(moved, topics=("working",))])
    assert len([c for c in stub_model if c["phase"] == "author"]) == 2


def test_a_new_prompt_version_invalidates_the_cache(stub_model, monkeypatch):
    facts = _facts()
    rewrites.write_all([_value_set(facts, topics=("working",))])
    monkeypatch.setattr(B, "PROMPT_VERSION", "section-v2")
    rewrites.write_all([_value_set(facts, topics=("working",))])
    assert len([c for c in stub_model if c["phase"] == "author"]) == 2


def test_a_retry_after_a_partial_failure_only_rewrites_what_failed(monkeypatch):
    """"Preserve successful partial results across retries": a section that wrote one of
    its two fields must not pay to write that one again on the next run."""
    import studio.ai.client as client

    answered = {"working"}                   # only this field comes back the first time
    asked = []

    def structured(model, system, user, *, tier="balanced", node="ai", phase="other",
                   fields=(), **kw):
        if model is not CommentarySections:
            return None
        asked.append(tuple(fields))
        wanted = [line.split()[2] for line in user.splitlines()
                  if line.startswith("--- FIELD ")]
        return CommentarySections(sections=[
            CommentarySection(field_id=fid, bullets=[
                CommentaryBullet(text=line, fact_ids=[]) for line in _SENTENCES])
            for fid in wanted if fid.split(".")[0] in answered])

    monkeypatch.setattr(client, "llm_available", lambda: True)
    monkeypatch.setattr(client, "structured", structured)

    facts = _facts()
    topics = ("working", "challenges")
    first = rewrites.write_all([_value_set(facts, topics=topics)])[0]
    written = [v for v in first.values() if v.startswith("The book grew")]
    assert len(written) == 1, "exactly one field was answerable on the first run"

    # Second run: the model can now answer both, but must only be ASKED the one that
    # failed — the field that succeeded was cached the moment it passed.
    answered.add("challenges")
    asked.clear()
    second = rewrites.write_all([_value_set(facts, topics=topics)])[0]
    assert all(len(fields) == 1 for fields in asked), asked
    assert all(v.startswith("The book grew") for v in second.values())


def test_the_cache_can_be_turned_off(stub_model, monkeypatch):
    monkeypatch.setenv("STUDIO_COMMENTARY_CACHE", "off")
    facts = _facts()
    rewrites.write_all([_value_set(facts, topics=("working",))])
    rewrites.write_all([_value_set(facts, topics=("working",))])
    assert len([c for c in stub_model if c["phase"] == "author"]) == 2


# ── telemetry ───────────────────────────────────────────────────────────────


def test_a_model_call_records_itself_with_its_phase(monkeypatch):
    """The recording lives in ``studio.ai.client``, so it is driven through the real one."""
    import core.llm.clients as llm
    import studio.ai.client as client
    from pydantic import BaseModel

    class Answer(BaseModel):
        text: str = "written"

    class FakeStructured:
        def invoke(self, messages):
            return Answer()

    class FakeClient:
        def with_structured_output(self, model):
            return FakeStructured()

    monkeypatch.setattr(llm, "make_client", lambda tier: FakeClient())
    monkeypatch.setattr(client, "llm_available", lambda: True)

    with telemetry.job("test") as record:
        client.structured(Answer, "s", "u", tier="reason", node="section-x",
                          phase=telemetry.AUTHOR, fields=("a", "b"))
        client.structured(Answer, "s", "u", node="section-x-verify",
                          phase=telemetry.VERIFY)
        summary = record.summary()

    assert summary.calls == 2
    assert summary.calls_by_phase[telemetry.AUTHOR] == 1
    assert summary.calls_by_phase[telemetry.VERIFY] == 1
    assert record.calls[0].fields == ("a", "b")
    assert "job=test" in summary.as_line()


def test_a_failed_call_is_still_recorded_with_its_failure_kind(monkeypatch):
    """The slowest calls in a build are often the ones that produced nothing."""
    import core.llm.clients as llm
    import studio.ai.client as client

    class Exploding:
        def invoke(self, messages):
            raise RuntimeError("Error code: 429 - rate limit is exceeded")

    monkeypatch.setattr(llm, "make_client", lambda tier: Exploding())
    monkeypatch.setattr(client, "llm_available", lambda: True)

    with telemetry.job("test") as record:
        assert client.generate("s", "u", phase=telemetry.AUTHOR) is None
    assert record.calls[0].status == "error"
    assert record.calls[0].failure == "rate_limit"


def test_failures_are_classified_so_a_retry_policy_can_read_them():
    cases = {
        "rate_limit": Exception("Error code: 429 - rate limit exceeded"),
        "timeout": TimeoutError("request timed out after 60s"),
        "auth": Exception("401 unauthorized: invalid api key"),
        "config": Exception("DeploymentNotFound: the deployment does not exist"),
    }
    for expected, exc in cases.items():
        assert telemetry.classify_failure(exc) == expected
    assert telemetry.is_transient("rate_limit") and telemetry.is_transient("timeout")
    assert not telemetry.is_transient("auth"), "retrying a bad key burns the budget"
    assert not telemetry.is_transient("config")


def test_percentiles_do_not_need_numpy():
    from studio.telemetry import _percentile

    assert _percentile([1.0, 2.0, 3.0, 4.0], 50) == 2.0
    assert _percentile([1.0, 2.0, 3.0, 4.0], 95) == 4.0
    assert _percentile([], 50) == 0.0


def test_a_job_is_reentrant_so_a_nested_build_shares_one_record():
    with telemetry.job("outer") as outer:
        with telemetry.job("inner") as inner:
            assert inner is outer
        assert telemetry.active() is outer
    assert telemetry.active() is None


# ── the explicit per-column writer still works ──────────────────────────────


def test_an_injected_writer_still_gets_one_call_per_column():
    """The per-column path is how a test drives this without a model — it must not have
    been quietly replaced by the batched one."""
    seen = []
    values = _value_set(_facts(), topics=("working", "growth"))
    written = rewrites.write_all([values], write=lambda p: seen.append(p) or p.draft.upper())
    assert len(seen) == 2
    assert all(v.isupper() for v in written[0].values())


# ── end to end: a real deck, over the real templates, with a stubbed model ──


@pytest.mark.e2e
def test_a_real_deck_is_written_section_by_section_and_every_field_is_ai_authored(
        tmp_path, stub_model, monkeypatch):
    """The plan's end-to-end path, with only the model replaced.

        selection -> result -> evidence -> sub-deck plan -> commentary -> fill -> merge

    Two things are asserted that unit tests cannot: that a real template's columns group
    into sections at all (they carry real facts objects, not fixtures), and that the deck
    makes ONE author call per sub-deck rather than one per column — which is the entire
    performance claim.
    """
    from pptx import Presentation

    from studio.compute import compute_overall
    from studio.template_fill.assemble import assemble_deck, deck_shape

    monkeypatch.setenv("COMMENTARY_MODE", "ai_required")
    monkeypatch.setenv("STUDIO_MAX_WORKERS", "1")        # deterministic ordering in the log

    result = compute_overall(filters={"carrier": "Zurich", "country": ["Singapore"]})
    shape = deck_shape(result, scope="country")
    out = assemble_deck(result, out_path=str(tmp_path / "deck.pptx"),
                        work_dir=str(tmp_path / "work"), scope="country")

    assert Presentation(out).slides                       # a deck came out
    authored = [c for c in stub_model if c["phase"] == "author"]
    assert authored, "the model must have written this deck"
    # One call per sub-deck that carries prose — never one per field.
    assert len(authored) <= sum(shape.blocks().values())
    assert sum(len(c["fields"]) for c in authored) >= len(authored)


@pytest.mark.e2e
def test_a_real_deck_refuses_to_ship_when_the_model_is_gone(tmp_path, monkeypatch):
    """``ai_required`` must fail the BUILD, not quietly fill the slides with rule prose."""
    import studio.ai.client as client

    from studio.compute import compute_overall
    from studio.template_fill.assemble import assemble_deck

    monkeypatch.setenv("COMMENTARY_MODE", "ai_required")
    monkeypatch.setenv("STUDIO_MAX_WORKERS", "1")
    monkeypatch.setattr(client, "llm_available", lambda: True)
    monkeypatch.setattr(client, "structured", lambda *a, **kw: None)

    result = compute_overall(filters={"carrier": "Zurich", "country": ["Singapore"]})
    with pytest.raises(mode.CommentaryUnavailable):
        assemble_deck(result, out_path=str(tmp_path / "deck.pptx"),
                      work_dir=str(tmp_path / "work"), scope="overall")


def test_a_risk_flag_reaches_the_audit_line_rather_than_being_asked_for_and_binned(
        monkeypatch, caplog):
    """The schema asks for a risk read; something has to look at it or it is dead tokens."""
    import logging

    import studio.ai.client as client

    def structured(model, system, user, *, tier="balanced", node="ai", phase="other",
                   fields=(), **kw):
        if model is not CommentarySections:
            return None
        wanted = [line.split()[2] for line in user.splitlines()
                  if line.startswith("--- FIELD ")]
        return CommentarySections(sections=[
            CommentarySection(field_id=fid, risk_flag="concern", bullets=[
                CommentaryBullet(text=line, fact_ids=[]) for line in _SENTENCES])
            for fid in wanted])

    monkeypatch.setattr(client, "llm_available", lambda: True)
    monkeypatch.setattr(client, "structured", structured)

    with caplog.at_level(logging.INFO, logger="studio.template_fill.commentary_batch"):
        with telemetry.job("risk") as record:
            rewrites.write_all([_value_set(_facts(), topics=("working",))])
    assert "risk[" in caplog.text and "concern" in caplog.text
    assert record.counters.get("commentary_risk_concern") == 1
