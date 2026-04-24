# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
"""
Request-mode heuristics and lightweight research orchestration.

This module holds the prompt-routing helpers that used to live inside
`houdinimind/agent/loop.py`, plus the embedded `AutoResearcher` used by the
turn classifier.
"""

import json
import re
from typing import Callable, List

from .llm_client import OllamaClient

READ_ONLY_TOOLS = {
    "get_scene_summary",
    "get_all_errors",
    "get_node_parameters",
    "get_node_inputs",
    "get_geometry_attributes",
    "inspect_display_output",
    "resolve_build_hints",
    "analyze_geometry",
    "sample_geometry",
    "profile_network",
    "get_hip_info",
    "get_bounding_box",
    "check_geometry_issues",
    "find_nodes",
    "get_current_node_path",
    "measure_cook_time",
    "list_node_types",
    "verify_node_type",
    "get_dop_objects",
    "get_sim_stats",
    "list_materials",
    "get_usd_hierarchy",
    "get_node_cook_info",
    "get_hda_parameters",
    "search_knowledge",
    "get_vex_snippet",
    "get_node_recipe",
    "explain_node_type",
    "suggest_workflow",
    "get_error_fix",
    "compare_nodes",
    "take_node_snapshot",
    "get_timeline_keyframes",
    "get_flip_diagnostic",
    "search_docs",
    "capture_pane",
    "list_takes",
    "list_vdb_grids",
    "analyze_vdb",
    "get_packed_geo_info",
    "list_all_file_references",
    "scan_missing_files",
    "get_cook_dependency_order",
    "get_parm_expression_audit",
    "list_material_assignments",
    "list_installed_hdas",
    "diff_hda_versions",
    "validate_usd_stage",
    "get_usd_prim_attributes",
    "get_memory_usage",
    "suggest_optimization",
    "eval_hscript",
}

NON_SCENE_MUTATING_WRITE_TOOLS = {
    "create_backup",
    "export_geometry",
    "save_hip",
}

NON_SUBSTANTIVE_COMPLETION_WRITE_TOOLS = NON_SCENE_MUTATING_WRITE_TOOLS | {
    "set_display_flag",
    "layout_network",
}

CACHE_TTL = {
    # Write tools clear the entire cache immediately, so these TTLs only guard
    # against out-of-band manual scene edits. Short TTLs were causing 0% cache
    # hit rates because LLM calls routinely take longer than 10s. Raised to 90s
    # (scene-summary / errors) and 120-180s (heavier reads) so the cache stays
    # warm across consecutive LLM rounds within the same build/debug phase.
    "get_scene_summary": 90,
    "get_geometry_attributes": 120,
    "get_all_errors": 90,
    "get_hip_info": 120,
    "get_node_parameters": 90,
    "list_materials": 120,
    "get_node_cook_info": 90,
    "get_bounding_box": 120,
    "get_node_inputs": 90,
    "inspect_display_output": 90,
    "resolve_build_hints": 120,
    "list_takes": 120,
    "list_vdb_grids": 120,
    "list_installed_hdas": 180,
    "get_memory_usage": 60,
    "validate_usd_stage": 120,
    "list_material_assignments": 120,
    "get_packed_geo_info": 120,
    "analyze_vdb": 120,
}

