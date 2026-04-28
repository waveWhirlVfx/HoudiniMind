# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
"""
Geometry tools: analysis, bounding box, sampling, checking.
"""

import math as _math
import random
import traceback as _tb

from . import _core as core

_ok = core._ok
_err = core._err
_require_hou = core._require_hou
_resolve_geometry_source_node = core._resolve_geometry_source_node

try:
    import hou

    HOU_AVAILABLE = core.HOU_AVAILABLE
except ImportError:
    HOU_AVAILABLE = False
    hou = None


def _resolve_node_geometry(node):
    source_node = _resolve_geometry_source_node(node) or node
    geo_getter = getattr(source_node, "geometry", None)
    if not callable(geo_getter):
        return source_node, None
    try:
        return source_node, geo_getter()
    except Exception:
        return source_node, None


def _geometry_attribs(geo, owner: str):
    getter_map = {
        "detail": ("globalAttribs", "detailAttribs"),
        "point": ("pointAttribs",),
        "prim": ("primAttribs",),
        "vertex": ("vertexAttribs",),
    }
    for getter_name in getter_map.get(owner, ()):
        getter = getattr(geo, getter_name, None)
        if callable(getter):
            try:
                return list(getter() or [])
            except Exception:
                pass
    attrib_type_name = {
        "detail": "Detail",
        "point": "Point",
        "prim": "Prim",
        "vertex": "Vertex",
    }.get(owner)
    attrib_type = getattr(getattr(hou, "attribType", None), attrib_type_name, None)
    legacy_getter = getattr(geo, "attribs", None)
    if callable(legacy_getter) and attrib_type is not None:
        try:
            return list(legacy_getter(attrib_type) or [])
        except Exception:
            pass
    return []


def analyze_geometry(node_path):
    """Deep geometric analysis: bbox, counts, attributes, UVs, normals, memory estimate."""
    try:
        _require_hou()
        node = hou.node(node_path)
        if not node:
            return _err(f"Node not found: {node_path}")
        resolved_node, geo = _resolve_node_geometry(node)
        if not geo:
            return _err("No geometry output")
        bbox = geo.boundingBox()
        pts = geo.points()
        prims = geo.prims()
        prim_types = {}
        for p in prims:
            k = str(p.type())
            prim_types[k] = prim_types.get(k, 0) + 1

        def _ai(attribs):
            return [
                {"name": a.name(), "type": str(a.dataType()), "size": a.size()} for a in attribs
            ]

        size = bbox.sizevec()
        detail_attribs = _geometry_attribs(geo, "detail")
        point_attribs = _geometry_attribs(geo, "point")
        prim_attribs = _geometry_attribs(geo, "prim")
        vertex_attribs = _geometry_attribs(geo, "vertex")
        return _ok(
            {
                "resolved_node_path": resolved_node.path(),
                "point_count": len(pts),
                "prim_count": len(prims),
                "prim_type_breakdown": prim_types,
                "bounding_box": {
                    "min": list(bbox.minvec()),
                    "max": list(bbox.maxvec()),
                    "size": list(size),
                    "centre": list(bbox.center()),
                    "volume_approx": round(size[0] * size[1] * size[2], 4),
                },
                "attributes": {
                    "detail": _ai(detail_attribs),
                    "point": _ai(point_attribs),
                    "prim": _ai(prim_attribs),
                    "vertex": _ai(vertex_attribs),
                },
                "has_uvs": any(a.name() in ("uv", "UV", "st") for a in point_attribs),
                "has_normals": any(a.name() == "N" for a in point_attribs),
                "has_cd": any(a.name() == "Cd" for a in point_attribs),
                "estimated_memory_mb": round((len(pts) * 12 + len(prims) * 4) / 1e6, 3),
            }
        )
    except Exception:
        return _err(_tb.format_exc())


def get_bounding_box(node_path):
    """Return bounding box (min/max/size/centre/diagonal) of a node's geometry."""
    try:
        _require_hou()
        node = hou.node(node_path)
        if not node:
            return _err(f"Node not found: {node_path}")
        _resolved_node, geo = _resolve_node_geometry(node)
        if not geo:
            return _err("No geometry")
        bb = geo.boundingBox()
        size = bb.sizevec()
        return _ok(
            {
                "min": list(bb.minvec()),
                "max": list(bb.maxvec()),
                "size": list(size),
                "centre": list(bb.center()),
                "diagonal": round(_math.sqrt(sum(v**2 for v in list(size))), 4),
            }
        )
    except Exception as e:
        return _err(str(e))


