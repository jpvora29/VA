"""Running a signature against a LangChain chat model.

This is the single place a declared :class:`~core.llm.signature.Signature` becomes an
actual model call. It builds the two messages (:mod:`core.llm.prompt`), derives the
structured-output model from the signature's declared outputs, invokes the tier's
LangChain client, and records the call's token usage — so no node has to assemble a
prompt, a response schema, or a usage log for itself.

A node holds a :class:`Predictor` — a signature bound to a tier — and calls it with
the signature's input names. Setting ``reasoning=True`` prepends a ``reasoning``
field so the model works the problem through before committing, which is what the
routing, planning and depth-classification steps need.

The result is a :class:`Prediction` whose attributes are the signature's output
names, so a node reads ``result.plan`` or ``result.routing_context`` exactly as it
declared them.

The client is resolved lazily by tier, so importing this module never constructs an
Azure client or requires credentials.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Sequence, Type

from pydantic import BaseModel, Field, create_model

from core.llm.prompt import build_system_prompt, build_user_prompt
from core.llm.signature import Example, Signature
from core.observability import extract_token_usage, record_token_usage

REASONING_FIELD = "reasoning"

# How the schema is put to the model. `function_calling` (tool calling) is a
# deliberate choice over langchain-openai's `json_schema` default, which sends
# OpenAI/Azure *strict* structured outputs — a mode these signatures cannot express:
#
#   * Strict requires every object's `required` to list every one of its properties.
#     Our output models are almost entirely defaulted fields, and LangChain's strict
#     fixer only patches the TOP level, so nested objects (`query_intent`,
#     `output_directives`, `entities`) arrive with no `required` at all and Azure
#     rejects the request.
#   * Strict has no way to express an open-ended map. `RoutingContext.resolved_filters`
#     and `QueryIntent.filters` are `Dict[str, List[str]]` keyed by arbitrary column
#     names; strict demands fixed properties + `additionalProperties: false`, so the
#     map is stripped to an empty object.
#
# Tool calling keeps optional fields optional and open-ended dicts intact, which is
# what these models were written for.
STRUCTURED_OUTPUT_METHOD = "function_calling"


class Prediction(Mapping):
    """One model answer, addressed by the signature's output names.

    Also a mapping, so a caller can iterate the fields it got without knowing the
    signature — used by the widget/boardroom code that keys results by field name.
    """

    def __init__(self, values: Dict[str, Any]) -> None:
        self._values = dict(values)

    def __getattr__(self, name: str) -> Any:
        try:
            return self._values[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __getitem__(self, key: str) -> Any:
        return self._values[key]

    def __iter__(self):
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __repr__(self) -> str:
        return f"Prediction({self._values!r})"


def tier_client(tier: str):
    """The chat client a tier's calls go through, for the chatbot graph.

    Deliberately reads the `Initialization` singletons rather than calling
    :func:`core.llm.clients.make_client` directly. They are the same objects — every
    one is built by that factory — but going through the singletons is the seam a test
    patches to intercept a node's calls. Studio and MoM, which must not construct the
    chatbot's database engine, call ``make_client`` instead.

    Imported lazily so this module stays credential-free at import.
    """
    from core.initialization import Initialization

    return {
        "reason": lambda: Initialization.llm_reason,
        "balanced": lambda: Initialization.llm_balanced,
        "fast": lambda: Initialization.llm_fast,
        "creative": lambda: Initialization.llm_creative,
    }.get(tier, lambda: Initialization.llm_balanced)()


def build_response_model(
    signature: Type[Signature], *, reasoning: bool = False
) -> Type[BaseModel]:
    """A Pydantic model of the signature's outputs — the structured-output schema.

    A leading ``reasoning`` field is added for chain-of-thought so the model writes
    its working before the answer, the way the field order asks it to.
    """
    fields: Dict[str, Any] = {}
    if reasoning:
        fields[REASONING_FIELD] = (
            str,
            Field(default="", description="Step-by-step working behind the answer."),
        )
    for spec in signature.outputs:
        fields[spec.name] = (spec.annotation, Field(description=spec.desc or spec.name))
    return create_model(f"{signature.__name__}Response", **fields)


@dataclass(frozen=True)
class Predictor:
    """A signature bound to a tier — callable with the signature's input names.

    Held as an attribute on a node the same way the old predictors were, so a node
    still declares its call once in ``__init__`` and invokes it per turn.
    """

    signature: Type[Signature]
    tier: str = "balanced"
    reasoning: bool = False
    label: str = ""
    node: str = ""
    examples: Sequence[Example] = ()

    def with_examples(self, examples: Sequence[Example]) -> "Predictor":
        """A copy carrying few-shot demonstrations (the old ``.demos`` seam)."""
        return Predictor(self.signature, self.tier, self.reasoning, self.label,
                         self.node, tuple(examples))

    def __call__(self, *, client: Optional[Any] = None, **values: Any) -> Prediction:
        return run(self.signature, values, tier=self.tier, reasoning=self.reasoning,
                   examples=self.examples, label=self.label or self.signature.__name__,
                   node=self.node, client=client)


def run(
    signature: Type[Signature],
    values: Dict[str, Any],
    *,
    tier: str = "balanced",
    reasoning: bool = False,
    examples: Sequence[Example] = (),
    label: str = "",
    node: str = "",
    client: Optional[Any] = None,
) -> Prediction:
    """Invoke one signature and return its outputs. Raises if the model's answer
    cannot be parsed into the declared schema — a caller that can carry on without
    it should catch, as the callers of an unparseable answer always had to."""
    from langchain_core.messages import HumanMessage, SystemMessage

    response_model = build_response_model(signature, reasoning=reasoning)
    chat = (client or tier_client(tier)).with_structured_output(
        response_model, method=STRUCTURED_OUTPUT_METHOD, include_raw=True
    )
    result = chat.invoke([
        SystemMessage(content=build_system_prompt(signature, reasoning=reasoning)),
        HumanMessage(content=build_user_prompt(signature, values, examples=examples)),
    ])
    parsed, raw = _unpack(result)
    record_token_usage(extract_token_usage(raw), label=label or signature.__name__,
                       node=node or None)
    return Prediction(_fields(parsed))


def _unpack(result: Any) -> tuple[Any, Any]:
    """Split LangChain's ``include_raw`` envelope into (parsed, raw message)."""
    if not isinstance(result, dict):
        return result, result
    error = result.get("parsing_error")
    if error:
        raise ValueError(f"structured output did not parse: {error}")
    parsed = result.get("parsed")
    if parsed is None:
        raise ValueError("structured output returned no parsed value")
    return parsed, result.get("raw")


def _fields(parsed: Any) -> Dict[str, Any]:
    """The parsed model's fields, keeping nested models as models (not dicts)."""
    if isinstance(parsed, BaseModel):
        return {name: getattr(parsed, name) for name in type(parsed).model_fields}
    return dict(parsed or {})

