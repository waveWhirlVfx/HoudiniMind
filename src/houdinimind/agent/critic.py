# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
"""
HoudiniMind — Repair Critic v1
Lightweight self-correction module.

The critic evaluates tool results and build outputs, suggesting fixes
when it detects errors or quality issues. Used by the AgentLoop when
`enable_repair_critic` is True.
"""

import json
import re
import traceback
from typing import Any, Dict, List, Optional, Callable


# ── Heuristic error patterns (zero LLM cost) ─────────────────────────
_KNOWN_ERROR_PATTERNS = [
    {
        "pattern": re.compile(r"Node not found", re.IGNORECASE),
        "issue": "Referenced node path does not exist.",
        "fix_hint": "Verify the node path with get_scene_summary or find_nodes before retrying.",
    },
    {
        "pattern": re.compile(r"(parameter|parm).*not found", re.IGNORECASE),
        "issue": "Parameter name is incorrect for this node type.",
        "fix_hint": "Call get_node_parameters to get the correct parameter name, then retry with safe_set_parameter.",
    },
    {
        "pattern": re.compile(r"(cannot create|failed to create).*node", re.IGNORECASE),
        "issue": "Node creation failed — likely wrong parent context or invalid type.",
        "fix_hint": "Call verify_node_type first, then ensure parent_path is correct (SOPs need a geo container).",
    },
    {
        "pattern": re.compile(r"No geometry", re.IGNORECASE),
        "issue": "Node has no geometry output — may be uncooked or misconfigured.",
        "fix_hint": "Check upstream connections with get_node_inputs and force a cook.",
    },
    {
        "pattern": re.compile(r"Missing (connection|input)", re.IGNORECASE),
        "issue": "Required input is not connected.",
        "fix_hint": "Use suggest_node_repairs or get_node_inputs to identify which input needs wiring.",
    },
    {
        "pattern": re.compile(r"cook error|cook failed", re.IGNORECASE),
        "issue": "Node failed to cook.",
        "fix_hint": "Use deep_error_trace to find the root cause, then fix upstream.",
    },
    # ── VEX Syntax & Semantics ──
    {
        "pattern": re.compile(r"Invalid type for (?:operator|function)", re.IGNORECASE),
        "issue": "VEX type mismatch (e.g. passing float to int function).",
        "fix_hint": "Explicitly cast types in VEX (e.g. (int)@fattr) or check attribute signatures with sample_geometry.",
    },
    {
        "pattern": re.compile(r"Unknown identifier", re.IGNORECASE),
        "issue": "Referenced VEX variable or attribute is not defined.",
        "fix_hint": "Check for typos in @attrib names or ensure the attribute exists upstream using get_geometry_attributes.",
    },
    # ── Volume / VDB Mismatches ──
    {
        "pattern": re.compile(r"Primitive type mismatch.*(?:VDB|Volume)", re.IGNORECASE),
        "issue": "Mixing standard Volumes and VDBs incorrectly.",
        "fix_hint": "Convert to a consistent type using Convert VDB or VDB from Polygons.",
    },
    {
        "pattern": re.compile(r"VDB grid '(.*)' not found", re.IGNORECASE),
        "issue": "Referenced VDB grid name is missing.",
        "fix_hint": "Call list_vdb_grids to verify available grid names before processing.",
    },
    # ── Python SOP Errors ──
    {
        "pattern": re.compile(r"hou\.NodeError: (.*)", re.IGNORECASE),
        "issue": "Houdini Python API error.",
        "fix_hint": "Consult documentation with search_docs for the specific hou method being called.",
    },
    {
        "pattern": re.compile(r"IndentationError|SyntaxError", re.IGNORECASE),
        "issue": "Python script syntax error.",
        "fix_hint": "Fix the Python code formatting or logical syntax errors in write_python_script.",
    },
]


