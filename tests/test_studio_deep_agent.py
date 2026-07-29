"""Studio deepagents harness: gating, skills library, fail-soft fallbacks.

The harness must never be load-bearing: with `STUDIO_AI=off` (or
`STUDIO_DEEP_AGENT=off`) every consumer takes exactly the pre-existing path —
deterministic layout labels, counts-only QA summary — and the agent build
itself works offline against a fake model (skills injected, deny-write
permissions accepted).
"""
from __future__ import annotations

import os

import pytest

os.environ["STUDIO_AI"] = "off"          # deterministic: no LLM in tests

from studio.ai.deep_agent import (  # noqa: E402
    deep_agent_available,
    run_deep_agent,
    skills_root,
)
from studio.qa import QAIssue, QAReport, explain_qa_report, summarize_qa_counts  # noqa: E402
from studio.qa.report import CRITICAL, INFO, WARNING  # noqa: E402


# ── gating ────────────────────────────────────────────────────────────────────


def test_unavailable_when_studio_ai_off(monkeypatch):
    monkeypatch.setenv("STUDIO_AI", "off")
    assert deep_agent_available() is False
    assert run_deep_agent("hi", system_prompt="x") is None


def test_deep_agent_has_its_own_off_switch(monkeypatch):
    monkeypatch.setenv("STUDIO_AI", "auto")
    monkeypatch.setenv("API_KEY", "k")
    monkeypatch.setenv("ENDPOINT", "e")
    monkeypatch.setenv("STUDIO_DEEP_AGENT", "off")
    assert deep_agent_available() is False


def test_available_when_gate_open(monkeypatch):
    monkeypatch.setenv("STUDIO_AI", "auto")
    monkeypatch.setenv("API_KEY", "k")
    monkeypatch.setenv("ENDPOINT", "e")
    monkeypatch.delenv("STUDIO_DEEP_AGENT", raising=False)
    assert deep_agent_available() is True


# ── skills library ────────────────────────────────────────────────────────────


def _frontmatter(text: str) -> dict:
    import yaml

    assert text.startswith("---\n"), "SKILL.md must start with YAML frontmatter"
    return yaml.safe_load(text.split("---\n")[1])


def test_skills_library_exists_with_valid_frontmatter():
    skill_files = sorted(skills_root().glob("*/SKILL.md"))
    names = {f.parent.name for f in skill_files}
    assert {"template-layout", "commentary-style", "qa-explainer"} <= names
    for f in skill_files:
        meta = _frontmatter(f.read_text(encoding="utf-8"))
        assert meta["name"] == f.parent.name
        assert meta["description"].strip()
        assert len(meta["description"]) <= 500


# ── offline agent build (fake model — proves the harness wiring itself) ──────


def test_harness_builds_and_injects_skills(monkeypatch):
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
    from langchain_core.messages import AIMessage, HumanMessage

    captured: list = []

    class ToolBindableFake(GenericFakeChatModel):
        def bind_tools(self, tools, **kwargs):  # noqa: ANN001, ARG002
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
            captured.append(messages)
            return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    fake = ToolBindableFake(messages=iter([AIMessage(content="done")]))
    import studio.ai.client as client

    monkeypatch.setattr(client, "_tier_client", lambda tier: fake)
    monkeypatch.setenv("STUDIO_AI", "auto")
    monkeypatch.setenv("API_KEY", "k")
    monkeypatch.setenv("ENDPOINT", "e")

    text = run_deep_agent("hello", system_prompt="You label slides.",
                          tier="fast", node="test")
    assert text == "done"
    system = captured[0][0]
    prompt = system.text if isinstance(system.text, str) else str(system.content)
    assert "template-layout" in prompt          # skills progressively disclosed
    assert "You label slides." in prompt        # our system prompt leads


def test_run_returns_none_when_agent_errors(monkeypatch):
    import studio.ai.client as client

    def boom(tier):  # noqa: ANN001, ARG001
        raise RuntimeError("no client")

    monkeypatch.setattr(client, "_tier_client", boom)
    monkeypatch.setenv("STUDIO_AI", "auto")
    monkeypatch.setenv("API_KEY", "k")
    monkeypatch.setenv("ENDPOINT", "e")
    assert run_deep_agent("hi", system_prompt="x") is None


# ── consumers fall back deterministically ─────────────────────────────────────


