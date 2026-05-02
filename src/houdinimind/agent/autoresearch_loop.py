# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
"""
HoudiniMind — Agent Training Loop
Autonomous iterative learning loop inspired by Karpathy's autoresearch.

The agent autonomously generates and attempts Houdini tasks, learns from
errors, saves successful recipes, and progressively improves.
Stops only when the user hits Stop.

Key design:
  1. Dynamically generate the next task via LLM (considering past history)
  2. Clean the scene (or use a fresh geo context)
  3. Attempt to build it via AgentLoop.chat()
  4. Inspect errors → if errors, analyse root cause, add to lessons learned
  5. If success → validate geometry, save recipe, update learned prompt
  6. Generate next task; repeat indefinitely
  7. Self-optimisation: track error patterns, success rates, timing;
     periodically distill lessons into system_prompt_learned.txt
"""

import json
import os
import random
import sqlite3
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager

# ══════════════════════════════════════════════════════════════════════
#  Dynamic Task Generator
# ══════════════════════════════════════════════════════════════════════

# Domains and difficulty levels the generator can pick from
_DOMAINS = [
    "basics",
    "furniture",
    "props",
    "architecture",
    "vehicles",
    "nature",
    "procedural",
    "vex",
    "particles",
    "simulation",
    "hard_surface",
    "organic",
    "environment",
    "abstract",
]

_LEVEL_DESCRIPTIONS = {
    1: "single-primitive, very simple (sphere, box, cylinder with basic ops)",
    2: "multi-part assembly (merge several primitives into a recognisable object)",
    3: "procedural techniques (copy-to-points, for-each loops, instances)",
    4: "VEX wrangles, attribute manipulation, noise-driven effects",
    5: "simulations (RBD, Vellum cloth/grains) or complex procedural systems",
}


def generate_next_task(llm_chat_simple, history: list[str], lessons: list[dict]) -> dict:
    """
    Ask the agent to invent the next training task.

    Args:
        llm_chat_simple: callable(system, user, temperature, task) -> str.
            Takes a proper system prompt — the old shim prepended a sentinel
            to a user string, so the model saw it as literal user input and
            task generation worked only by accident.
        history: list of task names already attempted this session
        lessons: current high-confidence lessons from the DB

    Returns:
        dict with keys: name, prompt, level, domain, validation
    """
    # Pick a random domain and bias toward levels we haven't done recently
    domain = random.choice(_DOMAINS)
    # Avoid repeating last 3 domains if history long enough
    if len(history) >= 6:
        recent_domains = history[-3:]
        candidates = [d for d in _DOMAINS if d not in recent_domains]
        domain = random.choice(candidates) if candidates else random.choice(_DOMAINS)

    # Determine level: start easy, increase as session progresses
    n = len(history)
    if n < 3:
        level = 1
    elif n < 6:
        level = random.choice([1, 2])
    elif n < 10:
        level = random.choice([2, 3])
    elif n < 15:
        level = random.choice([3, 4])
    else:
        level = random.choice([3, 4, 5])

    already_done = ", ".join(history[-10:]) if history else "none"
    lesson_hints = ""
    if lessons:
        lesson_hints = "\n".join(
            f"- Known issue: {l['error'][:80]} → {l['fix'][:80]}" for l in lessons[:4]
        )
        lesson_hints = f"\n\nKnown lessons to factor into task design:\n{lesson_hints}"

    system = (
        "You are a Houdini SOP training task designer. "
        "Output ONLY valid JSON, no markdown fences, no explanation."
    )
    prompt = (
        f"Design ONE new Houdini SOP training task.\n\n"
        f"Domain: {domain}\n"
        f"Difficulty level: {level} — {_LEVEL_DESCRIPTIONS[level]}\n"
        f"Recently attempted tasks (avoid repeating): {already_done}"
        f"{lesson_hints}\n\n"
        f"Return JSON with exactly these keys:\n"
        f'{{"name": "short descriptive name", '
        f'"prompt": "detailed build instruction for the agent (2-4 sentences)", '
        f'"level": {level}, '
        f'"domain": "{domain}", '
        f'"validation": {{"min_nodes": <int>, "min_points": <int>}}}}\n\n'
        f"Be creative. Think of something new and interesting to build."
    )

    try:
        raw = llm_chat_simple(system=system, user=prompt, temperature=0.6, task="research")
        # Extract JSON from response
        raw = raw.strip()
        # Strip markdown fences if the model added them anyway
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()
        task = json.loads(raw)
        # Ensure required keys exist
        task.setdefault("level", level)
        task.setdefault("domain", domain)
        task.setdefault("validation", {"min_nodes": max(1, level), "min_points": level * 10})
        return task
    except Exception:
        # Fallback: construct a simple task without LLM
        fallback_prompts = {
            "basics": "Create a sphere with radius 1, subdivide it twice, then smooth it.",
            "furniture": "Build a simple desk: a flat box top and four leg boxes, merged.",
            "props": "Create a simple barrel: a cylinder body with two flat disc caps, merged.",
            "architecture": "Build a simple archway: two tall box pillars and a curved tube arch.",
            "vehicles": "Create a simple rocket: a cylinder body, cone tip, and three fin boxes.",
            "nature": "Create a simple tree: a cylinder trunk and a sphere canopy, merged.",
            "procedural": "Scatter 20 points on a grid, copy a small sphere to each point.",
            "vex": "Create a grid 20x20, use a VEX wrangle to push points up with sin(x)*cos(z) noise.",
            "particles": "Create a particle system emitting from a sphere surface.",
            "simulation": "Drop a box onto a ground plane using an RBD solver.",
            "hard_surface": "Model a simple bolt: a cylinder shaft and a hexagonal prism head.",
            "organic": "Create a pebble: subdivided box with smooth SOP applied multiple times.",
            "environment": "Build a simple rock formation using multiple scaled and rotated boxes merged.",
            "abstract": "Create a twisted ribbon using a grid, VEX bend, and a polyextrude.",
        }
        return {
            "name": f"{domain.title()} Task {random.randint(100, 999)}",
            "prompt": fallback_prompts.get(
                domain, "Create a sphere and add a color SOP coloring it blue."
            ),
            "level": level,
            "domain": domain,
            "validation": {"min_nodes": max(1, level), "min_points": level * 10},
        }


