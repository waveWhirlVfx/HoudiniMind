# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
"""
HoudiniMind — Sub-Agent Architecture v2

Defines specialized sub-agents with constrained tool access:
  - PlannerAgent:   Generates structured build plans (read-only tools)
  - ValidatorAgent: Post-build quality checks (read + vision tools)

Each sub-agent has its own system prompt and tool whitelist,
preventing accidental scene mutation from the wrong phase. The base
SubAgent runs a real tool-execution loop so declared tools actually
run against the live scene — without it the validator would only ever
see a text serialization and could not verify scene state.
"""

import json
import re
from typing import Any, Callable, Dict, List, Optional, Set


# ══════════════════════════════════════════════════════════════════════
#  Sub-Agent Base
# ══════════════════════════════════════════════════════════════════════

class SubAgent:
    """Base class for specialized sub-agents."""

    NAME: str = "base"
    SYSTEM_PROMPT: str = ""
    ALLOWED_TOOLS: Set[str] = set()
    MAX_TOOL_ROUNDS: int = 4

    def __init__(
        self,
        llm_chat_fn: Callable,
        all_tool_schemas: list,
        tool_executor: Optional[Callable[[str, dict], Any]] = None,
    ):
        """
        Args:
            llm_chat_fn: Callable(messages, tools, task, model_override) -> dict
            all_tool_schemas: The full TOOL_SCHEMAS list to filter from
            tool_executor: Callable(tool_name, args) -> result that actually runs
                a tool against the live Houdini scene. If None, the sub-agent
                has no tools sent to the LLM (pure text reasoning).
        """
        self._chat = llm_chat_fn
        self._schemas = self._filter_schemas(all_tool_schemas)
        self._tool_executor = tool_executor

    def _filter_schemas(self, all_schemas: list) -> list:
        """Return only schemas for tools this sub-agent is allowed to use."""
        if not self.ALLOWED_TOOLS:
            return []
        filtered = []
        for schema in all_schemas:
            name = schema.get("function", {}).get("name", "")
            if name in self.ALLOWED_TOOLS:
                filtered.append(schema)
        return filtered

    def run(self, query: str, context: str = "", model_override: str = None) -> str:
        """
        Execute this sub-agent with the given query.
        Runs a tool-execution loop when a tool_executor is wired; otherwise
        returns the first LLM response text.
        """
        messages: List[Dict[str, Any]] = []
        if self.SYSTEM_PROMPT:
            messages.append({"role": "system", "content": self.SYSTEM_PROMPT})
        if context:
            messages.append({"role": "system", "content": f"[CONTEXT]\n{context}"})
        messages.append({"role": "user", "content": query})

        send_tools = self._schemas if (self._schemas and self._tool_executor) else None

        for _round in range(max(1, self.MAX_TOOL_ROUNDS)):
            result = self._chat(
                messages,
                tools=send_tools,
                task=self.NAME,
                model_override=model_override,
            )
            text = result.get("content", "") or ""
            tool_calls = result.get("tool_calls", []) or []

            if not tool_calls or not self._tool_executor:
                return text

            messages.append({
                "role": "assistant",
                "content": text,
                "tool_calls": tool_calls,
            })

            for tc in tool_calls:
                fn = tc.get("function", {}) if isinstance(tc, dict) else {}
                name = fn.get("name", "")
                raw_args = fn.get("arguments", {})
                if isinstance(raw_args, str):
                    try:
                        args = json.loads(raw_args)
                    except (json.JSONDecodeError, ValueError):
                        args = {}
                elif isinstance(raw_args, dict):
                    args = raw_args
                else:
                    args = {}

                if name not in self.ALLOWED_TOOLS:
                    tool_result = {"ok": False, "error": f"tool '{name}' not allowed for {self.NAME}"}
                else:
                    try:
                        tool_result = self._tool_executor(name, args)
                    except Exception as exc:  # noqa: BLE001
                        tool_result = {"ok": False, "error": str(exc)}

                messages.append({
                    "role": "tool",
                    "name": name,
                    "content": json.dumps(tool_result, default=str)[:4000],
                    "tool_call_id": tc.get("id", "") if isinstance(tc, dict) else "",
                })

        # Ran out of rounds — one final call without tools to force a summary.
        result = self._chat(
            messages,
            tools=None,
            task=self.NAME,
            model_override=model_override,
        )
        return result.get("content", "") or ""


# ══════════════════════════════════════════════════════════════════════
#  PlannerAgent — generates structured build plans
# ══════════════════════════════════════════════════════════════════════

