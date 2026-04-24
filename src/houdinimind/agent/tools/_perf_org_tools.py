# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
"""
Performance, organization, export, animation tools.
"""

import base64
import os as _os
import re
import subprocess
import tempfile
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


# ── Performance diagnostics ──────────────────────────────────────────────────


def profile_network(parent_path, top_n=10):
    """Cook every node in a network and return leaderboard of slowest nodes."""
    try:
        _require_hou()
        parent = hou.node(parent_path)
        if not parent:
            return _err(f"Parent not found: {parent_path}")
        results = []
        for node in parent.children():
            t0 = core.time.perf_counter()
            try:
                node.cook(force=True)
            except Exception:
                pass
            elapsed_ms = (core.time.perf_counter() - t0) * 1000
            results.append(
                {
                    "path": node.path(),
                    "type": node.type().name(),
                    "cook_ms": round(elapsed_ms, 2),
                    "errors": list(node.errors()),
                }
            )
        results.sort(key=lambda x: x["cook_ms"], reverse=True)
        total_ms = sum(r["cook_ms"] for r in results)
        return _ok(
            {
                "total_ms": round(total_ms, 2),
                "node_count": len(results),
                "top_slowest": results[:top_n],
            }
        )
    except Exception as e:
        return _err(_tb.format_exc())


def deep_error_trace(start_node_path):
    """Trace errors upstream to find ROOT CAUSE."""
    try:
        _require_hou()
        node = hou.node(start_node_path)
        if not node:
            return _err(f"Node not found: {start_node_path}")
        visited = set()
        chain = []

        def trace(n, depth=0):
            if n is None or n.path() in visited or depth > 20:
                return
            visited.add(n.path())
            errs = list(n.errors())
            warns = list(n.warnings())
            if errs or warns:
                chain.append(
                    {
                        "path": n.path(),
                        "type": n.type().name(),
                        "depth_from_start": depth,
                        "errors": errs,
                        "warnings": warns,
                    }
                )
            for inp in n.inputs():
                trace(inp, depth + 1)

        trace(node)
        chain.reverse()
        return _ok(
            {
                "start_node": start_node_path,
                "error_chain": chain,
                "root_cause": chain[0] if chain else None,
                "total_affected": len(chain),
            }
        )
    except Exception as e:
        return _err(_tb.format_exc())


def get_node_cook_info(node_path):
    """Get cook state: dirty, time-dependent, bypassed, locked, errors, cook count."""
    try:
        _require_hou()
        node = hou.node(node_path)
        if not node:
            return _err(f"Node not found: {node_path}")
        return _ok(
            {
                "path": node_path,
                "type": node.type().name(),
                "is_time_dependent": node.isTimeDependent(),
                "is_bypassed": node.isBypassed(),
                "is_locked": node.isHardLocked()
                if hasattr(node, "isHardLocked")
                else False,
                "errors": list(node.errors()),
                "warnings": list(node.warnings()),
                "cook_count": node.cookCount() if hasattr(node, "cookCount") else None,
            }
        )
    except Exception as e:
        return _err(str(e))


def get_memory_usage():
    """Return Houdini process memory usage in MB."""
    try:
        import psutil

        proc = psutil.Process()
        return _ok({"rss_mb": proc.memory_info().rss / 1024 / 1024})
    except ImportError:
        return _err("psutil not found.")
    except Exception as e:
        return _err(_tb.format_exc())


def suggest_optimization(parent_path):
    """Analyze a SOP network and return actionable optimization suggestions."""
    try:
        _require_hou()
        parent = hou.node(parent_path)
        if not parent:
            return _err(f"Parent not found: {parent_path}")
        suggs = []
        for n in parent.allSubChildren():
            if n.type().name().lower() in ("boolean", "polyreduce", "remesh"):
                suggs.append(
                    {
                        "node": n.path(),
                        "issue": f"'{n.type().name()}' is potentially slow.",
                    }
                )
        return _ok({"suggestions": suggs})
    except Exception as e:
        return _err(str(e))


