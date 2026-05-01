from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class ProviderResponse:
    text: str
    tool_calls: list[dict[str, Any]]
    raw: dict[str, Any]
    latency_ms: float


class LLMProvider(ABC):
    model: str

    @abstractmethod
    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        **kwargs: Any,
    ) -> ProviderResponse:
        raise NotImplementedError