# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
"""
Node tools: creation, editing, connection, expressions, scripting.
"""

import ast
import json
import re
import traceback as _tb

from . import _core as core

_ok = core._ok
_err = core._err
_require_hou = core._require_hou
_snapshot_parm_value = core._snapshot_parm_value
_parse_expression_value = core._parse_expression_value
_ensure_parent_exists = core._ensure_parent_exists
_normalize_node_path = core._normalize_node_path
_resolve_menu_value = core._resolve_menu_value
_ensure_multiparm_count = core._ensure_multiparm_count
_parse_vector_string = core._parse_vector_string
_set_parm_value = core._set_parm_value
_resolve_geometry_source_node = core._resolve_geometry_source_node
_pipeline_interceptor = core._pipeline_interceptor
_ordered_unique = core._ordered_unique
_ordered_unique = core._ordered_unique
_parm_alias_candidates = core._parm_alias_candidates
_suggest_parm_names = core._suggest_parm_names
_resolve_parameter_name = core._resolve_parameter_name
_resolve_node_type_name = core._resolve_node_type_name
_SOP_TYPE_ALIASES = core.SOP_TYPE_ALIASES
_FILTER_NODE_TYPES = core.FILTER_NODE_TYPES
_infer_child_context_core = core._infer_child_context_core
_validate_vex_with_checker = core._validate_vex_with_checker
_vex_validation_unavailable = core._vex_validation_unavailable
_validate_python_code = core._validate_python_code
_HYBRID_KNOWLEDGE = core._HYBRID_KNOWLEDGE
HOUDINIMIND_ROOT = core.HOUDINIMIND_ROOT
_get_search_retriever = core._get_search_retriever
_lexical_search_knowledge = core._lexical_search_knowledge

try:
    import hou

    HOU_AVAILABLE = core.HOU_AVAILABLE
except ImportError:
    HOU_AVAILABLE = False
    hou = None

SOP_TYPE_ALIASES = core.SOP_TYPE_ALIASES
FILTER_NODE_TYPES = core.FILTER_NODE_TYPES


_infer_child_context = _infer_child_context_core


def verify_node_type(node_type, parent_path="/obj"):
    """Check whether a node type string is valid before calling create_node."""
    if not isinstance(node_type, str) or not node_type.strip():
        return _err("node_type is required and must be a non-empty string")
    normalized = node_type.lower().strip()
    alias = SOP_TYPE_ALIASES.get(normalized)
    if alias and alias != node_type:
        return _ok(
            {
                "valid": False,
                "canonical_type": alias,
                "suggestion": f"Use '{alias}' instead of '{node_type}'. The label in docs/UI is not the type string.",
            },
            message=f"Type alias found: '{node_type}' → '{alias}'",
        )
    if HOU_AVAILABLE:
        try:
            parent = hou.node(parent_path)
            if parent:
                test_node = parent.createNode(node_type, "__hm_typecheck__")
                test_node.destroy()
                return _ok(
                    {"valid": True, "canonical_type": node_type, "suggestion": None},
                    message=f"Type '{node_type}' is valid.",
                )
        except hou.OperationFailed:
            try:
                all_types = [t.name() for t in hou.sopNodeTypeCategory().nodeTypes().values()]
                if node_type in all_types:
                    return _ok(
                        {
                            "valid": True,
                            "canonical_type": node_type,
                            "suggestion": f"'{node_type}' is a valid SOP, but you tried to create it in {parent_path}. You must create a 'geo' node in /obj first, then create '{node_type}' inside it.",
                        },
                        message=f"Type '{node_type}' is valid but requires a different parent context.",
                    )
                close = [t for t in all_types if node_type.lower() in t.lower()][:8]
            except Exception:
                close = []
            alias_hit = SOP_TYPE_ALIASES.get(node_type.lower())
            suggestion = alias_hit or (close[0] if close else None)
            return _ok(
                {
                    "valid": False,
                    "canonical_type": suggestion,
                    "suggestion": f"'{node_type}' not found. Did you mean '{suggestion}'? Close matches: {close}",
                },
                message=f"Invalid type: {node_type}",
            )
        except Exception as e:
            return _err(str(e))
    if normalized in SOP_TYPE_ALIASES:
        canonical = SOP_TYPE_ALIASES[normalized]
        return _ok(
            {
                "valid": canonical == node_type,
                "canonical_type": canonical,
                "suggestion": None if canonical == node_type else f"Use '{canonical}'",
            }
        )
    return _ok(
        {
            "valid": None,
            "canonical_type": node_type,
            "suggestion": "Could not verify offline — use inside Houdini for live check.",
        }
    )


def list_node_types(category="sop", filter_pattern=""):
    """List all available node type strings for a category."""
    try:
        _require_hou()
        cat_map = {
            "sop": hou.sopNodeTypeCategory,
            "dop": hou.dopNodeTypeCategory,
            "obj": hou.objNodeTypeCategory,
            "object": hou.objNodeTypeCategory,
            "objects": hou.objNodeTypeCategory,
            "lop": hou.lopNodeTypeCategory,
            "stage": hou.lopNodeTypeCategory,
            "vop": hou.vopNodeTypeCategory,
            "mat": hou.vopNodeTypeCategory,
            "rop": hou.ropNodeTypeCategory,
            "out": hou.ropNodeTypeCategory,
        }
        category = (category or "").strip()
        filter_pattern = (filter_pattern or "").strip()
        cat_fn = cat_map.get(category.lower())
        if not cat_fn:
            return _err(f"Unknown category '{category}'. Use: sop, dop, obj, lop, vop, rop")
        types = sorted(cat_fn().nodeTypes().keys())
        if filter_pattern:
            types = [t for t in types if filter_pattern.lower() in t.lower()]
        limit = 100 if filter_pattern else 40
        truncated = len(types) > limit
        payload = {
            "category": category,
            "count": len(types),
            "types": types[:limit],
            "truncated": truncated,
        }
        if truncated and not filter_pattern:
            payload["suggestion"] = "Provide filter_pattern to narrow the list."
        return _ok(
            payload,
            message=f"{len(types)} types found in '{category}'"
            + (f" matching '{filter_pattern}'" if filter_pattern else "")
            + (f". Showing first {limit}." if truncated else ""),
        )
    except Exception as e:
        return _err(str(e))