def audit_spatial_layout(parent_path):
    """Returns a 'spatial audit' of all nodes inside parent_path."""
    try:
        _require_hou()
        parent = hou.node(parent_path)
        if not parent:
            return _err(f"Parent not found: {parent_path}")

        def _vec3(value):
            try:
                return [float(value[i]) for i in range(3)]
            except Exception:
                return None

        audit = []
        for child in parent.children():
            pos = child.position()
            tx, ty, tz = 0, 0, 0
            has_geo = False
            bbox_data = None
            try:
                geo = child.geometry()
                if geo and geo.points():
                    bb = geo.boundingBox()
                    center = bb.center()
                    tx, ty, tz = center[0], center[1], center[2]
                    has_geo = True
                    minv = _vec3(bb.minvec()) if hasattr(bb, "minvec") else None
                    maxv = _vec3(bb.maxvec()) if hasattr(bb, "maxvec") else None
                    sizev = _vec3(bb.sizevec()) if hasattr(bb, "sizevec") else None
                    centerv = _vec3(center)
                    if not minv and sizev and centerv:
                        minv = [centerv[i] - sizev[i] / 2.0 for i in range(3)]
                    if not maxv and sizev and centerv:
                        maxv = [centerv[i] + sizev[i] / 2.0 for i in range(3)]
                    if minv and maxv:
                        bbox_data = {
                            "min": [round(v, 4) for v in minv],
                            "max": [round(v, 4) for v in maxv],
                            "size": [
                                round((sizev[i] if sizev else maxv[i] - minv[i]), 4)
                                for i in range(3)
                            ],
                        }
            except Exception:
                pass
            if not has_geo:
                tx = child.parm("tx").eval() if child.parm("tx") else 0
                ty = child.parm("ty").eval() if child.parm("ty") else 0
                tz = child.parm("tz").eval() if child.parm("tz") else 0
            audit.append(
                {
                    "name": child.name(),
                    "type": child.type().name(),
                    "at_origin": (
                        abs(tx) < 0.001 and abs(ty) < 0.001 and abs(tz) < 0.001
                    ),
                    "actual_center": [round(tx, 3), round(ty, 3), round(tz, 3)],
                    "network_pos": [round(pos.x(), 2), round(pos.y(), 2)],
                    "bbox": bbox_data,
                }
            )
        # Structural pass-through types (null, merge, output) legitimately sit at
        # origin — they have no geometry bounding box. Exclude them from origin checks
        # so the LLM doesn't confuse an OUT node being at origin with a misplaced geo.
        _STRUCTURAL_TYPES = {"merge", "null", "output", "switch", "object_merge"}
        non_structural = [
            a for a in audit if a["type"] not in _STRUCTURAL_TYPES
        ]
        origin_nodes = [a for a in non_structural if a["at_origin"]]
        # A single centered generator is often intentional (sphere/box at
        # origin). Flag origin placement only when there are multiple generated
        # parts or mixed centered/off-center parts that suggest a layout error.
        issues = []
        if origin_nodes and len(non_structural) > 1:
            issues = [a["name"] for a in origin_nodes]
        contact_issues = []

        # ── Anti-pattern detection ────────────────────────────────────
        # Detect a flat/origin point source feeding copytopoints.
        anti_patterns = []
        FLAT_SOURCES = {"grid", "line", "circle"}
        for child in parent.children():
            if child.type().name() in FLAT_SOURCES:
                for out_node in child.outputs():
                    if out_node.type().name() == "copytopoints":
                        is_flat = True
                        try:
                            geo = child.geometry()
                            if geo and geo.points():
                                bb = geo.boundingBox()
                                y_size = bb.sizevec()[1]
                                y_center = bb.center()[1]
                                is_flat = (y_size < 0.01 and abs(y_center) < 0.05)
                        except Exception:
                            pass
                        if is_flat:
                            anti_patterns.append({
                                "type": "COPYTOPOINTS_FLAT_SOURCE",
                                "source_node": child.name(),
                                "copytopoints_node": out_node.name(),
                                "fix": (
                                    f"'{child.name()}' ({child.type().name()}) is a flat geometry "
                                    f"at Y≈0, feeding '{out_node.name()}' (copytopoints). "
                                    f"All copies will be placed on the ground plane (Y=0), not at "
                                    f"the intended world positions. "
                                    f"Fix options: (a) Use a point source whose points are already "
                                    f"at the correct world positions (e.g. VEX-generated points, "
                                    f"transformed source), or (b) Replace copytopoints with "
                                    f"individually-placed and transformed nodes merged together."
                                ),
                            })

        # ── Generic contact sanity checks ──────────────────────────────
        # This is intentionally heuristic: it does not certify a layout, but it
        # catches common "support under object but floating" failures using only
        # bounding boxes and generic support-like geometry.
        def _overlap_len(a0, a1, b0, b1):
            return max(0.0, min(a1, b1) - max(a0, b0))

        def _support_like(item):
            name = str(item.get("name", "")).lower()
            bbox = item.get("bbox") or {}
            size = bbox.get("size") or [0, 0, 0]
            sx, sy, sz = [float(v or 0) for v in size[:3]]
            token_match = any(
                tok in name
                for tok in ("leg", "support", "post", "column", "pillar", "stand", "brace")
            )
            slender_vertical = sy > 0 and sy >= max(sx, sz, 1e-6) * 2.0
            return token_match or slender_vertical

        geometry_items = [
            a for a in non_structural if isinstance(a.get("bbox"), dict)
        ]
        for lower in geometry_items:
            if not _support_like(lower):
                continue
            lb = lower["bbox"]
            lmin, lmax = lb["min"], lb["max"]
            nearest = None
            for upper in geometry_items:
                if upper is lower:
                    continue
                ub = upper["bbox"]
                umin, umax = ub["min"], ub["max"]
                gap = float(umin[1]) - float(lmax[1])
                if gap <= 0.005:
                    continue
                ox = _overlap_len(lmin[0], lmax[0], umin[0], umax[0])
                oz = _overlap_len(lmin[2], lmax[2], umin[2], umax[2])
                if ox <= 0 or oz <= 0:
                    continue
                if nearest is None or gap < nearest[0]:
                    nearest = (gap, upper["name"])
            if nearest:
                gap, upper_name = nearest
                contact_issues.append(
                    (
                        f"'{lower['name']}' appears to support '{upper_name}' but has "
                        f"a vertical gap of {gap:.4f} units."
                    )
                )

        if issues:
            node_list = ", ".join(f"'{n}'" for n in issues[:8])
            msg = (
                f"Audit complete. Found {len(issues)} geometry node(s) centred at world origin "
                f"that may need repositioning: {node_list}. "
                f"NOTE: null/merge/output nodes at origin are normal — this flag only applies "
                f"to geometry generators (box, sphere, tube, etc.) that should be offset."
            )
        else:
            msg = (
                "Audit complete. No non-structural geometry nodes are centred at "
                "world origin; contact/stacking is only heuristically checked."
            )
        if anti_patterns:
            msg += f" !! {len(anti_patterns)} COPYTOPOINTS_FLAT_SOURCE issue(s) — copies will land at Y=0. Read anti_patterns for fix."
        if contact_issues:
            msg += f" !! {len(contact_issues)} possible support/contact gap(s). Read contact_issues for details."

        return _ok(
            {
                "nodes": audit,
                "at_origin_issues": issues,
                "anti_patterns": anti_patterns,
                "contact_issues": contact_issues,
            },
            message=msg,
        )
    except Exception as e:
        return _err(str(e))