# ══════════════════════════════════════════════════════════════════════
#  AutoResearch Learning DB
# ══════════════════════════════════════════════════════════════════════


class AutoResearchDB:
    """Tracks attempts, errors, lessons, and success metrics."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self):
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS attempts (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_name       TEXT NOT NULL,
                    task_level      INTEGER DEFAULT 1,
                    attempt_num     INTEGER DEFAULT 1,
                    success         INTEGER DEFAULT 0,
                    error_summary   TEXT,
                    fix_applied     TEXT,
                    tool_sequence   TEXT,
                    duration_s      REAL DEFAULT 0,
                    created_ts      REAL
                );

                CREATE TABLE IF NOT EXISTS lessons (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    error_pattern   TEXT UNIQUE,
                    fix_pattern     TEXT,
                    times_seen      INTEGER DEFAULT 1,
                    times_fixed     INTEGER DEFAULT 0,
                    confidence      REAL DEFAULT 0.5,
                    domain          TEXT DEFAULT 'general',
                    created_ts      REAL,
                    last_seen_ts    REAL
                );

                CREATE TABLE IF NOT EXISTS session_stats (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_ts      REAL,
                    tasks_attempted INTEGER DEFAULT 0,
                    tasks_succeeded INTEGER DEFAULT 0,
                    total_attempts  INTEGER DEFAULT 0,
                    total_errors    INTEGER DEFAULT 0,
                    avg_attempts    REAL DEFAULT 0,
                    lessons_learned INTEGER DEFAULT 0,
                    duration_s      REAL DEFAULT 0
                );
            """)

    def log_attempt(
        self,
        task_name: str,
        level: int,
        attempt_num: int,
        success: bool,
        error_summary: str = "",
        fix_applied: str = "",
        tool_sequence: list | None = None,
        duration_s: float = 0,
    ):
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO attempts
                   (task_name, task_level, attempt_num, success, error_summary,
                    fix_applied, tool_sequence, duration_s, created_ts)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    task_name,
                    level,
                    attempt_num,
                    int(success),
                    error_summary,
                    fix_applied,
                    json.dumps(tool_sequence or []),
                    duration_s,
                    time.time(),
                ),
            )

    def add_lesson(self, error_pattern: str, fix_pattern: str, domain: str = "general"):
        now = time.time()
        with self._conn() as conn:
            existing = conn.execute(
                "SELECT id, times_seen FROM lessons WHERE error_pattern = ?", (error_pattern,)
            ).fetchone()
            if existing:
                conn.execute(
                    """UPDATE lessons SET times_seen = times_seen + 1,
                       fix_pattern = ?, confidence = MIN(1.0, confidence + 0.1),
                       last_seen_ts = ? WHERE id = ?""",
                    (fix_pattern, now, existing[0]),
                )
            else:
                conn.execute(
                    """INSERT INTO lessons
                       (error_pattern, fix_pattern, domain, created_ts, last_seen_ts)
                       VALUES (?, ?, ?, ?, ?)""",
                    (error_pattern, fix_pattern, domain, now, now),
                )

    def mark_lesson_used(self, error_pattern: str, fixed: bool):
        with self._conn() as conn:
            if fixed:
                conn.execute(
                    """UPDATE lessons SET times_fixed = times_fixed + 1,
                       confidence = MIN(1.0, confidence + 0.15)
                       WHERE error_pattern = ?""",
                    (error_pattern,),
                )
            else:
                conn.execute(
                    """UPDATE lessons SET confidence = MAX(0.0, confidence - 0.05)
                       WHERE error_pattern = ?""",
                    (error_pattern,),
                )

    def get_lessons(self, min_confidence: float = 0.3, limit: int = 20) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT error_pattern, fix_pattern, confidence, times_seen,
                          times_fixed, domain
                   FROM lessons WHERE confidence >= ?
                   ORDER BY confidence DESC, times_seen DESC
                   LIMIT ?""",
                (min_confidence, limit),
            ).fetchall()
        return [
            {
                "error": r[0],
                "fix": r[1],
                "confidence": round(r[2], 2),
                "seen": r[3],
                "fixed": r[4],
                "domain": r[5],
            }
            for r in rows
        ]

    def get_task_history(self, task_name: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT attempt_num, success, error_summary, fix_applied, duration_s
                   FROM attempts WHERE task_name = ?
                   ORDER BY created_ts DESC LIMIT 10""",
                (task_name,),
            ).fetchall()
        return [
            {"attempt": r[0], "success": bool(r[1]), "error": r[2], "fix": r[3], "duration": r[4]}
            for r in rows
        ]

    def get_stats(self) -> dict:
        with self._conn() as conn:
            total_attempts = conn.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]
            successes = conn.execute("SELECT COUNT(*) FROM attempts WHERE success=1").fetchone()[0]
            total_lessons = conn.execute("SELECT COUNT(*) FROM lessons").fetchone()[0]
            high_conf = conn.execute(
                "SELECT COUNT(*) FROM lessons WHERE confidence >= 0.7"
            ).fetchone()[0]
            unique_tasks = conn.execute(
                "SELECT COUNT(DISTINCT task_name) FROM attempts WHERE success=1"
            ).fetchone()[0]
        return {
            "total_attempts": total_attempts,
            "successes": successes,
            "success_rate": round(successes / max(1, total_attempts) * 100, 1),
            "total_lessons": total_lessons,
            "high_confidence_lessons": high_conf,
            "unique_tasks_mastered": unique_tasks,
        }

    def log_session(
        self,
        tasks_attempted: int,
        tasks_succeeded: int,
        total_attempts: int,
        total_errors: int,
        lessons_learned: int,
        duration_s: float,
    ):
        avg = total_attempts / max(1, tasks_attempted)
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO session_stats
                   (session_ts, tasks_attempted, tasks_succeeded, total_attempts,
                    total_errors, avg_attempts, lessons_learned, duration_s)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    time.time(),
                    tasks_attempted,
                    tasks_succeeded,
                    total_attempts,
                    total_errors,
                    avg,
                    lessons_learned,
                    duration_s,
                ),
            )