def resolve_build_hints(
    goal="",
    node_path="",
    parm_name="",
    node_type="",
    parent_path="/obj",
):
    """
    Resolve likely node-type and parameter-name mismatches before a build step.

    Useful as a cheap preflight before create_node() or safe_set_parameter().
    """
    try:
        payload = {
            "goal": (goal or "").strip(),
            "node_path": (node_path or "").strip(),
            "requested_parm_name": (parm_name or "").strip(),
            "requested_node_type": (node_type or "").strip(),
            "parent_path": (parent_path or "/obj").strip() or "/obj",
            "resolved_node_type": "",
            "parm_suggestions": [],
        }

        node = None
        if payload["node_path"]:
            _require_hou()
            node = hou.node(payload["node_path"])
            if not node:
                return _err(f"Node not found: {payload['node_path']}")
            payload["resolved_node_type"] = node.type().name()
            actual_parm_names = [p.name() for p in node.parms()]
            if payload["requested_parm_name"]:
                labels_by_name = {}
                for parm_obj in node.parms():
                    try:
                        name = parm_obj.name()
                        label = parm_obj.description()
                    except Exception:
                        continue
                    if label and str(label) != str(name):
                        labels_by_name[str(name)] = str(label)
                resolved = _resolve_parameter_name(
                    payload["requested_parm_name"],
                    actual_parm_names,
                    labels_by_name=labels_by_name,
                    node_type=payload["resolved_node_type"],
                )
                suggestions = [
                    str(name)
                    for name in _suggest_parm_names(
                        actual_parm_names,
                        payload["requested_parm_name"],
                        limit=8,
                    )
                ]
                payload["parm_suggestions"] = suggestions
                if resolved.get("status") == "resolved":
                    payload["resolved_parm_name"] = resolved.get("resolved")
                    payload["resolved_parm_reason"] = resolved.get("reason")
                elif suggestions:
                    payload["resolved_parm_name"] = suggestions[0]
        elif payload["requested_node_type"]:
            verify = verify_node_type(
                payload["requested_node_type"],
                parent_path=payload["parent_path"],
            )
            if verify.get("status") != "ok":
                return verify
            verify_data = verify.get("data") or {}
            payload["resolved_node_type"] = (
                verify_data.get("canonical_type") or payload["requested_node_type"]
            )
            payload["node_type_valid"] = verify_data.get("valid")
            if verify_data.get("suggestion"):
                payload["node_type_suggestion"] = verify_data["suggestion"]

        if payload["goal"]:
            payload["goal_tokens"] = core._tokenize_hint_text(payload["goal"])[:12]

        if not payload["resolved_node_type"] and payload["requested_node_type"]:
            payload["resolved_node_type"] = payload["requested_node_type"]

        if not payload["resolved_node_type"] and node is not None:
            payload["resolved_node_type"] = node.type().name()

        return _ok(
            payload,
            message="Resolved build hints for the requested node/parameter context.",
        )
    except Exception as e:
        return _err(str(e))