def remove_flat_copytopoints(parent_path, copytopoints_node_name, source_node_name):
    """
    Remove a flat-source → copytopoints pair from a SOP network.
    Disconnects any wires from the copytopoints node into downstream nodes,
    then destroys both the copytopoints node and its flat source node.
    Returns a list of disconnected downstream node paths so the caller can
    re-wire them manually after building a replacement.
    """
    try:
        _require_hou()
        parent = hou.node(parent_path)
        if not parent:
            return _err(f"Parent not found: {parent_path}")
        ctp = hou.node(f"{parent_path.rstrip('/')}/{copytopoints_node_name}")
        src = hou.node(f"{parent_path.rstrip('/')}/{source_node_name}")
        if not ctp:
            return _err(f"Node not found: {copytopoints_node_name}")

        # Record downstream connections before destroying
        downstream = []
        for out_node in list(ctp.outputs()):
            for port_idx, inp in enumerate(out_node.inputs()):
                if inp == ctp:
                    out_node.setInput(port_idx, None)
                    downstream.append({"node": out_node.path(), "port": port_idx})

        ctp.destroy()
        if src:
            src.destroy()

        return _ok(
            {"removed": [copytopoints_node_name, source_node_name or ""],
             "disconnected_downstream": downstream},
            message=(
                f"Removed '{copytopoints_node_name}' and '{source_node_name}'. "
                f"Disconnected {len(downstream)} downstream wire(s) — re-wire after "
                f"building replacement nodes."
            ),
        )
    except Exception as e:
        return _err(str(e))


