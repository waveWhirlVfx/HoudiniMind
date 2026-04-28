# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
"""
HoudiniMind — Tool Library (modular version)
All tool functions callable by the agent, plus schemas for the LLM.

This package keeps the refactored modular implementation while preserving the
old `python.agent.tools` compatibility surface that the agent loop, tests, and
UI still rely on.
"""

import os
from functools import wraps

from ..interceptor import HoudiniPipelineInterceptor
from . import (
    _advanced_tools,
    _chain_tools,
    _core,
    _geometry_tools,
    _inspection_tools,
    _knowledge_tools,
    _material_usd_tools,
    _node_tools,
    _pdg_tools,
    _perf_org_tools,
    _scene_tools,
    _simulation_tools,
    _vision_tools,
)
from ._registry import (
    BACKUP_BEFORE_TOOLS,
    CONFIRM_TOOLS,
    DANGEROUS_TOOLS,
    DESTRUCTIVE_TOOLS,
    TOOL_SAFETY_TIERS,
    TOOL_SCHEMAS,
)
from ._registry import (
    TOOL_FUNCTIONS as _RAW_TOOL_FUNCTIONS,
)

HOUDINIMIND_ROOT = _core.HOUDINIMIND_ROOT
SCHEMA_PATH = _core.SCHEMA_PATH
HOU_AVAILABLE = _core.HOU_AVAILABLE
hou = getattr(_core, "hou", None)

# Tools outside the modelling + FX scope. Filtered out when
# config.modeling_fx_only is True (see _apply_scope_filter below).
MODELING_FX_SCOPE_EXCLUDED = {
    # Materials / lookdev / UVs
    "create_material",
    "assign_material",
    "list_materials",
    "setup_fabric_lookdev",
    "create_uv_seams",
    "setup_karma_material",
    "setup_aov_passes",
    "list_material_assignments",
    # Solaris / USD
    "get_usd_hierarchy",
    "create_lop_node",
    "assign_usd_material",
    "get_usd_prim_attributes",
    "create_usd_light",
    "validate_usd_stage",
    # Rendering / camera / viewport render setup
    "render_scene_view",
    "render_quad_views",
    "render_with_camera",
    "setup_render_output",
    "submit_render",
    "set_viewport_camera",
    "set_viewport_display_mode",
    "create_camera",
    # Animation / takes / timeline. Keep advanced timeline/take management
    # out of the modeling+FX scope, but allow direct keyframing tools.
    "create_take",
    "list_takes",
    "switch_take",
    "bake_expressions_to_keys",
    # HDA admin (reload/diff/list — not needed for building)
    "reload_hda_definition",
    "list_installed_hdas",
    "diff_hda_versions",
    # Documentation / misc
    "create_documentation_snapshot",
    # PDG (usually render/cache workflows)
    "create_top_network",
    "create_top_node",
    "submit_pdg_cook",
    "get_pdg_work_items",
    "create_file_cache_top",
    "create_python_script_top",
}

_ok = _core._ok
_err = _core._err
_require_hou = _core._require_hou
_get_tool_functions = _core._get_tool_functions
_get_tool_schemas = _core._get_tool_schemas
_infer_child_context = _core._infer_child_context
SOP_TYPE_ALIASES = _core.SOP_TYPE_ALIASES
FILTER_NODE_TYPES = _core.FILTER_NODE_TYPES
_HYBRID_KNOWLEDGE = _core._HYBRID_KNOWLEDGE
_PARM_BASE_ALIASES = _core._PARM_BASE_ALIASES
_PARM_COMPONENT_ALIASES = _core._PARM_COMPONENT_ALIASES
_INTERNAL_PARM_BLACKLIST = _core._INTERNAL_PARM_BLACKLIST
_HINT_STOPWORDS = _core._HINT_STOPWORDS
_knowledge_base_candidates = _core._knowledge_base_candidates
_active_knowledge_base_path = _core._active_knowledge_base_path
_tokenize_hint_text = _core._tokenize_hint_text
_schema_pool_for_context = _core._schema_pool_for_context
_schema_pool_for_node = _core._schema_pool_for_node
_rank_text_candidates = _core._rank_text_candidates
_close_matches = _core._close_matches
_parm_alias_candidates = _core._parm_alias_candidates
_suggest_parm_names = _core._suggest_parm_names
_ensure_parent_exists = _core._ensure_parent_exists
_resolve_menu_value = _core._resolve_menu_value
_ensure_multiparm_count = _core._ensure_multiparm_count
_parse_vector_string = _core._parse_vector_string
_set_parm_value = _core._set_parm_value
_resolve_geometry_source_node = _core._resolve_geometry_source_node
_snapshot_parm_value = _core._snapshot_parm_value
_parse_expression_value = _core._parse_expression_value
_get_vcc_command = _core._get_vcc_command
_validate_vex_with_vcc = _core._validate_vex_with_vcc
_validate_vex_with_checker = _core._validate_vex_with_checker
_validate_python_code = _core._validate_python_code
REPAIR_STRATEGIES = _core.REPAIR_STRATEGIES

