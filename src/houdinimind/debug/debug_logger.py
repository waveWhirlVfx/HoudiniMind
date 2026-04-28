# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
import atexit
import base64
import contextlib
import datetime
import json
import os
import time
import traceback
from typing import Any


class DebugLogger:
    """
    Lightweight session logger for HoudiniMind.
    Writes a human-readable Markdown log plus a JSONL event stream.

    Changes v2:
      - phase() context manager      : auto-times any named phase
      - log_phase_start/end          : explicit open/close with elapsed_ms
      - log_llm_call records latency : elapsed_ms forwarded from caller
      - log_cache_event wired        : records hits/misses with running totals
      - log_rag records scores/count : meta dict forwarded from retriever
      - get_session_summary()        : aggregated stats dict for UI display
    """

    def __init__(self, data_dir: str):
        self.root_dir = os.path.join(data_dir, "debug", "sessions")
        self.session_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.started_at = datetime.datetime.now().isoformat()
        self.session_dir = os.path.join(self.root_dir, self.session_id)
        os.makedirs(self.session_dir, exist_ok=True)

        self.md_path = os.path.join(self.session_dir, "session.md")
        self.jsonl_path = os.path.join(self.session_dir, "session.jsonl")
        self.meta_path = os.path.join(self.session_dir, "session_meta.json")
        self.turn_index = 0
        self._meta_dirty = False  # deferred meta write flag

        # Line buffering (1) instead of 64k so logs survive active crashes
        self._md_file = open(self.md_path, "w", encoding="utf-8", buffering=1)
        self._jsonl_file = open(self.jsonl_path, "a", encoding="utf-8", buffering=1)

        # Aggregated counters queryable via get_session_summary()
        self._stats = {
            "llm_calls": 0,
            "tool_calls": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "rag_fetches": 0,
            "tool_errors": 0,
            "phase_latencies": {},  # phase_name -> [elapsed_ms, ...]
        }

        self._phase_stack: list = []  # (name, start_time)

        self._meta = {
            "session_id": self.session_id,
            "started_at": self.started_at,
            "turn_count": 0,
        }

        self._md_file.write(f"# HoudiniMind Debug Session: {self.session_id}\n\n")
        self._md_file.write(f"Started At: {self.started_at}\n\n---\n\n")
        # Don't flush here — buffer will be written at first natural sync point
        self._write_meta()  # write once at startup
        atexit.register(self.close)

    # ── Session config ────────────────────────────────────────────────

    def log_session_config(self, config: dict, extra: dict | None = None):
        payload = {"config": self._compact(config), "extra": self._compact(extra or {})}
        self._meta["config"] = payload
        self._write_meta()
        self._append_jsonl({"event": "session_config", "payload": payload, "ts": time.time()})

        # New: Write to Markdown for user visibility
        self._append_md("### Session Configuration\n\n")
        if extra:
            self._append_md("**Environment:**\n")
            for k, v in extra.items():
                self._append_md(f"- {k}: `{v}`\n")
            self._append_md("\n")

        self._append_md("**Agent Settings:**\n")
        # Log key settings explicitly for legibility
        keys = ["model", "vision_model", "turn_checkpoints", "max_tool_rounds", "temperature"]
        for k in keys:
            if k in config:
                self._append_md(f"- {k}: `{config[k]}`\n")
        if extra:
            self._append_md("\n**Runtime Snapshot:**\n")
            for k in ("Config Model", "Live Model", "Backend", "Vision"):
                if k in extra:
                    self._append_md(f"- {k}: `{extra[k]}`\n")

        self._append_md("\n---\n\n")
        # Flush once after session config — first real sync point

    # ── Turn lifecycle ────────────────────────────────────────────────

    def log_turn_start(self, user_message: str, meta: dict | None = None):
        self.turn_index += 1
        # Mark meta dirty — defer disk write to turn_end to avoid per-turn rewrite
        self._meta["turn_count"] = self.turn_index
        self._meta_dirty = True
        heading = str(user_message or "").strip().splitlines()[0] if user_message else ""
        self._append_md(
            f"## Turn: {heading}\n\n### Turn {self.turn_index}\n\n<user_request>\n{user_message}\n</user_request>\n\n"
        )
        if meta:
            parts = []
            for key in ("config_model", "live_model", "vision_model", "backend"):
                value = meta.get(key, "")
                if value:
                    parts.append(f"{key.replace('_', ' ').title()}: `{value}`")
            if parts:
                self._append_md("**Runtime:** " + " • ".join(parts) + "\n\n")
        self._append_jsonl(
            {
                "event": "turn_start",
                "turn_index": self.turn_index,
                "user_message": user_message,
                "meta": self._compact(meta or {}),
                "ts": time.time(),
            }
        )
        # No flush here — turn_end is the natural sync point

    def log_turn_end(self, response: str = "", meta: dict | None = None):
        self._append_md("---\n\n")
        self._append_jsonl(
            {
                "event": "turn_end",
                "turn_index": self.turn_index,
                "response_chars": len(response or ""),
                "meta": self._compact(meta or {}),
                "ts": time.time(),
            }
        )
        # Flush + commit deferred meta at turn boundary (once per turn, not per event)
        if self._meta_dirty:
            self._write_meta()
            self._meta_dirty = False
        self._flush_logs()

    # ── Phase timing ──────────────────────────────────────────────────

    def log_phase(self, name: str, status: str = "info", meta: dict | None = None):
        """Single-shot phase marker (no duration tracking)."""
        self._append_jsonl(
            {
                "event": "phase",
                "turn_index": self.turn_index,
                "name": name,
                "status": status,
                "meta": self._compact(meta or {}),
                "ts": time.time(),
            }
        )

    def log_phase_start(self, name: str, meta: dict | None = None) -> float:
        """Open a timed phase. Returns start timestamp."""
        t = time.time()
        self._phase_stack.append((name, t))
        phase_title = self._phase_markdown_title(name)
        if phase_title:
            self._append_md(f"### {phase_title}\n")
        self._append_jsonl(
            {
                "event": "phase_start",
                "turn_index": self.turn_index,
                "name": name,
                "meta": self._compact(meta or {}),
                "ts": t,
            }
        )
        return t

    def log_phase_end(
        self,
        name: str,
        status: str = "ok",
        started_at: float | None = None,
        meta: dict | None = None,
    ):
        """Close a timed phase, recording elapsed_ms."""
        now = time.time()
        if self._phase_stack and self._phase_stack[-1][0] == name:
            _, started_at = self._phase_stack.pop()
        elapsed_ms = int((now - started_at) * 1000) if started_at else None
        if elapsed_ms is not None:
            self._stats["phase_latencies"].setdefault(name, []).append(elapsed_ms)
        phase_title = self._phase_markdown_title(name)
        if phase_title:
            parts = [f"- status: `{status}`"]
            if elapsed_ms is not None:
                parts.append(f"- elapsed_ms: `{elapsed_ms}`")
            compact_meta = self._compact(meta or {})
            if compact_meta:
                parts.append(f"- meta: `{json.dumps(compact_meta, ensure_ascii=True)}`")
            self._append_md("\n".join(parts) + "\n\n")
        self._append_jsonl(
            {
                "event": "phase_end",
                "turn_index": self.turn_index,
                "name": name,
                "status": status,
                "elapsed_ms": elapsed_ms,
                "meta": self._compact(meta or {}),
                "ts": now,
            }
        )

    @contextlib.contextmanager
    def phase(self, name: str, meta: dict | None = None):
        """
        Context manager for automatic phase timing::

            with logger.phase("rag_fetch"):
                results = retriever.fetch(query)
        """
        started = self.log_phase_start(name, meta=meta)
        status = "ok"
        try:
            yield
        except Exception:
            status = "error"
            raise
        finally:
            self.log_phase_end(name, status=status, started_at=started)

    # ── LLM calls ─────────────────────────────────────────────────────

    def log_llm_call(
        self,
        stage: str,
        status: str = "info",
        elapsed_ms: int | None = None,
        meta: dict | None = None,
        model: str | None = None,
        tokens_in: int | None = None,
        tokens_out: int | None = None,
    ):
        self._stats["llm_calls"] += 1
        self._append_jsonl(
            {
                "event": "llm_call",
                "turn_index": self.turn_index,
                "stage": stage,
                "status": status,
                "elapsed_ms": elapsed_ms,
                "model": model,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "total_llm_calls": self._stats["llm_calls"],
                "meta": self._compact(meta or {}),
                "ts": time.time(),
            }
        )

    def log_llm_output(
        self,
        round_index: int,
        task: str,
        content: str,
        tool_calls: list | None = None,
        model: str | None = None,
        meta: dict | None = None,
    ):
        text = str(content or "").strip()
        if not text:
            return
        text_md = text if len(text) <= 8000 else text[:8000] + "\n...[truncated]"
        text_json = text if len(text) <= 12000 else text[:12000] + "... [truncated]"
        tool_names = []
        for tc in tool_calls or []:
            try:
                name = (tc.get("function") or {}).get("name", "")
                if name:
                    tool_names.append(str(name))
            except Exception:
                continue
        self._append_md(
            f"### LLM Round {int(round_index) + 1} ({task or 'default'})\n"
            f'<llm_round model="{model or ""}" tool_calls="{len(tool_names)}">\n'
            f"{text_md}\n"
            f"</llm_round>\n\n"
        )
        self._append_jsonl(
            {
                "event": "llm_output",
                "turn_index": self.turn_index,
                "round": int(round_index),
                "task": task or "",
                "model": model or "",
                "tool_calls": tool_names,
                "content": text_json,
                "meta": self._compact(meta or {}),
                "ts": time.time(),
            }
        )

    # ── RAG ───────────────────────────────────────────────────────────

    def log_rag(self, meta: dict):
        """
        meta should include: query, mode, top_k, result_count,
        scores (list[float]), elapsed_ms, source_names (list[str]).
        """
        self._stats["rag_fetches"] += 1
        self._append_jsonl(
            {
                "event": "rag",
                "turn_index": self.turn_index,
                "meta": self._compact(meta or {}),
                "ts": time.time(),
            }
        )

    # ── Scene snapshot ────────────────────────────────────────────────

    def log_scene_snapshot(self, status: str, meta: dict | None = None):
        self._append_jsonl(
            {
                "event": "scene_snapshot",
                "turn_index": self.turn_index,
                "status": status,
                "meta": self._compact(meta or {}),
                "ts": time.time(),
            }
        )

    # ── Cache ─────────────────────────────────────────────────────────

    def log_cache_event(self, cache_name: str, hit: bool, meta: dict | None = None):
        if hit:
            self._stats["cache_hits"] += 1
        else:
            self._stats["cache_misses"] += 1
        self._append_jsonl(
            {
                "event": "cache",
                "turn_index": self.turn_index,
                "cache_name": cache_name,
                "hit": bool(hit),
                "total_hits": self._stats["cache_hits"],
                "total_misses": self._stats["cache_misses"],
                "meta": self._compact(meta or {}),
                "ts": time.time(),
            }
        )

    # ── Screenshots ───────────────────────────────────────────────────

    def log_screenshot(
        self,
        label: str,
        image_path: str | None = None,
        image_b64: str | None = None,
        meta: dict | None = None,
    ):
        target_name = f"{label}_{int(time.time())}.png"
        target_path = os.path.join(self.session_dir, target_name)

        saved = False
        if image_b64:
            try:
                with open(target_path, "wb") as f:
                    f.write(base64.b64decode(image_b64))
                saved = True
            except Exception as e:
                self._append_jsonl(
                    {
                        "event": "screenshot_error",
                        "label": label,
                        "reason": f"base64 decode failed: {e}",
                        "ts": time.time(),
                    }
                )
        elif image_path and os.path.exists(image_path):
            import shutil

            shutil.copy(image_path, target_path)
            saved = True

        if saved:
            self._append_md(f"### {label}\n![{label}]({target_name})\n\n")
            self._append_jsonl(
                {
                    "event": "screenshot",
                    "turn_index": self.turn_index,
                    "label": label,
                    "file": target_name,
                    "meta": self._compact(meta or {}),
                    "ts": time.time(),
                }
            )
        else:
            self._append_md(f"### {label}\n_capture unavailable_\n\n")
            self._append_jsonl(
                {
                    "event": "screenshot_skipped",
                    "turn_index": self.turn_index,
                    "label": label,
                    "meta": self._compact(meta or {}),
                    "ts": time.time(),
                }
            )
        # Screenshots are infrequent (5-6/session) — flush so image + log stay in sync
        self._flush_logs()

    # ── Tools ─────────────────────────────────────────────────────────

    def log_tool_call(self, tool: str, args: dict, result: dict, meta: dict | None = None):
        self._stats["tool_calls"] += 1
        is_error = result.get("status") != "ok"
        if is_error:
            self._stats["tool_errors"] += 1

        status_icon = "✅" if not is_error else "❌"
        duration_ms = (result.get("_meta") or {}).get("duration_ms")
        self._append_md(f"#### {status_icon} `{tool}`\n")
        self._append_md(
            f'<tool_call name="{tool}" duration_ms="{duration_ms if duration_ms is not None else "unknown"}">\n'
        )
        self._append_md(f"<args>\n{json.dumps(args, indent=2)}\n</args>\n")
        if is_error:
            self._append_md(f"<error>\n{result.get('message', 'No message')}\n</error>\n")
        else:
            self._append_md(f"<result>\n{result.get('message', 'No message')}\n</result>\n")
        self._append_md("</tool_call>\n\n")
        self._append_jsonl(
            {
                "event": "tool",
                "turn_index": self.turn_index,
                "tool": tool,
                "args": self._compact(args),
                "status": result.get("status"),
                "message": result.get("message"),
                "duration_ms": duration_ms,
                "data": self._compact(result.get("data")),
                "meta": self._compact(meta or {}),
                "ts": time.time(),
            }
        )

    # ── Misc ──────────────────────────────────────────────────────────

    def log_response(self, response: str, meta: dict | None = None):
        self._append_md(
            f"### Agent Response\n<agent_response>\n{response}\n</agent_response>\n\n---\n\n"
        )
        self._append_jsonl(
            {
                "event": "response",
                "turn_index": self.turn_index,
                "content": response,
                "meta": self._compact(meta or {}),
                "ts": time.time(),
            }
        )
        # Flush at response boundary — natural end-of-content sync point

    def log_plan(self, plan_data: dict):
        scale = (plan_data or {}).get("prototype_scale") or {}
        if isinstance(scale, dict) and scale:
            self._append_md("#### Prototype Scale\n")
            for key in ("unit", "overall_size", "notes"):
                value = str(scale.get(key) or "").strip()
                if value:
                    self._append_md(f"- {key}: {value}\n")
            self._append_md("\n")

        phases = list((plan_data or {}).get("phases") or [])
        if not phases:
            self._append_md("_Plan generated with no phases._\n\n")
        else:
            for phase in phases:
                phase_name = str(phase.get("phase") or "Execution").strip()
                self._append_md(f"#### Stage: {phase_name}\n")
                for step in phase.get("steps", []):
                    step_no = step.get("step", "?")
                    action = str(step.get("action") or "").strip()
                    deps = list(step.get("dependency") or [])
                    risk = str(step.get("risk_level") or "").strip().lower()
                    suffix = []
                    if deps:
                        suffix.append(f"deps={deps}")
                    if risk and risk != "low":
                        suffix.append(f"risk={risk}")
                    detail = f" ({'; '.join(suffix)})" if suffix else ""
                    self._append_md(f"- {step_no}. {action}{detail}\n")
                    prototype_detail = str(step.get("prototype_detail") or "").strip()
                    if prototype_detail:
                        self._append_md(f"  detail: {prototype_detail}\n")
                    measurements = step.get("measurements")
                    if isinstance(measurements, dict) and measurements:
                        parts = [f"{k}={v}" for k, v in measurements.items() if str(v).strip()]
                        if parts:
                            self._append_md(f"  measurements: {', '.join(parts)}\n")
                    elif measurements:
                        self._append_md(f"  measurements: {measurements}\n")
                    count = step.get("count")
                    if count not in (None, ""):
                        self._append_md(f"  count: {count}\n")
                    for key in ("placement", "spacing"):
                        value = str(step.get(key) or "").strip()
                        if value:
                            self._append_md(f"  {key}: {value}\n")
                    relationships = step.get("relationships") or []
                    if isinstance(relationships, list) and relationships:
                        rel = "; ".join(
                            str(item).strip() for item in relationships if str(item).strip()
                        )
                        if rel:
                            self._append_md(f"  relationships: {rel}\n")
                    for key in ("validation", "recovery"):
                        value = str(step.get(key) or "").strip()
                        if value:
                            self._append_md(f"  {key}: {value}\n")
                self._append_md("\n")
        self._append_jsonl(
            {
                "event": "plan",
                "turn_index": self.turn_index,
                "plan": self._compact(plan_data or {}),
                "ts": time.time(),
            }
        )

    def log_system_note(self, note: str, meta: dict | None = None):
        self._append_md(f"> **Internal Note:**\n> <system_note>\n> {note}\n> </system_note>\n\n")
        self._append_jsonl(
            {
                "event": "system_note",
                "turn_index": self.turn_index,
                "content": note,
                "meta": self._compact(meta or {}),
                "ts": time.time(),
            }
        )
        # Do NOT flush — system notes are called 20-25x per turn; flushing each one
        # adds 20+ blocking syscalls. Logs are flushed at turn_end and close().

    # ── LLM Retries ───────────────────────────────────────────────────

    def log_llm_retry(
        self,
        attempt: int,
        max_retries: int,
        http_code: int | None = None,
        error_type: str | None = None,
        delay_s: float | None = None,
        model: str | None = None,
        meta: dict | None = None,
    ):
        """Log each retry attempt inside _request_with_retry."""
        self._append_md(
            f"> ⚠️ **LLM Retry** attempt {attempt}/{max_retries}"
            + (f" — HTTP {http_code}" if http_code else "")
            + (f" ({error_type})" if error_type else "")
            + (f" — backoff {delay_s:.1f}s" if delay_s is not None else "")
            + "\n\n"
        )
        self._append_jsonl(
            {
                "event": "llm_retry",
                "turn_index": self.turn_index,
                "attempt": attempt,
                "max_retries": max_retries,
                "http_code": http_code,
                "error_type": error_type,
                "delay_s": delay_s,
                "model": model,
                "meta": self._compact(meta or {}),
                "ts": time.time(),
            }
        )

    # ── Token usage ───────────────────────────────────────────────────

    def log_token_usage(
        self,
        stage: str,
        tokens_in: int | None = None,
        tokens_out: int | None = None,
        model: str | None = None,
        context_window: int | None = None,
        total_duration_ms: int | None = None,
        meta: dict | None = None,
    ):
        """Log token counts returned by the LLM response (Ollama: prompt_eval_count / eval_count)."""
        total = (tokens_in or 0) + (tokens_out or 0)
        pct = None
        if context_window and total:
            pct = round(total / context_window * 100, 1)
        self._append_md(
            f"> 🔢 **Tokens** [{stage}]"
            + (f" in={tokens_in}" if tokens_in is not None else "")
            + (f" out={tokens_out}" if tokens_out is not None else "")
            + (f" total={total}" if total else "")
            + (f" ({pct}% of ctx)" if pct is not None else "")
            + "\n\n"
        )
        self._append_jsonl(
            {
                "event": "token_usage",
                "turn_index": self.turn_index,
                "stage": stage,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "tokens_total": total,
                "ctx_window": context_window,
                "ctx_pct": pct,
                "model": model,
                "total_duration_ms": total_duration_ms,
                "meta": self._compact(meta or {}),
                "ts": time.time(),
            }
        )

    # ── Model routing ─────────────────────────────────────────────────

    def log_model_routing(
        self,
        task: str,
        selected_model: str,
        default_model: str | None = None,
        routed_via: str | None = None,
        meta: dict | None = None,
    ):
        """Log model routing decisions from _get_model_for()."""
        is_override = selected_model != default_model if default_model else None
        self._append_jsonl(
            {
                "event": "model_routing",
                "turn_index": self.turn_index,
                "task": task,
                "selected_model": selected_model,
                "default_model": default_model,
                "routed_via": routed_via,
                "is_override": is_override,
                "meta": self._compact(meta or {}),
                "ts": time.time(),
            }
        )

    # ── Exceptions ────────────────────────────────────────────────────

    def log_exception(
        self, context: str, exc: Exception, stack_trace: str | None = None, meta: dict | None = None
    ):
        """Log a full exception with type, message, and stack trace."""
        exc_type = type(exc).__name__
        exc_msg = str(exc)
        trace = stack_trace or traceback.format_exc()
        self._append_md(
            f"### ❌ Exception in `{context}`\n"
            f'<exception context="{context}" type="{exc_type}">\n'
            f"<message>\n{exc_msg[:500]}\n</message>\n"
            f"<traceback>\n{trace[:2000]}\n</traceback>\n"
            f"</exception>\n\n"
        )
        self._append_jsonl(
            {
                "event": "exception",
                "turn_index": self.turn_index,
                "context": context,
                "exc_type": exc_type,
                "exc_msg": exc_msg[:1000],
                "stack_trace": trace[:3000],
                "meta": self._compact(meta or {}),
                "ts": time.time(),
            }
        )

    # ── Tool timeout ──────────────────────────────────────────────────

    def log_tool_timeout(self, tool_name: str, timeout_s: float, meta: dict | None = None):
        """Log when a tool execution hits the timeout threshold."""
        self._append_md(f"> ⏱️ **Tool Timeout:** `{tool_name}` exceeded {timeout_s:.0f}s limit\n\n")
        self._append_jsonl(
            {
                "event": "tool_timeout",
                "turn_index": self.turn_index,
                "tool_name": tool_name,
                "timeout_s": timeout_s,
                "meta": self._compact(meta or {}),
                "ts": time.time(),
            }
        )

    # ── Context budget ────────────────────────────────────────────────

    def log_context_budget(
        self,
        stage: str,
        message_count: int | None = None,
        estimated_tokens: int | None = None,
        context_window: int | None = None,
        pct_used: float | None = None,
        meta: dict | None = None,
    ):
        """Log context window usage before/after LLM calls."""
        if estimated_tokens and context_window and pct_used is None:
            pct_used = round(estimated_tokens / context_window * 100, 1)
        self._append_jsonl(
            {
                "event": "context_budget",
                "turn_index": self.turn_index,
                "stage": stage,
                "message_count": message_count,
                "estimated_tokens": estimated_tokens,
                "context_window": context_window,
                "pct_used": pct_used,
                "meta": self._compact(meta or {}),
                "ts": time.time(),
            }
        )

    # ── Memory operations ─────────────────────────────────────────────

    def log_memory_op(self, op: str, meta: dict | None = None):
        """
        Log a memory system operation.
        op examples: 'rule_extracted', 'recipe_promoted', 'feedback_recorded',
                     'learning_cycle', 'pattern_analysed', 'negative_recipe'
        """
        self._append_md(
            f"> 🧠 **Memory:** `{op}`"
            + (f" — {meta.get('summary', '')}" if meta and meta.get("summary") else "")
            + "\n\n"
        )
        self._append_jsonl(
            {
                "event": "memory_op",
                "turn_index": self.turn_index,
                "op": op,
                "meta": self._compact(meta or {}),
                "ts": time.time(),
            }
        )

    # ── RAG detail ────────────────────────────────────────────────────

    def log_rag_detail(self, meta: dict):
        """
        Extended RAG logging: chunk content snippets, dedup metrics,
        fallback queries used, and budget truncation info.
        meta keys: query, complexity, budget_tokens, initial_count, dedup_dropped,
                   fallback_queries_tried, chunks_truncated, chunk_previews (list of str),
                   used_count, estimated_tokens
        """
        self._stats["rag_fetches"] += 1
        self._append_jsonl(
            {
                "event": "rag_detail",
                "turn_index": self.turn_index,
                "meta": self._compact(meta or {}),
                "ts": time.time(),
            }
        )

    # ── Session summary ───────────────────────────────────────────────

    def get_session_summary(self) -> dict:
        """Returns aggregated stats snapshot. Safe to call at any time."""
        latency_summary = {}
        for pname, samples in self._stats["phase_latencies"].items():
            if samples:
                latency_summary[pname] = {
                    "calls": len(samples),
                    "avg_ms": round(sum(samples) / len(samples)),
                    "max_ms": max(samples),
                    "min_ms": min(samples),
                }
        total_cache = self._stats["cache_hits"] + self._stats["cache_misses"]
        hit_rate = round(self._stats["cache_hits"] / total_cache * 100, 1) if total_cache else 0.0
        return {
            "session_id": self.session_id,
            "turns": self.turn_index,
            "llm_calls": self._stats["llm_calls"],
            "tool_calls": self._stats["tool_calls"],
            "tool_errors": self._stats["tool_errors"],
            "rag_fetches": self._stats["rag_fetches"],
            "cache_hits": self._stats["cache_hits"],
            "cache_misses": self._stats["cache_misses"],
            "cache_hit_rate_pct": hit_rate,
            "phase_latencies": latency_summary,
        }

    def get_session_path(self) -> str:
        return self.md_path

    # ── Internals ─────────────────────────────────────────────────────

    def _append_md(self, content: str):
        self._md_file.write(content)
        self._md_file.flush()

    def _append_jsonl(self, data: dict):
        self._jsonl_file.write(json.dumps(data) + "\n")
        self._jsonl_file.flush()

    @staticmethod
    def _phase_markdown_title(name: str) -> str:
        return {
            "planning": "Planning",
            "vision_verify": "Vision Verification",
            "validation": "Validation",
        }.get(str(name or "").strip().lower(), "")

    def _write_meta(self):
        with open(self.meta_path, "w", encoding="utf-8") as f:
            json.dump(self._meta, f, indent=2, ensure_ascii=False)

    def _flush_logs(self):
        for handle_name in ("_md_file", "_jsonl_file"):
            h = getattr(self, handle_name, None)
            if h:
                try:
                    h.flush()
                except Exception:
                    pass

    def close(self):
        try:
            self._meta["summary"] = self.get_session_summary()
            self._write_meta()
        except Exception:
            pass
        for handle_name in ("_md_file", "_jsonl_file"):
            h = getattr(self, handle_name, None)
            if h:
                try:
                    h.flush()
                except Exception:
                    pass
                try:
                    h.close()
                except Exception:
                    pass
                setattr(self, handle_name, None)

    def _compact(self, value: Any, depth: int = 0):
        if depth > 5:
            return "<max-depth>"
        if isinstance(value, dict):
            return {str(k): self._compact(v, depth + 1) for k, v in list(value.items())[:20]}
        if isinstance(value, (list, tuple)):
            return [self._compact(v, depth + 1) for v in value[:20]]
        if isinstance(value, str):
            if len(value) > 2000:
                return value[:2000] + "... [truncated]"
            return value
        if isinstance(value, (int, float, bool)) or value is None:
            return value
        return str(value)