def sample_geometry(node_path, num_points=10, attributes=None):
    """Sample a random subset of points and their attribute values."""
    try:
        _require_hou()
        node = hou.node(node_path)
        if not node:
            return _err(f"Node not found: {node_path}")
        _resolved_node, geo = _resolve_node_geometry(node)
        if not geo:
            return _err("No geometry")
        pts = geo.points()
        if not pts:
            return _ok({"samples": [], "total_points": 0})
        sample_pts = random.sample(pts, min(num_points, len(pts)))
        all_attrs = [a.name() for a in _geometry_attribs(geo, "point")]
        attrs_to_read = attributes if attributes else all_attrs[:8]
        samples = []
        for pt in sample_pts:
            entry = {"point_num": pt.number(), "position": list(pt.position())}
            for attr in attrs_to_read:
                try:
                    entry[attr] = pt.attribValue(attr)
                except Exception:
                    pass
            samples.append(entry)
        return _ok(
            {
                "total_points": len(pts),
                "sampled": len(samples),
                "attributes_available": all_attrs,
                "samples": samples,
            }
        )
    except Exception as e:
        return _err(str(e))


def check_geometry_issues(node_path):
    """Quality check: zero-area prims, NaN points, unreferenced points."""
    try:
        _require_hou()
        node = hou.node(node_path)
        if not node:
            return _err(f"Node not found: {node_path}")
        _resolved_node, geo = _resolve_node_geometry(node)
        if not geo:
            return _err("No geometry")
        pts = geo.points()
        prims = geo.prims()
        issues = []
        zero_area = 0
        for p in list(prims)[:500]:
            try:
                if hasattr(p, "intrinsicValue") and p.intrinsicValue("measuredarea") < 1e-10:
                    zero_area += 1
            except Exception:
                pass
        if zero_area:
            issues.append(f"{zero_area} zero-area polygons (can break Boolean/Vellum)")
        nan_pts = sum(
            1 for pt in list(pts)[:2000] if any(_math.isnan(v) for v in tuple(pt.position()))
        )
        if nan_pts:
            issues.append(f"{nan_pts} points with NaN positions (will explode sims)")
        used = set()
        for p in list(prims)[:1000]:
            for v in p.vertices():
                used.add(v.point().number())
        unreferenced = len(pts) - len(used)
        if unreferenced > 0:
            issues.append(f"{unreferenced} unreferenced points (waste memory)")
        return _ok(
            {
                "total_points": len(pts),
                "total_prims": len(prims),
                "issues": issues,
                "clean": len(issues) == 0,
            }
        )
    except Exception:
        return _err(_tb.format_exc())


def get_parameter_details(node_path, parm_name):
    """Return detailed metadata for a parameter: range, default, type, menu options."""
    try:
        _require_hou()
        node = hou.node(node_path)
        if not node:
            return _err(f"Node not found: {node_path}")
        parm = node.parm(parm_name)
        if not parm:
            return _err(f"Parameter not found: {parm_name}")
        templ = parm.parmTemplate()
        details = {
            "name": parm.name(),
            "label": parm.label(),
            "type": str(templ.type()),
            "default": templ.defaultValue() if hasattr(templ, "defaultValue") else None,
            "expression": parm.expression() if parm.expression() else None,
            "language": str(parm.expressionLanguage()) if parm.expression() else None,
        }
        if hasattr(templ, "numComponents"):
            details["size"] = templ.numComponents()
        if hasattr(templ, "min") and hasattr(templ, "max"):
            details["range"] = [templ.min(), templ.max()]
            details["min_is_strict"] = templ.minIsStrict()
            details["max_is_strict"] = templ.maxIsStrict()
        if hasattr(templ, "menuItems"):
            details["menu_items"] = templ.menuItems()
            details["menu_labels"] = templ.menuLabels()
        return _ok(details)
    except Exception as e:
        return _err(str(e))


