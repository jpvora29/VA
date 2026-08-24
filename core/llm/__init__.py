"""LangChain-backed LLM calls declared as typed signatures.

Three small pieces, each usable on its own:

* :mod:`core.llm.signature` — declare a call's instructions, inputs and outputs.
* :mod:`core.llm.prompt` — render a signature and its values into messages (pure).
* :mod:`core.llm.predict` — run one against a tier's LangChain client.
* :mod:`core.llm.clients` — resolve a tier name to its Azure chat client.

Nodes declare a `Signature`, hold a `Predictor`, and read results by output name.
Only `predict` touches LangChain, and only when called, so importing a signature
never needs credentials.
"""
from __future__ import annotations

from core.llm.predict import Prediction, Predictor, run, tier_client
from core.llm.signature import Example, InputField, OutputField, Signature

__all__ = [
    "Signature", "InputField", "OutputField", "Example",
    "Predictor", "Prediction", "run", "tier_client",
]