def _set_node_parameter(node, parm_name, value, parm_cache=None, cook_vex=True):
    """Shared parameter-setting logic used by safe_set_parameter and create_node_chain."""
    node_type = node.type().name()
    if not isinstance(parm_name, str) or not parm_name.strip():
        return _err(f"Invalid parameter name for {node.path()}: {parm_name!r}")
    parm_name = parm_name.strip()
    if parm_cache and "names" in parm_cache:
        actual_parm_names = parm_cache["names"]
    else:
        actual_parm_names = [p.name() for p in node.parms()]
    lowered_parm_name = parm_name.lower()
    actual_parm_lookup = {str(p).lower(): p for p in actual_parm_names}

    labels_by_name = {}
    for parm_obj in node.parms():
        try:
            name = parm_obj.name()
        except Exception:
            continue
        label = ""
        try:
            label = parm_obj.description()
        except Exception:
            label = ""
        if label and str(label) != str(name):
            labels_by_name[str(name)] = str(label)

    resolved = _resolve_parameter_name(
        parm_name,
        actual_parm_names,
        labels_by_name=labels_by_name,
        node_type=node_type,
    )
    if resolved.get("status") == "resolved":
        resolved_name = resolved.get("resolved")
        if resolved_name:
            parm_name = resolved_name
            lowered_parm_name = parm_name.lower()

    def _resolve_exact_alias(name):
        for candidate in _parm_alias_candidates(name):
            actual = actual_parm_lookup.get(str(candidate).lower())
            if actual:
                return actual
        return None

    if (
        lowered_parm_name in {"vex_code", "vexcode", "vex", "vex_snippet"}
        and "snippet" in actual_parm_names
    ):
        parm_name = "snippet"
        lowered_parm_name = "snippet"
    if isinstance(value, str):
        stripped = value.strip()
        if parm_name != "snippet":
            vec_from_space = _parse_vector_string(stripped)
            if vec_from_space is not None:
                value = vec_from_space
            elif stripped[:1] in {"[", "("} and stripped[-1:] in {"]", ")"}:
                try:
                    parsed = json.loads(stripped)
                except Exception:
                    try:
                        parsed = ast.literal_eval(stripped)
                    except Exception:
                        parsed = value
                if isinstance(parsed, (list, tuple)):
                    value = list(parsed)
    is_vector_like = isinstance(value, (list, tuple)) and len(value) >= 2
    parm = None
    if is_vector_like:
        try:
            parm_tuple = getattr(node, "parmTuple", None)
            parm = parm_tuple(parm_name) if callable(parm_tuple) else None
            if not parm:
                parm = node.parm(parm_name)
        except Exception:
            parm = None
    else:
        parm = node.parm(parm_name)
        if not parm:
            try:
                parm_tuple = getattr(node, "parmTuple", None)
                parm = parm_tuple(parm_name) if callable(parm_tuple) else None
                if parm:
                    try:
                        tuple_len = len(parm)
                    except Exception:
                        tuple_len = 0
                    if tuple_len > 1:
                        value = [value for _ in range(tuple_len)]
                        is_vector_like = True
            except Exception:
                parm = None
    if not parm:
        exact_alias = _resolve_exact_alias(parm_name)
        if exact_alias:
            parm = node.parm(exact_alias)
            if parm:
                parm_name = exact_alias
            else:
                parm_tuple = getattr(node, "parmTuple", None)
                parm = parm_tuple(exact_alias) if callable(parm_tuple) else None
                if parm:
                    parm_name = exact_alias
                    is_vector_like = True

    def _coerce_component_scalar(name, raw_value):
        if not isinstance(raw_value, (list, tuple)):
            return raw_value
        vals = list(raw_value)
        if not vals:
            return raw_value
        idx_map = {"x": 0, "y": 1, "z": 2, "w": 3}
        suffix = str(name or "").strip().lower()[-1:] if name else ""
        if suffix in idx_map and len(vals) > idx_map[suffix]:
            return vals[idx_map[suffix]]
        if len(vals) == 1:
            return vals[0]
        if str(name or "").strip().lower() in {"scale", "uniformscale", "pscale"}:
            return vals[0]
        return raw_value

    is_tuple = False
    if parm:
        is_tuple = type(parm).__name__ == "ParmTuple"
    if parm and not is_tuple and is_vector_like:
        if hasattr(parm, "tuple") and callable(parm.tuple):
            tuple_obj = parm.tuple()
            # Guardrail: do not upgrade explicit component params (e.g. sizex/sizey/tx)
            # to their tuple automatically, otherwise setting sizey=[...] can overwrite
            # the full size tuple unexpectedly.
            is_component_name = bool(re.search(r"[xyzw]$", parm_name.lower()))
            if tuple_obj and len(tuple_obj) > 1 and not is_component_name:
                parm = tuple_obj
        elif len(value) == 1:
            value = value[0]
            is_vector_like = False
        else:
            parm = None
    if not parm and not is_vector_like:
        exact_alias = _resolve_exact_alias(parm_name)
        if exact_alias:
            parm = node.parm(exact_alias)
            if parm:
                parm_name = exact_alias
    if not parm:
        try:
            if _ensure_multiparm_count(node, parm_name):
                parm = node.parm(parm_name)
        except Exception:
            pass
    if not parm and is_vector_like:
        components = ["x", "y", "z", "w"]
        vector_base = parm_name
        alias_candidates = _parm_alias_candidates(parm_name)
        if alias_candidates:
            vector_base = alias_candidates[0]
            for candidate in alias_candidates[1:]:
                if any(name.startswith(candidate) for name in actual_parm_names):
                    vector_base = candidate
                    break
        mapped_count = 0
        expression_components = 0
        mismatch_warnings = []
        for i, val in enumerate(value):
            if i >= len(components):
                break
            comp_name = f"{vector_base}{components[i]}"
            comp_parm = node.parm(comp_name)
            if comp_parm:
                set_result = _set_parm_value(comp_parm, val)
                mapped_count += 1
                if set_result.get("mode") == "expression":
                    expression_components += 1
                elif set_result.get("mode") == "value_mismatch":
                    mismatch_warnings.append(
                        f"{comp_name}: set {val} but reads {set_result.get('readback')}"
                    )
        if mapped_count > 0:
            result_data = {
                "mapped_components": mapped_count,
                "expression_components": expression_components,
            }
            msg = f"UNDO_TRACK: Mapped '{parm_name}' to {mapped_count} components on {node.path()}"
            if mismatch_warnings:
                result_data["readback_warnings"] = mismatch_warnings
                msg = f"WARNING: Mapped '{parm_name}' to {mapped_count} components but {len(mismatch_warnings)} value(s) didn't stick"
            return _ok(result_data, message=msg)
    if not parm:
        exact_alias = _resolve_exact_alias(parm_name)
        if exact_alias:
            parm = node.parm(exact_alias)
            if parm:
                parm_name = exact_alias
    if not parm:
        live_candidates = _suggest_parm_names(actual_parm_names, parm_name, limit=6)
        schema_candidates = (
            _pipeline_interceptor.suggest_parm_names(node_type, parm_name, n=6)
            if _pipeline_interceptor
            else []
        )
        all_candidates = list(dict.fromkeys(live_candidates + schema_candidates))[:8]
        return _err(
            f"Parameter '{parm_name}' not found on {node.path()} ({node_type}). "
            f"Close matches: {all_candidates}. "
            f"Use get_node_parameters('{node.path()}') for the full list."
        )
    if not is_tuple and isinstance(value, (list, tuple)):
        value = _coerce_component_scalar(parm_name, value)
    old = _snapshot_parm_value(parm)
    vex_validation = None
    vex_validation_unavailable = False
    if parm_name == "snippet" and isinstance(value, str):
        value = value.replace("\r\n", "\n").replace("\r", "\n")
        vex_validation = _validate_vex_with_checker(value)
        if not vex_validation.get("success"):
            vex_validation_unavailable = _vex_validation_unavailable(vex_validation)
            if not vex_validation_unavailable:
                errors = vex_validation.get("errors") or ["Unknown VEX validation error"]
                return _err(
                    "VEX validation failed before setting "
                    f"{node.path()}/snippet. Use write_vex_code() and fix the reported VEX "
                    f"issue before retrying. First error: {errors[0]}"
                )
    set_result = _set_parm_value(parm, value)
    if set_result.get("success") is False:
        return _err(f"Failed to set '{parm_name}': {set_result.get('error')}")
    if parm_name == "snippet" and isinstance(value, str):
        cook_errors = []
        if cook_vex:
            cook_fn = getattr(node, "cook", None)
            if callable(cook_fn):
                try:
                    cook_fn(force=True)
                except Exception as cook_err:
                    cook_errors.append(str(cook_err))
                errors_fn = getattr(node, "errors", None)
                if callable(errors_fn):
                    try:
                        cook_errors.extend(str(err) for err in errors_fn())
                    except Exception:
                        pass
        if cook_errors:
            try:
                parm.set(old)
            except Exception:
                pass
            return _err(
                "VEX cook failed after setting "
                f"{node.path()}/snippet; previous code was restored. First error: {cook_errors[0]}"
            )
        data = {
            "old": old,
            "new": value,
            "vex_validation": "unavailable"
            if vex_validation_unavailable
            else vex_validation.get("status", "ok")
            if isinstance(vex_validation, dict)
            else "ok",
            "warnings": (vex_validation or {}).get("warnings", []),
        }
        message = f"UNDO_TRACK: Set {node.path()}/snippet to validated VEX"
        if vex_validation_unavailable:
            message += (
                " — WARNING: VEX validator unavailable; snippet was set without compile preflight"
            )
        elif data["warnings"]:
            message += f" — warnings: {data['warnings']}"
        else:
            message += " — compiled OK"
        return _ok(data, message=message)
    if set_result.get("mode") == "expression":
        return _ok(
            {
                "old": old,
                "expression": set_result.get("expression"),
                "language": set_result.get("language"),
            },
            message=f"UNDO_TRACK: Set expression {node.path()}/{parm_name} = {set_result.get('expression')}",
        )
    if set_result.get("mode") == "value_mismatch":
        return _ok(
            {"old": old, "new": value, "readback": set_result.get("readback")},
            message=f"WARNING: {set_result.get('warning')}",
        )
    return _ok(
        {"old": old, "new": value},
        message=f"UNDO_TRACK: Set {node.path()}/{parm_name} to {value}",
    )


