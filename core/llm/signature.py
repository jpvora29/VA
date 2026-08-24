"""Declarative LLM signatures — the typed IO contract for one model call.

A *signature* is what a node asks the model for: prose instructions, the named
inputs it will be given, and the named outputs it must return. Declaring it keeps
the contract in one readable place instead of scattering prompt f-strings through
node code, and it is what lets :mod:`core.llm.predict` build the messages and the
structured-output model without the caller assembling either.

The shape is deliberately the one this codebase already reads::

    class DepthClassifierSignature(Signature):
        \"\"\"[ROLE] You classify a query as lookup or analytical...\"\"\"

        current_user_query: str = InputField(desc="The question to classify.")
        depth_decision: DepthDecision = OutputField(desc="The decision plus a reason.")

The class docstring is the instructions. Annotations carry the types — a plain
``str``, a ``List[str]``, or a Pydantic model for structured output. Declaration
order is preserved, so prompts render in the order the author wrote them.

Annotations are resolved on first read, not at class creation: every schema module
here uses ``from __future__ import annotations``, so the raw annotation is the
string ``"RoutingContext"``, and a model can only be built from the real class.
Deferring also lets a signature reference a model defined below it.

Pure and dependency-free on purpose: nothing here imports LangChain or calls a
model, so signatures can be inspected and unit-tested without credentials.
"""
from __future__ import annotations

from dataclasses import dataclass
from inspect import cleandoc
from typing import Any, Dict, Tuple, get_type_hints


@dataclass(frozen=True)
class InputField:
    """One value the node will supply to the model."""

    desc: str = ""


@dataclass(frozen=True)
class OutputField:
    """One value the model must return."""

    desc: str = ""


@dataclass(frozen=True)
class FieldSpec:
    """A resolved field — its name, declared type, and description."""

    name: str
    annotation: Any
    desc: str = ""


def _declared(namespace: Dict[str, Any], kind: type) -> Tuple[Tuple[str, str], ...]:
    """The (name, description) pairs of one field kind, in declaration order."""
    return tuple((name, field.desc) for name, field in namespace.items()
                 if isinstance(field, kind))


class SignatureMeta(type):
    """Records the declared fields, and resolves their types on first read."""

    def __new__(mcls, name, bases, namespace, **kwargs):
        cls = super().__new__(mcls, name, bases, namespace, **kwargs)
        cls._declared_inputs = _declared(namespace, InputField)
        cls._declared_outputs = _declared(namespace, OutputField)
        cls.instructions = cleandoc(namespace.get("__doc__") or "").strip()
        return cls

    def _resolved(cls) -> Dict[str, Tuple[FieldSpec, ...]]:
        """Both field tuples with real types, resolved once and cached per class."""
        cached = cls.__dict__.get("_field_specs")
        if cached is None:
            hints = get_type_hints(cls)
            cached = {
                kind: tuple(FieldSpec(name, hints.get(name, str), desc)
                            for name, desc in declared)
                for kind, declared in (("inputs", cls._declared_inputs),
                                       ("outputs", cls._declared_outputs))
            }
            cls._field_specs = cached
        return cached

    @property
    def inputs(cls) -> Tuple[FieldSpec, ...]:
        return cls._resolved()["inputs"]

    @property
    def outputs(cls) -> Tuple[FieldSpec, ...]:
        return cls._resolved()["outputs"]


class Signature(metaclass=SignatureMeta):
    """Base class for a declared LLM call contract.

    Subclasses set the docstring (instructions) and declare annotated
    `InputField` / `OutputField` attributes; the metaclass exposes them as
    `inputs`, `outputs` and `instructions`.
    """

    instructions: str = ""


@dataclass(frozen=True)
class Example:
    """One few-shot demonstration: the inputs given, and the outputs wanted.

    Replaces the ``dspy.Example(...).with_inputs(...)`` pairing with a single
    explicit split, so a demo cannot silently lose its input/output labelling.
    """

    inputs: Dict[str, Any]
    outputs: Dict[str, Any]
