"""Optional extension point. No provider SDK, network call, or key is required."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class LLMResponse:
    text: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int


class LLMAdapter(Protocol):
    """Future Gemini or other adapters must return structured usage metadata.

    The deterministic engine must never depend on an adapter being configured.
    """

    def complete(self, *, system_prompt: str, user_prompt: str) -> LLMResponse: ...
