from typing import Any
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ToolCallRequest:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    content: str | None
    toolCalls: list[ToolCallRequest] = field(default_factory=list)
    finishReason: str = "stop"
    usage: dict[str, int] = field(default_factory=dict)
    reasoningContent: str | None = None

    @property
    def hasToolCalls(self) -> bool:
        return len(self.toolCalls) > 0

    def formatToolHint(self) -> str:
        def inner(tc):
            args = (tc.arguments[0] if isinstance(tc.arguments, list) else tc.arguments) or {}
            val = next(iter(args.values()), None) if isinstance(args, dict) else None
            if not isinstance(val, str):
                return tc.name
            return f'{tc.name}("{val[:40]}…")' if len(val) > 40 else f'{tc.name}("{val}")'
        return ", ".join(inner(tc) for tc in self.toolCalls)


class PhiloLlmBase(ABC):
    @abstractmethod
    async def chat(self, messages, tools=None, **kwargs) -> LLMResponse:
        pass