BUILD_INTENT_RE = re.compile(
    r"^\s*(?:please\s+)?(?:can you\s+|could you\s+)?"
    r"(create|build|make|model|add|place|move|set|change|adjust|connect|wire|"
    r"layout|arrange|organize|duplicate|rename|assign|apply|extrude|bevel|"
    r"fracture|shatter|break|destroy|simulate|solver|cache|bake|run|playblast|"
    r"render|scatter|copy|instance|merge|boolean|subdivide|remesh|deform)\b",
    re.IGNORECASE,
)
FOLLOWUP_BUILD_RE = re.compile(
    r"(?:\b(?:now|also|next|then|and)\b.{0,40}\b(?:add|make|move|rotate|scale|change|set|connect|wire|assign|apply|delete|update|replace|swap|fracture|shatter|break|destroy|simulate|render|scatter|copy|instance|merge|boolean|subdivide|remesh|deform)\b)"
    r"|(?:\b(?:make|move|rotate|scale|change|set|connect|wire|assign|apply|delete|update|replace|swap|fracture|shatter|break|destroy|simulate|render|scatter|copy|instance|merge|boolean|subdivide|remesh|deform)\b.{0,24}\b(?:it|this|that|them|those)\b)"
    r"|(?:\b(?:it|this|that|them|those)\b.{0,40}\b(?:bigger|smaller|higher|lower|wider|narrower|taller|shorter|thicker|thinner|colored|coloured|rotated|scaled|moved|shifted|offset)\b)"
    r"|(?:\bwhat if\b.{0,60}\b(?:use|used|swap|replace)\b.{0,20}\binstead\b)"
    r"|(?:\b(?:do it|apply them|apply it|execute it|go ahead|proceed|build it|fix it)\b)",
    re.IGNORECASE,
)
DEBUG_INTENT_RE = re.compile(
    r"\b(error|errors|warning|warnings|broken|issue|issues|problem|problems|"
    r"failed|failure|crash|crashing|debug|diagnose|diagnostic|trace|repair|"
    r"fix|isn't working|is not working|not working|wrong)\b",
    re.IGNORECASE,
)
BUILD_RAG_INCLUDE_CATEGORIES = ["workflow", "recipe", "best_practice"]
BUILD_RAG_EXCLUDE_CATEGORIES = ["errors"]
DEBUG_RAG_INCLUDE_CATEGORIES = ["errors", "workflow", "best_practice", "nodes"]
_RAG_NODE_HINT_RE = re.compile(
    r"\b(node|nodes|sop|dop|lop|obj|rop|vop|parameter|parameters|parm|parms|"
    r"input|inputs|output|outputs|attribute|attributes|intrinsic|intrinsics)\b",
    re.IGNORECASE,
)
_RAG_VEX_HINT_RE = re.compile(
    r"(@[A-Za-z_]\w*|\b(vex|wrangle|attribwrangle|snippet|orient|pscale|"
    r"quaternion|noise|fit|snoise|curlnoise|vop)\b)",
    re.IGNORECASE,
)
_RAG_USD_HINT_RE = re.compile(
    r"\b(usd|solaris|lop|karma|materialx|stage|prim|scene graph)\b",
    re.IGNORECASE,
)
_RAG_GENERAL_HINT_RE = re.compile(
    r"\b(python|hom|hscript|expression|expressions|variable|variables|function|"
    r"functions|syntax|script|scripts)\b",
    re.IGNORECASE,
)
BUILD_MODE_ALWAYS_DISABLED_TOOLS = {
    "get_error_fix",
    "search_docs",
    "get_vex_snippet",
}
BUILD_MODE_WORKFLOW_TOOLS = {
    "search_knowledge",
    "suggest_workflow",
    "get_node_recipe",
}
_QUERY_TOKEN_RE = re.compile(r"[a-z0-9]+")
BUILD_QUERY_STOPWORDS = {
    "a",
    "an",
    "and",
    "at",
    "center",
    "centre",
    "clean",
    "create",
    "for",
    "from",
    "good",
    "in",
    "into",
    "it",
    "its",
    "make",
    "merged",
    "move",
    "my",
    "nice",
    "of",
    "on",
    "origin",
    "place",
    "please",
    "procedural",
    "procedurally",
    "proper",
    "really",
    "set",
    "simple",
    "some",
    "the",
    "this",
    "to",
    "up",
    "use",
    "using",
    "visible",
    "with",
}
BUILD_QUERY_ACTION_WORDS = {
    "add",
    "adjust",
    "arrange",
    "assign",
    "bevel",
    "build",
    "change",
    "connect",
    "duplicate",
    "extrude",
    "fix",
    "layout",
    "make",
    "model",
    "organize",
    "place",
    "rename",
    "rotate",
    "scale",
    "set",
    "wire",
}
BUILD_QUERY_DESCRIPTOR_WORDS = {
    "bottom",
    "cleaner",
    "complex",
    "detailed",
    "edge",
    "edges",
    "final",
    "four",
    "front",
    "height",
    "large",
    "left",
    "leg",
    "legs",
    "low",
    "medium",
    "right",
    "rounded",
    "smooth",
    "small",
    "surface",
    "tall",
    "thick",
    "thin",
    "top",
    "visible",
    "wide",
    "width",
}
BUILD_QUERY_TECHNICAL_WORDS = {
    "attribwrangle",
    "attribute",
    "attributes",
    "boolean",
    "copy",
    "dop",
    "dopnet",
    "expression",
    "geometry",
    "hscript",
    "input",
    "inputs",
    "lop",
    "material",
    "merge",
    "node",
    "nodes",
    "null",
    "obj",
    "output",
    "outputs",
    "parm",
    "parms",
    "parameter",
    "parameters",
    "python",
    "render",
    "rop",
    "scatter",
    "shader",
    "sim",
    "simulation",
    "sop",
    "solver",
    "stage",
    "usd",
    "uv",
    "vex",
    "vop",
    "wrangle",
}
BUILD_QUERY_PRIMITIVE_WORDS = {
    "box",
    "circle",
    "grid",
    "line",
    "platonic",
    "sphere",
    "tube",
    "torus",
}
STRUCTURAL_SOP_TYPES = {
    "merge",
    "null",
    "output",
    "switch",
    "subnet",
    "object_merge",
}
NON_SEMANTIC_SOP_TYPES = {
    "xform",
    "transform",
    "color",
    "material",
    "name",
    "groupcreate",
}
SIMPLE_PRIMITIVE_SOP_TYPES = {
    "box",
    "circle",
    "grid",
    "line",
    "platonic",
    "sphere",
    "tube",
    "torus",
}


