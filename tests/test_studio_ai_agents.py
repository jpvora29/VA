"""Studio AI layer — deterministic-fallback and faithfulness-verifier tests.

No API key is needed: these assert the AI layer is invisible (a no-op) when no LLM
is configured, and that the verifier strips invented numbers / peer names.
"""
from __future__ import annotations

from studio.ai import critic_agent, layout_agent, story_agent
from studio.ai.client import llm_available
from studio.ai.verifier import allowed_numbers, verify_bullets, verify_text
from studio.compute import compute_overall
from studio.deck import build_deck

_FILTERS = {"carrier": "Zurich", "country": ["Singapore"], "year": 2025}


def _deck(**kw):
    res = compute_overall(filters=_FILTERS, engine=None)
    return res, build_deck(res, carrier="Zurich", country="Singapore", year=2025, **kw)


# ── availability gate + graceful fallback ────────────────────────────────────


def test_llm_unavailable_when_disabled(monkeypatch):
    monkeypatch.setenv("STUDIO_AI", "off")
    assert llm_available() is False


def test_build_deck_ai_is_noop_without_llm(monkeypatch):
    monkeypatch.setenv("STUDIO_AI", "off")
    res = compute_overall(filters=_FILTERS, engine=None)
    base = build_deck(res, carrier="Zurich", country="Singapore", year=2025, ai=False)
    ai = build_deck(res, carrier="Zurich", country="Singapore", year=2025, ai=True)
    assert [s.title for s in base.slides] == [s.title for s in ai.slides]
    assert len(base.slides) == len(ai.slides)


def test_agents_return_input_unchanged_without_llm(monkeypatch):
    monkeypatch.setenv("STUDIO_AI", "off")
    res, deck = _deck()
    assert story_agent.enhance_deck(deck, res, subject="Zurich") is deck
    assert layout_agent.enhance_deck(deck) is deck


def test_critic_always_produces_a_report(monkeypatch):
    monkeypatch.setenv("STUDIO_AI", "off")
    _res, deck = _deck()
    reviewed = critic_agent.review_deck(deck)
    assert "critic_issues" in reviewed.meta
    assert isinstance(reviewed.meta["critic_issues"], list)


# ── faithfulness verifier ────────────────────────────────────────────────────


def test_verifier_strips_unsupported_number():
    allowed = allowed_numbers("Premium grew +28.6% to USD 207.9M versus FY2024.")
    clean, issues = verify_text(
        "Premium grew +28.6% to USD 207.9M. Margins jumped 73%.", allowed
    )
    assert "207.9M" in clean and "73%" not in clean
    assert any("73" in i for i in issues)


def test_verifier_blocks_individual_peer_name():
    allowed = allowed_numbers("Ranked #5 of 12.")
    clean, issues = verify_text(
        "Ranked #5 of 12. Allianz writes more than you.", allowed, forbidden_names=["Allianz"]
    )
    assert "Allianz" not in clean
    assert any("Allianz" in i for i in issues)


def test_verifier_keeps_supported_bullets():
    allowed = allowed_numbers("Cyber grew +58.4%. Whitespace is USD 410.0M.")
    clean, issues = verify_bullets(
        ["Cyber grew +58.4%", "Whitespace is USD 410.0M", "Retention fell 12%"], allowed
    )
    assert "Cyber grew +58.4%" in clean
    assert all("Retention" not in c for c in clean)
    assert issues


# ── the confidentiality list, and the shape it is built from ────────────────


def test_the_peer_blocklist_is_built_from_dash_option_dicts():
    """``cached_filter_options`` returns ``{"label": …, "value": …}`` dicts, not strings.

    Read as strings, the first carrier raised ``'dict' object has no attribute 'lower'``
    and took the whole of ``enhance_deck`` down with it — so the AI story pass never ran
    and the peer blocklist it exists to enforce was never applied. The failure was silent:
    the caller logs a warning and returns the un-enhanced deck, which looks exactly like
    "no LLM configured".
    """
    class _Result:
        flow = "gpr"

    names = story_agent._forbidden_names(_Result(), "Zurich")

    assert names, "the confidentiality list came back empty"
    assert all(isinstance(n, str) for n in names)
    assert "AIG" in names                      # a peer IS forbidden
    assert "Zurich" not in names               # ...the subject is not
    assert not any("marsh" == n.lower() for n in names)


def test_a_carrier_option_is_read_whatever_shape_it_arrives_in():
    assert story_agent._option_name({"label": "AIG", "value": "AIG"}) == "AIG"
    assert story_agent._option_name({"label": "AIG"}) == "AIG"      # value missing
    assert story_agent._option_name("Chubb") == "Chubb"             # already a string
    assert story_agent._option_name(None) == ""


def test_an_unavailable_options_cache_leaves_the_list_empty_rather_than_raising(monkeypatch):
    """Confidentiality is best-effort here; the verifier is the gate that must not fail."""
    import studio.data as D

    monkeypatch.setattr(D, "cached_filter_options",
                        lambda flow: (_ for _ in ()).throw(RuntimeError("no cache")))

    class _Result:
        flow = "gpr"

    assert story_agent._forbidden_names(_Result(), "Zurich") == []