def create_node(parent_path, node_type, name=None, cook=True):
    """Create a node and position it cleanly."""
    try:
        if not isinstance(node_type, str) or not node_type.strip():
            return _err("node_type is required and must be a non-empty string")
        _require_hou()
        parent_path = _normalize_node_path(parent_path) or "/"
        if not _ensure_parent_exists(parent_path):
            return _err(f"Could not fulfill parent path: {parent_path}")
        parent = hou.node(parent_path)
        if not parent:
            return _err(f"Parent node not found (even after fulfillment): {parent_path}")
        orig_type = node_type

        def _prepare_node_type(candidate_parent):
            candidate_context = _infer_child_context(candidate_parent)
            candidate_node_type = orig_type
            available_types = []
            try:
                child_category = (
                    candidate_parent.childTypeCategory()
                    if hasattr(candidate_parent, "childTypeCategory")
                    else None
                )
                node_types = child_category.nodeTypes() if child_category else {}
                available_types = list(node_types.keys())
            except Exception:
                available_types = []
            resolved_type = _resolve_node_type_name(
                candidate_node_type,
                available_node_types=available_types,
                aliases=SOP_TYPE_ALIASES,
            )
            if resolved_type.get("status") == "resolved":
                candidate_node_type = resolved_type.get("resolved") or candidate_node_type
            node_ok, safe_node = (
                _pipeline_interceptor.validate_node(candidate_context, candidate_node_type)
                if _pipeline_interceptor
                else (False, None)
            )
            if node_ok and safe_node:
                candidate_node_type = safe_node
            else:
                alias_hit = SOP_TYPE_ALIASES.get(candidate_node_type.strip().lower())
                if alias_hit:
                    candidate_node_type = alias_hit
            return candidate_context, candidate_node_type

        def _create_on_parent(candidate_parent):
            candidate_context, candidate_node_type = _prepare_node_type(candidate_parent)
            existing = None
            if name:
                if hasattr(candidate_parent, "node"):
                    try:
                        existing = candidate_parent.node(name)
                    except Exception:
                        existing = None
                if not existing and hasattr(hou, "node"):
                    try:
                        existing = hou.node(f"{candidate_parent.path().rstrip('/')}/{name}")
                    except Exception:
                        existing = None
            if existing and (
                existing.type().name() == candidate_node_type
                or existing.type().name().lower() == candidate_node_type.lower()
            ):
                return existing, candidate_node_type, candidate_context, None

            last_err = "Unknown error"
            node = None
            try:
                node = candidate_parent.createNode(candidate_node_type, name)
            except Exception as e:
                last_err = str(e)
                if "_v" in orig_type:
                    versioned = re.sub(r"_v(\d+)", r"::\1.0", orig_type)
                    try:
                        node = candidate_parent.createNode(versioned, name)
                        candidate_node_type = versioned
                    except Exception as ve:
                        last_err = str(ve)
            if not node:
                canonical = SOP_TYPE_ALIASES.get(orig_type.lower().strip())
                if canonical and canonical != candidate_node_type:
                    try:
                        node = candidate_parent.createNode(canonical, name)
                        candidate_node_type = canonical
                    except Exception as ce:
                        last_err = str(ce)
            return node, candidate_node_type, candidate_context, last_err

        node, node_type, context, last_err = _create_on_parent(parent)
        auto_corrected_parent = None
        if (
            not node
            and last_err
            and "cannot contain other nodes" in last_err.lower()
            and hasattr(parent, "parent")
        ):
            try:
                fallback_parent = parent.parent()
            except Exception:
                fallback_parent = None
            if fallback_parent and fallback_parent != parent:
                auto_corrected_parent = fallback_parent.path()
                parent = fallback_parent
                node, node_type, context, last_err = _create_on_parent(parent)

        if not node:
            suggestions = (
                _pipeline_interceptor.suggest_node_types(orig_type, context=context, n=5)
                if _pipeline_interceptor
                else []
            )
            suggestion_text = f" Did you mean one of: {suggestions}?" if suggestions else ""
            return _err(f"Failed to create node '{orig_type}': {last_err}.{suggestion_text}")
        node.moveToGoodPosition()

        # Phase 1 Simple: Automatic Viewport Framing (Safe implementation)
        if cook and HOU_AVAILABLE and hasattr(hou, "isGui") and hou.isGui():
            try:
                # Select the node to frame it
                node.setSelected(True, clear_all_selected=True)
                # Try to frame it in the active scene viewer if toolutils is available
                import toolutils

                viewer = getattr(toolutils, "sceneViewer", lambda: None)()
                if viewer and hasattr(viewer, "curViewport"):
                    viewport = viewer.curViewport()
                    if viewport and hasattr(viewport, "frameSelected"):
                        # Use hdefereval if possible to ensure UI safety
                        try:
                            import hdefereval

                            hdefereval.executeDeferred(viewport.frameSelected)
                        except ImportError:
                            viewport.frameSelected()
            except Exception:
                pass

        cook_errors = []
        is_filter = node_type.lower() in FILTER_NODE_TYPES or (
            hasattr(node, "inputs") and len(node.inputs()) > 0
        )
        if cook and not is_filter:
            try:
                node.cook(force=True)
                cook_errors = list(node.errors())
            except Exception as ce:
                cook_errors = [str(ce)]
        if hasattr(node, "setDisplayFlag"):
            node.setDisplayFlag(True)
        if hasattr(node, "setRenderFlag"):
            node.setRenderFlag(True)
        msg = f"UNDO_TRACK: Created {node.path()}"
        if auto_corrected_parent:
            msg += f" (auto-corrected parent to {auto_corrected_parent})"
        if node_type != orig_type:
            msg += f" (auto-corrected '{orig_type}' -> '{node_type}')"

        # Cook-error severity: expected-input errors on filter nodes (proximity,
        # group, copytopoints, etc.) are normal at creation time because the
        # node hasn't been wired yet. But "Error while cooking" or "attempted
        # operation failed" on a generator are real failures the agent must fix.
        fatal_cook_errors = []
        if cook_errors:
            FATAL_MARKERS = (
                "attempted operation failed",
                "error while cooking",
                "invalid source",
                "no such file",
            )
            EXPECTED_NO_INPUT_MARKERS = (
                "no input",
                "missing input",
                "input 0",
                "input 1",
                "is not connected",
            )
            for err in cook_errors:
                err_low = str(err).lower()
                if any(m in err_low for m in EXPECTED_NO_INPUT_MARKERS):
                    continue
                if any(m in err_low for m in FATAL_MARKERS):
                    fatal_cook_errors.append(str(err))

        if cook_errors:
            msg += f" — COOK ERRORS DETECTED: {cook_errors}"

        if fatal_cook_errors:
            return _err(
                f"Created {node.path()} but it has fatal cook errors: "
                f"{fatal_cook_errors}. Investigate before continuing — the node "
                f"is in the scene but not producing valid output. Use get_all_errors "
                f"and check inputs/parameters, or delete and recreate with a "
                f"different type if this node type is wrong for the task."
            )

        return _ok(
            {
                "path": node.path(),
                "type": node_type,
                "context": context,
                "errors": cook_errors,
                "original_request": orig_type,
            },
            message=msg,
        )
    except Exception as e:
        return _err(str(e))


