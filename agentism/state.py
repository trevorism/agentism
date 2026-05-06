"""Agent state dataclasses and text-cleaning helpers."""
import re
from dataclasses import dataclass, field

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def clean_response(text: str) -> str:
    """Strip Qwen3-style <think>…</think> blocks and normalise whitespace."""
    return _THINK_RE.sub("", text).strip()


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens

    def add(self, other: "TokenUsage") -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens


@dataclass
class AgentState:
    thread_id: str
    model: str
    agent: object
    session_history: list = field(default_factory=list)
    session_tokens: TokenUsage = field(default_factory=TokenUsage)
    last_user_input: str = ""