class PlannerAgent(SubAgent):
    NAME = "planning"
    SYSTEM_PROMPT = (
        "You are a Houdini build planner. Your ONLY job is to produce a "
        "clear, Houdini-specific execution plan before execution.\n"
        "You may use read-only tools to inspect the current scene.\n\n"
        "RULES:\n"
        "1. Output a JSON object matching this schema:\n"
        "   {\n"
        "     \"mission\": \"High-level goal\",\n"
        "     \"phases\": [\n"
        "       {\n"
        "         \"phase\": \"Name of phase\",\n"
        "         \"steps\": [\n"
        "           {\n"
        "             \"step\": 1,\n"
        "             \"action\": \"Houdini-specific action to perform\",\n"
        "             \"dependency\": [],\n"
        "             \"node_type\": \"exact Houdini node type if applicable\",\n"
        "             \"parameters\": {\"parm_name\": \"value\"},\n"
        "             \"validation\": \"how to check if this step succeeded in Houdini\"\n"
        "           }\n"
        "         ]\n"
        "       }\n"
        "     ]\n"
        "   }\n"
        "2. Dependencies must reference prior step numbers (e.g. [1]).\n"
        "3. Step numbers must be strictly sequential globally across all phases.\n"
        "4. Limit your plan STRICTLY to what the user explicitly asked for. Do NOT invent extra details, assumptions, or features.\n"
        "5. Formulate your steps using exact Houdini node types and parameters so the execution agent can perform them perfectly in Houdini.\n"
        "6. Output ONLY valid JSON — no prose.\n"
        "7. Maximum 20 steps across all phases."
    )
    ALLOWED_TOOLS = {
        "get_scene_summary", "get_current_node_path", "get_hip_info",
        "get_node_parameters", "get_node_inputs", "get_geometry_attributes",
        "find_nodes", "verify_node_type", "list_node_types",
        "search_knowledge", "get_node_recipe", "suggest_workflow",
        "explain_node_type", "resolve_build_hints",
    }
    _FORBIDDEN_PLAN_KEYS = {
        "node_type",
        "parameters",
        "parameter",
        "parm",
        "parms",
        "tool",
        "tools",
        "recommended_tools",
        "exact_node_path",
        "node_path",
    }
    _PROTOTYPE_STEP_DEFAULTS = {
        "prototype_detail": "",
        "measurements": {},
        "count": None,
        "placement": "",
        "spacing": "",
        "relationships": [],
        "validation": "",
        "recovery": "",
        "requires_inspection": False,
    }
    _TEXT_REPLACEMENTS = (
        (r"/obj/[^\s,;)\]}]+", "the relevant geometry"),
        (r"\bcreate_node\b", "scene edit"),
        (r"\bnode\s+type\b", "setup type"),
        (r"\bnodes\b", "setups"),
        (r"\bnode\b", "setup"),
        (r"\s+", " "),
    )

    def generate_plan(self, user_goal: str, scene_context: str = "") -> dict:
        """
        Generate a structured build plan.
        Returns a dictionary representing the hierarchical plan.
        """
        raw = self.run(user_goal, context=scene_context)
        return self._parse_plan(raw, user_goal)

    @classmethod
    def _parse_plan(cls, raw: str, fallback_goal: str) -> dict:
        """Parse the hierarchical JSON plan from the LLM response."""
        cleaned = re.sub(r"```(?:json)?\n?|```", "", raw).strip()

        obj_match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if obj_match:
            try:
                data = json.loads(obj_match.group())
                phases = data.get("phases", [])
                if isinstance(phases, list) and phases:
                    return {
                        "mission": data.get("mission", fallback_goal),
                        "prototype_scale": cls._sanitize_prototype_scale(
                            data.get("prototype_scale")
                        ),
                        "phases": cls._sanitize_phases(phases),
                    }
            except (json.JSONDecodeError, ValueError):
                pass

        # Support fallback if it generates the old schema
        array_match = re.search(r"\[.*\]", cleaned, re.DOTALL)
        if array_match:
            try:
                steps = json.loads(array_match.group())
                if isinstance(steps, list) and steps:
                    return {
                        "mission": fallback_goal,
                        "prototype_scale": cls._sanitize_prototype_scale(None),
                        "phases": cls._sanitize_phases(
                            [{"phase": "Execution", "steps": steps}]
                        ),
                    }
            except (json.JSONDecodeError, ValueError):
                pass

        # Ultimate Fallback
        return {
            "mission": fallback_goal,
            "prototype_scale": cls._sanitize_prototype_scale(None),
            "phases": [
                {
                    "phase": "Fallback Single Step",
                    "steps": [
                        {
                            "step": 1,
                            "action": fallback_goal,
                            "dependency": [],
                            "risk_level": "low",
                            "prototype_detail": fallback_goal,
                            "measurements": {},
                            "count": None,
                            "placement": "",
                            "spacing": "",
                            "relationships": [],
                            "validation": "The requested prototype is visibly present.",
                            "recovery": "Add the missing visible prototype elements.",
                            "requires_inspection": False
                        }
                    ]
                }
            ]
        }

    @classmethod
    def _sanitize_prototype_scale(cls, value: Any) -> dict:
        if not isinstance(value, dict):
            return {
                "unit": "Houdini units",
                "overall_size": "reasonable prototype scale",
                "notes": "Scale was not explicitly specified by the user.",
            }
        return {
            "unit": str(value.get("unit") or "Houdini units"),
            "overall_size": str(value.get("overall_size") or "reasonable prototype scale"),
            "notes": str(value.get("notes") or ""),
        }

    @classmethod
    def _sanitize_phases(cls, phases: list) -> list:
        sanitized = []
        next_step = 1
        for phase in phases:
            if not isinstance(phase, dict) or next_step > 20:
                continue
            valid_steps = []
            for raw_step in phase.get("steps", []):
                if not isinstance(raw_step, dict) or next_step > 20:
                    continue
                step = {
                    str(k): v
                    for k, v in raw_step.items()
                    if str(k).lower() not in cls._FORBIDDEN_PLAN_KEYS
                }
                if not step.get("prototype_detail") and raw_step.get("details"):
                    step["prototype_detail"] = str(raw_step.get("details"))
                step["step"] = next_step
                step["action"] = cls._sanitize_plan_text(step.get("action", ""))
                step.setdefault("dependency", [])
                step.setdefault("risk_level", "low")
                for key, default in cls._PROTOTYPE_STEP_DEFAULTS.items():
                    if key not in step:
                        step[key] = default.copy() if isinstance(default, (dict, list)) else default
                if not isinstance(step.get("measurements"), dict):
                    step["measurements"] = {"detail": str(step.get("measurements") or "")}
                if not isinstance(step.get("relationships"), list):
                    step["relationships"] = [str(step.get("relationships") or "")]
                for key in (
                    "prototype_detail", "placement", "spacing", "validation", "recovery",
                ):
                    step[key] = cls._sanitize_plan_text(step.get(key, ""))
                step["relationships"] = [
                    cls._sanitize_plan_text(item)
                    for item in step.get("relationships", [])
                    if str(item).strip()
                ]
                valid_steps.append(step)
                next_step += 1
            sanitized.append({
                "phase": str(phase.get("phase") or "Execution"),
                "steps": valid_steps,
            })
        return sanitized

    @classmethod
    def _sanitize_plan_text(cls, value: Any) -> str:
        text = str(value or "")
        for pattern, replacement in cls._TEXT_REPLACEMENTS:
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
        return re.sub(r"\s+", " ", text).strip()


