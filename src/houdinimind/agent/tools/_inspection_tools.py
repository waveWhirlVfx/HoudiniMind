# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
"""
Inspection tools: parameters, inputs, geometry, network inspection.
"""

import traceback as _traceback

from . import _core as core

_ok = core._ok
_err = core._err
_require_hou = core._require_hou
_normalize_node_path = core._normalize_node_path
_resolve_geometry_source_node = core._resolve_geometry_source_node
_infer_child_context = core._infer_child_context
_pipeline_interceptor = core._pipeline_interceptor
_schema_pool_for_context = core._schema_pool_for_context
_schema_pool_for_node = core._schema_pool_for_node
_rank_text_candidates = core._rank_text_candidates
_tokenize_hint_text = core._tokenize_hint_text
_parm_alias_candidates = core._parm_alias_candidates
_close_matches = core._close_matches
_ordered_unique = core._ordered_unique
_HINT_STOPWORDS = core._HINT_STOPWORDS
_PARM_BASE_ALIASES = core._PARM_BASE_ALIASES
_PARM_COMPONENT_ALIASES = core._PARM_COMPONENT_ALIASES
_INTERNAL_PARM_BLACKLIST = core._INTERNAL_PARM_BLACKLIST
_SOP_TYPE_ALIASES = core.SOP_TYPE_ALIASES

try:
    import hou

    HOU_AVAILABLE = core.HOU_AVAILABLE
except ImportError:
    HOU_AVAILABLE = False
    hou = None


def get_node_parameters(node_path, compact=True):
    """Read all parameter values, labels, and types."""
    try:
        _require_hou()
        node = hou.node(node_path)
        if not node:
            return _err(f"Node not found: {node_path}")
        parms = {}
        read_errors = []

        def _safe_eval(p):
            for strategy, fn in [
                ("eval", p.eval),
                ("evalAsString", p.evalAsString),
                ("unexpandedString", p.unexpandedString),
                ("rawValue", getattr(p, "rawValue", lambda: None)),
            ]:
                try:
                    v = fn()
                    if v is not None:
                        return v, strategy
                except Exception:
                    continue
            return None, "unavailable"

        for p in node.parms():
            try:
                tmpl = p.parmTemplate()
                val, strategy = _safe_eval(p)
                if compact:
                    if isinstance(tmpl, hou.MenuParmTemplate):
                        parms[p.name()] = {"v": val, "m": True}
                    else:
                        parms[p.name()] = val
                else:
                    parm_data = {
                        "value": val,
                        "read_strategy": strategy,
                        "label": p.description(),
                        "type": str(tmpl.type()),
                        "is_menu": False,
                    }
                    if isinstance(tmpl, hou.MenuParmTemplate):
                        try:
                            labels = list(tmpl.menuLabels())
                            parm_data["is_menu"] = True
                            parm_data["menu_hint"] = (
                                f"Menu with {len(labels)} items. "
                                "Pass the label string (e.g. 'Polygon') or integer index."
                            )
                        except Exception:
                            pass
                    parms[p.name()] = parm_data
            except Exception as e:
                read_errors.append(f"{p.name()}: {e}")
                continue

        seen = set(parms.keys())
        try:
            for pt in node.parmTuples():
                if pt.name() in seen:
                    continue
                try:
                    val, strategy = _safe_eval(pt)
                    if compact:
                        parms[pt.name()] = val
                    else:
                        parms[pt.name()] = {
                            "value": val,
                            "read_strategy": strategy,
                            "label": pt.description(),
                            "type": "tuple",
                            "is_menu": False,
                            "components": [p.name() for p in pt],
                        }
                except Exception as e:
                    read_errors.append(f"tuple:{pt.name()}: {e}")
        except Exception:
            pass

        result = {
            "path": node_path,
            "type": node.type().name(),
            "parameter_count": len(parms),
            "parameters": parms,
        }
        if read_errors:
            result["read_errors"] = read_errors
        return _ok(result)
    except Exception:
        return _err(_traceback.format_exc())