def create_object_merge(parent_path, source_node_path, name=None):
    """Create an Object Merge SOP pointing to a source node."""
    try:
        _require_hou()
        node = create_node(parent_path, "object_merge", name=name)["data"]["path"]
        hou.node(node).parm("objpath1").set(source_node_path)
        return _ok(
            {"path": node}, message=f"UNDO_TRACK: Created Object Merge to {source_node_path}"
        )
    except Exception as e:
        return _err(str(e))


def create_copy_to_points_setup(parent_path, source_path, points_path, name="copy_to_points"):
    """Create a Copy to Points SOP and connect the source and points nodes."""
    try:
        _require_hou()
        copy_node = create_node(parent_path, "copytopoints", name=name)["data"]["path"]
        node = hou.node(copy_node)
        node.setInput(0, hou.node(source_path))
        node.setInput(1, hou.node(points_path))
        return _ok({"path": copy_node}, message="UNDO_TRACK: Created Copy to Points setup")
    except Exception as e:
        return _err(str(e))


def delete_node(node_path):
    """Delete a node."""
    try:
        _require_hou()
        node = hou.node(node_path)
        if not node:
            return _err(f"Node not found: {node_path}")
        node_type = node.type().name()
        node.destroy()
        # Memory Management: Clear undo stack after deletion to free memory in autonomous loops
        try:
            hou.undonest.clear()
        except Exception:
            pass
        return _ok(message=f"UNDO_TRACK: Deleted {node_path} ({node_type})")
    except Exception as e:
        return _err(str(e))


def get_bounding_box(node_path):
    """Return the bounding box (min, max, size, center) of a geometry node."""
    try:
        _require_hou()
        node = hou.node(node_path)
        if not node:
            return _err(f"Node not found: {node_path}")

        # Ensure it's a SOP or has geometry
        geo = None
        if hasattr(node, "geometry"):
            geo = node.geometry()

        if not geo:
            # Try to find the display node if it's a Geo object
            display_node = node.displayNode() if hasattr(node, "displayNode") else None
            if display_node:
                geo = display_node.geometry()

        if not geo:
            return _err(f"Node {node_path} has no geometry to measure.")

        bbox = geo.boundingBox()
        res = {
            "min": list(bbox.minvec()),
            "max": list(bbox.maxvec()),
            "size": list(bbox.sizevec()),
            "center": list(bbox.center()),
        }
        return _ok(res, message=f"Bounding Box for {node_path}: Size {res['size']}")
    except Exception as e:
        return _err(str(e))


