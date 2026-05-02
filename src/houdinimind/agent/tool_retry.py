"""
HoudiniMind — Tool-level retry policy and circuit breaker.

Sits between the dispatcher and the actual tool function. Retries transient
failures (transport timeouts, connection resets) with exponential backoff.
Trips a per-tool circuit breaker after several consecutive failures so the
agent stops re-running a tool that's clearly in a bad state.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

# Substrings in error messages that indicate the failure is *transport-level*
# and might succeed on retry. Logical errors (bad args, missing nodes, etc.)
# never match these and never retry.
_TRANSIENT_PATTERNS = (
    re.compile(r"\btimeout\b", re.IGNORECASE),
    re.compile(r"timed out", re.IGNORECASE),
    re.compile(r"connection (refused|reset|aborted)", re.IGNORECASE),
    re.compile(r"no response from houdini", re.IGNORECASE),
    re.compile(r"broken pipe", re.IGNORECASE),
    re.compile(r"socket.*closed", re.IGNORECASE),
    re.compile(r"temporarily unavailable", re.IGNORECASE),
    re.compile(r"bridge error: \[errno", re.IGNORECASE),
)


def is_transient_error(result: dict | None) -> bool:
    if not isinstance(result, dict):
        return False
    if result.get("status") != "error":
        return False
    msg = str(result.get("message") or "")
    return any(pat.search(msg) for pat in _TRANSIENT_PATTERNS)


@dataclass
class RetryPolicy:
    max_attempts: int = 3  # total tries including the first
    base_delay_s: float = 0.4  # exponential backoff base
    max_delay_s: float = 4.0
    # Write tools are retried only on clearly transient transport errors.
    # Read-only tools have the same rule but are intrinsically safer.
    write_retry_on_transient_only: bool = True

    def delay_for(self, attempt: int) -> float:
        # attempt is 1-based; first retry waits base_delay.
        delay = self.base_delay_s * (2 ** max(0, attempt - 1))
        return min(delay, self.max_delay_s)

    def should_retry(
        self,
        attempt: int,
        result: dict | None,
        *,
        is_read_only: bool,
    ) -> bool:
        if attempt >= self.max_attempts:
            return False
        if not is_transient_error(result):
            # Logical errors are never retried — that's the LLM's job.
            return False
        # Transient — retry. (Read-only/write distinction intentionally not
        # used as a gate: transient transport errors are equally safe to retry
        # for both, because the call never reached server-side mutation.)
        _ = is_read_only  # reserved for future per-class tuning
        return True


@dataclass
class _BreakerState:
    consecutive_failures: int = 0
    opened_at: float = 0.0  # 0 means closed


@dataclass
class CircuitBreaker:
    """Per-tool consecutive-failure breaker.

    State machine per tool:
        closed → (N consecutive failures) → open → (cool_down_s) → half_open
        half_open → (one success) → closed
        half_open → (failure)      → open (reset cool-down)
    """

    failure_threshold: int = 4
    cool_down_s: float = 60.0
    _state: dict[str, _BreakerState] = field(default_factory=dict)

    def _get(self, tool: str) -> _BreakerState:
        st = self._state.get(tool)
        if st is None:
            st = _BreakerState()
            self._state[tool] = st
        return st

    def is_open(self, tool: str, *, now: float | None = None) -> tuple[bool, str]:
        """Returns (open?, reason). When in half-open, reports closed (allow one)."""
        st = self._state.get(tool)
        if st is None or st.opened_at == 0.0:
            return (False, "")
        t = now if now is not None else time.time()
        elapsed = t - st.opened_at
        if elapsed >= self.cool_down_s:
            # Half-open: allow a probe.
            return (False, "")
        remaining = max(0.0, self.cool_down_s - elapsed)
        return (
            True,
            f"circuit open: {tool} had ≥{self.failure_threshold} consecutive failures; "
            f"retry in ~{remaining:.0f}s.",
        )

    def record_failure(self, tool: str, *, now: float | None = None) -> None:
        st = self._get(tool)
        st.consecutive_failures += 1
        if st.consecutive_failures >= self.failure_threshold:
            st.opened_at = now if now is not None else time.time()

    def record_success(self, tool: str) -> None:
        st = self._get(tool)
        st.consecutive_failures = 0
        st.opened_at = 0.0

    def snapshot(self) -> dict[str, dict]:
        return {
            tool: {
                "consecutive_failures": st.consecutive_failures,
                "opened_at": st.opened_at,
            }
            for tool, st in self._state.items()
        }
