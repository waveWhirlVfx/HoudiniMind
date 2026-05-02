"""
HoudiniMind — Per-turn wall-clock and token budgets.

Hard limits that abort a turn cleanly when exceeded, instead of letting it run
unbounded. Counts:
  - wall-clock seconds since the turn began
  - input tokens sent to the LLM
  - output tokens received from the LLM

Each round of the tool loop checks the budget before issuing the next LLM
call; on exhaustion the loop breaks with a structured reason that callers can
surface to the user.
"""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class TurnBudget:
    wall_clock_s: float = 180.0
    max_input_tokens: int = 120_000
    max_output_tokens: int = 16_000
    enabled: bool = True

    _started_at: float = 0.0
    input_tokens_used: int = 0
    output_tokens_used: int = 0

    def start(self) -> None:
        self._started_at = time.time()
        self.input_tokens_used = 0
        self.output_tokens_used = 0

    def record_tokens(self, *, in_tokens: int = 0, out_tokens: int = 0) -> None:
        if in_tokens > 0:
            self.input_tokens_used += in_tokens
        if out_tokens > 0:
            self.output_tokens_used += out_tokens

    def elapsed_s(self) -> float:
        if self._started_at <= 0:
            return 0.0
        return max(0.0, time.time() - self._started_at)

    def time_remaining_s(self) -> float:
        return max(0.0, self.wall_clock_s - self.elapsed_s())

    def is_exhausted(self) -> tuple[bool, str]:
        """Returns (exhausted?, reason). Reason is empty string when not exhausted."""
        if not self.enabled:
            return (False, "")
        if self._started_at <= 0:
            return (False, "")
        if self.elapsed_s() >= self.wall_clock_s:
            return (
                True,
                f"wall-clock budget exhausted: {self.elapsed_s():.1f}s ≥ {self.wall_clock_s:.0f}s.",
            )
        if self.input_tokens_used >= self.max_input_tokens:
            return (
                True,
                f"input-token budget exhausted: "
                f"{self.input_tokens_used} ≥ {self.max_input_tokens}.",
            )
        if self.output_tokens_used >= self.max_output_tokens:
            return (
                True,
                f"output-token budget exhausted: "
                f"{self.output_tokens_used} ≥ {self.max_output_tokens}.",
            )
        return (False, "")

    def snapshot(self) -> dict:
        return {
            "elapsed_s": round(self.elapsed_s(), 2),
            "wall_clock_s": self.wall_clock_s,
            "input_tokens_used": self.input_tokens_used,
            "max_input_tokens": self.max_input_tokens,
            "output_tokens_used": self.output_tokens_used,
            "max_output_tokens": self.max_output_tokens,
            "enabled": self.enabled,
        }