def _query_terms(text: str) -> List[str]:
    return _QUERY_TOKEN_RE.findall(str(text or "").lower())


def _asset_goal_terms(text: str) -> List[str]:
    ordered = []
    seen = set()
    for token in _query_terms(text):
        if (
            token in BUILD_QUERY_STOPWORDS
            or token in BUILD_QUERY_ACTION_WORDS
            or token in BUILD_QUERY_DESCRIPTOR_WORDS
            or token in BUILD_QUERY_TECHNICAL_WORDS
            or token in BUILD_QUERY_PRIMITIVE_WORDS
            or len(token) <= 2
            or token.isdigit()
        ):
            continue
        if token in seen:
            continue
        seen.add(token)
        ordered.append(token)
    return ordered


def _query_needs_workflow_grounding(text: str) -> bool:
    tokens = set(_query_terms(text))
    if not tokens:
        return False
    explicit_workflow_terms = {
        "workflow",
        "recipe",
        "procedural",
        "procedurally",
        "asset",
        "object",
        "structure",
        "furniture",
    }
    if tokens & explicit_workflow_terms:
        return True
    return bool(tokens & _MULTI_PART_BUILD_OBJECTS)


_MULTI_PART_BUILD_OBJECTS = {
    # Furniture — need seat/legs/backrest etc.
    "chair", "stool", "table", "desk", "sofa", "couch", "bed", "bench",
    "shelf", "bookcase", "cabinet", "dresser", "wardrobe",
    # Structures
    "house", "building", "room", "wall", "door", "window", "roof", "bridge",
    "tower", "fence", "gate", "arch",
    # Vehicles
    "car", "truck", "bus", "boat", "ship", "plane", "bicycle", "motorcycle",
    # Props
    "lamp", "bottle", "cup", "mug", "vase", "pot", "crate",
    "barrel", "bucket", "basket", "bag",
    # Characters / anatomy
    "character", "body", "hand", "arm", "leg", "head", "face",
    # Tech
    "robot", "machine", "engine", "pipe", "column", "pillar",
    # Nature / organic
    "tree", "branch", "flower", "rock", "stone",
}


