# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
"""
HoudiniMind — Session Log
SQLite-backed log of every interaction, tool call, and scene event.
This raw data feeds the pattern analyser.
"""

import json
import os
import sqlite3
import time
from contextlib import contextmanager


class SessionLog:
    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------
    def _init_db(self):
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS interactions (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts          REAL NOT NULL,
                    user_msg    TEXT,
                    agent_resp  TEXT,
                    accepted    INTEGER DEFAULT NULL,  -- 1 accepted, 0 rejected, NULL unknown
                    rating      INTEGER DEFAULT NULL,  -- 1-5 optional
                    domain      TEXT,
                    hip_file    TEXT,
                    session_id  TEXT
                );

                CREATE TABLE IF NOT EXISTS tool_calls (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts          REAL NOT NULL,
                    interaction_id INTEGER,
                    tool_name   TEXT,
                    args        TEXT,
                    result      TEXT,
                    success     INTEGER,
                    FOREIGN KEY(interaction_id) REFERENCES interactions(id)
                );

                CREATE TABLE IF NOT EXISTS scene_events (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts          REAL NOT NULL,
                    category    TEXT,
                    event_data  TEXT,
                    session_id  TEXT
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

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------
    def log_interaction(
        self,
        user_message: str,
        agent_response: str,
        domain: str | None = None,
        hip_file: str | None = None,
        session_id: str | None = None,
    ) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO interactions
                   (ts, user_msg, agent_resp, domain, hip_file, session_id)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (time.time(), user_message, agent_response, domain, hip_file, session_id),
            )
            return cur.lastrowid

    def update_interaction_response(self, interaction_id: int, agent_response: str):
        with self._conn() as conn:
            conn.execute(
                "UPDATE interactions SET agent_resp=? WHERE id=?", (agent_response, interaction_id)
            )

    def log_tool_call(
        self, tool_name: str, args: dict, result: dict, interaction_id: int | None = None
    ):
        success = 1 if result.get("status") == "ok" else 0
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO tool_calls
                   (ts, interaction_id, tool_name, args, result, success)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    time.time(),
                    interaction_id,
                    tool_name,
                    json.dumps(args),
                    json.dumps(result),
                    success,
                ),
            )

    def log_scene_event(self, category: str, event_data: dict, session_id: str | None = None):
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO scene_events (ts, category, event_data, session_id)
                   VALUES (?, ?, ?, ?)""",
                (time.time(), category, json.dumps(event_data), session_id),
            )

    def mark_feedback(self, interaction_id: int, accepted: bool, rating: int | None = None):
        """Called when user clicks Accept/Reject in the UI."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE interactions SET accepted=?, rating=? WHERE id=?",
                (1 if accepted else 0, rating, interaction_id),
            )

    # ------------------------------------------------------------------
    # Reads for pattern analyser
    # ------------------------------------------------------------------
    def get_accepted_tool_sequences(self, min_count: int = 3) -> list[dict]:
        """
        Return tool call sequences that appeared in accepted interactions
        more than min_count times.
        """
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT tc.tool_name, tc.args, COUNT(*) as cnt
                FROM tool_calls tc
                JOIN interactions i ON tc.interaction_id = i.id
                WHERE i.accepted = 1
                GROUP BY tc.tool_name, tc.args
                HAVING cnt >= ?
                ORDER BY cnt DESC
            """,
                (min_count,),
            ).fetchall()
        return [{"tool": r[0], "args": r[1], "count": r[2]} for r in rows]

    def get_recent_interactions(self, limit: int = 50) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT id, ts, user_msg, agent_resp, accepted, rating, domain
                   FROM interactions ORDER BY ts DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [
            {
                "id": r[0],
                "ts": r[1],
                "user": r[2],
                "agent": r[3],
                "accepted": r[4],
                "rating": r[5],
                "domain": r[6],
            }
            for r in rows
        ]

    def get_scene_event_patterns(self, event_type: str, min_count: int = 5) -> list[dict]:
        """Find repeated patterns in scene events (e.g. always adds Fuse after Boolean)."""
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT event_data, COUNT(*) as cnt
                FROM scene_events
                WHERE category = ?
                GROUP BY event_data
                HAVING cnt >= ?
                ORDER BY cnt DESC
            """,
                (event_type, min_count),
            ).fetchall()
        return [{"data": json.loads(r[0]), "count": r[1]} for r in rows]

    def stats(self) -> dict:
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM interactions").fetchone()[0]
            accepted = conn.execute(
                "SELECT COUNT(*) FROM interactions WHERE accepted=1"
            ).fetchone()[0]
            rejected = conn.execute(
                "SELECT COUNT(*) FROM interactions WHERE accepted=0"
            ).fetchone()[0]
            tool_calls = conn.execute("SELECT COUNT(*) FROM tool_calls").fetchone()[0]
        return {
            "total_interactions": total,
            "accepted": accepted,
            "rejected": rejected,
            "tool_calls": tool_calls,
            "acceptance_rate": round(accepted / max(total, 1), 2),
        }

    def get_error_retry_pairs(self, limit_interactions: int = 20) -> list[dict]:
        """
        Find consecutive fail → success pairs for the same tool within the
        same interaction. These are the self-corrections the agent already
        made at runtime — we extract them as permanent rules.

        Returns list of dicts: {tool, failed_args, success_args, interaction_id}
        """
        with self._conn() as conn:
            # Fetch recent tool calls ordered by interaction + time
            rows = conn.execute(
                """
                SELECT tc.id, tc.interaction_id, tc.tool_name,
                       tc.args, tc.success, tc.ts
                FROM tool_calls tc
                JOIN interactions i ON tc.interaction_id = i.id
                WHERE i.id IN (
                    SELECT id FROM interactions ORDER BY ts DESC LIMIT ?
                )
                ORDER BY tc.interaction_id, tc.ts
            """,
                (limit_interactions,),
            ).fetchall()

        # Group by interaction_id
        from collections import defaultdict

        by_interaction = defaultdict(list)
        for row in rows:
            by_interaction[row[1]].append(
                {"id": row[0], "tool": row[2], "args": row[3], "success": row[4], "ts": row[5]}
            )

        pairs = []
        for iid, calls in by_interaction.items():
            for i in range(len(calls) - 1):
                curr, nxt = calls[i], calls[i + 1]
                # Same tool, first failed, second succeeded
                if (
                    curr["tool"] == nxt["tool"]
                    and curr["success"] == 0
                    and nxt["success"] == 1
                    and curr["args"] != nxt["args"]
                ):
                    pairs.append(
                        {
                            "tool": curr["tool"],
                            "failed_args": curr["args"],
                            "success_args": nxt["args"],
                            "interaction_id": iid,
                        }
                    )
        return pairs

    def get_accepted_interactions_with_calls(self, limit_interactions: int = 50) -> list[dict]:
        """
        Return recent interactions marked accepted=1, each paired with the
        ordered list of tool calls that ran inside it. Used by the
        UserLessonLearner to extract teaching → action lessons.
        """
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT id, ts, user_msg, agent_resp
                FROM interactions
                WHERE accepted = 1
                ORDER BY ts DESC
                LIMIT ?
                """,
                (limit_interactions,),
            ).fetchall()
            interactions = [
                {"id": r[0], "ts": r[1], "user": r[2] or "", "agent": r[3] or ""} for r in rows
            ]
            for inter in interactions:
                call_rows = conn.execute(
                    """
                    SELECT tool_name, args, success
                    FROM tool_calls
                    WHERE interaction_id = ?
                    ORDER BY ts
                    """,
                    (inter["id"],),
                ).fetchall()
                inter["tool_calls"] = [
                    {"tool": c[0], "args": c[1], "success": c[2]} for c in call_rows
                ]
        return interactions

    def search_past_successes(self, query: str, limit: int = 5) -> list[dict]:
        """
        Search through past interactions that were marked as 'accepted' (1).
        Uses a simple LIKE-based keyword search over user messages and responses.
        """
        kw = f"%{query}%"
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT user_msg, agent_resp, ts, hip_file
                FROM interactions
                WHERE accepted = 1
                AND (user_msg LIKE ? OR agent_resp LIKE ?)
                ORDER BY ts DESC LIMIT ?
            """,
                (kw, kw, limit),
            ).fetchall()
        return [{"user": r[0], "agent": r[1], "ts": r[2], "hip": r[3]} for r in rows]
