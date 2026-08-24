"""Every LLM call in this repo is a LangChain call.

The app used to run two model stacks side by side: LangChain for the analyst and Studio
paths, and dspy for the chatbot's signature-driven nodes — with
``core.initialization`` constructing ``dspy.LM`` objects and calling
``dspy.configure(...)`` as an import side effect. The nodes now declare the same typed
contracts through :mod:`core.llm.signature` and run them over LangChain, so dspy is gone
entirely.

These tests pin that: no module imports dspy, the packaging no longer depends on it, and
the shared tier factory both callers use carries the model config the old clients did.

No API key is needed anywhere here — the client is a fake, and tier resolution is pure.
"""
from __future__ import annotations

import subprocess
import sys

import pytest

from core.llm import clients as llm


@pytest.fixture(autouse=True)
def _clean_client_cache():
    """Each test resolves against its own env, not a client another one cached."""
    llm.reset_clients()
    yield
    llm.reset_clients()


@pytest.fixture
def azure_env(monkeypatch):
    """Credentials present and Studio AI on, without any per-tier deployment set."""
    for var in ("MODEL_TIERS", "REASON_DEPLOYMENT", "BALANCED_DEPLOYMENT",
                "FAST_DEPLOYMENT", "REASON_EFFORT", "REASON_VERBOSITY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("STUDIO_AI", "auto")
    monkeypatch.setenv("API_KEY", "k")
    monkeypatch.setenv("ENDPOINT", "https://example.invalid")
    monkeypatch.setenv("VERSION", "2024-10-01")
    monkeypatch.setenv("DEPLOYMENT", "base-deployment")


# ── the point of the change: dspy is gone ────────────────────────────────────


def test_loading_the_llm_path_pulls_in_neither_dspy_nor_credentials():
    """A cold interpreter that loads the signatures and the nodes that run them must
    import dspy nowhere — and must not need an Azure key to do it, because the tier
    client is resolved at call time rather than at import.

    This runs in a subprocess on purpose: by the time the rest of the suite has run,
    another test may already have imported dspy, and an in-process check would pass for
    the wrong reason.
    """
    probe = (
        "import sys;"
        "import core.llm, core.schemas.routing, core.schemas.boardroom, core.schemas.analytical;"
        "import core.agents.rephraser, core.agents.intent_classifier, core.agents.boardroom;"
        "import core.agents.common.planner, core.agents.common.sql_agent, core.analysis.planner;"
        "import core.context.semantic;"
        "import studio.ai, studio.template_fill.commentary_writer, studio.commentary.agent;"
        "print('dspy' in sys.modules, 'core.initialization' in sys.modules)"
    )
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True,
                         check=True).stdout.strip()
    assert out == "False False"


def test_no_module_references_dspy_in_code():
    """No executable line in the source tree names dspy, so it cannot creep back.

    Checked against the parsed source rather than the raw text: a few docstrings mention
    dspy to explain what replaced it, and those should not trip this.
    """
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    offenders = []
    for folder in ("core", "studio", "tests", "ui"):
        for path in (root / folder).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
            names |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names |= {a.name.split(".")[0] for a in node.names}
                elif isinstance(node, ast.ImportFrom):
                    names.add((node.module or "").split(".")[0])
            if "dspy" in names:
                offenders.append(str(path.relative_to(root)))
    assert offenders == []


def test_dspy_is_not_a_declared_dependency():
    """The packaging must not reinstall what the code no longer uses."""
    from pathlib import Path

    pyproject = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(
        encoding="utf-8"
    )
    dependencies = pyproject.split("[project]", 1)[-1].split("[", 1)[0]
    assert "dspy" not in dependencies


# ── tier resolution matches what core.initialization applied ─────────────────


def test_tiers_off_gives_the_expressive_client_to_reason_only(azure_env):
    assert llm.resolve_tier("reason") == llm.TierConfig("base-deployment", temperature=0.4)
    assert llm.resolve_tier("balanced") == llm.TierConfig("base-deployment", temperature=0.0)
    assert llm.resolve_tier("fast") == llm.TierConfig("base-deployment", temperature=0.0)


def test_an_unknown_tier_reads_as_balanced(azure_env):
    assert llm.resolve_tier("nonsense") == llm.resolve_tier("balanced")