def fix_furniture_legs(parent_path, leg_names=None, seat_height=0.45):
    """
    Fix furniture legs that are stuck at the origin (Y=0).
    Moves each leg node so its base sits at Y=0 and its top touches the seat.
    parent_path  — SOP network containing the leg nodes (and optional seat).
    leg_names    — list of node names to treat as legs; if None, auto-detects
                   nodes whose name contains 'leg'.
    seat_height  — target seat height in Houdini world units (default 0.45).
    Returns a summary of the nodes that were repositioned.
    """
    try:
        _require_hou()
        parent = hou.node(parent_path)
        if not parent:
            return _err(f"Parent not found: {parent_path}")

        if leg_names is None:
            leg_names = [c.name() for c in parent.children() if "leg" in c.name().lower()]

        if not leg_names:
            return _ok({"fixed": []}, message="No leg nodes found — nothing to fix.")

        fixed = []
        for name in leg_names:
            node = hou.node(f"{parent_path.rstrip('/')}/{name}")
            if not node:
                continue
            # Determine leg height from geometry bounding box
            try:
                geo = node.geometry()
                if geo and geo.points():
                    bb = geo.boundingBox()
                    leg_h = bb.sizevec()[1]
                else:
                    leg_h = seat_height
            except Exception:
                leg_h = seat_height

            target_ty = seat_height - leg_h / 2.0
            ty_parm = node.parm("ty")
            if ty_parm:
                ty_parm.set(target_ty)
                fixed.append({"node": name, "ty_set": round(target_ty, 4)})

        return _ok(
            {"fixed": fixed},
            message=f"Fixed {len(fixed)} leg node(s) in '{parent_path}'.",
        )
    except Exception as e:
        return _err(str(e))


# ── Export & scene management ─────────────────────────────────────────────────


def export_geometry(node_path, file_path, frame=None):
    """Export SOP geometry to a file (obj, bgeo, bgeo.sc, abc, usd)."""
    try:
        _require_hou()
        node = hou.node(node_path)
        if not node:
            return _err(f"Node not found: {node_path}")
        expanded = hou.expandString(file_path)
        dir_ = _os.path.dirname(expanded)
        if dir_:
            _os.makedirs(dir_, exist_ok=True)
        if frame is not None:
            hou.setFrame(frame)
        geo = node.geometry()
        if not geo:
            return _err("No geometry to export")
        geo.saveToFile(expanded)
        return _ok(
            {
                "exported_to": expanded,
                "point_count": len(geo.points()),
                "prim_count": len(geo.prims()),
            },
            message=f"Exported {node_path} → {expanded}",
        )
    except Exception as e:
        return _err(str(e))


