"""Rendering a signature and its values into the two messages a model is sent.

Pure functions, no LLM: given a :class:`~core.llm.signature.Signature` and the
values for its inputs, produce the system prompt (instructions + the IO contract)
and the user prompt (the labelled values, and any few-shot examples). Keeping this
separate from the call means prompts can be asserted in tests without credentials.

Values are rendered by type: Pydantic models and containers become indented JSON so
nested structure survives, everything else becomes plain text. A field is labelled
with its name and its description, so the model reads the same contract the author
declared rather than a bare blob.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Mapping, Sequence

from pydantic import BaseModel

from core.llm.signature import Example, FieldSpec, Signature

_MISSING = "(not provided)"


def render_value(value: Any) -> str:
    """One value as prompt text — JSON for structure, plain text for scalars."""
    if value is None:
        return _MISSING
    if isinstance(value, BaseModel):
        return value.model_dump_json(indent=2)
    if isinstance(value, str):
        return value.strip() or _MISSING
    if isinstance(value, (Mapping, Sequence, set)):
        try:
            return json.dumps(value, indent=2, default=str, ensure_ascii=False)
        except (TypeError, ValueError):
            return str(value)
    return str(value)


def _labelled(spec: FieldSpec, value: Any) -> str:
    """A field as a titled block: its name, what it is, then its value."""
    header = f"[{spec.name.upper()}]"
    if spec.desc:
        header += f" — {spec.desc}"
    return f"{header}\n{render_value(value)}"


def output_contract(signature: type[Signature]) -> str:
    """The lines telling the model what it must return, by name."""
    lines = [f"- {spec.name}: {spec.desc}" if spec.desc else f"- {spec.name}"
             for spec in signature.outputs]
    return "Return a structured object with these fields:\n" + "\n".join(lines)


def build_system_prompt(signature: type[Signature], *, reasoning: bool = False) -> str:
    """Instructions plus the output contract — the model's standing brief."""
    parts = [signature.instructions, output_contract(signature)]
    if reasoning:
        parts.append(
            "First think the problem through step by step in the `reasoning` field, "
            "then give the remaining fields. The reasoning is working, not the answer."
        )
    return "\n\n".join(part for part in parts if part)


def _render_example(signature: type[Signature], example: Example, index: int) -> str:
    """One few-shot demonstration, labelled the same way a real turn is."""
    shown = [_labelled(spec, example.inputs[spec.name])
             for spec in signature.inputs if spec.name in example.inputs]
    wanted = [f"[{name.upper()}]\n{render_value(value)}"
              for name, value in example.outputs.items()]
    return "\n".join([f"--- Example {index} ---", *shown, "--- Expected output ---", *wanted])


def build_user_prompt(
    signature: type[Signature],
    values: Dict[str, Any],
    *,
    examples: Sequence[Example] = (),
) -> str:
    """The turn's inputs (after any examples), each under its own labelled header."""
    blocks = [_render_example(signature, ex, i) for i, ex in enumerate(examples, start=1)]
    blocks += [_labelled(spec, values.get(spec.name)) for spec in signature.inputs]
    return "\n\n".join(blocks)
