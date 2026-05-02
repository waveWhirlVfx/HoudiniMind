# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
"""
Tool selection helpers for LLM clients.

Keeps keyword maps and relevance scoring out of the transport client so the
core client file stays smaller.
"""

import copy
import re

_PYTHON_TOOL_HINT_RE = re.compile(
    r"\b(python|script|code|loop|iterate|automation|for each|for-each)\b",
    re.IGNORECASE,
)

_TOOL_KEYWORD_MAP = {
    "scene": ["get_scene_summary", "get_current_node_path", "get_hip_info"],
    "error": ["get_all_errors", "deep_error_trace", "get_error_fix"],
    "warning": ["get_all_errors", "check_geometry_issues"],
    "debug": [
        "get_all_errors",
        "deep_error_trace",
        "profile_network",
        "get_node_cook_info",
        "inspect_display_output",
    ],
    "slow": ["profile_network", "measure_cook_time", "get_node_cook_info"],
    "performance": ["profile_network", "measure_cook_time"],
    "create": [
        "create_node",
        "verify_node_type",
        "resolve_build_hints",
        "safe_set_parameter",
        "connect_nodes",
        "set_display_flag",
        "layout_network",
    ],
    "build": [
        "create_node",
        "verify_node_type",
        "resolve_build_hints",
        "safe_set_parameter",
        "connect_nodes",
        "create_node_chain",
        "finalize_sop_network",
        "inspect_display_output",
        "set_display_flag",
    ],
    "delete": ["delete_node", "get_scene_summary"],
    "connect": ["connect_nodes", "disconnect_node", "get_node_inputs"],
    "parameter": [
        "resolve_build_hints",
        "safe_set_parameter",
        "set_parameter",
        "get_node_parameters",
        "batch_set_parameters",
    ],
    "parm": [
        "resolve_build_hints",
        "safe_set_parameter",
        "get_node_parameters",
        "batch_set_parameters",
    ],
    "expression": ["set_expression", "get_node_parameters"],
    "rename": ["rename_node"],
    "duplicate": ["duplicate_node"],
    "bypass": ["bypass_node"],
    "color": ["set_node_color", "create_material", "assign_material"],
    "colour": ["set_node_color", "create_material", "assign_material"],
    "geometry": [
        "analyze_geometry",
        "check_geometry_issues",
        "get_geometry_attributes",
        "sample_geometry",
    ],
    "geo": ["analyze_geometry", "check_geometry_issues", "get_geometry_attributes"],
    "attribute": ["get_geometry_attributes", "sample_geometry", "write_vex_code"],
    "vex": ["write_vex_code", "get_vex_snippet", "search_knowledge"],
    "wrangle": ["write_vex_code", "get_vex_snippet"],
    "python": ["write_python_script", "execute_python"],
    "uv": [
        "create_uv_seams",
        "search_knowledge",
        "get_vex_snippet",
        "setup_fabric_lookdev",
    ],
    "normal": ["check_geometry_issues", "search_knowledge"],
    "bounding": ["get_bounding_box"],
    "sim": [
        "setup_flip_fluid",
        "setup_pyro_sim",
        "setup_rbd_fracture",
        "setup_vellum_cloth",
        "setup_pop_sim",
        "get_simulation_diagnostic",
        "get_dop_objects",
        "get_sim_stats",
    ],
    "simulation": [
        "setup_flip_fluid",
        "setup_pyro_sim",
        "setup_rbd_fracture",
        "setup_vellum_cloth",
        "setup_pop_sim",
        "get_simulation_diagnostic",
        "get_dop_objects",
        "get_sim_stats",
        "get_flip_diagnostic",
        "bake_simulation",
    ],
    "flip": ["setup_flip_fluid", "get_flip_diagnostic", "get_dop_objects"],
    "fluid": ["setup_flip_fluid", "get_flip_diagnostic"],
    "water": ["setup_flip_fluid", "search_knowledge"],
    "pyro": ["setup_pyro_sim", "get_simulation_diagnostic", "get_sim_stats", "search_knowledge"],
    "fire": ["setup_pyro_sim", "search_knowledge"],
    "smoke": ["setup_pyro_sim", "search_knowledge"],
    "rbd": ["setup_rbd_fracture", "get_simulation_diagnostic", "get_dop_objects"],
    "fracture": ["setup_rbd_fracture", "get_simulation_diagnostic", "search_knowledge"],
    "destroy": ["setup_rbd_fracture", "get_simulation_diagnostic", "search_knowledge"],
    "vellum": ["setup_vellum_cloth", "get_simulation_diagnostic", "search_knowledge"],
    "cloth": ["setup_vellum_cloth", "get_simulation_diagnostic", "search_knowledge"],
    "pop": ["setup_pop_sim", "get_sim_stats", "get_dop_objects"],
    "particle": ["setup_pop_sim", "get_sim_stats", "get_dop_objects"],
    "particles": ["setup_pop_sim", "get_sim_stats", "get_dop_objects"],
    "bed": [
        "create_bed_controls",
        "create_node_chain",
        "setup_vellum_pillow",
        "setup_vellum_cloth",
    ],
    "mattress": [
        "create_bed_controls",
        "create_node",
        "safe_set_parameter",
        "create_node_chain",
    ],
    "pillow": ["create_node", "setup_vellum_pillow", "setup_vellum_cloth"],
    "fabric": ["setup_fabric_lookdev", "create_uv_seams", "get_vex_snippet"],
    "duvet": ["create_bed_controls", "setup_vellum_cloth", "setup_fabric_lookdev"],
    "bake": ["bake_simulation"],
    "material": ["create_material", "assign_material", "list_materials"],
    "shader": ["create_material", "assign_material", "list_materials"],
    "texture": ["create_material", "search_knowledge"],
    "materialx": ["create_material", "search_knowledge"],
    "usd": ["get_usd_hierarchy", "create_lop_node"],
    "solaris": ["get_usd_hierarchy", "create_lop_node"],
    "lop": ["get_usd_hierarchy", "create_lop_node"],
    "stage": ["get_usd_hierarchy"],
    "keyframe": ["set_keyframe", "get_timeline_keyframes", "delete_keyframe"],
    "animation": [
        "set_keyframe",
        "get_timeline_keyframes",
        "set_frame_range",
        "go_to_frame",
    ],
    "frame": ["go_to_frame", "set_frame_range", "set_keyframe"],
    "timeline": ["set_frame_range", "get_timeline_keyframes"],
    "shade": [
        "create_material",
        "assign_material",
        "list_materials",
        "setup_fabric_lookdev",
    ],
    "lookdev": [
        "create_material",
        "assign_material",
        "list_materials",
        "setup_fabric_lookdev",
    ],
    "export": ["export_geometry", "save_hip"],
    "save": ["save_hip"],
    "load": ["load_geometry"],
    "import": ["load_geometry"],
    "layout": [
        "layout_network",
        "create_network_box",
        "set_node_color",
        "set_node_comment",
    ],
    "organise": ["layout_network", "create_network_box", "set_node_color"],
    "organize": ["layout_network", "create_network_box", "set_node_color"],
    "subnet": ["create_subnet", "promote_parameter"],
    "hda": ["convert_to_hda", "get_hda_parameters"],
    "explain": [
        "search_knowledge",
        "explain_node_type",
        "suggest_workflow",
        "search_docs",
    ],
    "how": ["search_knowledge", "suggest_workflow", "get_node_recipe"],
    "what": ["search_knowledge", "explain_node_type"],
    "best": ["suggest_workflow", "search_knowledge"],
    "recipe": ["get_node_recipe", "search_knowledge"],
    "camera": ["create_camera", "safe_set_parameter"],
    "render": ["capture_pane", "export_geometry"],
    "screenshot": ["capture_pane"],
    "viewport": ["capture_pane"],
    "output": [
        "inspect_display_output",
        "finalize_sop_network",
        "set_display_flag",
    ],
    "final": [
        "inspect_display_output",
        "finalize_sop_network",
        "set_display_flag",
    ],
    "merge": ["create_node_chain", "connect_nodes", "finalize_sop_network"],
    "spatial": ["audit_spatial_layout", "get_bounding_box"],
    "position": ["safe_set_parameter", "audit_spatial_layout"],
    "move": ["safe_set_parameter", "audit_spatial_layout"],
    "_always": [
        "get_scene_summary",
        "create_node",
        "safe_set_parameter",
        "connect_nodes",
        "verify_node_type",
        "layout_network",
        "get_node_parameters",
        "get_all_errors",
        "search_knowledge",
        "audit_spatial_layout",
        "batch_set_parameters",
        "create_node_chain",
        "set_display_flag",
        "finalize_sop_network",
        "save_hip",
    ],
}


