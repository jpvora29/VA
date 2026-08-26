"""The signature layer — declaring a call, rendering it, and reading the answer back.

These cover the contract every migrated node now depends on: the declared fields become
the prompt and the structured-output schema, the model's answer comes back under the
names the signature declared, and token usage is recorded once per call.

No credentials: the chat client is a fake, and both the signature and prompt modules are
pure.
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal

import pytest
from pydantic import BaseModel, Field

from core.llm import Example, InputField, OutputField, Predictor, Signature
from core.llm.predict import build_response_model, run
from core.llm.prompt import build_system_prompt, build_user_prompt, render_value


class Decision(BaseModel):
    verdict: Literal["lookup", "analytical"] = Field(description="the call")
    reason: str = Field(default="", description="one line of justification")


class DepthSignature(Signature):
    """You classify a query as lookup or analytical.

    Prefer lookup when unsure.
    """

    user_query: str = InputField(desc="The question to classify.")
    history: List[str] = InputField(desc="Older turns, oldest first.")
    decision: Decision = OutputField(desc="The decision plus a reason.")


class SentenceSignature(Signature):
    """You rewrite one sentence."""

    draft: str = InputField(desc="The sentence to rewrite.")
    rewritten: str = OutputField(desc="The rewritten sentence.")


# ── fakes ────────────────────────────────────────────────────────────────────


class _FakeRaw:
    usage_metadata = {"input_tokens": 30, "output_tokens": 7, "total_tokens": 37}


class FakeClient:
    """Stands in for AzureChatOpenAI, recording what it was asked for."""

    def __init__(self, answer: Dict[str, Any] | None = None) -> None:
        self.answer = answer or {}
        self.messages: List[Any] = []
        self.schema: Any = None
        self.method: str | None = None

    def with_structured_output(self, model, method=None, include_raw=False):
        assert include_raw, "usage can only be read from the raw response"
        self.schema = model
        self.method = method
        return self

    def invoke(self, messages):
        self.messages = messages
        return {"parsed": self.schema(**self.answer), "raw": _FakeRaw(),
                "parsing_error": None}


# ── declaring a signature ────────────────────────────────────────────────────


def test_the_declared_fields_keep_their_order_types_and_descriptions():
    assert [f.name for f in DepthSignature.inputs] == ["user_query", "history"]
    assert [f.name for f in DepthSignature.outputs] == ["decision"]
    assert DepthSignature.inputs[1].annotation == List[str]
    assert DepthSignature.outputs[0].annotation is Decision
    assert DepthSignature.inputs[0].desc == "The question to classify."


def test_the_docstring_is_the_instructions_with_its_indentation_cleaned():
    assert DepthSignature.instructions.startswith("You classify a query")
    assert "\n    Prefer lookup" not in DepthSignature.instructions
    assert "Prefer lookup when unsure." in DepthSignature.instructions


def test_annotations_resolve_even_though_the_module_defers_them():
    """``from __future__ import annotations`` makes every annotation a string; the
    signature must hand back the real class so a schema can be built from it."""
    assert not isinstance(DepthSignature.outputs[0].annotation, str)


# ── the response schema ──────────────────────────────────────────────────────


def test_the_response_model_mirrors_the_declared_outputs():
    model = build_response_model(DepthSignature)
    assert list(model.model_fields) == ["decision"]
    model.model_json_schema()


def test_chain_of_thought_puts_reasoning_first_so_the_model_works_before_answering():
    model = build_response_model(DepthSignature, reasoning=True)
    assert list(model.model_fields) == ["reasoning", "decision"]


# ── the prompt ───────────────────────────────────────────────────────────────


def test_the_system_prompt_carries_the_instructions_and_the_output_contract():
    system = build_system_prompt(DepthSignature)
    assert "You classify a query" in system
    assert "- decision: The decision plus a reason." in system
    assert "reasoning" not in system


def test_the_reasoning_instruction_appears_only_for_chain_of_thought():
    assert "reasoning" in build_system_prompt(DepthSignature, reasoning=True)


def test_each_input_is_labelled_with_its_name_and_description():
    user = build_user_prompt(DepthSignature, {"user_query": "how is Zurich doing?",
                                              "history": ["premium in 2024"]})
    assert "[USER_QUERY]" in user
    assert "The question to classify." in user
    assert "how is Zurich doing?" in user
    assert '"premium in 2024"' in user          # a list renders as JSON


def test_a_missing_input_is_marked_rather_than_rendered_as_none():
    user = build_user_prompt(DepthSignature, {"user_query": "hi"})
    assert "(not provided)" in user
    assert "None" not in user


def test_a_pydantic_input_renders_as_json_so_its_structure_survives():
    rendered = render_value(Decision(verdict="lookup", reason="one metric"))
    assert '"verdict": "lookup"' in rendered


def test_examples_are_shown_before_the_turn_they_demonstrate():
    user = build_user_prompt(
        DepthSignature, {"user_query": "current"},
        examples=[Example(inputs={"user_query": "past"}, outputs={"decision": "lookup"})],
    )
    assert user.index("--- Example 1 ---") < user.index("current")
    assert "--- Expected output ---" in user


# ── running one ──────────────────────────────────────────────────────────────


def test_the_answer_comes_back_under_the_declared_output_name():
    client = FakeClient({"decision": Decision(verdict="analytical", reason="peers")})
    result = run(DepthSignature, {"user_query": "vs peers?", "history": []}, client=client)
    assert result.decision.verdict == "analytical"
    assert result.decision.reason == "peers"


def test_a_plain_string_output_is_returned_as_a_string():
    client = FakeClient({"rewritten": "A tidier sentence."})
    result = run(SentenceSignature, {"draft": "a sentence"}, client=client)
    assert result.rewritten == "A tidier sentence."


def test_a_prediction_is_also_a_mapping_over_its_fields():
    client = FakeClient({"rewritten": "x"})
    result = run(SentenceSignature, {"draft": "d"}, client=client)
    assert dict(result) == {"rewritten": "x"}


def test_reading_a_field_the_signature_never_declared_raises_attribute_error():
    client = FakeClient({"rewritten": "x"})
    result = run(SentenceSignature, {"draft": "d"}, client=client)
    with pytest.raises(AttributeError):
        result.not_a_field


def test_the_call_records_its_token_usage_once(monkeypatch):
    recorded = []
    import core.llm.predict as predict_module

    monkeypatch.setattr(
        predict_module, "record_token_usage",
        lambda usage, label="", node=None: recorded.append((usage, label, node)),
    )
    client = FakeClient({"rewritten": "x"})
    run(SentenceSignature, {"draft": "d"}, client=client, label="rephraser",
        node="rephraser")
    assert len(recorded) == 1
    usage, label, node = recorded[0]
    assert (usage["input_tokens"], usage["output_tokens"]) == (30, 7)
    assert (label, node) == ("rephraser", "rephraser")


def test_an_unparseable_answer_raises_rather_than_returning_a_half_result():
    class Broken(FakeClient):
        def invoke(self, messages):
            return {"parsed": None, "raw": _FakeRaw(),
                    "parsing_error": ValueError("bad json")}

    with pytest.raises(ValueError, match="did not parse"):
        run(SentenceSignature, {"draft": "d"}, client=Broken())


# ── the schema must reach the model in a mode it can express ─────────────────


def test_the_schema_is_sent_by_tool_calling_not_strict_structured_output():
    """Regression: langchain-openai defaults to `json_schema`, which sends a Pydantic
    class through the OpenAI SDK's STRICT conversion. Azure then rejects any signature
    whose output carries an open-ended map or defaulted nested objects."""
    client = FakeClient({"rewritten": "x"})
    run(SentenceSignature, {"draft": "d"}, client=client)
    assert client.method == "function_calling"


def test_an_open_ended_dict_output_survives_the_conversion_intact():
    """`RoutingContext.resolved_filters` is `Dict[str, List[str]]` keyed by arbitrary
    column names. Strict mode cannot express that; tool calling must keep it, or the
    context filler silently loses every resolved filter."""
    import json

    from langchain_core.utils.function_calling import convert_to_openai_function

    from core.schemas.routing import ContextFillerSignature

    model = build_response_model(ContextFillerSignature, reasoning=True)
    schema = convert_to_openai_function(model)["parameters"]

    routing = schema["properties"]["routing_context"]["properties"]
    resolved = routing["resolved_filters"]
    assert resolved["type"] == "object"
    # The map's VALUE schema is still a list-of-strings, not stripped to nothing.
    assert resolved["additionalProperties"] == {"type": "array",
                                                "items": {"type": "string"}}
    assert json.dumps(schema)      # and the whole thing is wire-serialisable


def test_every_signature_converts_for_the_wire():
    """No signature may produce a schema the client cannot send — a failure here is a
    hard 400 at request time, not a degraded answer."""
    import importlib
    import inspect as _inspect
    import json

    from langchain_core.utils.function_calling import convert_to_openai_function

    from core.llm.signature import Signature as _Signature

    modules = [
        "core.schemas.routing", "core.schemas.analytical", "core.schemas.boardroom",
        "core.schemas.combined", "core.schemas.followup", "core.schemas.gimmi",
        "core.schemas.gpr", "core.schemas.hitl", "core.schemas.survey",
        "core.schemas.analysis", "core.context.semantic",
        "core.agents.common.chart_spec",
    ]
    checked = 0
    for name in modules:
        module = importlib.import_module(name)
        for attr, obj in vars(module).items():
            if not (_inspect.isclass(obj) and issubclass(obj, _Signature)
                    and obj is not _Signature and obj.__module__ == name):
                continue
            for reasoning in (False, True):
                model = build_response_model(obj, reasoning=reasoning)
                json.dumps(convert_to_openai_function(model))
                checked += 1
    assert checked == 48, f"expected 24 signatures x 2 modes, converted {checked}"


# ── the predictor a node holds ───────────────────────────────────────────────


def test_a_predictor_passes_its_signature_inputs_straight_through():
    client = FakeClient({"decision": Decision(verdict="lookup")})
    predictor = Predictor(DepthSignature, tier="fast", reasoning=True, node="intent")
    result = predictor(client=client, user_query="AXA NPS?", history=[])
    assert result.decision.verdict == "lookup"
    assert result.reasoning == ""
    assert list(client.schema.model_fields) == ["reasoning", "decision"]


def test_with_examples_returns_a_copy_rather_than_mutating_the_shared_predictor():
    predictor = Predictor(DepthSignature)
    demoed = predictor.with_examples([Example(inputs={"user_query": "q"},
                                              outputs={"decision": "lookup"})])
    assert predictor.examples == ()
    assert len(demoed.examples) == 1
    assert demoed.signature is predictor.signature