def safe_set_parameter(node_path, parm_name, value):
    """Safely set a parameter value with alias handling and vector-component expansion."""
    try:
        _require_hou()
        node = hou.node(node_path)
        if not node:
            return _err(f"Node not found: {node_path}")
        return _set_node_parameter(node, parm_name, value)
    except Exception as e:
        return _err(str(e))


def set_parameter(node_path, parm_name, value):
    """Set a parameter to a literal value."""
    try:
        _require_hou()
        node = hou.node(node_path)
        if not node:
            return _err(f"Node not found: {node_path}")
        return _set_node_parameter(node, parm_name, value)
    except Exception as e:
        return _err(str(e))


def set_multiparm_count(node_path, parm_name, count):
    """Explicitly set the size of a multiparm block."""
    try:
        _require_hou()
        node = hou.node(node_path)
        if not node:
            return _err(f"Node not found: {node_path}")
        parm = node.parm(parm_name)
        if not parm:
            return _err(f"Multiparm counting parameter '{parm_name}' not found on {node_path}")
        if parm.parmTemplate().type() != hou.parmTemplateType.Int:
            return _err(f"Parameter '{parm_name}' is not an integer count parameter.")
        old = parm.eval()
        parm.set(count)
        return _ok(
            {"old": old, "new": count},
            message=f"Resized multiparm '{parm_name}' to {count}",
        )
    except Exception as e:
        return _err(str(e))


def set_expression(node_path, parm_name, expression, language="hscript"):
    """Set a parm to a HScript or Python expression."""
    try:
        _require_hou()
        node = hou.node(node_path)
        if not node:
            return _err(f"Node not found: {node_path}")
        parm = node.parm(parm_name)
        if not parm:
            return _err(f"Parm not found: {parm_name}")
        lang = hou.exprLanguage.Hscript if language == "hscript" else hou.exprLanguage.Python
        parm.setExpression(expression, lang)
        return _ok(
            {"expression": expression, "language": language},
            message=f"UNDO_TRACK: Set expression {node_path}/{parm_name} = {expression}",
        )
    except Exception as e:
        return _err(str(e))


def set_expression_from_description(node_path, parm_name, description, language="hscript"):
    """Translate a natural language description into a Houdini expression."""
    try:
        _require_hou()
        if not callable(core._shared_chat_simple_fn):
            return _err("LLM chat function not initialized in tools.py")
        node = hou.node(node_path)
        if not node:
            return _err(f"Node not found: {node_path}")
        parm = node.parm(parm_name)
        if not parm:
            available = [p.name() for p in node.parms()[:20]]
            return _err(f"Parameter '{parm_name}' not found on {node_path}. Available: {available}")
        node_type = node.type().name()
        system_prompt = (
            "You are a Houdini Expression Expert.\n"
            f"Convert the user's description into a valid Houdini {language.upper()} expression.\n"
            "Return ONLY the expression string, no quotes, no explanation, no markdown.\n"
            "Example Description: 'frame number'\n"
            "Example Output: $F\n"
            "Example Description: 'sine of time'\n"
            "Example Output: sin($T)"
        )
        user_prompt = f"Node Type: {node_type}\nParameter: {parm_name}\nLanguage: {language}\nDescription: {description}"
        expression = core._shared_chat_simple_fn(
            system=system_prompt, user=user_prompt, temperature=0.1, task="quick"
        ).strip()
        if expression.startswith("`") and expression.endswith("`"):
            expression = expression[1:-1].strip()
        if expression.startswith("'") and expression.endswith("'"):
            expression = expression[1:-1].strip()
        if expression.startswith('"') and expression.endswith('"'):
            expression = expression[1:-1].strip()
        lang_enum = hou.exprLanguage.Hscript if language == "hscript" else hou.exprLanguage.Python
        parm.setExpression(expression, lang_enum)
        return _ok(
            {"expression": expression, "language": language},
            message=f"UNDO_TRACK: Set expression from description '{description}' -> {node_path}/{parm_name} = {expression}",
        )
    except Exception as e:
        return _err(str(e))


def connect_nodes(from_path, to_path, from_out=0, to_in=0):
    """Wire two nodes together."""
    try:
        _require_hou()
        from_node = hou.node(from_path)
        to_node = hou.node(to_path)
        if not from_node:
            return _err(f"Source node not found: '{from_path}'.")
        if not to_node:
            return _err(f"Destination node not found: '{to_path}'.")
        to_node.setInput(to_in, from_node, from_out)
        return _ok(message=f"UNDO_TRACK: Connected {from_path}:{from_out} → {to_path}:{to_in}")
    except Exception as e:
        return _err(str(e))


def disconnect_node(node_path, input_index=0):
    """Disconnect a node's input at a given index."""
    try:
        _require_hou()
        node = hou.node(node_path)
        if not node:
            return _err(f"Node not found: {node_path}")
        node.setInput(input_index, None)
        return _ok(message=f"UNDO_TRACK: Disconnected {node_path} input {input_index}")
    except Exception as e:
        return _err(str(e))


def bypass_node(node_path, bypass=True):
    """Toggle bypass flag on a node."""
    try:
        _require_hou()
        node = hou.node(node_path)
        if not node:
            return _err(f"Node not found: {node_path}")
        node.bypass(bypass)
        state = "bypassed" if bypass else "unbypasssed"
        return _ok(message=f"UNDO_TRACK: {node_path} {state}")
    except Exception as e:
        return _err(str(e))


