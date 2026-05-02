# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
"""
HoudiniMind — Agent Loop v12
Upgrades over v11:
  OPT-1  Full debug instrumentation — log_phase/log_llm_call/log_rag/log_cache_event
          wired at every meaningful pipeline stage with per-phase latency tracking.
  OPT-2  Model routing live        — _get_model_for() now actually dispatches per task;
          model_routing config keys respected (planning/build/debug/quick/research/vex).
  OPT-3  Adaptive planning         — plan_enabled only triggers for complex queries
          (word count >= 10 OR technical terms present); skips extra LLM round-trip
          for short/simple requests.
  OPT-4  Cache hit/miss logging    — _get_cached_tool_result calls log_cache_event so
          debug sessions show cache efficiency per turn.
  OPT-5  LLM call timing           — every LLM call is wrapped with start/elapsed_ms
          and forwarded to log_llm_call for latency breakdown.
  OPT-6  RAG logging               — _prefetch_rag logs query, mode, and result count
          to debug sessions via log_rag.
  OPT-7  data_dir guard            — falls back gracefully when data_dir is an
          inaccessible absolute path (Windows path on Linux etc).
"""

import base64
import binascii
import difflib
import hashlib
import json
import re
import threading
import time
import traceback as _traceback
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FutureTimeoutError
from functools import partial

from ..debug import DebugLogger
from ..memory.world_model import WorldModel
from . import preconditions as _preconditions
from ._tokenizer import count_message_tokens, count_tokens
from .budget import TurnBudget
from .clarification import Clarifier
from .critic import RepairCritic
from .llm_client import OllamaClient
from .proxy_reference import ReferenceProxyPlanner
from .request_modes import (
    BUILD_INTENT_RE,
    CACHE_TTL,
    DEBUG_INTENT_RE,
    FOLLOWUP_BUILD_RE,
    HDA_INTENT_RE,
    NON_SCENE_MUTATING_WRITE_TOOLS,
    NON_SEMANTIC_SOP_TYPES,
    NON_SUBSTANTIVE_COMPLETION_WRITE_TOOLS,
    READ_ONLY_TOOLS,
    SIMPLE_PRIMITIVE_SOP_TYPES,
    STRUCTURAL_SOP_TYPES,
    VEX_CODE_INTENT_RE,
    AutoResearcher,
    _asset_goal_terms,
    _build_mode_disabled_tools_for_query,
    _query_is_complex,
    _query_needs_workflow_grounding,
    _query_terms,
    get_rag_category_policy,
)
from .scene_observer import SceneObserver
from .semantic_scoring import (
    aggregate_view_scores,
    format_scorecard,
    parse_view_score,
)
from .sub_agents import PlannerAgent, ValidatorAgent
from .task_contracts import (
    build_task_contract,
    format_task_contract_guidance,
    task_contract_rag_categories,
    verify_task_contract,
)
from .tool_models import ToolArgumentError, ToolValidator
from .tool_retry import CircuitBreaker, RetryPolicy
from .tools import (
    TOOL_FUNCTIONS,
    TOOL_SAFETY_TIERS,
    TOOL_SCHEMAS,
    apply_scope_filter,
)

try:
    import hou

    HOU_AVAILABLE = True
except ImportError:
    HOU_AVAILABLE = False