def _is_small_local_model(model_name: str) -> bool:
    lowered = str(model_name or "").lower()
    return any(tag in lowered for tag in ("2b", "3b", "4b", "tiny", "small"))


def select_relevant_tool_schemas(
    query: str,
    all_schemas: list,
    top_n: int,
    embed_fn=None,
    config: dict | None = None,
    model_name: str = "",
) -> list:
    config = dict(config or {})
    top_n = max(1, int(top_n or 1))
    q_lower = (query or "").lower()
    allow_execute_python = bool(_PYTHON_TOOL_HINT_RE.search(query or ""))

    schema_by_name = {s.get("function", {}).get("name"): s for s in all_schemas}
    selected_names: list = []

    for keyword, tools in _TOOL_KEYWORD_MAP.items():
        if keyword == "_always":
            continue
        if keyword in q_lower:
            for t in tools:
                if t not in selected_names:
                    selected_names.append(t)
    for t in _TOOL_KEYWORD_MAP["_always"]:
        if t not in selected_names:
            selected_names.append(t)

    if len(selected_names) < top_n:
        remaining = [n for n in schema_by_name if n not in selected_names]
        if not allow_execute_python:
            remaining = [n for n in remaining if n != "execute_python"]
        q_vec = embed_fn(query) if callable(embed_fn) else None
        if q_vec and remaining:
            scored = []
            for name in remaining:
                schema = schema_by_name.get(name, {})
                desc = schema.get("function", {}).get("description", name)
                tool_vec = embed_fn(desc) if callable(embed_fn) else None
                if tool_vec:
                    scored.append((name, _cosine(q_vec, tool_vec)))
            scored.sort(key=lambda x: x[1], reverse=True)
            for name, _ in scored[: top_n - len(selected_names)]:
                selected_names.append(name)
        else:
            for name in remaining[: top_n - len(selected_names)]:
                selected_names.append(name)

    if not allow_execute_python:
        selected_names = [n for n in selected_names if n != "execute_python"]

    strip_descs = bool(config.get("schema_strip_descriptions", False))

    result = []
    for name in selected_names:
        if len(result) >= top_n:
            break
        if name in schema_by_name:
            schema = copy.deepcopy(schema_by_name[name])
            if strip_descs:
                if "description" in schema.get("function", {}):
                    schema["function"].pop("description", None)
                props = schema.get("function", {}).get("parameters", {}).get("properties", {})
                for p_val in props.values():
                    if "description" in p_val:
                        p_val.pop("description", None)
            result.append(schema)
    return result


def _cosine(a: list, b: list) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    mag_a = sum(x * x for x in a) ** 0.5
    mag_b = sum(x * x for x in b) ** 0.5
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)