def _report() -> QAReport:
    return QAReport(issues=(
        QAIssue("missing_slot", CRITICAL, "Required slot empty", "kpi:2:5"),
        QAIssue("data_gap", WARNING, "No prior-year rows", "slide 3"),
        QAIssue("thinkcell", INFO, "Chart left for manual fill", "chart:4:1"),
    ))


def test_qa_summary_counts_are_deterministic():
    assert summarize_qa_counts(QAReport()) == "No QA issues — the deck exported clean."
    assert summarize_qa_counts(_report()) == \
        "Export blocked: 1 critical, 1 warning, 1 info issue(s)."


def test_explain_falls_back_to_counts_with_ai_off(monkeypatch):
    monkeypatch.setenv("STUDIO_AI", "off")
    assert explain_qa_report(_report()) == summarize_qa_counts(_report())


def test_explain_discards_prose_naming_banned_peer(monkeypatch):
    monkeypatch.setenv("STUDIO_AI", "auto")
    monkeypatch.setenv("API_KEY", "k")
    monkeypatch.setenv("ENDPOINT", "e")
    import studio.qa.explain as explain
    import studio.ai.deep_agent as deep

    monkeypatch.setattr(deep, "run_deep_agent",
                        lambda *a, **k: "Acme Insurance caused the issue.")
    assert explain_qa_report(_report(), forbidden_names=("Acme Insurance",)) == \
        summarize_qa_counts(_report())


def test_layout_labelling_ignores_ai_when_off(monkeypatch):
    monkeypatch.setenv("STUDIO_AI", "off")
    from studio.template_intelligence.layout_agent import _label_slides_with_ai

    class Descriptor:  # never touched when the gate is closed
        slides = ()

    assert _label_slides_with_ai(Descriptor()) is None


# ── commentary redraft: deep agent preferred, one-shot fallback ───────────────


def _slide_plan_and_pack():
    from studio.commentary.contracts import contract_for
    from studio.commentary.planner import SlideCommentaryPlan
    from studio.content.evidence_pack import EvidenceItem, EvidencePack

    item = EvidenceItem("f_1", "premium_total", 10.0, "$10m", {"scope": "total"})
    pack = EvidencePack(subject="Acme", country=None, period="2025",
                        comparison_period="2024", items={"f_1": item})
    plan = SlideCommentaryPlan(0, "trading_summary", contract_for("trading_summary"),
                               ("f_1",))
    return plan, pack


def _draft():
    from studio.commentary.verify import CommentarySentence

    return (CommentarySentence("Premium was $10m.", ("f_1",)),)


def test_commentary_redraft_prefers_deep_agent(monkeypatch):
    monkeypatch.setenv("STUDIO_AI", "auto")
    monkeypatch.setenv("API_KEY", "k")
    monkeypatch.setenv("ENDPOINT", "e")
    import studio.ai.client as client
    import studio.ai.deep_agent as deep
    from studio.commentary.agent import _redraft_with_ai

    def fake_deep(user, *, response_format, **kwargs):  # noqa: ANN001, ARG001
        return response_format(sentences=[
            {"sentence": "Premium held at $10m.", "fact_ids": ["f_1"]}])

    monkeypatch.setattr(deep, "run_deep_agent", fake_deep)
    monkeypatch.setattr(client, "structured",
                        lambda *a, **k: pytest.fail("one-shot must not run"))
    plan, pack = _slide_plan_and_pack()
    sentences = _redraft_with_ai(plan, pack, _draft())
    assert [s.text for s in sentences] == ["Premium held at $10m."]
    assert sentences[0].fact_ids == ("f_1",)


def test_commentary_redraft_falls_back_to_one_shot(monkeypatch):
    monkeypatch.setenv("STUDIO_AI", "auto")
    monkeypatch.setenv("API_KEY", "k")
    monkeypatch.setenv("ENDPOINT", "e")
    import studio.ai.client as client
    import studio.ai.deep_agent as deep
    from studio.commentary.agent import _redraft_with_ai

    monkeypatch.setattr(deep, "run_deep_agent", lambda *a, **k: None)

    def fake_structured(model, system, user, **kwargs):  # noqa: ANN001, ARG001
        return model(sentences=[
            {"sentence": "Premium stayed at $10m.", "fact_ids": ["f_1"]}])

    monkeypatch.setattr(client, "structured", fake_structured)
    plan, pack = _slide_plan_and_pack()
    sentences = _redraft_with_ai(plan, pack, _draft())
    assert [s.text for s in sentences] == ["Premium stayed at $10m."]
