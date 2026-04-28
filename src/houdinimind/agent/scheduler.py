# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
"""
HoudiniMind — Scheduled AutoResearch
Runs autonomous research loops on a configurable cron-style schedule.

Usage (from panel backend):
    from houdinimind.agent.scheduler import ResearchScheduler
    scheduler = ResearchScheduler(agent, memory, config, stream_cb)
    scheduler.start()   # begins background scheduling thread
    scheduler.stop()    # clean shutdown

Config keys (core_config.json):
    schedule_enabled        bool   — master on/off switch (default: false)
    schedule_interval_h     float  — hours between runs (default: 24)
    schedule_topics         list   — list of research topic strings
    schedule_run_at_startup bool   — run once immediately on startup (default: false)
"""

from __future__ import annotations

import threading
import time
import traceback
from collections.abc import Callable


class ResearchScheduler:
    """
    Background thread that fires AutoResearch on a fixed interval.
    Thread-safe: start/stop can be called from any thread.
    """

    def __init__(
        self,
        agent,
        memory,
        config: dict,
        stream_callback: Callable | None = None,
        status_callback: Callable | None = None,
    ):
        self.agent = agent
        self.memory = memory
        self.config = config
        self.stream_cb = stream_callback
        self.status_cb = status_callback

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_run_ts: float = 0.0
        self._run_count: int = 0
        self._lock = threading.Lock()

    # ── Public API ────────────────────────────────────────────────────

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop,
            daemon=True,
            name="houdinimind-scheduler",
        )
        self._thread.start()
        print("[HoudiniMind Scheduler] Started.")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        print("[HoudiniMind Scheduler] Stopped.")

    def trigger_now(self) -> None:
        """Fire a research run immediately (outside the normal schedule)."""
        threading.Thread(
            target=self._run_research,
            daemon=True,
            name="houdinimind-scheduler-manual",
        ).start()

    def stats(self) -> dict:
        with self._lock:
            return {
                "enabled": self.config.get("schedule_enabled", False),
                "interval_h": self.config.get("schedule_interval_h", 24),
                "last_run_ts": self._last_run_ts,
                "run_count": self._run_count,
                "next_run_in_s": max(0, (self._last_run_ts + self._interval_s()) - time.time())
                if self._last_run_ts
                else 0,
            }

    # ── Internal ──────────────────────────────────────────────────────

    def _interval_s(self) -> float:
        return float(self.config.get("schedule_interval_h", 24)) * 3600

    def _topics(self) -> list[str]:
        topics = self.config.get("schedule_topics") or []
        if not topics:
            topics = [
                "Houdini SOP node updates and new procedural techniques",
                "Houdini VEX tips and performance optimizations",
                "Houdini simulation best practices",
            ]
        return topics

    def _loop(self) -> None:
        # Optionally run immediately at startup
        if self.config.get("schedule_run_at_startup", False):
            self._run_research()

        while not self._stop_event.is_set():
            interval = self._interval_s()
            # Sleep in small increments so stop() is responsive
            elapsed = 0.0
            tick = 30.0
            while elapsed < interval and not self._stop_event.is_set():
                self._stop_event.wait(timeout=min(tick, interval - elapsed))
                elapsed += tick

            if self._stop_event.is_set():
                break

            if self.config.get("schedule_enabled", False):
                self._run_research()

    def _run_research(self) -> None:
        if not self.agent:
            return

        topics = self._topics()
        print(f"[HoudiniMind Scheduler] Running AutoResearch on {len(topics)} topic(s).")
        if self.stream_cb:
            self.stream_cb("\x00AGENT_PROGRESS\x00Scheduled AutoResearch starting…")

        for topic in topics:
            if self._stop_event.is_set():
                break
            try:
                print(f"[HoudiniMind Scheduler] Researching: {topic}")
                self.agent.research(
                    topic,
                    stream_callback=self.stream_cb,
                    status_callback=self.status_cb,
                )
                # Trigger memory learning cycle after each research run
                if self.memory:
                    self.memory.run_learning_cycle()
                print(f"[HoudiniMind Scheduler] Done: {topic[:60]}")
            except Exception as e:
                print(f"[HoudiniMind Scheduler] Research failed for '{topic}': {e}")
                traceback.print_exc()

        with self._lock:
            self._last_run_ts = time.time()
            self._run_count += 1

        print(f"[HoudiniMind Scheduler] Cycle complete (total runs: {self._run_count}).")
        if self.stream_cb:
            self.stream_cb(
                f"\x00AGENT_PROGRESS\x00Scheduled AutoResearch complete (run #{self._run_count})."
            )
