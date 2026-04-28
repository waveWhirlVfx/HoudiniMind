# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
"""
HoudiniMind — Degradation Tracker
Surfaces silent failures so the user knows when subsystems are degraded.
"""

import time
from collections.abc import Callable


class DegradationTracker:
    """
    Tracks subsystem degradations and notifies the stream callback.
    Each degradation is reported once per session to avoid spam.
    """

    def __init__(self):
        self._reported: dict[str, float] = {}  # key -> timestamp
        self._active: dict[str, str] = {}  # key -> message
        self._cooldown_s = 300  # Don't re-report same issue within 5 minutes

    def report(self, key: str, message: str, stream_callback: Callable | None = None):
        """Report a degradation. Only emits to UI if not recently reported."""
        now = time.time()
        last = self._reported.get(key, 0)
        self._active[key] = message

        if now - last < self._cooldown_s:
            return  # Already reported recently

        self._reported[key] = now
        if stream_callback:
            stream_callback(f"\u200b\u26a0 {message}\n")

    def resolve(self, key: str, stream_callback: Callable | None = None):
        """Mark a degradation as resolved."""
        if key in self._active:
            del self._active[key]
            if stream_callback:
                stream_callback(f"\u200b\u2713 Resolved: {key}\n")

    def get_active(self) -> dict[str, str]:
        """Get currently active degradations."""
        return dict(self._active)

    def summary(self) -> str:
        """One-line summary of active degradations."""
        if not self._active:
            return ""
        return f"[{len(self._active)} degraded: {', '.join(self._active.keys())}]"
