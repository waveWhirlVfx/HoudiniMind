# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
"""
HoudiniMind — Memory System
Three components:
  PatternAnalyser  — mines session_log for repeating patterns
  RecipeBook       — stores promoted, confidence-scored workflows
  SelfUpdater      — rewrites the learned section of the system prompt
"""

import json
import os
import re
import sqlite3
import time
from contextlib import contextmanager

# ══════════════════════════════════════════════════════════════════════
#  Recipe Book
# ══════════════════════════════════════════════════════════════════════


class RecipeBook:
    """
    A SQLite store of learned workflow patterns.
    Each recipe has a confidence score that rises with acceptance
    and decays over time or with rejections.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._use_memory_fallback = False
        self._fallback_rules: list[dict] = []
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS recipes (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    name            TEXT UNIQUE,
                    description     TEXT,
                    trigger_pattern TEXT,        -- what user intent triggers this
                    steps           TEXT,        -- JSON list of {tool, args}
                    confidence      REAL DEFAULT 0.5,
                    times_used      INTEGER DEFAULT 0,
                    times_accepted  INTEGER DEFAULT 0,
                    times_rejected  INTEGER DEFAULT 0,
                    domain          TEXT,
                    created_ts      REAL,
                    last_used_ts    REAL
                );
                CREATE TABLE IF NOT EXISTS negative_recipes (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    name            TEXT UNIQUE,
                    description     TEXT,
                    trigger_pattern TEXT,
                    steps           TEXT,        -- JSON list of {tool, args}
                    times_rejected  INTEGER DEFAULT 1,
                    domain          TEXT,
                    created_ts      REAL,
                    last_seen_ts    REAL
                );
            """)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def add_recipe(
        self,
        name: str,
        description: str,
        trigger_pattern: str,
        steps: list,
        domain: str = "general",
    ) -> int:
        with self._conn() as conn:
            try:
                cur = conn.execute(
                    """INSERT INTO recipes
                       (name, description, trigger_pattern, steps, domain, created_ts, last_used_ts)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        name,
                        description,
                        trigger_pattern,
                        json.dumps(steps),
                        domain,
                        time.time(),
                        time.time(),
                    ),
                )
                return cur.lastrowid
            except sqlite3.IntegrityError:
                return -1  # already exists

    def record_use(self, recipe_id: int, accepted: bool, complexity_weight: float = 1.0):
        """
        Update confidence with a responsive, bounded delta.

        complexity_weight: 0.5 simple (single tool), 1.0 medium, 2.0 complex.

        Acceptance gives a diminishing-returns boost (fast rise from 0.5,
        slow near 1.0).  Rejection applies an escalating penalty based on
        how many times this recipe has already been rejected.
        """
        with self._conn() as conn:
            row = conn.execute(
                "SELECT confidence, times_rejected FROM recipes WHERE id = ?",
                (recipe_id,),
            ).fetchone()
            if not row:
                return
            current_conf, times_rejected = row

            if accepted:
                # Diminishing returns: headroom shrinks as confidence rises
                headroom = max(0.0, 1.0 - current_conf)
                base_delta = 0.12 * headroom  # ~0.06 @ conf=0.5, ~0.01 @ conf=0.9
                delta = base_delta * max(0.5, min(2.0, complexity_weight))
            else:
                # Each rejection hurts a little more (cap at 5 escalations)
                rejection_factor = 1.0 + 0.3 * min(times_rejected, 5)
                delta = -0.10 * rejection_factor * max(0.5, min(2.0, complexity_weight))

            new_conf = max(0.0, min(1.0, current_conf + delta))
            accepted_inc = 1 if accepted else 0
            rejected_inc = 0 if accepted else 1

            conn.execute(
                """
                UPDATE recipes SET
                  times_used      = times_used + 1,
                  times_accepted  = times_accepted + ?,
                  times_rejected  = times_rejected + ?,
                  confidence      = ?,
                  last_used_ts    = ?
                WHERE id = ?
            """,
                (accepted_inc, rejected_inc, round(new_conf, 4), time.time(), recipe_id),
            )

    def boost_on_success(self, domain: str, step_count: int):
        """
        Give a small implicit lift to recently-used recipes in *domain* when
        a turn completes successfully without explicit user feedback.
        This reinforces good patterns even when users don't click Accept/Reject.
        """
        if not domain:
            return
        boost = min(0.04, 0.01 * step_count)  # up to +0.04 for complex builds
        cutoff = time.time() - 7 * 86400  # only recipes touched in last week
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE recipes
                SET confidence = MIN(1.0, confidence + ?)
                WHERE domain = ? AND last_used_ts > ? AND confidence < 0.95
            """,
                (round(boost, 4), domain, cutoff),
            )

    def decay_stale(self, days_threshold: int = 14):
        """
        Exponential decay for unused recipes.

        Recipes dormant for *days_threshold* days lose confidence at a rate
        proportional to their idle time — a recipe unused 60 days decays
        much faster than one unused 15 days.
        """
        now = time.time()
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, confidence, last_used_ts FROM recipes WHERE confidence > 0"
            ).fetchall()
            updates = []
            for rid, conf, last_used in rows:
                if last_used is None:
                    continue
                days_idle = (now - last_used) / 86400
                if days_idle < days_threshold:
                    continue
                # Each threshold-period multiplies remaining confidence by 0.92
                periods_idle = days_idle / days_threshold
                new_conf = conf * (0.92**periods_idle)
                updates.append((round(max(0.0, new_conf), 4), rid))
            if updates:
                conn.executemany("UPDATE recipes SET confidence = ? WHERE id = ?", updates)

    def get_all(self, min_confidence: float = 0.3) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT id, name, description, trigger_pattern, steps,
                       confidence, domain, times_used, times_accepted
                FROM recipes WHERE confidence >= ?
                ORDER BY confidence DESC
            """,
                (min_confidence,),
            ).fetchall()
        return [
            {
                "id": r[0],
                "name": r[1],
                "description": r[2],
                "trigger": r[3],
                "steps": json.loads(r[4]),
                "confidence": round(r[5], 2),
                "domain": r[6],
                "used": r[7],
                "accepted": r[8],
                "times_used": r[7],
                "times_accepted": r[8],
            }
            for r in rows
        ]

    def search(self, keyword: str) -> list[dict]:
        kw = f"%{keyword}%"
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT id, name, description, trigger_pattern, steps, confidence, domain
                FROM recipes
                WHERE name LIKE ? OR description LIKE ? OR trigger_pattern LIKE ?
                ORDER BY confidence DESC LIMIT 10
            """,
                (kw, kw, kw),
            ).fetchall()
        return [
            {
                "id": r[0],
                "name": r[1],
                "description": r[2],
                "trigger": r[3],
                "steps": json.loads(r[4]),
                "confidence": r[5],
                "domain": r[6],
            }
            for r in rows
        ]

    def add_negative_recipe(
        self,
        name: str,
        description: str,
        trigger_pattern: str,
        steps: list,
        domain: str = "general",
    ) -> int:
        """Store a pattern that was rejected multiple times - agent should avoid this."""
        with self._conn() as conn:
            existing = conn.execute(
                "SELECT id, times_rejected FROM negative_recipes WHERE name = ?", (name,)
            ).fetchone()
            if existing:
                conn.execute(
                    """UPDATE negative_recipes
                       SET times_rejected = times_rejected + 1, last_seen_ts = ?
                       WHERE id = ?""",
                    (time.time(), existing[0]),
                )
                return existing[0]
            try:
                cur = conn.execute(
                    """INSERT INTO negative_recipes
                       (name, description, trigger_pattern, steps, times_rejected,
                        domain, created_ts, last_seen_ts)
                       VALUES (?, ?, ?, ?, 1, ?, ?, ?)""",
                    (
                        name,
                        description,
                        trigger_pattern,
                        json.dumps(steps),
                        domain,
                        time.time(),
                        time.time(),
                    ),
                )
                return cur.lastrowid
            except sqlite3.IntegrityError:
                return -1

    def get_negative_recipes(self, min_rejections: int = 3) -> list[dict]:
        """Get anti-patterns the agent should avoid."""
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT id, name, description, trigger_pattern, steps,
                       times_rejected, domain, created_ts, last_seen_ts
                FROM negative_recipes WHERE times_rejected >= ?
                ORDER BY times_rejected DESC
            """,
                (min_rejections,),
            ).fetchall()
        return [
            {
                "id": r[0],
                "name": r[1],
                "description": r[2],
                "trigger": r[3],
                "steps": json.loads(r[4]),
                "times_rejected": r[5],
                "domain": r[6],
                "created_ts": r[7],
                "last_seen_ts": r[8],
            }
            for r in rows
        ]

    def expire_stale(self, days: int = 90, min_confidence: float = 0.1):
        """Delete recipes with confidence below min_confidence AND last_used_ts older than days."""
        cutoff = time.time() - (days * 86400)
        with self._conn() as conn:
            conn.execute(
                """
                DELETE FROM recipes
                WHERE confidence < ? AND last_used_ts < ?
            """,
                (min_confidence, cutoff),
            )

    def stats(self) -> dict:
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM recipes").fetchone()[0]
            high = conn.execute("SELECT COUNT(*) FROM recipes WHERE confidence >= 0.7").fetchone()[
                0
            ]
        return {"total_recipes": total, "high_confidence": high}


# ══════════════════════════════════════════════════════════════════════
#  Pattern Analyser
# ══════════════════════════════════════════════════════════════════════


class PatternAnalyser:
    """
    Reads the session log and promotes repeated successful patterns
    into the recipe book.
    Runs in the background after each session.
    """

    PROMOTION_THRESHOLD = 2  # how many times a pattern must appear

    def __init__(self, session_log, recipe_book: RecipeBook):
        self.log = session_log
        self.recipes = recipe_book

    def run(self) -> int:
        """
        Analyse logs and promote patterns.
        Returns the number of new recipes created.
        """
        new_count = 0
        new_count += self._analyse_tool_sequences()
        new_count += self._analyse_node_creation_patterns()
        self._analyse_rejected_patterns()
        return new_count

    def _analyse_tool_sequences(self) -> int:
        """Promote frequently accepted tool calls into recipes."""
        patterns = self.log.get_accepted_tool_sequences(self.PROMOTION_THRESHOLD)
        created = 0
        for p in patterns:
            try:
                args_dict = json.loads(p["args"]) if isinstance(p["args"], str) else p["args"]
            except Exception:
                args_dict = {}

            name = f"auto_{p['tool']}_{p['count']}x"
            description = (
                f"Automatically promoted: tool '{p['tool']}' was accepted "
                f"{p['count']} times with similar arguments."
            )
            steps = [{"tool": p["tool"], "args": args_dict}]
            trigger = f"user needs to {p['tool'].replace('_', ' ')}"

            recipe_id = self.recipes.add_recipe(
                name=name,
                description=description,
                trigger_pattern=trigger,
                steps=steps,
            )
            if recipe_id > 0:
                created += 1
        return created

    def _analyse_node_creation_patterns(self) -> int:
        """Find nodes the user always creates together and make a recipe."""
        events = self.log.get_scene_event_patterns("node", self.PROMOTION_THRESHOLD)
        created = 0
        for ev in events:
            data = ev["data"]
            if data.get("event") != "ChildCreated":
                continue
            node_type = data.get("node_type", "unknown")
            name = f"auto_create_{node_type}_{ev['count']}x"
            description = (
                f"User creates '{node_type}' nodes frequently ({ev['count']} times observed)."
            )
            steps = [{"tool": "create_node", "args": {"node_type": node_type}}]
            trigger = f"create {node_type}"
            recipe_id = self.recipes.add_recipe(
                name=name,
                description=description,
                trigger_pattern=trigger,
                steps=steps,
            )
            if recipe_id > 0:
                created += 1
        return created

    def _analyse_rejected_patterns(self):
        """Find tool calls rejected 3+ times and promote them to negative recipes."""
        try:
            patterns = self.log.get_accepted_tool_sequences(min_count=1)
        except Exception:
            return
        for p in patterns:
            rejected_count = p.get("rejected_count", 0)
            if rejected_count < 3:
                continue
            try:
                args_dict = json.loads(p["args"]) if isinstance(p["args"], str) else p["args"]
            except Exception:
                args_dict = {}
            name = f"anti_{p['tool']}_{rejected_count}x_rejected"
            description = (
                f"Anti-pattern: tool '{p['tool']}' was rejected "
                f"{rejected_count} times. Avoid this approach."
            )
            steps = [{"tool": p["tool"], "args": args_dict}]
            trigger = f"user needs to {p['tool'].replace('_', ' ')}"
            self.recipes.add_negative_recipe(
                name=name,
                description=description,
                trigger_pattern=trigger,
                steps=steps,
            )


# ══════════════════════════════════════════════════════════════════════
#  Meta Rule Learner  (learns from the agent's own self-corrections)
# ══════════════════════════════════════════════════════════════════════


class MetaRuleLearner:
    """
    Watches for error → retry patterns in the session log.
    When the agent self-corrects at runtime (e.g. /object/ → /obj/,
    or adds missing `inputs` arrays), this class extracts that correction
    and writes it as a permanent rule into system_prompt_learned.txt.

    This is the autonomous version of what a human would do when they
    look at a debug session and add a rule manually.
    """

    # How many times a correction must appear before it becomes a rule
    PROMOTION_THRESHOLD = 1

    # Rules already covered in system_prompt_base.txt — don't duplicate them
    _BASE_RULES_FINGERPRINTS = {
        "/obj",
        "inputs",
        "origin",
        "dir",
        "points",
        "copytopoints",
    }

    def __init__(self, session_log, learned_path: str):
        self.log = session_log
        self.learned_path = learned_path
        # Track which rules we've already written so we don't duplicate
        self._seen_rules: set = set()
        self._load_existing_rules()

    def _load_existing_rules(self):
        """Load fingerprints of rules already in learned file."""
        if not os.path.exists(self.learned_path):
            return
        try:
            with open(self.learned_path, encoding="utf-8") as f:
                content = f.read()
            # Collect all lines under the meta-rules section
            in_section = False
            for line in content.splitlines():
                if "## Self-discovered correction rules" in line:
                    in_section = True
                    continue
                if in_section and line.startswith("## "):
                    break
                if in_section and line.startswith("- "):
                    self._seen_rules.add(line.strip())
        except Exception:
            pass

    def _extract_rule(self, tool: str, failed_args: dict, success_args: dict) -> str:
        """
        Given a fail→success pair, produce a human-readable rule string.
        Returns empty string if we can't extract a useful rule.
        """
        try:
            # ── parent_path corrections (e.g. /object/ → /obj/) ──────────
            f_parent = failed_args.get("parent_path", "")
            s_parent = success_args.get("parent_path", "")
            if f_parent and s_parent and f_parent != s_parent:
                return (
                    f"[{tool}] Wrong path `{f_parent}` → correct path is `{s_parent}`. "
                    f"Always use `{s_parent}` as parent_path for this context."
                )

            # ── node_path corrections ────────────────────────────────────
            f_path = failed_args.get("node_path", "")
            s_path = success_args.get("node_path", "")
            if f_path and s_path and f_path != s_path:
                # Extract just the prefix difference
                f_parts = f_path.split("/")
                s_parts = s_path.split("/")
                if len(f_parts) == len(s_parts):
                    for _i, (fp, sp) in enumerate(zip(f_parts, s_parts, strict=False)):
                        if fp != sp:
                            return (
                                f"[{tool}] Path segment `{fp}` is wrong — "
                                f"use `{sp}` instead. Correct path: `{s_path}`."
                            )

            # ── create_node_chain: missing inputs arrays ─────────────────
            if tool == "create_node_chain":
                f_chain = failed_args.get("chain", [])
                s_chain = success_args.get("chain", [])
                f_missing = [
                    s["name"]
                    for s in f_chain
                    if "inputs" not in s
                    and s.get("type") in {"merge", "copytopoints", "boolean", "attribtransfer"}
                ]
                s_has = [s["name"] for s in s_chain if "inputs" in s]
                if f_missing and s_has:
                    return (
                        f"[create_node_chain] Always include `inputs` array for "
                        f"multi-input nodes: {', '.join(f_missing)}. "
                        f"Without it the chain step fails."
                    )

            # ── parameter name corrections ────────────────────────────────
            f_parm = failed_args.get("parm_name", "")
            s_parm = success_args.get("parm_name", "")
            if f_parm and s_parm and f_parm != s_parm:
                node = success_args.get("node_path", "")
                return (
                    f"[{tool}] Parameter `{f_parm}` does not exist — "
                    f"use `{s_parm}` instead (on {node})."
                )

        except Exception:
            pass
        return ""

    def run(self) -> int:
        """
        Scan recent sessions for self-corrections, extract rules,
        append new ones to system_prompt_learned.txt.
        Returns number of new rules written.
        """
        pairs = self.log.get_error_retry_pairs(limit_interactions=30)
        new_rules = []

        for pair in pairs:
            try:
                failed_args = (
                    json.loads(pair["failed_args"])
                    if isinstance(pair["failed_args"], str)
                    else pair["failed_args"]
                )
                success_args = (
                    json.loads(pair["success_args"])
                    if isinstance(pair["success_args"], str)
                    else pair["success_args"]
                )
            except Exception:
                continue

            rule = self._extract_rule(pair["tool"], failed_args, success_args)
            if not rule:
                continue
            rule_line = f"- {rule}"
            if rule_line in self._seen_rules:
                continue  # already written
            new_rules.append(rule_line)
            self._seen_rules.add(rule_line)

        if not new_rules:
            return 0

        # Append to system_prompt_learned.txt under a dedicated section
        self._write_rules(new_rules)
        return len(new_rules)

    def _write_rules(self, new_rules: list):
        """Append new self-discovered rules into system_prompt_learned.txt."""
        try:
            # Read existing content
            if os.path.exists(self.learned_path):
                with open(self.learned_path, encoding="utf-8") as f:
                    content = f.read()
            else:
                content = ""

            SECTION_HEADER = "## Self-discovered correction rules (auto-generated)"

            if SECTION_HEADER in content:
                # Append inside the existing section
                insert_pos = content.index(SECTION_HEADER) + len(SECTION_HEADER)
                # Find the next section or end of file
                next_section = content.find("\n## ", insert_pos)
                if next_section == -1:
                    content = content + "\n" + "\n".join(new_rules)
                else:
                    content = (
                        content[:next_section]
                        + "\n"
                        + "\n".join(new_rules)
                        + content[next_section:]
                    )
            else:
                # Add a new section at the end
                block = (
                    f"\n\n{SECTION_HEADER}\n"
                    "These rules were inferred automatically from the agent's own "
                    "self-corrections during past sessions. They are exact replays of "
                    "✅ retry-after-❌ patterns observed in tool call logs.\n\n"
                    + "\n".join(new_rules)
                )
                content = content + block

            os.makedirs(os.path.dirname(self.learned_path), exist_ok=True)
            with open(self.learned_path, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception as e:
            print(f"[MetaRuleLearner] write failed: {e}")


# ══════════════════════════════════════════════════════════════════════
#  User-Lesson Learner
# ══════════════════════════════════════════════════════════════════════


class UserLessonLearner:
    """
    Extracts lessons from accepted interactions where the user's message
    looks like teaching/correction (imperatives, "please connect", "always
    do X", "next time", "remember", etc.) and at least one tool call ran
    successfully as a result.

    Unlike MetaRuleLearner — which only fires on agent self-correction
    (fail → success of the same tool) — this captures lessons the user
    explicitly delivered, even when every tool call succeeded on the
    first try. The output is appended to system_prompt_learned.txt so
    future sessions inherit the lesson via the system prompt.
    """

    TEACHING_CUES = (
        "please ",
        "connect",
        "wire",
        "always",
        "never",
        "should",
        "must ",
        "make sure",
        "ensure ",
        "next time",
        "from now on",
        "remember",
        "keep this in mind",
        "don't forget",
        "do not forget",
        "instead",
    )

    # Trivial messages we never want to mine even if a cue happens to match
    SKIP_PHRASES = (
        "keep this in your mind",
        "keep this in mind",
        "remember this",
    )

    SECTION_HEADER = "## User-taught lessons (auto-generated from accepted teaching)"
    MAX_USER_MSG_CHARS = 220
    MAX_LESSONS_KEPT = 60

    def __init__(self, session_log, learned_path: str):
        self.log = session_log
        self.learned_path = learned_path
        self._seen_signatures: set[str] = set()
        self._load_existing_signatures()

    # ------------------------------------------------------------------
    # Existing-rule discovery (so we don't re-write duplicates)
    # ------------------------------------------------------------------
    def _load_existing_signatures(self):
        if not os.path.exists(self.learned_path):
            return
        try:
            with open(self.learned_path, encoding="utf-8") as f:
                content = f.read()
            in_section = False
            for line in content.splitlines():
                if self.SECTION_HEADER in line:
                    in_section = True
                    continue
                if in_section and line.startswith("## "):
                    break
                if in_section and line.startswith("- "):
                    sig = self._line_signature(line)
                    if sig:
                        self._seen_signatures.add(sig)
        except Exception:
            pass

    @staticmethod
    def _line_signature(line: str) -> str:
        # Cheap signature: lowercase, collapse whitespace, drop trailing meta.
        text = re.sub(r"\s+", " ", line).strip().lower()
        text = re.sub(r"\[seen .*?\]\s*$", "", text).strip()
        return text

    # ------------------------------------------------------------------
    # Teaching detection
    # ------------------------------------------------------------------
    def _looks_like_teaching(self, user_msg: str) -> bool:
        if not user_msg:
            return False
        text = user_msg.strip().lower()
        if len(text) < 10 or len(text) > 600:
            return False
        if any(skip in text for skip in self.SKIP_PHRASES):
            # Pure acknowledgement requests with no action content.
            return False
        return any(cue in text for cue in self.TEACHING_CUES)

    @staticmethod
    def _strip_live_context(user_msg: str) -> str:
        """Remove the [LIVE CONTEXT: …] block the UI prepends to user messages."""
        lines = []
        skipping = False
        for raw in (user_msg or "").splitlines():
            if raw.startswith("[LIVE CONTEXT:"):
                skipping = True
                continue
            if skipping and (raw.startswith("- ") or not raw.strip()):
                continue
            skipping = False
            lines.append(raw)
        return "\n".join(lines).strip()

    # ------------------------------------------------------------------
    # Tool-sequence summary
    # ------------------------------------------------------------------
    @staticmethod
    def _summarize_calls(tool_calls: list[dict]) -> str:
        parts = []
        for c in tool_calls:
            if not c.get("success"):
                continue
            try:
                args = json.loads(c["args"]) if isinstance(c["args"], str) else c["args"]
            except Exception:
                args = {}
            keys = (
                "from_path",
                "to_path",
                "from_out",
                "to_in",
                "node_path",
                "parent_path",
                "node_type",
                "name",
                "parm_name",
                "value",
            )
            kept = {k: args[k] for k in keys if k in args}
            kept_str = ", ".join(f"{k}={kept[k]!r}" for k in kept) if kept else ""
            parts.append(f"{c['tool']}({kept_str})")
        # Cap to keep prompt small
        if len(parts) > 6:
            parts = [*parts[:6], f"… +{len(parts) - 6} more"]
        return "; ".join(parts)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def run(self) -> int:
        """Scan recent accepted interactions, write new lessons. Returns count."""
        try:
            interactions = self.log.get_accepted_interactions_with_calls(limit_interactions=50)
        except Exception:
            return 0

        new_lines: list[str] = []
        for inter in interactions:
            user_msg = self._strip_live_context(inter.get("user", ""))
            if not self._looks_like_teaching(user_msg):
                continue
            tool_calls = inter.get("tool_calls") or []
            successful = [c for c in tool_calls if c.get("success")]
            if not successful:
                # Pure acknowledgement turn with no action — nothing to ground.
                continue
            summary = self._summarize_calls(successful)
            if not summary:
                continue
            short_msg = user_msg.strip().replace("\n", " ")
            if len(short_msg) > self.MAX_USER_MSG_CHARS:
                short_msg = short_msg[: self.MAX_USER_MSG_CHARS - 1] + "…"
            line = f'- When user says "{short_msg}" → {summary}'
            sig = self._line_signature(line)
            if not sig or sig in self._seen_signatures:
                continue
            self._seen_signatures.add(sig)
            new_lines.append(line)

        if not new_lines:
            return 0

        self._write_lessons(new_lines)
        return len(new_lines)

    # ------------------------------------------------------------------
    # File write
    # ------------------------------------------------------------------
    def _write_lessons(self, new_lines: list[str]):
        try:
            content = ""
            if os.path.exists(self.learned_path):
                with open(self.learned_path, encoding="utf-8") as f:
                    content = f.read()

            if self.SECTION_HEADER in content:
                head_idx = content.index(self.SECTION_HEADER) + len(self.SECTION_HEADER)
                next_section = content.find("\n## ", head_idx)
                section_end = next_section if next_section != -1 else len(content)
                section_body = content[head_idx:section_end]
                merged = section_body.rstrip() + "\n" + "\n".join(new_lines) + "\n"

                # Trim to most recent N lessons to keep prompt bounded.
                kept = [ln for ln in merged.splitlines() if ln.startswith("- ")][
                    -self.MAX_LESSONS_KEPT :
                ]
                rebuilt = "\n" + "\n".join(kept) + "\n"
                content = content[:head_idx] + rebuilt + content[section_end:]
            else:
                block = (
                    f"\n\n{self.SECTION_HEADER}\n"
                    "These were captured from past sessions where the user gave an "
                    "instruction and the agent's tool calls succeeded and were "
                    "accepted. Treat them as durable lessons unless the user "
                    "overrides them.\n\n" + "\n".join(new_lines) + "\n"
                )
                content = content + block

            os.makedirs(os.path.dirname(self.learned_path), exist_ok=True)
            with open(self.learned_path, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception as e:
            print(f"[UserLessonLearner] write failed: {e}")


# ══════════════════════════════════════════════════════════════════════
#  Self-Updater
# ══════════════════════════════════════════════════════════════════════


class SelfUpdater:
    """
    Rewrites the learned section of the system prompt based on
    what's in the recipe book.

    ONLY touches system_prompt_learned.txt.
    system_prompt_base.txt is NEVER modified.
    """

    def __init__(self, recipe_book: RecipeBook, data_dir: str):
        self.recipes = recipe_book
        self.data_dir = data_dir
        self.learned_path = os.path.join(data_dir, "system_prompt_learned.txt")

    def _load_preserved_guidance(self) -> list[str]:
        """
        Preserve any extra learned guidance already present in
        system_prompt_learned.txt so a learning run does not erase
        higher-value heuristics that were added previously.
        """
        if not os.path.exists(self.learned_path):
            return []

        try:
            with open(self.learned_path, encoding="utf-8") as f:
                lines = f.read().splitlines()
        except Exception:
            return []

        try:
            start = lines.index("## Behavioural guidance (learned from accepted interactions)") + 1
        except ValueError:
            return []

        default_lines = {
            "- Prefer suggesting specific parameter values over generic advice.",
            "- When the user accepts a suggestion, remember it for similar future situations.",
            "- Learned recipes are advisory only. Never apply them proactively when they would add nodes or steps the user did not request.",
            "",
        }
        preserved = []
        for line in lines[start:]:
            if line in default_lines:
                continue
            if not line.strip():
                continue
            preserved.append(line)
        return preserved

    def update(self) -> str:
        """
        Rebuild system_prompt_learned.txt from current recipes.
        Returns the new content.
        """
        recipes = self.recipes.get_all(min_confidence=0.5)
        if hasattr(self.recipes, "decay_stale"):
            self.recipes.decay_stale()
        if hasattr(self.recipes, "expire_stale"):
            self.recipes.expire_stale()
        preserved_guidance = self._load_preserved_guidance()

        if not recipes:
            content = "# Learned knowledge\n(No patterns learned yet.)\n"
        else:
            lines = [
                "# Learned knowledge (auto-generated — do not edit manually)",
                f"# Last updated: {time.strftime('%Y-%m-%d %H:%M')}",
                "",
                "## High-confidence workflow recipes",
                "",
            ]
            for r in recipes:
                if r["confidence"] >= 0.7:
                    lines.append(
                        f"- **{r['name']}** (confidence {r['confidence']}): {r['description']}"
                    )
                    if r["steps"]:
                        step_str = " → ".join(s["tool"] for s in r["steps"])
                        lines.append(f"  Steps: {step_str}")

            negative = []
            if hasattr(self.recipes, "get_negative_recipes"):
                negative = self.recipes.get_negative_recipes(min_rejections=1)
            if negative:
                lines += [
                    "",
                    "## Anti-patterns (avoid these)",
                    "",
                ]
                for nr in negative:
                    lines.append(f"- **{nr['name']}**: {nr['description']}")

            lines += [
                "",
                "## Domain observations",
                "",
            ]
            domains = {}
            for r in recipes:
                domains.setdefault(r["domain"], []).append(r)
            for domain, domain_recipes in domains.items():
                lines.append(f"- **{domain}**: {len(domain_recipes)} learned patterns")

            lines += [
                "",
                "## Behavioural guidance (learned from accepted interactions)",
                "- Prefer suggesting specific parameter values over generic advice.",
                "- When the user accepts a suggestion, remember it for similar future situations.",
                "- Learned recipes are advisory only. Never apply them proactively when they would add nodes or steps the user did not request.",
            ]
            for line in preserved_guidance:
                if line not in lines:
                    lines.append(line)
            content = "\n".join(lines)

        os.makedirs(self.data_dir, exist_ok=True)
        with open(self.learned_path, "w", encoding="utf-8") as f:
            f.write(content)

        return content


# ══════════════════════════════════════════════════════════════════════
#  Project Rule Book
# ══════════════════════════════════════════════════════════════════════


class ProjectRuleBook:
    """
    Stores explicit user/studio preferences as durable project rules.
    """

    RULE_CUES = (
        "always",
        "never",
        "should",
        "must",
        "prefer",
        "do not",
        "don't",
        "use that only",
        "main focus",
        "focus is",
        "need to",
        "needs to",
    )

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._use_memory_fallback = False
        self._fallback_rules: list[dict] = []
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        schema = """
            CREATE TABLE IF NOT EXISTS project_rules (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                rule_text       TEXT UNIQUE,
                source          TEXT,
                confidence      REAL DEFAULT 0.7,
                times_seen      INTEGER DEFAULT 1,
                created_ts      REAL,
                last_seen_ts    REAL
            );
        """
        try:
            with self._conn() as conn:
                conn.executescript(schema)
        except sqlite3.OperationalError:
            # A stale or partially written DB file should not brick preference memory.
            try:
                if os.path.exists(self.db_path):
                    os.remove(self.db_path)
            except OSError:
                pass
            try:
                with self._conn() as conn:
                    conn.executescript(schema)
            except sqlite3.OperationalError:
                self._use_memory_fallback = True

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _normalize_rule_text(rule_text: str) -> str:
        text = re.sub(r"\s+", " ", (rule_text or "").strip())
        return text.rstrip(" .")

    def add_or_update_rule(
        self, rule_text: str, source: str = "user_preference", confidence: float = 0.75
    ) -> bool:
        normalized = self._normalize_rule_text(rule_text)
        if len(normalized) < 12:
            return False
        now = time.time()
        if self._use_memory_fallback:
            existing = next((r for r in self._fallback_rules if r["rule"] == normalized), None)
            if existing:
                existing["source"] = source
                existing["confidence"] = max(existing["confidence"], confidence)
                existing["times_seen"] += 1
                existing["last_seen_ts"] = now
                return False
            self._fallback_rules.append(
                {
                    "id": len(self._fallback_rules) + 1,
                    "rule": normalized,
                    "source": source,
                    "confidence": confidence,
                    "times_seen": 1,
                    "created_ts": now,
                    "last_seen_ts": now,
                }
            )
            return True
        with self._conn() as conn:
            existing = conn.execute(
                "SELECT id, confidence FROM project_rules WHERE rule_text=?",
                (normalized,),
            ).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE project_rules
                    SET source=?, confidence=?, times_seen=times_seen + 1, last_seen_ts=?
                    WHERE id=?
                    """,
                    (source, max(existing[1], confidence), now, existing[0]),
                )
                return False
            conn.execute(
                """
                INSERT INTO project_rules
                    (rule_text, source, confidence, times_seen, created_ts, last_seen_ts)
                VALUES (?, ?, ?, 1, ?, ?)
                """,
                (normalized, source, confidence, now, now),
            )
        return True

    def extract_rules(self, user_message: str) -> list[str]:
        text = (user_message or "").strip()
        if not text:
            return []
        segments = re.split(r"[\n\r]+|(?<=[.!?])\s+", text)
        rules = []
        for raw in segments:
            segment = self._normalize_rule_text(raw)
            lower = segment.lower()
            if len(segment) < 16 or len(segment) > 240:
                continue
            if not any(cue in lower for cue in self.RULE_CUES):
                continue
            if lower.startswith("[dry run]"):
                segment = self._normalize_rule_text(segment.replace("[Dry Run]", "", 1))
            if segment and segment not in rules:
                rules.append(segment)
        return rules[:8]

    def remember_from_message(
        self, user_message: str, source: str = "user_preference"
    ) -> list[str]:
        remembered = []
        for rule in self.extract_rules(user_message):
            self.add_or_update_rule(rule, source=source)
            remembered.append(rule)
        return remembered

    def boost_rule_confidence(self, rule_text: str, amount: float = 0.05) -> bool:
        """Increase the confidence of a rule, usually after a successful interaction."""
        normalized = self._normalize_rule_text(rule_text)
        now = time.time()
        if self._use_memory_fallback:
            existing = next((r for r in self._fallback_rules if r["rule"] == normalized), None)
            if existing:
                existing["confidence"] = min(0.99, existing["confidence"] + amount)
                existing["last_seen_ts"] = now
                return True
            return False
        with self._conn() as conn:
            existing = conn.execute(
                "SELECT id, confidence FROM project_rules WHERE rule_text=?",
                (normalized,),
            ).fetchone()
            if existing:
                new_conf = min(0.99, existing[1] + amount)
                conn.execute(
                    "UPDATE project_rules SET confidence=?, last_seen_ts=? WHERE id=?",
                    (new_conf, now, existing[0]),
                )
                return True
        return False

    def get_active_rules(self, limit: int = 8, min_confidence: float = 0.55) -> list[dict]:
        if self._use_memory_fallback:
            rows = [
                dict(rule)
                for rule in sorted(
                    self._fallback_rules,
                    key=lambda r: (r["confidence"], r["last_seen_ts"]),
                    reverse=True,
                )
                if rule["confidence"] >= min_confidence
            ]
            return rows[:limit]
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT id, rule_text, source, confidence, times_seen, last_seen_ts
                FROM project_rules
                WHERE confidence >= ?
                ORDER BY confidence DESC, last_seen_ts DESC
                LIMIT ?
                """,
                (min_confidence, limit),
            ).fetchall()
        return [
            {
                "id": r[0],
                "rule": r[1],
                "source": r[2],
                "confidence": round(r[3], 2),
                "times_seen": r[4],
                "last_seen_ts": r[5],
            }
            for r in rows
        ]

    def render_for_prompt(self, limit: int = 8) -> str:
        rules = self.get_active_rules(limit=limit)
        if not rules:
            return ""
        lines = [
            "[PROJECT RULES]",
            "These are durable user/studio preferences. Follow them unless the user overrides them explicitly:",
        ]
        for rule in rules:
            lines.append(f"- {rule['rule']}")
        return "\n".join(lines)

    def stats(self) -> dict:
        if self._use_memory_fallback:
            total = len(self._fallback_rules)
            strong = sum(1 for rule in self._fallback_rules if rule["confidence"] >= 0.75)
            return {"total_rules": total, "strong_rules": strong}
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM project_rules").fetchone()[0]
            strong = conn.execute(
                "SELECT COUNT(*) FROM project_rules WHERE confidence >= 0.75"
            ).fetchone()[0]
        return {"total_rules": total, "strong_rules": strong}


# ══════════════════════════════════════════════════════════════════════
#  Memory Manager — unified interface
# ══════════════════════════════════════════════════════════════════════


class MemoryManager:
    """
    Single entry point for all memory operations.
    The AgentLoop and UI interact only with this class.
    """

    def __init__(self, data_dir: str, debug_logger=None, hou_job_dir: str | None = None):
        from .session_log import SessionLog

        self.data_dir = data_dir

        # Resolve $JOB for namespacing. The caller should pass hou_job_dir
        # pre-resolved on Houdini's main thread — calling hou.* here from a
        # background init thread would acquire the HOM lock and freeze the
        # Houdini UI. Fall back to a hou.* call only if hou_job_dir wasn't
        # supplied AND we happen to be on the main thread.
        job_dir = data_dir
        if hou_job_dir and os.path.isdir(hou_job_dir):
            job_dir = os.path.join(hou_job_dir, "houdinimind")
        else:
            try:
                import threading as _threading

                if _threading.current_thread() is _threading.main_thread():
                    import hou

                    job = hou.expandString("$JOB")
                    if job and job != "$JOB" and os.path.isdir(job):
                        job_dir = os.path.join(job, "houdinimind")
            except Exception:
                pass

        db_dir = os.path.join(job_dir, "db")
        os.makedirs(db_dir, exist_ok=True)

        self.session_log = SessionLog(os.path.join(db_dir, "sessions.db"))
        self.recipe_book = RecipeBook(os.path.join(db_dir, "recipes.db"))
        self.project_rules = ProjectRuleBook(os.path.join(db_dir, "project_rules.db"))
        self.pattern_analyser = PatternAnalyser(self.session_log, self.recipe_book)
        self.self_updater = SelfUpdater(self.recipe_book, job_dir)
        self.meta_rule_learner = MetaRuleLearner(
            self.session_log,
            os.path.join(job_dir, "system_prompt_learned.txt"),
        )
        self.user_lesson_learner = UserLessonLearner(
            self.session_log,
            os.path.join(job_dir, "system_prompt_learned.txt"),
        )
        self._current_interaction_id: int | None = None
        self._last_user_message: str = ""
        self.debug_logger = debug_logger  # optional, set after construction

    def _get_current_hip_path(self) -> str:
        # Only call hou.* on the main thread — calling from a background
        # thread acquires the HOM lock and stalls the Houdini UI.
        try:
            import threading as _threading

            if _threading.current_thread() is not _threading.main_thread():
                return ""
            import hou

            return hou.hipFile.path() or ""
        except Exception:
            return ""

    def start_interaction(self, user_message: str, domain: str | None = None) -> int:
        try:
            self._last_user_message = user_message or ""
            rules_before = self.project_rules.stats().get("total_rules", 0)

            self.project_rules.remember_from_message(self._last_user_message)

            rules_after = self.project_rules.stats().get("total_rules", 0)
            if self.debug_logger and rules_after > rules_before:
                source_type = "rule_extracted"
                self.debug_logger.log_memory_op(
                    source_type,
                    meta={
                        "new_rules": rules_after - rules_before,
                        "total_rules": rules_after,
                        "source_msg": user_message[:200],
                        "summary": f"+{rules_after - rules_before} rules extracted ({source_type})",
                    },
                )
            iid = self.session_log.log_interaction(
                user_message,
                "",
                domain=domain,
                hip_file=self._get_current_hip_path(),
            )
            self._current_interaction_id = iid
            return iid
        except Exception:
            return -1

    def finish_interaction(self, agent_response: str, interaction_id: int | None = None):
        target_id = interaction_id or self._current_interaction_id
        if not target_id or target_id < 1:
            return
        try:
            self.session_log.update_interaction_response(target_id, agent_response)
            self._current_interaction_id = target_id
        except Exception:
            pass

    def log_interaction(
        self, user_message: str, agent_response: str, domain: str | None = None
    ) -> int:
        iid = self.start_interaction(user_message, domain=domain)
        if iid > 0:
            self.finish_interaction(agent_response, iid)
        return iid

    def log_tool_call(self, tool_name: str, args: dict, result: dict):
        try:
            self.session_log.log_tool_call(tool_name, args, result, self._current_interaction_id)
        except Exception:
            pass

    def log_scene_event(self, category: str, data: dict):
        try:
            self.session_log.log_scene_event(category, data)
        except Exception:
            pass

    def record_feedback(self, accepted: bool, rating: int | None = None):
        """Called when user hits Accept or Reject in the UI."""
        if self._current_interaction_id and self._current_interaction_id > 0:
            self.session_log.mark_feedback(self._current_interaction_id, accepted, rating)

        if accepted and self._last_user_message:
            # Boost confidence of rules found in this message since they worked!
            rules = self.project_rules.extract_rules(self._last_user_message)
            for rule in rules:
                self.project_rules.boost_rule_confidence(rule, amount=0.05)

            # Also ensure they are stored (if they weren't already)
            self.project_rules.remember_from_message(
                self._last_user_message,
                source="accepted_user_preference",
            )

        if self.debug_logger:
            self.debug_logger.log_memory_op(
                "feedback_recorded",
                meta={
                    "accepted": accepted,
                    "rating": rating,
                    "interaction_id": self._current_interaction_id,
                    "summary": f"{'✅ accepted' if accepted else '❌ rejected'}"
                    + (f" rating={rating}" if rating else ""),
                },
            )

    def run_learning_cycle(self) -> dict:
        """
        Run the full learning pipeline:
          1. Analyse patterns → recipe book
          2. Meta-rule learning → extract self-corrections → system_prompt_learned.txt
          3. Rebuild system prompt section
          4. Refresh the retrievable JSON knowledge base
        Returns a summary dict.
        """
        new_recipes = self.pattern_analyser.run()
        new_meta_rules = self.meta_rule_learner.run()  # self-correction rules
        new_user_lessons = self.user_lesson_learner.run()  # user-taught lessons
        self.self_updater.update()
        kb_rebuilt = False
        kb_error = None
        try:
            from ..rag.kb_builder import rebuild_kb_from_session_feedback

            rebuild_kb_from_session_feedback(self.data_dir)
            kb_rebuilt = True
        except Exception as e:
            kb_error = str(e)

        result = {
            "new_recipes": new_recipes,
            "new_meta_rules": new_meta_rules,
            "new_user_lessons": new_user_lessons,
            "recipe_stats": self.recipe_book.stats(),
            "log_stats": self.session_log.stats(),
        }
        result["kb_rebuilt"] = kb_rebuilt
        if kb_error:
            result["kb_error"] = kb_error

        if self.debug_logger:
            self.debug_logger.log_memory_op(
                "learning_cycle",
                meta={
                    "new_recipes": new_recipes,
                    "new_meta_rules": new_meta_rules,
                    "new_user_lessons": new_user_lessons,
                    "recipe_stats": self.recipe_book.stats(),
                    "kb_rebuilt": kb_rebuilt,
                    "kb_error": kb_error,
                    "summary": (
                        f"{new_recipes} new recipes, {new_meta_rules} meta-rules, "
                        f"{new_user_lessons} user lessons, kb_rebuilt={kb_rebuilt}"
                    ),
                },
            )
        return result

    # ── Conversation Persistence ──────────────────────────────────────
    def save_conversation(self, conversation: list[dict]):
        """Save the raw message list to a JSON file for session persistence."""
        try:
            db_dir = os.path.dirname(self.session_log.db_path)
            path = os.path.join(db_dir, "conversation.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(conversation, f, indent=2)
        except Exception:
            pass

    def load_conversation(self) -> list[dict]:
        """Load the persisted message list from the JSON store."""
        try:
            db_dir = os.path.dirname(self.session_log.db_path)
            path = os.path.join(db_dir, "conversation.json")
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return []

    def get_recipes(self, query: str | None = None) -> list[dict]:
        if query:
            return self.recipe_book.search(query)
        return self.recipe_book.get_all()

    def get_project_rules(self, limit: int = 8) -> list[dict]:
        return self.project_rules.get_active_rules(limit=limit)

    def get_project_rules_prompt(self, limit: int = 8) -> str:
        return self.project_rules.render_for_prompt(limit=limit)

    def dashboard(self) -> dict:
        return {
            "log": self.session_log.stats(),
            "recipes": self.recipe_book.stats(),
            "project_rules": self.project_rules.stats(),
        }