def get_stacking_offset(lower_node_path, upper_node_path, axis="y"):
    """Calculate the exact transform offset to stack upper_node on top of lower_node."""
    try:
        _require_hou()
        lower = hou.node(lower_node_path)
        upper = hou.node(upper_node_path)
        if not lower or not upper:
            return _err("Missing node path")
        try:
            lower.cook()
            upper.cook()
        except Exception:
            pass
        l_geo = lower.geometry()
        u_geo = upper.geometry()
        if not l_geo or not u_geo:
            return _err("Nodes must have geometry to calculate stacking")
        l_bbox = l_geo.boundingBox()
        u_bbox = u_geo.boundingBox()
        offset = 0.0
        if axis.lower() == "y":
            offset = l_bbox.maxvec()[1] - u_bbox.minvec()[1]
        elif axis.lower() == "x":
            offset = l_bbox.maxvec()[0] - u_bbox.minvec()[0]
        elif axis.lower() == "z":
            offset = l_bbox.maxvec()[2] - u_bbox.minvec()[2]
        return _ok(
            {
                "offset": round(offset, 4),
                "axis": axis,
                "hints": {
                    "base_max": round(l_bbox.maxvec()[1] if axis == "y" else 0, 4),
                    "top_min": round(u_bbox.minvec()[1] if axis == "y" else 0, 4),
                },
            },
            message=f"To stack {upper.name()} on {lower.name()}, set t{axis} to current_value + {round(offset, 4)}",
        )
    except Exception as e:
        return _err(str(e))


def batch_align_to_support(support_node_path, target_node_paths, axis="y"):
    """Align multiple nodes to a single support node's bounding box boundaries."""
    try:
        _require_hou()
        support = hou.node(support_node_path)
        if not support:
            return _err(f"Support node not found: {support_node_path}")
        s_geo = support.geometry()
        if not s_geo:
            return _err("Support node has no geometry")
        s_bbox = s_geo.boundingBox()
        results = []
        for path in target_node_paths:
            node = hou.node(path)
            if not node:
                continue
            node.cook()
            n_geo = node.geometry()
            if not n_geo:
                continue
            n_bbox = n_geo.boundingBox()
            offset = 0.0
            if axis == "y":
                offset = s_bbox.maxvec()[1] - n_bbox.minvec()[1]
                node.parm("ty").set(node.parm("ty").eval() + offset)
            elif axis == "-y":
                offset = s_bbox.minvec()[1] - n_bbox.maxvec()[1]
                node.parm("ty").set(node.parm("ty").eval() + offset)
            results.append({"node": path, "applied_offset": round(offset, 4)})
        return _ok(
            {"results": results},
            message=f"Aligned {len(results)} nodes to {support.name()} on {axis}",
        )
    except Exception as e:
        return _err(str(e))


def create_transformed_node(parent_path, node_type, name, parms=None, support_node=None):
    """Atomic creation: creates a node, sets parameters, and optionally stacks it."""
    try:
        _require_hou()
        parent = hou.node(parent_path)
        if not parent:
            return _err(f"Parent not found: {parent_path}")
        node = parent.createNode(node_type, name)
        if parms:
            for k, v in parms.items():
                p = node.parm(k)
                if p:
                    p.set(v)
                else:
                    for i, comp in enumerate(["x", "y", "z"]):
                        pc = node.parm(f"{k}{comp}")
                        if pc:
                            if isinstance(v, (list, tuple)) and i < len(v):
                                pc.set(v[i])
                            elif not isinstance(v, (list, tuple)):
                                pc.set(v)
        if support_node:
            s_node = hou.node(support_node)
            if not s_node:
                s_node = parent.node(support_node)
            if s_node:
                node.cook()
                s_node.cook()
                alignment = batch_align_to_support(s_node.path(), [node.path()], axis="y")
                if alignment["status"] == "ok":
                    return _ok(
                        {
                            "path": node.path(),
                            "message": f"Created {node.name()} and stacked on {s_node.name()}",
                            "alignment": alignment["data"],
                        }
                    )
        node.moveToGoodPosition()
        return _ok({"path": node.path(), "name": node.name()})
    except Exception as e:
        return _err(str(e))


def audit_network_layout(parent_path="/obj", threshold=10.0):
    """Check for nodes that are overlapping or too close in the network editor."""
    try:
        _require_hou()
        parent = hou.node(parent_path)
        if not parent:
            return _err(f"Node not found: {parent_path}")
        nodes = parent.children()
        overlaps = []
        for i, n1 in enumerate(nodes):
            for n2 in nodes[i + 1 :]:
                dist = n1.position().distanceTo(n2.position())
                if dist < threshold:
                    overlaps.append(f"{n1.name()} and {n2.name()} (dist: {round(dist, 2)})")
        return _ok({"overlaps": overlaps, "count": len(overlaps)})
    except Exception as e:
        return _err(str(e))