def load_geometry(file_path, parent_path="/obj/geo1"):
    """Load external geometry file into a File SOP."""
    try:
        _require_hou()
        parent = hou.node(parent_path)
        if not parent:
            return _err(f"Parent not found: {parent_path}")
        file_sop = parent.createNode("file", "loaded_geo")
        file_sop.parm("file").set(file_path)
        file_sop.moveToGoodPosition()
        return _ok(
            {"node": file_sop.path(), "file": file_path},
            message=f"UNDO_TRACK: Loaded geometry from {file_path}",
        )
    except Exception as e:
        return _err(str(e))


def find_and_replace_parameter(
    root_path, search_value, replace_value, parm_name_filter=""
):
    """Find-and-replace a string value across all parameters in a network."""
    try:
        _require_hou()
        root = hou.node(root_path)
        if not root:
            return _err(f"Root not found: {root_path}")
        changed = []
        for node in root.recursiveGlob("*"):
            for p in node.parms():
                if parm_name_filter and parm_name_filter not in p.name():
                    continue
                try:
                    val = str(p.rawValue())
                    if search_value in val:
                        new_val = val.replace(search_value, replace_value)
                        p.set(new_val)
                        changed.append(
                            {
                                "node": node.path(),
                                "parm": p.name(),
                                "old": val,
                                "new": new_val,
                            }
                        )
                except Exception:
                    continue
        return _ok(
            {"changed_count": len(changed), "changes": changed[:50]},
            message=f"UNDO_TRACK: Find/replace '{search_value}'→'{replace_value}' in {root_path}: {len(changed)} changes",
        )
    except Exception as e:
        return _err(str(e))


def batch_set_parameters(nodes_and_parms):
    """Bulk parameter set."""
    try:
        _require_hou()
        from . import _node_tools as nt

        results = []
        failed = 0
        for item in nodes_and_parms:
            n = hou.node(item["node_path"])
            if not n:
                failed += 1
                results.append({"node": item["node_path"], "status": "node not found"})
                continue
            res = nt._set_node_parameter(n, item["parm_name"], item.get("value"))
            if res.get("status") == "ok":
                result_entry = {
                    "node": item["node_path"],
                    "parm": item["parm_name"],
                    "status": "ok",
                }
                data = res.get("data") or {}
                if "new" in data:
                    result_entry["value"] = data["new"]
                if "mapped_components" in data:
                    result_entry["mapped_components"] = data["mapped_components"]
                if "readback_warnings" in data:
                    result_entry["readback_warnings"] = data["readback_warnings"]
                msg = res.get("message", "")
                if msg.startswith("WARNING:"):
                    result_entry["warning"] = msg
                results.append(result_entry)
            else:
                failed += 1
                results.append(
                    {
                        "node": item["node_path"],
                        "parm": item.get("parm_name"),
                        "status": "error",
                        "message": res.get("message"),
                    }
                )
        summary = {"count": len(results), "failed": failed, "results": results}
        if failed:
            return {
                "status": "error",
                "message": f"Batch set incomplete: {failed} of {len(results)} parameter writes failed",
                "data": summary,
            }
        warnings = [r["warning"] for r in results if "warning" in r]
        for r in results:
            if "readback_warnings" in r:
                warnings.extend(r["readback_warnings"])
        if warnings:
            unique_warnings = list(dict.fromkeys(warnings))
            return _ok(
                summary,
                message=f"WARNING: Batch set {len(results)} parameters, but with {len(unique_warnings)} mismatches",
            )
        return _ok(summary, message=f"UNDO_TRACK: Batch set {len(results)} parameters")
    except Exception as e:
        return _err(str(e))