class RepairCritic:
    """
    Evaluates tool call results and build outputs for errors.

    Two modes of operation:
      1. Heuristic (fast, free): Pattern-matches known error signatures
      2. LLM-backed (slower, smarter): Sends context to the model for analysis

    The critic returns structured verdicts:
      {"ok": True/False, "issue": str, "fix_action": str, "confidence": float}
    """

    def __init__(self, llm_chat_fn: Optional[Callable] = None, max_llm_evals_per_turn: int = 3, on_degradation: Optional[Callable] = None):
        """
        Args:
            llm_chat_fn: A callable(system, user, temperature) -> str for LLM-backed analysis.
                         Pass `llm.chat_simple` from OllamaClient.
            max_llm_evals_per_turn: Cap expensive LLM critic calls per agent turn.
            on_degradation: Optional callback(key, message) invoked when critic degrades.
        """
        self._chat = llm_chat_fn
        self._max_llm = max(0, max_llm_evals_per_turn)
        self._llm_calls_this_turn = 0
        self._on_degradation = on_degradation

    def reset_turn(self):
        """Call at the start of each agent turn to reset the LLM budget."""
        self._llm_calls_this_turn = 0

    # ──────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────

    def evaluate_tool_result(
        self,
        tool_name: str,
        tool_args: dict,
        result: Any,
    ) -> Dict:
        """
        Evaluate a single tool call result.

        Returns:
            {"ok": bool, "issue": str, "fix_action": str, "confidence": float}
        """
        # Normalise result
        if isinstance(result, dict):
            status = result.get("status", "")
            message = result.get("message", "")
        elif isinstance(result, str):
            status = "error" if "error" in result.lower() else "ok"
            message = result
        else:
            return self._verdict_ok()

        # Fast path: success
        if status == "ok":
            return self._verdict_ok()

        # Heuristic check
        heuristic = self._heuristic_check(message)
        if heuristic:
            return heuristic

        # LLM fallback (if budget remains)
        if self._chat and self._llm_calls_this_turn < self._max_llm:
            return self._llm_evaluate_error(tool_name, tool_args, message)

        # Budget exhausted - report degradation
        if self._on_degradation:
            self._on_degradation("critic", "Repair critic LLM budget exhausted — using heuristic-only diagnosis")

        # No diagnosis available
        return {
            "ok": False,
            "issue": message[:200],
            "fix_action": "",
            "confidence": 0.3,
            "_critic_mode": "budget_exhausted",
        }

    def evaluate_build_output(
        self,
        scene_summary: dict,
        original_goal: str,
        audit_result: Optional[dict] = None,
    ) -> Dict:
        """
        Post-build quality check: evaluates whether the built scene
        matches the user's original goal.

        This is a higher-level check than evaluate_tool_result.
        """
        issues = []

        # Check for nodes with errors
        if isinstance(scene_summary, dict):
            nodes = scene_summary.get("data", {}).get("nodes", [])
            error_nodes = [n for n in nodes if n.get("errors")]
            if error_nodes:
                paths = [n["path"] for n in error_nodes[:5]]
                issues.append(f"Nodes with errors: {', '.join(paths)}")

        # Check spatial audit
        if isinstance(audit_result, dict):
            data = audit_result.get("data", audit_result)
            origin_issues = data.get("at_origin_issues", [])
            if origin_issues:
                names = [item.get("node", str(item)) if isinstance(item, dict) else str(item) for item in origin_issues[:5]]
                issues.append(f"Nodes stuck at origin (0,0,0): {', '.join(names)}")

        if not issues:
            return self._verdict_ok()

        combined = "; ".join(issues)

        # LLM-assisted fix suggestion
        if self._chat and self._llm_calls_this_turn < self._max_llm:
            return self._llm_evaluate_build(original_goal, combined)

        return {
            "ok": False,
            "issue": combined,
            "fix_action": "Investigate the listed issues and fix node positions/connections.",
            "confidence": 0.6,
        }

    # ──────────────────────────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _verdict_ok() -> Dict:
        return {"ok": True, "issue": "", "fix_action": "", "confidence": 1.0}

    def _heuristic_check(self, message: str) -> Optional[Dict]:
        """Pattern-match known error signatures (zero LLM cost)."""
        for pattern_info in _KNOWN_ERROR_PATTERNS:
            if pattern_info["pattern"].search(message):
                return {
                    "ok": False,
                    "issue": pattern_info["issue"],
                    "fix_action": pattern_info["fix_hint"],
                    "confidence": 0.85,
                    "_critic_mode": "heuristic",
                }
        return None

    def _llm_evaluate_error(self, tool_name: str, tool_args: dict, error_msg: str) -> Dict:
        """Use the LLM to diagnose an error and suggest a fix."""
        self._llm_calls_this_turn += 1
        try:
            args_str = json.dumps(tool_args, default=str)[:300]
            raw = self._chat(
                system=(
                    "You are a Houdini agent critic. A tool call failed.\n"
                    "Diagnose the SPECIFIC cause and suggest ONE concrete fix action.\n"
                    "Reply as JSON: {\"issue\": \"...\", \"fix_action\": \"...\", \"confidence\": 0.0-1.0}\n"
                    "fix_action should be a specific tool call or parameter correction.\n"
                    "Output ONLY valid JSON — no prose, no markdown."
                ),
                user=f"Tool: {tool_name}\nArgs: {args_str}\nError: {error_msg[:400]}",
                temperature=0.05,
            )
            return self._parse_critic_json(raw, error_msg)
        except Exception:
            return {
                "ok": False,
                "issue": error_msg[:200],
                "fix_action": "",
                "confidence": 0.3,
                "_critic_mode": "llm",
            }

    def _llm_evaluate_build(self, goal: str, issues: str) -> Dict:
        """Use the LLM to suggest fixes for post-build quality issues."""
        self._llm_calls_this_turn += 1
        try:
            raw = self._chat(
                system=(
                    "You are a Houdini build quality critic.\n"
                    "Given the user's goal and the detected issues, suggest ONE concrete fix.\n"
                    "Reply as JSON: {\"issue\": \"...\", \"fix_action\": \"...\", \"confidence\": 0.0-1.0}\n"
                    "Output ONLY valid JSON — no prose."
                ),
                user=f"Goal: {goal}\nIssues found: {issues}",
                temperature=0.05,
            )
            return self._parse_critic_json(raw, issues)
        except Exception:
            return {
                "ok": False,
                "issue": issues[:200],
                "fix_action": "Investigate manually.",
                "confidence": 0.4,
                "_critic_mode": "llm",
            }

    @staticmethod
    def _parse_critic_json(raw: str, fallback_issue: str) -> Dict:
        """Safely parse LLM JSON response."""
        cleaned = re.sub(r"```(?:json)?\n?|```", "", raw).strip()
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
                return {
                    "ok": False,
                    "issue": str(data.get("issue", fallback_issue))[:300],
                    "fix_action": str(data.get("fix_action", ""))[:300],
                    "confidence": float(data.get("confidence", 0.6)),
                    "_critic_mode": "llm",
                }
            except (json.JSONDecodeError, ValueError, KeyError):
                pass
        return {
            "ok": False,
            "issue": fallback_issue[:200],
            "fix_action": "",
            "confidence": 0.3,
            "_critic_mode": "llm",
        }
