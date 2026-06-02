from langchain_openai import AzureChatOpenAI
from dataclasses import dataclass, field
from typing import Optional, Callable, TypeAlias
import os
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class BaseLLMConfig:
    model: str
    api_key: str = field(default_factory=lambda: os.environ["API_KEY"])
    temperature: float = 0.0
    max_tokens: Optional[int] = None
    api_version: str = field(default_factory=lambda: os.environ["VERSION"])


@dataclass(BaseLLMConfig)
class LLMConfig:
    azure_deployment: str = field(default_factory=lambda: os.environ["DEPLOYMENT"])
    azure_endpoint: str = field(default_factory=lambda: os.environ["ENDPOINT"])


@dataclass(frozen=True)
class DSPyConfig:
    api_base: str = field(default_factory=os.environ["ENDPOINT"])


LLMConfigLoader: TypeAlias = Callable[[str | int | float], LLMConfig]
DSPyConfigLoader: TypeAlias = Callable[[str | int | float], DSPyConfig]


def load_llm_config(
    model: str = "gpt-41-mini",
    temperature: float = 0.0,
) -> LLMConfig:
    return LLMConfig(model=model, temperature=temperature)


def load_dspy_config(
    model: str = f"azure/{os.environ['DEPLOYMENT']}",
    temperature: float = 0.0,
) -> DSPyConfig:
    return DSPyConfig(model=model, temperature=temperature)