def compare_nodes(node_path_a, node_path_b):
    """Compare parameter values between two nodes."""
    try:
        _require_hou()
        a = hou.node(node_path_a)
        b = hou.node(node_path_b)
        if not a:
            return _err(f"Node A not found: {node_path_a}")
        if not b:
            return _err(f"Node B not found: {node_path_b}")
        diffs = []
        a_parms = {p.name(): p.eval() for p in a.parms()}
        b_parms = {p.name(): p.eval() for p in b.parms()}
        all_keys = set(list(a_parms.keys()) + list(b_parms.keys()))
        for k in sorted(all_keys):
            va = a_parms.get(k, "<missing>")
            vb = b_parms.get(k, "<missing>")
            if va != vb:
                diffs.append({"parm": k, "a": va, "b": vb})
        return _ok(
            {
                "node_a": node_path_a,
                "node_b": node_path_b,
                "same_type": a.type().name() == b.type().name(),
                "diff_count": len(diffs),
                "diffs": diffs[:50],
            }
        )
    except Exception as e:
        return _err(str(e))


def duplicate_node(node_path, new_name=None):
    """Duplicate a node in the same network."""
    try:
        _require_hou()
        node = hou.node(node_path)
        if not node:
            return _err(f"Node not found: {node_path}")
        parent = node.parent()
        copied = hou.copyNodesTo([node], parent)[0]
        if new_name:
            copied.setName(new_name, unique_name=True)
        copied.moveToGoodPosition()
        return _ok(
            {"original": node_path, "duplicate": copied.path()},
            message=f"UNDO_TRACK: Duplicated {node_path} → {copied.path()}",
        )
    except Exception as e:
        return _err(str(e))


def rename_node(node_path, new_name):
    """Rename a node."""
    try:
        _require_hou()
        node = hou.node(node_path)
        if not node:
            return _err(f"Node not found: {node_path}")
        old_name = node.name()
        node.setName(new_name, unique_name=True)
        return _ok(
            {"old_name": old_name, "new_name": node.name(), "path": node.path()},
            message=f"UNDO_TRACK: Renamed {old_name} → {node.name()}",
        )
    except Exception as e:
        return _err(str(e))


def create_camera(parent_path="/obj", name="agent_cam", position=None, look_at=None):
    """Create a camera with optional position and look-at target."""
    if position is None:
        position = [5, 3, 5]
    try:
        _require_hou()
        parent = hou.node(parent_path)
        if not parent:
            return _err(f"Parent not found: {parent_path}")
        cam = parent.createNode("cam", name)
        cam.parmTuple("t").set(position)
        if look_at:
            target = hou.node(look_at)
            if target:
                cam.parm("lookatpath").set(look_at)
        cam.moveToGoodPosition()
        return _ok(
            {"path": cam.path(), "position": position, "look_at": look_at},
            message=f"UNDO_TRACK: Created camera {cam.path()}",
        )
    except Exception as e:
        return _err(str(e))


def take_node_snapshot(node_path):
    """Save all parameter values for a node."""
    try:
        _require_hou()
        node = hou.node(node_path)
        if not node:
            return _err(f"Node not found: {node_path}")
        snapshot = {}
        for p in node.parms():
            try:
                snapshot[p.name()] = p.eval()
            except Exception:
                continue
        return _ok(
            {
                "path": node_path,
                "type": node.type().name(),
                "parm_count": len(snapshot),
                "snapshot": snapshot,
            }
        )
    except Exception as e:
        return _err(str(e))


def set_keyframe(node_path, parm_name, frame, value):
    """Set a keyframe on a parameter at a specific frame."""
    try:
        _require_hou()
        node = hou.node(node_path)
        if not node:
            return _err(f"Node not found: {node_path}")
        parm = node.parm(parm_name)
        if not parm:
            return _err(f"Parameter '{parm_name}' not found on {node_path}")

        key = hou.Keyframe()
        key.setFrame(frame)
        key.setValue(value)
        parm.setKeyframe(key)
        return _ok({
            "message": f"Keyframe set on {node_path}/{parm_name} at frame {frame} with value {value}",
            "undo_track": f"Set keyframe {node_path}/{parm_name} = {value} at frame {frame}"
        })
    except Exception as e:
        return _err(str(e))