def get_node_inputs(node_path, only_connected=True):
    """Check input connections and any red-arrow errors."""
    try:
        _require_hou()
        node = hou.node(node_path)
        if not node:
            return _err("Node not found")
        input_names = list(node.inputNames()) if hasattr(node, "inputNames") else []
        raw_inputs = list(node.inputs()) if hasattr(node, "inputs") else []
        raw_connectors = list(node.inputConnectors()) if hasattr(node, "inputConnectors") else []
        input_count = max(len(input_names), len(raw_inputs), len(raw_connectors))
        inputs = []
        for i in range(input_count):
            conn = raw_connectors[i] if i < len(raw_connectors) else None
            conn_errors = []
            if hasattr(conn, "errors"):
                try:
                    conn_errors = list(conn.errors())
                except Exception:
                    conn_errors = []
            elif isinstance(conn, (list, tuple)):
                for nested in conn:
                    if hasattr(nested, "errors"):
                        try:
                            conn_errors.extend(list(nested.errors()))
                        except Exception:
                            pass
            inputs.append(
                {
                    "index": i,
                    "label": input_names[i] if i < len(input_names) else f"Input {i}",
                    "connected_to": raw_inputs[i].path()
                    if i < len(raw_inputs) and raw_inputs[i]
                    else None,
                    "errors": conn_errors,
                }
            )
        connected_inputs = [
            inp for inp in inputs if inp["connected_to"] is not None or inp["errors"]
        ]
        return _ok(
            {
                "node": node_path,
                "inputs": connected_inputs,
                "total_input_slots": len(inputs),
                "connected_count": len(connected_inputs),
            }
        )
    except Exception as e:
        return _err(str(e))


def get_geometry_attributes(node_path, max_attribs=50):
    """Read all point/prim/vertex/detail attributes from a SOP node."""
    try:
        _require_hou()
        node = hou.node(node_path)
        if not node:
            return _err(f"Node not found: {node_path}")
        source_node = _resolve_geometry_source_node(node)
        geo = source_node.geometry() if callable(getattr(source_node, "geometry", None)) else None
        if not geo:
            return _err("No geometry on this node — ensure it is a SOP node that has cooked.")
        result = {
            "resolved_node_path": source_node.path() if hasattr(source_node, "path") else node_path,
            "detail": {},
            "point_attrs": [],
            "prim_attrs": [],
            "vertex_attrs": [],
        }

        point_attribs = list(getattr(geo, "pointAttribs", lambda: [])() or [])
        prim_attribs = list(getattr(geo, "primAttribs", lambda: [])() or [])
        vertex_attribs = list(getattr(geo, "vertexAttribs", lambda: [])() or [])
        detail_attribs = list(getattr(geo, "globalAttribs", lambda: [])() or [])

        result["point_attrs"] = [attrib.name() for attrib in point_attribs[:max_attribs]]
        result["prim_attrs"] = [attrib.name() for attrib in prim_attribs[:max_attribs]]
        result["vertex_attrs"] = [attrib.name() for attrib in vertex_attribs[:max_attribs]]
        for attrib in detail_attribs[:max_attribs]:
            try:
                result["detail"][attrib.name()] = geo.attribValue(attrib.name())
            except Exception:
                result["detail"][attrib.name()] = None

        result["point_count"] = len(getattr(geo, "points", lambda: [])() or [])
        result["prim_count"] = len(getattr(geo, "prims", lambda: [])() or [])
        return _ok(result, message=f"Read attributes from {result['resolved_node_path']}")
    except Exception:
        return _err(_traceback.format_exc())


def inspect_display_output(parent_path):
    """Resolve the currently visible/renderable output under a node or network."""
    try:
        _require_hou()
        parent = hou.node(parent_path)
        if not parent:
            return _err(f"Node not found: {parent_path}")
        display_node = None
        render_node = None
        for attr_name, target_name in (
            ("displayNode", "display"),
            ("renderNode", "render"),
        ):
            getter = getattr(parent, attr_name, None)
            if callable(getter):
                try:
                    resolved = getter()
                except Exception:
                    resolved = None
                if resolved is not None:
                    if target_name == "display":
                        display_node = resolved
                    else:
                        render_node = resolved
        try:
            children = list(parent.children())
        except Exception:
            children = []
        if not display_node:
            for child in children:
                try:
                    if child.isDisplayFlagSet():
                        display_node = child
                        break
                except Exception:
                    continue
        if not render_node:
            for child in children:
                try:
                    if child.isRenderFlagSet():
                        render_node = child
                        break
                except Exception:
                    continue
        primary_node = display_node or render_node or parent
        geometry_node = _resolve_geometry_source_node(primary_node)
        if not geometry_node or not callable(getattr(geometry_node, "geometry", None)):
            return _err(f"No visible geometry output found under {parent_path}")
        geo = geometry_node.geometry()
        if not geo:
            return _err(f"{geometry_node.path()} has no cooked geometry")
        errors, warnings = [], []
        for attr_name, bucket in (("errors", errors), ("warnings", warnings)):
            getter = getattr(geometry_node, attr_name, None)
            if callable(getter):
                try:
                    bucket.extend(list(getter()))
                except Exception:
                    pass
        return _ok(
            {
                "parent_path": parent_path,
                "display_path": display_node.path() if display_node else None,
                "render_path": render_node.path() if render_node else None,
                "resolved_geometry_path": geometry_node.path(),
                "point_count": len(geo.points()),
                "prim_count": len(geo.prims()),
                "error_count": len(errors),
                "warning_count": len(warnings),
                "errors": errors,
                "warnings": warnings,
                "has_visible_output": True,
            },
            message=f"Visible output resolved to {geometry_node.path()}",
        )
    except Exception as e:
        return _err(str(e))