# ══════════════════════════════════════════════════════════════════════
#  AutoResearch Loop Engine
# ══════════════════════════════════════════════════════════════════════


class AutoResearchLoop:
    """
    Autonomous iterative learning loop inspired by Karpathy's autoresearch.

    The loop:
      1. Picks the next task from a curated curriculum
      2. Attempts to build it via AgentLoop.chat()
      3. Checks for errors → learns from them
      4. On success → saves recipe, updates learned prompt
      5. Moves to next task; repeats until stopped

    Self-improvement mechanisms:
      - Error pattern database: tracks recurring errors and their fixes
      - Lesson injection: prepends learned lessons to each attempt prompt
      - Recipe extraction: successful builds become reusable recipes
      - Prompt evolution: periodically distills lessons into system_prompt_learned.txt
      - Adaptive retries: fewer retries for tasks where lessons already exist
    """

    MAX_ATTEMPTS_PER_TASK = 3
    LESSON_DISTILL_EVERY = 5  # distill lessons into prompt every N tasks

    def __init__(self, agent_loop, memory_manager=None, data_dir: str = "data"):
        self.agent = agent_loop
        self.memory = memory_manager
        self.data_dir = data_dir

        db_path = os.path.join(data_dir, "db", "autoresearch.db")
        self.db = AutoResearchDB(db_path)

        self._stop_event = threading.Event()
        self._running = False
        self._current_task: dict | None = None
        self._task_index = 0
        self._session_task_names: list[str] = []  # track names this session
        self._session_stats = {
            "tasks_attempted": 0,
            "tasks_succeeded": 0,
            "total_attempts": 0,
            "total_errors": 0,
            "lessons_learned": 0,
            "start_time": 0,
        }

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def current_task(self) -> dict | None:
        return self._current_task

    def stop(self):
        """Signal the loop to stop after the current attempt finishes."""
        self._stop_event.set()
        if self.agent:
            self.agent.cancel()

    def get_stats(self) -> dict:
        db_stats = self.db.get_stats()
        db_stats.update(
            {
                "running": self._running,
                "current_task": self._current_task.get("name") if self._current_task else None,
                "task_index": self._task_index,
                "session": dict(self._session_stats),
            }
        )
        return db_stats

    def run(
        self,
        stream_callback: Callable[[str], None] | None = None,
        tool_callback: Callable | None = None,
        progress_callback: Callable[[dict], None] | None = None,
    ):
        """
        Main loop entry point. Runs in the calling thread (launch in a thread).

        Args:
            stream_callback: receives text chunks for the UI chat bubble
            tool_callback: receives (tool_name, args, result) for tool display
            progress_callback: receives progress dicts for the UI status panel
        """
        self._stop_event.clear()
        self._running = True
        self._session_stats = {
            "tasks_attempted": 0,
            "tasks_succeeded": 0,
            "total_attempts": 0,
            "total_errors": 0,
            "lessons_learned": 0,
            "start_time": time.time(),
        }

        def _progress(data: dict):
            if progress_callback:
                progress_callback(data)

        def _stream(text: str):
            if stream_callback:
                stream_callback(text)

        _stream("\n\n🔬 **Agent Training Loop Started**\n")
        _stream(f"🧠 Lessons in memory: {self.db.get_stats()['total_lessons']}\n")
        _stream("🎲 Tasks will be generated dynamically each round\n\n")

        _progress(
            {
                "event": "started",
                "lessons": self.db.get_stats()["total_lessons"],
            }
        )

        def _llm_chat_simple(
            system: str, user: str, temperature: float = 0.3, task: str = "research"
        ) -> str:
            """Bridge to the agent's llm.chat_simple so task generation can send a
            real system prompt rather than smuggling one in a user message."""
            try:
                return self.agent.llm.chat_simple(
                    system=system, user=user, temperature=temperature, task=task
                )
            except Exception:
                return ""

        try:
            while not self._stop_event.is_set():
                # Dynamically generate next task
                _stream("\n💭 Generating next task…\n")
                lessons = self.db.get_lessons(min_confidence=0.3)
                task = generate_next_task(
                    _llm_chat_simple,
                    self._session_task_names,
                    lessons,
                )
                self._session_task_names.append(task["name"])
                self._current_task = task
                self._session_stats["tasks_attempted"] += 1

                _stream(f"\n{'=' * 60}\n")
                _stream(
                    f"## 📋 Task {self._task_index + 1}: **{task['name']}** (Level {task['level']} · {task['domain']})\n"
                )
                _stream(f"> {task['prompt'][:150]}…\n\n")
                _progress(
                    {
                        "event": "task_start",
                        "task_name": task["name"],
                        "task_level": task["level"],
                        "task_index": self._task_index + 1,
                    }
                )

                success = self._attempt_task(task, _stream, _progress)

                if self._stop_event.is_set():
                    break

                if success:
                    self._session_stats["tasks_succeeded"] += 1
                    _stream(f"\n✅ **{task['name']}** — PASSED\n")
                    _progress({"event": "task_success", "task_name": task["name"]})

                    # Save recipe on success
                    self._save_recipe_from_task(task)
                else:
                    _stream(
                        f"\n❌ **{task['name']}** — FAILED after {self.MAX_ATTEMPTS_PER_TASK} attempts\n"
                    )
                    _progress({"event": "task_failed", "task_name": task["name"]})

                # Distill lessons periodically
                if self._session_stats["tasks_attempted"] % self.LESSON_DISTILL_EVERY == 0:
                    self._distill_lessons(_stream)

                self._task_index += 1

                # Brief pause between tasks
                if not self._stop_event.is_set():
                    self._stop_event.wait(timeout=2.0)

        except Exception as e:
            _stream(f"\n\n⚠️ **AutoResearch Error:** {e}\n")
        finally:
            self._running = False
            self._current_task = None
            elapsed = time.time() - self._session_stats["start_time"]

            # Log session stats
            self.db.log_session(
                tasks_attempted=self._session_stats["tasks_attempted"],
                tasks_succeeded=self._session_stats["tasks_succeeded"],
                total_attempts=self._session_stats["total_attempts"],
                total_errors=self._session_stats["total_errors"],
                lessons_learned=self._session_stats["lessons_learned"],
                duration_s=elapsed,
            )

            # Final distill
            self._distill_lessons(_stream)

            stats = self.db.get_stats()
            _stream(f"\n\n{'=' * 60}\n")
            _stream("## 🔬 Training Session Complete\n")
            _stream(f"- Tasks attempted: {self._session_stats['tasks_attempted']}\n")
            _stream(f"- Tasks succeeded: {self._session_stats['tasks_succeeded']}\n")
            _stream(f"- Total attempts: {self._session_stats['total_attempts']}\n")
            _stream(f"- Lessons learned: {self._session_stats['lessons_learned']}\n")
            _stream(f"- All-time success rate: {stats['success_rate']}%\n")
            _stream(
                f"- Total lessons in DB: {stats['total_lessons']} ({stats['high_confidence_lessons']} high-confidence)\n"
            )
            _stream(f"- Duration: {int(elapsed)}s\n")

            _progress(
                {
                    "event": "stopped",
                    "stats": stats,
                    "session": dict(self._session_stats),
                }
            )

    # ── Core attempt logic ───────────────────────────────────────────

    def _attempt_task(self, task: dict, stream_cb: Callable, progress_cb: Callable) -> bool:
        """
        Try to build a task up to MAX_ATTEMPTS_PER_TASK times.
        Returns True if the task was built successfully.
        """
        lessons = self.db.get_lessons(min_confidence=0.3)
        task_history = self.db.get_task_history(task["name"])

        for attempt in range(1, self.MAX_ATTEMPTS_PER_TASK + 1):
            if self._stop_event.is_set():
                return False

            self._session_stats["total_attempts"] += 1
            t0 = time.time()

            stream_cb(f"\n### Attempt {attempt}/{self.MAX_ATTEMPTS_PER_TASK}\n")
            progress_cb(
                {
                    "event": "attempt_start",
                    "task_name": task["name"],
                    "attempt": attempt,
                    "max_attempts": self.MAX_ATTEMPTS_PER_TASK,
                }
            )

            # Build the prompt with lessons injected
            prompt = self._build_attempt_prompt(task, attempt, lessons, task_history)

            # Clean scene before each attempt
            self._clean_scene(stream_cb)

            # Reset cancel event on agent so it can run
            if hasattr(self.agent, "_cancel_event"):
                self.agent._cancel_event.clear()

            # Run the agent
            try:
                result = self.agent.chat(prompt, stream_cb, dry_run=False)
            except Exception as e:
                result = f"Agent error: {e}"
                stream_cb(f"\n⚠️ Agent error: {e}\n")

            duration = time.time() - t0

            if self._stop_event.is_set():
                return False

            # Check for errors
            errors = self._check_errors(stream_cb)
            success = len(errors) == 0

            # Validate geometry if no errors
            if success:
                success = self._validate_result(task, stream_cb)

            # Record attempt
            error_summary = "; ".join(errors[:3]) if errors else ""
            self.db.log_attempt(
                task_name=task["name"],
                level=task["level"],
                attempt_num=attempt,
                success=success,
                error_summary=error_summary,
                duration_s=duration,
            )

            if success:
                return True

            # Learn from errors
            if errors:
                self._session_stats["total_errors"] += len(errors)
                self._analyse_and_learn(task, errors, result, stream_cb)
                # Add learned fix to history for next attempt
                task_history = self.db.get_task_history(task["name"])
                lessons = self.db.get_lessons(min_confidence=0.3)

        return False

    # ── Prompt construction ──────────────────────────────────────────

    def _build_attempt_prompt(
        self, task: dict, attempt: int, lessons: list[dict], task_history: list[dict]
    ) -> str:
        """Build a rich prompt with context from prior learning."""
        parts = []

        # Core task instruction
        parts.append(f"[AUTORESEARCH TASK] {task['prompt']}")
        parts.append("")
        parts.append(
            "IMPORTANT: Build this completely. Create all geometry nodes, "
            "set all parameters, connect everything properly, and set the "
            "display flag on the final merge/output node. Do NOT stop early."
        )

        # Inject relevant lessons
        relevant_lessons = [
            l for l in lessons if l["domain"] in (task.get("domain", "general"), "general")
        ]
        if relevant_lessons:
            parts.append("")
            parts.append("[LEARNED LESSONS — apply these to avoid known errors]")
            for l in relevant_lessons[:8]:
                parts.append(
                    f"- Error: {l['error'][:100]} → Fix: {l['fix'][:100]} (confidence: {l['confidence']})"
                )

        # Inject history from previous attempts on this task
        failed_history = [h for h in task_history if not h["success"]]
        if failed_history and attempt > 1:
            parts.append("")
            parts.append("[PREVIOUS ATTEMPT ERRORS — avoid repeating these]")
            for h in failed_history[:3]:
                if h.get("error"):
                    parts.append(f"- Attempt {h['attempt']}: {h['error'][:150]}")

        # Level-specific guidance
        if task["level"] >= 3:
            parts.append("")
            parts.append(
                "[TECHNIQUE HINT] For multi-part objects, use separate primitives "
                "and merge them. Use transform SOPs to position parts. "
                "Verify with get_bounding_box that parts don't overlap incorrectly."
            )

        return "\n".join(parts)

    # ── Scene management ─────────────────────────────────────────────

    def _clean_scene(self, stream_cb: Callable):
        """Create a fresh geo container for each attempt."""
        try:
            import hou as _hou

            from .tools import TOOL_FUNCTIONS

            # Use hipFile.clear every 5 attempts for a total state reset (Mac stability rule)
            if self._session_stats.get("total_attempts", 0) % 5 == 0:
                _hou.hipFile.clear(suppress_save_prompt=True)
                stream_cb("\u200b🧹 Hard reset scene (hipFile.clear)\n")

            # Create a new geo node for the attempt
            create_fn = TOOL_FUNCTIONS.get("create_node")
            if create_fn:
                # Delete existing autoresearch geo if present
                existing = _hou.node("/obj/autoresearch_geo")
                if existing:
                    existing.destroy()
                    _hou.undonest.clear()  # Clear undo stack after delete (Mac stability rule)
                create_fn(parent_path="/obj", node_type="geo", name="autoresearch_geo")
                stream_cb("\u200b🧹 Clean scene ready\n")
        except Exception as e:
            stream_cb(f"\u200b⚠️ Scene cleanup note: {e}\n")

    # ── Error checking ───────────────────────────────────────────────

    def _check_errors(self, stream_cb: Callable) -> list[str]:
        """Check Houdini scene for errors after a build attempt.

        get_all_errors returns {"data": {"nodes": [{"path": ..., "errors": [...]}]}}.
        The previous implementation read data["errors"] (wrong key) and
        isinstance(data, list) (wrong shape), so the loop reported zero errors
        no matter what the scene looked like — every autoresearch attempt was
        marked successful regardless of failure.
        """
        errors: list[str] = []
        try:
            from .tools import TOOL_FUNCTIONS

            error_fn = TOOL_FUNCTIONS.get("get_all_errors")
            if not error_fn:
                return errors
            result = error_fn()
            if not isinstance(result, dict):
                return errors
            data = result.get("data", {}) or {}
            # Canonical shape: {"nodes": [{"path": "/obj/x", "errors": [...]}, ...]}
            nodes = data.get("nodes") if isinstance(data, dict) else None
            if isinstance(nodes, list):
                for node in nodes:
                    if not isinstance(node, dict):
                        continue
                    path = node.get("path", "?")
                    for err in node.get("errors", []) or []:
                        if isinstance(err, dict):
                            msg = err.get("message") or err.get("error") or str(err)
                            errors.append(f"{path}: {msg}")
                        elif isinstance(err, str):
                            errors.append(f"{path}: {err}")
            # Fallback: legacy flat list shape
            elif isinstance(data, list):
                for e in data:
                    if isinstance(e, dict):
                        errors.append(f"{e.get('node', '?')}: {e.get('message', '?')}")
                    elif isinstance(e, str):
                        errors.append(e)
        except Exception as e:
            stream_cb(f"\u200b⚠️ Error check failed: {e}\n")
        return errors

    # ── Geometry validation ──────────────────────────────────────────

    def _validate_result(self, task: dict, stream_cb: Callable) -> bool:
        """Validate that the built geometry meets minimum criteria."""
        validation = task.get("validation", {})
        if not validation:
            return True

        try:
            from .tools import TOOL_FUNCTIONS

            # Check scene has enough nodes
            scene_fn = TOOL_FUNCTIONS.get("get_scene_summary")
            if scene_fn:
                result = scene_fn()
                if isinstance(result, dict):
                    data = result.get("data", {})
                    node_count = 0
                    if isinstance(data, dict):
                        nodes = data.get("nodes", [])
                        node_count = len(nodes) if isinstance(nodes, list) else 0
                    min_nodes = validation.get("min_nodes", 1)
                    if node_count < min_nodes:
                        stream_cb(
                            f"\u200b⚠️ Validation: only {node_count} nodes (need {min_nodes})\n"
                        )
                        return False

            stream_cb("\u200b✅ Validation passed\n")
            return True

        except Exception as e:
            stream_cb(f"\u200b⚠️ Validation error: {e}\n")
            return True  # Don't fail on validation errors

    # ── Error analysis and learning ──────────────────────────────────

    def _analyse_and_learn(
        self, task: dict, errors: list[str], result: str, stream_cb: Callable
    ) -> str:
        """Analyse errors, extract patterns, and store lessons."""
        learned_count = 0

        for error in errors[:5]:
            # Extract error pattern (normalize)
            pattern = self._normalize_error(error)
            if not pattern:
                continue

            # Ask the agent to suggest a fix (quick LLM call)
            fix = self._suggest_fix(error, task)

            if fix:
                self.db.add_lesson(
                    error_pattern=pattern,
                    fix_pattern=fix,
                    domain=task.get("domain", "general"),
                )
                learned_count += 1
                stream_cb(f"\u200b🧠 Learned: {pattern[:60]} → {fix[:60]}\n")

        self._session_stats["lessons_learned"] += learned_count
        return f"Learned {learned_count} lessons from {len(errors)} errors"

    def _normalize_error(self, error: str) -> str:
        """Normalize an error message to a reusable pattern."""
        import re

        # Remove node-specific paths
        normalized = re.sub(r"/obj/[^\s:]+", "<node_path>", error)
        # Remove specific numbers
        normalized = re.sub(r"\b\d+\b", "<N>", normalized)
        # Collapse whitespace
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized[:200] if len(normalized) > 15 else ""

    def _suggest_fix(self, error: str, task: dict) -> str:
        """Use the LLM to suggest a fix for an error."""
        try:
            fix = self.agent.llm.chat_simple(
                system=(
                    "You are a Houdini error analyst. Given a Houdini error, "
                    "suggest a ONE-LINE fix. Be specific: name the exact node type, "
                    "parameter, or connection to change. No generic advice."
                ),
                user=f"Error: {error}\nContext: building {task['name']}",
                temperature=0.1,
            )
            # Take first line only
            fix = fix.strip().split("\n")[0][:200]
            return fix if len(fix) > 10 else ""
        except Exception:
            return ""

    # ── Recipe extraction ────────────────────────────────────────────

    def _save_recipe_from_task(self, task: dict):
        """Save a successful build as a reusable recipe."""
        if not self.memory:
            return
        try:
            recipe_name = f"autoresearch_{task['name'].lower().replace(' ', '_')}"
            self.memory.recipe_book.add_recipe(
                name=recipe_name,
                description=f"AutoResearch learned: {task['name']} (Level {task['level']})",
                trigger_pattern=task["name"].lower(),
                steps=[{"tool": "chat", "args": {"prompt": task["prompt"]}}],
                domain=task.get("domain", "general"),
            )
            # Boost confidence since it was auto-validated
            recipes = self.memory.recipe_book.search(recipe_name)
            if recipes:
                self.memory.recipe_book.record_use(recipes[0]["id"], accepted=True)
        except Exception:
            pass

    # ── Lesson distillation ──────────────────────────────────────────

    def _distill_lessons(self, stream_cb: Callable):
        """
        Periodically distill accumulated lessons into the learned prompt.
        This is the self-improvement mechanism — the agent gets smarter
        with each distillation cycle.
        """
        lessons = self.db.get_lessons(min_confidence=0.5)
        if not lessons:
            return

        stream_cb("\n\u200b🧬 Distilling lessons into system prompt…\n")

        # Write lessons as guidance to system_prompt_learned.txt
        try:
            learned_path = os.path.join(self.data_dir, "system_prompt_learned.txt")
            existing_content = ""
            if os.path.exists(learned_path):
                with open(learned_path, encoding="utf-8") as f:
                    existing_content = f.read()

            # Build AutoResearch section
            ar_header = "## AutoResearch — Learned Error Patterns"
            ar_lines = [
                "",
                ar_header,
                f"# Auto-distilled at {time.strftime('%Y-%m-%d %H:%M')}",
                "",
            ]
            for l in lessons[:15]:
                ar_lines.append(
                    f'- When you see: "{l["error"][:80]}" → '
                    f"Fix: {l['fix'][:80]} (confidence: {l['confidence']})"
                )

            ar_block = "\n".join(ar_lines)

            # Replace or append the AutoResearch section
            if ar_header in existing_content:
                # Find and replace the section
                import re

                pattern = re.escape(ar_header) + r".*?(?=\n## |\Z)"
                new_content = re.sub(
                    pattern, ar_block.lstrip("\n"), existing_content, flags=re.DOTALL
                )
            else:
                new_content = existing_content.rstrip() + "\n" + ar_block

            with open(learned_path, "w", encoding="utf-8") as f:
                f.write(new_content)

            # Reload the prompt in the agent
            if hasattr(self.agent, "reload_system_prompt"):
                self.agent.reload_system_prompt()

            stream_cb(f"\u200b✅ Distilled {len(lessons)} lessons into system prompt\n")
        except Exception as e:
            stream_cb(f"\u200b⚠️ Distillation failed: {e}\n")

        # Also run the memory learning cycle if available
        if self.memory:
            try:
                self.memory.run_learning_cycle()
            except Exception:
                pass
