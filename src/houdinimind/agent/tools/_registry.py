# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
"""
HoudiniMind — Tool Registry
The backbone of the modular tools/ directory.
All sub-modules import from here via `_core.py`.

This module:
1. Imports ALL tool functions from all sub-modules
2. Builds TOOL_FUNCTIONS dict and TOOL_SCHEMAS list
3. Populates lazy registries in `_core.py`
4. Sets safety tier sets
5. Re-exports everything for backward compatibility

Import order matters here — _registry.py must import AFTER all sub-modules
so that the registry population happens last.
"""

import inspect

from . import _core as core
from ._advanced_tools import (
    add_hda_parameters,
    analyze_vdb,
    auto_color_by_type,
    bake_expressions_to_keys,
    collapse_to_subnet,
    convert_network_to_hda,
    convert_to_hda,
    cook_network_range,
    copy_paste_nodes,
    create_documentation_snapshot,
    create_hda_with_parameters,
    create_take,
    diff_hda_versions,
    edit_animation_curve,
    eval_hscript,
    get_cook_dependency_order,
    get_hda_parameters,
    get_packed_geo_info,
    get_parm_expression_audit,
    list_all_file_references,
    list_installed_hdas,
    list_takes,
    list_vdb_grids,
    lock_node,
    reload_hda_definition,
    remap_file_paths,
    scan_missing_files,
    set_object_visibility,
    set_viewport_camera,
    set_viewport_display_mode,
    setup_crowd_sim,
    setup_feather_sim,
    setup_grain_sim,
    setup_render_output,
    setup_wire_solver,
    submit_render,
    switch_take,
    watch_node_events,
    write_vop_network,
)
from ._chain_tools import (
    add_spare_parameters,
    add_sticky_note,
    auto_connect_chain,
    create_bed_controls,
    create_network_box,
    create_node_chain,
    create_subnet,
    layout_network,
    promote_parameter,
    set_node_color,
    set_node_comment,
)
from ._geometry_tools import (
    analyze_geometry,
    audit_network_layout,
    batch_align_to_support,
    check_geometry_issues,
    create_transformed_node,
    get_bounding_box,
    get_parameter_details,
    get_stacking_offset,
    sample_geometry,
)
from ._inspection_tools import (
    find_nodes,
    get_current_node_path,
    get_geometry_attributes,
    get_node_inputs,
    get_node_parameters,
    inspect_display_output,
    measure_cook_time,
)
from ._knowledge_tools import (
    explain_node_type,
    get_error_fix,
    get_node_recipe,
    get_vex_snippet,
    search_knowledge,
    suggest_workflow,
)
from ._material_usd_tools import (
    assign_material,
    assign_usd_material,
    create_lop_node,
    create_material,
    create_usd_light,
    create_uv_seams,
    get_usd_hierarchy,
    get_usd_prim_attributes,
    list_material_assignments,
    list_materials,
    setup_aov_passes,
    setup_fabric_lookdev,
    setup_karma_material,
    validate_usd_stage,
)
from ._node_tools import (
    bypass_node,
    connect_nodes,
    create_node,
    delete_node,
    disconnect_node,
    execute_python,
    finalize_sop_network,
    list_node_types,
    resolve_build_hints,
    safe_set_parameter,
    set_display_flag,
    set_expression,
    set_expression_from_description,
    set_multiparm_count,
    set_parameter,
    verify_node_type,
    write_python_script,
    write_vex_code,
)
from ._pdg_tools import (
    create_file_cache_top,
    create_python_script_top,
    create_top_network,
    create_top_node,
    get_pdg_work_items,
    submit_pdg_cook,
)
from ._perf_org_tools import (
    audit_spatial_layout,
    batch_set_parameters,
    compare_nodes,
    create_camera,
    deep_error_trace,
    delete_keyframe,
    duplicate_node,
    export_geometry,
    find_and_replace_parameter,
    fix_furniture_legs,
    get_memory_usage,
    get_node_cook_info,
    get_timeline_keyframes,
    go_to_frame,
    load_geometry,
    profile_network,
    rename_node,
    set_frame_range,
    set_keyframe,
    suggest_optimization,
    take_node_snapshot,
)
from ._repair import (
    suggest_node_repairs,
)
from ._scene_tools import (
    create_backup,
    get_all_errors,
    get_hip_info,
    get_scene_summary,
    restore_backup,
    save_hip,
)
from ._simulation_tools import (
    bake_simulation,
    get_dop_objects,
    get_flip_diagnostic,
    get_sim_stats,
    get_simulation_diagnostic,
    setup_flip_fluid,
    setup_pyro_sim,
    setup_rbd_fracture,
    setup_vellum_cloth,
    setup_vellum_pillow,
)
from ._vision_tools import (
    capture_pane,
    render_quad_views,
    render_scene_view,
    render_with_camera,
    search_docs,
)