def _query_is_complex(text: str) -> bool:
    words = re.findall(r"[a-z0-9_]+", text.lower())
    if not words:
        return False
    tokens = set(words)

    advanced_terms = {
        "vex",
        "hscript",
        "python",
        "hom",
        "usd",
        "solaris",
        "lop",
        "dop",
        "dopnet",
        "simulation",
        "sim",
        "pdg",
        "tops",
        "karma",
        "materialx",
        "wrangle",
        "attribwrangle",
        "fracture",
        "solver",
        "rbd",
        "bullet",
        "physics",
        "collision",
        "collider",
        "collide",
        "impact",
        "animate",
        "animated",
        "animation",
        "keyframe",
        "vellum",
        "flip",
        "pyro",
        "fluid",
        "smoke",
        "fire",
        "cloth",
    }
    debug_terms = {
        "broken",
        "debug",
        "diagnose",
        "error",
        "errors",
        "failing",
        "fix",
        "issue",
        "issues",
        "missing",
        "problem",
        "problems",
        "repair",
        "stuck",
        "why",
    }

    # Build requests that name a recognisable multi-part object always need
    # planning even if the query is short (e.g. "create a chair" = 3 words).
    multi_part_hits = tokens & _MULTI_PART_BUILD_OBJECTS
    if multi_part_hits:
        # Skip planning for bare "create a <single object>" requests (≤ 5 words).
        # These are straightforward enough that the model builds them correctly
        # without a plan — and the planning round-trip just wastes 45+ seconds.
        if (
            len(multi_part_hits) == 1
            and len(words) <= 5
            and not (tokens & advanced_terms)
            and not (tokens & debug_terms)
        ):
            return False

        simple_modeling_cues = {
            "procedural",
            "visible",
            "out",
            "output",
            "node",
            "nodes",
            "sop",
            "geo",
            "network",
            "obj",
            "basic",
            "simple",
            "quick",
        }
        if (
            len(multi_part_hits) == 1
            and len(words) <= 12
            and (tokens & simple_modeling_cues)
            and not (tokens & advanced_terms)
            and not (tokens & debug_terms)
        ):
            return False
        return True

    if len(words) <= 10 and not (tokens & advanced_terms) and not (tokens & debug_terms):
        return False
    if len(words) >= 18:
        return True
    if tokens & advanced_terms:
        return True
    technical_terms = tokens & (
        BUILD_QUERY_TECHNICAL_WORDS - {"node", "nodes", "null", "obj", "output", "outputs"}
    )
    technical_count = len(technical_terms)
    primitive_count = len(tokens & BUILD_QUERY_PRIMITIVE_WORDS)
    descriptor_count = len(tokens & BUILD_QUERY_DESCRIPTOR_WORDS)
    debug_count = len(tokens & debug_terms)
    return debug_count >= 2 or technical_count >= 2 or (
        len(words) >= 12 and (technical_count + primitive_count + descriptor_count) >= 4
    )


def _build_mode_disabled_tools_for_query(query: str) -> set:
    disabled = set(BUILD_MODE_ALWAYS_DISABLED_TOOLS)
    if not _query_needs_workflow_grounding(query):
        disabled.update(BUILD_MODE_WORKFLOW_TOOLS)
    return disabled