# ══════════════════════════════════════════════════════════════════════
#  AgentLoop
# ══════════════════════════════════════════════════════════════════════
class AgentLoop:
    PROGRESS_SENTINEL = "\x00AGENT_PROGRESS\x00"
    LLM_TRACE_SENTINEL = "\x00LLM_TRACE\x00"

    # Internal scratch namespaces created by HoudiniMind for VEX validation
    # and ephemeral checks. These should never be reported as user-visible
    # outputs nor included in verification scope.
    _HOUDINIMIND_SCRATCH_PREFIXES = (
        "/obj/__HOUDINIMIND_TEMP_GEO__",
        "/obj/__HOUDINIMIND_VEX_CHECKER__",
    )

    @staticmethod
    def _compute_image_hash(image_b64: str | bytes | None) -> str:
        """Return a stable hash for viewport capture payloads."""
        if image_b64 is None:
            return ""
        payload = (
            image_b64.decode("utf-8", errors="ignore")
            if isinstance(image_b64, bytes)
            else str(image_b64)
        )
        payload = payload.strip()
        if "," in payload and payload[:64].lower().startswith("data:"):
            payload = payload.split(",", 1)[1]
        payload = "".join(payload.split())
        try:
            raw = base64.b64decode(payload, validate=True)
        except (binascii.Error, ValueError):
            raw = payload.encode("utf-8", errors="ignore")
        return hashlib.sha256(raw).hexdigest()

    @classmethod
    def _is_scratch_path(cls, path: str | None) -> bool:
        if not path:
            return False
        return any(path.startswith(p) for p in cls._HOUDINIMIND_SCRATCH_PREFIXES) or (
            "__HOUDINIMIND_" in path
        )

    def __init__(
        self,
        config: dict,
        memory_manager=None,
        on_tool_call: Callable | None = None,
        rag_injector=None,
    ):
        # ── Tool scope filter (modelling + FX focus) ────────────────────
        # Filter out texturing/rendering/USD/materials before anything else
        # reads TOOL_FUNCTIONS/TOOL_SCHEMAS. Safe no-op when
        # modeling_fx_only=False.
        try:
            apply_scope_filter(config)
        except Exception as _e:
            print(f"[HoudiniMind] Scope filter failed (non-fatal): {_e}")

        # OPT-7: resolve data_dir robustly BEFORE constructing OllamaClient,
        # so the embed cache can persist to disk on the first run.
        import os as _os

        _raw_data_dir = config.get("data_dir", "data")
        if _raw_data_dir == "__auto__":
            _raw_data_dir = _os.path.join(
                _os.path.dirname(_os.path.abspath(__file__)), "..", "..", "..", "data"
            )
        if not _os.path.isdir(_raw_data_dir):
            _raw_data_dir = _os.path.join(
                _os.path.dirname(_os.path.abspath(__file__)), "..", "..", "..", "data"
            )
        config["data_dir"] = _os.path.normpath(_raw_data_dir)

        # ── LLM Backend Selection ────────────────────────────────────────
        # Ollama-only backend.
        self.llm = OllamaClient(config)
        try:
            import houdinimind.agent.tools as _tools_mod

            _tools_mod._SHARED_EMBED_FN = self.llm.embed
            _tools_mod._SHARED_CHAT_SIMPLE_FN = self.llm.chat_simple
        except Exception as e:
            print(f"[HoudiniMind] Tools module wiring failed: {e}")
        self.memory = memory_manager
        self.memory_manager = memory_manager
        self.on_tool_call = on_tool_call
        self.rag = rag_injector
        self.config = config

        try:
            from .model_adapter import ModelAdapter

            self.model_adapter = ModelAdapter(
                self.llm.model, getattr(self.llm, "context_window", 32768), config
            )
        except Exception:
            self.model_adapter = None

        self.conversation: list[dict] = []
        if self.memory_manager:
            self.conversation = self.memory_manager.load_conversation()

        self.undo_stack: list[str] = []
        self._system_prompt_dirty = False
        self.system_prompt = self._build_system_prompt()

        if not self.conversation:
            self.conversation = [{"role": "system", "content": self.system_prompt}]
            if self.memory_manager:
                self.memory_manager.save_conversation(self.conversation)
        self.max_tool_rounds = config.get("max_tool_rounds", 16)
        self.tool_round_pause_s = float(config.get("tool_round_pause_s", 0.0))
        self.max_capture_pane_per_turn = int(config.get("max_capture_pane_per_turn", 2))
        self.fast_build_rounds = max(0, int(config.get("fast_build_rounds", 8)))
        self.fast_debug_rounds = max(0, int(config.get("fast_debug_rounds", 6)))
        self.max_auto_repairs = max(0, int(config.get("max_auto_repairs", 3)))
        self.turn_checkpoints_enabled = bool(config.get("auto_backup", False))
        self.auto_restore_on_failed_verification = bool(
            config.get("auto_restore_on_failed_verification", True)
        )
        self.verification_light_before_repair = bool(
            config.get("verification_light_before_repair", True)
        )
        self.auto_network_view_checks = bool(config.get("auto_network_view_checks", True))
        self.verify_skip_vision = bool(config.get("verify_skip_vision", False))
        self.clarification_enabled = bool(config.get("clarification_enabled", True))
        self._clarifier = Clarifier(self.llm, enabled=self.clarification_enabled)
        self.preconditions_enabled = bool(config.get("preconditions_enabled", True))
        # Active failure-driven blacklist: blocks repeating an identical
        # (tool, args) signature that has already failed recently.
        self.failure_blacklist_enabled = bool(config.get("failure_blacklist_enabled", True))
        self.failure_blacklist_window = max(1, int(config.get("failure_blacklist_window", 12)))
        self.tool_retry_enabled = bool(config.get("tool_retry_enabled", True))
        self._retry_policy = RetryPolicy(
            max_attempts=max(1, int(config.get("tool_retry_max_attempts", 3))),
            base_delay_s=max(0.05, float(config.get("tool_retry_base_delay_s", 0.4))),
            max_delay_s=max(0.5, float(config.get("tool_retry_max_delay_s", 4.0))),
        )
        self._circuit_breaker = CircuitBreaker(
            failure_threshold=max(2, int(config.get("circuit_breaker_threshold", 4))),
            cool_down_s=max(5.0, float(config.get("circuit_breaker_cool_down_s", 60.0))),
        )
        self._turn_budget = TurnBudget(
            wall_clock_s=max(10.0, float(config.get("turn_wall_clock_s", 240.0))),
            max_input_tokens=max(2000, int(config.get("turn_max_input_tokens", 200_000))),
            max_output_tokens=max(500, int(config.get("turn_max_output_tokens", 16_000))),
            enabled=bool(config.get("turn_budget_enabled", True)),
        )
        self.semantic_scoring_enabled = bool(config.get("semantic_scoring_enabled", True))
        self.semantic_score_threshold = float(config.get("semantic_score_threshold", 0.72))
        self.semantic_multiview_enabled = bool(config.get("semantic_multiview_enabled", False))
        self.semantic_multiview_engine = (
            str(config.get("semantic_multiview_engine", "karma")).strip().lower()
        )
        if self.semantic_multiview_engine not in {"opengl", "karma", "mantra"}:
            self.semantic_multiview_engine = "karma"
        self.semantic_run_on_goal_pass = bool(config.get("semantic_run_on_goal_pass", True))
        self.final_check_enabled = bool(config.get("final_check_enabled", False))
        self.early_completion_exit_enabled = bool(config.get("early_completion_exit_enabled", True))
        self.early_completion_min_round = max(1, int(config.get("early_completion_min_round", 4)))
        self.proxy_generation_enabled = bool(config.get("proxy_generation_enabled", True))
        self.max_history = 20
        self.compress_at = 16
        self.live_scene_max_chars = max(2000, int(config.get("live_scene_max_chars", 9000)))
        self.live_scene_max_nodes = max(12, int(config.get("live_scene_max_nodes", 80)))
        self.live_scene_max_connections = max(
            12, int(config.get("live_scene_max_connections", 120))
        )
        self.auto_param_recovery_similarity_cutoff = float(
            config.get("auto_param_recovery_similarity_cutoff", 0.9)
        )
        self._live_scene_json: str = None
        self.auto_researcher = AutoResearcher(
            self.llm,
            rag=rag_injector,
            max_iterations=config.get("research_iterations", 2),
        )
        self.debug_logger = DebugLogger(config.get("data_dir", "data"))
        # Wire debug_logger into LLM client so it can log retries & routing
        if hasattr(self.llm, "debug_logger"):
            self.llm.debug_logger = self.debug_logger
        # Wire debug_logger into memory_manager so it can log ops
        if self.memory_manager and hasattr(self.memory_manager, "debug_logger"):
            self.memory_manager.debug_logger = self.debug_logger
        # Wire debug_logger into rag injector so it can log chunk detail
        if self.rag and hasattr(self.rag, "debug_logger"):
            self.rag.debug_logger = self.debug_logger

        from .degradation import DegradationTracker

        self._degradation = DegradationTracker()

        # Confirmation gate
        self._confirm_callback: Callable | None = None
        self._confirm_event = threading.Event()
        self._confirm_result = False

        # Cancel gate
        self._cancel_event = threading.Event()

        # Tool result cache
        self._tool_cache: dict = {}
        self._tool_cache_lock = threading.Lock()
        self._scene_event_hooks = None
        self._scene_event_invalidations = 0

        # RAG follow-up cache — last prefetched context, reused for follow-up turns
        self._last_rag_query: str | None = None
        self._last_rag_mode: str | None = None
        self._last_rag_result = None
        self._rag_followup_reuses = 0
        self._turn_tool_counts: dict = {}
        self._turn_capture_pane_analyses = 0
        self._last_turn_tool_counts: dict = {}
        self._last_turn_tool_history: list[str] = []
        self._last_turn_write_tools: list[str] = []
        self._last_turn_mutation_summaries: list[str] = []
        self._last_turn_scene_diff_text: str | None = None
        self._last_turn_dry_run = False

        # Cross-turn error memory — persists across all turns in the session.
        # Each entry: {tool, error, request_tokens: set[str], turn: int}
        # Used to avoid repeating strategies that already failed on similar requests.
        self._cross_turn_failures: list[dict] = []
        self._turn_index: int = 0
        self._turn_failed_attempts: dict = {}  # populated by _run_loop, read by chat()
        self._current_turn_checkpoint_path: str | None = None
        self._last_turn_checkpoint_path: str | None = None
        self._last_turn_verification_report: dict | None = None
        self._last_turn_verification_text: str | None = None
        self._last_turn_semantic_text: str | None = None
        self._last_turn_semantic_scorecard: dict | None = None
        self._last_turn_output_paths: list[str] = []
        self._last_turn_network_review_text: str | None = None
        self._turn_network_capture_failed = False
        self._turn_scene_write_epoch = 0
        self._turn_snapshot_cache: dict = {}
        self._turn_capture_cache: dict = {}
        self._turn_tool_schema_cache: dict = {}
        self._last_snapshot: dict | None = None
        self._is_new_request = True
        self._fast_message_mode = False
        self._task_anchor: str | None = None  # survives history compression

        self._turn_checkpoint_attempted = False
        self._backup_done_this_session = False
        self._runtime_status_callback: Callable | None = None
        self._reference_proxy_planner = ReferenceProxyPlanner()

        # Phase 1: HACS Observation and World Model layer
        self.scene_observer = SceneObserver(
            modeling_fx_only=bool(config.get("modeling_fx_only", False))
        )
        self._cache_scene_observation = bool(config.get("cache_scene_observation", True))
        if not hasattr(self, "world_model"):
            self.world_model = WorldModel()
        # HARDENING: guard world_model against concurrent access from
        # background snapshot thread and main chat() thread.
        self._world_model_lock = threading.Lock()

        # ── v11 Intelligence Modules ──────────────────────────────────
        # Repair Critic: auto-diagnose tool errors and suggest fixes
        self._critic_enabled = bool(config.get("enable_repair_critic", False))
        self._critic = (
            RepairCritic(
                llm_chat_fn=self.llm.chat_simple,
                max_llm_evals_per_turn=3,
            )
            if self._critic_enabled
            else None
        )

        # Tool Validator: schema-based argument validation
        self._tool_validator = ToolValidator(TOOL_SCHEMAS)

        # Vision Feedback: VLM evaluates viewport after builds
        self._vision_enabled = bool(config.get("vision_enabled", True))

        # Fast execution keeps the loop responsive, but it must not silently
        # disable planning or vision based on model-name heuristics.
        self._fast_execution = bool(config.get("fast_execution", True))

        # Structured Planning: PlannerAgent decomposes build/debug requests.
        self._plan_enabled = bool(config.get("plan_enabled", True))

        # Sub-agents call this to actually hit the live scene. Without it
        # their declared tools would be silently ignored by run().
        def _sub_agent_tool_executor(name: str, args: dict):
            return self._execute_tool(name, args, dry_run=False)

        self._planner = (
            PlannerAgent(
                llm_chat_fn=self.llm.chat,
                all_tool_schemas=TOOL_SCHEMAS,
                tool_executor=_sub_agent_tool_executor,
            )
            if self._plan_enabled
            else None
        )

        # Post-build Validator: checks quality after builds
        self._validator = ValidatorAgent(
            llm_chat_fn=self.llm.chat,
            all_tool_schemas=TOOL_SCHEMAS,
            tool_executor=_sub_agent_tool_executor,
        )

        if config.get("embed_tools_at_startup", True):
            self._warmup_tool_embeddings()

        # Log session metadata for the debug session (session.md).
        # Prefer a pre-resolved value passed via config — calling hou.* here
        # from a background init thread would acquire the HOM lock and
        # freeze the Houdini UI. Fall back to a hou.* call only when we're
        # already on the main thread.
        _hou_app_version = config.get("_hou_app_version") or "N/A"
        if _hou_app_version == "N/A" and HOU_AVAILABLE:
            try:
                if threading.current_thread() is threading.main_thread():
                    _hou_app_version = hou.applicationVersionString()
            except Exception:
                pass
        extra = {
            "Houdini": _hou_app_version,
            "Config Model": config.get("model", ""),
            "Live Model": self.llm.model,
            "Backend": self.llm.backend_name,
            "Vision": (
                f"{self.llm.vision_model} "
                f"(Client Enabled: {self.llm.vision_enabled}, Runtime Enabled: {self._vision_enabled})"
            ),
        }
        self.debug_logger.log_session_config(config, extra=extra)

        if bool(config.get("event_driven_cache_invalidation", True)):
            self._register_scene_event_listener()

        self._load_cross_turn_failures()

    def _debug_model_meta(self) -> dict:
        return {
            "config_model": self.config.get("model", ""),
            "live_model": getattr(self.llm, "model", ""),
            "vision_model": getattr(self.llm, "vision_model", ""),
            "vision_enabled": bool(getattr(self.llm, "vision_enabled", False)),
            "fast_message_mode": bool(getattr(self, "_fast_message_mode", False)),
            "backend": getattr(self.llm, "backend_name", ""),
        }

    def _warmup_tool_embeddings(self) -> None:
        """
        Warm the tool-description embedding cache in the background so the
        first query does not pay the full cold-start selection cost.

        PERF-2: Skip warmup entirely when every tool description is already
        in the cache — the previous version would fire 60+ embed() calls,
        each round-tripping through the cache lookup even though nothing
        would change. Flush the cache once at the end, not per-embed.
        """

        descriptions = [
            ((schema.get("function") or {}).get("description") or "") for schema in TOOL_SCHEMAS
        ]
        descriptions = [d for d in descriptions if d]
        if not descriptions:
            return
        try:
            if all(d in self.llm._embed_cache for d in descriptions):
                return
        except Exception:
            pass

        def _warm():
            try:
                for desc in descriptions:
                    self.llm.embed(desc)
                self.llm.flush_embed_cache()
            except Exception as e:
                print(f"[HoudiniMind] Tool embedding warmup failed (non-fatal): {e}")

        threading.Thread(
            target=_warm,
            daemon=True,
            name="houdinimind-tool-embed-warmup",
        ).start()

    # ── v11: Vision Feedback Loop ─────────────────────────────────────
    def _vision_verify_build(self, goal: str, stream_callback=None) -> str | None:
        """
        After a build turn, capture the viewport and ask the VLM to evaluate
        geometry correctness. Returns a correction message or None if OK.
        """
        if not self._vision_enabled or not self.llm.vision_enabled:
            return None
        if self._turn_capture_pane_analyses >= self.max_capture_pane_per_turn:
            return None

        try:
            # Capture viewport
            from .tools import TOOL_FUNCTIONS

            capture_result = self._hou_call(
                TOOL_FUNCTIONS.get("capture_pane", lambda **kw: None),
                pane_type="viewport",
            )
            if not capture_result or capture_result.get("status") != "ok":
                return None

            image_b64 = None
            data = capture_result.get("data", {})
            if isinstance(data, dict):
                image_b64 = data.get("image_b64") or data.get("base64")
            if not image_b64:
                return None

            self._turn_capture_pane_analyses += 1

            # --- VISION GATING (Point 4) ---
            # Compare current viewport hash with initial hash. If they are identical,
            # we can skip the expensive VLM call because nothing changed visually.
            current_hash = self._compute_image_hash(image_b64)
            if (
                hasattr(self, "_initial_viewport_hash")
                and self._initial_viewport_hash == current_hash
            ):
                self.debug_logger.log_system_note(
                    "Vision Gating: No visual changes detected (hash match). Skipping VLM."
                )
                return None
            # -------------------------------

            if stream_callback:
                stream_callback("\u200b👁️ Vision feedback: evaluating viewport…\n")

            # OPT-1: track vision verify as a timed phase
            _vis_t0 = time.time()
            self.debug_logger.log_phase_start("vision_verify")
            # Ask VLM to evaluate
            analysis = self.llm.chat_with_image(
                system=(
                    "You are a Houdini geometry quality inspector.\n"
                    "Evaluate the viewport screenshot for:\n"
                    "1. Are all geometry pieces visible and correctly positioned?\n"
                    "2. Are there overlapping parts that shouldn't overlap?\n"
                    "3. Is any geometry stuck at the origin (0,0,0) when it shouldn't be?\n"
                    "4. Does the overall shape match what was requested?\n\n"
                    "If everything looks correct, reply: LOOKS_GOOD\n"
                    "If there are issues, describe them specifically and suggest fixes."
                ),
                user=f"The user requested: {goal}\nEvaluate this viewport screenshot.",
                image_b64=image_b64,
                temperature=0.1,
            )
            _vis_elapsed = int((time.time() - _vis_t0) * 1000)
            looks_good = "LOOKS_GOOD" in analysis.upper()
            self.debug_logger.log_llm_call(
                "vision_verify",
                status="ok",
                elapsed_ms=_vis_elapsed,
                meta={"passed": looks_good},
            )
            self.debug_logger.log_phase_end(
                "vision_verify",
                status="ok",
                started_at=_vis_t0,
                meta={"passed": looks_good},
            )

            if looks_good:
                if stream_callback:
                    stream_callback("\u200b✅ Vision check passed\n")
                return None

            if stream_callback:
                stream_callback("\u200b⚠️ Vision detected issues\n")
            return f"[VISION FEEDBACK] {analysis}"

        except Exception as e:
            # Vision failure is non-fatal — log and continue
            self.debug_logger.log_phase_end(
                "vision_verify", status="error", meta={"error": str(e)[:120]}
            )
            if stream_callback:
                stream_callback(f"\u200b⚠️ Vision check skipped: {str(e)[:80]}\n")
            return None

    # ── v11: Structured Planning ──────────────────────────────────────
    def _generate_build_plan(
        self, goal: str, scene_context: str = "", stream_callback=None
    ) -> list[dict] | None:
        """
        Use the PlannerAgent to decompose a complex build into steps.
        Returns a list of step dicts or None if planning is disabled.
        """
        if not self._plan_enabled or not self._planner:
            return None

        try:
            if stream_callback:
                stream_callback("\u200b📋 Generating build plan…\n")
            steps = self._planner.generate_plan(goal, scene_context=scene_context)
            if stream_callback:
                step_summary = "\n".join(
                    f"  {s.get('step', i + 1)}. {s.get('action', '?')}"
                    for i, s in enumerate(steps[:10])
                )
                stream_callback(f"\u200b📋 Plan ({len(steps)} steps):\n{step_summary}\n\n")
            return steps
        except Exception as e:
            if stream_callback:
                stream_callback(f"\u200b⚠️ Planning skipped: {str(e)[:80]}\n")
            return None

    # ── Confirmation gate ─────────────────────────────────────────────
    def set_confirmation_callback(self, cb: Callable):
        self._confirm_callback = cb

    def handle_rejection(self, reason: str = ""):
        msg = "⚠️ USER REJECTED LAST RESPONSE."
        if reason:
            msg += f" Reason: {reason}"
        self.conversation.append({"role": "system", "content": msg})

    def resolve_confirmation(self, approved: bool):
        self._confirm_result = approved
        self._confirm_event.set()

    def _request_confirmation(self, description: str) -> bool:
        if not self._confirm_callback:
            return not self.config.get("require_confirmation_callback", False)
        self._confirm_event.clear()
        self._confirm_result = False
        self._confirm_callback(description)
        self._confirm_event.wait(timeout=60)
        return self._confirm_result

    # ── Context compression ───────────────────────────────────────────
    def _compress_history_if_needed(self):
        if len(self.conversation) <= self.compress_at:
            return
        if getattr(self, "_fast_message_mode", False):
            keep = self.conversation[-max(6, self.compress_at // 2) :]
            while keep and keep[0].get("role") == "tool":
                keep = keep[1:]
            self.conversation = [
                {
                    "role": "system",
                    "content": "[FAST HISTORY COMPACTION]\n"
                    "Older turns were trimmed without an LLM summary to keep this Fast turn responsive. "
                    "Use current live scene/tool reads for exact state when needed.",
                },
                *keep,
            ]
            self.debug_logger.log_phase(
                "fast_history_trim",
                status="ok",
                meta={"kept_messages": len(keep)},
            )
            return
        half = len(self.conversation) // 2
        to_compress = self.conversation[:half]
        keep = self.conversation[half:]

        # CRIT-6: a `tool` message must be preceded by an `assistant` message
        # with tool_calls. After slicing in half we may start `keep` mid-turn,
        # leaving orphan tool messages at the front — OpenAI/Ollama reject that.
        # Walk forward past any leading tool messages until we find a clean
        # boundary (assistant with tool_calls, or user message).
        while keep:
            first = keep[0]
            role = first.get("role")
            if role == "tool":
                keep = keep[1:]
                continue
            if role == "assistant" and first.get("tool_calls"):
                # Keep assistant+tools as a unit; fine as long as tools follow.
                break
            break

        turn_log = []
        for m in to_compress:
            role = m.get("role", "")
            raw_content = m.get("content", "") or ""
            # PERF-5: tool results frequently run 1.5–3k chars; 300 drops the
            # node paths we need for continuity. Bump the floor so summaries
            # keep enough signal to reference existing nodes.
            if (
                "[SCENE DIFF]" in raw_content
                or "Connected:" in raw_content
                or "connections" in raw_content.lower()
                or role == "tool"
            ):
                limit = 1500
            else:
                limit = 800
            content = raw_content[:limit]
            if role in ("user", "assistant", "tool"):
                turn_log.append(f"{role.upper()}: {content}")

        try:
            summary = self.llm.chat_simple(
                system=(
                    "You are summarising a Houdini agent session for compact context.\n"
                    "Output EXACTLY this structure and nothing else:\n\n"
                    "GOAL: <one sentence>\n"
                    "NODES_CREATED: <comma-separated /full/node/paths or NONE>\n"
                    "CONNECTIONS: <comma-separated from_node→to_node:input_index entries or NONE>\n"
                    "PARMS_SET: <comma-separated node/parm=value entries or NONE>\n"
                    "ERRORS_FIXED: <comma-separated 'error at /path: resolution' entries or NONE>\n"
                    "INCOMPLETE: <unfinished steps or NONE>"
                ),
                user="Session turns to summarise:\n" + "\n".join(turn_log),
                temperature=0.05,
                task="quick",
            )
        except Exception:
            summary = "[Earlier session context — condensed]"

        self.conversation = [
            {"role": "system", "content": f"[COMPRESSED HISTORY]\n{summary}"},
            *keep,
        ]

    # ── Intent classification ─────────────────────────────────────────
    # Patterns that indicate the user wants to execute something from a prior
    # advice/research turn (e.g. "yes", "ok", "do it", "apply those", "go ahead").
    _EXEC_FOLLOWUP_RE = re.compile(
        r"^\s*(?:yes|yeah|yep|ok|okay|sure|please|go|do|"
        r"do it|do that|do those|do them|do all|"
        r"apply|apply it|apply them|apply those|apply all|"
        r"execute|execute it|execute them|"
        r"go ahead|proceed|let'?s go|make it so|"
        r"implement|implement it|implement them|implement those|"
        r"fix it|fix them|fix those|"
        r"build it|build them|"
        r"sounds good|looks good|lgtm|perfect|great|"
        r"all of them|all of those|every one|"
        r"the first|the second|the third|option \d|number \d|"
        r"#\d)\s*[.!]?\s*$",
        re.IGNORECASE,
    )

    def _last_assistant_had_suggestions(self) -> bool:
        """Check whether the previous assistant response listed actionable improvements."""
        for msg in reversed(self.conversation):
            role = msg.get("role", "")
            if role == "assistant":
                content = (msg.get("content") or "").lower()
                suggestion_markers = (
                    "improvement",
                    "suggest",
                    "could ",
                    "you can ",
                    "would benefit",
                    "consider ",
                    "recommendation",
                    "potential fix",
                    "steps:",
                    "approach:",
                    "1.",
                    "2.",
                    "3.",  # numbered lists of improvements
                    "here's what",
                    "here are",
                )
                return any(m in content for m in suggestion_markers)
            if role == "user":
                # Don't look past the previous user message
                break
        return False

    def _classify_request_mode(self, user_message: str) -> tuple[str, float]:
        text = (user_message or "").strip()
        if not text:
            return "advice", 0.99

        if build_task_contract(text):
            return "build", 0.94
        if BUILD_INTENT_RE.search(text):
            return "build", 0.92
        if HDA_INTENT_RE.search(text):
            return "build", 0.95
        if DEBUG_INTENT_RE.search(text):
            return "debug", 0.88
        if self.conversation and FOLLOWUP_BUILD_RE.search(text):
            return "build", 0.80

        # Detect short "go ahead" follow-ups after an advice/research turn
        # that listed actionable suggestions. Without this, "yes" or "do it"
        # falls through to advice mode (read-only tools only), making the
        # agent describe changes but never execute them.
        if (
            self.conversation
            and self._EXEC_FOLLOWUP_RE.match(text)
            and self._last_assistant_had_suggestions()
        ):
            return "build", 0.85

        if AutoResearcher.is_research_query(text):
            return "research", 0.85

        # The previous embedding fallback was gated on a config key that
        # never exists and only ever promoted "build" — noise without signal.
        # Return a low-confidence advice classification so callers know the
        # query slipped through the keyword regexes.
        return "advice", 0.50

    # ── 2. PRE-FETCH RAG IN BACKGROUND ──────────────────────────────────
    def _is_rag_followup(self, query: str) -> bool:
        if not query or not self._last_rag_query:
            return False
        text = query.strip()
        if not text:
            return False
        if FOLLOWUP_BUILD_RE.search(text):
            return True
        if self._EXEC_FOLLOWUP_RE.match(text):
            return True
        return False

    def _prefetch_rag(self, query: str, mode: str) -> None:
        if not self.config.get("prefetch_rag", False) or not self.rag:
            return

        # ARCH-11: Use an Event so the consumer can distinguish "finished in
        # time" from "still running" and never pick up a half-written buffer.
        self._rag_done_event = threading.Event()

        if (
            bool(self.config.get("rag_followup_reuse", True))
            and self._last_rag_result is not None
            and self._last_rag_mode == mode
            and self._is_rag_followup(query)
        ):
            self._prefetched_rag = self._last_rag_result
            self._rag_followup_reuses += 1
            try:
                self.debug_logger.log_rag(
                    meta={
                        "query": query[:200],
                        "mode": mode,
                        "elapsed_ms": 0,
                        "result_count": -1,
                        "reused_followup": True,
                        "previous_query": (self._last_rag_query or "")[:200],
                    }
                )
            except Exception:
                pass
            self._rag_done_event.set()
            return

        def _fetch():
            try:
                kwargs = self._get_rag_injection_kwargs(mode, query)
                _t0 = time.time()
                self._prefetched_rag = self.rag.build_context_message(
                    query,
                    request_mode=mode,
                    **kwargs,
                )
                _elapsed = int((time.time() - _t0) * 1000)
                # OPT-6: log RAG fetch with timing and result metadata
                result_count = 0
                if hasattr(self.rag, "last_context_meta"):
                    result_count = int(self.rag.last_context_meta.get("used_count", 0) or 0)
                elif isinstance(self._prefetched_rag, str):
                    result_count = self._prefetched_rag.count("\n\n")
                self._last_rag_query = query
                self._last_rag_mode = mode
                self._last_rag_result = self._prefetched_rag
                self.debug_logger.log_rag(
                    meta={
                        "query": query[:200],
                        "mode": mode,
                        "elapsed_ms": _elapsed,
                        "result_count": result_count,
                        "top_k": self.config.get("rag_top_k", 5),
                        "hybrid": self.config.get("rag_hybrid_search", True),
                    }
                )
            finally:
                self._rag_done_event.set()

        self._rag_thread = threading.Thread(target=_fetch, daemon=True)
        self._rag_thread.start()

    def _select_relevant_recipes(self, query: str) -> list[dict]:
        """
        Select the top 3 most relevant recipes by semantic similarity to the query.
        """
        if not self.memory or not hasattr(self.memory, "get_recipes"):
            return []
        try:
            recipes = self.memory.get_recipes()
            if not recipes:
                return []

            query_emb = self.llm.embed(query)
            if not query_emb:
                return recipes[:3]

            import math

            def cosine_sim(v1, v2):
                dot = sum(a * b for a, b in zip(v1, v2, strict=False))
                mag1 = sum(a * a for a in v1)
                mag2 = sum(b * b for b in v2)
                if mag1 == 0 or mag2 == 0:
                    return 0.0
                return dot / math.sqrt(mag1 * mag2)

            scored = []
            for r in recipes:
                trigger = r.get("trigger", r.get("name", ""))
                if not trigger:
                    continue
                r_emb = self.llm.embed(trigger)
                if not r_emb:
                    continue
                score = cosine_sim(query_emb, r_emb)
                scored.append((score, r))

            scored.sort(key=lambda x: x[0], reverse=True)
            return [r for score, r in scored[:3]]
        except Exception as e:
            try:
                self.debug_logger.log_system_note(f"Recipe embedding search failed: {e}")
            except Exception:
                pass
            return recipes[:3]

    def _build_mode_guidance(self, request_mode: str, query: str = "") -> str | None:
        if getattr(self, "_fast_message_mode", False):
            if request_mode == "build":
                return (
                    "[REQUEST MODE: BUILD - FAST]\n"
                    "Your FIRST tool call must be search_knowledge() using the user's request as the query. "
                    "The knowledge base has topology recipes for almost any object — always check it before "
                    "inventing a node chain. If nothing relevant comes back, proceed with your own judgment.\n"
                    "Execute the user's scene edits directly with the fewest reliable tool calls.\n"
                    "Do not write a plan first. Do not inspect unless a needed node path or parameter is unknown.\n"
                    "Batch related writes in one response when possible. Prefer exact selected/live-context paths.\n"
                    "Complete ALL tasks the user requested — if the message contains multiple edits, apply each one in sequence before stopping.\n"
                    "If a tool returns a schema hint, apply the hint once; do not start broad diagnosis.\n"
                    "Preserve quality: do not skip required nodes for recognizable assets, simulations, or requested connections."
                )
            if request_mode == "debug":
                return (
                    "[REQUEST MODE: DEBUG - FAST]\n"
                    "Apply one targeted fix using the available live context. Inspect only the specific node or parameter needed."
                )
        if request_mode == "build":
            base_guidance = (
                "[REQUEST MODE: BUILD]\n"
                "STEP 0 — KNOWLEDGE CHECK (before any tool calls):\n"
                "Call search_knowledge() with the user's request as the query. The knowledge base has topology "
                "recipes for almost any object or effect — use what it returns rather than guessing a node chain. "
                "If nothing relevant comes back, proceed with your own Houdini knowledge.\n"
                "STEP 1 — PLAN: Write a concise numbered plan, then immediately execute it without stopping.\n"
                "The user wants concrete scene changes now, not a generic explanation.\n"
                "A response counts as complete only if you created/edited real nodes or "
                "reported a specific tool-level blocker.\n"
                "Before calling create_node() for any non-trivial or uncertain node type, call "
                "resolve_build_hints() first to resolve the exact node type string and likely "
                "parameter names in one step.\n"
                "If the scene is empty or no /obj/geo container exists yet, create a geo node in /obj first.\n"
                "Do not assume /obj/geo1 already exists just because example prompts mention it.\n"
                "If a create_node() call fails because the parent path is a SOP node, move up to the containing geo network and retry there.\n"
                "Prioritize SOP/DOP/VEX workflows for modeling and FX tasks.\n"
                "Avoid USD/LOP/PDG or material-only detours unless the user explicitly asks for them.\n"
                "When building SOP geometry, finish with a clear visible final output.\n"
                "If multiple branches contribute to the result, merge them before the final output.\n"
                "End on a display/render-flagged OUT/null/output node and use inspect_display_output() to confirm it cheaply."
            )
            if _query_needs_workflow_grounding(query):
                base_guidance += "\nDo not treat a single visible primitive as a successful build for an object request."
            relevant_recipes = self._select_relevant_recipes(query)
            if relevant_recipes:
                examples = []
                for r in relevant_recipes:
                    trigger = r.get("trigger", r.get("name", ""))
                    steps = [s.get("tool") for s in r.get("steps", []) if isinstance(s, dict)]
                    if steps:
                        examples.append(f"Prompt: {trigger}\nTool Sequence: {', '.join(steps)}")
                if examples:
                    base_guidance += (
                        "\n\n[FEW-SHOT EXAMPLES - Successful Past Sequences]\n"
                        + "\n".join(examples)
                    )
            return base_guidance
        if request_mode == "debug":
            return (
                "[REQUEST MODE: DEBUG]\n"
                "Before any tool calls, write a short numbered diagnose-and-fix plan, then execute it.\n"
                "Diagnose and repair an existing scene issue.\n"
                "Prioritise scene inspection, error tracing, and targeted fixes."
            )
        if request_mode == "advice":
            return (
                "[REQUEST MODE: ADVICE]\n"
                "The user is asking for guidance or explanation.\n"
                "Be specific and grounded. Do not force scene edits unless clearly requested."
            )
        return None

    def _query_mentions_known_vex_symbol(self, query: str) -> bool:
        retriever = getattr(getattr(self, "rag", None), "retriever", None)
        checker = getattr(retriever, "_query_mentions_vex_symbol", None)
        if not callable(checker):
            return False
        try:
            return bool(checker(query))
        except Exception:
            return False

    def _query_needs_vex_contract(self, query: str) -> bool:
        text = str(query or "")
        return bool(VEX_CODE_INTENT_RE.search(text) or self._query_mentions_known_vex_symbol(text))

    def _build_vex_contract_guidance(self, query: str, request_mode: str) -> str | None:
        if not self._query_needs_vex_contract(query):
            return None
        return (
            "[VEX WRANGLE CONTRACT]\n"
            "This turn may generate or edit VEX. Treat all VEX as an Attribute Wrangle snippet, not a standalone CVEX file or Python script.\n"
            'Before writing VEX, retrieve dedicated VEX context: call search_knowledge(query=<user goal or function names>, top_k=5, category_filter="vex"). Use returned signatures and examples as authority.\n'
            "When editing a live node, write code with write_vex_code(node_path, vex_code). That tool validates compile/cook behavior before setting the snippet; do not bypass it with safe_set_parameter unless write_vex_code is unavailable.\n"
            "Preflight the snippet before finalizing: verify real VEX function names/signatures, wrangle attribute class assumptions, @attribute read/write usage, vector/float/int conversions, array syntax, geometry handles, and channel references.\n"
            "Cook-reasoning checklist: use npoints(0) rather than assigning @numpt; use setpointattrib/setprimattrib/setdetailattrib for explicit writes; use geohandle 0 for current geometry; avoid Python/HOM calls; avoid undefined helper functions; guard point/prim lookups that can return -1.\n"
            "If write_vex_code returns validation_failed or node cook errors, read the exact error, fix the code once or twice in-place, and retry before the final response. Do not return code that still has known syntax, type, attribute, or invalid-function errors.\n"
            "Final response should state the node updated and validation status. If validation cannot run because Houdini/vcc is unavailable, explicitly say validation was unavailable and include the static preflight assumptions."
        )

    def _build_dry_run_guidance(self) -> str:
        return (
            "[EXECUTION MODE: DRY RUN]\n"
            "You may inspect the scene normally, but any write-capable tool calls will be "
            "simulated only and MUST NOT be described as already applied.\n"
            "Use read-only tools freely, plan concrete scene changes, and make your final "
            "reply explicitly state that no scene changes were applied."
        )

    def _build_project_rules_guidance(self) -> str | None:
        if not self.memory or not hasattr(self.memory, "get_project_rules_prompt"):
            return None
        try:
            text = self.memory.get_project_rules_prompt(limit=8)
            return text or None
        except Exception:
            return None

    def _lookup_workflow_reference_hits(self, query: str, top_k: int = 3) -> list[dict]:
        if not query or "search_knowledge" not in TOOL_FUNCTIONS:
            return []
        try:
            result = self._sanitize(
                TOOL_FUNCTIONS["search_knowledge"](
                    query=query,
                    top_k=top_k,
                    category_filter="workflow",
                )
            )
        except Exception:
            return []
        if result.get("status") != "ok":
            return []
        return list((result.get("data") or {}).get("results") or [])

    @staticmethod
    def _workflow_excerpt(result: dict, limit: int = 220) -> str:
        content = str((result or {}).get("content", "") or "").strip()
        if not content:
            return ""
        first_line = next((line.strip() for line in content.splitlines() if line.strip()), "")
        excerpt = first_line or content
        excerpt = re.sub(r"\s+", " ", excerpt)
        if len(excerpt) > limit:
            excerpt = excerpt[:limit].rstrip() + "..."
        return excerpt

    def _build_workflow_grounding_message(self, query: str, request_mode: str) -> str | None:
        if request_mode != "build" or not _query_needs_workflow_grounding(query):
            return None
        hits = self._lookup_workflow_reference_hits(query, top_k=3)
        if not hits:
            return None

        goal_terms = _asset_goal_terms(query)
        goal_label = " ".join(goal_terms[:3]) if goal_terms else "requested object"
        lines = [
            "[WORKFLOW GROUNDING]",
            f"The user asked for a recognizable asset/object ({goal_label}), not just any visible primitive.",
            "Relevant local workflow references:",
        ]
        for hit in hits[:3]:
            title = str(hit.get("title", "") or "Workflow Reference")
            excerpt = self._workflow_excerpt(hit)
            line = f"- {title}"
            if excerpt:
                line += f": {excerpt}"
            lines.append(line)
        lines.append(
            "Use these references only as structural guidance. Do not add extra props, demo geometry, simulations, collisions, or embellishments the user did not request."
        )
        lines.append(
            "Do not stop at a single primitive if the request is for a multi-part object such as a table, chair, or bed."
        )
        return "\n".join(lines)

    def _reset_turn_state(self) -> None:
        # Clear any stale cancel from a previous stopped turn so the new turn
        # doesn't immediately exit at its first cancel checkpoint.
        self._cancel_event.clear()
        if getattr(self, "_turn_budget", None) is not None:
            self._turn_budget.start()
        self._current_turn_checkpoint_path = None
        self._last_turn_verification_report = None
        self._last_turn_verification_text = None
        self._last_turn_semantic_text = None
        self._last_turn_semantic_scorecard = None
        self._last_turn_output_paths = []
        self._last_turn_network_review_text = None
        self._active_task_contract = None
        self._turn_network_capture_failed = False
        self._turn_scene_write_epoch = 0
        self._turn_snapshot_cache = {}
        self._turn_capture_cache = {}
        self._turn_tool_schema_cache = {}
        self._turn_checkpoint_attempted = False
        self._last_turn_final_viewport_b64 = None
        self._last_origin_issues: set = set()  # for stuck-node detection across repair rounds
        self._turn_hou_main_thread_blocked = False
        self._plan_verification_count = 0
        self._turn_validation_failed = False
        self._turn_validation_issues: list[str] = []
        self._exhaustion_continuation_attempted = False  # HARDENING: reset per turn
        # If the user attached an image this turn, chat_with_vision already ran one
        # vision call. Pre-charge the budget so _perform_visual_self_check respects
        # the per-turn cap and doesn't fire a redundant second analysis.
        self._turn_user_provided_vision = bool(
            getattr(self, "_this_turn_user_provided_vision", False)
        )
        self._this_turn_user_provided_vision = False
        if self._turn_user_provided_vision:
            self._turn_capture_pane_analyses = 1

    def _vision_capture_allowed(self) -> bool:
        return (
            not bool(getattr(self, "_vision_bypass_active", False))
            and not bool(getattr(self, "verify_skip_vision", False))
            and bool(getattr(self, "_vision_enabled", True))
            and bool(getattr(self.llm, "vision_enabled", True))
        )

    def _get_rag_injection_kwargs(self, request_mode: str, query: str = "") -> dict:
        policy = get_rag_category_policy(request_mode, query)
        include_categories = policy.get("include_categories")
        if self._query_needs_vex_contract(query):
            include_categories = list(include_categories or [])
            include_categories.extend(["vex", "nodes", "general"])
            include_categories = list(dict.fromkeys(include_categories))
        contract_categories = task_contract_rag_categories(build_task_contract(query))
        if contract_categories:
            include_categories = list(include_categories or [])
            include_categories.extend(contract_categories)
            include_categories = list(dict.fromkeys(include_categories))
        kwargs = {
            "include_categories": include_categories,
            "exclude_categories": policy.get("exclude_categories", []),
        }
        kwargs["include_memory"] = request_mode != "build"
        return kwargs

    # ── FIX-1: Dynamic tool selection ─────────────────────────────────
    def _get_tool_schemas_for_request(self, query: str, request_mode: str) -> list:
        """
        Return only the top-N most relevant tool schemas for this specific query.
        This is the core fix for the context-window overflow problem:
        sending all 61 schemas every request costs ~15-25k tokens alone.

        Steps:
          1. Use OllamaClient.select_relevant_tools() (keyword + semantic scoring).
          2. If mode is BUILD, additionally remove knowledge-only tools.

        ARCH-7: the previous per-turn cache was reset at _reset_turn_state and
        keyed on (query, request_mode). Since query is unique per turn, it
        could only hit within the same turn — a case already handled by the
        tool_schemas local that chat() passes through every _run_loop call.
        """
        cache_key = (
            str(query or ""),
            str(request_mode or ""),
            int(self.config.get("max_tools_per_request", 20)),
        )
        cached = self._turn_tool_schema_cache.get(cache_key)
        if cached is not None:
            return list(cached)

        selected = self.llm.select_relevant_tools(
            query=query,
            all_schemas=TOOL_SCHEMAS,
            top_n=self.config.get("max_tools_per_request", 20),
        )

        if request_mode == "build":
            disabled_tools = _build_mode_disabled_tools_for_query(query)
            selected = [
                s for s in selected if s.get("function", {}).get("name", "") not in disabled_tools
            ]
        elif request_mode == "advice":
            selected = [
                s for s in selected if s.get("function", {}).get("name", "") in READ_ONLY_TOOLS
            ]
        self._turn_tool_schema_cache[cache_key] = list(selected)
        return selected

    # ── Scene context refresh ─────────────────────────────────────────
    def _refresh_live_scene_context(self, depth: int = 3) -> str | None:
        if "get_scene_summary" not in TOOL_FUNCTIONS:
            return self._live_scene_json
        try:
            scene = self._hou_call(TOOL_FUNCTIONS["get_scene_summary"], depth=depth)
            scene = self._sanitize(scene)
            if scene.get("status") != "ok":
                return self._live_scene_json
            self._live_scene_json = json.dumps(scene.get("data", {}), indent=2)
            return self._live_scene_json
        except Exception as e:
            self.debug_logger.log_system_note(f"Live scene refresh failed: {e}")
            return self._live_scene_json

    def _mark_scene_dirty(self, tool_name: str | None = None) -> None:
        if tool_name in NON_SCENE_MUTATING_WRITE_TOOLS:
            return
        self._turn_scene_write_epoch += 1
        self._turn_snapshot_cache = {}
        self._turn_capture_cache = {}

    def _capture_scene_snapshot(self) -> dict | None:
        if not HOU_AVAILABLE:
            return None
        cached = self._turn_snapshot_cache.get(self._turn_scene_write_epoch)
        if cached is not None:
            self.debug_logger.log_scene_snapshot(
                "cache_hit",
                meta={
                    "epoch": self._turn_scene_write_epoch,
                    "node_count": len(cached.get("nodes", []) or []),
                },
            )
            return cached
        try:
            from ..bridge.scene_reader import SceneReader

            max_nodes = max(25, int(self.config.get("scene_snapshot_max_nodes", 120)))
            max_parms = max(4, int(self.config.get("scene_snapshot_max_parms", 8)))
            timeout_s = max(1.0, float(self.config.get("scene_snapshot_timeout_s", 4.0)))
            self.debug_logger.log_scene_snapshot(
                "start",
                meta={
                    "epoch": self._turn_scene_write_epoch,
                    "max_nodes": max_nodes,
                    "max_parms_per_node": max_parms,
                    "timeout_s": timeout_s,
                },
            )

            def _build_snapshot(**_ignored):
                return SceneReader(
                    max_nodes=max_nodes,
                    max_parms_per_node=max_parms,
                    include_cook_hotspots=False,
                    include_dop_summary=False,
                    include_usd_summary=False,
                    include_material_assignments=False,
                ).snapshot("/")

            def _read_snapshot():
                return self._hou_call(
                    _build_snapshot,
                    _timeout_s=timeout_s,
                )

            if self._has_houdini_main_thread_dispatch():
                snapshot = _read_snapshot()
            else:
                snapshot, timeout_err = self._execute_with_timeout(_read_snapshot, timeout_s)
                if timeout_err:
                    self.debug_logger.log_scene_snapshot(
                        "timeout",
                        meta={
                            "epoch": self._turn_scene_write_epoch,
                            "timeout_s": timeout_s,
                        },
                    )
                    self.debug_logger.log_system_note(
                        f"Scene snapshot timed out after {timeout_s:.1f}s; continuing without pre-turn scene diff."
                    )
                    return None
            self._turn_snapshot_cache[self._turn_scene_write_epoch] = snapshot
            self.debug_logger.log_scene_snapshot(
                "ok",
                meta={
                    "epoch": self._turn_scene_write_epoch,
                    "node_count": len(snapshot.get("nodes", []) or []),
                    "connection_count": len(snapshot.get("connections", []) or []),
                },
            )
            return snapshot
        except Exception as e:
            self.debug_logger.log_scene_snapshot(
                "error",
                meta={"epoch": self._turn_scene_write_epoch, "error": str(e)},
            )
            self.debug_logger.log_system_note(f"Scene snapshot failed: {e}")
            return None

    @staticmethod
    def _diff_scene_snapshots(before: dict | None, after: dict | None) -> dict | None:
        if not before or not after:
            return None

        before_nodes = {n.get("path"): n for n in before.get("nodes", []) if n.get("path")}
        after_nodes = {n.get("path"): n for n in after.get("nodes", []) if n.get("path")}

        created = sorted(set(after_nodes) - set(before_nodes))
        deleted = sorted(set(before_nodes) - set(after_nodes))

        def _conn_set(snapshot: dict):
            return {
                (
                    c.get("from"),
                    c.get("to"),
                    c.get("to_input", 0),
                )
                for c in snapshot.get("connections", [])
                if c.get("from") and c.get("to")
            }

        added_connections = sorted(_conn_set(after) - _conn_set(before))
        removed_connections = sorted(_conn_set(before) - _conn_set(after))

        parm_changes = []
        for path in sorted(set(before_nodes) & set(after_nodes)):
            before_parms = before_nodes[path].get("parameters", {}) or {}
            after_parms = after_nodes[path].get("parameters", {}) or {}
            changed = []
            for parm_name in sorted(set(before_parms) | set(after_parms)):
                if before_parms.get(parm_name) != after_parms.get(parm_name):
                    changed.append(parm_name)
            if changed:
                parm_changes.append(
                    {
                        "path": path,
                        "count": len(changed),
                        "parms": changed[:5],
                    }
                )
                if len(parm_changes) >= 12:
                    break

        return {
            "created": created[:15],
            "deleted": deleted[:15],
            "added_connections": added_connections[:12],
            "removed_connections": removed_connections[:12],
            "parm_changes": parm_changes,
        }

    @staticmethod
    def _format_scene_diff(diff: dict | None, dry_run: bool = False) -> str:
        if not diff:
            return ""
        header = "[PLANNED SCENE DIFF]" if dry_run else "[SCENE DIFF]"
        lines = [header]
        if diff.get("created"):
            lines.append("Created: " + ", ".join(diff["created"]))
        if diff.get("deleted"):
            lines.append("Deleted: " + ", ".join(diff["deleted"]))
        if diff.get("added_connections"):
            lines.append(
                "Connected: "
                + ", ".join(f"{src} -> {dst}[{idx}]" for src, dst, idx in diff["added_connections"])
            )
        if diff.get("removed_connections"):
            lines.append(
                "Disconnected: "
                + ", ".join(
                    f"{src} -/-> {dst}[{idx}]" for src, dst, idx in diff["removed_connections"]
                )
            )
        if diff.get("parm_changes"):
            parm_bits = []
            for change in diff["parm_changes"]:
                parm_bits.append(
                    f"{change['path']} ({change['count']} parm{'s' if change['count'] != 1 else ''}: "
                    + ", ".join(change["parms"])
                    + ")"
                )
            lines.append("Parameter changes: " + "; ".join(parm_bits))
        return "\n".join(lines)

    @staticmethod
    def _parent_path(path: str | None) -> str | None:
        if not path or "/" not in path:
            return None
        parent = path.rsplit("/", 1)[0]
        return parent or "/"

    def _candidate_finalize_networks(self, before: dict | None, after: dict | None) -> list[str]:
        diff = self._diff_scene_snapshots(before, after)
        if not diff:
            return []

        candidates: list[str] = []

        def _remember(path: str | None) -> None:
            parent = self._parent_path(path)
            if not parent or parent.count("/") < 2:
                return
            if self._is_scratch_path(parent) or self._is_scratch_path(path):
                return
            if parent not in candidates:
                candidates.append(parent)

        for path in diff.get("created", []):
            _remember(path)
        for change in diff.get("parm_changes", []):
            _remember(change.get("path"))
        for src, dst, _ in diff.get("added_connections", []):
            _remember(src)
            _remember(dst)
        canonical = []
        for parent in sorted(candidates, key=lambda value: (value.count("/"), len(value))):
            if any(self._path_under_parent(parent, kept) and parent != kept for kept in canonical):
                continue
            canonical.append(parent)
        return canonical[:8]

    @staticmethod
    def _path_under_parent(path: str | None, parent_path: str | None) -> bool:
        if not path or not parent_path:
            return False
        parent = parent_path.rstrip("/")
        if not parent:
            parent = "/"
        if parent == "/":
            return path.startswith("/")
        return path == parent or path.startswith(parent + "/")

    @staticmethod
    def _bbox_axis_overlap(a_min: float, a_max: float, b_min: float, b_max: float) -> float:
        return max(0.0, min(float(a_max), float(b_max)) - max(float(a_min), float(b_min)))

    @classmethod
    def _detect_table_leg_support_issues(
        cls, bbox_map: dict, tabletop_path: str, leg_paths: list[str]
    ) -> list[dict]:
        tabletop_bbox = bbox_map.get(tabletop_path) or {}
        table_min = tabletop_bbox.get("min") or []
        table_max = tabletop_bbox.get("max") or []
        if len(table_min) < 3 or len(table_max) < 3:
            return []

        tabletop_bottom = float(table_min[1])
        tabletop_thickness = max(0.0, float(table_max[1]) - float(table_min[1]))
        gap_threshold = max(0.05, tabletop_thickness * 0.5)
        issues = []

        for leg_path in leg_paths:
            leg_bbox = bbox_map.get(leg_path) or {}
            leg_min = leg_bbox.get("min") or []
            leg_max = leg_bbox.get("max") or []
            if len(leg_min) < 3 or len(leg_max) < 3:
                continue

            leg_top = float(leg_max[1])
            gap = tabletop_bottom - leg_top
            if gap <= gap_threshold:
                continue

            overlap_x = cls._bbox_axis_overlap(table_min[0], table_max[0], leg_min[0], leg_max[0])
            overlap_z = cls._bbox_axis_overlap(table_min[2], table_max[2], leg_min[2], leg_max[2])
            if overlap_x <= 0.0 or overlap_z <= 0.0:
                continue

            issues.append(
                {
                    "severity": "repair",
                    "path": leg_path,
                    "message": (
                        f"{leg_path} does not support the tabletop. "
                        f"Its top is {gap:.3f} units below the tabletop underside."
                    ),
                }
            )

        return issues

    def _table_support_verification_issues(
        self,
        user_message: str,
        after_snapshot: dict | None,
        parent_paths: list[str],
        stream_callback: Callable | None = None,
    ) -> list[dict]:
        if "table" not in set(_query_terms(user_message)):
            return []
        if not after_snapshot or not parent_paths or "get_bounding_box" not in TOOL_FUNCTIONS:
            return []

        issues = []
        after_nodes = after_snapshot.get("nodes", []) or []
        bbox_map = {}

        for parent_path in parent_paths[:2]:
            sop_nodes = [
                node
                for node in after_nodes
                if self._parent_path(node.get("path")) == parent_path
                and str(node.get("category", "")).lower() == "sop"
            ]
            if not sop_nodes:
                continue

            leg_paths = [
                str(node.get("path"))
                for node in sop_nodes
                if node.get("path") and "leg" in str(node.get("path")).lower().split("/")[-1]
            ]
            if not leg_paths:
                # No leg-named nodes — check structural completeness.
                # A table needs at minimum a tabletop + support (legs/base).
                # Count generator SOPs (box, sphere, tube, etc.) to see if
                # the build has enough distinct geometry nodes.
                generator_types = {
                    "box",
                    "sphere",
                    "tube",
                    "torus",
                    "grid",
                    "circle",
                    "platonic",
                    "metaball",
                }
                generator_sops = [
                    node
                    for node in sop_nodes
                    if str(node.get("type", "")).lower() in generator_types
                ]
                if len(generator_sops) < 3:
                    issues.append(
                        {
                            "severity": "repair",
                            "path": parent_path,
                            "message": (
                                f"Incomplete table structure: only {len(generator_sops)} "
                                f"generator SOP(s) found (need at least 3: 1 tabletop + "
                                f"2+ legs/supports). Create the missing leg nodes as "
                                f"separate box SOPs inside {parent_path}."
                            ),
                        }
                    )
                continue

            surface_candidates = [
                str(node.get("path"))
                for node in sop_nodes
                if node.get("path")
                and "leg" not in str(node.get("path")).lower().split("/")[-1]
                and str(node.get("type", "")).lower() not in {"merge", "null", "output"}
            ]
            if not surface_candidates:
                continue

            for node_path in surface_candidates + leg_paths:
                if node_path in bbox_map:
                    continue
                bbox_result = self._run_observation_tool(
                    "get_bounding_box", {"node_path": node_path}, stream_callback
                )
                if bbox_result.get("status") == "ok":
                    bbox_map[node_path] = bbox_result.get("data") or {}

            def _footprint(path: str) -> float:
                bbox = bbox_map.get(path) or {}
                mins = bbox.get("min") or []
                maxs = bbox.get("max") or []
                if len(mins) < 3 or len(maxs) < 3:
                    return -1.0
                return abs(float(maxs[0]) - float(mins[0])) * abs(float(maxs[2]) - float(mins[2]))

            tabletop_path = max(surface_candidates, key=_footprint, default=None)
            if not tabletop_path or _footprint(tabletop_path) <= 0.0:
                continue

            issues.extend(self._detect_table_leg_support_issues(bbox_map, tabletop_path, leg_paths))

        return issues

    def _extract_display_output_paths(
        self, snapshot: dict | None, parent_paths: list[str] | None = None
    ) -> list[str]:
        if not snapshot:
            return []
        output_nodes = []
        parents = list(parent_paths or [])
        for node in snapshot.get("nodes", []) or []:
            path = node.get("path")
            if not path:
                continue
            if self._is_scratch_path(path):
                continue
            if parents and not any(self._path_under_parent(path, parent) for parent in parents):
                continue
            if node.get("is_displayed") or node.get("is_render_flag"):
                output_nodes.append(node)
        if parents:
            preferred_nodes = []
            for parent in parents:
                descendants = [
                    node
                    for node in output_nodes
                    if self._path_under_parent(node.get("path"), parent)
                    and node.get("path") != parent
                ]
                if descendants:
                    shallowest_depth = min(node.get("path", "").count("/") for node in descendants)
                    preferred_nodes.extend(
                        node
                        for node in descendants
                        if node.get("path", "").count("/") == shallowest_depth
                    )
                else:
                    preferred_nodes.extend(
                        node for node in output_nodes if node.get("path") == parent
                    )
            output_nodes = preferred_nodes
        unique = []
        for node in output_nodes:
            path = node.get("path")
            if path not in unique:
                unique.append(path)
        return unique

    def _record_post_loop_tool_call(self, tool_name: str, args: dict, result: dict) -> None:
        self._last_turn_tool_counts[tool_name] = self._last_turn_tool_counts.get(tool_name, 0) + 1
        self._last_turn_tool_history.append(tool_name)
        self.debug_logger.log_tool_call(tool_name, args, result)
        if self.memory:
            self.memory.log_tool_call(tool_name, args, result)
        if self.on_tool_call:
            self.on_tool_call(tool_name, args, result)

    def _run_observation_tool(
        self, tool_name: str, args: dict, stream_callback: Callable | None = None
    ) -> dict:
        res = self._execute_tool(tool_name, args, stream_callback=stream_callback, dry_run=False)
        self._record_post_loop_tool_call(tool_name, args, res)
        return res

    def _auto_finalize_build_outputs(
        self,
        before_snapshot: dict | None,
        after_snapshot: dict | None,
        stream_callback: Callable | None = None,
    ) -> list[str]:
        if not HOU_AVAILABLE or "finalize_sop_network" not in TOOL_FUNCTIONS:
            return []

        finalized_outputs: list[str] = []
        seen_outputs = set()

        for parent_path in self._candidate_finalize_networks(before_snapshot, after_snapshot):
            # FIX: Skip if the network already has a terminal OUT node
            if after_snapshot:
                existing_outs = [
                    n
                    for n in after_snapshot.get("nodes", [])
                    if self._path_under_parent(n.get("path"), parent_path)
                    and n.get("name") == "OUT"
                ]
                if existing_outs:
                    self.debug_logger.log_system_note(
                        f"Skipping auto-finalize for {parent_path}: OUT node already exists."
                    )
                    continue

            args = {"parent_path": parent_path}
            try:
                res = self._hou_call(TOOL_FUNCTIONS["finalize_sop_network"], **args)
            except Exception as e:
                res = {"status": "error", "message": str(e), "data": None}

            res = self._sanitize(res)
            self.debug_logger.log_tool_call("finalize_sop_network", args, res)
            if self.memory:
                self.memory.log_tool_call("finalize_sop_network", args, res)
            if self.on_tool_call:
                self.on_tool_call("finalize_sop_network", args, res)

            if res.get("status") != "ok":
                continue

            if "UNDO_TRACK:" in res.get("message", ""):
                self.undo_stack.append(res["message"].replace("UNDO_TRACK: ", ""))

            self._mark_scene_dirty("finalize_sop_network")

            output_path = (res.get("data") or {}).get("output_path")
            if not output_path or output_path in seen_outputs:
                continue

            seen_outputs.add(output_path)
            finalized_outputs.append(output_path)
            if stream_callback:
                stream_callback(
                    f"\u200b✅ `finalize_sop_network` → {res.get('message', 'OK')[:120]}\n\n"
                )

        return finalized_outputs

    def _ensure_turn_checkpoint(self, stream_callback: Callable | None = None) -> None:
        if not self.turn_checkpoints_enabled:
            return
        if self._current_turn_checkpoint_path or self._turn_checkpoint_attempted:
            return
        # If backup already failed this session (e.g. unsaved .hip), skip silently.
        # This prevents ❌ create_backup appearing on every turn.
        if getattr(self, "_backup_permanently_failed", False):
            return
        if not HOU_AVAILABLE:
            return
        try:
            self._turn_checkpoint_attempted = True
            create_backup_fn = TOOL_FUNCTIONS.get("create_backup")
            if not create_backup_fn:
                from .tools import create_backup as create_backup_fn
            res = self._hou_call(create_backup_fn)
            res = self._sanitize(res)
        except Exception as e:
            res = {"status": "error", "message": str(e), "data": None}
        self.debug_logger.log_tool_call("create_backup", {}, res)
        if self.memory:
            self.memory.log_tool_call("create_backup", {}, res)
        if self.on_tool_call:
            self.on_tool_call("create_backup", {}, res)
        if res.get("status") == "ok":
            backup_path = (res.get("data") or {}).get("backup_path")
            if backup_path:
                self._current_turn_checkpoint_path = backup_path
                self._last_turn_checkpoint_path = backup_path
                self._emit_runtime_status("checkpoint", path=backup_path)
                if stream_callback:
                    stream_callback("\u200b💾 Turn checkpoint saved before scene edits…\n\n")
        else:
            # Mark backup as permanently failed for this session to avoid
            # repeated failures flooding the debug log with ❌ entries.
            self._backup_permanently_failed = True
            self.debug_logger.log_system_note(
                "Backup failed (source .hip inaccessible). "
                "Suppressing further backup attempts this session. "
                "Save the .hip file to enable checkpoints."
            )

    def _compact_live_scene_payload(self, payload: dict) -> dict:
        if not isinstance(payload, dict):
            return {}

        selected = list(payload.get("selected_nodes", []) or [])[:8]
        raw_nodes = list(payload.get("nodes", []) or [])
        raw_connections = list(payload.get("connections", []) or [])
        focus_parents = set()

        for path in selected:
            parent = self._parent_path(path)
            if parent:
                focus_parents.add(parent)

        for node in raw_nodes:
            path = node.get("path")
            if not path:
                continue
            if node.get("is_displayed") or node.get("is_render_flag"):
                parent = self._parent_path(path)
                if parent:
                    focus_parents.add(parent)
            if len(focus_parents) >= 4:
                break

        def _in_focus(path: str) -> bool:
            if not path:
                return False
            if not focus_parents:
                return True
            return any(self._path_under_parent(path, parent) for parent in focus_parents)

        compact_nodes = []
        for node in raw_nodes:
            path = node.get("path")
            if not path or not _in_focus(path):
                continue
            compact_nodes.append(
                {
                    "path": path,
                    "type": node.get("type"),
                    "category": node.get("category"),
                    "display": bool(node.get("is_displayed")),
                    "render": bool(node.get("is_render_flag")),
                    "errors": list(node.get("errors", []) or [])[:1],
                    "warnings": list(node.get("warnings", []) or [])[:1],
                }
            )
            if len(compact_nodes) >= self.live_scene_max_nodes:
                break

        node_paths = {node.get("path") for node in compact_nodes if node.get("path")}
        compact_connections = []
        for conn in raw_connections:
            src = conn.get("from")
            dst = conn.get("to")
            if not src or not dst:
                continue
            if node_paths and src not in node_paths and dst not in node_paths:
                continue
            compact_connections.append(
                {"from": src, "to": dst, "to_input": conn.get("to_input", 0)}
            )
            if len(compact_connections) >= self.live_scene_max_connections:
                break

        return {
            "hip_file": payload.get("hip_file"),
            "current_frame": payload.get("current_frame"),
            "node_count": len(compact_nodes),
            "connection_count": len(compact_connections),
            "focus_networks": sorted(focus_parents)[:4],
            "selected_nodes": selected,
            "nodes": compact_nodes,
            "connections": compact_connections,
            "error_count": payload.get("error_count", 0),
        }

    def _compress_live_scene_context(self, scene_json: str) -> str:
        text = str(scene_json or "").strip()
        if not text:
            return ""
        try:
            parsed = json.loads(text)
        except Exception:
            parsed = None

        if isinstance(parsed, dict):
            compact = self._compact_live_scene_payload(parsed)
            if compact:
                while True:
                    encoded = json.dumps(compact, indent=2, default=str)
                    if len(encoded) <= self.live_scene_max_chars:
                        return encoded

                    conns = list(compact.get("connections", []) or [])
                    nodes = list(compact.get("nodes", []) or [])
                    shrunk = False

                    if len(conns) > 8:
                        compact["connections"] = conns[: max(8, len(conns) // 2)]
                        compact["connection_count"] = len(compact["connections"])
                        shrunk = True

                    if not shrunk and len(nodes) > 6:
                        compact["nodes"] = nodes[: max(6, len(nodes) // 2)]
                        node_paths = {
                            n.get("path")
                            for n in compact["nodes"]
                            if isinstance(n, dict) and n.get("path")
                        }
                        compact["connections"] = [
                            c
                            for c in (compact.get("connections", []) or [])
                            if c.get("from") in node_paths and c.get("to") in node_paths
                        ]
                        compact["node_count"] = len(compact["nodes"])
                        compact["connection_count"] = len(compact["connections"])
                        shrunk = True

                    if shrunk:
                        continue

                    compact = {
                        "hip_file": compact.get("hip_file"),
                        "current_frame": compact.get("current_frame"),
                        "focus_networks": list(compact.get("focus_networks", []) or [])[:2],
                        "selected_nodes": list(compact.get("selected_nodes", []) or [])[:4],
                        "node_count": int(compact.get("node_count", 0) or 0),
                        "connection_count": int(compact.get("connection_count", 0) or 0),
                        "summary": "Live scene context truncated for token budget.",
                    }

                # Unreachable by design; loop returns.

        if len(text) <= self.live_scene_max_chars:
            return text
        return text[: self.live_scene_max_chars].rstrip() + "\n... [TRUNCATED]"

    def _build_verification_repair_message(
        self, original_request: str, verification_report: dict
    ) -> str:
        issues = verification_report.get("issues", []) or []
        issue_lines = []
        for item in issues[:8]:
            severity = item.get("severity", "issue").upper()
            issue_lines.append(f"- [{severity}] {item.get('message', 'Unknown issue')}")
        if not issue_lines:
            issue_lines.append(
                "- Verification reported a problem, but no specific issue text was available."
            )

        # FIX: Add spatial orientation rules to the repair guidance
        spatial_grounding = (
            "\n\nSPATIAL REPAIR RULES:\n"
            "1. Gravity check: components like tabletops or lids must sit ABOVE their supports (Legs, Base).\n"
            "2. Y-Axis Math: Top_Y = Support_Height + (Top_Thickness / 2). If legs are 0.75m high, the tabletop's center must be > 0.75m.\n"
            "3. Ground plane: Base elements must sit at Y >= 0."
        )

        network_summary = ""
        network_review = verification_report.get("network_review") or {}
        if network_review.get("summary"):
            network_summary = f"\n\nNetwork-view review summary:\n{network_review.get('summary')}"
        contract_note = ""
        contract_guidance = format_task_contract_guidance(
            getattr(self, "_active_task_contract", None)
        )
        if contract_guidance:
            contract_note = f"\n\n{contract_guidance}"
        return (
            "The current Houdini result is close, but verification found concrete issues.\n"
            f"Original request: {original_request}\n\n"
            "Repair ONLY the issues below. Preserve the good work already in the scene.\n"
            + "\n".join(issue_lines)
            + spatial_grounding
            + network_summary
            + contract_note
            + "\n\nRules:\n"
            "1. Do not restart the build from scratch.\n"
            "2. Prefer the smallest targeted fix for each issue.\n"
            "3. Reuse the existing nodes and wiring whenever possible.\n"
            "4. End on a visible OUT/null/output node if this is a SOP build.\n"
            "5. After repairing, summarize exactly what you fixed.\n\n"
            "MANDATORY: You MUST call at least one write tool (set_node_parameter, "
            "connect_nodes, create_node, execute_python, etc.) to apply the fix. "
            "Reading parameters alone does NOT repair anything. If you have already "
            "identified the root cause in a previous inspection pass, skip re-reading "
            "and go straight to fixing with set_node_parameter or the appropriate "
            "write tool. A repair pass that ends without any write tool call is a "
            "failure — the scene will be identical and verification will fail again."
        )

    @staticmethod
    def _format_verification_report(report: dict | None) -> str:
        if not report:
            return ""
        status = (report.get("status") or "unknown").upper()
        lines = [f"[VERIFICATION] {status}"]
        outputs = report.get("outputs") or []
        if outputs:
            lines.append("Outputs checked: " + ", ".join(outputs[:6]))
        for issue in report.get("issues", [])[:8]:
            prefix = {
                "error": "ERROR",
                "warning": "WARN",
                "repair": "FIX",
            }.get(issue.get("severity"), "INFO")
            lines.append(f"- {prefix}: {issue.get('message', '')}")
        summary = report.get("summary")
        if summary and not report.get("issues"):
            lines.append(summary)
        return "\n".join(lines)

    def _network_snapshot_for_prompt(
        self, snapshot: dict | None, parent_paths: list[str] | None = None
    ) -> str:
        if not snapshot:
            return "{}"
        parents = list(parent_paths or [])
        selected = snapshot.get("selected_nodes", []) or []
        nodes = []
        for node in snapshot.get("nodes", []) or []:
            path = node.get("path")
            if not path:
                continue
            if parents and not any(self._path_under_parent(path, parent) for parent in parents):
                continue
            nodes.append(
                {
                    "path": path,
                    "type": node.get("type"),
                    "display": node.get("is_displayed"),
                    "render": node.get("is_render_flag"),
                    "errors": node.get("errors", [])[:2],
                    "warnings": node.get("warnings", [])[:2],
                    "inputs": [
                        inp.get("from_node")
                        for inp in (node.get("inputs") or [])[:4]
                        if inp.get("from_node")
                    ],
                    "outputs": [
                        out.get("to_node")
                        for out in (node.get("outputs") or [])[:4]
                        if out.get("to_node")
                    ],
                }
            )
            if len(nodes) >= 36:
                break
        connections = []
        for conn in snapshot.get("connections", []) or []:
            src = conn.get("from")
            dst = conn.get("to")
            if not src or not dst:
                continue
            if parents and not any(
                self._path_under_parent(src, parent) or self._path_under_parent(dst, parent)
                for parent in parents
            ):
                continue
            connections.append(
                {
                    "from": src,
                    "to": dst,
                    "to_input": conn.get("to_input", 0),
                }
            )
            if len(connections) >= 40:
                break
        payload = {
            "focus_networks": parents,
            "selected_nodes": selected[:8],
            "node_count": len(nodes),
            "nodes": nodes,
            "connections": connections,
            "error_count": snapshot.get("error_count", 0),
        }
        return json.dumps(payload, indent=2, default=str)

    @staticmethod
    def _parse_network_vision_report(raw: str | None) -> dict:
        text = (raw or "").strip()
        if not text:
            return {"verdict": "UNKNOWN", "summary": "", "issues": [], "raw": raw or ""}
        candidate = text
        if "```" in candidate:
            candidate = re.sub(
                r"^```(?:json)?\s*|\s*```$", "", candidate.strip(), flags=re.IGNORECASE
            )
        parsed = None
        for probe in (candidate,):
            try:
                parsed = json.loads(probe)
                break
            except Exception:
                match = re.search(r"\{.*\}", probe, re.DOTALL)
                if match:
                    try:
                        parsed = json.loads(match.group(0))
                        break
                    except Exception:
                        pass
        if isinstance(parsed, dict):
            verdict = str(parsed.get("verdict", "UNKNOWN")).upper()
            issues = []
            for item in parsed.get("issues", []) or []:
                if isinstance(item, dict):
                    issues.append(
                        {
                            "severity": item.get("severity", "warning"),
                            "message": item.get("message", ""),
                        }
                    )
            return {
                "verdict": verdict,
                "summary": parsed.get("summary", "") or "",
                "issues": issues,
                "raw": text,
            }
        issues = []
        lower = text.lower()
        if any(
            word in lower
            for word in (
                "disconnected",
                "orphan",
                "floating",
                "multiple outputs",
                "missing out",
                "missing merge",
                "loose branch",
                "red node",
                "error node",
            )
        ):
            issues.append({"severity": "repair", "message": text.splitlines()[0][:240]})
        verdict = "FAIL" if issues or "fail" in lower else "PASS"
        return {
            "verdict": verdict,
            "summary": text[:400],
            "issues": issues,
            "raw": text,
        }

    @staticmethod
    def _format_network_vision_report(report: dict | None) -> str:
        if not report:
            return ""
        lines = [f"[NETWORK VIEW] {report.get('verdict', 'UNKNOWN')}"]
        summary = report.get("summary", "")
        if summary:
            lines.append(summary)
        for issue in report.get("issues", [])[:6]:
            lines.append(
                f"- {issue.get('severity', 'warning').upper()}: {issue.get('message', '')}"
            )
        return "\n".join(lines)

    def _analyze_network_view(
        self,
        user_message: str,
        scene_snapshot: dict | None,
        parent_paths: list[str] | None = None,
        focus_node: str | None = None,
        stream_callback: Callable | None = None,
    ) -> dict | None:
        if not self.auto_network_view_checks or not HOU_AVAILABLE:
            return None
        if self._turn_network_capture_failed:
            return None

        # Capture network view, focusing on focus_node if provided
        image_b64 = self._capture_debug_screenshot(
            "Network View Audit", pane_type="network", node_path=focus_node
        )
        if not image_b64:
            return None
        scene_context = self._truncate_prompt_context(
            self._network_snapshot_for_prompt(scene_snapshot, parent_paths), limit=4000
        )
        prompt = (
            "You are reviewing a Houdini Network Editor screenshot together with a structured scene-graph summary.\n"
            "Use the screenshot for human-style spatial/layout clues and the JSON summary for exact node paths and wiring.\n"
            "Focus on disconnected nodes, loose branches, missing merges, missing OUT/output nodes, red/orange error nodes, "
            "orphaned nodes, suspicious bypasses, and layout issues that make debugging harder.\n"
            "If the network looks good, say so clearly.\n"
            "Output ONLY valid JSON with this exact schema:\n"
            '{"verdict":"PASS|FAIL","summary":"short summary","issues":[{"severity":"error|warning|repair","message":"exact issue"}]}\n\n'
            f"User request:\n{user_message}\n\n"
            f"Structured network summary:\n{scene_context}"
        )
        try:
            raw = self.llm.chat_vision(prompt=prompt, image_b64=image_b64)
        except Exception as e:
            err_str = str(e).replace('"', '\\"')
            raw = f'{{"verdict":"UNKNOWN","summary":"Network view analysis unavailable: {err_str}","issues":[]}}'
        if isinstance(raw, str) and "vision analysis is disabled" in raw.lower():
            return None
        report = self._parse_network_vision_report(raw)
        self._last_turn_network_review_text = self._format_network_vision_report(report)
        self.debug_logger.log_system_note(self._last_turn_network_review_text or raw)
        if stream_callback:
            stream_callback("\u200b🕸️ Reviewed the network editor to check wiring and layout.\n\n")
        return report

    def _goal_match_verification_issues(
        self,
        user_message: str,
        after_snapshot: dict | None,
        parent_paths: list[str],
    ) -> list[dict]:
        if not after_snapshot or not _query_needs_workflow_grounding(user_message):
            return []

        goal_terms = _asset_goal_terms(user_message)
        if not goal_terms:
            return []

        workflow_hits = self._lookup_workflow_reference_hits(user_message, top_k=2)
        workflow_titles = [
            str(hit.get("title", "")).strip() for hit in workflow_hits[:2] if hit.get("title")
        ]
        goal_label = " ".join(goal_terms[:3])
        after_nodes = after_snapshot.get("nodes", []) or []

        issues = []

        for parent_path in parent_paths[:4]:
            sop_nodes = [
                node
                for node in after_nodes
                if self._parent_path(node.get("path")) == parent_path
                and node.get("category") == "Sop"
            ]
            substantive_nodes = [
                node
                for node in sop_nodes
                if str(node.get("type", "")).lower() not in STRUCTURAL_SOP_TYPES
            ]
            semantic_nodes = [
                node
                for node in substantive_nodes
                if str(node.get("type", "")).lower() not in NON_SEMANTIC_SOP_TYPES
            ]

            # ── Check 1: Single-primitive shortcut (original check) ──
            if len(semantic_nodes) == 1:
                node_type = str(semantic_nodes[0].get("type", "")).lower()
                if node_type in SIMPLE_PRIMITIVE_SOP_TYPES:
                    workflow_note = ""
                    if workflow_titles:
                        workflow_note = (
                            " Relevant workflow references include "
                            + ", ".join(workflow_titles)
                            + "."
                        )
                    issues.append(
                        {
                            "severity": "repair",
                            "path": parent_path,
                            "message": (
                                f"{parent_path} currently resolves to a single {node_type} primitive, "
                                f"which does not satisfy the requested {goal_label}.{workflow_note} "
                                "Build the recognizable object instead of stopping at one primitive."
                            ),
                        }
                    )
                    continue

            # ── Check 2: Display output is a mismatched primitive ─────
            # Even if the network has many nodes (e.g. a partial table
            # build), the display flag may be set on a wrong node (e.g.
            # a sphere from a previous task).  Detect this by checking
            # what the display output actually resolves to.
            display_nodes = [node for node in sop_nodes if node.get("is_displayed")]
            if display_nodes:
                display_type = str(display_nodes[0].get("type", "")).lower()
                display_path = display_nodes[0].get("path", "")
                # Check if the display node is a simple primitive that
                # doesn't match any of the goal terms
                if display_type in SIMPLE_PRIMITIVE_SOP_TYPES:
                    goal_lower = {t.lower() for t in goal_terms}
                    # If none of the goal terms match the displayed type,
                    # this is likely a hallucination from a previous task
                    if display_type not in goal_lower and not any(
                        display_type in term for term in goal_lower
                    ):
                        # Check if there are other, more relevant nodes
                        # that should be displayed instead
                        other_nodes = [n for n in semantic_nodes if n.get("path") != display_path]
                        if other_nodes:
                            other_names = ", ".join(
                                str(n.get("type", "?")) for n in other_nodes[:4]
                            )
                            issues.append(
                                {
                                    "severity": "repair",
                                    "path": parent_path,
                                    "message": (
                                        f"The display flag is on '{display_path}' ({display_type}), "
                                        f"which does not match the requested '{goal_label}'. "
                                        f"The network has other nodes ({other_names}) that "
                                        f"should be connected to the output instead. "
                                        f"Fix the network wiring and set the display flag on "
                                        f"the correct merged output."
                                    ),
                                }
                            )

            # ── Check 3: Orphaned build branches ─────────────────────
            # Detect nodes that were created for the build but are not
            # connected to the display chain. These are "lost" nodes
            # from a failed create_node_chain or manual wiring attempt.
            if len(semantic_nodes) > 2:
                # Build the set of paths in the display chain
                display_chain = set()
                connections = after_snapshot.get("connections", []) or []
                reverse_edges = {}
                for conn in connections:
                    src = conn.get("from")
                    dst = conn.get("to")
                    if src and dst:
                        reverse_edges.setdefault(dst, set()).add(src)

                # Walk upstream from display nodes
                display_paths = [n.get("path") for n in display_nodes if n.get("path")]
                pending = list(display_paths)
                while pending:
                    p = pending.pop()
                    if p in display_chain:
                        continue
                    display_chain.add(p)
                    for upstream in reverse_edges.get(p, ()):
                        pending.append(upstream)

                # Find orphaned semantic nodes
                orphans = [
                    n
                    for n in semantic_nodes
                    if n.get("path") and n.get("path") not in display_chain
                ]
                if orphans and len(orphans) >= 2:
                    orphan_types = ", ".join(
                        f"{n.get('type', '?')} ({n.get('path', '?').split('/')[-1]})"
                        for n in orphans[:5]
                    )
                    issues.append(
                        {
                            "severity": "repair",
                            "path": parent_path,
                            "message": (
                                f"{len(orphans)} node(s) are disconnected from the display output: "
                                f"{orphan_types}. These were likely created for the '{goal_label}' "
                                f"build but are not wired into the final output. Ensure they are "
                                f"wired into the main node chain, or connect them through a merge "
                                f"node if they are separate geometric elements, then set the display "
                                f"flag on the final result."
                            ),
                        }
                    )

        return issues

    @staticmethod
    def _parse_goal_match_vision_report(raw: str | None) -> dict:
        text = (raw or "").strip()
        if not text:
            return {"verdict": "UNKNOWN", "summary": "", "issues": [], "raw": raw or ""}

        candidate = text
        if "```" in candidate:
            candidate = re.sub(
                r"^```(?:json)?\s*|\s*```$",
                "",
                candidate.strip(),
                flags=re.IGNORECASE,
            )

        parsed = None
        for probe in (candidate,):
            try:
                parsed = json.loads(probe)
                break
            except Exception:
                match = re.search(r"\{.*\}", probe, re.DOTALL)
                if match:
                    try:
                        parsed = json.loads(match.group(0))
                        break
                    except Exception:
                        pass

        if isinstance(parsed, dict):
            verdict = str(parsed.get("verdict") or parsed.get("status") or "UNKNOWN").upper()
            issues = []
            for item in parsed.get("issues", []) or []:
                if isinstance(item, str):
                    item = item.strip()
                    if item:
                        issues.append(item)
                elif isinstance(item, dict):
                    message = str(item.get("message", "") or "").strip()
                    if message:
                        issues.append(message)
            return {
                "verdict": verdict,
                "summary": str(parsed.get("summary", "") or "").strip(),
                "issues": issues,
                "raw": text,
            }

        first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
        upper = first_line.upper()
        if upper.startswith("PASS"):
            verdict = "PASS"
        elif upper.startswith("FAIL"):
            verdict = "FAIL"
        else:
            verdict = "UNCERTAIN"

        issues = []
        for line in text.splitlines()[1:]:
            line = line.strip().lstrip("-* ").strip()
            if line:
                issues.append(line)

        return {
            "verdict": verdict,
            "summary": first_line[:240],
            "issues": issues[:6],
            "raw": text,
        }

    @staticmethod
    def _format_goal_match_vision_report(report: dict | None) -> str:
        if not report:
            return ""
        lines = [f"[GOAL MATCH] {report.get('verdict', 'UNKNOWN')}"]
        summary = str(report.get("summary", "") or "").strip()
        if summary:
            lines.append(summary)
        for issue in (report.get("issues") or [])[:6]:
            lines.append(f"- {issue}")
        return "\n".join(lines)

    def _goal_match_scene_context(
        self,
        after_snapshot: dict | None,
        parent_paths: list[str] | None,
        outputs: list[str] | None,
    ) -> str:
        if not after_snapshot:
            return "{}"
        parents = list(parent_paths or [])
        nodes = []
        for node in after_snapshot.get("nodes", []) or []:
            path = node.get("path")
            if not path:
                continue
            if parents and not any(self._path_under_parent(path, parent) for parent in parents):
                continue
            if str(node.get("category", "")).lower() != "sop":
                continue
            nodes.append(
                {
                    "path": path,
                    "name": node.get("name"),
                    "type": node.get("type"),
                    "display": node.get("is_displayed"),
                    "render": node.get("is_render_flag"),
                }
            )
            if len(nodes) >= 18:
                break
        payload = {
            "candidate_parents": parents[:4],
            "outputs": list(outputs or [])[:4],
            "nodes": nodes,
        }
        return json.dumps(payload, indent=2, default=str)

    @staticmethod
    def _display_node_has_inputs(output_path: str, snapshot: dict) -> bool:
        """Return True if the display output node has at least one incoming wire,
        OR if it is a generator SOP (box, sphere, etc.) that legitimately has
        zero inputs.  Generator SOPs produce geometry without any upstream
        connection, so treating them as 'disconnected' is a false failure."""
        if not output_path or not snapshot:
            return False
        connections = snapshot.get("connections", []) or []
        if any(c.get("to") == output_path for c in connections):
            return True
        # Check if the display node is a generator SOP — these have zero
        # inputs by design and should not be flagged as disconnected.
        for node in snapshot.get("nodes", []) or []:
            if node.get("path") == output_path:
                node_type = str(node.get("type", "")).lower()
                if node_type in SIMPLE_PRIMITIVE_SOP_TYPES or node_type in {
                    "file",
                    "alembic",
                    "object_merge",
                    "stash",
                    "heightfield",
                    "testgeometry_rubbertoy",
                    "testgeometry_pighead",
                    "testgeometry_squab",
                    "font",
                }:
                    return True
                break
        return False

    def _goal_match_vision_review(
        self,
        user_message: str,
        after_snapshot: dict | None,
        parent_paths: list[str],
        outputs: list[str],
        stream_callback: Callable | None = None,
    ) -> dict | None:
        if self.verify_skip_vision or not self.llm.vision_enabled:
            return None
        if not after_snapshot or not _query_needs_workflow_grounding(user_message):
            return None

        # Guard: if every display output node has no incoming wires the viewport
        # will be blank — skip expensive vision analysis and report the real cause.
        if outputs and all(not self._display_node_has_inputs(p, after_snapshot) for p in outputs):
            msg = (
                f"Display node(s) {outputs} have no connected inputs — viewport is empty. "
                "Wire geometry into the display node before verifying."
            )
            self.debug_logger.log_system_note(f"[GOAL MATCH] Skipped — {msg}")
            return {"verdict": "FAIL", "summary": msg, "issues": [msg], "_skipped_vision": True}

        image_b64 = self._capture_debug_screenshot(
            "Goal Match Verification",
            pane_type="viewport",
            force_refresh=False,
        )
        if not image_b64:
            return None

        goal_terms = _asset_goal_terms(user_message)
        goal_label = " ".join(goal_terms[:4]) if goal_terms else "requested object"
        scene_context = self._truncate_prompt_context(
            self._goal_match_scene_context(after_snapshot, parent_paths, outputs),
            limit=2500,
        )
        prompt = (
            "You are validating whether a Houdini viewport result actually matches the user's requested object.\n"
            "Be strict. PASS only if a neutral human would recognize the requested object from the screenshot alone.\n"
            "FAIL if the result is still a generic primitive blockout, has the wrong silhouette, is missing defining parts, feels incomplete, or has clearly floating/disconnected major components.\n"
            "If you are uncertain, return FAIL with the missing cues.\n"
            "Return strict JSON with this exact shape:\n"
            '{"verdict":"PASS|FAIL","summary":"one sentence","issues":["specific issue 1","specific issue 2"]}\n\n'
            f"USER REQUEST: {user_message}\n"
            f"REQUESTED OBJECT: {goal_label}\n"
            f"VISIBLE OUTPUTS: {', '.join(outputs[:4]) if outputs else 'NONE'}\n"
            f"SCENE CONTEXT:\n{scene_context}"
        )

        try:
            raw = self.llm.chat_vision(prompt=prompt, image_b64=image_b64)
        except Exception as e:
            self.debug_logger.log_system_note(f"Goal-match vision check unavailable: {e}")
            return None

        report = self._parse_goal_match_vision_report(raw)
        text = self._format_goal_match_vision_report(report)
        if text:
            self.debug_logger.log_system_note(text)
        if stream_callback:
            stream_callback(
                "\u200b🎯 Checked whether the final shape matches the requested object.\n\n"
            )
        return report

    @staticmethod
    def _semantic_view_label(render_info: dict) -> str:
        path = str((render_info or {}).get("filepath", "") or "").lower()
        for token in ("front", "left", "right", "top", "perspective", "viewport"):
            if token in path:
                return token
        return "perspective"

    def _collect_semantic_views(
        self,
        stream_callback: Callable | None = None,
    ) -> list[dict]:
        views = []
        viewport_b64 = self._capture_debug_screenshot(
            "Semantic Viewport",
            pane_type="viewport",
            force_refresh=False,
        )
        if viewport_b64:
            views.append({"view": "viewport", "image_b64": viewport_b64})

        if not self.semantic_multiview_enabled:
            return views

        if not HOU_AVAILABLE or "render_quad_views" not in TOOL_FUNCTIONS:
            return views

        try:
            render_result = self._hou_call(
                TOOL_FUNCTIONS["render_quad_views"],
                orthographic=True,
                render_engine=self.semantic_multiview_engine,
            )
            render_result = self._sanitize(render_result)
        except Exception as e:
            self.debug_logger.log_system_note(f"Semantic multi-view render unavailable: {e}")
            return views

        if render_result.get("status") != "ok":
            return views
        renders = list((render_result.get("data") or {}).get("renders") or [])
        for render in renders[:4]:
            image_b64 = render.get("image_b64")
            if not image_b64:
                continue
            view = self._semantic_view_label(render)
            views.append({"view": view, "image_b64": image_b64})
            try:
                self.debug_logger.log_screenshot(
                    f"Semantic {view.title()}",
                    image_b64=image_b64,
                )
            except Exception:
                pass

        if stream_callback and len(views) > 1:
            stream_callback("\u200b🖼️ Captured additional semantic validation views.\n\n")
        return views

    def _evaluate_semantic_views(
        self,
        user_message: str,
        after_snapshot: dict | None,
        parent_paths: list[str],
        outputs: list[str],
        stream_callback: Callable | None = None,
    ) -> dict | None:
        if (
            not self.semantic_scoring_enabled
            or self.verify_skip_vision
            or not self.llm.vision_enabled
            or not after_snapshot
            or not _query_needs_workflow_grounding(user_message)
        ):
            return None

        # Guard: disconnected display node → blank viewport → skip scoring
        if outputs and all(not self._display_node_has_inputs(p, after_snapshot) for p in outputs):
            self.debug_logger.log_system_note(
                "[SEMANTIC SCORE] Skipped — display node(s) have no inputs (empty viewport)."
            )
            return None

        scene_context = self._truncate_prompt_context(
            self._goal_match_scene_context(after_snapshot, parent_paths, outputs),
            limit=2500,
        )
        views = self._collect_semantic_views(stream_callback=stream_callback)
        if not views:
            return None

        reports = []
        for view in views[:4]:
            prompt = (
                "You are scoring whether a Houdini build matches the requested object from a single view.\n"
                "Return strict JSON only with this shape:\n"
                '{"scores":{"identity":0.0,"completeness":0.0,"proportion":0.0,"support":0.0,"editability":0.0},"overall":0.0,"verdict":"PASS|FAIL","summary":"one sentence","issues":["issue"]}\n'
                "Scoring rules:\n"
                "- identity: does the silhouette read as the requested object\n"
                "- completeness: key required parts are present\n"
                "- proportion: relative dimensions feel plausible\n"
                "- support: contact/support relationships look physically believable\n"
                "- editability: the result looks like a clean proxy/blockout that can be refined\n"
                "Be strict. If the result still reads like generic primitives, score identity below 0.6.\n\n"
                f"USER REQUEST: {user_message}\n"
                f"VIEW: {view['view']}\n"
                f"VISIBLE OUTPUTS: {', '.join(outputs[:4]) if outputs else 'NONE'}\n"
                f"SCENE CONTEXT:\n{scene_context}"
            )
            try:
                raw = self.llm.chat_vision(prompt=prompt, image_b64=view["image_b64"])
            except Exception as e:
                self.debug_logger.log_system_note(f"Semantic score skipped for {view['view']}: {e}")
                continue
            reports.append(
                parse_view_score(
                    raw,
                    view=view["view"],
                    threshold=self.semantic_score_threshold,
                )
            )

        if not reports:
            return None

        scorecard = aggregate_view_scores(
            reports,
            threshold=self.semantic_score_threshold,
        )
        scorecard_dict = scorecard.to_dict()
        rendered = format_scorecard(scorecard)
        self._last_turn_semantic_scorecard = scorecard_dict
        self._last_turn_semantic_text = rendered
        self.debug_logger.log_system_note(rendered)
        self._emit_runtime_status(
            "semantic_score",
            overall=scorecard.overall,
            threshold=scorecard.threshold,
            verdict=scorecard.verdict,
        )
        if stream_callback:
            stream_callback(
                f"\u200b🧭 Semantic score {scorecard.overall:.2f} / {scorecard.threshold:.2f}.\n\n"
            )
        return scorecard_dict

    def _run_verification_suite(
        self,
        user_message: str,
        before_snapshot: dict | None,
        after_snapshot: dict | None,
        request_mode: str,
        stream_callback: Callable | None = None,
        verification_profile: str = "full",
    ) -> dict | None:
        if not HOU_AVAILABLE or not after_snapshot or request_mode not in {"build", "debug"}:
            return None

        profile = str(verification_profile or "full").strip().lower()
        light_profile = profile in {"light", "fast", "quick"}

        parent_paths = self._candidate_finalize_networks(before_snapshot, after_snapshot)
        outputs = self._extract_display_output_paths(after_snapshot, parent_paths)

        # ── Auto-fix: display node disconnected ──────────────────────────
        # If every display output has no incoming wires, the viewport is blank.
        # Before running expensive vision analysis, try to fix this automatically
        # by calling finalize_sop_network, then refresh the snapshot and outputs.
        if outputs and all(not self._display_node_has_inputs(p, after_snapshot) for p in outputs):
            self.debug_logger.log_system_note(
                f"[VERIFICATION] Display node(s) {outputs[:3]} have no connected inputs. "
                "Auto-calling finalize_sop_network to wire geometry before verification."
            )
            for parent in parent_paths[:2]:
                try:
                    args = {"parent_path": parent}
                    fix_res = (
                        self._hou_call(TOOL_FUNCTIONS["finalize_sop_network"], **args)
                        if "finalize_sop_network" in TOOL_FUNCTIONS
                        else None
                    )
                    if fix_res:
                        fix_res = self._sanitize(fix_res)
                        self.debug_logger.log_tool_call("finalize_sop_network", args, fix_res)
                        if fix_res.get("status") == "ok":
                            self._mark_scene_dirty("finalize_sop_network")
                            self.debug_logger.log_system_note(
                                f"Auto-finalize fixed display wiring for {parent}: "
                                f"{fix_res.get('message', '')[:120]}"
                            )
                except Exception as _e:
                    self.debug_logger.log_system_note(
                        f"Auto-finalize attempt failed for {parent}: {_e}"
                    )
            # Refresh snapshot and outputs after auto-fix
            after_snapshot = self._capture_scene_snapshot() or after_snapshot
            outputs = self._extract_display_output_paths(after_snapshot, parent_paths)

            # If still disconnected after auto-fix, inject a direct repair issue
            # and skip the vision pipeline entirely (nothing to show).
            if outputs and all(
                not self._display_node_has_inputs(p, after_snapshot) for p in outputs
            ):
                disconnected_msg = (
                    f"Display node(s) {outputs[:3]} still have no connected inputs. "
                    "The viewport is empty — connect geometry to the display output node."
                )
                self.debug_logger.log_system_note(f"[VERIFICATION] FAIL — {disconnected_msg}")
                report = {
                    "status": "fail",
                    "profile": profile,
                    "summary": disconnected_msg,
                    "issues": [
                        {
                            "severity": "repair",
                            "path": (outputs or parent_paths or [""])[0],
                            "message": disconnected_msg,
                        }
                    ],
                    "outputs": outputs,
                    "candidate_parents": parent_paths,
                    "network_review": None,
                    "semantic_review": None,
                    "semantic_scorecard": None,
                }
                report["text"] = self._format_verification_report(report)
                return report
        # ── End auto-fix ─────────────────────────────────────────────────

        issues = []
        before_paths = {
            node.get("path")
            for node in (before_snapshot or {}).get("nodes", []) or []
            if node.get("path")
        }
        after_nodes_by_path = {
            node.get("path"): node
            for node in (after_snapshot.get("nodes", []) or [])
            if node.get("path")
        }
        display_ancestors = set(outputs)
        reverse_edges = {}
        for conn in after_snapshot.get("connections", []) or []:
            src = conn.get("from")
            dst = conn.get("to")
            if src and dst:
                reverse_edges.setdefault(dst, set()).add(src)
        pending = list(outputs)
        while pending:
            node_path = pending.pop()
            for upstream in reverse_edges.get(node_path, ()):
                if upstream not in display_ancestors:
                    display_ancestors.add(upstream)
                    pending.append(upstream)

        self._emit_progress(
            stream_callback,
            "I'm verifying the final network state before I wrap up.",
        )

        error_scan = self._run_observation_tool(
            "get_all_errors", {"include_warnings": True}, stream_callback
        )
        error_nodes = []
        if error_scan.get("status") == "ok":
            error_nodes = list((error_scan.get("data") or {}).get("nodes", []) or [])
            for node in error_nodes:
                path = node.get("path")
                if parent_paths and not any(
                    self._path_under_parent(path, parent) for parent in parent_paths
                ):
                    continue
                # Skip nodes inside locked HDA definitions — their errors
                # are internal to the asset and can't be fixed by the agent.
                try:
                    import hou as _hou

                    hnode = _hou.node(path) if path else None
                    if hnode is not None and hnode.isInsideLockedHDA():
                        continue
                except Exception:
                    pass
                errs = node.get("errors") or []
                warns = node.get("warnings") or []

                # v10: Skip orphan nodes — if a node has errors but is NOT
                # connected to any display output, it's an abandoned node
                # from a failed earlier attempt. Flagging it confuses the agent.
                is_in_display_chain = path in display_ancestors
                if not is_in_display_chain:
                    node_info = after_nodes_by_path.get(path, {})
                    has_downstream = bool(node_info.get("outputs"))
                    if not has_downstream:
                        if path in before_paths:
                            continue
                        first_issue = (errs or warns or ["unknown issue"])[0]
                        issues.append(
                            {
                                "severity": "error" if errs else "warning",
                                "path": path,
                                "message": (
                                    f"{path} is a newly created orphan branch with "
                                    f"{'errors' if errs else 'warnings'}: {first_issue}"
                                ),
                            }
                        )
                        continue

                if errs:
                    issues.append(
                        {
                            "severity": "error",
                            "path": path,
                            "message": f"{path} has errors: {errs[0]}",
                        }
                    )
                elif warns:
                    issues.append(
                        {
                            "severity": "warning",
                            "path": path,
                            "message": f"{path} has warnings: {warns[0]}",
                        }
                    )

        existing_issue_paths = {issue.get("path") for issue in issues}
        for node in error_nodes:
            path = node.get("path")
            if (
                not path
                or path in existing_issue_paths
                or path in before_paths
                or path in display_ancestors
            ):
                continue
            if parent_paths and not any(
                self._path_under_parent(path, parent) for parent in parent_paths
            ):
                continue
            node_info = after_nodes_by_path.get(path, {})
            if node_info.get("outputs"):
                continue
            errs = node.get("errors") or []
            warns = node.get("warnings") or []
            if not errs and not warns:
                continue
            first_issue = (errs or warns)[0]
            issues.append(
                {
                    "severity": "error" if errs else "warning",
                    "path": path,
                    "message": (
                        f"{path} is a newly created orphan branch with "
                        f"{'errors' if errs else 'warnings'}: {first_issue}"
                    ),
                }
            )

        if request_mode == "build" and not outputs:
            target = parent_paths[0] if parent_paths else "/obj"
            issues.append(
                {
                    "severity": "repair",
                    "path": target,
                    "message": f"No visible final output was found in {target}. Finalize the build with an OUT node.",
                }
            )

        for output_path in outputs[:4]:
            geo_result = self._run_observation_tool(
                "get_geometry_attributes", {"node_path": output_path}, stream_callback
            )
            if geo_result.get("status") != "ok":
                issues.append(
                    {
                        "severity": "error",
                        "path": output_path,
                        "message": f"{output_path} could not be inspected for geometry: {geo_result.get('message', '')}",
                    }
                )
            else:
                geo_data = geo_result.get("data") or {}
                # Robust point_count extraction: try top-level first, then
                # fall back to the nested point[0].count used by the older
                # get_geometry_attributes schema.
                point_count = int(geo_data.get("point_count", 0) or 0)
                if point_count <= 0:
                    point_list = geo_data.get("point") or []
                    if point_list and isinstance(point_list, list):
                        point_count = int(point_list[0].get("count", 0) or 0)
                if point_count <= 0:
                    issues.append(
                        {
                            "severity": "repair",
                            "path": output_path,
                            "message": f"{output_path} is visible but appears to have no geometry output.",
                        }
                    )
                elif request_mode == "build" and "get_bounding_box" in TOOL_FUNCTIONS:
                    # P2: Bounding box sanity — catch degenerate geometry
                    # (e.g. tube with height=0 produces points but zero volume)
                    bbox_result = self._run_observation_tool(
                        "get_bounding_box", {"node_path": output_path}, stream_callback
                    )
                    if bbox_result.get("status") == "ok":
                        bbox_data = bbox_result.get("data") or {}
                        size = bbox_data.get("size") or bbox_data.get("dimensions") or []
                        if isinstance(size, (list, tuple)) and len(size) >= 3:
                            volume = abs(size[0]) * abs(size[1]) * abs(size[2])
                            if volume < 1e-9:
                                issues.append(
                                    {
                                        "severity": "repair",
                                        "path": output_path,
                                        "message": (
                                            f"{output_path} has {point_count} points but near-zero "
                                            f"bounding volume ({volume:.2e}). Some geometry may be "
                                            f"degenerate (e.g. zero-height tube or zero-area faces)."
                                        ),
                                    }
                                )

            input_result = self._run_observation_tool(
                "get_node_inputs", {"node_path": output_path}, stream_callback
            )
            if input_result.get("status") == "ok":
                bad_inputs = [
                    inp
                    for inp in (input_result.get("data") or {}).get("inputs", [])
                    if inp.get("errors")
                ]
                for inp in bad_inputs[:3]:
                    label = inp.get("label") or f"Input {inp.get('index', 0)}"
                    issues.append(
                        {
                            "severity": "error",
                            "path": output_path,
                            "message": (
                                f"{output_path} has an input issue on {label}: "
                                f"{'; '.join(inp.get('errors') or [])}"
                            ),
                        }
                    )

        if request_mode == "build" and parent_paths:
            after_nodes = after_snapshot.get("nodes", []) or []
            for parent_path in parent_paths[:4]:
                sop_nodes = [
                    node
                    for node in after_nodes
                    if self._parent_path(node.get("path")) == parent_path
                    and node.get("category") == "Sop"
                ]
                terminals = []
                for node in sop_nodes:
                    outputs_in_parent = [
                        out
                        for out in (node.get("outputs") or [])
                        if self._path_under_parent(out.get("to_node"), parent_path)
                    ]
                    if not outputs_in_parent:
                        terminals.append(node)
                visible_outputs = [
                    path for path in outputs if self._path_under_parent(path, parent_path)
                ]
                if len(terminals) > 1 and not visible_outputs:
                    issues.append(
                        {
                            "severity": "repair",
                            "path": parent_path,
                            "message": f"{parent_path} still has multiple loose terminal SOP branches. Merge them before finishing.",
                        }
                    )

        issues.extend(
            self._goal_match_verification_issues(
                user_message,
                after_snapshot,
                parent_paths,
            )
        )
        issues.extend(
            self._table_support_verification_issues(
                user_message,
                after_snapshot,
                parent_paths,
                stream_callback=stream_callback,
            )
        )
        contract = getattr(self, "_active_task_contract", None) or build_task_contract(user_message)
        issues.extend(
            verify_task_contract(
                contract,
                before_snapshot,
                after_snapshot,
                parent_paths,
                outputs,
            )
        )

        # ── Spatial layout audit for furniture / multi-part builds ─────────────
        # If the query is for a recognizable object (chair, table, bed, etc.) and
        # audit_spatial_layout is available, run it and inject any at-origin nodes
        # as repair issues. This catches legs stuck at Y=0 before the VLM check.
        if (
            request_mode == "build"
            and parent_paths
            and _query_needs_workflow_grounding(user_message)
            and "audit_spatial_layout" in TOOL_FUNCTIONS
            and not light_profile
        ):
            for _parent in parent_paths[:2]:
                try:
                    _audit_res = self._hou_call(
                        TOOL_FUNCTIONS["audit_spatial_layout"],
                        parent_path=_parent,
                    )
                    _audit_res = self._sanitize(_audit_res)
                    self.debug_logger.log_tool_call(
                        "audit_spatial_layout", {"parent_path": _parent}, _audit_res
                    )
                    if _audit_res.get("status") == "ok":
                        _audit_data = _audit_res.get("data") or {}
                        _at_origin = _audit_data.get("at_origin_issues") or []

                        # ── Stuck detection: same nodes at origin across repairs ──
                        _prev_origin = getattr(self, "_last_origin_issues", set())
                        _curr_origin = set(_at_origin)
                        _still_stuck = _curr_origin & _prev_origin
                        self._last_origin_issues = _curr_origin

                        for _node_path in _at_origin[:5]:
                            if _node_path in _still_stuck:
                                # Same node was at origin last repair round too —
                                # the tweaking approach isn't working. Tell the agent
                                # to abandon the current approach entirely.
                                issues.append(
                                    {
                                        "severity": "repair",
                                        "path": _node_path,
                                        "message": (
                                            f"STUCK: '{_node_path}' has been at origin for "
                                            f"multiple repair rounds. Your current fix approach "
                                            f"is NOT working. You MUST abandon this approach and "
                                            f"rebuild from scratch using a different strategy. "
                                            f"If this is a grid or copytopoints node, DELETE it "
                                            f"and replace with individual positioned box nodes."
                                        ),
                                    }
                                )
                            else:
                                issues.append(
                                    {
                                        "severity": "repair",
                                        "path": _node_path,
                                        "message": (
                                            f"{_node_path} is at the origin (Y=0) — it was not "
                                            "correctly stacked/positioned. Use get_stacking_offset "
                                            "or set_node_parameter to move it into place."
                                        ),
                                    }
                                )

                        # ── Anti-pattern detection ───────────────────────────────
                        for _ap in _audit_data.get("anti_patterns") or []:
                            issues.append(
                                {
                                    "severity": "repair",
                                    "path": _parent,
                                    "message": _ap.get(
                                        "fix", "Anti-pattern detected — rebuild required."
                                    ),
                                }
                            )

                        _overlap = _audit_data.get("overlap_issues") or []
                        for _msg in _overlap[:3]:
                            issues.append(
                                {
                                    "severity": "warning",
                                    "path": _parent,
                                    "message": str(_msg),
                                }
                            )
                except Exception as _ae:
                    self.debug_logger.log_system_note(
                        f"audit_spatial_layout skipped for {_parent}: {_ae}"
                    )

        semantic_review = None
        semantic_scorecard = None
        if request_mode == "build" and not light_profile:
            semantic_review = self._goal_match_vision_review(
                user_message,
                after_snapshot,
                parent_paths,
                outputs,
                stream_callback=stream_callback,
            )
            if semantic_review and semantic_review.get("verdict") == "FAIL":
                detail = semantic_review.get("summary") or next(
                    iter(semantic_review.get("issues") or []),
                    "",
                )
                issues.append(
                    {
                        "severity": "repair",
                        "path": (outputs or parent_paths or [""])[0],
                        "message": (
                            "The viewport result does not yet clearly read as the requested object. "
                            f"{detail}"
                        ).strip(),
                    }
                )
            should_run_semantic_score = (
                semantic_review is None
                or semantic_review.get("verdict") != "PASS"
                or self.semantic_run_on_goal_pass
            )
            if should_run_semantic_score:
                semantic_scorecard = self._evaluate_semantic_views(
                    user_message,
                    after_snapshot,
                    parent_paths,
                    outputs,
                    stream_callback=stream_callback,
                )
            else:
                self.debug_logger.log_system_note(
                    "Skipping semantic scorecard: goal-match already PASS."
                )
            if semantic_scorecard and semantic_scorecard.get("verdict") == "FAIL":
                issues.append(
                    {
                        "severity": "repair",
                        "path": (outputs or parent_paths or [""])[0],
                        "message": (
                            "Multi-view semantic scoring is below the required threshold. "
                            f"Overall {float(semantic_scorecard.get('overall', 0.0) or 0.0):.2f} "
                            f"vs threshold {float(semantic_scorecard.get('threshold', self.semantic_score_threshold) or self.semantic_score_threshold):.2f}."
                        ),
                    }
                )

            # Semantic override: if the scorecard PASSES with a high score (≥ 0.85),
            # goal-match failures that are purely about visual detail/quality (not structural
            # absence) should be downgraded to warnings rather than blocking repair loops.
            _STRUCTURAL_ABSENCE_KEYWORDS = {
                "completely missing",
                "no geometry",
                "nothing visible",
                "empty",
                "not visible",
                "absent",
                "zero geometry",
                "does not exist",
            }
            semantic_overall = float((semantic_scorecard or {}).get("overall", 0.0) or 0.0)
            if (
                semantic_overall >= 0.85
                and semantic_scorecard
                and semantic_scorecard.get("verdict") == "PASS"
            ):
                downgraded = []
                for iss in issues:
                    msg_lower = iss.get("message", "").lower()
                    is_structural = any(kw in msg_lower for kw in _STRUCTURAL_ABSENCE_KEYWORDS)
                    if (
                        iss.get("severity") == "repair"
                        and "viewport result does not yet clearly read" in msg_lower
                        and not is_structural
                    ):
                        # Detail/quality complaint overridden by strong semantic pass
                        iss = dict(iss)
                        iss["severity"] = "warning"
                        iss["message"] = (
                            f"[Downgraded by semantic pass {semantic_overall:.2f}] "
                            + iss["message"]
                        )
                        self.debug_logger.log_system_note(
                            f"Goal-match repair downgraded to warning — semantic score {semantic_overall:.2f} overrides detail complaint."
                        )
                    # If semantic confidence is strong, origin/stuck layout nudges should
                    # not block completion for otherwise valid recognisable assets.
                    if iss.get("severity") == "repair" and (
                        "at the origin (y=0)" in msg_lower
                        or msg_lower.startswith("stuck:")
                        or " has been at origin " in msg_lower
                    ):
                        iss = dict(iss)
                        iss["severity"] = "warning"
                        iss["message"] = (
                            f"[Downgraded by semantic pass {semantic_overall:.2f}] "
                            + iss["message"]
                        )
                        self.debug_logger.log_system_note(
                            f"Spatial-origin repair downgraded to warning — semantic score {semantic_overall:.2f} indicates acceptable object identity."
                        )
                    downgraded.append(iss)
                issues = downgraded

        network_review = None
        # Only trigger network review if issues are found (errors/warnings)
        # or if vision is specifically requested.
        requires_network_audit = any(i.get("severity") in ("error", "repair") for i in issues)
        if not light_profile and requires_network_audit and self.llm.vision_enabled:
            # Focus on the first problematic node if any
            critical_issues = [
                i for i in issues if i.get("severity") in ("error", "repair") and i.get("path")
            ]
            focus_node = critical_issues[0]["path"] if critical_issues else None

            network_review = self._analyze_network_view(
                user_message,
                after_snapshot,
                parent_paths=parent_paths,
                focus_node=focus_node,
                stream_callback=stream_callback,
            )
        elif not requires_network_audit:
            self.debug_logger.log_system_note("Skipping network audit: no critical issues found.")
        if network_review:
            for issue in network_review.get("issues", [])[:6]:
                issues.append(
                    {
                        "severity": issue.get("severity", "warning"),
                        "path": parent_paths[0] if parent_paths else "",
                        "message": issue.get("message", ""),
                    }
                )

        blocking_issues = [
            i for i in issues if str(i.get("severity", "")).lower() in {"error", "repair"}
        ]
        status = "pass" if not blocking_issues else "fail"
        summary = "Verification passed. The current result looks structurally sound."
        if blocking_issues:
            summary = f"Verification found {len(issues)} issue(s) that should be fixed before the turn is considered complete."
        elif issues:
            summary = (
                "Verification passed with non-blocking warnings. "
                "The current result is acceptable, with optional cleanup suggestions."
            )
        report = {
            "status": status,
            "profile": profile,
            "summary": summary,
            "issues": issues,
            "outputs": outputs,
            "candidate_parents": parent_paths,
            "network_review": network_review,
            "semantic_review": semantic_review,
            "semantic_scorecard": semantic_scorecard,
        }
        report["text"] = self._format_verification_report(report)
        semantic_text = self._format_goal_match_vision_report(semantic_review)
        if semantic_text:
            report["text"] = (report["text"].rstrip() + "\n\n" + semantic_text).strip()
        scorecard_text = self._last_turn_semantic_text or ""
        if scorecard_text:
            report["text"] = (report["text"].rstrip() + "\n\n" + scorecard_text).strip()
        network_text = self._format_network_vision_report(network_review)
        if network_text:
            report["text"] = (report["text"].rstrip() + "\n\n" + network_text).strip()
        self._last_turn_verification_report = report
        self._last_turn_verification_text = report["text"]
        self._last_turn_output_paths = outputs
        self.debug_logger.log_system_note(report["text"])
        self._emit_runtime_status(
            "verification",
            status=status,
            outputs=list(outputs[:4]),
        )
        if stream_callback:
            prefix = "✅" if status == "pass" else "⚠️"
            stream_callback(f"\u200b{prefix} Verification {status}.\n\n")
        return report

    @staticmethod
    def _truncate_prompt_context(text: str, limit: int = 4000) -> str:
        """Cap text length to avoid context overflow / HTTP 400."""
        if not text:
            return ""
        if len(text) <= limit:
            return text
        return text[:limit].rstrip() + "\n... [TRUNCATED]"

    @staticmethod
    def _short_name(value) -> str:
        if value is None:
            return "it"
        text = str(value).strip()
        if not text:
            return "it"
        if "/" in text:
            text = text.rstrip("/").rsplit("/", 1)[-1]
        return text or "it"

    def _emit_runtime_status(self, kind: str, **payload) -> None:
        callback = getattr(self, "_runtime_status_callback", None)
        if not callback:
            return
        event = {"kind": kind}
        event.update(payload)
        try:
            callback(event)
        except Exception:
            pass

    def _emit_progress(self, stream_callback: Callable, message: str | None):
        text = (message or "").strip()
        if stream_callback and text:
            stream_callback(f"{self.PROGRESS_SENTINEL}{text}")
        if text:
            self._emit_runtime_status("substate", message=text)

    def _emit_llm_trace(
        self,
        stream_callback: Callable,
        round_num: int,
        task: str | None,
        text: str,
        tool_calls: list,
    ) -> None:
        tool_names = []
        for tc in tool_calls or []:
            try:
                name = (tc.get("function") or {}).get("name") or ""
            except Exception:
                name = ""
            if name:
                tool_names.append(str(name))
        payload = {
            "round": int(round_num),
            "task": str(task or ""),
            "tool_call_count": len(tool_calls or []),
            "tool_names": tool_names[:8],
            "content": str(text or "").strip(),
        }
        if not payload["content"] and not payload["tool_names"]:
            return
        self._emit_runtime_status("llm_trace", **payload)
        show_trace = bool((self.config.get("ui") or {}).get("show_llm_trace_history", False))
        if stream_callback and show_trace:
            try:
                stream_callback(self.LLM_TRACE_SENTINEL + json.dumps(payload))
            except Exception:
                pass

    @staticmethod
    def _is_houdini_main_thread_timeout(message: str) -> bool:
        text = str(message or "").lower()
        return "main-thread call timed out" in text and "houdini" in text

    @staticmethod
    def _describe_llm_round(request_mode: str, round_num: int) -> str:
        if round_num == 0:
            if request_mode == "build":
                return "Planning the build before touching the scene."
            if request_mode == "debug":
                return "Reviewing the scene state and narrowing down the issue."
            if request_mode == "research":
                return "Breaking the problem down and choosing the first move."
            return "Thinking through the request and choosing the next action."
        return "Reviewing the latest scene state and deciding the next step."

    @classmethod
    def _describe_tool_action(cls, tool_name: str, args: dict) -> str:
        if tool_name == "create_node":
            node_name = args.get("name") or args.get("node_type") or "node"
            node_type = args.get("node_type")
            if node_type and node_type != node_name:
                return f"I'm creating the {node_name} node using {node_type}."
            return f"I'm creating the {node_name} node."
        if tool_name == "create_node_chain":
            chain = args.get("chain", []) or []
            names = [
                step.get("name") or step.get("type") for step in chain[:4] if isinstance(step, dict)
            ]
            names = [str(name) for name in names if name]
            if names:
                return f"I'm building the node chain: {', '.join(names)}."
            return "I'm building the node chain."
        if tool_name in {"safe_set_parameter", "set_parameter"}:
            return (
                f"I'm adjusting {args.get('parm_name', 'a parameter')} "
                f"on {cls._short_name(args.get('node_path'))}."
            )
        if tool_name == "batch_set_parameters":
            count = len(args.get("nodes_and_parms", []) or [])
            return f"I'm updating {count} parameter{'s' if count != 1 else ''} in one pass."
        if tool_name == "connect_nodes":
            return (
                f"I'm wiring {cls._short_name(args.get('from_path'))} "
                f"into {cls._short_name(args.get('to_path'))}."
            )
        if tool_name == "disconnect_node":
            return (
                f"I'm removing one of the connections on {cls._short_name(args.get('node_path'))}."
            )
        if tool_name == "set_display_flag":
            return f"I'm making {cls._short_name(args.get('node_path'))} the visible output."
        if tool_name == "finalize_sop_network":
            return "I'm merging the final pieces together and setting a clear output node."
        if tool_name == "get_scene_summary":
            return "I'm checking the current Houdini scene so I can build in the right place."
        if tool_name == "get_all_errors":
            return "I'm checking for any scene or node errors before I continue."
        if tool_name == "get_node_parameters":
            return f"I'm inspecting the parameters on {cls._short_name(args.get('node_path'))}."
        if tool_name == "get_node_inputs":
            return f"I'm checking how {cls._short_name(args.get('node_path'))} is wired."
        if tool_name == "get_geometry_attributes":
            return f"I'm inspecting the geometry attributes on {cls._short_name(args.get('node_path'))}."
        if tool_name == "inspect_display_output":
            return (
                f"I'm checking the visible output under {cls._short_name(args.get('parent_path'))}."
            )
        if tool_name == "resolve_build_hints":
            return "I'm checking the most likely Houdini node and parameter names before the next step."
        if tool_name == "capture_pane":
            return "I'm checking the viewport to make sure the result looks right."
        if tool_name in {"search_knowledge", "search_docs"}:
            return "I'm pulling in a quick reference before the next step."
        if tool_name == "execute_python":
            return "I'm running a small Houdini Python step."
        return f"I'm working on the next Houdini step with {tool_name.replace('_', ' ')}."

    @classmethod
    def _describe_tool_failure(cls, tool_name: str, args: dict, error_message: str) -> str:
        lower = (error_message or "").lower()
        if "node type" in lower:
            return "That node type wasn't valid, so I'm checking the correct Houdini node and retrying."
        if "parm" in lower or "parameter" in lower:
            return "That parameter didn't match, so I'm checking the right parameter name and continuing."
        if tool_name == "connect_nodes":
            return "That connection didn't work, so I'm correcting the wiring and trying again."
        return "That step didn't work as expected, so I'm correcting it and continuing."

    @staticmethod
    def _summarize_mutation(tool_name: str, args: dict, result: dict) -> str | None:
        data = result.get("data") or {}
        if tool_name == "create_node":
            return f"Create node {data.get('path', args.get('name', args.get('node_type', '?')))}"
        if tool_name == "delete_node":
            return f"Delete node {args.get('node_path', '?')}"
        if tool_name == "connect_nodes":
            return f"Connect {args.get('from_path', '?')} -> {args.get('to_path', '?')}[{args.get('to_in', 0)}]"
        if tool_name == "disconnect_node":
            return f"Disconnect {args.get('node_path', '?')}[{args.get('input_index', 0)}]"
        if tool_name in {"safe_set_parameter", "set_parameter"}:
            return f"Set {args.get('node_path', '?')}/{args.get('parm_name', '?')}"
        if tool_name == "set_expression":
            return f"Set expression on {args.get('node_path', '?')}/{args.get('parm_name', '?')}"
        if tool_name == "batch_set_parameters":
            return f"Batch set {len(args.get('nodes_and_parms', []))} parameter(s)"
        if tool_name == "rename_node":
            return f"Rename {args.get('node_path', '?')} -> {args.get('new_name', '?')}"
        if tool_name == "duplicate_node":
            return f"Duplicate {args.get('node_path', '?')}"
        if tool_name == "create_node_chain":
            created = [c.get("path") for c in data.get("created", []) if c.get("path")]
            return "Create chain: " + ", ".join(created[:6]) if created else "Create node chain"
        if tool_name.startswith("setup_"):
            paths = [str(v) for v in data.values() if isinstance(v, str) and v.startswith("/")]
            return (
                f"{tool_name}: " + ", ".join(paths[:6])
                if paths
                else tool_name.replace("_", " ").title()
            )
        if tool_name == "create_material":
            return f"Create material {data.get('material_path', args.get('mat_name', '?'))}"
        if tool_name == "assign_material":
            return (
                f"Assign material {args.get('material_path', '?')} to {args.get('node_path', '?')}"
            )
        if tool_name == "create_camera":
            return f"Create camera {data.get('path', args.get('name', 'agent_cam'))}"
        if tool_name == "create_subnet":
            return f"Create subnet {data.get('subnet_path', args.get('name', '?'))}"
        if tool_name == "create_bed_controls":
            return f"Create controls {data.get('path', args.get('name', 'BED_CONTROLS'))}"
        if tool_name == "set_display_flag":
            return f"Set display output on {args.get('node_path', '?')}"
        if tool_name == "finalize_sop_network":
            return f"Finalize SOP output {data.get('output_path', args.get('parent_path', '?'))}"
        if tool_name == "execute_python":
            return "Execute arbitrary Python"
        message = result.get("message", "")
        return message[:120] if message else None

    @staticmethod
    def _format_mutation_summary(mutations: list[str], dry_run: bool = False) -> str:
        if not mutations:
            return ""
        header = "[PLANNED SCENE DIFF]" if dry_run else "[SCENE DIFF]"
        unique = []
        for item in mutations:
            if item not in unique:
                unique.append(item)
        lines = [header]
        lines.extend(f"- {item}" for item in unique[:12])
        if len(unique) > 12:
            lines.append(f"- ...and {len(unique) - 12} more change(s)")
        return "\n".join(lines)

    @staticmethod
    def _dry_run_path(parent_path: str, name: str) -> str:
        parent = (parent_path or "/").rstrip("/")
        if not parent:
            parent = "/"
        if parent == "/":
            return f"/{name}"
        return f"{parent}/{name}"

    @classmethod
    def _simulate_dry_run_result(cls, tool_name: str, args: dict, safety_level: str) -> dict:
        data = {"args": args, "dry_run": True}

        if tool_name == "create_node":
            name = args.get("name") or f"{args.get('node_type', 'node')}1"
            data.update(
                {
                    "path": cls._dry_run_path(args.get("parent_path", "/"), name),
                    "type": args.get("node_type"),
                    "original_request": args.get("node_type"),
                }
            )
        elif tool_name == "create_subnet":
            name = args.get("name") or "subnet1"
            data["subnet_path"] = cls._dry_run_path(args.get("parent_path", "/"), name)
        elif tool_name == "create_camera":
            name = args.get("name") or "agent_cam"
            data["path"] = cls._dry_run_path(args.get("parent_path", "/obj"), name)
        elif tool_name == "create_bed_controls":
            name = args.get("name") or "BED_CONTROLS"
            data["path"] = cls._dry_run_path(args.get("parent_path", "/"), name)
        elif tool_name == "create_material":
            data["material_path"] = cls._dry_run_path("/mat", args.get("mat_name", "material1"))
        elif tool_name == "assign_material":
            base = args.get("node_path", "/obj/geo1/null1").split("/")[-1]
            data["material_sop"] = cls._dry_run_path(
                "/".join(args.get("node_path", "/obj/geo1").split("/")[:-1]),
                f"{base}_material",
            )
            data["material"] = args.get("material_path")
        elif tool_name == "create_node_chain":
            parent = args.get("parent_path", "/")
            created = []
            for idx, step in enumerate(args.get("chain", []), start=1):
                name = step.get("name") or f"{step.get('type', 'node')}{idx}"
                created.append(
                    {
                        "path": cls._dry_run_path(parent, name),
                        "type": step.get("type"),
                        "name": name,
                    }
                )
            data["created"] = created
            data["count"] = len(created)
            if created:
                data["chain_head"] = created[0]["path"]
                data["chain_tail"] = created[-1]["path"]
        elif tool_name in {"setup_vellum_cloth", "setup_vellum_pillow"}:
            parent = args.get("parent_path", "/")
            if tool_name == "setup_vellum_cloth":
                data.update(
                    {
                        "constraints": cls._dry_run_path(parent, "vellum_cloth_constraints"),
                        "solver": cls._dry_run_path(parent, "vellum_solver"),
                        "cache": cls._dry_run_path(parent, "vellum_cache"),
                    }
                )
            else:
                data.update(
                    {
                        "constraints": cls._dry_run_path(parent, "pillow_struts"),
                        "solver": cls._dry_run_path(parent, "pillow_solver"),
                    }
                )
        elif tool_name in {"setup_flip_fluid", "setup_pyro_sim", "setup_rbd_fracture"}:
            parent = args.get("parent_path", "/")
            if tool_name == "setup_flip_fluid":
                data.update(
                    {
                        "source": cls._dry_run_path(parent, "flipsource1"),
                        "dopnet": cls._dry_run_path(parent, "flip_dopnet"),
                        "solver": cls._dry_run_path(
                            cls._dry_run_path(parent, "flip_dopnet"), "flipsolver1"
                        ),
                        "surface": cls._dry_run_path(parent, "fluid_surface"),
                    }
                )
            elif tool_name == "setup_pyro_sim":
                data.update(
                    {
                        "source": cls._dry_run_path(parent, "pyrosource1"),
                        "volume_rasterize": cls._dry_run_path(parent, "pyro_volume_rasterize"),
                        "solver": cls._dry_run_path(parent, "pyrosolver1"),
                        "postprocess": cls._dry_run_path(parent, "pyro_postprocess"),
                        "output": cls._dry_run_path(parent, "pyro_out"),
                        "mode": "sop",
                        "rasterized_attributes": ["density", "temperature", "fuel", "v"],
                    }
                )
            else:
                data.update(
                    {
                        "fracture": cls._dry_run_path(parent, "fracture1"),
                        "solver": cls._dry_run_path(parent, "rbd_bullet_solver"),
                        "output": cls._dry_run_path(parent, "rbd_out"),
                        "mode": "sop",
                    }
                )
        elif tool_name in {"safe_set_parameter", "set_parameter", "set_expression"}:
            data.update(
                {
                    "node_path": args.get("node_path"),
                    "parm_name": args.get("parm_name"),
                }
            )
        elif tool_name == "finalize_sop_network":
            parent = args.get("parent_path", "/")
            data.update(
                {
                    "output_path": cls._dry_run_path(parent, args.get("output_name", "OUT")),
                    "merge_path": cls._dry_run_path(parent, args.get("merge_name", "MERGE_FINAL")),
                    "source_paths": [],
                    "reused_existing": False,
                }
            )

        return {
            "status": "ok",
            "message": f"DRY RUN: Would execute {tool_name}",
            "data": data,
            "_meta": {"dry_run": True, "safety": safety_level},
        }

    # ── Shared dispatcher for Houdini main-thread marshalling ──
    # PERF-7: previously every tool call spawned its own daemon thread just to
    # call executeInMainThreadWithResult — 100–500µs of CPython thread startup
    # on each of the 30+ tool calls in a build turn. A small ThreadPoolExecutor
    # reuses threads.
    _hou_dispatch_pool = None
    _hou_dispatch_pool_lock = threading.Lock()
    _LONG_HOU_WRITE_TIMEOUTS = {
        "create_node_chain": 180.0,
        "finalize_sop_network": 120.0,
        "setup_pyro_sim": 240.0,
        "setup_rbd_fracture": 240.0,
        "setup_flip_fluid": 240.0,
        "setup_vellum_cloth": 180.0,
        "setup_vellum_pillow": 180.0,
        "bake_simulation": 300.0,
        "cook_network_range": 300.0,
        "layout_network": 90.0,
    }

    @classmethod
    def _get_hou_dispatch_pool(cls):
        if cls._hou_dispatch_pool is None:
            with cls._hou_dispatch_pool_lock:
                if cls._hou_dispatch_pool is None:
                    cls._hou_dispatch_pool = ThreadPoolExecutor(
                        max_workers=4,
                        thread_name_prefix="hou-dispatch",
                    )
        return cls._hou_dispatch_pool

    # ── FIX-2: Safe main-thread hou.* execution (no ThreadPoolExecutor) ─
    @classmethod
    def _hou_call(cls, fn, **kwargs):
        """
        Execute a hou.* function safely on Houdini's main thread.
        Uses hdefereval when available (inside Houdini), falls back to
        a direct call (unit tests / standalone).

        NEVER call hou.* from a background thread — it is not thread-safe
        and causes crashes or corrupted scene state.

        A configurable timeout (default 30s) is enforced via the shared
        dispatch pool so that a slow or hung Houdini cook never blocks the
        agent indefinitely.
        """
        timeout_s = float(kwargs.pop("_timeout_s", 90.0) or 90.0)
        try:
            import hdefereval
        except ImportError:
            return fn(**kwargs)

        # If we're already on Houdini's main Python thread, execute directly.
        # Dispatching back onto the main thread and then waiting here deadlocks.
        if threading.current_thread() is threading.main_thread():
            return fn(**kwargs)

        pool = cls._get_hou_dispatch_pool()
        # hdefereval.executeInMainThreadWithResult has its own positional
        # parameter named "code" in some Houdini builds. Passing tool kwargs
        # through here makes execute_python(code=...) collide with that API.
        # Bind kwargs before dispatch so Houdini receives only a callable.
        future = pool.submit(hdefereval.executeInMainThreadWithResult, partial(fn, **kwargs))
        try:
            return future.result(timeout=timeout_s)
        except FutureTimeoutError as exc:  # type: ignore[name-defined]
            raise TimeoutError(
                f"Houdini main-thread call timed out after {timeout_s:.0f}s for {getattr(fn, '__name__', str(fn))}. "
                "Houdini may still be cooking or blocked; increase the relevant hou-call timeout if this scene is intentionally heavy."
            ) from exc

    @staticmethod
    def _has_houdini_main_thread_dispatch() -> bool:
        try:
            import hdefereval

            return True
        except ImportError:
            return False

    def _tool_hou_timeout(self, tool_name: str, *, is_read: bool) -> float:
        base_timeout = max(30.0, float(self.config.get("tool_timeout_s", 90.0)))
        read_timeout = max(
            5.0,
            float(self.config.get("read_hou_call_timeout_s", min(base_timeout / 2.0, 30.0))),
        )
        if is_read:
            if getattr(self, "_fast_message_mode", False):
                return max(
                    5.0,
                    float(self.config.get("fast_read_hou_call_timeout_s", read_timeout)),
                )
            return read_timeout

        write_timeout = max(60.0, float(self.config.get("write_hou_call_timeout_s", base_timeout)))
        long_default = self._LONG_HOU_WRITE_TIMEOUTS.get(tool_name, write_timeout)
        if getattr(self, "_fast_message_mode", False):
            fast_write_timeout = max(
                60.0,
                float(self.config.get("fast_write_hou_call_timeout_s", write_timeout)),
            )
            return max(fast_write_timeout, long_default)
        return max(write_timeout, long_default)

    # ── FIX-3: Structured Planning pass for BUILD/DEBUG ─────────────
    def _generate_plan(
        self,
        user_message: str,
        request_mode: str,
        stream_callback: Callable | None = None,
        workflow_grounding: str | None = None,
    ) -> dict | None:
        """
        Ask the LLM to produce a structured hierarchical plan via PlannerAgent BEFORE
        executing any tool calls.
        """
        if request_mode not in ("build", "debug"):
            return None
        if not self.config.get("plan_enabled", True):
            return None
        # The user requested that the agent ALWAYS plans and reasons.
        # Removing the heuristic _query_is_complex check entirely.

        if stream_callback:
            stream_callback("\u200b📋 Formulating hierarchical plan…\n\n")

        if not getattr(self, "_planner", None):
            return None

        try:
            self.debug_logger.log_phase_start("planning")
            _plan_t0 = time.time()

            # Use WorldModel context if available
            scene_context = ""
            if hasattr(self, "world_model"):
                scene_context = self.world_model.to_prompt_context()

            if workflow_grounding:
                scene_context += f"\n\n[Workflow Grounding]\n{workflow_grounding}"

            plan_data = self._planner.generate_plan(user_message, scene_context=scene_context)

            self.debug_logger.log_phase_end(
                "planning",
                status="ok",
                started_at=_plan_t0,
                meta={"phases": len(plan_data.get("phases", []))},
            )
            self.debug_logger.log_plan(plan_data)

            if stream_callback:
                steps_text = []
                for phase in plan_data.get("phases", []):
                    steps_text.append(f"► Stage: {phase.get('phase', 'Execution')}")
                    for s in phase.get("steps", []):
                        action = s.get("action", "")
                        deps = s.get("dependency", [])
                        dep_str = f" (deps: {deps})" if deps else ""
                        risk = (
                            f" [{str(s.get('risk_level', 'low')).upper()}]"
                            if str(s.get("risk_level")).lower() in ["high", "medium"]
                            else ""
                        )
                        steps_text.append(f"  {s.get('step')}. {action}{dep_str}{risk}")

                joined_text = "\n".join(steps_text)
                stream_callback(f"\u200b📋 Plan:\n{joined_text}\n\n---\n\nExecuting…\n\n")
            return plan_data
        except Exception as exc:
            self.debug_logger.log_phase_end(
                "planning",
                status="error",
                started_at=_plan_t0 if "_plan_t0" in locals() else None,
                meta={"error": str(exc)[:160]},
            )
            self.debug_logger.log_exception(
                context="planning",
                exc=exc,
                stack_trace=_traceback.format_exc(),
            )
            self.debug_logger.log_system_note(f"Planning failed: {exc}")
            return None

    def _verify_plan_completion(
        self, plan_data: dict, tool_history: list[str], assistant_response: str
    ) -> str | None:
        """
        Two-stage plan verification:
        1. Scene-grounded check: extract node_path commitments from the plan and
           call get_node_parameters on each to confirm they actually exist in Houdini.
        2. LLM text comparison for steps that have no node_path commitment.
        Returns a reminder message if steps are missing, or None if complete.
        """
        if not plan_data:
            return None

        # Stage 1: scene-grounded node existence check
        missing_nodes: list[str] = []
        # Track expected (node_type, parent_path) for steps that named a type
        # but no exact path, or whose path didn't match — we then check whether
        # ANY child of the parent has that type, not just the exact name.
        expected_types: list[tuple[str, str, str]] = []  # (node_type, parent_or_path, action)
        for phase in plan_data.get("phases", []):
            for step in phase.get("steps", []):
                node_path = step.get("node_path", "") or ""
                node_type = (step.get("node_type", "") or "").strip().lower()
                action = step.get("action", "") or ""
                step_id = step.get("step")
                if node_path and node_path.startswith("/obj"):
                    try:
                        result = self._tool_executor(
                            "get_node_parameters", {"node_path": node_path}
                        )
                        if not (isinstance(result, dict) and result.get("status") != "error"):
                            missing_nodes.append(
                                f"Step {step_id}: {action} — node {node_path} not found in scene"
                            )
                    except Exception:
                        pass

                # If the step named a node_type, remember it for type-presence
                # check below. This catches the case where the agent created
                # a node of the right type but at a different path/name than
                # the planner specified.
                if node_type and node_type not in {"none", "n/a", "-"}:
                    parent_hint = ""
                    if node_path:
                        parent_hint = node_path.rsplit("/", 1)[0] if "/" in node_path else ""
                    expected_types.append((node_type, parent_hint or "/obj", action))

        # Type-presence check: for each expected type, see if the scene has
        # at least one node of that type under the expected parent. Lifts the
        # node-name miss out of "missing" if a type-equivalent node exists.
        type_misses: list[str] = []
        if expected_types:
            try:
                snapshot = self._capture_scene_snapshot() if HOU_AVAILABLE else None
            except Exception:
                snapshot = None
            scene_types_by_parent: dict[str, set[str]] = {}
            if snapshot:
                for node in snapshot.get("nodes", []) or []:
                    n_path = node.get("path") or ""
                    if self._is_scratch_path(n_path):
                        continue
                    n_type = (node.get("type") or "").strip().lower()
                    if not n_path or not n_type:
                        continue
                    parent = n_path.rsplit("/", 1)[0] if "/" in n_path else ""
                    scene_types_by_parent.setdefault(parent, set()).add(n_type)
                    # Also index ancestors so a node of the right type below the
                    # expected parent still counts.
                    crumbs = parent.split("/")
                    while len(crumbs) > 2:
                        crumbs.pop()
                        scene_types_by_parent.setdefault("/".join(crumbs), set()).add(n_type)

            for n_type, parent_hint, action in expected_types:
                # Already explicitly missing-by-path → don't double count
                # if the type also missing; just record the type miss with a
                # clearer hint.
                under = scene_types_by_parent.get(parent_hint, set())
                # Fallback: search under any /obj/<top> that contains the parent
                if n_type not in under:
                    matched = any(n_type in v for k, v in scene_types_by_parent.items())
                    if not matched:
                        type_misses.append(
                            f"Plan called for a '{n_type}' node ({action.strip()[:80]}) "
                            f"but no node of that type exists in the scene."
                        )

        if missing_nodes or type_misses:
            joined_paths = "\n".join(missing_nodes)
            joined_types = "\n".join(type_misses)
            sections = []
            if missing_nodes:
                sections.append(f"Missing nodes ({len(missing_nodes)}):\n{joined_paths}")
            if type_misses:
                sections.append(f"Missing node types ({len(type_misses)}):\n{joined_types}")
            joined = "\n\n".join(sections)
            return (
                f"Plan verification found gaps between the plan and the scene:\n"
                f"{joined}\n\n"
                f"Create the missing nodes (or equivalents) now using the exact "
                f"node_type the plan specified. Do NOT substitute a different "
                f"approach — the plan was chosen for a reason. If you genuinely "
                f"cannot use that node type, explain why before deviating."
            )

        # Stage 2: LLM text comparison for non-node steps
        plan_json = json.dumps(plan_data, indent=2)
        history_str = ", ".join(tool_history[-40:])

        system = (
            "You are a Houdini Plan Verification Agent.\n"
            "Compare the [INTENDED PLAN] against the [TOOL HISTORY] and the [ASSISTANT RESPONSE].\n"
            "Your goal is to ensure NO steps were forgotten or skipped.\n\n"
            "CRITERIA:\n"
            "1. Every phase and step in the plan must be addressed.\n"
            "2. If a step was attempted but failed, it counts as addressed only if the assistant mentions the failure or attempted it.\n"
            "3. If the assistant claims the task is done but high-level stages (like fracture, simulation, merge, or output) "
            "are clearly missing from the tool history, the plan is NOT complete.\n\n"
            "OUTPUT:\n"
            "- If all steps are completed: REPLY 'PLAN_COMPLETE'\n"
            "- If steps are missing: REPLY with a concise numbered list of missing steps and 'Please complete these steps now.'\n"
        )

        prompt = (
            f"[INTENDED PLAN]\n{plan_json}\n\n"
            f"[TOOL HISTORY]\n{history_str}\n\n"
            f"[ASSISTANT RESPONSE]\n{assistant_response}\n\n"
            "Is the plan complete? Check carefully for skipped merge/output/verify steps."
        )

        try:
            verdict = self.llm.chat_simple(
                system=system, user=prompt, temperature=0.05, task="quick"
            )
            if "PLAN_COMPLETE" in verdict.upper():
                return None
            return verdict
        except Exception:
            return None

    # ── Public API ────────────────────────────────────────────────────
    def chat(
        self,
        user_message: str,
        stream_callback: Callable | None = None,
        dry_run: bool = False,
        status_callback: Callable | None = None,
    ) -> str:
        previous_status_callback = self._runtime_status_callback
        self._runtime_status_callback = status_callback
        self._reset_turn_state()
        if self.rag and hasattr(self.rag, "reset_turn"):
            self.rag.reset_turn()

        # Track if this is a brand new request or a follow-up
        # New requests bypass initial vision snapshots to save tokens
        self._is_new_request = len(self.conversation) <= 1
        interaction_message = f"[DRY RUN] {user_message}" if dry_run else user_message

        # Task anchor: persist the user's goal across history compression.
        # Refresh on every substantive user request so the anchor always
        # reflects what the user JUST asked for, not a stale earlier turn.
        if len(user_message.strip()) > 20:
            self._task_anchor = user_message.strip()[:600]
        # Strip permanent negative constraints from history so they don't poison future turns
        if "do NOT modify the scene" in interaction_message:
            interaction_message = interaction_message.replace(
                " - do NOT modify the scene.", ""
            ).replace("READ-ONLY: ", "")

        # Capture rule count before interaction to detect rule extraction during the turn.
        # The actual comparison happens after _run_loop returns — sampling it here would
        # always match because the LLM hasn't run yet.
        rules_before = 0
        if self.memory and hasattr(self.memory, "project_rules"):
            rules_before = self.memory.project_rules.stats().get("total_rules", 0)

        interaction_id = self._start_logged_interaction(interaction_message)
        self._turn_rules_before = rules_before

        before_snapshot = None

        self.debug_logger.log_turn_start(interaction_message, meta=self._debug_model_meta())
        request_mode, _conf = self._classify_request_mode(user_message)
        self._active_task_contract = build_task_contract(user_message)
        if self._active_task_contract and request_mode == "advice":
            request_mode = "build"
            _conf = max(_conf, 0.90)
        self._emit_runtime_status(
            "turn_start",
            request_mode=request_mode,
            dry_run=bool(dry_run),
        )
        # OPT-1: log classification result so debug sessions show mode+confidence
        self.debug_logger.log_phase(
            "classify",
            status="ok",
            meta={
                "mode": request_mode,
                "confidence": _conf,
                "task_contract": (
                    self._active_task_contract.contract_id if self._active_task_contract else None
                ),
            },
        )
        fast_turn = bool(getattr(self, "_fast_message_mode", False))

        # ── User clarification channel ───────────────────────────────────
        # If the request is too ambiguous to act on, ask one short question
        # instead of guessing. Skipped in fast mode and dry runs.
        if not fast_turn and not dry_run and getattr(self, "_clarifier", None) is not None:
            recent_clar = bool(getattr(self, "_last_turn_was_clarification", False))
            # Survive process restarts: scan the last assistant message for the flag.
            if not recent_clar:
                for msg in reversed(self.conversation):
                    if msg.get("role") == "assistant":
                        recent_clar = bool(msg.get("_clarification"))
                        break
            cdec = self._clarifier.should_clarify(
                user_message,
                request_mode,
                recent_clarification_in_history=recent_clar,
            )
            self.debug_logger.log_phase(
                "clarify",
                status="ask" if cdec.ask else "skip",
                meta={"reason": cdec.reason[:160], "mode": request_mode},
            )
            if cdec.ask:
                clar_text = cdec.to_user_text()
                # Append the exchange so the user's reply lands in proper context.
                self.conversation.append({"role": "user", "content": user_message})
                self.conversation.append(
                    {"role": "assistant", "content": clar_text, "_clarification": True}
                )
                if self.memory_manager:
                    try:
                        self.memory_manager.save_conversation(self.conversation)
                    except Exception:
                        pass
                self._last_turn_was_clarification = True
                if stream_callback:
                    stream_callback(clar_text)
                self._finish_logged_interaction(interaction_id, clar_text)
                self._runtime_status_callback = previous_status_callback
                return clar_text
        # No clarification asked → reset the flag so a future ambiguous turn can ask again.
        self._last_turn_was_clarification = False

        if fast_turn:
            self.debug_logger.log_phase(
                "fast_mode",
                status="enabled",
                meta={
                    "vision_enabled": bool(getattr(self.llm, "vision_enabled", False)),
                    "max_tool_rounds": int(getattr(self, "max_tool_rounds", 0) or 0),
                    "early_completion_min_round": int(
                        getattr(self, "early_completion_min_round", 0) or 0
                    ),
                    "skips": [
                        "planning",
                        "rag_prefetch",
                        "startup_scene_snapshot",
                        "llm_history_compression",
                        "workflow_grounding",
                        "project_rules",
                        "post_build_verification",
                        "plan_completion_check",
                    ],
                    "reduced": ["cross_turn_failure_memory(cap=1)"],
                },
            )

        # ── Trigger background tasks concurrently ──
        self._prefetched_rag = []
        self._hot_cache_rag = None
        import concurrent.futures

        snapshot_future = None
        viewport_future = None

        # RAG prefetch: always run for build turns so the knowledge base is
        # available regardless of fast mode. Fast non-build turns (quick edits,
        # debug) still skip it for latency.
        if not fast_turn or request_mode == "build":
            self._prefetch_rag(user_message, request_mode)

            # Start snapshot and viewport captures concurrently
            pool = concurrent.futures.ThreadPoolExecutor(max_workers=2)
            snapshot_future = pool.submit(self._capture_scene_snapshot)

            if not self._is_new_request:
                viewport_future = pool.submit(self._capture_debug_screenshot, "Initial Viewport")

                # Store the hash for vision gating
                def _store_hash():
                    res = viewport_future.result()
                    if res:
                        self._initial_viewport_hash = self._compute_image_hash(res)

                threading.Thread(target=_store_hash, daemon=True).start()
            else:
                self.debug_logger.log_system_note("Skipping initial capture for fast/new request.")
                self._initial_viewport_hash = None

        try:
            # Phase 1 HACS: Rigorous Observation
            if not fast_turn and snapshot_future:
                current_snapshot = snapshot_future.result()
            else:
                current_snapshot = None

            if current_snapshot:
                with self._world_model_lock:
                    self.world_model.update_from_scene_snapshot(current_snapshot)
            if request_mode in {"build", "debug"}:
                before_snapshot = current_snapshot

            # Smart Scene Delta Injection
            delta_injection = ""
            if self._last_snapshot and current_snapshot:
                diff = self._diff_scene_snapshots(self._last_snapshot, current_snapshot)
                delta_text = self._format_scene_diff(diff)
                if delta_text:
                    delta_injection = f"\n\n[SCENE DELTA SINCE LAST MESSAGE]\n{delta_text}"

            self._last_snapshot = current_snapshot

            workflow_grounding = (
                ""
                if fast_turn
                else self._build_workflow_grounding_message(
                    user_message,
                    request_mode,
                )
            )

            # FIX-3: Structured Planning Pass
            plan_injection = ""
            plan_data = (
                None
                if fast_turn
                else self._generate_plan(
                    user_message,
                    request_mode,
                    stream_callback,
                    workflow_grounding=workflow_grounding,
                )
            )
            if plan_data:
                steps_text = json.dumps(plan_data, indent=2)
                plan_injection = (
                    f"\n\n[PROTOTYPE EXECUTION CONTRACT]\n{steps_text}\n\n"
                    "This plan is binding for the build. Convert its prototype measurements, counts, spacing, placement, and relationships into the actual scene edits.\n"
                    "Do not silently rescale the object. If the plan says a tabletop is 4.0 units wide or four legs are 3.4 units apart, build that scale unless physically impossible.\n"
                    "For every repeated part, create the requested count and preserve the requested spacing/symmetry.\n"
                    "Before your final answer, compare the built result against each plan validation line. If any line fails, fix it before claiming success.\n"
                    "After building, make sure the final visible output is merged if needed and ends at an OUT node."
                )

            self._compress_history_if_needed()
            # ARCH-1: the plan goes in as an ephemeral system message (see below),
            # not inlined into the persisted user content. Saving the augmented
            # user message would drift the persisted history out of sync with
            # what the LLM saw.
            augmented_message = user_message + delta_injection
            self.conversation.append({"role": "user", "content": interaction_message})
            if self.memory_manager:
                self.memory_manager.save_conversation(self.conversation)

            # Inject the World Model into the system prompt
            system_content = self.system_prompt + "\n\n" + self.world_model.to_prompt_context()
            few_shot = []
            if getattr(self, "model_adapter", None):
                system_content = self.model_adapter.adapt_system_prompt(self.system_prompt)
                few_shot = self.model_adapter.get_few_shot_message(user_message)

            base_messages = [
                {"role": "system", "content": system_content},
                *few_shot,
                *self.conversation,
            ]
            if getattr(self, "model_adapter", None):
                base_messages = self.model_adapter.trim_history(base_messages)

            mode_guidance = self._build_mode_guidance(request_mode, user_message)
            if mode_guidance:
                base_messages.insert(
                    len(base_messages) - 1, {"role": "system", "content": mode_guidance}
                )
            vex_guidance = self._build_vex_contract_guidance(user_message, request_mode)
            if vex_guidance:
                base_messages.insert(
                    len(base_messages) - 1, {"role": "system", "content": vex_guidance}
                )
            contract_guidance = format_task_contract_guidance(self._active_task_contract)
            if contract_guidance:
                base_messages.insert(
                    len(base_messages) - 1,
                    {"role": "system", "content": contract_guidance},
                )
            # Task anchor: re-inject original goal so it survives history compression.
            # Placed just before the current user message so it's always in context.
            if self._task_anchor:
                anchor_msg = (
                    f"[TASK ANCHOR — your current objective, do not deviate from this]\n"
                    f"{self._task_anchor}"
                )
                base_messages.insert(
                    len(base_messages) - 1, {"role": "system", "content": anchor_msg}
                )

            # Fast mode: inject known node parameter schemas to prevent parm hallucination
            if fast_turn:
                schema_hint = self._build_fast_schema_hint(user_message)
                if schema_hint:
                    base_messages.insert(
                        len(base_messages) - 1, {"role": "system", "content": schema_hint}
                    )
            if workflow_grounding:
                base_messages.insert(
                    len(base_messages) - 1,
                    {"role": "system", "content": workflow_grounding},
                )
            project_rules = "" if fast_turn else self._build_project_rules_guidance()
            if project_rules:
                base_messages.insert(
                    len(base_messages) - 1, {"role": "system", "content": project_rules}
                )
            if dry_run:
                base_messages.insert(
                    len(base_messages) - 1,
                    {"role": "system", "content": self._build_dry_run_guidance()},
                )

            # Cross-turn failure memory: warn agent about strategies that already failed
            # Fast turns use a lightweight version (single most-recent failure only)
            cross_turn_note = self._build_cross_turn_failure_note(user_message, fast=fast_turn)
            if cross_turn_note:
                base_messages.insert(
                    len(base_messages) - 1,
                    {"role": "system", "content": cross_turn_note},
                )

            # Scene delta is transient for this turn, so we still replace the
            # last user message with the augmented form. But the plan goes in
            # as a separate ephemeral system message so we don't persist a
            # user message containing the plan JSON (ARCH-1).
            if delta_injection:
                base_messages[-1] = {"role": "user", "content": augmented_message}
            if plan_injection:
                base_messages.insert(
                    len(base_messages) - 1,
                    {"role": "system", "content": plan_injection.strip()},
                )
            if dry_run:
                base_messages[-1]["content"] += (
                    "\n\n[DRY RUN]\nWrite-capable tools will be simulated. "
                    "Plan concrete changes but do not claim they were applied."
                )

            # Combine and wait for RAG thread — configurable cap (default 8s).
            # Previously 3s was too tight for first-time embed + BM25 on a large
            # knowledge base. We now key off an Event so we only use the
            # prefetch result if it actually finished before the deadline
            # (ARCH-11 — `is_alive` can flip false between the join and the
            # subsequent attr read, picking up a stale or partial buffer).
            # Build turns always wait for RAG (prefetch was started above for both
            # fast and non-fast build turns). Non-build fast turns skip it.
            rag_done = (
                getattr(self, "_rag_done_event", None)
                if (not fast_turn or request_mode == "build")
                else None
            )
            rag_wait_s = float(self.config.get("rag_prefetch_wait_s", 3.0))
            rag_ready = False
            if rag_done is not None:
                rag_ready = rag_done.wait(timeout=rag_wait_s)
                if not rag_ready:
                    print("[HoudiniMind] RAG prefetch timed out — proceeding without context")

            ctx_msg = getattr(self, "_prefetched_rag", None) if rag_ready else None

            full_messages = list(base_messages)
            if ctx_msg:
                # Find insertion point: right before last user message
                insert_at = len(full_messages)
                for i in reversed(range(len(full_messages))):
                    if full_messages[i].get("role") == "user":
                        insert_at = i
                        break
                full_messages.insert(insert_at, ctx_msg)

            # FIX-1: Only send relevant tools
            active_schemas = self._get_tool_schemas_for_request(user_message, request_mode)
            response_text = self._run_loop(
                full_messages,
                stream_callback,
                tool_schemas=active_schemas,
                dry_run=dry_run,
                request_mode=request_mode,
                plan_data=plan_data,
            )
            # Detect whether the turn added project rules. This has to run AFTER
            # _run_loop — the LLM hasn't written anything at the point we sampled
            # rules_before.
            self._announce_rule_learning(stream_callback)
            # Persist any tool failures from this turn into the cross-turn memory
            self._store_cross_turn_failures(user_message)
            self._turn_index += 1
            transient_llm_failure = self._is_transient_llm_failure(response_text)
            # Central repair budget for this turn. Shared across structural,
            # visual, and post-visual repair paths. Use _try_consume_repair_budget
            # to decrement — it enforces the hard floor at zero.
            self._turn_repair_budget = max(0, int(self.max_auto_repairs))

            # Self-correction: if build request made no edits, retry once
            if self._should_retry_build_turn(request_mode, response_text, dry_run=dry_run):
                self.debug_logger.log_system_note("Build self-correction: no write tools executed.")
                if stream_callback:
                    stream_callback(
                        "\u200b⚠️ No scene edits detected. Retrying in builder mode…\n\n"
                    )
                retry_messages = [
                    *list(full_messages),
                    {"role": "assistant", "content": response_text},
                    {"role": "user", "content": self._build_retry_message(user_message)},
                ]
                response_text = self._run_loop(
                    retry_messages,
                    stream_callback,
                    tool_schemas=active_schemas,
                    dry_run=dry_run,
                    request_mode=request_mode,
                    plan_data=plan_data,
                    _depth=1,
                )

            after_snapshot = None
            hou_blocked = bool(getattr(self, "_turn_hou_main_thread_blocked", False))
            if (
                request_mode == "build"
                and self._last_turn_write_tools
                and not dry_run
                and not transient_llm_failure
                and not hou_blocked
            ):
                after_snapshot = self._capture_scene_snapshot()
                finalized_outputs = self._auto_finalize_build_outputs(
                    before_snapshot, after_snapshot, stream_callback
                )
                if finalized_outputs:
                    self._last_turn_write_tools.append("finalize_sop_network")
                    self._last_turn_mutation_summaries.extend(
                        f"Finalize visible SOP output {path}" for path in finalized_outputs
                    )
                    response_text = (
                        response_text.rstrip()
                        + "\n\nFinalized visible output: "
                        + ", ".join(finalized_outputs[:4])
                    ).strip()
                    after_snapshot = self._capture_scene_snapshot()
            if (
                request_mode in {"build", "debug"}
                and not dry_run
                and not transient_llm_failure
                and self._last_turn_write_tools
                and not fast_turn
                and not hou_blocked
            ):
                after_snapshot = after_snapshot or self._capture_scene_snapshot()
                verification_report = self._run_verification_suite(
                    user_message,
                    before_snapshot,
                    after_snapshot,
                    request_mode,
                    stream_callback,
                    verification_profile=(
                        "light" if self.verification_light_before_repair else "full"
                    ),
                )
                if (
                    verification_report
                    and verification_report.get("status") == "fail"
                    and self._try_consume_repair_budget()
                ):
                    if stream_callback:
                        stream_callback(
                            "\u200b⚠️ Verification found issues. Running a targeted repair pass…\n\n"
                        )

                    critic_note = ""
                    try:
                        if locals().get("plan_data") and self.config.get(
                            "enable_repair_critic", False
                        ):
                            if stream_callback:
                                stream_callback(
                                    "\u200b🔍 Critic LLM analyzing failure root cause…\n\n"
                                )
                            critic_sys = "You are a Houdini critic. Identify the root cause of why the scene diff does not match the JSON goal/plan based on the report issues. Output 1 precise sentence."
                            critic_user = f"Goal: {json.dumps(plan_data)}\n\nReport:\n{verification_report.get('summary', '')}\nIssues:\n{json.dumps(verification_report.get('issues', []))}"
                            critic_insight = self.llm.chat_simple(
                                system=critic_sys,
                                user=critic_user,
                                task="critic",
                                temperature=0.2,
                            )
                            if critic_insight:
                                critic_note = f"\n\nCRITIC INSIGHT: {critic_insight.strip()}"
                    except Exception as e:
                        self.debug_logger.log_phase(
                            "critic_error", status="warn", meta={"error": str(e)[:100]}
                        )

                    repair_messages = [
                        *list(full_messages),
                        {"role": "assistant", "content": response_text},
                        {
                            "role": "user",
                            "content": self._build_verification_repair_message(
                                user_message, verification_report
                            )
                            + critic_note,
                        },
                    ]
                    response_text = self._run_loop(
                        repair_messages,
                        stream_callback,
                        tool_schemas=active_schemas,
                        dry_run=False,
                        request_mode="debug",
                        plan_data=plan_data,
                        _depth=1,
                    )
                    hou_blocked = bool(getattr(self, "_turn_hou_main_thread_blocked", False))
                    after_snapshot = None if hou_blocked else self._capture_scene_snapshot()
                    if not hou_blocked and request_mode == "build" and self._last_turn_write_tools:
                        finalized_outputs = self._auto_finalize_build_outputs(
                            before_snapshot, after_snapshot, stream_callback
                        )
                        if finalized_outputs:
                            self._last_turn_write_tools.append("finalize_sop_network")
                            self._last_turn_mutation_summaries.extend(
                                f"Finalize visible SOP output {path}" for path in finalized_outputs
                            )
                            after_snapshot = self._capture_scene_snapshot()
                    if not hou_blocked:
                        self._run_verification_suite(
                            user_message,
                            before_snapshot,
                            after_snapshot,
                            request_mode,
                            stream_callback,
                            verification_profile="full",
                        )
            raw_llm_response = bool((self.config.get("ui") or {}).get("raw_llm_response", False))
            if not raw_llm_response:
                response_text = self._reconcile_final_response_after_verification(
                    response_text,
                    self._last_turn_verification_report,
                )

            after_image_b64 = (
                None
                if transient_llm_failure or hou_blocked
                else self._capture_debug_screenshot("After Viewport")
            )

            # ── Vision feedback loop: up to 3 vision-guided repair attempts ──────
            # Runs for every build/debug turn when vision is enabled.
            # No keyword filter, no structural-pass skip (structural != visually correct).
            # Agent always knows its final goal via _task_anchor.
            _VISION_MAX_ATTEMPTS = 3
            _vision_goal = (getattr(self, "_task_anchor", None) or user_message).strip()
            _vision_attempt = 0
            _vision_loop_active = (
                not transient_llm_failure
                and not hou_blocked
                and not fast_turn  # skip in fast mode
                and request_mode in {"build", "debug"}
                and HOU_AVAILABLE
                and self._vision_capture_allowed()  # vision must be enabled
                and bool(self._last_turn_write_tools)
                and not dry_run
            )
            did_visual_repair = False
            if _vision_loop_active:
                while _vision_attempt < _VISION_MAX_ATTEMPTS:
                    _vision_attempt += 1
                    if stream_callback:
                        stream_callback(
                            f"​👁️ Vision check {_vision_attempt}/{_VISION_MAX_ATTEMPTS}"
                            f" — verifying: {_vision_goal[:80]}…\n\n"
                        )

                    # Attempt 1 reuses the already-captured image; later attempts
                    # take a fresh screenshot so repairs are actually visible.
                    _check_image = (
                        after_image_b64
                        if _vision_attempt == 1
                        else self._capture_debug_screenshot(
                            f"Vision Check {_vision_attempt}", force_refresh=True
                        )
                    )

                    visual_pass = self._perform_visual_self_check(
                        _vision_goal, response_text, _check_image, stream_callback
                    )

                    if visual_pass:
                        if stream_callback:
                            stream_callback(f"​✅ Vision passed on attempt {_vision_attempt}.\n\n")
                        break

                    if _vision_attempt >= _VISION_MAX_ATTEMPTS:
                        # All attempts exhausted — emit a clear diagnostic.
                        _final_verdict = getattr(
                            self, "_last_visual_verdict", "No verdict recorded."
                        )
                        _diag = (
                            f"After {_VISION_MAX_ATTEMPTS} vision-guided repair attempts "
                            "the scene still does not visually match the goal.\n\n"
                            f"GOAL: {_vision_goal}\n\n"
                            f"LAST VISION VERDICT:\n{_final_verdict}\n\n"
                            "The geometry and node graph are intact. The visual mismatch "
                            "may need a different modelling approach. "
                            "Please inspect the scene and tell me what to adjust next."
                        )
                        response_text = (
                            response_text.rstrip()
                            + f"\n\n[VISION DIAGNOSTIC — {_VISION_MAX_ATTEMPTS} ATTEMPTS]\n{_diag}"
                        )
                        if stream_callback:
                            stream_callback(
                                f"​⚠️ Vision still failing after {_VISION_MAX_ATTEMPTS} "
                                "attempts — see diagnostic below.\n\n"
                            )
                        break

                    # ── Repair attempt (not last) ────────────────────────────────────
                    did_visual_repair = True
                    if stream_callback:
                        stream_callback(
                            f"​🛠️ Vision attempt {_vision_attempt} failed — "
                            "running targeted repair…\n\n"
                        )

                    # ── Gather spatial diagnostics for the repair prompt ──
                    diag_lines = []
                    conn_lines = []
                    after_snap = after_snapshot or self._capture_scene_snapshot()
                    if after_snap:
                        for nd in after_snap.get("nodes") or []:
                            nd_path = nd.get("path", "")
                            nd_type = str(nd.get("type", ""))
                            # Gather bounding boxes for geometry nodes
                            if nd_type in (
                                "box",
                                "grid",
                                "sphere",
                                "tube",
                                "torus",
                                "merge",
                                "copytopoints",
                                "xform",
                                "null",
                            ) or nd.get("is_displayed"):
                                try:
                                    bb = self._hou_call(
                                        TOOL_FUNCTIONS["get_bounding_box"],
                                        node_path=nd_path,
                                    )
                                    if bb.get("status") == "ok":
                                        d = bb.get("data") or {}
                                        cx = d.get("center_x", d.get("cx", 0))
                                        cy = d.get("center_y", d.get("cy", 0))
                                        cz = d.get("center_z", d.get("cz", 0))
                                        sx = d.get("size_x", d.get("sx", 0))
                                        sy = d.get("size_y", d.get("sy", 0))
                                        sz = d.get("size_z", d.get("sz", 0))
                                        diag_lines.append(
                                            f"  {nd_path} ({nd_type}): "
                                            f"center=({cx:.3f}, {cy:.3f}, {cz:.3f}), "
                                            f"size=({sx:.3f}, {sy:.3f}, {sz:.3f})"
                                        )
                                except Exception:
                                    pass
                            # Gather connection info for multi-input nodes
                            if nd_type in ("copytopoints", "merge", "boolean"):
                                try:
                                    inp = self._hou_call(
                                        TOOL_FUNCTIONS["get_node_inputs"],
                                        node_path=nd_path,
                                    )
                                    if inp.get("status") == "ok":
                                        conn_lines.append(
                                            f"  {nd_path} inputs: {inp.get('message', inp.get('data', ''))}"
                                        )
                                except Exception:
                                    pass

                    diag_section = ""
                    if diag_lines:
                        diag_section += (
                            "\n\n📐 CURRENT BOUNDING BOXES (center + size in scene units):\n"
                            + "\n".join(diag_lines[:12])
                        )
                    if conn_lines:
                        diag_section += "\n\n🔗 MULTI-INPUT NODE WIRING:\n" + "\n".join(
                            conn_lines[:6]
                        )

                    repair_prompt = (
                        f"FINAL GOAL: {_vision_goal}\n\n"
                        f"Vision check {_vision_attempt}/{_VISION_MAX_ATTEMPTS} FAILED — "
                        "geometry-specific structural or proportional flaws found.\n\n"
                        f"\U0001f50d CRITIC REPORT:\n{getattr(self, '_last_visual_verdict', 'Visual check failed.')}\n"
                        f"{diag_section}\n\n"
                        "ROOT CAUSE ANALYSIS — think step by step:\n"
                        "1. Look at the bounding boxes above. Are components at the wrong Y position? "
                        "Vertical support parts usually have size_y larger than their horizontal footprint and must touch the component they support.\n"
                        "2. For copytopoints: input 0 = geometry to copy, input 1 = target points. Are they correct?\n"
                        "3. Is the copied geometry oriented correctly BEFORE being copied? "
                        "If a vertical support is flat, its Y-size needs to be the largest dimension.\n"
                        "4. For stacked parts, compute min_y/max_y from bounding boxes and close only the measured gap.\n\n"
                        "FIX RULES:\n"
                        "- Do NOT restart. Modify existing node parameters with safe_set_parameter.\n"
                        "- Fix the MINIMUM number of parameters to resolve the flaws.\n"
                        "- You MUST call write tools (safe_set_parameter, connect_nodes, etc.) — reading alone is not a fix.\n"
                        f"- After fixing, vision will re-check automatically (attempt {_vision_attempt + 1}/{_VISION_MAX_ATTEMPTS})."
                    )

                    repair_messages = [
                        *list(full_messages),
                        {"role": "assistant", "content": response_text},
                        {"role": "user", "content": repair_prompt},
                    ]
                    response_text = self._run_loop(
                        repair_messages,
                        stream_callback,
                        tool_schemas=active_schemas,
                        dry_run=False,
                        request_mode="debug",
                        plan_data=plan_data,
                        _depth=1,
                    )
                    hou_blocked = bool(getattr(self, "_turn_hou_main_thread_blocked", False))
                    after_snapshot = None if hou_blocked else self._capture_scene_snapshot()

            auto_restore_note = ""
            if not hou_blocked:
                auto_restore_note = self._auto_restore_failed_turn_if_needed(
                    request_mode=request_mode,
                    dry_run=dry_run,
                    remaining_repair_budget=self._turn_repair_budget,
                    stream_callback=stream_callback,
                )
            if auto_restore_note:
                response_text = (
                    response_text.rstrip() + "\n\n[AUTO-ROLLBACK]\n" + auto_restore_note
                ).strip()
                after_snapshot = self._capture_scene_snapshot() if not hou_blocked else None

            # ── Persist repair lesson so agent learns for next session ──
            if locals().get("did_visual_repair") and self.memory and self._last_turn_write_tools:
                try:
                    import hashlib as _hashlib

                    _task_key = _hashlib.md5(user_message.encode()).hexdigest()[:8]
                    _recipe_name = f"repair_{_task_key}"
                    _steps = [{"tool": t, "args": {}} for t in self._last_turn_write_tools]
                    _existing = self.memory.recipe_book.search(user_message[:60])
                    if not _existing:
                        _rid = self.memory.recipe_book.add_recipe(
                            name=_recipe_name,
                            description=(
                                f"Auto-repair recipe for: '{user_message[:80]}'. "
                                "Agent detected visual flaws and self-corrected. "
                                "Use these tools/parameters for this type of task."
                            ),
                            trigger_pattern=user_message[:120],
                            steps=_steps,
                            domain="geometry",
                        )
                    else:
                        _rid = _existing[0]["id"]
                    if _rid and _rid > 0:
                        self.memory.recipe_book.record_use(_rid, accepted=True)
                    self.memory.self_updater.update()
                except Exception:
                    pass

            scene_diff_text = ""
            verification_text = self._last_turn_verification_text or ""
            if dry_run:
                scene_diff_text = self._format_mutation_summary(
                    self._last_turn_mutation_summaries, dry_run=True
                )
            elif self._last_turn_write_tools:
                if not hou_blocked:
                    after_snapshot = after_snapshot or self._capture_scene_snapshot()
                    scene_diff = self._diff_scene_snapshots(before_snapshot, after_snapshot)
                    scene_diff_text = self._format_scene_diff(scene_diff, dry_run=False)
                if not scene_diff_text:
                    scene_diff_text = self._format_mutation_summary(
                        self._last_turn_mutation_summaries, dry_run=False
                    )

            self._last_turn_scene_diff_text = scene_diff_text or None

            # --- FINAL CHECK PHASE ---
            if (
                self.final_check_enabled
                and not dry_run
                and not transient_llm_failure
                and HOU_AVAILABLE
                and not hou_blocked
            ):
                if stream_callback:
                    stream_callback(
                        "\n\u200b🏁 Final Check: generating comprehensive visual report…\n"
                    )

                # Force high-resolution captures for the final state
                final_viewport_b64 = self._capture_debug_screenshot(
                    "Final Viewport", pane_type="viewport", force_refresh=True
                )
                # Store on agent so the UI panel can display it inline in the bubble
                self._last_turn_final_viewport_b64 = final_viewport_b64
                if final_viewport_b64:
                    self._emit_runtime_status("viewport_image", image_b64=final_viewport_b64)

                # For the final network view, if the agent has a known candidate parent,
                # try to frame it to show the user the structure better.
                final_node_path = None
                if self._last_turn_output_paths:
                    final_node_path = self._last_turn_output_paths[0]

                self._capture_debug_screenshot(
                    "Final Network View",
                    pane_type="network",
                    node_path=final_node_path,
                    force_refresh=True,
                )

                final_note = "\n\n[FINAL CHECK]\nViewport and Network View captures completed for the final state."
                response_text = (response_text.rstrip() + final_note).strip()

            if verification_text and not raw_llm_response:
                response_text = (response_text.rstrip() + "\n\n" + verification_text).strip()
            if scene_diff_text and not raw_llm_response:
                response_text = (response_text.rstrip() + "\n\n" + scene_diff_text).strip()

            # ── Task-contract block: prepend a clear banner if the active
            # contract still has unresolved issues after every repair pass.
            contract_banner = self._format_unresolved_contract_banner()
            if contract_banner and not raw_llm_response:
                response_text = (contract_banner + "\n\n" + response_text).strip()

            if not raw_llm_response:
                response_text = self._build_grounded_turn_response(
                    request_mode,
                    response_text,
                    dry_run=dry_run,
                )

            self.debug_logger.log_response(response_text)
            self.conversation.append({"role": "assistant", "content": response_text})
            self._emit_runtime_status(
                "turn_complete",
                request_mode=request_mode,
                success=not response_text.lower().startswith("⚠️ agent error"),
            )
            return response_text
        except Exception as e:
            response_text = f"⚠️ Agent Error: {e}"
            self.debug_logger.log_system_note(response_text)
            # HARDENING: log full traceback for debugging but never re-raise
            # to the UI. Re-raising kills the Python Panel's worker thread
            # and forces the user to restart the panel.
            self.debug_logger.log_exception(
                context="chat_outer",
                exc=e,
                stack_trace=_traceback.format_exc(),
            )
            self._emit_runtime_status(
                "turn_complete",
                request_mode=request_mode if "request_mode" in locals() else "advice",
                success=False,
                error=str(e),
            )
            self.conversation.append({"role": "assistant", "content": response_text})
            return response_text
        finally:
            self._runtime_status_callback = previous_status_callback
            self._finish_logged_interaction(interaction_id, response_text)

    def chat_with_vision(
        self,
        user_message: str,
        image_bytes: bytes,
        stream_callback: Callable | None = None,
        dry_run: bool = False,
        status_callback: Callable | None = None,
    ) -> str:
        # Check if vision is disabled
        if not getattr(self.llm, "vision_enabled", True):
            if stream_callback:
                stream_callback(
                    "\u200bℹ️  Vision model is disabled in settings. Skipping image analysis.\n\n"
                )
            return self.chat(
                user_message,
                stream_callback,
                dry_run=dry_run,
                status_callback=status_callback,
            )

        if stream_callback:
            stream_callback("\u200b👁️  Analysing image with vision model…\n\n")

        # Detect whether this looks like a Houdini screenshot (node graph / viewport)
        # or a reference image the user wants to recreate. The heuristic: if the user
        # message contains build intent words, treat it as a reference object image.
        _build_words = re.compile(
            r"\b(create|build|make|model|recreate|reproduce|match|replicate|based on|like this|this chair|this object)\b",
            re.IGNORECASE,
        )
        _is_reference_image = bool(_build_words.search(user_message))

        if _is_reference_image:
            vision_prompt = (
                "You are a 3D modelling analyst helping a Houdini artist recreate this object as a procedural 3D model.\n\n"
                "Analyse the image and answer ALL of the following:\n\n"
                "1. COMPONENT LIST — List every distinct physical part separately (e.g. front leg, rear leg, seat board, backrest post, top rail, slat, stretcher). "
                "Do NOT merge separate parts together. A leg and a backrest post are different parts even if they look similar.\n\n"
                "2. CONNECTIONS — For each component, state exactly what it connects to and where (top/bottom/side).\n\n"
                "3. DIMENSIONS (relative) — Estimate proportions: height/width/depth ratios for each part relative to the overall object.\n\n"
                "4. COUNTS — State the exact count of each repeated part (e.g. '4 legs', '5 slats', '2 stretchers').\n\n"
                "5. STRUCTURAL ACCURACY — Be precise: do NOT infer construction technique from appearance. "
                "If rear legs look the same height as front legs, say so — do NOT assume they extend further just because there is a backrest.\n\n"
                "6. ASSEMBLY ORDER — Suggest a bottom-up build order for a Houdini procedural model.\n\n"
                "Be factual and conservative. If you are unsure about a detail, say so rather than guessing."
            )
        else:
            # Bug fix: the screenshot is a 3D viewport — the Node Network editor,
            # Parameter Pane, and Timeline are NOT visible. Asking vision to describe
            # "node networks" or "parameter values" causes hallucinated "Inferred"
            # sections. Vision must only report what the pixels actually show.
            vision_prompt = (
                "You are analysing a Houdini 3D viewport screenshot.\n"
                "IMPORTANT: This image shows ONLY the 3D viewport. "
                "The Node Network editor, Parameter Pane, and Timeline are NOT visible.\n\n"
                "Describe ONLY what you can actually see:\n"
                "1. GEOMETRY — What shapes/objects are present? Count and describe each.\n"
                "2. VISUAL CORRECTNESS — Does the geometry look like the intended result? "
                "What specifically looks wrong, missing, or misplaced?\n"
                "3. VISIBLE ARTIFACTS — Floating parts, wrong proportions, gaps, overlaps, "
                "or components that should connect but don't.\n\n"
                "Do NOT guess node types, parameter values, or network structure from geometry "
                "appearance. If something cannot be confirmed from the viewport alone, say so."
            )

        # Build a brief tool-history summary so vision doesn't re-derive what the
        # agent already knows it built. Vision covers only the visual gap.
        _tool_context = ""
        try:
            _recent_tools: list[str] = []
            for msg in (self.conversation or [])[-30:]:
                if msg.get("role") == "assistant":
                    for tc in msg.get("tool_calls") or []:
                        fn_name = (tc.get("function") or {}).get("name", "")
                        if fn_name:
                            _recent_tools.append(fn_name)
            if _recent_tools:
                _tool_context = (
                    f"\n\nAGENT CONTEXT: The agent already executed these tools this session "
                    f"({', '.join(_recent_tools[-12:])}). Node/parameter state is already known "
                    "from those calls — focus purely on whether the 3D geometry looks "
                    "visually correct, not on re-deriving structure."
                )
        except Exception:
            pass

        try:
            vision_description = self.llm.chat_vision(
                prompt=vision_prompt + _tool_context, image_bytes=image_bytes
            )
        except Exception as e:
            if self._cancel_event.is_set():
                self._cancel_event.clear()
                return "⏹ Task cancelled by user."
            if isinstance(e, ConnectionError):
                vision_description = f"[Vision model unavailable: {e}]"
            else:
                raise

        proxy_injection = ""
        request_mode, _ = self._classify_request_mode(user_message)
        if self.proxy_generation_enabled and request_mode == "build":
            try:
                proxy_spec = self._reference_proxy_planner.build_proxy_spec(
                    self.llm,
                    user_message=user_message,
                    vision_description=vision_description,
                )
                proxy_injection = self._reference_proxy_planner.format_prompt_injection(proxy_spec)
                if proxy_injection and stream_callback:
                    stream_callback("\u200b🧱 Built a proxy spec from the attached reference.\n\n")
            except Exception as e:
                self.debug_logger.log_system_note(f"Reference proxy generation unavailable: {e}")

        # Signal that the user already provided visual context for this turn so
        # _reset_turn_state can pre-charge the vision budget. This prevents
        # _perform_visual_self_check from firing a redundant second vision call
        # when the user's screenshot already established the baseline.
        self._this_turn_user_provided_vision = True

        augmented = f"{user_message}\n\n[VISION ANALYSIS OF ATTACHED IMAGE]\n{vision_description}"
        if proxy_injection:
            augmented += f"\n\n{proxy_injection}"
        return self.chat(
            augmented,
            stream_callback,
            dry_run=dry_run,
            status_callback=status_callback,
        )

    def inspect_network_view(
        self,
        stream_callback: Callable | None = None,
        status_callback: Callable | None = None,
    ) -> str:
        previous_status_callback = self._runtime_status_callback
        self._runtime_status_callback = status_callback
        self._reset_turn_state()
        interaction_message = "[Network Inspect] Inspect the current Houdini network view."
        interaction_id = self._start_logged_interaction(
            interaction_message, domain="network_inspect"
        )
        response_text = None
        self.debug_logger.log_turn_start(interaction_message, meta=self._debug_model_meta())
        try:
            self._refresh_live_scene_context()
            snapshot = self._capture_scene_snapshot()
            if not snapshot:
                response_text = "I couldn't capture the current Houdini scene snapshot to inspect the network view."
                return response_text

            if stream_callback:
                stream_callback("\u200b🕸️ Inspecting the current network editor…\n\n")

            parent_paths = []
            for selected_path in snapshot.get("selected_nodes", []) or []:
                parent = self._parent_path(selected_path)
                if parent and parent not in parent_paths:
                    parent_paths.append(parent)

            error_scan = self._run_observation_tool(
                "get_all_errors", {"include_warnings": True}, stream_callback
            )
            network_review = self._analyze_network_view(
                "Inspect the current Houdini network editor and explain the important wiring/layout issues like a human reviewer.",
                snapshot,
                parent_paths=parent_paths,
                stream_callback=stream_callback,
            )

            lines = ["Network inspection complete."]
            node_count = len(snapshot.get("nodes", []) or [])
            connection_count = len(snapshot.get("connections", []) or [])
            selected_nodes = snapshot.get("selected_nodes", []) or []
            lines.append(
                f"Snapshot: {node_count} nodes, {connection_count} connections, {len(selected_nodes)} selected node(s)."
            )
            if selected_nodes:
                lines.append("Selected: " + ", ".join(selected_nodes[:4]))
            if network_review:
                summary = network_review.get("summary", "")
                if summary:
                    lines.append(summary)
                for issue in network_review.get("issues", [])[:6]:
                    lines.append(
                        f"- {issue.get('severity', 'warning').upper()}: {issue.get('message', '')}"
                    )
            if error_scan.get("status") == "ok":
                nodes = (error_scan.get("data") or {}).get("nodes", [])[:6]
                if nodes:
                    lines.append("")
                    lines.append("Houdini-reported issues:")
                    for node in nodes:
                        errs = node.get("errors") or node.get("warnings") or []
                        if errs:
                            lines.append(f"- {node.get('path', '?')}: {errs[0]}")
            response_text = "\n".join(lines).strip()
            self.debug_logger.log_response(response_text)
            self.conversation.append({"role": "user", "content": interaction_message})
            self.conversation.append({"role": "assistant", "content": response_text})
            if self.memory_manager:
                self.memory_manager.save_conversation(self.conversation)
            return response_text
        except Exception as e:
            response_text = f"⚠️ Network inspection error: {e}"
            self.debug_logger.log_system_note(response_text)
            raise
        finally:
            self._runtime_status_callback = previous_status_callback
            self._finish_logged_interaction(interaction_id, response_text)

    # ── Research option sentinel ──────────────────────────────────────
    # The panel watches for this prefix in stream chunks.  When it sees it,
    # it renders a ResearchOptionsWidget instead of appending raw text.
    _OPTIONS_SENTINEL = AutoResearcher.OPTIONS_SENTINEL

    @staticmethod
    def _parse_research_options(synthesis: str) -> list:
        """
        Parse '## Option N: Title' blocks out of a synthesis string.
        Returns a list of dicts: {id, title, body}
        Falls back to a single option containing the whole synthesis.
        """
        # Strip the marker if present
        clean = synthesis.replace(AutoResearcher.OPTIONS_SENTINEL, "").strip()
        blocks = re.split(r"(?m)^## Option \d+[:\s]", clean)
        options = []
        titles = re.findall(r"(?m)^## Option \d+[:\s](.+)$", clean)
        # blocks[0] is text before first heading — skip it
        for i, block in enumerate(blocks[1:], start=1):
            title = titles[i - 1].strip() if (i - 1) < len(titles) else f"Option {i}"
            options.append({"id": i, "title": title, "body": block.strip()})
        if not options:
            # No options found — wrap the whole synthesis as one option
            options = [{"id": 1, "title": "Research Result", "body": clean}]
        return options

    def research(
        self,
        query: str,
        stream_callback=None,
        status_callback: Callable | None = None,
    ) -> str:
        """
        Run AutoResearch and stream the OPTIONS SENTINEL to the panel.
        By default, auto-selects the strongest option and executes it.
        If the user explicitly asks to compare approaches/options, it returns
        the option list for manual selection instead.
        """
        previous_status_callback = self._runtime_status_callback
        self._runtime_status_callback = status_callback
        self._reset_turn_state()
        interaction_message = f"[AutoResearch] {query}"
        interaction_id = self._start_logged_interaction(interaction_message, domain="research")
        full_response = None

        self.debug_logger.log_turn_start(interaction_message, meta=self._debug_model_meta())
        self._capture_debug_screenshot("Before Viewport")

        try:
            options = self.auto_researcher.run(query, progress_callback=stream_callback)
            options_json = json.dumps({"query": query, "options": options}, ensure_ascii=False)

            auto_execute = bool(self.config.get("auto_research_execute_best_option", True))
            if AutoResearcher.should_offer_manual_choice(query):
                auto_execute = False

            if auto_execute and options:
                request_mode, _conf = self._classify_request_mode(query)
                selected = self.auto_researcher.select_best_option(
                    query,
                    options,
                    request_mode=request_mode,
                )
                selected_id = selected.get("id", "?")
                selected_label = selected.get("label", "Selected Option")
                selection_reason = selected.get(
                    "_selection_reason",
                    "it is the strongest fit for the request",
                )
                selection_note = (
                    f"I compared {len(options)} approaches and I’m choosing "
                    f"`{selected_label}` because {selection_reason}."
                )
                if stream_callback:
                    stream_callback(self.PROGRESS_SENTINEL + selection_note)
                self.debug_logger.log_system_note(
                    f"Auto-selected research option {selected_id}: {selected_label}\n"
                    f"Reason: {selection_reason}\n"
                    f"Options: {options_json}"
                )
                full_response = self.execute_research_option(
                    selected,
                    query,
                    stream_callback=stream_callback,
                    log_interaction=False,
                    interaction_message=f"[AutoSelected Option {selected_id}] {selected_label} — {query}",
                )
                self.debug_logger.log_response(full_response)
                self.conversation.append({"role": "user", "content": interaction_message})
                self.conversation.append({"role": "assistant", "content": full_response})
                return full_response

            # Serialize and emit sentinel so panel can render option cards
            sentinel_payload = AutoResearcher.OPTIONS_SENTINEL + options_json

            if stream_callback:
                stream_callback(sentinel_payload)

            full_response = options_json
            self.debug_logger.log_response(full_response)
            self.conversation.append({"role": "user", "content": interaction_message})
            self.conversation.append({"role": "assistant", "content": full_response})
            return full_response

        except Exception as e:
            full_response = f"\u26a0\ufe0f Research Error: {e}"
            self.debug_logger.log_system_note(full_response)
            raise
        finally:
            self._runtime_status_callback = previous_status_callback
            self._finish_logged_interaction(interaction_id, full_response)

    def execute_research_option(
        self,
        option: dict,
        original_query: str,
        stream_callback=None,
        log_interaction: bool = True,
        interaction_message: str | None = None,
    ) -> str:
        """
        Called by panel when user clicks 'Use This' on an option card.
        Builds an execution prompt from the selected option and runs the agent loop.
        """
        self._reset_turn_state()
        label = option.get("label", "Selected Option")
        if getattr(self, "model_adapter", None):
            self.model_adapter.adapt_system_prompt(self.system_prompt)
            self.model_adapter.get_few_shot_message(original_query)

        summary = option.get("summary", "")
        details = option.get("details", "")
        use_when = option.get("use_when", "")
        opt_id = option.get("id", "?")

        interaction_message = (
            interaction_message or f"[Execute Option {opt_id}] {label} — {original_query}"
        )
        interaction_id = -1
        full_response = None

        if log_interaction:
            interaction_id = self._start_logged_interaction(
                interaction_message, domain="research_exec"
            )
            self.debug_logger.log_turn_start(interaction_message, meta=self._debug_model_meta())
            self._capture_debug_screenshot("Before Viewport")
        else:
            self.debug_logger.log_system_note(interaction_message)

        try:
            request_mode, _conf = self._classify_request_mode(original_query)
            self._active_task_contract = build_task_contract(original_query)
            if request_mode in {"build", "debug"}:
                self._refresh_live_scene_context()

            sep = "\u2550" * 55
            sep2 = "\u2500" * 32
            execution_prompt = (
                f"{sep}\n"
                f"EXECUTE SELECTED OPTION: {label}\n"
                f"{sep}\n\n"
                f"Original request: {original_query}\n\n"
                f"Selected approach: {summary}\n"
                f"Why this option: {use_when}\n\n"
                f"Implementation details:\n{details}\n\n"
                f"{sep2}\n"
                "CRITICAL: Use Houdini tools NOW to implement this exactly as described above.\n"
                "Do NOT switch to a different approach. Follow the details precisely.\n"
                "After completion, confirm what was created/changed.\n"
                f"{sep2}\n"
                "Begin execution now."
            )

            self._compress_history_if_needed()
            recent_history = (
                self.conversation[-8:] if len(self.conversation) >= 8 else self.conversation[:]
            )
            exec_messages = [
                {"role": "system", "content": self.system_prompt},
                *recent_history,
                {"role": "user", "content": execution_prompt},
            ]

            mode_guidance = self._build_mode_guidance(request_mode, original_query)
            if mode_guidance:
                exec_messages.insert(
                    len(exec_messages) - 1, {"role": "system", "content": mode_guidance}
                )
            contract_guidance = format_task_contract_guidance(self._active_task_contract)
            if contract_guidance:
                exec_messages.insert(
                    len(exec_messages) - 1,
                    {"role": "system", "content": contract_guidance},
                )
            project_rules = self._build_project_rules_guidance()
            if project_rules:
                exec_messages.insert(
                    len(exec_messages) - 1, {"role": "system", "content": project_rules}
                )

            if self.rag:
                # P2-A: use the prefetch result when the background thread finished
                # in time, avoiding a redundant synchronous retrieval on the hot path.
                _prefetch_ready = (
                    getattr(self, "_rag_done_event", None) is not None
                    and self._rag_done_event.is_set()
                    and isinstance(getattr(self, "_prefetched_rag", None), dict)
                )
                if _prefetch_ready:
                    exec_messages = self.rag.inject_prebuilt(exec_messages, self._prefetched_rag)
                else:
                    exec_messages = self.rag.inject_into_messages(
                        messages=exec_messages,
                        query=original_query,
                        live_scene_json=self._live_scene_json,
                        **self._get_rag_injection_kwargs(request_mode, original_query),
                    )

            full_response = self._run_loop(
                exec_messages,
                stream_callback,
                tool_schemas=self._get_tool_schemas_for_request(original_query, request_mode),
                request_mode=request_mode,
            )
            self._capture_debug_screenshot("After Viewport")
            if log_interaction:
                self.debug_logger.log_response(full_response)
                self.conversation.append({"role": "user", "content": interaction_message})
                self.conversation.append({"role": "assistant", "content": full_response})
                if self.memory_manager:
                    self.memory_manager.save_conversation(self.conversation)
            return full_response

        except Exception as e:
            full_response = f"\u26a0\ufe0f Execution Error: {e}"
            self.debug_logger.log_system_note(full_response)
            raise
        finally:
            if log_interaction:
                self._finish_logged_interaction(interaction_id, full_response)

    # ── Internal loop ─────────────────────────────────────────────────
    _MAX_LOOP_DEPTH = 3  # HARDENING: prevent unbounded recursive _run_loop calls

    def _run_loop(
        self,
        messages: list,
        stream_callback: Callable | None = None,
        tool_schemas: list | None = None,
        dry_run: bool = False,
        request_mode: str = "advice",
        plan_data: dict | None = None,
        _depth: int = 0,
    ) -> str:
        # HARDENING: recursion depth guard — repair, validation, and plan-completion
        # paths all call _run_loop recursively.  Without a ceiling this could
        # stack-overflow when the LLM keeps triggering repair cascades.
        if _depth >= self._MAX_LOOP_DEPTH:
            self.debug_logger.log_system_note(
                f"_run_loop recursion depth {_depth} >= {self._MAX_LOOP_DEPTH}, returning early"
            )
            # Still return a useful summary if we made scene edits
            if hasattr(self, "_last_turn_write_tools") and self._last_turn_write_tools:
                return (
                    "Reached maximum repair depth. Scene edits were applied. "
                    "Please review the scene and provide further instructions."
                )
            return "Reached maximum repair depth. Please review the scene and provide further instructions."

        current_messages = list(messages)
        consecutive_errors = 0
        MAX_CONSECUTIVE_ERRORS = 3
        tool_history: list[str] = []
        write_tools: list[str] = []
        mutation_summaries: list[str] = []
        active_schemas = tool_schemas or TOOL_SCHEMAS
        failed_attempts: dict = {}
        self._turn_tool_counts = {}
        self._turn_capture_pane_analyses = 0
        self._turn_failed_attempts = {}  # reset each turn; updated live for cross-turn memory
        # Stagnation detection — tracks error signatures to detect looping on same failure
        _error_signature_counts: dict = {}
        MAX_SAME_ERROR_REPEATS = 3
        # Successful-call repetition guard: tracks (tool, target_node) → count
        # so we can detect when the model loops on resizing the same node
        # without ever creating the missing nodes.
        _success_node_counts: dict = {}
        MAX_SAME_NODE_CALLS = 5

        for round_num in range(self.max_tool_rounds):
            hard_timeout_this_round = False
            if round_num > 0 and self.tool_round_pause_s > 0:
                time.sleep(self.tool_round_pause_s)

            if self._cancel_event.is_set():
                self._cancel_event.clear()
                self._finalize_turn_tracking(tool_history, write_tools)
                return "⏹ Task cancelled by user."

            # OPT-1: log each tool round as a phase so sessions show loop depth
            self.debug_logger.log_phase(
                "tool_round",
                status="info",
                meta={"round": round_num, "mode": request_mode},
            )

            # ── Budget gate ──────────────────────────────────────────────
            # Stop cleanly if wall-clock or token budget for this turn ran out.
            if getattr(self, "_turn_budget", None) is not None:
                exhausted, reason = self._turn_budget.is_exhausted()
                if exhausted:
                    self.debug_logger.log_phase(
                        "budget",
                        status="exhausted",
                        meta=self._turn_budget.snapshot(),
                    )
                    self._finalize_turn_tracking(tool_history, write_tools)
                    return (
                        f"⏸ Stopped early: {reason} "
                        "Partial progress preserved. Re-issue with adjusted "
                        "scope or raise the budget in core_config.json."
                    )

            llm_task = self._select_loop_task(request_mode, round_num, consecutive_errors)
            _llm_t0 = time.time()
            if request_mode != "advice":
                self._emit_progress(
                    stream_callback, self._describe_llm_round(request_mode, round_num)
                )
            # FIX: Stabilize payload size for long tool loops (HTTP 400 fix)
            current_messages = self._truncate_tool_history(current_messages)

            # Goal anchor — re-inject the original user objective right before
            # every LLM call so it survives history truncation and stays at
            # peak recency. Without this the agent drifts off-task in long
            # tool loops (e.g. wandering off into unrelated edits after ~10
            # rounds, once the original user message has been compressed out).
            current_messages = self._inject_task_anchor_reminder(current_messages)

            msg = None

            try:
                llm_timeout_s = self._select_loop_timeout(
                    request_mode, round_num, bool(write_tools)
                )
                # Tool-calling uses Ollama's stream=True under the hood so we
                # can forward each token to the UI in real time.  The token
                # callback emits raw deltas through stream_callback (no
                # \u200b prefix → routes to the message bubble like a normal
                # chat stream).  Some backends buffer when tools= is passed
                # and never call us back per-token; we track that and fall
                # back to a single emission of the final text below.
                _streamed_any = {"v": False}

                def _live_token(delta: str):
                    if not delta or stream_callback is None:
                        return
                    _streamed_any["v"] = True
                    try:
                        stream_callback(delta)
                    except Exception:
                        pass

                # Budget bookkeeping: record input tokens before the call.
                if getattr(self, "_turn_budget", None) is not None:
                    try:
                        in_tok = count_message_tokens(current_messages, model=self.llm.model)
                    except Exception:
                        in_tok = 0
                    if in_tok:
                        self._turn_budget.record_tokens(in_tokens=in_tok)

                # HARDENING: retry transient LLM failures with exponential backoff
                # before giving up. Avoids losing entire turns to momentary Ollama hiccups.
                _LLM_RETRY_DELAYS = [2.0, 5.0, 10.0]
                _llm_last_exc = None
                for _retry_i in range(len(_LLM_RETRY_DELAYS) + 1):
                    try:
                        msg = self.llm.chat(
                            current_messages,
                            tools=active_schemas,
                            task=llm_task,
                            timeout_s=llm_timeout_s,
                            chunk_callback=_live_token,
                        )
                        _llm_last_exc = None
                        # Budget bookkeeping: record output tokens.
                        if getattr(self, "_turn_budget", None) is not None and msg:
                            try:
                                out_tok = count_tokens(
                                    str(msg.get("content") or ""),
                                    model=self.llm.model,
                                )
                            except Exception:
                                out_tok = 0
                            if out_tok:
                                self._turn_budget.record_tokens(out_tokens=out_tok)
                        break  # success
                    except Exception as _llm_exc:
                        _llm_last_exc = _llm_exc
                        # Non-transient errors (e.g. HTTP 400 bad schema) propagate immediately
                        if not self._is_transient_llm_failure(str(_llm_exc)):
                            break
                        if _retry_i >= len(_LLM_RETRY_DELAYS):
                            break  # final retry exhausted
                        _delay = _LLM_RETRY_DELAYS[_retry_i]
                        self.debug_logger.log_system_note(
                            f"LLM call failed (attempt {_retry_i + 1}/{len(_LLM_RETRY_DELAYS) + 1}): "
                            f"{_llm_exc}. Retrying in {_delay}s..."
                        )
                        if stream_callback:
                            stream_callback(
                                f"\u200b\u23f3 LLM temporarily unavailable, retrying in {_delay:.0f}s...\n"
                            )
                        time.sleep(_delay)
                        _llm_t0 = time.time()  # reset timer for the retry
                        _streamed_any["v"] = False  # reset streaming flag

                if _llm_last_exc is not None:
                    raise _llm_last_exc
                _llm_elapsed = int((time.time() - _llm_t0) * 1000)
                text = msg.get("content", "") or ""

                tool_calls = msg.get("tool_calls", []) if msg else []
                # Fallback: if the model emitted JSON tool calls in text
                # instead of using native Ollama tool calling, recover them.
                if not tool_calls and text and getattr(self, "model_adapter", None):
                    extracted = self.model_adapter.extract_fallback_tool_calls(text)
                    if extracted:
                        tool_calls = extracted
            except Exception as e:
                if hasattr(e, "code") and e.code == 400:
                    raise ConnectionError(
                        f"HTTP 400: Bad Request. The context window (history/verification data) "
                        f"likely exceeded the {self.context_window} token limit."
                    )
                if hasattr(e, "code"):
                    raise ConnectionError(f"HTTP Error {e.code}: {getattr(e, 'reason', 'Unknown')}")
                self.debug_logger.log_llm_call(
                    "tool_loop",
                    status="error",
                    elapsed_ms=int((time.time() - _llm_t0) * 1000),
                    meta={"round": round_num, "error": str(e)},
                )
                self.debug_logger.log_exception(
                    context=f"tool_loop round {round_num}",
                    exc=e,
                    stack_trace=_traceback.format_exc(),
                )
                self.debug_logger.log_system_note(f"LLM request failed: {e}")
                if self._should_use_local_response_fallback(
                    str(e), write_tools, mutation_summaries, dry_run=dry_run
                ):
                    fallback = self._build_local_response_fallback(
                        mutation_summaries,
                        write_tools,
                        str(e),
                        dry_run=dry_run,
                    )
                    self.debug_logger.log_system_note(
                        "Using local response fallback after late LLM failure."
                    )
                    self._finalize_turn_tracking(
                        tool_history, write_tools, mutation_summaries, dry_run
                    )
                    return fallback
                # HARDENING: Even if _should_use_local_response_fallback returned
                # False, if we already made scene edits preserve them in the
                # response so the user sees what was done before the LLM died.
                if write_tools and mutation_summaries:
                    self._finalize_turn_tracking(
                        tool_history, write_tools, mutation_summaries, dry_run
                    )
                    return (
                        f"⚠️ LLM connection failed ({str(e)[:100]}), but scene edits were applied.\n\n"
                        + self._format_mutation_summary(mutation_summaries)
                    )
                self._finalize_turn_tracking(tool_history, write_tools, mutation_summaries, dry_run)
                return f"⚠️ {e}"

            _tu = getattr(self.llm, "_last_token_usage", {})
            self.debug_logger.log_llm_call(
                "tool_loop",
                status="ok",
                elapsed_ms=_llm_elapsed,
                model=_tu.get("model") if _tu else None,
                tokens_in=_tu.get("tokens_in") if _tu else None,
                tokens_out=_tu.get("tokens_out") if _tu else None,
                meta={
                    "round": round_num,
                    "task": llm_task,
                    "has_tool_calls": bool(tool_calls),
                    "text_chars": len(text),
                    "streaming": bool(stream_callback),
                },
            )
            # Log token usage from Ollama response (also written to md for human readability)
            _tu = getattr(self.llm, "_last_token_usage", {})
            if _tu and (_tu.get("tokens_in") or _tu.get("tokens_out")):
                self.debug_logger.log_token_usage(
                    stage="tool_loop",
                    tokens_in=_tu.get("tokens_in"),
                    tokens_out=_tu.get("tokens_out"),
                    model=_tu.get("model"),
                    context_window=getattr(self.llm, "context_window", None),
                    total_duration_ms=_tu.get("total_duration_ms"),
                    meta={"round": round_num},
                )
            # Log context budget (message count) so we can track window usage
            self.debug_logger.log_context_budget(
                stage="tool_loop_pre",
                message_count=len(current_messages),
                context_window=getattr(self.llm, "context_window", None),
            )
            self.debug_logger.log_llm_output(
                round_index=round_num,
                task=llm_task or request_mode or "default",
                content=text,
                tool_calls=tool_calls,
                model=_tu.get("model") if _tu else None,
                meta={"has_tool_calls": bool(tool_calls)},
            )
            self._emit_llm_trace(
                stream_callback,
                round_num,
                llm_task or request_mode,
                text,
                tool_calls,
            )

            if not tool_calls:
                # ── Phase 3: Post-Build QA Validation ──
                # If we mutated the scene, trigger the ValidatorAgent to ensure
                # no cook errors or disconnected sequences exist before returning.
                if (
                    request_mode == "build"
                    and not dry_run
                    and write_tools
                    and not getattr(self, "_fast_skip_validator", False)
                    and hasattr(self, "_validator")
                    and getattr(self, "world_model", None)
                    and round_num < self.max_tool_rounds - 1
                ):
                    _goal = ""
                    for _m in reversed(current_messages):
                        if _m.get("role") == "user" and isinstance(_m.get("content"), str):
                            _goal = _m["content"][:500]
                            break

                    if stream_callback:
                        stream_callback("\u200b🔍 Running Validator QA check on scene...\n")

                    self.debug_logger.log_phase_start("validation")
                    val_report = self._validator.validate_build(
                        goal=_goal, scene_context=self.world_model.to_prompt_context()
                    )
                    self.debug_logger.log_phase_end(
                        "validation", status="ok" if val_report.get("passed") else "failed"
                    )

                    if not val_report.get("passed", True) and not val_report.get("advisory_only"):
                        issues = val_report.get("issues", [])
                        suggestions = val_report.get("suggestions", [])
                        if not issues:
                            issues = ["Validator reported failure without a specific issue."]
                        self._turn_validation_failed = True
                        self._turn_validation_issues = [str(i) for i in issues]

                        val_msg = "[VALIDATION FAILED]\n"
                        if issues:
                            val_msg += f"Issues found: {'; '.join(issues)}\n"
                        if suggestions:
                            val_msg += f"Suggestions: {'; '.join(suggestions)}\n"
                        val_msg += "Fix these issues now before considering the task complete."

                        if stream_callback:
                            stream_callback(
                                f"\u200b❌ Validation Failed: {len(issues)} issues found. Re-entering loop to repair...\n\n"
                            )

                        # CRIT-9: the previous code streamed the assistant text,
                        # appended it, appended the system repair, then continued
                        # the while-loop — so the NEXT stream produced a second
                        # visible response with no separator, and tool_history /
                        # write_tools / mutation_summaries were never finalized
                        # for the round that just ran. Finalize here, then re-enter
                        # _run_loop with the repair messages, mirroring how
                        # verification repair is handled in chat().
                        self._finalize_turn_tracking(
                            tool_history, write_tools, mutation_summaries, dry_run
                        )
                        repair_messages = [
                            *list(current_messages),
                            {"role": "assistant", "content": text},
                            {"role": "system", "content": val_msg},
                        ]
                        return self._run_loop(
                            repair_messages,
                            stream_callback,
                            tool_schemas=tool_schemas,
                            dry_run=dry_run,
                            request_mode=request_mode,
                            plan_data=plan_data,
                            _depth=_depth + 1,
                        )

                # If the backend buffered (no per-token callback fired) emit
                # the final text now in word-chunks so the user still sees a
                # streaming-like effect in the bubble.  Otherwise we already
                # streamed live above and emit nothing here.
                if stream_callback and text and not _streamed_any["v"]:
                    words = text.split(" ")
                    chunk_size = 20
                    for chunk_start in range(0, len(words), chunk_size):
                        if self._cancel_event.is_set():
                            self._cancel_event.clear()
                            self._finalize_turn_tracking(
                                tool_history, write_tools, mutation_summaries, dry_run
                            )
                            return "⏹ Task cancelled by user."
                        chunk_words = words[chunk_start : chunk_start + chunk_size]
                        chunk_text = " ".join(chunk_words)
                        if chunk_start + chunk_size < len(words):
                            chunk_text += " "
                        stream_callback(chunk_text)
                if self._cancel_event.is_set():
                    self._cancel_event.clear()
                    self._finalize_turn_tracking(
                        tool_history, write_tools, mutation_summaries, dry_run
                    )
                    return "⏹ Task cancelled by user."
                if (
                    request_mode == "build"
                    and not dry_run
                    and getattr(self, "_turn_validation_failed", False)
                    and not write_tools
                ):
                    issues = getattr(self, "_turn_validation_issues", []) or [
                        "Validation did not pass."
                    ]
                    self._finalize_turn_tracking(
                        tool_history, write_tools, mutation_summaries, dry_run
                    )
                    return (
                        "Validation did not pass, so I cannot honestly mark this complete yet. "
                        f"Remaining issue: {'; '.join(str(i) for i in issues[:3])}"
                    )
                # ── Phase 4: Plan Completion Check ──
                if (
                    request_mode == "build"
                    and not dry_run
                    and plan_data
                    and not getattr(self, "_fast_message_mode", False)
                    and round_num < self.max_tool_rounds - 1
                    and self._plan_verification_count < 2
                ):
                    reminder = self._verify_plan_completion(plan_data, tool_history, text)
                    if reminder:
                        self._plan_verification_count += 1
                        if stream_callback:
                            stream_callback(
                                "\u200b📋 Plan incomplete — re-entering loop to finish steps...\n\n"
                            )

                        self._finalize_turn_tracking(
                            tool_history, write_tools, mutation_summaries, dry_run
                        )
                        reminder_messages = [
                            *list(current_messages),
                            {"role": "assistant", "content": text},
                            {"role": "system", "content": f"[PLAN NOT FINISHED]\n{reminder}"},
                        ]
                        return self._run_loop(
                            reminder_messages,
                            stream_callback,
                            tool_schemas=tool_schemas,
                            dry_run=dry_run,
                            request_mode=request_mode,
                            plan_data=plan_data,
                            _depth=_depth + 1,
                        )

                self._finalize_turn_tracking(tool_history, write_tools, mutation_summaries, dry_run)
                return text

            # Intermediate LLM reasoning text — if the backend buffered we
            # emit it as one chunk now.  When live streaming worked, the
            # tokens already reached the bubble via chunk_callback above.
            if text and stream_callback and not _streamed_any["v"]:
                stream_callback(f"{text}\n\n")

            assistant_msg = msg if msg is not None else {"role": "assistant", "content": text}
            current_messages.append(assistant_msg)
            all_errors_this_round = []
            successful_tools_this_round = 0
            round_tool_names: list[str] = []

            tool_results: dict[int, dict] = {}

            def _execute_single_tool(
                idx: int, tc: dict, *, concurrent: bool = False
            ) -> tuple[int, str, str, dict, str, dict]:
                tool_name = tc.get("function", {}).get("name", "").strip(" \"'")
                raw_args = tc.get("function", {}).get("arguments", {})
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                except (TypeError, json.JSONDecodeError) as exc:
                    return (
                        idx,
                        str(tc.get("id") or ""),
                        tool_name,
                        {"_raw_arguments": str(raw_args)[:1000]},
                        "",
                        {
                            "status": "error",
                            "message": (
                                "Argument JSON parsing failed: "
                                f"{exc}. Re-emit this tool call with valid JSON object arguments."
                            ),
                            "data": None,
                            "_correction_hint": (
                                "Tool arguments must be a valid JSON object string, "
                                "with quoted keys and no trailing commas."
                            ),
                        },
                    )
                if not isinstance(args, dict):
                    return (
                        idx,
                        str(tc.get("id") or ""),
                        tool_name,
                        {"_raw_arguments": args},
                        "",
                        {
                            "status": "error",
                            "message": (
                                "Argument validation failed: tool arguments must be a JSON object, "
                                f"not {type(args).__name__}."
                            ),
                            "data": None,
                            "_correction_hint": (
                                "Re-call the tool with an object containing the schema fields."
                            ),
                        },
                    )
                attempt_sig = self._tool_attempt_signature(tool_name, args)
                prior_failure = failed_attempts.get(attempt_sig)
                if (
                    prior_failure
                    and prior_failure.get("write_epoch") == self._turn_scene_write_epoch
                ):
                    res = self._duplicate_failure_result(
                        tool_name, prior_failure.get("message", "Unknown error")
                    )
                else:
                    # In parallel read-only batches, suppress the UI callback so
                    # stream output isn't interleaved across threads. Progress
                    # is emitted later from _process_result in index order.
                    cb = None if concurrent else stream_callback
                    res = self._execute_tool(tool_name, args, cb, dry_run=dry_run)
                return idx, str(tc.get("id") or ""), tool_name, args, attempt_sig, res

            def _process_result(
                idx: int,
                tool_call_id: str,
                tool_name: str,
                args: dict,
                attempt_sig: str,
                res: dict,
            ):
                nonlocal consecutive_errors
                nonlocal successful_tools_this_round
                nonlocal hard_timeout_this_round
                if self._cancel_event.is_set():
                    return
                self._turn_tool_counts[tool_name] = self._turn_tool_counts.get(tool_name, 0) + 1
                round_tool_names.append(tool_name)
                tool_history.append(tool_name)
                self._emit_progress(stream_callback, self._describe_tool_action(tool_name, args))
                if stream_callback:
                    arg_str = ", ".join(f"{k}={repr(v)[:40]}" for k, v in args.items())
                    if len(arg_str) > 240:
                        arg_str = arg_str[:240].rstrip() + "…"
                    stream_callback(f"\u200b🔧 {tool_name}({arg_str})\n")
                self.debug_logger.log_tool_call(tool_name, args, res)
                if "UNDO_TRACK:" in res.get("message", ""):
                    self.undo_stack.append(res["message"].replace("UNDO_TRACK: ", ""))
                if self.memory:
                    self.memory.log_tool_call(tool_name, args, res)
                if self.on_tool_call:
                    self.on_tool_call(tool_name, args, res)
                if res.get("status") == "error":
                    if self._is_houdini_main_thread_timeout(res.get("message", "")):
                        hard_timeout_this_round = True
                    self._emit_progress(
                        stream_callback,
                        self._describe_tool_failure(tool_name, args, res.get("message", "")),
                    )
                    failed_attempts[attempt_sig] = {
                        "tool": tool_name,
                        "args": args,
                        "message": res.get("message", "unknown error"),
                        "write_epoch": self._turn_scene_write_epoch,
                    }
                    self._turn_failed_attempts = dict(failed_attempts)
                    all_errors_this_round.append(
                        {
                            "tool": tool_name,
                            "args": args,
                            "error": res.get("message", "unknown error"),
                            "hint": res.get("_correction_hint", ""),
                        }
                    )
                    if stream_callback:
                        stream_callback(
                            f"\u200b❌ {tool_name} failed: {res.get('message', '')[:200]}\n"
                        )
                else:
                    consecutive_errors = 0
                    failed_attempts.pop(attempt_sig, None)
                    if res.get("status") == "ok":
                        successful_tools_this_round += 1
                    if (
                        res.get("status") == "ok"
                        and tool_name not in READ_ONLY_TOOLS
                        and tool_name not in NON_SCENE_MUTATING_WRITE_TOOLS
                        and not res.get("_meta", {}).get("dry_run")
                    ):
                        # The scene changed; previously failed signatures may now be valid.
                        failed_attempts.clear()
                        self._turn_failed_attempts = {}
                    # Track successful calls per (tool, node_path) for repetition guard
                    if res.get("status") == "ok" and tool_name == "safe_set_parameter":
                        _target = args.get("node_path", "")
                        _key = f"{tool_name}:{_target}"
                        _success_node_counts[_key] = _success_node_counts.get(_key, 0) + 1
                    if tool_name not in READ_ONLY_TOOLS and res.get("status") not in {"cancelled"}:
                        write_tools.append(tool_name)
                        mutation = self._summarize_mutation(tool_name, args, res)
                        if mutation:
                            mutation_summaries.append(mutation)
                    if stream_callback:
                        prefix = "🧪" if res.get("_meta", {}).get("dry_run") else "✅"
                        stream_callback(
                            f"\u200b{prefix} {tool_name} → {res.get('message', 'OK')[:120]}\n"
                        )
                tool_msg = {"role": "tool", "content": json.dumps(res)}
                if tool_call_id:
                    tool_msg["tool_call_id"] = tool_call_id
                current_messages.append(tool_msg)

            if len(tool_calls) == 1:
                idx, tool_call_id, tool_name, args, attempt_sig, res = _execute_single_tool(
                    0, tool_calls[0]
                )
                if self._cancel_event.is_set():
                    self._cancel_event.clear()
                    self._finalize_turn_tracking(
                        tool_history, write_tools, mutation_summaries, dry_run
                    )
                    return "⏹ Task cancelled by user."
                _process_result(idx, tool_call_id, tool_name, args, attempt_sig, res)
            else:
                read_only_batch = [
                    (i, tc)
                    for i, tc in enumerate(tool_calls)
                    if tc.get("function", {}).get("name", "").strip(" \"'") in READ_ONLY_TOOLS
                ]
                write_batch = [
                    (i, tc)
                    for i, tc in enumerate(tool_calls)
                    if tc.get("function", {}).get("name", "").strip(" \"'") not in READ_ONLY_TOOLS
                ]

                tool_results: dict[int, tuple] = {}

                if read_only_batch:
                    max_workers = min(len(read_only_batch), 8)
                    with ThreadPoolExecutor(max_workers=max_workers) as executor:
                        futures = {}
                        for i, tc in read_only_batch:
                            if self._cancel_event.is_set():
                                executor.shutdown(wait=False, cancel_futures=True)
                                break
                            futures[
                                executor.submit(_execute_single_tool, i, tc, concurrent=True)
                            ] = i

                        for future in as_completed(futures):
                            try:
                                idx, tool_call_id, tool_name, args, attempt_sig, res = (
                                    future.result()
                                )
                                tool_results[idx] = (
                                    tool_call_id,
                                    tool_name,
                                    args,
                                    attempt_sig,
                                    res,
                                )
                            except Exception as exc:
                                i = futures[future]
                                tool_results[i] = (
                                    "",
                                    None,
                                    None,
                                    None,
                                    {
                                        "status": "error",
                                        "message": f"Tool execution error: {exc}",
                                    },
                                )

                for i, tc in write_batch:
                    if self._cancel_event.is_set():
                        self._cancel_event.clear()
                        self._finalize_turn_tracking(
                            tool_history, write_tools, mutation_summaries, dry_run
                        )
                        return "⏹ Task cancelled by user."
                    idx, tool_call_id, tool_name, args, attempt_sig, res = _execute_single_tool(
                        i, tc
                    )
                    tool_results[idx] = (tool_call_id, tool_name, args, attempt_sig, res)

                for i, tc in enumerate(tool_calls):
                    if self._cancel_event.is_set():
                        self._cancel_event.clear()
                        self._finalize_turn_tracking(
                            tool_history, write_tools, mutation_summaries, dry_run
                        )
                        return "⏹ Task cancelled by user."
                    if i in tool_results:
                        tool_call_id, tool_name, args, attempt_sig, res = tool_results[i]
                        if tool_name:
                            _process_result(i, tool_call_id, tool_name, args, attempt_sig, res)

            if hard_timeout_this_round:
                self._turn_hou_main_thread_blocked = True
                self.debug_logger.log_phase(
                    "abort_houdini_main_thread_timeout",
                    status="error",
                    meta={"round": round_num},
                )
                self._finalize_turn_tracking(tool_history, write_tools, mutation_summaries, dry_run)
                timeout_msg = (
                    "Stopped early: Houdini main thread is blocked, so tool calls are timing out. "
                    "Finish/cancel the current cook in Houdini, then retry."
                )
                if mutation_summaries:
                    timeout_msg = (
                        timeout_msg + "\n\n[SCENE DIFF]\n- " + "\n- ".join(mutation_summaries[:10])
                    )
                return timeout_msg

            # ── Successful-call repetition guard ─────────────────────
            # Detect when the model loops on safe_set_parameter for the
            # same node N+ times. This catches the "resize same box in
            # circles" pattern that wastes rounds without creating new nodes.
            _repeat_warning_injected = False
            for _rep_key, _rep_count in _success_node_counts.items():
                if _rep_count >= MAX_SAME_NODE_CALLS:
                    _rep_tool, _rep_node = _rep_key.split(":", 1)
                    self.debug_logger.log_phase(
                        "repetition_guard",
                        status="warn",
                        meta={"key": _rep_key, "count": _rep_count},
                    )
                    current_messages.append(
                        {
                            "role": "user",
                            "content": (
                                f"🚨 REPETITION DETECTED: You have called `{_rep_tool}` on "
                                f"`{_rep_node}` {_rep_count} times. You are stuck in a loop "
                                f"resizing/repositioning the same node.\n\n"
                                f"STOP modifying `{_rep_node}`. The plan requires MULTIPLE "
                                f"separate nodes (e.g. 4 legs need 4 box nodes, not 1 box "
                                f"resized repeatedly).\n\n"
                                f"ACTION REQUIRED:\n"
                                f"1. Call `create_node` for each MISSING part\n"
                                f"2. Call `safe_set_parameter` ONCE per new node\n"
                                f"3. Position each node at its correct offset\n"
                                f"Do NOT call safe_set_parameter on `{_rep_node}` again."
                            ),
                        }
                    )
                    # Reset the counter so the guard re-fires if the model
                    # ignores the first warning.
                    _success_node_counts[_rep_key] = 0
                    _repeat_warning_injected = True
                    if stream_callback:
                        stream_callback(
                            f"\u200b🔁 Repetition guard: {_rep_tool} called {_rep_count}× on {_rep_node}. Injecting correction.\n"
                        )
            if _repeat_warning_injected:
                continue  # skip error processing, let model act on the warning

            if all_errors_this_round:
                no_progress_failure_round = successful_tools_this_round == 0
                consecutive_errors = consecutive_errors + 1 if no_progress_failure_round else 0
                # Stagnation detection — build a signature from tool+error and count repeats
                for e in all_errors_this_round:
                    sig = f"{e.get('tool', '')}:{e.get('error', '')[:60]}"
                    _error_signature_counts[sig] = _error_signature_counts.get(sig, 0) + 1
                    if _error_signature_counts[sig] >= MAX_SAME_ERROR_REPEATS:
                        self.debug_logger.log_phase(
                            "stagnation_exit",
                            status="warn",
                            meta={
                                "signature": sig,
                                "count": _error_signature_counts[sig],
                            },
                        )
                        self._finalize_turn_tracking(
                            tool_history, write_tools, mutation_summaries, dry_run
                        )
                        return (
                            f"Stopped: the same error repeated {MAX_SAME_ERROR_REPEATS}+ times without progress.\n"
                            f"Stuck on: `{e.get('tool', '')}` — {e.get('error', '')[:120]}\n"
                            "Try rephrasing your request or check node/parameter names."
                        )
                if no_progress_failure_round and consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    err_summary = "; ".join(e["error"][:80] for e in all_errors_this_round)
                    self._finalize_turn_tracking(
                        tool_history, write_tools, mutation_summaries, dry_run
                    )
                    return (
                        f"Stopped after {consecutive_errors} consecutive tool failures.\n"
                        f"Last errors: {err_summary}\n"
                        "Check node type strings and parameter names and try again."
                    )
                retry_lines = [
                    f"- Tool `{e['tool']}` with args {e['args']} failed: {e['error']}"
                    for e in all_errors_this_round
                ]
                network_retry_note = ""
                if (
                    request_mode in {"build", "debug"}
                    and not dry_run
                    and no_progress_failure_round
                    and consecutive_errors == 1
                    and not getattr(self, "_fast_execution", False)
                ):
                    retry_snapshot = self._capture_scene_snapshot()
                    retry_parents = (
                        self._candidate_finalize_networks(None, retry_snapshot)
                        if retry_snapshot
                        else []
                    )
                    retry_network_review = self._analyze_network_view(
                        "Inspect the current network view and point out the most likely wiring/layout clue that will help fix the failed tool step.",
                        retry_snapshot,
                        parent_paths=retry_parents,
                        stream_callback=stream_callback,
                    )
                    if retry_network_review and retry_network_review.get("summary"):
                        network_retry_note = "\n\nNetwork-view clue:\n" + retry_network_review.get(
                            "summary", ""
                        )
                # Detect null-required-field errors and emit a targeted schema reminder
                null_field_hints = []
                for e in all_errors_this_round:
                    err_msg = e.get("error", "")
                    if "Missing required field" in err_msg and "null" not in err_msg.lower():
                        # e.g. node_type was passed as null (JSON null → None → fails required check)
                        null_field_hints.append(
                            f"⚠️ `{e['tool']}` had a required field set to null. "
                            f"You MUST provide a real string value — never null or None.\n"
                            f"Schema hint from error: {err_msg.split('Hint:')[-1].strip()[:300] if 'Hint:' in err_msg else err_msg[:200]}"
                        )
                    elif "Missing required field" in err_msg:
                        null_field_hints.append(
                            f"⚠️ `{e['tool']}` is missing a required field.\n"
                            f"Schema: {err_msg.split('Hint:')[-1].strip()[:300] if 'Hint:' in err_msg else err_msg[:200]}"
                        )

                null_field_section = ""
                if null_field_hints:
                    null_field_section = (
                        "\n\n🚨 REQUIRED FIELD ERRORS — read carefully:\n"
                        + "\n".join(null_field_hints)
                        + "\nDo NOT call the same tool again with null values. Fill every required field with a real value."
                    )

                # Fast mode: emit a single tight fix-hint when latency matters.
                use_tight_hint = bool(getattr(self, "_fast_execution", False))
                if use_tight_hint:
                    fix_lines = []
                    for e in all_errors_this_round:
                        hint = (e.get("hint") or "").strip()
                        err = (e.get("error") or "").strip()
                        if hint:
                            fix_lines.append(
                                f"• `{e['tool']}` failed: {err[:160]}\n  Fix: {hint[:240]}"
                            )
                        else:
                            fix_lines.append(f"• `{e['tool']}` failed: {err[:200]}")
                    current_messages.append(
                        {
                            "role": "user",
                            "content": (
                                "Tool call failed. Apply ONE targeted fix, then continue:\n"
                                + "\n".join(fix_lines)
                                + null_field_section
                                + network_retry_note
                                + "\n\nRules: fix only the failed argument, do not restart, "
                                "do not re-read what already succeeded, do not repeat the same call."
                            ),
                        }
                    )
                else:
                    current_messages.append(
                        {
                            "role": "user",
                            "content": (
                                "One or more tool calls failed. Self-correct and retry:\n"
                                + "\n".join(retry_lines)
                                + null_field_section
                                + network_retry_note
                                + "\n\nGuidance:\n"
                                "• Wrong node type or parm guess? Call resolve_build_hints() first, then verify_node_type() if needed.\n"
                                "• Wrong parm name? Use safe_set_parameter() — returns close matches on failure.\n"
                                "• Unsure whether the build is visible? Call inspect_display_output().\n"
                                "• After correcting, continue the plan — do NOT restart from scratch.\n"
                                "• Do NOT stop — keep going through the remaining planned steps."
                            ),
                        }
                    )
                if stream_callback:
                    stream_callback("\u200b🔁 Injecting self-correction guidance…\n\n")
                self._emit_progress(
                    stream_callback,
                    "I'm correcting the failed step and continuing from where I left off.",
                )
            else:
                stable_outputs = self._stable_outputs_for_early_completion(
                    request_mode,
                    round_num,
                    round_tool_names,
                    had_errors=False,
                    write_tools=write_tools,
                )
                if not stable_outputs:
                    stable_outputs = self._stable_outputs_near_round_limit(
                        request_mode,
                        round_num,
                        round_tool_names,
                        had_errors=False,
                        write_tools=write_tools,
                    )
                if stable_outputs:
                    self._turn_failed_attempts = dict(failed_attempts)
                    self._finalize_turn_tracking(
                        tool_history, write_tools, mutation_summaries, dry_run
                    )
                    return self._build_round_limit_summary(
                        mutation_summaries,
                        write_tools,
                        output_paths=stable_outputs,
                    )

        self._turn_failed_attempts = dict(failed_attempts)
        self._finalize_turn_tracking(tool_history, write_tools, mutation_summaries, dry_run)

        # HARDENING: Round limit reached — if we have a plan and it's incomplete,
        # attempt one continuation pass instead of giving up.
        if (
            plan_data
            and write_tools
            and not dry_run
            and request_mode == "build"
            and _depth < self._MAX_LOOP_DEPTH
            and not getattr(self, "_exhaustion_continuation_attempted", False)
        ):
            reminder = self._verify_plan_completion(plan_data, tool_history, "")
            if reminder:
                self._exhaustion_continuation_attempted = True
                self.debug_logger.log_system_note(
                    "Round limit reached but plan incomplete — attempting continuation"
                )
                if stream_callback:
                    stream_callback(
                        "\u200b🔁 Round limit reached but task isn't done — continuing…\n\n"
                    )
                continuation_messages = [
                    *list(messages[:2]),  # system + first user message
                    *current_messages[-6:],  # recent context
                    {
                        "role": "system",
                        "content": (
                            f"[ROUND LIMIT CONTINUATION]\n"
                            f"You hit the tool round limit but the task is NOT done.\n"
                            f"Remaining steps:\n{reminder}\n\n"
                            f"Complete ONLY the remaining steps. Do NOT repeat finished work."
                        ),
                    },
                ]
                return self._run_loop(
                    continuation_messages,
                    stream_callback,
                    tool_schemas=tool_schemas,
                    dry_run=dry_run,
                    request_mode=request_mode,
                    plan_data=plan_data,
                    _depth=_depth + 1,
                )

        if write_tools:
            output_paths = []
            snapshot = self._capture_scene_snapshot() if HOU_AVAILABLE else None
            if snapshot:
                output_paths = self._extract_display_output_paths(snapshot)
            return self._build_round_limit_summary(
                mutation_summaries,
                write_tools,
                output_paths=output_paths,
            )
        if getattr(self, "_fast_message_mode", False):
            return (
                "Fast mode round cap reached before a successful scene edit. "
                "Retry with Fast off for a deeper repair loop, or provide the exact node/parameter name."
            )
        return "Max tool rounds reached — some steps may be incomplete."

    # ── Token estimation helper ──────────────────────────────────────
    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Accurate token count via tiktoken (cl100k_base) with heuristic fallback."""
        return count_tokens(text)

    @staticmethod
    def _message_tokens(msg: dict) -> int:
        """Accurate token count for a single message dict via tiktoken."""
        return count_message_tokens(msg)

    _ANCHOR_TAG = "[TASK ANCHOR — REMINDER]"

    def _inject_task_anchor_reminder(self, messages: list) -> list:
        """
        Re-append the user's original goal as a fresh system reminder every
        round so it always sits at peak recency and never gets compressed
        out by _truncate_tool_history. Strips any prior anchor reminders
        first so the message doesn't accumulate.
        """
        anchor = getattr(self, "_task_anchor", None)
        if not anchor:
            return messages
        cleaned = [
            m
            for m in messages
            if not (m.get("role") == "system" and self._ANCHOR_TAG in (m.get("content") or ""))
        ]
        reminder = (
            f"{self._ANCHOR_TAG}\n"
            f"The user's original request for this turn was:\n"
            f"  «{anchor}»\n\n"
            "Rules:\n"
            "1. Every tool call must directly serve this objective. If you "
            "cannot justify a step against the request above, do not run it.\n"
            "2. Do not pivot to unrelated edits, layout fixes, or "
            "improvements the user did not ask for.\n"
            "3. If you discover a problem that genuinely blocks the request "
            "and needs a different approach, STOP calling tools and ASK the "
            "user before changing direction.\n"
            "4. When the request is satisfied, stop and summarize. Do not "
            "keep tool-calling for polish."
        )
        cleaned.append({"role": "system", "content": reminder})
        return cleaned

    def _truncate_tool_history(self, messages: list, max_messages: int = 10) -> list:
        """
        Token-budget-aware context truncation using tiktoken for accuracy.

        Reserves 70% of context window for prompt + history, greedily
        includes messages newest-first until budget exhausted. Individual
        huge tool results (>2000 tokens) are trimmed inline.
        """
        from ._tokenizer import TokenBudget

        if len(messages) > max_messages:
            if messages and messages[0].get("role") == "system":
                tail_keep = max(1, max_messages - 1)
                messages = [messages[0], *messages[-tail_keep:]]
            else:
                messages = messages[-max_messages:]

        context_window = getattr(self.llm, "context_window", None) or self.config.get(
            "context_window", 65536
        )
        budget = TokenBudget(
            context_window=context_window,
            safety_margin=0.70,
            max_single_result=2000,
            min_messages_kept=2,
        )
        if budget.can_fit(messages):
            return messages
        return budget.truncate(messages)

    # ── Tool execution timeout helper ─────────────────────────────────
    def _execute_with_timeout(self, func, timeout_s: float, **kwargs):
        """
        Run *func* with a timeout using threading.Event.

        signal.alarm cannot be used from non-main threads, so we launch the
        work on a daemon thread and wait on an Event with the specified
        timeout.  Returns (result, None) on success or (None, error_msg)
        on timeout / exception.
        """
        result_holder: list = []
        error_holder: list = []
        done_event = threading.Event()

        def _worker():
            try:
                result_holder.append(func(**kwargs))
            except Exception as exc:
                error_holder.append(exc)
            finally:
                done_event.set()

        worker = threading.Thread(target=_worker, daemon=True)
        worker.start()
        finished = done_event.wait(timeout=timeout_s)

        if not finished:
            if hasattr(self, "debug_logger"):
                self.debug_logger.log_tool_timeout(
                    tool_name=getattr(func, "__name__", str(func)),
                    timeout_s=timeout_s,
                )
            return None, (
                f"Tool execution timed out after {timeout_s:.0f}s. "
                "The operation may still be running in the background."
            )

        if error_holder:
            raise error_holder[0]

        return result_holder[0] if result_holder else None, None

    # ── Tool execution (FIX-2: all hou.* on main thread) ─────────────
    def _execute_tool(
        self, tool_name: str, args: dict, stream_callback=None, dry_run: bool = False
    ) -> dict:
        # Intercept common LLM tool name hallucinations
        if tool_name == "connect":
            tool_name = "connect_nodes"

        if tool_name not in TOOL_FUNCTIONS:
            return {"status": "error", "message": f"Unknown tool: {tool_name}"}

        # BUG-3: When the user has turned vision off (vision_enabled=false),
        # capture_pane still executes the expensive screenshot + OpenGL
        # readback. Short-circuit here so disabled vision truly skips the
        # work rather than only hiding the image from the LLM later.
        if tool_name == "capture_pane" and not self._vision_capture_allowed():
            return {
                "status": "skipped",
                "message": "capture_pane skipped: vision is bypassed for this turn.",
                "data": {"image_b64": None},
                "_meta": {"dry_run": dry_run, "vision_disabled": True},
            }

        safety_level = TOOL_SAFETY_TIERS.get(tool_name, "safe")
        started = time.time()

        # ── v11: Schema-based argument validation with self-correction ──
        try:
            args = self._tool_validator.validate(tool_name, args)
        except ToolArgumentError as e:
            correction = self._tool_validator.get_correction_prompt(e)
            return {
                "status": "error",
                "message": f"Argument validation failed: {e}",
                "data": None,
                "_meta": {"dry_run": dry_run, "safety": safety_level},
                "_correction_hint": correction,
            }

        # ── Tool preconditions (cheap pre-call sanity checks) ───────────
        # Uses the cached scene snapshot if one is available; never forces a
        # fresh snapshot because we're on the dispatcher hot path.
        if not dry_run and getattr(self, "preconditions_enabled", True):
            cached_snapshot = (
                self._turn_snapshot_cache.get(self._turn_scene_write_epoch)
                if hasattr(self, "_turn_snapshot_cache")
                else None
            )
            try:
                pre = _preconditions.evaluate(tool_name, args, scene_snapshot=cached_snapshot)
            except Exception as _pre_e:
                # Preconditions must never break tool execution.
                pre = _preconditions.PreconditionResult.passed()
                self.debug_logger.log_system_note(
                    f"[PRECONDITIONS] check raised {_pre_e!r} — passing through."
                )
            if not pre.ok and pre.severity == "block":
                self.debug_logger.log_phase(
                    "precondition",
                    status="block",
                    meta={"tool": tool_name, "reason": pre.message[:200]},
                )
                return {
                    "status": "error",
                    "message": _preconditions.format_failure(pre),
                    "data": None,
                    "_meta": {
                        "dry_run": dry_run,
                        "safety": safety_level,
                        "precondition": True,
                    },
                    "_correction_hint": pre.suggested_fix or pre.message,
                }
            if not pre.ok and pre.severity == "warn":
                self.debug_logger.log_phase(
                    "precondition",
                    status="warn",
                    meta={"tool": tool_name, "reason": pre.message[:200]},
                )

        # ── Active failure-driven blacklist ─────────────────────────────
        # Block exact (tool, args) combinations that already failed recently.
        if not dry_run:
            blocked = self._check_failure_blacklist(tool_name, args)
            if blocked is not None:
                self.debug_logger.log_phase(
                    "failure_blacklist",
                    status="block",
                    meta={"tool": tool_name},
                )
                return blocked

        # ── Circuit breaker (per-tool) ───────────────────────────────────
        # Refuse to call a tool that has tripped the breaker until cool-down.
        if not dry_run and getattr(self, "tool_retry_enabled", False):
            breaker_open, breaker_reason = self._circuit_breaker.is_open(tool_name)
            if breaker_open:
                self.debug_logger.log_phase(
                    "circuit_breaker",
                    status="open",
                    meta={"tool": tool_name, "reason": breaker_reason[:160]},
                )
                return {
                    "status": "error",
                    "message": breaker_reason,
                    "data": None,
                    "_meta": {"circuit_open": True, "tool": tool_name},
                    "_correction_hint": (
                        "This tool is in a bad state and is paused. "
                        "Try a different approach or wait for cool-down."
                    ),
                }

        if not dry_run and tool_name in READ_ONLY_TOOLS and tool_name != "capture_pane":
            cached = self._get_cached_tool_result(tool_name, args)
            if cached is not None:
                cached.setdefault("_meta", {})
                cached["_meta"]["dry_run"] = dry_run
                cached["_meta"]["safety"] = safety_level
                cached["_meta"]["cached"] = True
                cached["_meta"]["duration_ms"] = int((time.time() - started) * 1000)
                self._annotate_turn_valid_result(tool_name, cached, cached=True)
                return cached
        if not dry_run and tool_name == "capture_pane":
            capture_cache_key = self._capture_cache_key(args)
            if capture_cache_key:
                cached = self._turn_capture_cache.get(capture_cache_key)
                if cached is not None:
                    cached = json.loads(json.dumps(cached))
                    cached.setdefault("_meta", {})
                    cached["_meta"]["dry_run"] = dry_run
                    cached["_meta"]["safety"] = safety_level
                    cached["_meta"]["cached"] = True
                    cached["_meta"]["duration_ms"] = int((time.time() - started) * 1000)
                    return cached

        is_write_tool = tool_name not in READ_ONLY_TOOLS
        if not dry_run and is_write_tool:
            self._ensure_turn_checkpoint(stream_callback=stream_callback)

        if not dry_run and safety_level in {"confirm", "dangerous"}:
            if tool_name == "delete_node":
                node_path = args.get("node_path", "?")
                desc = f"Delete node: {node_path}"
            elif tool_name == "disconnect_node":
                node_path = args.get("node_path", "?")
                desc = f"Disconnect input {args.get('input_index', 0)} of: {node_path}"
            elif tool_name == "find_and_replace_parameter":
                desc = (
                    f"Find/replace '{args.get('search_value', '')}' -> "
                    f"'{args.get('replace_value', '')}' in {args.get('root_path', '?')}"
                )
            elif tool_name == "convert_to_hda":
                desc = (
                    f"Convert {args.get('node_path', '?')} into HDA '{args.get('hda_name', '?')}'"
                )
            elif tool_name == "export_geometry":
                desc = f"Export geometry from {args.get('node_path', '?')} to {args.get('file_path', '?')}"
            else:
                code = (args.get("code", "") or "").strip()
                first_line = code.splitlines()[0] if code else ""
                preview = first_line[:120] + ("..." if len(first_line) > 120 else "")
                desc = "Execute arbitrary Python in the Houdini session"
                if preview:
                    desc += f": {preview}"
            if stream_callback:
                label = "Dangerous action" if safety_level == "dangerous" else "Confirming action"
                stream_callback(f"\u200b⚠️  {label}: {desc}…\n\n")
            if not self._request_confirmation(desc):
                return {
                    "status": "cancelled",
                    "message": f"User denied: {desc}",
                    "data": None,
                }

        if dry_run and tool_name not in READ_ONLY_TOOLS:
            simulated = self._simulate_dry_run_result(tool_name, args, safety_level)
            simulated.setdefault("_meta", {})
            simulated["_meta"]["duration_ms"] = int((time.time() - started) * 1000)
            return simulated

        try:
            # FIX-2: Always use _hou_call — never raw thread calls
            is_read = tool_name in READ_ONLY_TOOLS
            hou_timeout_s = self._tool_hou_timeout(tool_name, is_read=is_read)

            # ── Retry loop for transient transport errors ───────────────
            attempt = 0
            attempts_used = 1
            while True:
                attempt += 1
                result = self._hou_call(
                    TOOL_FUNCTIONS[tool_name],
                    _timeout_s=hou_timeout_s,
                    **args,
                )
                sanitized = self._sanitize(result)
                if not isinstance(sanitized, dict):
                    sanitized = {"status": "ok", "message": "OK", "data": sanitized}
                if not getattr(self, "tool_retry_enabled", False):
                    attempts_used = attempt
                    break
                if not self._retry_policy.should_retry(attempt, sanitized, is_read_only=is_read):
                    attempts_used = attempt
                    break
                delay = self._retry_policy.delay_for(attempt)
                self.debug_logger.log_phase(
                    "tool_retry",
                    status="retry",
                    meta={
                        "tool": tool_name,
                        "attempt": attempt,
                        "delay_s": round(delay, 2),
                        "err": str(sanitized.get("message", ""))[:120],
                    },
                )
                time.sleep(delay)
            sanitized.setdefault("_meta", {})
            sanitized["_meta"]["dry_run"] = dry_run
            sanitized["_meta"]["safety"] = safety_level
            sanitized["_meta"]["duration_ms"] = int((time.time() - started) * 1000)
            if attempts_used > 1:
                sanitized["_meta"]["retry_attempts"] = attempts_used

            # Update circuit breaker based on final outcome.
            if getattr(self, "tool_retry_enabled", False):
                if sanitized.get("status") == "ok":
                    self._circuit_breaker.record_success(tool_name)
                elif sanitized.get("status") == "error":
                    self._circuit_breaker.record_failure(tool_name)
            if sanitized.get("status") == "error" and tool_name in {
                "safe_set_parameter",
                "set_parameter",
            }:
                recovered = self._attempt_parameter_recovery(tool_name, args, sanitized)
                if recovered:
                    sanitized = recovered
                    sanitized.setdefault("_meta", {})
                    sanitized["_meta"]["dry_run"] = dry_run
                    sanitized["_meta"]["safety"] = safety_level
                    sanitized["_meta"]["duration_ms"] = int((time.time() - started) * 1000)
            if tool_name == "capture_pane":
                include_vision = self._turn_capture_pane_analyses < self.max_capture_pane_per_turn
                enriched = self._enrich_capture_result(
                    sanitized,
                    stream_callback=stream_callback,
                    include_vision=include_vision,
                )
                if include_vision and enriched.get("status") == "ok":
                    self._turn_capture_pane_analyses += 1
                capture_cache_key = self._capture_cache_key(args)
                if capture_cache_key:
                    self._turn_capture_cache[capture_cache_key] = json.loads(json.dumps(enriched))
                return enriched
            if sanitized.get("status") == "ok":
                if tool_name in READ_ONLY_TOOLS:
                    self._annotate_turn_valid_result(tool_name, sanitized, cached=False)
                    self._store_cached_tool_result(tool_name, args, sanitized)
                elif not dry_run:
                    self._mark_scene_dirty(tool_name)
                    self._tool_cache.clear()

            # ── v11: Repair Critic evaluates errors ──
            if self._critic and sanitized.get("status") == "error":
                verdict = self._critic.evaluate_tool_result(tool_name, args, sanitized)
                if not verdict["ok"] and verdict.get("fix_action"):
                    sanitized["_critic_verdict"] = verdict
                    sanitized["_correction_hint"] = (
                        f"Critic diagnosis: {verdict['issue']}\n"
                        f"Suggested fix: {verdict['fix_action']}"
                    )

            return sanitized
        except Exception as e:
            error_text = str(e)
            is_main_thread_timeout = self._is_houdini_main_thread_timeout(error_text)
            return {
                "status": "error",
                "message": error_text,
                "data": None,
                "_meta": {
                    "dry_run": dry_run,
                    "safety": safety_level,
                    "duration_ms": int((time.time() - started) * 1000),
                    "timed_out": bool(is_main_thread_timeout),
                    "error_code": ("houdini_main_thread_timeout" if is_main_thread_timeout else ""),
                },
            }

    def _sanitize(self, val):
        if isinstance(val, dict):
            return {k: self._sanitize(v) for k, v in val.items()}
        if isinstance(val, list):
            return [self._sanitize(v) for v in val]
        t = str(type(val))
        if "hou." in t:
            if hasattr(val, "asTuple"):
                return list(val)
            if hasattr(val, "path"):
                return val.path()
            return str(val)
        return val

    def _select_loop_task(
        self, request_mode: str, round_num: int, consecutive_errors: int
    ) -> str | None:
        if request_mode == "build":
            if consecutive_errors == 0 and round_num < self.fast_build_rounds:
                return "build"
            return None
        if request_mode == "debug":
            if consecutive_errors == 0 and round_num < self.fast_debug_rounds:
                return "debug"
            return None
        return None

    def _select_loop_timeout(self, request_mode: str, round_num: int, has_writes: bool) -> float:
        base_timeout = max(15.0, float(self.config.get("tool_loop_llm_timeout_s", 75.0)))
        late_timeout = max(15.0, float(self.config.get("late_round_llm_timeout_s", 45.0)))
        if has_writes and round_num >= max(self.fast_build_rounds, self.fast_debug_rounds):
            return min(base_timeout, late_timeout)
        if has_writes and round_num >= 6:
            return min(base_timeout, late_timeout)
        return base_timeout

    def _tool_attempt_signature(self, tool_name: str, args: dict) -> str:
        safe_args = self._sanitize(args)
        return f"{tool_name}:{json.dumps(safe_args, sort_keys=True, default=str)}"

    def _duplicate_failure_result(self, tool_name: str, previous_error: str) -> dict:
        return {
            "status": "error",
            "message": (
                "Skipped duplicate failing call to keep the turn fast. "
                f"Previous {tool_name} error: {previous_error[:180]}"
            ),
            "data": None,
            "_meta": {
                "duplicate_failure": True,
                "safety": TOOL_SAFETY_TIERS.get(tool_name, "safe"),
            },
        }

    @staticmethod
    def _coerce_param_retry_value(parm_name: str, value):
        if not isinstance(value, (list, tuple)):
            return value
        values = list(value)
        if not values:
            return value
        suffix_map = {"x": 0, "y": 1, "z": 2, "w": 3}
        suffix = str(parm_name or "").strip().lower()[-1:] if parm_name else ""
        if suffix in suffix_map and len(values) > suffix_map[suffix]:
            return values[suffix_map[suffix]]
        if len(values) == 1:
            return values[0]
        if str(parm_name or "").strip().lower() in {"scale", "uniformscale", "pscale"}:
            return values[0]
        return value

    @staticmethod
    def _parm_name_similarity(a: str, b: str) -> float:
        return difflib.SequenceMatcher(None, str(a or "").lower(), str(b or "").lower()).ratio()

    @staticmethod
    def _parm_base_name(name: str) -> str:
        text = re.sub(r"[^a-z0-9]+", "", str(name or "").lower())
        return re.sub(r"[xyzw]$", "", text)

    @classmethod
    def _parm_names_semantically_compatible(cls, requested: str, candidate: str) -> bool:
        req = str(requested or "").strip().lower()
        cand = str(candidate or "").strip().lower()
        if not req or not cand:
            return False
        if req == cand:
            return True
        if cls._parm_base_name(req) and cls._parm_base_name(req) == cls._parm_base_name(cand):
            return True
        req_tokens = set(re.findall(r"[a-z]+", req))
        cand_tokens = set(re.findall(r"[a-z]+", cand))
        if not req_tokens or not cand_tokens:
            return False
        return bool(req_tokens & cand_tokens)

    @staticmethod
    def _is_auto_recovery_unsafe_parm(parm_name: str, parm_meta: dict | None = None) -> bool:
        name = str(parm_name or "").strip().lower()
        if not name:
            return True
        if "ramp" in name:
            return True
        if any(ch in name for ch in ("[", "]", "#")):
            return True
        if re.search(r"\d+$", name):
            return True
        type_text = ""
        if isinstance(parm_meta, dict):
            type_text = str(parm_meta.get("type", "") or "").lower()
        risky_type_tokens = ("ramp", "folder", "multiparm", "multi parm", "separator")
        return any(token in type_text for token in risky_type_tokens)

    @staticmethod
    def _extract_inline_parm_hint(err_lower: str, requested: str) -> str | None:
        """Pull a candidate parm name out of the failure message when Houdini
        already surfaced one ("Did you mean 'xxx'?" / "Similar: xxx, yyy").

        Returns the candidate when it looks like a valid parameter identifier
        and differs from the requested name. None otherwise.
        """
        patterns = [
            r"did you mean ['\"]?([a-zA-Z_][a-zA-Z0-9_]*)['\"]?",
            r"similar (?:parameters|parms)?:?\s*['\"]?([a-zA-Z_][a-zA-Z0-9_]*)['\"]?",
            r"closest (?:match|parm)?:?\s*['\"]?([a-zA-Z_][a-zA-Z0-9_]*)['\"]?",
        ]
        for pat in patterns:
            m = re.search(pat, err_lower)
            if m:
                candidate = m.group(1)
                if candidate and candidate != requested.lower():
                    return candidate
        return None

    def _attempt_parameter_recovery(
        self,
        tool_name: str,
        args: dict,
        failed_result: dict,
    ) -> dict | None:
        node_path = args.get("node_path")
        requested = str(args.get("parm_name", "") or "").strip()
        if (
            tool_name not in {"safe_set_parameter", "set_parameter"}
            or not node_path
            or not requested
            or "get_node_parameters" not in TOOL_FUNCTIONS
        ):
            return None

        err = str((failed_result or {}).get("message", "") or "").lower()
        recoverable = (
            "parameter '" in err
            or "parm '" in err
            or "invalid size" in err
            or "unsupported type" in err
            or "wrong number or type of arguments" in err
        )
        if not recoverable:
            return None

        # BUG-2: If the error message itself carries an explicit suggestion
        # (e.g. "Did you mean 'tx'?" or "Available: tx, ty, tz"), resolve
        # locally before round-tripping through another get_node_parameters
        # Houdini call — the extra call can block 100–300 ms and is wholly
        # redundant when the error already told us the answer.
        inline_hint = self._extract_inline_parm_hint(err, requested)
        if inline_hint:
            new_args = dict(args)
            new_args["parm_name"] = inline_hint
            try:
                recovered_fn = TOOL_FUNCTIONS.get(tool_name)
                if recovered_fn is not None:
                    recovered = self._sanitize(self._hou_call(recovered_fn, **new_args))
                    if recovered.get("status") == "ok":
                        recovered["_recovered_from"] = requested
                        recovered["_recovered_to"] = inline_hint
                        return recovered
            except Exception:
                pass

        try:
            probe = self._sanitize(
                self._hou_call(
                    TOOL_FUNCTIONS["get_node_parameters"],
                    node_path=node_path,
                    compact=False,
                )
            )
        except Exception:
            return None
        if probe.get("status") != "ok":
            return None
        params = (probe.get("data") or {}).get("parameters") or {}
        if not isinstance(params, dict) or not params:
            return None
        names = list(params.keys())
        requested_meta = params.get(requested) if isinstance(params.get(requested), dict) else {}
        if self._is_auto_recovery_unsafe_parm(requested, requested_meta):
            return None

        target = requested
        if target not in names:
            suffix = target[-1:].lower()
            if suffix in {"x", "y", "z", "w"}:
                base = target[:-1]
                if base in names:
                    target = base
            if target not in names:
                close = difflib.get_close_matches(
                    requested,
                    names,
                    n=3,
                    cutoff=max(0.8, self.auto_param_recovery_similarity_cutoff - 0.08),
                )
                for candidate in close:
                    candidate_meta = (
                        params.get(candidate) if isinstance(params.get(candidate), dict) else {}
                    )
                    if self._is_auto_recovery_unsafe_parm(candidate, candidate_meta):
                        continue
                    if not self._parm_names_semantically_compatible(requested, candidate):
                        continue
                    similarity = self._parm_name_similarity(requested, candidate)
                    base_match = self._parm_base_name(requested) == self._parm_base_name(candidate)
                    if not base_match and similarity < self.auto_param_recovery_similarity_cutoff:
                        continue
                    target = candidate
                    break
        if target not in names:
            return None
        target_meta = params.get(target) if isinstance(params.get(target), dict) else {}
        if self._is_auto_recovery_unsafe_parm(target, target_meta):
            return None
        if target != requested:
            if not self._parm_names_semantically_compatible(requested, target):
                return None
            similarity = self._parm_name_similarity(requested, target)
            base_match = self._parm_base_name(requested) == self._parm_base_name(target)
            if not base_match and similarity < self.auto_param_recovery_similarity_cutoff:
                return None

        coerced = self._coerce_param_retry_value(target, args.get("value"))
        if isinstance(args.get("value"), (list, tuple)) and len(args.get("value")) > 1:
            target_type = str((target_meta or {}).get("type", "") or "").lower()
            if (
                "tuple" not in target_type
                and not re.search(r"[xyzw]$", target.lower())
                and target.lower() not in {"scale", "uniformscale", "pscale"}
            ):
                return None
        retry_args = {
            "node_path": node_path,
            "parm_name": target,
            "value": coerced,
        }
        if retry_args["parm_name"] == args.get("parm_name") and retry_args["value"] == args.get(
            "value"
        ):
            return None

        try:
            retried = self._sanitize(self._hou_call(TOOL_FUNCTIONS[tool_name], **retry_args))
        except Exception:
            return None
        if retried.get("status") != "ok":
            return None

        retried.setdefault("_meta", {})
        retried["_meta"]["auto_param_recovery"] = True
        retried["_meta"]["auto_recovered_from"] = requested
        retried["_meta"]["auto_recovered_to"] = target
        retried["message"] = (
            f"AUTO_RECOVER: {node_path}/{requested} -> {target}; "
            f"retried with Houdini-inspected parameters. {retried.get('message', '')}"
        ).strip()
        self.debug_logger.log_system_note(
            f"Auto parameter recovery succeeded for {node_path}: {requested} -> {target}"
        )
        return retried

    def _should_use_local_response_fallback(
        self,
        error_text: str,
        write_tools: list[str],
        mutation_summaries: list[str],
        dry_run: bool = False,
    ) -> bool:
        if dry_run or not write_tools:
            return False
        if not mutation_summaries:
            return False
        lower = str(error_text or "").lower()
        return any(
            marker in lower
            for marker in (
                "timed out",
                "timeout",
                "cannot reach ollama",
                "cannot reach openai",
                "service unavailable",
                "overloaded",
                "connection refused",
                "connection reset",
                "rate limit",
                "429",
                "http 500",
                # HARDENING: additional transient error patterns
                "econnreset",
                "broken pipe",
                "incomplete chunked",
                "read timed out",
            )
        )

    def _build_local_response_fallback(
        self,
        mutation_summaries: list[str],
        write_tools: list[str],
        error_text: str,
        dry_run: bool = False,
    ) -> str:
        summary = self._format_mutation_summary(mutation_summaries, dry_run=dry_run)
        if not summary and write_tools:
            summary = "[SCENE DIFF]\n- Applied write tools: " + ", ".join(
                list(dict.fromkeys(write_tools))[:8]
            )
        if dry_run:
            prefix = (
                "The planning pass completed, but the final assistant response timed out. "
                "Here is the planned scene diff."
            )
        else:
            prefix = (
                "Scene edits were applied, but the final assistant response timed out. "
                "Here is the confirmed change summary."
            )
        if error_text:
            prefix += f" Backend issue: {str(error_text).strip()[:180]}"
        return (prefix + ("\n\n" + summary if summary else "")).strip()

    @staticmethod
    def _round_has_substantive_writes(round_tool_names: list[str]) -> bool:
        return any(
            tool_name not in READ_ONLY_TOOLS
            and tool_name not in NON_SUBSTANTIVE_COMPLETION_WRITE_TOOLS
            for tool_name in (round_tool_names or [])
        )

    def _build_round_limit_summary(
        self,
        mutation_summaries: list[str],
        write_tools: list[str],
        output_paths: list[str] | None = None,
    ) -> str:
        summary = self._format_mutation_summary(mutation_summaries, dry_run=False)
        if not summary and write_tools:
            summary = "[SCENE DIFF]\n- Applied write tools: " + ", ".join(
                list(dict.fromkeys(write_tools))[:8]
            )
        # Filter out HoudiniMind scratch namespaces — they confuse the user.
        outputs = [p for p in (output_paths or []) if not self._is_scratch_path(p)]

        # Surface verification FAIL state explicitly — without this, a build
        # that hit round limit with verification problems was reported as
        # "visible output is present" with no hint anything was wrong.
        verification_report = self._last_turn_verification_report or {}
        verification_text = self._last_turn_verification_text or ""
        verification_failed = verification_report.get("status") == "fail"

        if verification_failed:
            prefix = "Scene edits were applied but verification FAILED. The build is not complete."
        elif outputs:
            prefix = (
                "Scene edits were applied and a visible output is present. "
                f"Visible output: {', '.join(outputs[:4])}."
            )
        else:
            prefix = "Scene edits were applied before the agent hit its round limit."

        parts = [prefix]
        if verification_failed and verification_text:
            parts.append(verification_text)
        if summary:
            parts.append(summary)
        return "\n\n".join(parts).strip()

    def _build_grounded_turn_response(
        self,
        request_mode: str,
        response_text: str | None,
        dry_run: bool = False,
    ) -> str | None:
        if request_mode not in {"build", "debug"}:
            return response_text

        lower = (response_text or "").lower()
        if "task cancelled" in lower or "agent error" in lower:
            return response_text
        if self._is_transient_llm_failure(response_text):
            return response_text

        verification_report = self._last_turn_verification_report or {}
        outputs = list(verification_report.get("outputs") or self._last_turn_output_paths or [])
        scene_diff_text = self._last_turn_scene_diff_text or self._format_mutation_summary(
            self._last_turn_mutation_summaries,
            dry_run=dry_run,
        )
        verification_text = self._last_turn_verification_text or ""

        if not dry_run and not self._last_turn_write_tools and not verification_text:
            return response_text

        # Count nodes created from scene diff for a richer summary
        _nodes_created = 0
        if scene_diff_text:
            for _ln in scene_diff_text.splitlines():
                if _ln.strip().startswith("Created:"):
                    _nodes_created = len(_ln.split(","))
                    break

        # How many tool steps were taken this turn
        _step_count = len(self._last_turn_write_tools or [])

        lines = []
        if dry_run:
            lines.append("Dry run complete. No scene edits were applied.")
        elif verification_report.get("status") == "pass":
            if request_mode == "build":
                lines.append("Build completed successfully.")
                _details = []
                if _nodes_created:
                    _details.append(
                        f"{_nodes_created} node{'s' if _nodes_created != 1 else ''} created"
                    )
                if _step_count:
                    _details.append(f"{_step_count} step{'s' if _step_count != 1 else ''}")
                if _details:
                    lines.append("Build details: " + ", ".join(_details) + ".")
            else:
                lines.append("Scene repair completed successfully.")
        elif verification_report.get("status") == "fail":
            lines.append("Scene edits were applied, but verification still found issues.")
        elif self._last_turn_write_tools:
            lines.append("Scene edits were applied.")

        if outputs and not dry_run:
            lines.append("Visible output: " + ", ".join(outputs[:4]))

        pass_summary_added = False
        if verification_report.get("status") == "pass":
            summary = str(verification_report.get("summary", "") or "").strip()
            if summary:
                lines.append(summary)
                pass_summary_added = True

        blocks = []
        if verification_report.get("status") == "fail" and verification_text:
            blocks.append(verification_text)
        elif (
            verification_report.get("status") != "fail"
            and verification_text
            and not pass_summary_added
        ):
            lines.append(verification_text.splitlines()[0])

        if scene_diff_text:
            blocks.append(scene_diff_text)

        grounded = "\n\n".join(
            [item.strip() for item in lines if str(item).strip()]
            + [item.strip() for item in blocks if str(item).strip()]
        ).strip()
        return grounded or response_text

    def _stable_outputs_near_round_limit(
        self,
        request_mode: str,
        round_num: int,
        round_tool_names: list[str],
        had_errors: bool,
        write_tools: list[str],
    ) -> list[str]:
        if request_mode not in {"build", "debug"}:
            return []
        if had_errors or not write_tools:
            return []
        if round_num < max(2, self.max_tool_rounds - 2):
            return []
        if self._round_has_substantive_writes(round_tool_names):
            return []
        if not (
            self._turn_tool_counts.get("inspect_display_output", 0)
            or self._turn_tool_counts.get("finalize_sop_network", 0)
            or self._turn_tool_counts.get("set_display_flag", 0)
        ):
            return []
        snapshot = self._capture_scene_snapshot()
        return self._extract_display_output_paths(snapshot) if snapshot else []

    def _stable_outputs_for_early_completion(
        self,
        request_mode: str,
        round_num: int,
        round_tool_names: list[str],
        had_errors: bool,
        write_tools: list[str],
    ) -> list[str]:
        if not self.early_completion_exit_enabled:
            return []
        if request_mode not in {"build", "debug"}:
            return []
        if had_errors or not write_tools:
            return []
        if round_num < self.early_completion_min_round:
            return []
        if self._round_has_substantive_writes(round_tool_names):
            return []
        completion_probe_seen = bool(
            self._turn_tool_counts.get("set_display_flag", 0)
            or self._turn_tool_counts.get("finalize_sop_network", 0)
            or self._turn_tool_counts.get("inspect_display_output", 0)
            or self._turn_tool_counts.get("capture_pane", 0)
            or (
                self._turn_tool_counts.get("get_all_errors", 0)
                and (
                    self._turn_tool_counts.get("get_geometry_attributes", 0)
                    or self._turn_tool_counts.get("get_node_inputs", 0)
                    or self._turn_tool_counts.get("get_scene_summary", 0)
                    or self._turn_tool_counts.get("get_bounding_box", 0)
                )
            )
        )
        if not completion_probe_seen:
            return []

        snapshot = self._capture_scene_snapshot()
        if not snapshot:
            return []
        outputs = self._extract_display_output_paths(snapshot)
        if not outputs:
            return []
        if request_mode == "build" and not (
            self._turn_tool_counts.get("set_display_flag", 0)
            or self._turn_tool_counts.get("finalize_sop_network", 0)
            or self._turn_tool_counts.get("inspect_display_output", 0)
            or (
                self._turn_tool_counts.get("get_all_errors", 0)
                and self._turn_tool_counts.get("get_geometry_attributes", 0)
            )
        ):
            return []
        return outputs

    # ── Build retry helpers ───────────────────────────────────────────
    def _should_retry_build_turn(
        self, request_mode: str, response_text: str | None, dry_run: bool = False
    ) -> bool:
        if request_mode != "build" or not HOU_AVAILABLE or dry_run:
            return False
        if self._last_turn_write_tools:
            return False
        if not response_text:
            return False
        lower = response_text.lower()
        return not (
            "task cancelled" in lower
            or "agent error" in lower
            or self._is_transient_llm_failure(response_text)
        )

    @staticmethod
    def _is_transient_llm_failure(response_text: str | None) -> bool:
        lower = (response_text or "").lower()
        return any(
            marker in lower
            for marker in (
                "cannot reach ollama",
                "cannot reach openai",
                "connection refused",
                "connection reset",
                "timed out",
                "timeout",
                "failed to establish a new connection",
                "actively refused",
                "address already in use",
                "only one usage of each socket address",
                "winerror 10048",
                "winerror 10061",
                "temporary failure",
                "temporarily unavailable",
                "service unavailable",
                "overloaded",
                "too many requests",
                "429",
                "please wait",
                "rate limit",
                # HARDENING: additional transient patterns
                "http 500",
                "econnreset",
                "broken pipe",
                "incomplete chunked",
                "read timed out",
            )
        )

    @staticmethod
    def _looks_like_terminal_tool_failure(response_text: str | None) -> bool:
        lower = (response_text or "").strip().lower()
        if not lower:
            return False
        terminal_prefixes = (
            "max tool rounds reached",
            "stopped after ",
            "stopped:",
            "argument validation failed:",
            "tool execution timed out",
            "unknown tool:",
        )
        return (
            lower.startswith(terminal_prefixes)
            or "consecutive tool failures" in lower
            or "some steps may be incomplete" in lower
        )

    def _reconcile_final_response_after_verification(
        self, response_text: str | None, verification_report: dict | None
    ) -> str | None:
        if not verification_report or verification_report.get("status") != "pass":
            return response_text
        if not self._looks_like_terminal_tool_failure(response_text):
            return response_text
        if self._is_transient_llm_failure(response_text):
            return response_text
        lower = (response_text or "").lower()
        if "task cancelled" in lower or "agent error" in lower:
            return response_text
        outputs = verification_report.get("outputs") or self._last_turn_output_paths or []
        output_text = f" Visible output: {', '.join(outputs[:4])}." if outputs else ""
        return (
            "Completed the scene update successfully. "
            "Verification passed for the current network state." + output_text
        ).strip()

    def _build_retry_message(self, user_message: str) -> str:
        return (
            "The previous response did not make any concrete scene edits for a BUILD request.\n"
            f"Original request: {user_message}\n\n"
            "Self-correct now:\n"
            "1. Do not return a tutorial or generic workflow summary.\n"
            "2. Use scene-editing tools to create or modify the requested result.\n"
            "3. If execution is blocked, report the exact blocker from tool output.\n"
            "4. Your final reply must mention the concrete node paths or parameters changed.\n"
            "5. If you created SOP geometry, finish on a visible merged OUT node."
        )

    def _tool_cache_key(self, tool_name: str, args: dict) -> str | None:
        if tool_name not in CACHE_TTL:
            return None
        try:
            return f"{tool_name}:{json.dumps(args, sort_keys=True, default=str)}"
        except Exception:
            return None

    def _capture_cache_key(self, args: dict) -> str | None:
        try:
            return (
                f"capture:{self._turn_scene_write_epoch}:"
                f"{json.dumps(args or {}, sort_keys=True, default=str)}"
            )
        except Exception:
            return None

    def _get_cached_tool_result(self, tool_name: str, args: dict) -> dict | None:
        cache_key = self._tool_cache_key(tool_name, args)
        if not cache_key:
            return None
        # HARDENING: read under lock — _on_scene_event can mutate _tool_cache
        # from a Houdini callback thread at any time.
        with self._tool_cache_lock:
            entry = self._tool_cache.get(cache_key)
            if not entry:
                # OPT-4: log cache miss
                self.debug_logger.log_cache_event(tool_name, hit=False)
                return None
            if (time.time() - entry["ts"]) > CACHE_TTL[tool_name]:
                self._tool_cache.pop(cache_key, None)
                # OPT-4: expired = miss
                self.debug_logger.log_cache_event(tool_name, hit=False, meta={"reason": "expired"})
                return None
            # OPT-4: log cache hit
            self.debug_logger.log_cache_event(tool_name, hit=True)
            try:
                return json.loads(json.dumps(entry["result"]))
            except Exception:
                return entry["result"]

    def _annotate_turn_valid_result(
        self, tool_name: str, result: dict, cached: bool = False
    ) -> None:
        if tool_name not in CACHE_TTL or not isinstance(result, dict):
            return
        if result.get("status") != "ok":
            return
        note = (
            f"[NOTE: This {tool_name} result is valid for this turn. "
            f"Do not call {tool_name}() again unless you modify the scene or need different arguments.]"
        )
        if cached:
            note = "[NOTE: Returned from the turn cache. " + note[len("[NOTE: ") :]
        message = str(result.get("message") or "OK")
        if note in message:
            return
        result["message"] = f"{message}\n{note}".strip()

    def _store_cached_tool_result(self, tool_name: str, args: dict, result: dict) -> None:
        cache_key = self._tool_cache_key(tool_name, args)
        if not cache_key:
            return
        with self._tool_cache_lock:
            self._tool_cache[cache_key] = {"ts": time.time(), "result": result}

    _GLOBAL_SCOPE_CACHED_TOOLS = frozenset(
        {
            "get_scene_summary",
            "get_all_errors",
            "get_hip_info",
            "list_takes",
            "list_installed_hdas",
            "get_memory_usage",
            "list_material_assignments",
        }
    )

    def _invalidate_cache_for_node(self, node_path: str) -> int:
        if not node_path or not self._tool_cache:
            return 0
        path = str(node_path)
        parent = path.rsplit("/", 1)[0] if "/" in path else ""
        try:
            quoted_self = json.dumps(path)
            quoted_parent = json.dumps(parent) if parent else None
        except Exception:
            return 0
        removed = 0
        with self._tool_cache_lock:
            for key in list(self._tool_cache.keys()):
                tool_name = key.split(":", 1)[0]
                if tool_name in self._GLOBAL_SCOPE_CACHED_TOOLS:
                    self._tool_cache.pop(key, None)
                    removed += 1
                    continue
                if quoted_self in key or (quoted_parent and quoted_parent in key):
                    self._tool_cache.pop(key, None)
                    removed += 1
        if removed:
            self._scene_event_invalidations += removed
            try:
                self.debug_logger.log_cache_event(
                    "scene_event_invalidate",
                    hit=False,
                    meta={"node_path": path, "removed": removed},
                )
            except Exception:
                pass
        return removed

    _SCENE_MUTATING_EVENTS = frozenset(
        {
            "ChildCreated",
            "ChildDeleted",
            "NameChanged",
            "FlagChanged",
            "InputRewired",
            "ParmTupleChanged",
        }
    )

    def _on_scene_event(self, category: str, data: dict) -> None:
        if category != "node":
            if category == "hip_file":
                with self._tool_cache_lock:
                    self._tool_cache.clear()
            return
        event_name = str((data or {}).get("event") or "")
        if event_name not in self._SCENE_MUTATING_EVENTS:
            return
        node_path = str((data or {}).get("node_path") or "")
        if node_path:
            self._invalidate_cache_for_node(node_path)

    def _register_scene_event_listener(self) -> None:
        if not HOU_AVAILABLE or self._scene_event_hooks is not None:
            return
        try:
            from ..bridge.event_hooks import EventHooks

            hooks = EventHooks(on_event=self._on_scene_event, track_parm_changes=True)
            hooks.register()
            self._scene_event_hooks = hooks
        except Exception as e:
            print(f"[HoudiniMind] Scene-event cache invalidation unavailable: {e}")

    # ── Cross-turn error memory ───────────────────────────────────────
    def _failure_memory_path(self) -> str:
        try:
            import os as _os

            data_dir = self.config.get("data_dir") or "data"
            return _os.path.join(data_dir, "db", "failure_memory.json")
        except Exception:
            return ""

    def _load_cross_turn_failures(self) -> None:
        if not bool(self.config.get("persist_failure_memory", True)):
            return
        path = self._failure_memory_path()
        if not path:
            return
        try:
            import os as _os

            if not _os.path.isfile(path):
                return
            with open(path, encoding="utf-8") as f:
                payload = json.load(f)
            entries = payload.get("entries") or []
            for e in entries:
                tokens = e.get("request_tokens")
                if isinstance(tokens, list):
                    e["request_tokens"] = set(tokens)
                elif not isinstance(tokens, set):
                    e["request_tokens"] = set()
            self._cross_turn_failures = entries[-30:]  # HARDENING: raised cap from 15 to 30
        except Exception:
            pass

    def _save_cross_turn_failures(self) -> None:
        if not bool(self.config.get("persist_failure_memory", True)):
            return
        path = self._failure_memory_path()
        if not path or not self._cross_turn_failures:
            return
        try:
            import os as _os

            _os.makedirs(_os.path.dirname(path), exist_ok=True)
            payload = {
                "_version": 2,
                "entries": [
                    {
                        "tool": e.get("tool", ""),
                        "error": e.get("error", ""),
                        "request_tokens": sorted(e.get("request_tokens") or []),
                        "turn": int(e.get("turn", 0) or 0),
                        # HARDENING v2: persist enriched failure context
                        "failed_args": e.get("failed_args") or {},
                        "successful_tools": e.get("successful_tools") or [],
                    }
                    for e in self._cross_turn_failures[-30:]
                ],
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f)
        except Exception:
            pass

    def _store_cross_turn_failures(self, user_message: str) -> None:
        """Persist this turn's tool failures into the session-level failure log."""
        if not self._turn_failed_attempts:
            return
        request_tokens = set(_query_terms(user_message))
        for sig, entry in self._turn_failed_attempts.items():
            self._cross_turn_failures.append(
                {
                    "tool": entry.get("tool", sig.split(":")[0]),
                    "error": entry.get("message", "unknown error")[:120],
                    "request_tokens": request_tokens,
                    "turn": self._turn_index,
                    # HARDENING: store exact args that failed so we warn precisely
                    "failed_args": {k: str(v)[:60] for k, v in (entry.get("args") or {}).items()},
                    # HARDENING: store what DID work so far in this turn
                    "successful_tools": list(dict.fromkeys(self._last_turn_write_tools or []))[:8],
                }
            )
        # HARDENING: raised cap from 15 to 30 for long sessions
        self._cross_turn_failures = self._cross_turn_failures[-30:]
        self._save_cross_turn_failures()

    def _format_unresolved_contract_banner(self) -> str:
        """If the active task contract still has unresolved issues, return a banner.

        Reads from ``self._last_turn_verification_report`` (populated by the
        verification suite). Empty string when there's nothing to flag.
        """
        contract = getattr(self, "_active_task_contract", None)
        if not contract:
            return ""
        report = getattr(self, "_last_turn_verification_report", None) or {}
        issues = report.get("issues") or []
        if not issues:
            return ""
        # Match contract-tagged issues by title prefix (used by both bespoke and
        # generic verifiers) so we don't flag unrelated repair issues.
        prefix = (contract.title or contract.contract_id or "").strip()
        contract_issues = [
            i
            for i in issues
            if isinstance(i, dict)
            and isinstance(i.get("message"), str)
            and (prefix and (prefix in i["message"] or "contract failed" in i["message"].lower()))
        ]
        if not contract_issues:
            return ""
        bullets = "\n".join(f"  • {i.get('message', '')[:240]}" for i in contract_issues[:5])
        return (
            f"⚠️ [TASK CONTRACT NOT SATISFIED — {contract.title}]\n"
            "Repair attempts did not fully resolve the contract:\n"
            f"{bullets}"
        )

    def _failure_args_fingerprint(self, args: dict) -> str:
        """Stable fingerprint of args matching the format stored in failure memory."""
        try:
            truncated = {k: str(v)[:60] for k, v in (args or {}).items()}
            return json.dumps(truncated, sort_keys=True, default=str)
        except Exception:
            return ""

    def _check_failure_blacklist(self, tool_name: str, args: dict) -> dict | None:
        """Return a blocking error dict if this exact (tool, args) recently failed.

        Looks at the most recent ``failure_blacklist_window`` entries and matches
        on (tool name AND identical truncated-args fingerprint). Read-only tools
        are never blocked — re-reading after state changes is a legitimate move.
        """
        if not getattr(self, "failure_blacklist_enabled", False):
            return None
        if tool_name in READ_ONLY_TOOLS:
            return None
        recent = (self._cross_turn_failures or [])[-self.failure_blacklist_window :]
        if not recent:
            return None
        fp = self._failure_args_fingerprint(args)
        if not fp:
            return None
        for entry in reversed(recent):
            if entry.get("tool") != tool_name:
                continue
            failed_args = entry.get("failed_args") or {}
            try:
                entry_fp = json.dumps(failed_args, sort_keys=True, default=str)
            except Exception:
                continue
            if entry_fp == fp:
                err = (entry.get("error") or "previous failure")[:160]
                return {
                    "status": "error",
                    "message": (
                        f"Failure blacklist: identical {tool_name}({args}) "
                        f"already failed earlier — {err}"
                    ),
                    "data": None,
                    "_meta": {"failure_blocked": True, "previous_error": err},
                    "_correction_hint": (
                        "This exact tool+args combo failed before. "
                        "Change at least one argument or pick a different tool."
                    ),
                }
        return None

    def _build_cross_turn_failure_note(self, user_message: str, fast: bool = False) -> str:
        """
        Return a system-message string listing past failures that are relevant to
        the current request (keyword overlap >= 2 tokens), capped at 3 items
        (or 1 item in fast mode for minimal token overhead).
        Returns empty string if nothing relevant.
        """
        if not self._cross_turn_failures:
            return ""
        current_tokens = set(_query_terms(user_message))
        if not current_tokens:
            return ""
        # BUG-1: Short queries rarely clear the ≥2-token overlap threshold even
        # when they reference the same thing as a previous failure. For queries
        # with 1–3 meaningful terms, lower the bar to a single-term match so
        # cross-turn memory still fires on "fix it", "try again", etc.
        overlap_threshold = 1 if len(current_tokens) <= 3 else 2
        cap = 1 if fast else 3
        relevant = []
        for entry in reversed(self._cross_turn_failures):  # most recent first
            overlap = current_tokens & entry["request_tokens"]
            if len(overlap) >= overlap_threshold:
                relevant.append(entry)
            if len(relevant) >= cap:
                break
        if not relevant:
            return ""
        lines = ["[CROSS-TURN MEMORY] Previous attempts on similar requests already failed:"]
        for e in relevant:
            lines.append(f"  • `{e['tool']}` → {e['error']}")
        lines.append("Avoid repeating those exact approaches. Try a different strategy.")
        return "\n".join(lines)

    def _get_node_schema(self) -> dict:
        """Lazy-load and cache the Houdini full node schema from disk."""
        if hasattr(self, "_node_schema_cache"):
            return self._node_schema_cache
        try:
            import os

            schema_path = os.path.join(
                self.config.get("data_dir", "data"), "schema", "houdini_full_schema.json"
            )
            with open(schema_path, encoding="utf-8") as f:
                self._node_schema_cache = json.load(f)
        except Exception:
            self._node_schema_cache = {}
        return self._node_schema_cache

    def _build_fast_schema_hint(self, user_message: str) -> str:
        """
        Scan the user message for known Houdini node type names and inject
        their parameter lists as a compact system hint. Zero LLM calls —
        pure local dict lookup. Capped at 4 nodes to stay token-light.
        """
        schema = self._get_node_schema()
        if not schema:
            return ""
        # Build flat name→data lookup once and cache it
        flat = getattr(self, "_flat_node_schema", None)
        if flat is None:
            flat = {}
            for ctx, nodes in schema.items():
                if not isinstance(nodes, dict):
                    continue
                for node_name, node_data in nodes.items():
                    # Skip versioned/nested entries like "Sop/foo::2.0"
                    if not isinstance(node_name, str) or "/" in node_name or "::" in node_name:
                        continue
                    flat[node_name.lower()] = {
                        "ctx": ctx,
                        "ui_name": node_data.get("ui_name", node_name)
                        if isinstance(node_data, dict)
                        else node_name,
                        "parms": (
                            node_data.get("parameters", [])[:20]
                            if isinstance(node_data, dict)
                            else []
                        ),
                    }
            self._flat_node_schema = flat
        if not flat:
            return ""
        # Extract candidate tokens from the message
        candidates = re.findall(r"\b([a-z][a-z0-9_]{2,30})\b", user_message.lower())
        found = {}
        for cand in candidates:
            if cand in flat and cand not in found:
                found[cand] = flat[cand]
            if len(found) >= 4:
                break
        if not found:
            return ""
        lines = ["[FAST SCHEMA HINT] Known parameters for referenced node types:"]
        for name, info in found.items():
            parm_str = ", ".join(info["parms"][:15]) if info["parms"] else "—"
            lines.append(f"  {info['ctx']}/{name} ({info['ui_name']}): {parm_str}")
        lines.append("Use exact parameter names above — do not guess or invent parm names.")
        return "\n".join(lines)

    def _finalize_turn_tracking(
        self,
        tool_history: list[str],
        write_tools: list[str],
        mutation_summaries: list[str] | None = None,
        dry_run: bool = False,
    ) -> None:
        self._last_turn_tool_counts = dict(self._turn_tool_counts)
        self._last_turn_tool_history = list(tool_history)
        self._last_turn_write_tools = list(write_tools)
        self._last_turn_mutation_summaries = list(mutation_summaries or [])
        self._last_turn_dry_run = dry_run
        self._last_turn_checkpoint_path = self._current_turn_checkpoint_path

    # ── Debug screenshot capture ──────────────────────────────────────
    def _capture_debug_screenshot(
        self,
        label: str,
        pane_type: str = "viewport",
        node_path: str | None = None,
        force_refresh: bool = False,
    ) -> str | None:
        if not self._vision_capture_allowed():
            return None
        if pane_type == "network" and self._turn_network_capture_failed:
            return None
        cache_key = f"debug:{pane_type}:{self._turn_scene_write_epoch}:{node_path or ''}"
        cached = None if force_refresh else self._turn_capture_cache.get(cache_key)
        if cached:
            return cached
        try:
            res = self._hou_call(
                TOOL_FUNCTIONS["capture_pane"],
                pane_type=pane_type,
                node_path=node_path,
                scale=0.75,
            )
            if res.get("status") != "ok":
                if pane_type == "network":
                    self._turn_network_capture_failed = True
                return None
            image_b64 = (res.get("data") or {}).get("image_b64")
            if image_b64:
                self.debug_logger.log_screenshot(label, image_b64=image_b64)
                self._turn_capture_cache[cache_key] = image_b64
            return image_b64
        except Exception as e:
            if pane_type == "network":
                self._turn_network_capture_failed = True
            self.debug_logger.log_system_note(f"{label} capture failed: {e}")
            return None

    def _enrich_capture_result(
        self,
        result: dict,
        stream_callback: Callable | None = None,
        include_vision: bool = True,
    ) -> dict:
        if result.get("status") != "ok":
            return result
        data = dict(result.get("data") or {})
        image_b64 = data.pop("image_b64", None)
        if not image_b64:
            result["data"] = data
            return result
        if not include_vision:
            data["image_available"] = True
            data["vision_analysis"] = (
                "[Skipped to keep this turn fast after repeated screenshot requests.]"
            )
            enriched = dict(result)
            enriched["data"] = data
            enriched["message"] = (
                f"{result.get('message', 'Captured screenshot.')} Vision analysis skipped after per-turn limit."
            )
            return enriched
        pane_type = data.get("pane_type", "viewport")
        prompt = (
            f"You are inspecting a Houdini {pane_type} screenshot. "
            "Describe the visible result, highlight red/orange error indicators, "
            "call out obvious geometry or layout issues, and say whether it looks correct."
        )
        try:
            vision_analysis = self.llm.chat_vision(prompt=prompt, image_b64=image_b64)
        except Exception as e:
            vision_analysis = f"[Vision analysis unavailable: {e}]"

        data["image_available"] = True
        data["vision_analysis"] = vision_analysis
        if stream_callback:
            stream_callback("\u200b👁️  Analysed captured screenshot…\n\n")
        enriched = dict(result)
        enriched["data"] = data
        enriched["message"] = (
            f"{result.get('message', 'Captured screenshot.')} Vision analysis attached."
        )
        return enriched

    @staticmethod
    def _classify_visual_self_check_verdict(verdict: str) -> str:
        text = str(verdict or "").strip()
        if not text:
            return "uncertain"
        first = text.splitlines()[0].strip().upper()
        upper = text.upper()
        capture_terms = (
            "NO VISUAL EVIDENCE",
            "CANNOT VALIDATE",
            "CAN'T VALIDATE",
            "NO VIEWPORT",
            "NO SCREENSHOT",
            "MISSING VIEWPORT",
            "TEXT CHAT",
            "CHAT LOG",
            "CONVERSATION",
            "UNVERIFIABLE",
        )
        if first.startswith("PASS"):
            return "pass"
        if first.startswith("FAIL_CAPTURE") or any(term in upper for term in capture_terms):
            return "capture"
        if first.startswith("UNCERTAIN"):
            return "uncertain"
        if first.startswith("FAIL_GEOMETRY"):
            return "geometry"
        # Backward-compatible handling for older critic prompts.
        if first.startswith("FAIL"):
            return "geometry"
        return "uncertain"

    def _perform_visual_self_check(
        self,
        user_message: str,
        response_text: str,
        image_b64: str | None = None,
        stream_callback: Callable | None = None,
    ) -> bool:
        """
        Analyses the viewport/network screenshot via the vision model.
        Returns True if the check passed (or is skipped), False if visible issues were found.
        """
        if not HOU_AVAILABLE:
            return True

        # Allow one extra capture for the visual self-check on top of the
        # normal per-turn budget. Use self.max_capture_pane_per_turn (already
        # resolved from config at init) so this stays consistent with the
        # gate in _execute_tool — reading config.get() separately let the
        # two limits drift out of sync.
        if self._turn_capture_pane_analyses >= self.max_capture_pane_per_turn + 1:
            return True

        image_b64 = image_b64 or self._capture_debug_screenshot(
            "Visual Self-Check",
            force_refresh=True,
        )
        if not image_b64:
            return True

        prompt = (
            "### TASK: CYNICAL HOUDINI CRITIC\n"
            "You are validating the final visual result of a Houdini task. "
            "You must be EXTREMELY CRITICAL. Most agents fail by creating 'floating' or 'flat' geometry.\n\n"
            "If the image is not a real Houdini viewport/render of the scene, do not infer geometry flaws.\n\n"
            "### CRITERIA:\n"
            "1. PROPORTIONS: Does it look like a real-world object or a distorted mess?\n"
            "2. SOLIDITY: Are intended solid parts actually volumetric rather than flat placeholder planes?\n"
            "3. CONNECTIVITY: Are components that should touch actually connected, or are they floating/intersecting weirdly?\n"
            "4. COMPLETENESS: Does it match ALL parts of the user request?\n"
            "5. IDENTITY: Would a neutral human clearly call this the requested object, or does it still read like a generic blockout? If ambiguous, FAIL.\n\n"
            "### OUTPUT FORMAT:\n"
            "Line 1: PASS, FAIL_GEOMETRY, FAIL_CAPTURE, or UNCERTAIN\n"
            "Line 2+: Precise bullets explaining visible flaws.\n\n"
            "Use FAIL_CAPTURE when the screenshot shows UI/chat/text, is blank, is cropped away from the scene, or lacks viewport evidence.\n"
            "Use FAIL_GEOMETRY only when the viewport itself shows a concrete geometry flaw.\n\n"
            f"USER REQUEST: {user_message}\n"
            f"AGENT CLAIM: {self._truncate_prompt_context(response_text, limit=1000)}"
        )

        try:
            verdict = self.llm.chat_vision(prompt=prompt, image_b64=image_b64)
            self._turn_capture_pane_analyses += 1
        except Exception as e:
            self.debug_logger.log_system_note(f"Visual self-check unavailable: {e}")
            return True  # Don't block turn on vision failure

        self.debug_logger.log_system_note(f"Visual self-check result:\n{verdict}")

        verdict_kind = self._classify_visual_self_check_verdict(verdict)

        if verdict_kind in {"capture", "uncertain"}:
            self.debug_logger.log_system_note(
                f"Visual self-check skipped repair: {verdict_kind} evidence."
            )
            if stream_callback:
                stream_callback(
                    "\u200b👁️ Visual self-check could not verify the viewport; skipping repair.\n\n"
                )
            return True

        if verdict_kind == "geometry":
            self._last_visual_verdict = verdict
            self.conversation.append(
                {"role": "system", "content": f"[VISUAL SELF-CHECK]\n{verdict}"}
            )
            if self.memory_manager:
                self.memory_manager.save_conversation(self.conversation)

            if stream_callback:
                stream_callback(f"\u200b⚠️ Visual self-check found issues.\n{verdict}\n\n")
            return False

        if stream_callback:
            stream_callback("\u200b👁️ Visual self-check passed.\n\n")
        return True

    # ── Logging helpers ───────────────────────────────────────────────
    def _start_logged_interaction(self, user_message: str, domain: str | None = None) -> int:
        if not self.memory:
            return -1
        return self.memory.start_interaction(user_message, domain=domain)

    def _finish_logged_interaction(self, interaction_id: int, response_text: str | None):
        if self.memory and interaction_id > 0 and response_text is not None:
            self.memory.finish_interaction(response_text, interaction_id)

        if self.debug_logger:
            self.debug_logger.log_turn_end()

    # ── Session management ────────────────────────────────────────────
    def _build_system_prompt(self) -> str:
        import os

        d = self.config.get("data_dir", "")
        b_path = os.path.join(d, "system_prompt_base.txt")
        l_path = os.path.join(d, "system_prompt_learned.txt")
        base = open(b_path, encoding="utf-8").read() if os.path.exists(b_path) else ""
        learned = open(l_path, encoding="utf-8").read() if os.path.exists(l_path) else ""

        # Inject project rules from memory
        project_rules = ""
        if self.memory and hasattr(self.memory, "get_project_rules_prompt"):
            try:
                project_rules = self.memory.get_project_rules_prompt(limit=8) or ""
            except Exception as e:
                print(f"[HoudiniMind] Project rules load failed: {e}")

        full_prompt = f"{base}\n\n{learned}".strip()
        if project_rules:
            full_prompt += f"\n\n{project_rules}"

        return full_prompt.strip()

    def reload_system_prompt(self):
        self.system_prompt = self._build_system_prompt()
        self._system_prompt_dirty = False

    def mark_system_prompt_dirty(self):
        """Flag the cached system prompt for rebuild on next use. Callers
        that mutate project rules or other sources feeding _build_system_prompt
        should call this instead of touching disk on the hot path."""
        self._system_prompt_dirty = True

    def _announce_rule_learning(self, stream_callback):
        """After a turn ends, if the project-rules count grew, reload the system
        prompt (dirty flag + rebuild) and notify the UI. Called from chat() AFTER
        _run_loop so the LLM has had a chance to extract rules from the message."""
        if not (self.memory and hasattr(self.memory, "project_rules")):
            return
        try:
            rules_after = self.memory.project_rules.stats().get("total_rules", 0)
        except Exception:
            return
        if rules_after > getattr(self, "_turn_rules_before", rules_after):
            if stream_callback:
                stream_callback(
                    "\u200b🧠 Learned! I've saved your instruction as a project rule.\n\n"
                )
            self.mark_system_prompt_dirty()
            self.reload_system_prompt()

    def reload_knowledge(self):
        if not self.rag:
            return
        try:
            if hasattr(self.rag, "retriever") and hasattr(self.rag.retriever, "reload"):
                self.rag.retriever.reload()
            if hasattr(self.rag, "reset_session"):
                self.rag.reset_session()
        except Exception as e:
            self.debug_logger.log_system_note(f"Knowledge reload failed: {e}")

    def cancel(self):
        self._cancel_event.set()
        self._confirm_event.set()
        try:
            self.llm.cancel_active_requests()
        except Exception:
            pass

    def has_restorable_checkpoint(self) -> bool:
        return bool(self._last_turn_checkpoint_path)

    def restore_last_turn_checkpoint(self) -> str:
        backup_path = self._last_turn_checkpoint_path
        if not backup_path:
            return "No restorable checkpoint is available for the last turn."
        restore_fn = TOOL_FUNCTIONS.get("restore_backup")
        if not restore_fn:
            return "Restore support is unavailable."
        try:
            result = self._hou_call(restore_fn, backup_path=backup_path)
            result = self._sanitize(result)
        except Exception as e:
            result = {"status": "error", "message": str(e), "data": None}
        self.debug_logger.log_tool_call("restore_backup", {"backup_path": backup_path}, result)
        if self.memory:
            self.memory.log_tool_call("restore_backup", {"backup_path": backup_path}, result)
        if result.get("status") == "ok":
            self._tool_cache.clear()
            self._turn_tool_counts = {}
            self._turn_capture_pane_analyses = 0
            self._turn_scene_write_epoch = 0
            self._turn_snapshot_cache = {}
            self._turn_capture_cache = {}
            self._turn_tool_schema_cache = {}
            self._live_scene_json = None
            self._refresh_live_scene_context()
            self._last_turn_scene_diff_text = "[SCENE DIFF]\nRestored the previous turn checkpoint."
            self._last_turn_write_tools = []
            self._last_turn_mutation_summaries = []
            self._last_turn_verification_report = None
            self._last_turn_verification_text = "[VERIFICATION] RESTORED\nThe scene was restored from the last saved turn checkpoint."
            return result.get("message", f"Restored backup: {backup_path}")
        return f"Checkpoint restore failed: {result.get('message', 'Unknown error')}"

    def _try_consume_repair_budget(self) -> bool:
        """Atomically consume one unit of the current turn's repair budget.

        Returns True if a unit was consumed, False if the budget is exhausted.
        All repair paths (structural, visual, post-visual) share this counter so
        max_auto_repairs is a hard ceiling across the whole turn.
        """
        budget = getattr(self, "_turn_repair_budget", 0)
        if budget <= 0:
            return False
        self._turn_repair_budget = budget - 1
        return True

    def _auto_restore_failed_turn_if_needed(
        self,
        request_mode: str,
        dry_run: bool,
        remaining_repair_budget: int,
        stream_callback: Callable | None = None,
    ) -> str | None:
        if dry_run or request_mode not in {"build", "debug"}:
            return None
        if not self.auto_restore_on_failed_verification:
            return None
        if remaining_repair_budget > 0:
            return None
        report = self._last_turn_verification_report or {}
        if report.get("status") != "fail":
            return None
        if not self._last_turn_write_tools:
            return None

        # HARDENING: Only auto-restore on severe failures. If the geometry
        # exists but has minor issues, keep the work rather than wiping it.
        issues = report.get("issues", [])
        severe_issues = [i for i in issues if i.get("severity") in {"repair", "error"}]
        if not severe_issues:
            minor_msg = (
                "Verification found minor issues but the geometry is intact. "
                "You may want to review and adjust manually."
            )
            self.debug_logger.log_system_note(
                f"[AUTO-RESTORE] Skipped — only minor issues: {len(issues)} total, 0 severe"
            )
            if stream_callback:
                stream_callback(
                    "\u200b\u2705 Minor verification issues detected but geometry is preserved.\n\n"
                )
            return minor_msg

        if not self.has_restorable_checkpoint():
            return "Verification still failed and no checkpoint is available for rollback."

        restore_msg = self.restore_last_turn_checkpoint()
        if stream_callback:
            stream_callback(
                "\u200b\u21a9\ufe0f Verification remained failed; restoring turn checkpoint.\n\n"
            )
        if "failed" in str(restore_msg).lower():
            return "Verification still failed after repairs, and automatic rollback failed: " + str(
                restore_msg
            )
        return (
            "Verification still failed after repair budget was exhausted. "
            f"Automatic rollback succeeded: {restore_msg}"
        )

    def undo_last_action(self) -> str:
        if not self.undo_stack:
            return "Nothing to undo."
        last = self.undo_stack.pop()
        return self.chat(f"[UNDO REQUEST] Please undo this action: {last}", None)

    def reset_conversation(self):
        self.conversation = [{"role": "system", "content": self.system_prompt}]
        self.undo_stack = []
        self._backup_done_this_session = False
        self._cancel_event.clear()
        self._tool_cache = {}
        self._turn_tool_counts = {}
        self._turn_capture_pane_analyses = 0
        self._turn_scene_write_epoch = 0
        self._turn_snapshot_cache = {}
        self._turn_capture_cache = {}
        self._turn_tool_schema_cache = {}
        self._last_turn_tool_counts = {}
        self._last_turn_tool_history = []
        self._last_turn_write_tools = []
        self._last_turn_mutation_summaries = []
        self._last_turn_scene_diff_text = None
        self._last_turn_dry_run = False
        self._current_turn_checkpoint_path = None
        self._last_turn_checkpoint_path = None
        self._last_turn_verification_report = None
        self._last_turn_verification_text = None
        self._last_turn_output_paths = []
        self._last_snapshot = None
        if self.memory_manager:
            self.memory_manager.save_conversation(self.conversation)

    def inject_scene_context(self, scene_json: str):
        compact_scene = self._compress_live_scene_context(scene_json)
        self._live_scene_json = compact_scene
        self.conversation = [
            m
            for m in self.conversation
            if not m.get("content", "").startswith("[LIVE SCENE STATE]")
        ]
        self.conversation.insert(
            0, {"role": "system", "content": f"[LIVE SCENE STATE]\n{compact_scene}"}
        )