TOOL_FUNCTIONS = {
    "create_backup": create_backup,
    "restore_backup": restore_backup,
    "verify_node_type": verify_node_type,
    "list_node_types": list_node_types,
    "resolve_build_hints": resolve_build_hints,
    "get_scene_summary": get_scene_summary,
    "get_all_errors": get_all_errors,
    "get_node_parameters": get_node_parameters,
    "get_node_inputs": get_node_inputs,
    "get_geometry_attributes": get_geometry_attributes,
    "inspect_display_output": inspect_display_output,
    "get_current_node_path": get_current_node_path,
    "find_nodes": find_nodes,
    "measure_cook_time": measure_cook_time,
    "analyze_geometry": analyze_geometry,
    "get_bounding_box": get_bounding_box,
    "sample_geometry": sample_geometry,
    "check_geometry_issues": check_geometry_issues,
    "audit_network_layout": audit_network_layout,
    "audit_spatial_layout": audit_spatial_layout,
    "fix_furniture_legs": fix_furniture_legs,
    "create_node_chain": create_node_chain,
    "create_subnet": create_subnet,
    "auto_connect_chain": auto_connect_chain,
    "promote_parameter": promote_parameter,
    "set_node_color": set_node_color,
    "set_node_comment": set_node_comment,
    "create_network_box": create_network_box,
    "create_node": create_node,
    "delete_node": delete_node,
    "safe_set_parameter": safe_set_parameter,
    "set_parameter": set_parameter,
    "add_spare_parameters": add_spare_parameters,
    "set_expression": set_expression,
    "set_expression_from_description": set_expression_from_description,
    "connect_nodes": connect_nodes,
    "disconnect_node": disconnect_node,
    "bypass_node": bypass_node,
    "set_display_flag": set_display_flag,
    "set_multiparm_count": set_multiparm_count,
    "finalize_sop_network": finalize_sop_network,
    "write_vex_code": write_vex_code,
    "write_python_script": write_python_script,
    "execute_python": execute_python,
    "create_material": create_material,
    "assign_material": assign_material,
    "list_materials": list_materials,
    "setup_fabric_lookdev": setup_fabric_lookdev,
    "create_uv_seams": create_uv_seams,
    "get_usd_hierarchy": get_usd_hierarchy,
    "create_lop_node": create_lop_node,
    "profile_network": profile_network,
    "deep_error_trace": deep_error_trace,
    "get_node_cook_info": get_node_cook_info,
    "collapse_to_subnet": collapse_to_subnet,
    "convert_to_hda": convert_to_hda,
    "convert_network_to_hda": convert_network_to_hda,
    "create_hda_with_parameters": create_hda_with_parameters,
    "add_hda_parameters": add_hda_parameters,
    "get_hda_parameters": get_hda_parameters,
    "search_knowledge": search_knowledge,
    "get_vex_snippet": get_vex_snippet,
    "get_node_recipe": get_node_recipe,
    "explain_node_type": explain_node_type,
    "suggest_workflow": suggest_workflow,
    "get_error_fix": get_error_fix,
    "export_geometry": export_geometry,
    "get_hip_info": get_hip_info,
    "find_and_replace_parameter": find_and_replace_parameter,
    "save_hip": save_hip,
    "set_keyframe": set_keyframe,
    "set_frame_range": set_frame_range,
    "go_to_frame": go_to_frame,
    "layout_network": layout_network,
    "create_bed_controls": create_bed_controls,
    "add_sticky_note": add_sticky_note,
    "setup_vellum_cloth": setup_vellum_cloth,
    "setup_vellum_pillow": setup_vellum_pillow,
    "setup_flip_fluid": setup_flip_fluid,
    "get_dop_objects": get_dop_objects,
    "bake_simulation": bake_simulation,
    "get_sim_stats": get_sim_stats,
    "setup_pyro_sim": setup_pyro_sim,
    "setup_rbd_fracture": setup_rbd_fracture,
    "get_simulation_diagnostic": get_simulation_diagnostic,
    "get_flip_diagnostic": get_flip_diagnostic,
    "get_stacking_offset": get_stacking_offset,
    "batch_align_to_support": batch_align_to_support,
    "create_transformed_node": create_transformed_node,
    "duplicate_node": duplicate_node,
    "rename_node": rename_node,
    "load_geometry": load_geometry,
    "batch_set_parameters": batch_set_parameters,
    "compare_nodes": compare_nodes,
    "create_camera": create_camera,
    "take_node_snapshot": take_node_snapshot,
    "delete_keyframe": delete_keyframe,
    "get_timeline_keyframes": get_timeline_keyframes,
    "suggest_node_repairs": suggest_node_repairs,
    "capture_pane": capture_pane,
    "render_scene_view": render_scene_view,
    "render_quad_views": render_quad_views,
    "render_with_camera": render_with_camera,
    "search_docs": search_docs,
    "watch_node_events": watch_node_events,
    "get_parm_expression_audit": get_parm_expression_audit,
    "list_all_file_references": list_all_file_references,
    "scan_missing_files": scan_missing_files,
    "get_cook_dependency_order": get_cook_dependency_order,
    "copy_paste_nodes": copy_paste_nodes,
    "lock_node": lock_node,
    "set_object_visibility": set_object_visibility,
    "cook_network_range": cook_network_range,
    "edit_animation_curve": edit_animation_curve,
    "bake_expressions_to_keys": bake_expressions_to_keys,
    "create_take": create_take,
    "list_takes": list_takes,
    "switch_take": switch_take,
    "analyze_vdb": analyze_vdb,
    "list_vdb_grids": list_vdb_grids,
    "get_packed_geo_info": get_packed_geo_info,
    "remap_file_paths": remap_file_paths,
    "write_vop_network": write_vop_network,
    "eval_hscript": eval_hscript,
    "setup_wire_solver": setup_wire_solver,
    "setup_crowd_sim": setup_crowd_sim,
    "setup_grain_sim": setup_grain_sim,
    "setup_feather_sim": setup_feather_sim,
    "setup_karma_material": setup_karma_material,
    "setup_aov_passes": setup_aov_passes,
    "list_material_assignments": list_material_assignments,
    "setup_render_output": setup_render_output,
    "submit_render": submit_render,
    "set_viewport_camera": set_viewport_camera,
    "set_viewport_display_mode": set_viewport_display_mode,
    "assign_usd_material": assign_usd_material,
    "get_usd_prim_attributes": get_usd_prim_attributes,
    "create_usd_light": create_usd_light,
    "validate_usd_stage": validate_usd_stage,
    "reload_hda_definition": reload_hda_definition,
    "list_installed_hdas": list_installed_hdas,
    "diff_hda_versions": diff_hda_versions,
    "create_documentation_snapshot": create_documentation_snapshot,
    "auto_color_by_type": auto_color_by_type,
    "get_memory_usage": get_memory_usage,
    "suggest_optimization": suggest_optimization,
    "create_top_network": create_top_network,
    "create_top_node": create_top_node,
    "submit_pdg_cook": submit_pdg_cook,
    "get_pdg_work_items": get_pdg_work_items,
    "create_file_cache_top": create_file_cache_top,
    "create_python_script_top": create_python_script_top,
    "get_parameter_details": get_parameter_details,
}


DESTRUCTIVE_TOOLS = {"delete_node", "disconnect_node"}
CONFIRM_TOOLS = {
    "delete_node",
    "disconnect_node",
    "find_and_replace_parameter",
    "convert_to_hda",
    "export_geometry",
    "remap_file_paths",
    "eval_hscript",
    "write_python_script",
}
DANGEROUS_TOOLS = {"execute_python"}
TOOL_SAFETY_TIERS = {tool: "confirm" for tool in CONFIRM_TOOLS}
TOOL_SAFETY_TIERS.update({tool: "dangerous" for tool in DANGEROUS_TOOLS})
BACKUP_BEFORE_TOOLS = {
    "delete_node",
    "disconnect_node",
    "set_parameter",
    "safe_set_parameter",
    "set_expression",
    "set_expression_from_description",
    "connect_nodes",
    "write_vex_code",
    "write_python_script",
    "execute_python",
    "create_node_chain",
    "setup_vellum_cloth",
    "create_material",
    "assign_material",
    "convert_to_hda",
    "find_and_replace_parameter",
    "export_geometry",
    "promote_parameter",
    "remap_file_paths",
    "bake_expressions_to_keys",
    "write_vop_network",
    "setup_wire_solver",
    "setup_crowd_sim",
    "setup_grain_sim",
    "setup_feather_sim",
    "setup_karma_material",
    "setup_aov_passes",
    "submit_pdg_cook",
}


def _infer_schema_type(param: inspect.Parameter) -> str:
    annotation = param.annotation
    if annotation is bool:
        return "boolean"
    if annotation is int:
        return "integer"
    if annotation is float:
        return "number"
    if annotation in (list, tuple):
        return "array"
    if annotation is dict:
        return "object"

    default = param.default
    if isinstance(default, bool):
        return "boolean"
    if isinstance(default, int) and not isinstance(default, bool):
        return "integer"
    if isinstance(default, float):
        return "number"
    if isinstance(default, (list, tuple)):
        return "array"
    if isinstance(default, dict):
        return "object"
    return "string"


def _build_fallback_schema(tool_name: str, fn) -> dict:
    description = (
        (inspect.getdoc(fn) or f"{tool_name.replace('_', ' ').title()}.").strip().splitlines()[0]
    )
    properties = {}
    required = []
    for param in inspect.signature(fn).parameters.values():
        if param.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue
        schema = {"type": _infer_schema_type(param)}
        if param.default is inspect._empty:
            required.append(param.name)
        else:
            default = param.default
            if isinstance(default, tuple):
                default = list(default)
            if default is not None:
                schema["default"] = default
        properties[param.name] = schema

    parameters = {"type": "object", "properties": properties}
    if required:
        parameters["required"] = required
    return {
        "type": "function",
        "function": {
            "name": tool_name,
            "description": description,
            "parameters": parameters,
        },
    }


TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "verify_node_type",
            "description": "ALWAYS call before create_node if unsure of the internal type string. Checks alias table (catches polybevel2→polybevel) and live Houdini registry. Returns canonical_type and suggestion. IMPORTANT: Pass the real existing parent_path for the node you are checking; use '/obj' first if the geo container does not exist yet.",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_type": {"type": "string"},
                    "parent_path": {"type": "string", "default": "/obj"},
                },
                "required": ["node_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_node_types",
            "description": "List all valid internal type strings for a node category. Use when create_node fails.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": ["sop", "dop", "obj", "lop", "vop", "rop"],
                        "default": "sop",
                    },
                    "filter_pattern": {"type": "string", "default": ""},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_scene_summary",
            "description": "Full scan of all scene networks, errors-first.",
            "parameters": {
                "type": "object",
                "properties": {"depth": {"type": "integer", "default": 3}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_all_errors",
            "description": "Fast triage — returns ONLY nodes with errors/warnings. Use first when debugging.",
            "parameters": {
                "type": "object",
                "properties": {"include_warnings": {"type": "boolean", "default": True}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_node_parameters",
            "description": "Read all parameter values for a node.",
            "parameters": {
                "type": "object",
                "properties": {"node_path": {"type": "string"}},
                "required": ["node_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_node_inputs",
            "description": "Check input connections and red-arrow errors.",
            "parameters": {
                "type": "object",
                "properties": {"node_path": {"type": "string"}},
                "required": ["node_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_geometry_attributes",
            "description": "Read detail/point/prim attributes from a SOP node.",
            "parameters": {
                "type": "object",
                "properties": {"node_path": {"type": "string"}},
                "required": ["node_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inspect_display_output",
            "description": "Cheap final-output inspector. Resolves the currently visible/renderable output under a GEO/network, returns the actual geometry node path, point/prim counts, and any node errors. Prefer this over broad scene scans when you just need to confirm the final result.",
            "parameters": {
                "type": "object",
                "properties": {"parent_path": {"type": "string"}},
                "required": ["parent_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_node_path",
            "description": "Get the currently selected or context node path.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_nodes",
            "description": "Search scene for nodes by name, type, or error state.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "default": "*"},
                    "node_type": {"type": "string"},
                    "has_errors": {"type": "boolean", "default": False},
                    "root": {"type": "string", "default": "/"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "measure_cook_time",
            "description": "Force-cook a node and measure cook time in milliseconds.",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_path": {"type": "string"},
                    "num_frames": {"type": "integer", "default": 1},
                },
                "required": ["node_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_geometry",
            "description": "Deep geometric analysis: bounding box, poly counts, attribute inventory, UVs, normals, memory estimate. Call before making modelling decisions.",
            "parameters": {
                "type": "object",
                "properties": {"node_path": {"type": "string"}},
                "required": ["node_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_bounding_box",
            "description": "Return bounding box (min/max/size/centre/diagonal) of a node's geometry.",
            "parameters": {
                "type": "object",
                "properties": {"node_path": {"type": "string"}},
                "required": ["node_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sample_geometry",
            "description": "Sample a random subset of points and their attribute values. Use to understand data flowing through a node before writing VEX.",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_path": {"type": "string"},
                    "num_points": {"type": "integer", "default": 10},
                    "attributes": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["node_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_geometry_issues",
            "description": "Quality check: zero-area prims, NaN points, non-manifold, unreferenced points. Run before Boolean or Vellum setups.",
            "parameters": {
                "type": "object",
                "properties": {"node_path": {"type": "string"}},
                "required": ["node_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "audit_network_layout",
            "description": "Check for nodes that are overlapping or too close in the network editor. Returns a list of overlapping node pairs and their distances.",
            "parameters": {
                "type": "object",
                "properties": {
                    "parent_path": {"type": "string"},
                    "threshold": {"type": "number", "default": 10.0},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_node_chain",
            "description": "Create and wire a sequence of nodes in ONE call. Pass a chain list with type, name, parms dict, optional inputs array (names of nodes in chain to wire into this node), and optional vex string per step. Primitive generators (box, sphere, etc) do NOT auto-wire. Merge nodes AUTO-GATHER all unwired nodes in the chain.",
            "parameters": {
                "type": "object",
                "properties": {
                    "parent_path": {"type": "string"},
                    "chain": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string"},
                                "name": {"type": "string"},
                                "parms": {"type": "object"},
                                "vex": {"type": "string"},
                                "inputs": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                        },
                    },
                },
                "required": ["parent_path", "chain"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_subnet",
            "description": "Create a subnet and optionally move existing nodes inside it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "parent_path": {"type": "string"},
                    "name": {"type": "string"},
                    "nodes_inside": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["parent_path", "name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "auto_connect_chain",
            "description": "Connect an already-existing list of node paths in sequence (0→1→2→...).",
            "parameters": {
                "type": "object",
                "properties": {"node_paths": {"type": "array", "items": {"type": "string"}}},
                "required": ["node_paths"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "promote_parameter",
            "description": "Promote a parameter up N levels to the parent subnet with a channel reference. Essential for non-destructive HDA-style workflows.",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_path": {"type": "string"},
                    "parm_name": {"type": "string"},
                    "label": {"type": "string"},
                    "target_levels": {"type": "integer", "default": 1},
                },
                "required": ["node_path", "parm_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_node_color",
            "description": "Set the network editor colour of a node. Pass r/g/b as separate floats (0-1) OR pass color as a list [r,g,b]. Example: {node_path: '/obj/geo1/box', r: 0.8, g: 0.4, b: 0.2}",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_path": {"type": "string"},
                    "r": {"type": "number", "description": "Red 0-1"},
                    "g": {"type": "number", "description": "Green 0-1"},
                    "b": {"type": "number", "description": "Blue 0-1"},
                    "color": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "Alternative: [r, g, b] list",
                    },
                },
                "required": ["node_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_node_comment",
            "description": "Attach a visible comment string to a node in the network editor.",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_path": {"type": "string"},
                    "comment": {"type": "string"},
                },
                "required": ["node_path", "comment"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_network_box",
            "description": "Create a labelled network box around a group of nodes for visual organisation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "parent_path": {"type": "string"},
                    "node_paths": {"type": "array", "items": {"type": "string"}},
                    "label": {"type": "string", "default": ""},
                    "color": {
                        "type": "array",
                        "items": {"type": "number"},
                        "default": [0.2, 0.2, 0.2],
                    },
                },
                "required": ["parent_path", "node_paths"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_node",
            "description": "Create a new node. CRITICAL: SOPs (box, sphere, merge, etc) CANNOT be created directly in '/obj'. If the scene is empty, first create a 'geo' node in '/obj'. Only after that should you create SOPs inside the new geo container (for example parent_path='/obj/geo1').",
            "parameters": {
                "type": "object",
                "properties": {
                    "parent_path": {"type": "string"},
                    "node_type": {"type": "string"},
                    "name": {"type": "string"},
                },
                "required": ["parent_path", "node_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_node",
            "description": (
                "Permanently remove a Houdini node from the network. "
                "Use this to clean up stale, unwanted, or incorrectly created nodes. "
                "IMPORTANT: This destroys the node and all its connections — it cannot be undone via the agent. "
                "Do NOT confuse with the 'delete' SOP type — that is a geometry filter, not a node-removal tool. "
                "Example: delete_node('/obj/geo1/sphere1') removes the sphere1 SOP node."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "node_path": {
                        "type": "string",
                        "description": "Absolute path to the node to delete, e.g. '/obj/geo1/sphere1'",
                    },
                },
                "required": ["node_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "safe_set_parameter",
            "description": "Safely set a parameter value with alias handling and vector-component expansion (for example size -> sizex/y/z). Prefer this over raw parameter writes when the name may be fuzzy.",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_path": {"type": "string"},
                    "parm_name": {"type": "string"},
                    "value": {},
                },
                "required": ["node_path", "parm_name", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_parameter",
            "description": "Set a parameter to a literal value. Ensure the parameter name is precisely matched.",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_path": {"type": "string", "description": "Absolute path to the node"},
                    "parm_name": {
                        "type": "string",
                        "description": "Exact internal name of the parameter",
                    },
                    "value": {},
                },
                "required": ["node_path", "parm_name", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_spare_parameters",
            "description": "Dynamically add new custom parameters (sliders, toggles, etc.) to a node. Mandatory for Rule 11 (Control Hubs).",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_path": {"type": "string"},
                    "params": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "label": {"type": "string"},
                                "type": {
                                    "type": "string",
                                    "enum": [
                                        "float",
                                        "int",
                                        "toggle",
                                        "string",
                                        "color",
                                    ],
                                    "default": "float",
                                },
                                "default": {"type": "number"},
                                "min": {"type": "number"},
                                "max": {"type": "number"},
                            },
                            "required": ["name"],
                        },
                    },
                },
                "required": ["node_path", "params"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_expression_from_description",
            "description": "Translate a natural language description (e.g. 'sine wave based on time') into a valid Houdini expression and apply it to a parameter.",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_path": {"type": "string"},
                    "parm_name": {"type": "string"},
                    "description": {"type": "string"},
                    "language": {
                        "type": "string",
                        "enum": ["hscript", "python"],
                        "default": "hscript",
                    },
                },
                "required": ["node_path", "parm_name", "description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "connect_nodes",
            "description": "Connect one node output to another node input.",
            "parameters": {
                "type": "object",
                "properties": {
                    "from_path": {"type": "string"},
                    "to_path": {"type": "string"},
                    "from_out": {"type": "integer", "default": 0},
                    "to_in": {"type": "integer", "default": 0},
                },
                "required": ["from_path", "to_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_display_flag",
            "description": "Set the display and optional render flag on a node so the intended result is visible.",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_path": {"type": "string"},
                    "display": {"type": "boolean", "default": True},
                    "render": {"type": "boolean"},
                },
                "required": ["node_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_multiparm_count",
            "description": "Explicitly set the size of a multiparm block (e.g. number of points in an Add SOP, or number of rules in an L-System). Call this before trying to set individual block parameters if they don't exist yet.",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_path": {"type": "string"},
                    "parm_name": {
                        "type": "string",
                        "description": "The name of the parameter that controls the count (e.g. 'points' for Add SOP).",
                    },
                    "count": {"type": "integer"},
                },
                "required": ["node_path", "parm_name", "count"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finalize_sop_network",
            "description": "Ensure a SOP network ends in a visible final OUT node, creating or reusing merge/output structure when needed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "parent_path": {"type": "string"},
                    "output_name": {"type": "string", "default": "OUT"},
                    "merge_name": {"type": "string", "default": "MERGE_FINAL"},
                },
                "required": ["parent_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_python_script",
            "description": "Write Python code into a Python Script SOP and cook it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_path": {"type": "string"},
                    "code": {"type": "string"},
                },
                "required": ["node_path", "code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "execute_python",
            "description": "Execute Python code in the Houdini session. Use only when the user explicitly wants Python code run.",
            "parameters": {
                "type": "object",
                "properties": {"code": {"type": "string"}},
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_materials",
            "description": "List all materials in /mat and /shop.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "setup_fabric_lookdev",
            "description": "High-level Fabric Lookdev wizard. Adds UV Flatten, creates a Principled Shader with fabric presets (high roughness), and assigns it to the geometry.",
            "parameters": {
                "type": "object",
                "properties": {
                    "parent_path": {"type": "string"},
                    "geo_node_path": {"type": "string"},
                    "base_color": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 3,
                        "maxItems": 3,
                        "default": [0.7, 0.7, 0.7],
                    },
                    "texture_path": {"type": "string"},
                },
                "required": ["parent_path", "geo_node_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_usd_hierarchy",
            "description": "Walk and return the USD prim hierarchy at a LOP node. Use before adding materials or lights to Solaris.",
            "parameters": {
                "type": "object",
                "properties": {
                    "lop_node_path": {"type": "string"},
                    "max_depth": {"type": "integer", "default": 4},
                },
                "required": ["lop_node_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_lop_node",
            "description": "Create a LOP (Solaris/USD) node with alias correction and optional parms.",
            "parameters": {
                "type": "object",
                "properties": {
                    "parent_path": {"type": "string"},
                    "node_type": {"type": "string"},
                    "name": {"type": "string"},
                    "parms": {"type": "object"},
                },
                "required": ["parent_path", "node_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "profile_network",
            "description": "Cook every node in a network and return a leaderboard of slowest nodes. Essential for optimisation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "parent_path": {"type": "string"},
                    "top_n": {"type": "integer", "default": 10},
                },
                "required": ["parent_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "deep_error_trace",
            "description": "Trace errors upstream from a failing node to find the ROOT CAUSE. Returns ordered chain from origin → symptom.",
            "parameters": {
                "type": "object",
                "properties": {"start_node_path": {"type": "string"}},
                "required": ["start_node_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_node_cook_info",
            "description": "Get cook state: dirty, time-dependent, bypassed, locked, errors, cook count.",
            "parameters": {
                "type": "object",
                "properties": {"node_path": {"type": "string"}},
                "required": ["node_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "collapse_to_subnet",
            "description": (
                "Collapse a list of loose SOP nodes inside a geo network into a single subnet node. "
                "REQUIRED step before convert_to_hda or create_hda_with_parameters — those tools "
                "need a subnet as input, not individual SOPs. "
                "Call this first, then pass the returned subnet_path to create_hda_with_parameters. "
                "All wiring to/from the collapsed nodes is preserved automatically."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "parent_path": {
                        "type": "string",
                        "description": "Path to the SOP network containing the nodes, e.g. '/obj/geo1'",
                    },
                    "node_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Names of nodes to collapse, e.g. ['left_rail', 'right_rail', 'rung_template', 'rung_points', 'copy_rungs', 'merge1', 'OUT']",
                    },
                    "subnet_name": {
                        "type": "string",
                        "description": "Name for the new subnet node (default 'subnet1')",
                        "default": "subnet1",
                    },
                },
                "required": ["parent_path", "node_names"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "convert_to_hda",
            "description": (
                "Convert SOP nodes to an HDA digital asset and save to disk. "
                "TWO MODES: "
                "(1) Subnet already exists: pass node_path='/obj/geo1/my_subnet'. "
                "(2) Loose SOPs (most common after a build): pass node_path='/obj/geo1' (the parent geo) "
                "AND node_names=['left_rail','right_rail',...] — the tool auto-collapses then converts. "
                "After conversion use add_hda_parameters to expose parms. "
                "Uses node.createDigitalAsset() — the correct H19/H20 API."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "node_path": {
                        "type": "string",
                        "description": "Path to the subnet '/obj/geo1/my_subnet' OR the parent geo '/obj/geo1' when node_names is provided",
                    },
                    "hda_name": {
                        "type": "string",
                        "description": "Internal HDA type name (no spaces), e.g. 'ladder_hda'",
                    },
                    "hda_label": {
                        "type": "string",
                        "description": "Human-readable label shown in Houdini TAB menu",
                    },
                    "node_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Names of loose SOP nodes to collapse before converting. Use when nodes are not yet in a subnet, e.g. ['left_rail','right_rail','rung_template','rung_points','copy_rungs','merge1','OUT']",
                    },
                    "save_path": {
                        "type": "string",
                        "description": "Directory to save the .hda file (default: $HOME/houdini20.5/otls)",
                    },
                    "version": {"type": "string", "default": "1.0"},
                    "min_inputs": {"type": "integer", "default": 0},
                    "max_inputs": {"type": "integer", "default": 1},
                },
                "required": ["node_path", "hda_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "convert_network_to_hda",
            "description": (
                "The ROBUST, PREFERRED tool for converting a network of loose SOP nodes into a fully procedural HDA. "
                "This tool performs a complete one-shot conversion: it scans the provided nodes for user-meaningful "
                "parameters (dimensions, toggles, custom expressions), collapses the nodes into a subnet, converts "
                "the subnet to an HDA, auto-builds the parameter interface, and wires all internal ch() links automatically. "
                "Always use this when the user asks to 'convert this to an HDA'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "parent_path": {
                        "type": "string",
                        "description": "Path to the geo/SOP network containing the nodes, e.g. '/obj/geo1'",
                    },
                    "node_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Names of loose SOP nodes to convert, e.g. ['left_rail','right_rail','copy_rungs','OUT']",
                    },
                    "hda_name": {
                        "type": "string",
                        "description": "Internal HDA type name (no spaces), e.g. 'ladder_hda'",
                    },
                    "hda_label": {
                        "type": "string",
                        "description": "Human-readable label shown in Houdini TAB menu",
                    },
                    "save_path": {
                        "type": "string",
                        "description": "Directory to save the .hda file (default: $HOME/houdini20.5/otls)",
                    },
                    "auto_link": {
                        "type": "boolean",
                        "description": "If true (default), automatically discovers, promotes, and links meaningful parameters from the internal nodes.",
                        "default": True,
                    },
                },
                "required": ["parent_path", "node_names", "hda_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_hda_with_parameters",
            "description": (
                "One-shot HDA creation: converts a SOP subnet to an HDA AND immediately adds "
                "a full parameter interface with ch() links wired to internal nodes. "
                "Preferred over calling convert_to_hda + add_hda_parameters separately. "
                "IMPORTANT: subnet_path MUST be inside a SOP network (e.g. '/obj/geo1/ladder_subnet'), "
                "NOT at /obj directly. "
                "Use 'link_to' in each parameter to wire the HDA parm to the matching internal node parm. "
                "Use this when creating ladder, staircase, railing, or any procedural prop HDA."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "subnet_path": {
                        "type": "string",
                        "description": "Path to the subnet inside a SOP network, e.g. '/obj/geo1/ladder_subnet' (NOT '/obj/ladder_subnet')",
                    },
                    "hda_name": {
                        "type": "string",
                        "description": "Internal type name (no spaces), e.g. 'ladder_hda'",
                    },
                    "hda_label": {
                        "type": "string",
                        "description": "Human-readable label, e.g. 'Procedural Ladder'",
                    },
                    "parameters": {
                        "type": "array",
                        "description": "List of parameter descriptors. Use 'link_to' to wire each HDA parm to an internal node parm via ch().",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "label": {"type": "string"},
                                "type": {
                                    "type": "string",
                                    "enum": ["float", "int", "toggle", "menu", "string"],
                                },
                                "default": {},
                                "min": {"type": "number"},
                                "max": {"type": "number"},
                                "help": {"type": "string"},
                                "link_to": {
                                    "type": "object",
                                    "description": "Wire this HDA parm to an internal node parm via ch(). Path is relative to the HDA node root.",
                                    "properties": {
                                        "node": {
                                            "type": "string",
                                            "description": "Relative path to the internal node, e.g. 'staircase_sop' or 'subnet1/copy1'",
                                        },
                                        "parm": {
                                            "type": "string",
                                            "description": "Parameter name on that node, e.g. 'steps'",
                                        },
                                    },
                                    "required": ["node", "parm"],
                                },
                                "menu_items": {"type": "array", "items": {"type": "string"}},
                                "menu_labels": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["name", "type"],
                        },
                    },
                    "save_path": {"type": "string"},
                    "version": {"type": "string", "default": "1.0"},
                },
                "required": ["subnet_path", "hda_name", "hda_label", "parameters"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_hda_parameters",
            "description": (
                "Add parameters to an existing HDA definition and wire them to internal node parms via ch(). "
                "Safe to call multiple times — duplicate names are skipped. "
                "Use 'link_to' in each parameter to create ch() expressions automatically. "
                "Use after convert_to_hda when you want to add parms incrementally."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "node_path": {"type": "string", "description": "Path to the HDA node instance"},
                    "parameters": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "label": {"type": "string"},
                                "type": {
                                    "type": "string",
                                    "enum": ["float", "int", "toggle", "menu", "string"],
                                },
                                "default": {},
                                "min": {"type": "number"},
                                "max": {"type": "number"},
                                "help": {"type": "string"},
                                "link_to": {
                                    "type": "object",
                                    "description": "Wire this HDA parm to an internal node parm via ch(). Path is relative to the HDA node root.",
                                    "properties": {
                                        "node": {"type": "string"},
                                        "parm": {"type": "string"},
                                    },
                                    "required": ["node", "parm"],
                                },
                                "menu_items": {"type": "array", "items": {"type": "string"}},
                                "menu_labels": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["name", "type"],
                        },
                    },
                },
                "required": ["node_path", "parameters"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_hda_parameters",
            "description": "List all interface parameters on an HDA: name, label, type, default, current value.",
            "parameters": {
                "type": "object",
                "properties": {"node_path": {"type": "string"}},
                "required": ["node_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_knowledge",
            "description": "Search the HoudiniMind knowledge base strictly for SPECIFIC TECHNICAL DETAILS (node parameters, internal names, VEX functions, and error fixes). DO NOT query for high-level project workflows, tutorials, or step-by-step guides (e.g. do NOT ask 'how to build a bed'). Use this when you need technical reference for a specific node type.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "top_k": {"type": "integer", "default": 5},
                    "category_filter": {
                        "type": "string",
                        "enum": [
                            "vex",
                            "recipe",
                            "errors",
                            "best_practice",
                            "workflow",
                        ],
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_vex_snippet",
            "description": "Get ready-to-use VEX code snippets for a task (noise, copy-stamp, group by normal, etc). Returns snippets from the knowledge base.",
            "parameters": {
                "type": "object",
                "properties": {"task": {"type": "string"}},
                "required": ["task"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_node_recipe",
            "description": "Get a step-by-step node chain recipe for a common Houdini workflow. NOTE: The local knowledge database primarily contains technical node data. If no full workflow exists, deduce it by querying individual node parameters instead.",
            "parameters": {
                "type": "object",
                "properties": {"workflow": {"type": "string"}},
                "required": ["workflow"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "explain_node_type",
            "description": "Get a plain-English explanation of what a node type does, its key parms, and typical upstream/downstream nodes.",
            "parameters": {
                "type": "object",
                "properties": {"node_type": {"type": "string"}},
                "required": ["node_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "suggest_workflow",
            "description": "Given a plain-English goal, returns recommended node chain. NOTE: Since the knowledge base is optimized for technical parameter data rather than full tutorials, use this tool sparingly and rely on your own spatial reasoning to combine nodes.",
            "parameters": {
                "type": "object",
                "properties": {"goal": {"type": "string"}},
                "required": ["goal"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_error_fix",
            "description": "Given an error message, look up known fixes in the knowledge base and return actionable solutions.",
            "parameters": {
                "type": "object",
                "properties": {"error_message": {"type": "string"}},
                "required": ["error_message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "export_geometry",
            "description": "Export SOP geometry to a file (obj, bgeo, bgeo.sc, abc, usd). Creates directories as needed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_path": {"type": "string"},
                    "file_path": {"type": "string"},
                    "frame": {"type": "integer"},
                },
                "required": ["node_path", "file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_hip_info",
            "description": "Return hip file path, unsaved changes, current frame, FPS, frame range, Houdini version.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_and_replace_parameter",
            "description": "Find-and-replace a string value across all parameters in a network. Useful for bulk path remapping or material renaming.",
            "parameters": {
                "type": "object",
                "properties": {
                    "root_path": {"type": "string"},
                    "search_value": {"type": "string"},
                    "replace_value": {"type": "string"},
                    "parm_name_filter": {"type": "string", "default": ""},
                },
                "required": ["root_path", "search_value", "replace_value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_hip",
            "description": "Save the current hip file.",
            "parameters": {
                "type": "object",
                "properties": {"increment": {"type": "boolean", "default": False}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_keyframe",
            "description": "Set a keyframe on a parameter.",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_path": {"type": "string"},
                    "parm_name": {"type": "string"},
                    "value": {"type": "number"},
                    "frame": {"type": "integer"},
                    "slope_in": {"type": "number"},
                    "slope_out": {"type": "number"},
                },
                "required": ["node_path", "parm_name", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_frame_range",
            "description": "Set global frame range and optionally FPS.",
            "parameters": {
                "type": "object",
                "properties": {
                    "start": {"type": "integer"},
                    "end": {"type": "integer"},
                    "fps": {"type": "number"},
                },
                "required": ["start", "end"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "go_to_frame",
            "description": "Jump to a specific frame.",
            "parameters": {
                "type": "object",
                "properties": {"frame": {"type": "integer"}},
                "required": ["frame"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "layout_network",
            "description": "Auto-layout all nodes in a network.",
            "parameters": {
                "type": "object",
                "properties": {"parent_path": {"type": "string"}},
                "required": ["parent_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_bed_controls",
            "description": "Create a control null with master parameters (Width, Length, Mattress Height) for procedural bedding. ALWAYS use this at the start of a bed build.",
            "parameters": {
                "type": "object",
                "properties": {
                    "parent_path": {"type": "string"},
                    "name": {"type": "string", "default": "BED_CONTROLS"},
                },
                "required": ["parent_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_sticky_note",
            "description": "Add an annotating sticky note to a network.",
            "parameters": {
                "type": "object",
                "properties": {
                    "parent_path": {"type": "string"},
                    "text": {"type": "string"},
                    "x": {"type": "number", "default": 0},
                    "y": {"type": "number", "default": 0},
                    "width": {"type": "number", "default": 3},
                    "height": {"type": "number", "default": 1.5},
                },
                "required": ["parent_path", "text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "capture_pane",
            "description": "Capture a high-resolution screenshot of a Houdini pane (viewport or network editor). If pane_type is 'network' and a node_path is provided, it will automatically frame that node before capture.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pane_type": {
                        "type": "string",
                        "enum": ["viewport", "network"],
                        "default": "viewport",
                    },
                    "node_path": {
                        "type": "string",
                        "description": "Optional: full path to a node to frame in the Network Editor.",
                    },
                    "scale": {"type": "number", "default": 0.75},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "render_scene_view",
            "description": "Advanced rendering: automatically sets up a camera rig to encompass all visible geometry and renders a high-quality image. Use this for final verification of complex builds.",
            "parameters": {
                "type": "object",
                "properties": {
                    "orthographic": {"type": "boolean", "default": False},
                    "rotation": {
                        "type": "array",
                        "items": {"type": "number"},
                        "default": [0, 90, 0],
                    },
                    "render_engine": {
                        "type": "string",
                        "enum": ["opengl", "karma", "mantra"],
                        "default": "opengl",
                    },
                    "karma_engine": {
                        "type": "string",
                        "enum": ["cpu", "gpu"],
                        "default": "cpu",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "render_quad_views",
            "description": "Render four canonical views (Front, Left, Top, Perspective) of the visible scene in one call. Perfect for auditing symmetry and spatial layout.",
            "parameters": {
                "type": "object",
                "properties": {
                    "orthographic": {"type": "boolean", "default": True},
                    "render_engine": {
                        "type": "string",
                        "enum": ["opengl", "karma", "mantra"],
                        "default": "opengl",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "render_with_camera",
            "description": "Render the scene using a specific existing camera node.",
            "parameters": {
                "type": "object",
                "properties": {
                    "camera_path": {"type": "string"},
                    "render_engine": {
                        "type": "string",
                        "enum": ["opengl", "karma", "mantra"],
                        "default": "opengl",
                    },
                },
                "required": ["camera_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_docs",
            "description": "Search SideFX Houdini documentation for information on nodes, parameters, or VEX functions. Use this when the local knowledge base is insufficient.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "setup_flip_fluid",
            "description": "Create a complete FLIP fluid simulation rig in one call: source → dopnet(flipsolver) → particlefluidsurface. The bread-and-butter FX TD setup.",
            "parameters": {
                "type": "object",
                "properties": {
                    "parent_path": {"type": "string"},
                    "geo_node_path": {"type": "string"},
                    "container_size": {"type": "array", "items": {"type": "number"}},
                    "particle_separation": {"type": "number", "default": 0.1},
                    "gravity": {"type": "number", "default": -9.8},
                    "cache_dir": {"type": "string", "default": "$HIP/cache/flip"},
                },
                "required": ["parent_path", "geo_node_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_flip_diagnostic",
            "description": "Analyse a FLIP simulation for particle count, velocity range, substeps, and NaN detection.",
            "parameters": {
                "type": "object",
                "properties": {"dopnet_path": {"type": "string"}},
                "required": ["dopnet_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "batch_align_to_support",
            "description": "Align multiple nodes (e.g. 4 legs, 3 shelves) to a single support node's bounding box boundaries in one call. Use axis='y' to stack on top, or '-y' to stack underneath.",
            "parameters": {
                "type": "object",
                "properties": {
                    "support_node_path": {"type": "string"},
                    "target_node_paths": {"type": "array", "items": {"type": "string"}},
                    "axis": {
                        "type": "string",
                        "enum": ["y", "-y", "x", "-x", "z", "-z"],
                        "default": "y",
                    },
                },
                "required": ["support_node_path", "target_node_paths"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_transformed_node",
            "description": "Atomic creation tool: creates a node, sets multiple parameters, and optionally stacks it on a support node in a single request. Reduces network overhead for complex builds.",
            "parameters": {
                "type": "object",
                "properties": {
                    "parent_path": {"type": "string"},
                    "node_type": {"type": "string"},
                    "name": {"type": "string"},
                    "parms": {"type": "object"},
                    "support_node": {"type": "string"},
                },
                "required": ["parent_path", "node_type", "name", "parms"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "duplicate_node",
            "description": "Duplicate a node in the same network.",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_path": {"type": "string"},
                    "new_name": {"type": "string"},
                },
                "required": ["node_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rename_node",
            "description": "Rename a node.",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_path": {"type": "string"},
                    "new_name": {"type": "string"},
                },
                "required": ["node_path", "new_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "load_geometry",
            "description": "Load external geometry (.bgeo, .abc, .obj, .usd) via a File SOP.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "parent_path": {"type": "string", "default": "/obj/geo1"},
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "batch_set_parameters",
            "description": "Bulk-set parameters on multiple nodes. Input: list of {node_path, parm_name, value}.",
            "parameters": {
                "type": "object",
                "properties": {"nodes_and_parms": {"type": "array", "items": {"type": "object"}}},
                "required": ["nodes_and_parms"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_nodes",
            "description": "Compare parameter values between two nodes. Returns the diff.",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_path_a": {"type": "string"},
                    "node_path_b": {"type": "string"},
                },
                "required": ["node_path_a", "node_path_b"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_camera",
            "description": "Create a camera with position and optional look-at target.",
            "parameters": {
                "type": "object",
                "properties": {
                    "parent_path": {"type": "string", "default": "/obj"},
                    "name": {"type": "string", "default": "agent_cam"},
                    "position": {"type": "array", "items": {"type": "number"}},
                    "look_at": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "take_node_snapshot",
            "description": "Save all parameter values for a node (useful for before/after comparison).",
            "parameters": {
                "type": "object",
                "properties": {"node_path": {"type": "string"}},
                "required": ["node_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_keyframe",
            "description": "Delete a keyframe at a specific frame, or all keyframes on a parameter.",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_path": {"type": "string"},
                    "parm_name": {"type": "string"},
                    "frame": {"type": "integer"},
                },
                "required": ["node_path", "parm_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_timeline_keyframes",
            "description": "List all keyframes on a parameter.",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_path": {"type": "string"},
                    "parm_name": {"type": "string"},
                },
                "required": ["node_path", "parm_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "suggest_node_repairs",
            "description": "Expert diagnostic tool that identifies common wiring errors for solvers and returns exact repair actions. CALL THIS when a solver (FLIP, Vellum, Pyro) has errors or disconnected inputs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_path": {
                        "type": "string",
                        "description": "Path to the node with errors.",
                    }
                },
                "required": ["node_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "watch_node_events",
            "description": "Start (or stop) a Server-Sent Events broadcaster that streams live Houdini graph changes (node created/deleted/renamed/rewired/parm changed) to any connected client. Call once to start; call with stop=True to tear down.",
            "parameters": {
                "type": "object",
                "properties": {
                    "port": {"type": "integer", "default": 9877},
                    "stop": {"type": "boolean", "default": False},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_parm_expression_audit",
            "description": "Walk every node under a root and return all parameters carrying an hscript or Python expression. Use before refactoring to understand all procedural dependencies.",
            "parameters": {
                "type": "object",
                "properties": {
                    "root": {"type": "string", "default": "/"},
                    "language": {
                        "type": "string",
                        "enum": ["hscript", "python", "both"],
                        "default": "both",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_all_file_references",
            "description": "Collect every string parameter that looks like a file path across the scene. Use to audit textures, caches, and HDAs before delivery or migration.",
            "parameters": {
                "type": "object",
                "properties": {"root": {"type": "string", "default": "/"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "scan_missing_files",
            "description": "Run list_all_file_references and check disk existence of each path. Returns split report: missing, found, and sequence (frame-range) paths.",
            "parameters": {
                "type": "object",
                "properties": {"root": {"type": "string", "default": "/"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_cook_dependency_order",
            "description": "Walk upstream from a node and return all ancestor nodes in the order they must cook to produce the result. Includes dirty-node flagging.",
            "parameters": {
                "type": "object",
                "properties": {"node_path": {"type": "string"}},
                "required": ["node_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "copy_paste_nodes",
            "description": "Copy a list of nodes into a different parent network, preserving internal connections between them.",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_paths": {"type": "array", "items": {"type": "string"}},
                    "dest_parent_path": {"type": "string"},
                },
                "required": ["node_paths", "dest_parent_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lock_node",
            "description": "Lock or unlock a node's cached geometry so it doesn't recook when upstream changes. Useful for freezing slow sims or caches.",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_path": {"type": "string"},
                    "lock": {"type": "boolean", "default": True},
                },
                "required": ["node_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_object_visibility",
            "description": "Show or hide an object-level node in the viewport without deleting it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_path": {"type": "string"},
                    "visible": {"type": "boolean", "default": True},
                },
                "required": ["node_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cook_network_range",
            "description": "Force-cook a node (or the display node of a network) across a frame range. Reports cook times and errors per frame.",
            "parameters": {
                "type": "object",
                "properties": {
                    "parent_path": {"type": "string"},
                    "start_frame": {"type": "integer"},
                    "end_frame": {"type": "integer"},
                    "node_path": {"type": "string"},
                },
                "required": ["parent_path", "start_frame", "end_frame"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_animation_curve",
            "description": "Edit the interpolation type and slopes of all keyframes on a parameter. Choose bezier, linear, constant, ease, easein, or easeout.",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_path": {"type": "string"},
                    "parm_name": {"type": "string"},
                    "interpolation": {
                        "type": "string",
                        "enum": [
                            "constant",
                            "linear",
                            "bezier",
                            "ease",
                            "easein",
                            "easeout",
                        ],
                        "default": "bezier",
                    },
                    "slope_auto": {"type": "boolean", "default": True},
                    "in_slope": {"type": "number"},
                    "out_slope": {"type": "number"},
                },
                "required": ["node_path", "parm_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bake_expressions_to_keys",
            "description": "Evaluate all expression-driven parameters on a node across a frame range and replace them with explicit keyframes. Use before export or farm submission.",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_path": {"type": "string"},
                    "start_frame": {"type": "integer"},
                    "end_frame": {"type": "integer"},
                    "parm_filter": {"type": "string"},
                },
                "required": ["node_path", "start_frame", "end_frame"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_take",
            "description": "Create a new scene take for parameter overrides (e.g. different lighting per shot). Optionally nest under a parent take.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "make_active": {"type": "boolean", "default": True},
                    "parent_take": {"type": "string"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_takes",
            "description": "Return the full take hierarchy showing the active take and which parameters each take overrides.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "switch_take",
            "description": "Make a named take the active take so its parameter overrides take effect immediately.",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_vdb",
            "description": "Inspect all VDB grids on a SOP node. Returns per-grid name, data type, voxel size, active voxel count, bounding box, and background value.",
            "parameters": {
                "type": "object",
                "properties": {"node_path": {"type": "string"}},
                "required": ["node_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_vdb_grids",
            "description": "Fast summary of VDB grid names and types on a SOP node. Call before writing VEX that references a grid by name (density, vel, surface, heat).",
            "parameters": {
                "type": "object",
                "properties": {"node_path": {"type": "string"}},
                "required": ["node_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_packed_geo_info",
            "description": "Inspect packed primitives: piece names, counts, bounding boxes, and intrinsic transforms. Essential before setting up RBD or Copy-to-Points workflows.",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_path": {"type": "string"},
                    "max_pieces": {"type": "integer", "default": 50},
                },
                "required": ["node_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remap_file_paths",
            "description": "Bulk-remap file paths across a network by replacing a path prefix. dry_run=True (default) previews changes without writing. Set dry_run=False to apply.",
            "parameters": {
                "type": "object",
                "properties": {
                    "root": {"type": "string"},
                    "old_prefix": {"type": "string"},
                    "new_prefix": {"type": "string"},
                    "dry_run": {"type": "boolean", "default": True},
                },
                "required": ["root", "old_prefix", "new_prefix"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_vop_network",
            "description": "Build a VOP network by creating and wiring VOP nodes. Pass a chain of {type, name, parms, inputs} dicts. inputs use 'nodename.outputname' syntax.",
            "parameters": {
                "type": "object",
                "properties": {
                    "parent_path": {"type": "string"},
                    "chain": {"type": "array", "items": {"type": "object"}},
                },
                "required": ["parent_path", "chain"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "eval_hscript",
            "description": "Evaluate an hscript expression (e.g. $F, ch('tx')) or command (e.g. opfind) and return the result. Bridges the gap between Python and hscript-only functionality.",
            "parameters": {
                "type": "object",
                "properties": {"expression": {"type": "string"}},
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "setup_wire_solver",
            "description": "Create a Wire solver simulation for hair, cables, or ropes using curve primitives as the source.",
            "parameters": {
                "type": "object",
                "properties": {
                    "parent_path": {"type": "string"},
                    "geo_node_path": {"type": "string"},
                    "stiffness": {"type": "number", "default": 100.0},
                    "damping": {"type": "number", "default": 5.0},
                    "gravity": {"type": "number", "default": -9.81},
                },
                "required": ["parent_path", "geo_node_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "setup_crowd_sim",
            "description": "Create a Houdini crowd simulation with agent source, crowd solver, and optional terrain follow.",
            "parameters": {
                "type": "object",
                "properties": {
                    "parent_path": {"type": "string"},
                    "agent_geo_path": {"type": "string"},
                    "num_agents": {"type": "integer", "default": 100},
                    "terrain_path": {"type": "string"},
                },
                "required": ["parent_path", "agent_geo_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "setup_grain_sim",
            "description": "Create a POP Grains sand/granular simulation. Fast for large piles of sand, soil, or small rocks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "parent_path": {"type": "string"},
                    "source_node_path": {"type": "string"},
                    "particle_separation": {"type": "number", "default": 0.05},
                    "friction": {"type": "number", "default": 0.5},
                    "clumping": {"type": "number", "default": 0.1},
                },
                "required": ["parent_path", "source_node_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "setup_feather_sim",
            "description": "Create a Houdini Feather grooming and Vellum simulation network from guide quill curves.",
            "parameters": {
                "type": "object",
                "properties": {
                    "parent_path": {"type": "string"},
                    "quill_geo_path": {"type": "string"},
                    "barb_count": {"type": "integer", "default": 20},
                    "wind_strength": {"type": "number", "default": 0.5},
                },
                "required": ["parent_path", "quill_geo_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "setup_karma_material",
            "description": "Create a Karma-native MaterialX Standard Surface material in /mat with full PBR inputs and optional texture wiring.",
            "parameters": {
                "type": "object",
                "properties": {
                    "mat_name": {"type": "string"},
                    "base_color": {
                        "type": "array",
                        "items": {"type": "number"},
                        "default": [0.8, 0.8, 0.8],
                    },
                    "roughness": {"type": "number", "default": 0.5},
                    "metallic": {"type": "number", "default": 0.0},
                    "emission_color": {"type": "array", "items": {"type": "number"}},
                    "texture_path": {"type": "string"},
                },
                "required": ["mat_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "setup_aov_passes",
            "description": "Add render AOV passes (diffuse, specular, emission, shadow, depth, cryptomatte) to a Karma or Mantra ROP.",
            "parameters": {
                "type": "object",
                "properties": {
                    "rop_path": {"type": "string"},
                    "passes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": [
                            "diffuse_direct",
                            "specular_direct",
                            "emission",
                            "shadow_matte",
                            "depth",
                            "crypto_object",
                        ],
                    },
                },
                "required": ["rop_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_material_assignments",
            "description": "Scan all geometry nodes and return every material assignment — both object-level parms and Material SOP nodes.",
            "parameters": {
                "type": "object",
                "properties": {"root": {"type": "string", "default": "/obj"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "setup_render_output",
            "description": "Create and configure a ROP (karma/mantra/opengl) with correct output paths, frame range, camera, and sane defaults. Creates output directories automatically.",
            "parameters": {
                "type": "object",
                "properties": {
                    "parent_path": {"type": "string", "default": "/out"},
                    "renderer": {
                        "type": "string",
                        "enum": ["karma", "mantra", "opengl", "usdrender"],
                        "default": "karma",
                    },
                    "output_path": {
                        "type": "string",
                        "default": "$HIP/render/$HIPNAME.$F4.exr",
                    },
                    "start_frame": {"type": "integer"},
                    "end_frame": {"type": "integer"},
                    "camera_path": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_render",
            "description": "Submit a ROP for rendering locally, to HQueue, or to Deadline. For farm submission, saves the hip file first and returns a job ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "rop_path": {"type": "string"},
                    "farm": {
                        "type": "string",
                        "enum": ["local", "hqueue", "deadline"],
                        "default": "local",
                    },
                    "priority": {"type": "integer", "default": 50},
                    "job_name": {"type": "string"},
                },
                "required": ["rop_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_stacking_offset",
            "description": "Universal spatial alignment tool: calculates the exact Y-offset needed to stack one node perfectly on top of another using bounding box geometry. Use this for ALL multi-part builds (tables, props, rigs).",
            "parameters": {
                "type": "object",
                "properties": {
                    "lower_node_path": {
                        "type": "string",
                        "description": "The supporting node (base).",
                    },
                    "upper_node_path": {
                        "type": "string",
                        "description": "The node to be placed on top.",
                    },
                    "axis": {"type": "string", "enum": ["x", "y", "z"], "default": "y"},
                },
                "required": ["lower_node_path", "upper_node_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_parameter_details",
            "description": "Universal parameter discovery tool: returns UI range, default value, type, and menu options for any node parameter. CALL THIS before setting unknown parameters to avoid out-of-range failures.",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_path": {"type": "string"},
                    "parm_name": {"type": "string"},
                },
                "required": ["node_path", "parm_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_viewport_camera",
            "description": "Point the Houdini viewport at a specific camera node so the view matches the render camera.",
            "parameters": {
                "type": "object",
                "properties": {
                    "camera_path": {"type": "string"},
                    "pane_index": {"type": "integer", "default": 0},
                },
                "required": ["camera_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_viewport_display_mode",
            "description": "Change the viewport shading mode: smooth, wire, wireghost, flat, hidden_invis, or points.",
            "parameters": {
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": [
                            "smooth",
                            "wire",
                            "wireghost",
                            "flat",
                            "hidden_invis",
                            "points",
                        ],
                        "default": "smooth",
                    },
                    "pane_index": {"type": "integer", "default": 0},
                },
                "required": ["mode"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "assign_usd_material",
            "description": "Add a LOP Assign Material node to bind a mtlx material to a USD prim. Auto-wires after the last node in the network.",
            "parameters": {
                "type": "object",
                "properties": {
                    "lop_parent_path": {"type": "string"},
                    "prim_path": {"type": "string"},
                    "material_path": {"type": "string"},
                },
                "required": ["lop_parent_path", "prim_path", "material_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_usd_prim_attributes",
            "description": "Read all USD attributes on a specific prim at a given frame. Requires pxr (bundled with Houdini 18.5+).",
            "parameters": {
                "type": "object",
                "properties": {
                    "lop_node_path": {"type": "string"},
                    "prim_path": {"type": "string"},
                    "frame": {"type": "integer"},
                },
                "required": ["lop_node_path", "prim_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_usd_light",
            "description": "Add a USD light (rectlight, spherelight, distantlight, domelight) to a Solaris stage with intensity, color, and position.",
            "parameters": {
                "type": "object",
                "properties": {
                    "lop_parent_path": {"type": "string"},
                    "light_type": {
                        "type": "string",
                        "enum": [
                            "rectlight",
                            "spherelight",
                            "distantlight",
                            "domelight",
                            "disklight",
                            "cylinderlight",
                        ],
                        "default": "rectlight",
                    },
                    "name": {"type": "string", "default": "key_light"},
                    "intensity": {"type": "number", "default": 10.0},
                    "color": {
                        "type": "array",
                        "items": {"type": "number"},
                        "default": [1.0, 1.0, 1.0],
                    },
                    "translate": {"type": "array", "items": {"type": "number"}},
                },
                "required": ["lop_parent_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "validate_usd_stage",
            "description": "Check a USD stage for missing prims, untyped prims, composition errors, and broken LOP node errors. Returns structured error/warning report.",
            "parameters": {
                "type": "object",
                "properties": {"lop_node_path": {"type": "string"}},
                "required": ["lop_node_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reload_hda_definition",
            "description": "Reload an HDA definition from disk without restarting Houdini. Pass a node path or a .hda file path. Omit both to reload all HDA files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "hda_node_path": {"type": "string"},
                    "hda_file_path": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_installed_hdas",
            "description": "List all installed HDA definitions in the session with name, label, category, version, and file path.",
            "parameters": {
                "type": "object",
                "properties": {"filter_name": {"type": "string"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "diff_hda_versions",
            "description": "Compare the parameter interfaces of two HDA instances. Returns parms only in A, only in B, and parms with different default values.",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_path_a": {"type": "string"},
                    "node_path_b": {"type": "string"},
                },
                "required": ["node_path_a", "node_path_b"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_documentation_snapshot",
            "description": "Export a full network as an annotated Markdown report: node inventory, cook hotspots, HDA list, parameter connections. Saved to $HIP/docs/ by default.",
            "parameters": {
                "type": "object",
                "properties": {
                    "parent_path": {"type": "string"},
                    "output_path": {"type": "string"},
                },
                "required": ["parent_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "auto_color_by_type",
            "description": "Automatically color-code all nodes in a network by functional category (generators=teal, VEX=amber, sim=red, USD=purple, output=green, etc). Makes large networks far easier to navigate.",
            "parameters": {
                "type": "object",
                "properties": {"parent_path": {"type": "string"}},
                "required": ["parent_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_memory_usage",
            "description": "Return Houdini process memory in MB plus scene node counts. Uses psutil if available, falls back to /proc/self/status on Linux.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "suggest_optimization",
            "description": "Analyze a SOP network and return actionable optimization suggestions: slow nodes, redundant Normal SOPs, excessive Foreach loops, missing File Caches, and error-blocked cooks.",
            "parameters": {
                "type": "object",
                "properties": {"parent_path": {"type": "string"}},
                "required": ["parent_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_top_network",
            "description": "Create a TOP network (topnet) for PDG workflow orchestration — batch caching, rendering, data processing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "parent_path": {"type": "string", "default": "/obj"},
                    "name": {"type": "string", "default": "topnet1"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_top_node",
            "description": "Create a node inside a TOP network (e.g. pythonscript, filecache, ropfetch, wedge).",
            "parameters": {
                "type": "object",
                "properties": {
                    "parent_path": {"type": "string"},
                    "node_type": {"type": "string"},
                    "name": {"type": "string"},
                    "parms": {"type": "object"},
                },
                "required": ["parent_path", "node_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_pdg_cook",
            "description": "Cook a PDG graph from the specified TOP node. Use mode='blocking' to wait or 'async' to return immediately.",
            "parameters": {
                "type": "object",
                "properties": {
                    "top_node_path": {"type": "string"},
                    "mode": {
                        "type": "string",
                        "enum": ["blocking", "async"],
                        "default": "blocking",
                    },
                },
                "required": ["top_node_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_pdg_work_items",
            "description": "List work items and their states (waiting, cooking, cooked, failed) for a TOP node.",
            "parameters": {
                "type": "object",
                "properties": {"top_node_path": {"type": "string"}},
                "required": ["top_node_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_file_cache_top",
            "description": "Create a File Cache TOP that caches geometry from a SOP path to disk.",
            "parameters": {
                "type": "object",
                "properties": {
                    "parent_path": {"type": "string"},
                    "sop_path": {"type": "string"},
                    "cache_dir": {"type": "string", "default": "$HIP/cache"},
                },
                "required": ["parent_path", "sop_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_python_script_top",
            "description": "Create a Python Script TOP that executes custom code per work item — for AI automation, data processing, or API calls.",
            "parameters": {
                "type": "object",
                "properties": {
                    "parent_path": {"type": "string"},
                    "code": {"type": "string"},
                    "name": {"type": "string", "default": "pyscript1"},
                },
                "required": ["parent_path", "code"],
            },
        },
    },
]

_schema_names = {
    schema.get("function", {}).get("name")
    for schema in TOOL_SCHEMAS
    if schema.get("function", {}).get("name")
}
for _tool_name, _tool_fn in TOOL_FUNCTIONS.items():
    if _tool_name not in _schema_names:
        TOOL_SCHEMAS.append(_build_fallback_schema(_tool_name, _tool_fn))


core._tool_functions_registry = TOOL_FUNCTIONS
core._tool_schemas_registry = TOOL_SCHEMAS
core._tool_meta_registry = {
    "DESTRUCTIVE_TOOLS": DESTRUCTIVE_TOOLS,
    "CONFIRM_TOOLS": CONFIRM_TOOLS,
    "DANGEROUS_TOOLS": DANGEROUS_TOOLS,
    "TOOL_SAFETY_TIERS": TOOL_SAFETY_TIERS,
    "BACKUP_BEFORE_TOOLS": BACKUP_BEFORE_TOOLS,
}