def _ordered_unique_categories(values) -> list:
    ordered = []
    seen = set()
    for value in values or []:
        key = str(value or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        ordered.append(key)
    return ordered


def get_rag_category_policy(request_mode: str, query: str = "") -> dict:
    mode = str(request_mode or "").lower()
    text = str(query or "")

    if mode == "build":
        include = list(BUILD_RAG_INCLUDE_CATEGORIES) + ["nodes"]
        exclude = list(BUILD_RAG_EXCLUDE_CATEGORIES)
    elif mode == "debug":
        include = list(DEBUG_RAG_INCLUDE_CATEGORIES)
        exclude = []
    else:
        return {
            "include_categories": None,
            "exclude_categories": [],
        }

    extras = []
    if _RAG_NODE_HINT_RE.search(text):
        extras.extend(["nodes", "general"])
    if _RAG_VEX_HINT_RE.search(text):
        extras.extend(["vex", "general"])
    if _RAG_USD_HINT_RE.search(text):
        extras.extend(["usd", "nodes"])
    if _RAG_GENERAL_HINT_RE.search(text):
        extras.append("general")

    return {
        "include_categories": _ordered_unique_categories(include + extras),
        "exclude_categories": exclude,
    }


class AutoResearcher:
    RESEARCH_TRIGGERS = re.compile(
        r"\b(how does|explain|what is the best|deep dive|research|"
        r"walk me through|compare|pros and cons|optimise|"
        r"best practice|best way|architecture|design)\b",
        re.IGNORECASE,
    )
    MANUAL_CHOICE_TRIGGERS = re.compile(
        r"\b(compare|comparison|pros and cons|tradeoffs|trade-offs|"
        r"show me options|show options|multiple approaches|three approaches|"
        r"choose an approach|which option|which approach|options?)\b",
        re.IGNORECASE,
    )

    OPTIONS_SENTINEL = "\x00RESEARCH_OPTIONS\x00"

    def __init__(self, llm: OllamaClient, rag=None, max_iterations: int = 1):
        self.llm = llm
        self.rag = rag
        self.max_iterations = max(1, max_iterations)

    @staticmethod
    def is_research_query(text: str) -> bool:
        return bool(AutoResearcher.RESEARCH_TRIGGERS.search(text))

    @staticmethod
    def should_offer_manual_choice(text: str) -> bool:
        return bool(AutoResearcher.MANUAL_CHOICE_TRIGGERS.search(text or ""))

    def run(
        self, query: str, progress_callback: Callable[[str], None] = None
    ) -> List[dict]:
        def _p(msg):
            if progress_callback:
                progress_callback(msg)

        all_context: List[str] = []

        for iteration in range(self.max_iterations):
            label = f"[{iteration + 1}/{self.max_iterations}]"
            _p(f"\u200b\U0001f50d AutoResearch {label} — Decomposing…")

            sub_questions = self._decompose(query, all_context)
            _p(f"\u200b\U0001f4cb {len(sub_questions)} sub-question(s) identified")

            for i, sq in enumerate(sub_questions):
                _p(
                    f"\u200b\U0001f4da Retrieving [{i + 1}/{len(sub_questions)}]: {sq[:60]}…"
                )
                chunk = self._retrieve(sq)
                if chunk and "INSUFFICIENT_DATA" not in chunk:
                    all_context.append(f"Q: {sq}\nA: {chunk}")
                elif chunk:
                    _p(f"\u200b\u26a0\ufe0f  Skipped thin context for: {sq[:40]}…")

            _p(
                f"\u200b\u2699\ufe0f  Synthesising {len(all_context)} chunk(s) into 3 options…"
            )
            options = self._synthesise_options(query, all_context)

            if iteration < self.max_iterations - 1 and len(all_context) >= 2:
                _p(f"\u200b\U0001f9d0 Checking for critical gaps…")
                gaps = self._find_gaps(query, options)
                if not gaps:
                    _p("\u200b\u2705 AutoResearch complete — no gaps")
                    return options
                query = f"{query}\n\nAlso address: {gaps}"
            else:
                _p("\u200b\u2705 AutoResearch complete")

        return options

    def _decompose(self, query: str, existing: List[str]) -> List[str]:
        already = ""
        if existing:
            already = "\n\nAlready retrieved:\n" + "\n".join(
                c.split("\n")[0] for c in existing[:2]
            )
        raw = self.llm.chat_simple(
            system=(
                "You are a Houdini FX research planner.\n"
                "Output EXACTLY 2 sub-questions that together fully cover the user question.\n"
                "Each sub-question must reference specific Houdini nodes, parms, or VEX functions.\n"
                "Output ONLY a numbered list — no preamble, no explanations."
            ),
            user=f"Question: {query}{already}",
            temperature=0.05,
        )
        questions = []
        for line in raw.splitlines():
            clean = re.sub(r"^[\d]+[.)\s]+|^[-*]\s*", "", line.strip()).strip()
            if len(clean) > 10:
                questions.append(clean)
        return questions[:2] or [query]

    def _retrieve(self, sub_q: str) -> str:
        if self.rag:
            try:
                chunks = self.rag.retriever.retrieve(sub_q, top_k=3)
                if chunks:
                    result = "\n\n".join(c.get("content", "") for c in chunks)
                    if result.strip():
                        return result
            except Exception:
                pass

        return self.llm.chat_simple(
            system=(
                "You are a Houdini FX expert.\n"
                "Answer ONLY using facts you are CERTAIN of: real node types "
                "(e.g. flipsolver, gasdissipate, voronoi_fracture), exact parm paths, "
                "and real VEX functions (e.g. volumesample, primuv).\n"
                "If you are NOT certain about a specific detail, write INSUFFICIENT_DATA "
                "for that detail — do NOT guess or invent plausible-sounding names.\n"
                "Max 100 words. No generic advice."
            ),
            user=sub_q,
            temperature=0.05,
        )

    def _synthesise_options(self, original: str, context: List[str]) -> List[dict]:
        context_block = (
            "\n\n".join(context)
            if context
            else "(no RAG context available — use only knowledge you are certain of)"
        )

        raw = self.llm.chat_simple(
            system=(
                "You are a senior Houdini FX TD producing an options report.\n\n"
                "STRICT RULES — violating any rule makes the output unusable:\n"
                "1. Output ONLY valid JSON. No markdown fences, no prose, no preamble.\n"
                "2. The JSON must have EXACTLY this structure:\n"
                '   {"options": [\n'
                '     {"id":1,"label":"<5-7 word title>","summary":"<1 clear sentence>",'
                '"details":"<exact nodes/VEX/parms — max 5 lines>","use_when":"<1 clause>"},\n'
                '     {"id":2,...},\n'
                '     {"id":3,...}\n'
                "   ]}\n"
                "3. The 3 options MUST be meaningfully different approaches "
                "(e.g. fast/simple vs robust/production vs custom/advanced).\n"
                "4. 'details' MUST cite real Houdini node types and exact parm names.\n"
                "5. If you don't know a specific detail, OMIT that sentence entirely.\n"
                "6. No option may say 'it depends' — every option must commit to a specific approach."
            ),
            user=(f"Question: {original}\n\nResearch context:\n{context_block}"),
            temperature=0.1,
        )

        return self._parse_options_json(raw, original)

    def _parse_options_json(self, raw: str, fallback_query: str) -> List[dict]:
        cleaned = re.sub(r"```(?:json)?\n?|```", "", raw).strip()
        json_match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group())
                options = data.get("options", [])
                valid = []
                for opt in options:
                    if isinstance(opt, dict) and "label" in opt and "summary" in opt:
                        opt.setdefault("id", len(valid) + 1)
                        opt.setdefault("details", "")
                        opt.setdefault("use_when", "")
                        valid.append(opt)
                if valid:
                    return valid[:3]
            except (json.JSONDecodeError, KeyError, ValueError):
                pass

        return [
            {
                "id": 1,
                "label": "Research Result",
                "summary": fallback_query[:80],
                "details": raw[:600] if raw else "No details retrieved.",
                "use_when": "Use when no other options are available.",
            }
        ]

    def _find_gaps(self, original: str, options: List[dict]) -> str:
        options_text = "\n".join(
            f"Option {o['id']}: {o['label']} — {o.get('summary', '')}" for o in options
        )
        raw = self.llm.chat_simple(
            system=(
                "You are a critical Houdini FX reviewer.\n"
                "If the options fully cover the question, reply exactly: COMPLETE\n"
                "If one critical aspect is missing, write ONE specific follow-up question "
                "naming the missing node or concept. Do not list multiple gaps."
            ),
            user=f"Question: {original}\n\nOptions presented:\n{options_text}",
            temperature=0.05,
        )
        return "" if "COMPLETE" in raw.upper() else raw.strip()

    @staticmethod
    def _contains_any(text: str, phrases: List[str]) -> bool:
        lowered = (text or "").lower()
        return any(phrase in lowered for phrase in phrases)

    def select_best_option(
        self, query: str, options: List[dict], request_mode: str = "advice"
    ) -> dict:
        if not options:
            return {}

        query_text = (query or "").lower()
        query_wants_variation = self._contains_any(
            query_text,
            [
                "variation",
                "variations",
                "random",
                "randomized",
                "scatter",
                "instancing",
                "instance",
                "copy to points",
                "multiple versions",
                "leg count",
                "counts",
                "different versions",
            ],
        )
        query_wants_lookdev = self._contains_any(
            query_text,
            ["material", "shader", "lookdev", "look dev", "shading", "render"],
        )
        query_wants_controls = self._contains_any(
            query_text,
            ["procedural", "parametric", "controls", "adjustable", "reusable"],
        )

        ranked = []
        for idx, option in enumerate(options):
            label = option.get("label", "")
            summary = option.get("summary", "")
            details = option.get("details", "")
            use_when = option.get("use_when", "")
            text = " ".join([label, summary, details, use_when]).lower()
            detail_lines = [
                line.strip() for line in details.splitlines() if line.strip()
            ]

            score = 0.0
            reasons = []

            if self._contains_any(
                text, ["null", "output", "display flag", "render flag"]
            ):
                score += 2.5
                reasons.append("it already calls out a clear final output")
            if self._contains_any(text, ["merge", "merge sop"]):
                score += 1.0
                reasons.append("it includes a straightforward final merge")

            if request_mode in {"build", "debug"}:
                if self._contains_any(
                    text, ["quick", "simple", "basic", "primitive", "blockout"]
                ):
                    score += 2.0
                    reasons.append("it is the lowest-risk build path")
                if self._contains_any(text, ["transform", "box sop", "null sop"]):
                    score += 1.2
                if detail_lines:
                    score += max(0.0, 1.6 - (0.25 * max(0, len(detail_lines) - 3)))

            if self._contains_any(
                text,
                ["copy to points", "copytopoints", "scatter", "instancing", "instance"],
            ):
                if query_wants_variation:
                    score += 2.0
                    reasons.append("it matches the request for variation or instancing")
                else:
                    score -= 2.2
            if self._contains_any(
                text, ["material", "shader", "shading", "shop_materialpath"]
            ):
                if query_wants_lookdev:
                    score += 1.5
                else:
                    score -= 1.8
            if self._contains_any(text, ["advanced", "custom", "architecture"]):
                score -= 1.0
            if query_wants_controls and self._contains_any(
                text, ["procedural", "control", "reusable", "transform"]
            ):
                score += 1.2

            ranked.append((score, -idx, option, reasons))

        ranked.sort(reverse=True)
        best_score, _neg_idx, best_option, reasons = ranked[0]
        chosen = dict(best_option)
        reason = (
            reasons[0]
            if reasons
            else "it is the best fit for the request with the lowest execution risk"
        )
        chosen["_selection_score"] = round(best_score, 2)
        chosen["_selection_reason"] = reason
        return chosen