# ══════════════════════════════════════════════════════════════════════
#  ValidatorAgent — post-build quality checks
# ══════════════════════════════════════════════════════════════════════

class ValidatorAgent(SubAgent):
    NAME = "validation"
    MAX_TOOL_ROUNDS = 5
    SYSTEM_PROMPT = (
        "You are the HACS Quality Assurance Validator.\n"
        "Your task is to review the most recent changes made to the Houdini scene using the provided WorldModel context and your toolset.\n\n"
        "IMPORTANT: You MUST call at least one inspection tool (get_all_errors, "
        "inspect_display_output, get_scene_summary, or check_geometry_issues) "
        "against the live scene before issuing a verdict. Do NOT rely solely on "
        "the WorldModel text — it may be stale.\n\n"
        "Strictly check for:\n"
        "1. Critical cook errors (red UI flags) on any node.\n"
        "2. Floating/disconnected nodes inside procedural chains that should be wired.\n"
        "3. Geometry stuck at origin (0,0,0) that should be positioned.\n"
        "4. Missing display/render flags on the final output node.\n"
        "5. Visual correctness (if a viewport screenshot is provided).\n\n"
        "Output a JSON report exactly matching this schema:\n"
        "{\n"
        "  \"passed\": true/false,\n"
        "  \"issues\": [\"specific node path + concise issue description\"],\n"
        "  \"suggestions\": [\"exact steps or tools required to fix the issue\"]\n"
        "}\n"
        "Output ONLY valid JSON — no markdown fences, no conversational prose."
    )
    ALLOWED_TOOLS = {
        "get_scene_summary", "get_all_errors", "get_node_parameters",
        "get_node_inputs", "get_geometry_attributes", "inspect_display_output",
        "get_bounding_box", "check_geometry_issues", "find_nodes",
        "get_node_cook_info", "capture_pane", "analyze_geometry",
        "audit_spatial_layout",
    }

    def validate_build(self, goal: str, scene_context: str = "") -> dict:
        """
        Run validation and return a structured report.
        Returns {"passed": bool, "issues": list, "suggestions": list}

        When the sub-agent has no tool_executor wired, validation is advisory
        only — the result is flagged so the caller can ignore it rather than
        act on a hallucinated PASS.
        """
        raw = self.run(
            f"Validate the build result for: {goal}",
            context=scene_context,
        )
        report = self._parse_report(raw)
        if self._tool_executor is None:
            report["advisory_only"] = True
        return report

    @staticmethod
    def _parse_report(raw: str) -> dict:
        cleaned = re.sub(r"```(?:json)?\n?|```", "", raw).strip()
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
                return {
                    "passed": bool(data.get("passed", False)),
                    "issues": list(data.get("issues", [])),
                    "suggestions": list(data.get("suggestions", [])),
                }
            except (json.JSONDecodeError, ValueError):
                pass
        return {"passed": False, "issues": [raw[:300]], "suggestions": []}