def set_display_flag(node_path, display=True, render=None):
    """Set the display and/or render flag on a SOP/DOP node."""
    try:
        _require_hou()
        node = hou.node(node_path)
        if not node:
            return _err(f"Node not found: {node_path}")
        if hasattr(node, "setDisplayFlag"):
            node.setDisplayFlag(display)
        if render is not None and hasattr(node, "setRenderFlag"):
            node.setRenderFlag(render)
        return _ok(message=f"UNDO_TRACK: Set display={display}, render={render} on {node_path}")
    except Exception as e:
        return _err(str(e))


def finalize_sop_network(parent_path, output_name="OUT", merge_name="MERGE_FINAL"):
    """Ensure a SOP network ends in a visible, display-flagged final output."""
    try:
        _require_hou()
        parent_path = _normalize_node_path(parent_path) or "/"
        parent = hou.node(parent_path)
        if not parent:
            return _err(f"Parent not found: {parent_path}")

        def _child(name):
            return hou.node(f"{parent_path.rstrip('/')}/{name}")

        def _geometry_counts(node):
            try:
                geo = node.geometry()
                if not geo:
                    return 0, 0
                return len(geo.points()), len(geo.prims())
            except Exception:
                return 1, 1

        def _same_parent_outputs(node):
            try:
                return [out for out in node.outputs() if out.parent() == parent]
            except Exception:
                return []

        def _clear_inputs(node):
            try:
                input_count = len(node.inputConnectors())
            except Exception:
                input_count = len(node.inputs())
            for idx in range(input_count):
                try:
                    node.setInput(idx, None)
                except Exception:
                    pass

        # Check for exact name OR any null whose name starts with "OUT"
        existing_out = _child(output_name)
        if not existing_out:
            for _c in parent.children():
                if (
                    _c.name().upper().startswith("OUT")
                    and _c.type().name() == "null"
                    and any(_c.inputs())
                ):
                    existing_out = _c
                    break
        if existing_out and any(existing_out.inputs()) and existing_out.type().name() == "null":
            try:
                existing_out.setDisplayFlag(True)
                existing_out.setRenderFlag(True)
            except Exception:
                pass
            # Report the exact node(s) connected to OUT so the LLM can verify
            # the wiring is correct (e.g. table merge, not an old sphere).
            connected_sources = [n for n in existing_out.inputs() if n]
            source_summary = (
                ", ".join(f"{n.name()} ({n.type().name()})" for n in connected_sources[:4])
                if connected_sources
                else "none"
            )
            return _ok(
                {
                    "output_path": existing_out.path(),
                    "merge_path": _child(merge_name).path() if _child(merge_name) else None,
                    "source_paths": [n.path() for n in connected_sources],
                    "reused_existing": True,
                },
                message=(
                    f"Network already finalized at {existing_out.path()}. "
                    f"Currently connected to: {source_summary}. "
                    f"If this is the wrong source, use connect_nodes to rewire OUT."
                ),
            )
        existing_merge = _child(merge_name)
        if (
            existing_merge
            and not _same_parent_outputs(existing_merge)
            and any(existing_merge.inputs())
        ):
            try:
                existing_merge.setDisplayFlag(True)
                existing_merge.setRenderFlag(True)
            except Exception:
                pass
            return _ok(
                {
                    "output_path": existing_merge.path(),
                    "merge_path": existing_merge.path(),
                    "source_paths": [n.path() for n in existing_merge.inputs() if n],
                    "reused_existing": True,
                },
                message=f"Network already finalized at {existing_merge.path()}",
            )
        terminals = []
        for node in parent.children():
            if node.name() == output_name:
                continue
            if node.name() == merge_name and any(node.inputs()):
                continue
            try:
                if node.errors() or node.isBypassed():
                    continue
            except (Exception, AttributeError):
                pass
            if _same_parent_outputs(node):
                continue
            p_count, pr_count = _geometry_counts(node)
            if p_count <= 0 and pr_count <= 0:
                continue
            score = 1
            if pr_count > 0:
                score += 4
            if node.type().name() in {
                "null",
                "output",
            } or node.name().lower().startswith("out"):
                score += 3
            try:
                if node.isDisplayFlagSet():
                    score += 2
            except Exception:
                pass
            terminals.append((score, pr_count, p_count, node))
        if not terminals:
            if existing_out:
                return _ok(
                    {"output_path": existing_out.path()},
                    message="No terminal SOP candidates found to finalize.",
                )
            return _err(f"No terminal SOP geometry found in {parent_path} to finalize.")
        terminals.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
        top_candidates = [item[3] for item in terminals[:6]]
        merge = _child(merge_name)
        if len(top_candidates) > 1:
            if not merge:
                merge = parent.createNode("merge", merge_name)
                merge.moveToGoodPosition()
            _clear_inputs(merge)
            for idx, candidate in enumerate(top_candidates):
                merge.setInput(idx, candidate)
            final_source = merge
        else:
            final_source = top_candidates[0]
            if merge and merge != final_source:
                merge.destroy()
                merge = None
        out_node = existing_out
        if not out_node:
            out_node = parent.createNode("null", output_name)
            out_node.moveToGoodPosition()
        out_node.setInput(0, final_source)
        try:
            out_node.setDisplayFlag(True)
            out_node.setRenderFlag(True)
            parent.layoutChildren()
        except Exception:
            pass
        return _ok(
            {
                "output_path": out_node.path(),
                "merge_path": merge.path() if merge and merge != final_source else None,
                "source_paths": [item[3].path() for item in terminals],
                "reused_existing": bool(existing_out),
            },
            message=f"UNDO_TRACK: Finalized SOP output at {out_node.path()}",
        )
    except Exception as e:
        return _err(str(e))