def test_the_creative_tier_stays_warm_whether_or_not_tiers_are_on(azure_env, monkeypatch):
    """The prose nodes' client is the base deployment run warm — never a reasoning
    model, so turning tiers on must not quietly re-point or cool it."""
    warm = llm.TierConfig("base-deployment", temperature=0.4)
    assert llm.resolve_tier("creative") == warm
    monkeypatch.setenv("MODEL_TIERS", "on")
    monkeypatch.setenv("REASON_DEPLOYMENT", "gpt-5-mini")
    assert llm.resolve_tier("creative") == warm


def test_a_tier_with_its_own_deployment_gets_reasoning_params(azure_env, monkeypatch):
    monkeypatch.setenv("MODEL_TIERS", "on")
    monkeypatch.setenv("REASON_DEPLOYMENT", "gpt-5-mini")
    monkeypatch.setenv("REASON_EFFORT", "high")
    monkeypatch.setenv("REASON_VERBOSITY", "low")
    config = llm.resolve_tier("reason")
    assert config == llm.TierConfig("gpt-5-mini", effort="high", verbosity="low")
    assert config.temperature is None          # reasoning models reject one


def test_a_tier_falling_back_to_the_base_deployment_sends_no_effort(azure_env, monkeypatch):
    """The base deployment is a classic model; ``reasoning_effort`` would 400 it."""
    monkeypatch.setenv("MODEL_TIERS", "on")
    config = llm.resolve_tier("fast")
    assert config == llm.TierConfig("base-deployment", temperature=0.0)


def test_effort_can_be_switched_off_on_a_tiered_deployment(azure_env, monkeypatch):
    monkeypatch.setenv("MODEL_TIERS", "on")
    monkeypatch.setenv("REASON_DEPLOYMENT", "gpt-5-mini")
    monkeypatch.setenv("REASON_EFFORT", "none")
    assert llm.resolve_tier("reason") == llm.TierConfig("gpt-5-mini", temperature=0.0)


def test_client_kwargs_carry_the_credentials_and_latency_guards(azure_env, monkeypatch):
    monkeypatch.setenv("LLM_TIMEOUT", "12")
    monkeypatch.setenv("LLM_MAX_RETRIES", "5")
    kwargs = llm._client_kwargs(llm.resolve_tier("balanced"))
    assert kwargs["azure_deployment"] == "base-deployment"
    assert kwargs["azure_endpoint"] == "https://example.invalid"
    assert kwargs["api_version"] == "2024-10-01"
    assert (kwargs["timeout"], kwargs["max_retries"]) == (12.0, 5)
    assert kwargs["temperature"] == 0.0
    assert "reasoning_effort" not in kwargs


def test_the_same_config_is_only_built_once(azure_env):
    assert llm.make_client("balanced") is llm.make_client("fast")
    assert llm.make_client("reason") is not llm.make_client("balanced")


# ── the wrapper still routes through the tier client ─────────────────────────


def test_structured_calls_go_through_the_shared_factory(azure_env, monkeypatch):
    """`studio.ai.client.structured` must build its client from the shared factory."""
    from pydantic import BaseModel

    import studio.ai.client as client

    class Answer(BaseModel):
        text: str

    seen = {}

    class FakeStructured:
        def invoke(self, messages):
            seen["messages"] = messages
            return Answer(text="written")

    class FakeClient:
        def with_structured_output(self, model):
            seen["model"] = model
            return FakeStructured()

    def fake_make_client(tier):
        seen["tier"] = tier
        return FakeClient()

    monkeypatch.setattr(llm, "make_client", fake_make_client)
    result = client.structured(Answer, "system prompt", "user prompt", tier="fast")
    assert result.text == "written"
    assert seen["tier"] == "fast"
    assert seen["model"] is Answer
    assert [m.content for m in seen["messages"]] == ["system prompt", "user prompt"]


def test_an_unavailable_llm_short_circuits_before_any_client_is_built(monkeypatch):
    import studio.ai.client as client

    monkeypatch.setenv("STUDIO_AI", "off")
    monkeypatch.setattr(llm, "make_client",
                        lambda tier: pytest.fail("a client was built with AI off"))
    assert client.generate("s", "u") is None
    assert client.structured(object, "s", "u") is None