def get_current_node_path():
    """Get the currently selected or context node path."""
    try:
        _require_hou()
        sel = hou.selectedNodes()
        if sel:
            return _ok({"path": sel[0].path()})
        pane = hou.ui.paneTabOfType(hou.paneTabType.NetworkEditor)
        if pane:
            return _ok({"path": pane.pwd().path()})
        return _err("No context")
    except Exception:
        return _err("Context error")


def find_nodes(pattern="*", node_type=None, has_errors=False, root="/"):
    """Search the scene for nodes matching a name pattern, type filter, or error state."""
    try:
        _require_hou()
        root_node = hou.node(root)
        if not root_node:
            return _err(f"Root not found: {root}")
        node_type_filter = getattr(hou, "NodeTypeFilter", None)
        type_filter = getattr(node_type_filter, "NoFilter", None) if node_type_filter else None
        if node_type:
            if node_type_filter:
                type_map = {
                    "sop": getattr(node_type_filter, "Sop", None),
                    "dop": getattr(node_type_filter, "Dop", None),
                    "obj": getattr(node_type_filter, "Object", None),
                    "object": getattr(node_type_filter, "Object", None),
                    "objects": getattr(node_type_filter, "Object", None),
                    "lop": getattr(node_type_filter, "Lop", None),
                    "stage": getattr(node_type_filter, "Lop", None),
                    "rop": getattr(node_type_filter, "Rop", None),
                    "out": getattr(node_type_filter, "Rop", None),
                    "vop": getattr(node_type_filter, "Vop", None),
                    "mat": getattr(node_type_filter, "Vop", None),
                }
                type_filter = type_map.get(node_type.lower(), type_filter)
        if type_filter is None:
            matched = root_node.recursiveGlob(pattern)
        else:
            matched = root_node.recursiveGlob(pattern, filter=type_filter)
        results = []
        for n in matched:
            if node_type and not node_type_filter:
                category = ""
                try:
                    category = n.type().category().name().lower()
                except Exception:
                    category = ""
                aliases = {
                    "obj": "object",
                    "objects": "object",
                    "stage": "lop",
                    "out": "rop",
                    "mat": "vop",
                }
                wanted = aliases.get(node_type.lower(), node_type.lower())
                if wanted not in {category, n.type().name().lower()}:
                    continue
            errs = list(n.errors())
            warns = list(n.warnings())
            if has_errors and not errs and not warns:
                continue
            results.append(
                {
                    "path": n.path(),
                    "type": n.type().name(),
                    "errors": errs,
                    "warnings": warns,
                }
            )
        return _ok({"count": len(results), "nodes": results})
    except Exception:
        return _err(_traceback.format_exc())


def measure_cook_time(node_path, num_frames=1):
    """Force-cook a node and measure its cook time in milliseconds."""
    try:
        _require_hou()
        node = hou.node(node_path)
        if not node:
            return _err(f"Node not found: {node_path}")
        current_frame = hou.frame()
        times = []
        for i in range(num_frames):
            if num_frames > 1:
                hou.setFrame(current_frame + i)
            t0 = core.time.perf_counter()
            node.cook(force=True)
            t1 = core.time.perf_counter()
            times.append((t1 - t0) * 1000)
        if num_frames > 1:
            hou.setFrame(current_frame)
        avg_ms = sum(times) / len(times)
        return _ok(
            {
                "avg_ms": round(avg_ms, 2),
                "min_ms": round(min(times), 2),
                "max_ms": round(max(times), 2),
                "num_frames": num_frames,
            }
        )
    except Exception as e:
        return _err(str(e))