try:
    pipeline_interceptor = HoudiniPipelineInterceptor(SCHEMA_PATH)
except Exception:
    pipeline_interceptor = getattr(_core, "_pipeline_interceptor", None)

_SEARCH_RETRIEVER_CACHE = _core._search_retriever_cache
_SHARED_EMBED_FN = _core._shared_embed_fn
_SHARED_CHAT_SIMPLE_FN = getattr(_core, "_shared_chat_simple_fn", None)

_SYNC_MODULES = (
    _core,
    _scene_tools,
    _inspection_tools,
    _node_tools,
    _chain_tools,
    _geometry_tools,
    _simulation_tools,
    _material_usd_tools,
    _perf_org_tools,
    _knowledge_tools,
    _vision_tools,
    _advanced_tools,
    _pdg_tools,
)


def _sync_runtime_overrides():
    global SCHEMA_PATH

    root = os.path.abspath(globals().get("HOUDINIMIND_ROOT") or _core.HOUDINIMIND_ROOT)
    SCHEMA_PATH = os.path.join(root, "data", "schema", "houdini_full_schema.json")

    _core.HOUDINIMIND_ROOT = root
    _core.SCHEMA_PATH = SCHEMA_PATH

    hou_module = globals().get("hou", getattr(_core, "hou", None))
    hou_available = bool(globals().get("HOU_AVAILABLE", _core.HOU_AVAILABLE))
    _core.hou = hou_module
    _core._hou = hou_module
    _core.HOU_AVAILABLE = hou_available

    _core._shared_embed_fn = globals().get("_SHARED_EMBED_FN", _core._shared_embed_fn)
    _core._shared_chat_simple_fn = globals().get(
        "_SHARED_CHAT_SIMPLE_FN",
        getattr(_core, "_shared_chat_simple_fn", None),
    )

    search_cache = globals().get("_SEARCH_RETRIEVER_CACHE")
    if isinstance(search_cache, dict):
        _core._search_retriever_cache = search_cache

    current_interceptor = globals().get("pipeline_interceptor")
    _core._pipeline_interceptor = current_interceptor
    _node_tools._pipeline_interceptor = current_interceptor

    search_getter = globals().get("_get_search_retriever")
    if callable(search_getter):
        _core._get_search_retriever = search_getter
        _node_tools._get_search_retriever = search_getter

    lexical_search = globals().get("_lexical_search_knowledge")
    if callable(lexical_search):
        _core._lexical_search_knowledge = lexical_search
        _node_tools._lexical_search_knowledge = lexical_search

    for module in _SYNC_MODULES:
        if hasattr(module, "HOUDINIMIND_ROOT"):
            module.HOUDINIMIND_ROOT = root
        if hasattr(module, "SCHEMA_PATH"):
            module.SCHEMA_PATH = SCHEMA_PATH
        if hasattr(module, "hou"):
            module.hou = hou_module
        if hasattr(module, "HOU_AVAILABLE"):
            module.HOU_AVAILABLE = hou_available


def _wrap_callable(fn):
    @wraps(fn)
    def _wrapped(*args, **kwargs):
        _sync_runtime_overrides()
        return fn(*args, **kwargs)

    return _wrapped


TOOL_FUNCTIONS = {
    tool_name: _wrap_callable(tool_fn) for tool_name, tool_fn in _RAW_TOOL_FUNCTIONS.items()
}

for _tool_name, _tool_fn in TOOL_FUNCTIONS.items():
    globals()[_tool_name] = _tool_fn


def apply_scope_filter(config: dict):
    """
    Filter TOOL_FUNCTIONS / TOOL_SCHEMAS by config.

    When `modeling_fx_only=True` (default for the modelling + FX focused agent),
    texturing, material, USD/Solaris, rendering, animation takes, HDA lifecycle,
    and PDG tools are stripped from the live registries. The underlying code is
    untouched — flipping the flag back to False restores the full set.
    """
    if not config or not config.get("modeling_fx_only", False):
        return TOOL_FUNCTIONS, TOOL_SCHEMAS

    excluded = MODELING_FX_SCOPE_EXCLUDED
    filtered_funcs = {name: fn for name, fn in TOOL_FUNCTIONS.items() if name not in excluded}
    filtered_schemas = [
        s for s in TOOL_SCHEMAS if s.get("function", {}).get("name") not in excluded
    ]
    # Mutate the live dict/list in place so downstream consumers that captured
    # a reference still observe the scoped set.
    for name in list(TOOL_FUNCTIONS.keys()):
        if name in excluded:
            TOOL_FUNCTIONS.pop(name, None)
            globals().pop(name, None)

    TOOL_SCHEMAS[:] = filtered_schemas
    return filtered_funcs, filtered_schemas


_get_search_retriever = _wrap_callable(_core._get_search_retriever)
_lexical_search_knowledge = _wrap_callable(_core._lexical_search_knowledge)
_set_node_parameter = _wrap_callable(_node_tools._set_node_parameter)
audit_spatial_layout = _wrap_callable(_perf_org_tools.audit_spatial_layout)