def set_relative_parameter(node_path, parm_name, target_node_path, mode="maxy"):
    """
    Set a parameter to an expression relative to another node's bounding box.
    Modes: minx, maxx, sizex, centerx, miny, maxy, sizey, centery, minz, maxz, sizez, centerz
    """
    try:
        _require_hou()
        node = hou.node(node_path)
        if not node:
            return _err(f"Source node not found: {node_path}")

        mode_map = {
            "minx": "D_XMIN",
            "maxx": "D_XMAX",
            "sizex": "D_XSIZE",
            "centerx": "D_XCENT",
            "miny": "D_YMIN",
            "maxy": "D_YMAX",
            "sizey": "D_YSIZE",
            "centery": "D_YCENT",
            "minz": "D_ZMIN",
            "maxz": "D_ZMAX",
            "sizez": "D_ZSIZE",
            "centerz": "D_ZCENT",
        }

        if mode not in mode_map:
            return _err(f"Invalid mode: {mode}. Choose from: {list(mode_map.keys())}")

        rel_path = node.relativePathTo(hou.node(target_node_path))
        expression = f'bbox("{rel_path}", {mode_map[mode]})'

        parm = node.parm(parm_name)
        if not parm:
            return _err(f"Parameter {parm_name} not found on {node_path}")

        parm.setExpression(expression)
        return _ok({"expression": expression}, message=f"Set {parm_name} to {expression}")
    except Exception as e:
        return _err(str(e))


def write_vex_code(node_path, vex_code):
    """Write VEX code into an Attribute Wrangle / VOP node's 'snippet' parm."""
    try:
        _require_hou()
        if vex_code:
            vex_code = vex_code.replace("\r\n", "\n").replace("\r", "\n")
        node = hou.node(node_path)
        if not node:
            return _err(f"Node not found: {node_path}")
        snippet_parm = node.parm("snippet")
        if not snippet_parm:
            return _err(f"No 'snippet' parm on {node_path} — is this a Wrangle node?")
        valid_res = _validate_vex_with_checker(vex_code)
        if not valid_res["success"]:
            return _err(
                f"VEX compile failed for {node_path}: "
                f"{valid_res['errors'][0] if valid_res['errors'] else 'Unknown error'}",
                {"errors": valid_res["errors"], "status": "validation_failed"},
            )
        snippet_parm.set(vex_code)
        try:
            node.cook()
        except Exception:
            pass
        return _ok(
            {
                "errors": [],
                "warnings": valid_res["warnings"],
                "lines": len(vex_code.splitlines()),
            },
            message=f"UNDO_TRACK: Wrote VEX to {node_path}"
            + (
                f" — warnings: {valid_res['warnings']}"
                if valid_res["warnings"]
                else " — compiled OK"
            ),
        )
    except Exception as e:
        return _err(str(e))


def write_python_script(node_path, code):
    """Write Python code into a Python Script SOP's 'python' parm."""
    try:
        _require_hou()
        node = hou.node(node_path)
        if not node:
            return _err(f"Node not found: {node_path}")
        py_parm = node.parm("python")
        if not py_parm:
            return _err(f"No 'python' parm on {node_path} — is this a Python Script SOP?")
        val_res = _validate_python_code(code)
        if not val_res.get("success"):
            return _err(
                f"Python validation FAILED for {node_path}: {val_res.get('errors')[0]}",
                {"errors": val_res.get("errors"), "status": "validation_failed"},
            )
        py_parm.set(code)
        try:
            node.cook(force=True)
            errors = list(node.errors())
        except Exception as cook_err:
            errors = [str(cook_err)]
        return _ok(
            {"errors": errors, "lines": len(code.splitlines())},
            message=f"UNDO_TRACK: Wrote Python to {node_path}"
            + (f" — ERRORS: {errors}" if errors else " — ran OK"),
        )
    except Exception as e:
        return _err(str(e))


def _python_code_writes_wrangle_snippet(code):
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False
    snippet_names = {"snippet", "vex", "vex_code", "vexcode", "vex_snippet"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "set":
            target = func.value
            if isinstance(target, ast.Call) and isinstance(target.func, ast.Attribute):
                if target.func.attr == "parm" and target.args:
                    arg = target.args[0]
                    if isinstance(arg, ast.Constant) and str(arg.value).lower() in snippet_names:
                        return True
        if isinstance(func, ast.Attribute) and func.attr in {"setParms", "setParmsPending"}:
            if node.args and isinstance(node.args[0], ast.Dict):
                for key in node.args[0].keys:
                    if isinstance(key, ast.Constant) and str(key.value).lower() in snippet_names:
                        return True
    return bool(
        re.search(
            r"\.parm\s*\(\s*['\"](?:snippet|vex(?:_code|code|_snippet)?)['\"]\s*\)\s*\.set\s*\(",
            code,
        )
        or re.search(r"\.setParms(?:Pending)?\s*\(\s*\{[^}]*['\"]snippet['\"]\s*:", code, re.S)
    )


def execute_python(code):
    """Execute arbitrary Python code in the Houdini session."""
    try:
        val_res = _validate_python_code(code)
        if not val_res.get("success"):
            return _err(
                f"Python script validation FAILED: {val_res.get('errors')[0]}",
                {"errors": val_res.get("errors"), "status": "validation_failed"},
            )
        if _python_code_writes_wrangle_snippet(code):
            return _err(
                "Direct Python writes to wrangle snippet parameters are blocked. "
                "Use write_vex_code(node_path, vex_code) so VEX is validated and cooked before it is kept."
            )
        _require_hou()
        import io as _io
        from contextlib import redirect_stdout as _redirect_stdout

        f = _io.StringIO()
        with _redirect_stdout(f):
            exec_globals = {"hou": hou, "TOOL_FUNCTIONS": core._get_tool_functions()}
            exec_globals.update(core._get_tool_functions())
            exec(code, exec_globals)
        output = f.getvalue().strip()
        return _ok(
            {"output": output},
            message=f"UNDO_TRACK: Executed Python script ({len(code.splitlines())} lines)",
        )
    except Exception as e:
        return _err(f"Python Execution Error: {e}\n{_tb.format_exc()}")