def set_frame_range(start_frame, end_frame):
    """Set the global animation frame range."""
    try:
        _require_hou()
        hou.playbar.setFrameRange(start_frame, end_frame)
        hou.playbar.setPlaybackRange(start_frame, end_frame)
        return _ok({
            "message": f"Global frame range set to {start_frame}-{end_frame}",
            "undo_track": f"Set frame range {start_frame}-{end_frame}"
        })
    except Exception as e:
        return _err(str(e))

def go_to_frame(frame):
    """Set the current playback frame."""
    try:
        _require_hou()
        hou.setFrame(frame)
        return _ok({
            "message": f"Current frame set to {frame}",
            "undo_track": f"Go to frame {frame}"
        })
    except Exception as e:
        return _err(str(e))


# ── Animation ─────────────────────────────────────────────────────────────────


def set_keyframe(
    node_path, parm_name, value, frame=None, slope_in=None, slope_out=None
):
    """Set a keyframe on a parameter."""
    try:
        _require_hou()
        node = hou.node(node_path)
        if not node:
            return _err(f"Node not found: {node_path}")
        parm = node.parm(parm_name)
        if not parm:
            return _err(f"Parm not found: {parm_name}")
        kf = hou.Keyframe()
        kf.setFrame(frame if frame is not None else hou.frame())
        kf.setValue(value)
        if slope_in is not None:
            kf.setSlopeAuto(False)
            kf.setInSlope(slope_in)
        if slope_out is not None:
            kf.setSlopeAuto(False)
            kf.setSlope(slope_out)
        parm.setKeyframe(kf)
        return _ok(
            {"frame": kf.frame(), "value": value},
            message=f"UNDO_TRACK: Keyframe set on {node_path}/{parm_name} @ frame {kf.frame()}",
        )
    except Exception as e:
        return _err(str(e))


def delete_keyframe(node_path, parm_name, frame=None):
    """Delete a keyframe at a specific frame, or all keyframes."""
    try:
        _require_hou()
        node = hou.node(node_path)
        if not node:
            return _err(f"Node not found: {node_path}")
        p = node.parm(parm_name)
        if not p:
            return _err(f"Parm not found: {parm_name}")
        if frame is not None:
            kfs = [k for k in p.keyframes() if int(k.frame()) == frame]
            for k in kfs:
                p.deleteKeyframe(k)
            return _ok({"deleted": len(kfs), "frame": frame})
        else:
            p.deleteAllKeyframes()
            return _ok({"deleted": "all"})
    except Exception as e:
        return _err(str(e))


def get_timeline_keyframes(node_path, parm_name):
    """List all keyframes on a parameter."""
    try:
        _require_hou()
        node = hou.node(node_path)
        if not node:
            return _err(f"Node not found: {node_path}")
        p = node.parm(parm_name)
        if not p:
            return _err(f"Parm not found: {parm_name}")
        kfs = []
        for k in p.keyframes():
            kfs.append(
                {
                    "frame": k.frame(),
                    "value": k.value(),
                    "slope_in": k.inSlope() if hasattr(k, "inSlope") else None,
                    "slope_out": k.slope() if hasattr(k, "slope") else None,
                }
            )
        return _ok(
            {
                "path": node_path,
                "parm": parm_name,
                "keyframe_count": len(kfs),
                "keyframes": kfs,
            }
        )
    except Exception as e:
        return _err(str(e))


def set_frame_range(start, end, fps=None):
    """Set the global frame range and optionally FPS."""
    try:
        _require_hou()
        hou.playbar.setFrameRange(start, end)
        hou.playbar.setPlaybackRange(start, end)
        if fps is not None:
            hou.setFps(fps)
        return _ok(
            {"start": start, "end": end, "fps": hou.fps() if fps is None else fps},
            message=f"Frame range set: {start}–{end}",
        )
    except Exception as e:
        return _err(str(e))


def go_to_frame(frame):
    """Jump to a specific frame."""
    try:
        _require_hou()
        hou.setFrame(frame)
        return _ok({"frame": frame})
    except Exception as e:
        return _err(str(e))
