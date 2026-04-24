# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
"""
HoudiniMind — Advanced Tools
Scene intel, node management, VDB/packed geo, USD/Solaris, HDA, rendering, organization, simulation setups.
"""

import re
import os
import time
import subprocess
import tempfile
import threading
import json

from . import _core as core


def watch_node_events(port: int = 9877, stop: bool = False) -> dict:
    """Start (or stop) a Server-Sent Events broadcaster on the given port."""
    core._require_hou()
    from http.server import BaseHTTPRequestHandler, HTTPServer

    try:
        from houdinimind.bridge.event_hooks import EventHooks
    except ImportError:
        return core._err("EventHooks bridge not found.")
    _STATE = getattr(watch_node_events, "_state", {"server": None, "hooks": None})
    watch_node_events._state = _STATE
    if stop:
        if _STATE["server"]:
            _STATE["server"].shutdown()
            _STATE["server"] = None
        if _STATE["hooks"]:
            _STATE["hooks"].unregister()
            _STATE["hooks"] = None
        return core._ok(message="Event broadcaster stopped.")
    if _STATE["server"]:
        return core._ok(
            message=f"Broadcaster already running on port {_STATE['server'].server_address[1]}."
        )
    _clients: list = []
    _clients_lock = threading.Lock()

    def broadcast(cat: str, data: dict):
        payload = "data: " + json.dumps({**data, "_category": cat}) + "\n\n"
        encoded = payload.encode("utf-8")
        with _clients_lock:
            dead = []
            for wfile in _clients:
                try:
                    wfile.write(encoded)
                    wfile.flush()
                except Exception:
                    dead.append(wfile)
            for d in dead:
                _clients.remove(d)

    class SSEHandler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path != "/events":
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            with _clients_lock:
                _clients.append(self.wfile)
            try:
                while True:
                    time.sleep(15)
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
            except Exception:
                with _clients_lock:
                    if self.wfile in _clients:
                        _clients.remove(self.wfile)

    try:
        server = HTTPServer(("127.0.0.1", port), SSEHandler)
    except OSError as e:
        return core._err(f"Could not bind to port {port}: {e}")
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    hooks = EventHooks(on_event=broadcast, track_parm_changes=True)
    hooks.register()
    _STATE["server"] = server
    _STATE["hooks"] = hooks
    return core._ok(
        {"url": f"http://127.0.0.1:{port}/events"},
        message=f"Event broadcaster running.",
    )


def get_parm_expression_audit(root: str = "/", language: str = "both") -> dict:
    """Walk every node under root and return all parameters that carry an expression."""
    core._require_hou()
    results = []

    def scan(node):
        for parm in node.parms():
            try:
                lang = parm.expressionLanguage()
            except Exception:
                continue
            if lang is None:
                continue
            lang_name = str(lang).split(".")[-1].lower()
            if language != "both" and lang_name != language:
                continue
            try:
                expr = parm.expression()
            except Exception:
                expr = "<unreadable>"
            results.append(
                {
                    "node": node.path(),
                    "parm": parm.name(),
                    "language": lang_name,
                    "expression": expr,
                }
            )
        for child in node.children():
            scan(child)

    root_node = core._hou.node(root)
    if not root_node:
        return core._err(f"Node not found: {root}")
    scan(root_node)
    return core._ok({"count": len(results), "expressions": results})


def list_all_file_references(root: str = "/") -> dict:
    """Collect every string parameter that looks like a file path across the scene."""
    core._require_hou()
    FILE_PARM_HINTS = (
        "file",
        "path",
        "tex",
        "map",
        "cache",
        "geo",
        "bgeo",
        "abc",
        "usd",
        "hip",
        "hda",
        "otl",
        "img",
        "pic",
        "rat",
        "seq",
        "src",
        "dst",
        "dir",
        "out",
        "in",
    )
    PATH_RE = re.compile(r"[/\\]|^\$", re.IGNORECASE)
    results = []

    def scan(node):
        for parm in node.parms():
            try:
                val = (
                    parm.unexpandedString()
                    if hasattr(parm, "unexpandedString")
                    else str(parm.eval())
                )
            except Exception:
                continue
            if (
                isinstance(val, str)
                and val.strip()
                and (
                    any(h in parm.name().lower() for h in FILE_PARM_HINTS)
                    or PATH_RE.search(val)
                )
            ):
                try:
                    expanded = core._hou.expandString(val)
                except Exception:
                    expanded = val
                results.append(
                    {
                        "node": node.path(),
                        "parm": parm.name(),
                        "raw": val,
                        "expanded": expanded,
                    }
                )
        for child in node.children():
            scan(child)

    root_node = core._hou.node(root)
    if not root_node:
        return core._err(f"Node not found: {root}")
    scan(root_node)
    return core._ok({"count": len(results), "references": results})


def scan_missing_files(root: str = "/") -> dict:
    """Check disk existence of all file references found under root."""
    core._require_hou()
    ref_result = list_all_file_references(root)
    if ref_result["status"] != "ok":
        return ref_result
    missing, found, sequence = [], [], []
    SEQUENCE_RE = re.compile(r"\$F\d*|#+|\%0\d+d", re.IGNORECASE)
    for ref in ref_result["data"]["references"]:
        exp = ref["expanded"]
        if not exp or exp.startswith("<"):
            continue
        if SEQUENCE_RE.search(ref["raw"]):
            sequence.append(ref)
            continue
        if os.path.exists(exp):
            found.append(ref)
        else:
            missing.append(ref)
    return core._ok(
        {
            "missing_count": len(missing),
            "found_count": len(found),
            "sequence_count": len(sequence),
            "missing": missing,
            "sequences": sequence,
        }
    )


def get_cook_dependency_order(node_path: str) -> dict:
    """Walk upstream from a node and return ancestor nodes in cook order."""
    core._require_hou()
    node = core._hou.node(node_path)
    if not node:
        return core._err(f"Node not found: {node_path}")
    visited, seen = [], set()

    def walk(n):
        if n.path() in seen:
            return
        seen.add(n.path())
        for inp in n.inputs():
            if inp:
                walk(inp)
        visited.append(
            {
                "path": n.path(),
                "type": n.type().name(),
                "dirty": not n.isTimeDependent() and bool(n.errors()),
            }
        )

    walk(node)
    return core._ok({"depth": len(visited), "chain": visited})


def copy_paste_nodes(node_paths: list, dest_parent_path: str) -> dict:
    """Copy a list of nodes into a different parent network."""
    core._require_hou()
    nodes = [core._hou.node(p) for p in node_paths if core._hou.node(p)]
    if len(nodes) != len(node_paths):
        return core._err("One or more source nodes not found.")
    dest = core._hou.node(dest_parent_path)
    if not dest:
        return core._err(f"Destination not found: {dest_parent_path}")
    try:
        copies = core._hou.copyNodesTo(nodes, dest)
        return core._ok({"copied": [c.path() for c in copies], "count": len(copies)})
    except Exception:
        return core._err(core._traceback.format_exc())


def lock_node(node_path: str, lock: bool = True) -> dict:
    """Lock or unlock a node's cached geometry."""
    core._require_hou()
    node = core._hou.node(node_path)
    if not node:
        return core._err(f"Node not found: {node_path}")
    try:
        if hasattr(node, "setLocked"):
            node.setLocked(lock)
        else:
            flag = getattr(core._hou.nodeFlag, "Lock", None)
            if flag:
                node.setGenericFlag(flag, lock)
        return core._ok({"path": node_path, "locked": lock})
    except Exception:
        return core._err(core._traceback.format_exc())


def set_object_visibility(node_path: str, visible: bool = True) -> dict:
    """Show or hide an object-level node in the viewport."""
    core._require_hou()
    node = core._hou.node(node_path)
    if not node:
        return core._err(f"Node not found: {node_path}")
    try:
        if hasattr(node, "setDisplayFlag"):
            node.setDisplayFlag(visible)
        parm = node.parm("display")
        if parm:
            parm.set(1 if visible else 0)
        return core._ok({"path": node_path, "visible": visible})
    except Exception:
        return core._err(core._traceback.format_exc())


def cook_network_range(
    parent_path: str, start_frame: int, end_frame: int, node_path: str = None
) -> dict:
    """Force-cook a node or network across a frame range."""
    core._require_hou()
    parent = core._hou.node(parent_path)
    if not parent:
        return core._err(f"Parent not found: {parent_path}")
    target = core._hou.node(node_path) if node_path else None
    if not target:
        for child in parent.children():
            if hasattr(child, "isDisplayFlagSet") and child.isDisplayFlagSet():
                target = child
                break
    if not target:
        return core._err("Target node not found.")
    errors_by_frame, cook_times = {}, []
    for f in range(start_frame, end_frame + 1):
        core._hou.setFrame(f)
        t0 = time.time()
        try:
            target.cook(force=True)
        except Exception as e:
            errors_by_frame[f] = str(e)
        errs = list(target.errors())
        if errs:
            errors_by_frame[f] = errs
        cook_times.append(round((time.time() - t0) * 1000, 1))
    return core._ok(
        {
            "node": target.path(),
            "frames_cooked": end_frame - start_frame + 1,
            "error_frames": list(errors_by_frame.keys()),
            "avg_cook_ms": round(sum(cook_times) / len(cook_times), 1)
            if cook_times
            else 0,
        }
    )


def edit_animation_curve(
    node_path: str,
    parm_name: str,
    interpolation: str = "bezier",
    slope_auto: bool = True,
    in_slope: float = None,
    out_slope: float = None,
) -> dict:
    """Edit interpolation type and slopes of all keyframes on a parameter."""
    core._require_hou()
    node = core._hou.node(node_path)
    if not node:
        return core._err(f"Node not found: {node_path}")
    parm = node.parm(parm_name)
    if not parm:
        return core._err(f"Parameter '{parm_name}' not found.")
    interp_map = {
        "constant": core._hou.keyframeInterpolation.Constant,
        "linear": core._hou.keyframeInterpolation.Linear,
        "bezier": core._hou.keyframeInterpolation.Bezier,
        "ease": core._hou.keyframeInterpolation.EaseInEaseOut,
        "easein": core._hou.keyframeInterpolation.EaseIn,
        "easeout": core._hou.keyframeInterpolation.EaseOut,
    }
    interp = interp_map.get(interpolation.lower())
    if interp is None:
        return core._err(f"Unknown interpolation '{interpolation}'.")
    try:
        keys = list(parm.keyframes())
        if not keys:
            return core._err(f"No keyframes found on {parm_name}.")
        for k in keys:
            k.setInterpolation(interp)
            if slope_auto:
                k.setSlopeAuto(True)
            else:
                if in_slope is not None:
                    k.setInSlope(in_slope)
                if out_slope is not None:
                    k.setOutSlope(out_slope)
        parm.setKeyframes(keys)
        return core._ok(
            {
                "parm": parm_name,
                "keyframe_count": len(keys),
                "interpolation": interpolation,
            }
        )
    except Exception:
        return core._err(core._traceback.format_exc())


def bake_expressions_to_keys(
    node_path: str, start_frame: int, end_frame: int, parm_filter: str = None
) -> dict:
    """Evaluate expressions and replace them with explicit keyframes."""
    core._require_hou()
    node = core._hou.node(node_path)
    if not node:
        return core._err(f"Node not found: {node_path}")
    baked, skipped = [], []
    for parm in node.parms():
        if parm_filter and parm_filter not in parm.name():
            continue
        try:
            parm.expression()
            has_expr = True
        except Exception:
            has_expr = False
        if not has_expr:
            continue
        try:
            keys = []
            for f in range(start_frame, end_frame + 1):
                val = parm.evalAtFrame(f)
                if isinstance(val, (int, float)):
                    k = core._hou.Keyframe()
                    k.setFrame(f)
                    k.setValue(val)
                    keys.append(k)
            if keys:
                parm.deleteAllKeyframes()
                parm.setKeyframes(keys)
                baked.append(parm.name())
            else:
                skipped.append(parm.name())
        except Exception as e:
            skipped.append(f"{parm.name()} ({e})")
    return core._ok(
        {"baked": baked, "skipped": skipped, "frames": end_frame - start_frame + 1}
    )


def create_take(name: str, make_active: bool = True, parent_take: str = None) -> dict:
    """Create a new scene take."""
    core._require_hou()
    try:
        if parent_take:
            parent = core._hou.takes.findTake(parent_take)
            if not parent:
                return core._err(f"Parent take '{parent_take}' not found.")
            take = parent.addChildTake(name)
        else:
            take = core._hou.takes.rootTake().addChildTake(name)
        if make_active:
            core._hou.takes.setCurrentTake(take)
        return core._ok({"name": take.name(), "active": make_active})
    except Exception:
        return core._err(core._traceback.format_exc())


def list_takes() -> dict:
    """Return the full take hierarchy."""
    core._require_hou()
    try:
        current = core._hou.takes.currentTake()

        def serialise(take):
            parms = []
            for pt in take.parmTuples():
                try:
                    parms.append({"node": pt.node().path(), "parm": pt.name()})
                except Exception:
                    pass
            return {
                "name": take.name(),
                "active": take.name() == current.name(),
                "overrides": parms,
                "children": [serialise(c) for c in take.children()],
            }

        return core._ok(
            {"current": current.name(), "takes": serialise(core._hou.takes.rootTake())}
        )
    except Exception:
        return core._err(core._traceback.format_exc())


def switch_take(name: str) -> dict:
    """Make a named take the active take."""
    core._require_hou()
    try:
        take = core._hou.takes.findTake(name)
        if not take:
            return core._err(f"Take '{name}' not found.")
        core._hou.takes.setCurrentTake(take)
        return core._ok({"active_take": name})
    except Exception:
        return core._err(core._traceback.format_exc())


def analyze_vdb(node_path: str) -> dict:
    """Inspect all VDB grids on a SOP node."""
    core._require_hou()
    node = core._hou.node(node_path)
    if not node:
        return core._err(f"Node not found: {node_path}")
    try:
        geo = node.geometry()
        if not geo:
            return core._err("No geometry on this node.")
        VDB_TYPE = getattr(core._hou.primType, "VDB", None)
        grids = []
        for prim in geo.prims():
            if VDB_TYPE is not None and prim.type() != VDB_TYPE:
                continue
            intr = {}
            for key in (
                "activevoxelcount",
                "voxelsize",
                "indexbbox",
                "background",
                "gridtype",
                "name",
            ):
                try:
                    intr[key] = prim.intrinsicValue(key)
                except Exception:
                    intr[key] = None
            if intr["gridtype"] is None and intr["name"] is None:
                continue
            grids.append(
                {
                    "name": intr["name"] or f"prim_{prim.number()}",
                    "grid_type": intr["gridtype"],
                    "voxel_size": intr["voxelsize"],
                    "active_voxels": intr["activevoxelcount"],
                }
            )
        if not grids:
            return core._err("No VDB primitives found.")
        return core._ok({"grid_count": len(grids), "grids": grids})
    except Exception:
        return core._err(core._traceback.format_exc())


def list_vdb_grids(node_path: str) -> dict:
    """Fast summary of all VDB grids on a SOP node."""
    core._require_hou()
    result = analyze_vdb(node_path)
    if result["status"] != "ok":
        return result
    summary = [
        {"name": g["name"], "type": g["grid_type"]} for g in result["data"]["grids"]
    ]
    return core._ok({"grids": summary, "count": len(summary)})


def get_packed_geo_info(node_path: str, max_pieces: int = 50) -> dict:
    """Inspect packed primitives on a SOP node."""
    core._require_hou()
    node = core._hou.node(node_path)
    if not node:
        return core._err(f"Node not found: {node_path}")
    try:
        geo = node.geometry()
        if not geo:
            return core._err("No geometry.")
        PACKED_TYPE = getattr(
            core._hou.primType,
            "PackedGeometry",
            getattr(core._hou.primType, "Packed", None),
        )
        pieces = []
        for prim in geo.prims()[:max_pieces]:
            if PACKED_TYPE is not None and prim.type() != PACKED_TYPE:
                continue
            info = {"prim_num": prim.number()}
            for key in ("name", "unexpandedfilename", "pointcount", "primcount"):
                try:
                    info[key] = prim.intrinsicValue(key)
                except Exception:
                    pass
            pieces.append(info)
        return core._ok(
            {
                "total_packed_prims": len(geo.prims()),
                "shown": len(pieces),
                "pieces": pieces,
            }
        )
    except Exception:
        return core._err(core._traceback.format_exc())


def remap_file_paths(
    root: str, old_prefix: str, new_prefix: str, dry_run: bool = True
) -> dict:
    """Bulk-remap file paths across a network."""
    core._require_hou()
    ref_result = list_all_file_references(root)
    if ref_result["status"] != "ok":
        return ref_result
    changes = []
    for ref in ref_result["data"]["references"]:
        raw = ref["raw"]
        if old_prefix not in raw:
            continue
        new_val = raw.replace(old_prefix, new_prefix, 1)
        changes.append(
            {"node": ref["node"], "parm": ref["parm"], "old": raw, "new": new_val}
        )
        if not dry_run:
            node = core._hou.node(ref["node"])
            if node:
                parm = node.parm(ref["parm"])
                if parm:
                    parm.set(new_val)
    return core._ok(
        {"dry_run": dry_run, "changes": changes, "change_count": len(changes)}
    )


def write_vop_network(parent_path: str, chain: list) -> dict:
    """Build a VOP network by creating and wiring VOP nodes programmatically."""
    core._require_hou()
    parent = core._hou.node(parent_path)
    if not parent:
        return core._err(f"Parent not found: {parent_path}")
    created, errors = {}, []
    for step in chain:
        vop_type = step.get("type")
        if not vop_type:
            errors.append("Step missing 'type'")
            continue
        try:
            node = parent.createNode(vop_type, step.get("name") or vop_type)
        except Exception as e:
            errors.append(f"Could not create VOP '{vop_type}': {e}")
            continue
        for pname, pval in (step.get("parms") or {}).items():
            parm = node.parm(pname)
            if parm:
                try:
                    parm.set(pval)
                except Exception:
                    pass
        created[node.name()] = node
        for inp_spec in step.get("inputs") or []:
            try:
                src_name, out_name = inp_spec.split(".", 1)
                src_node = created.get(src_name) or parent.node(src_name)
                if not src_node:
                    errors.append(f"Input source node '{src_name}' not found.")
                    continue
                out_idx = 0
                for i, conn in enumerate(src_node.outputConnectors()):
                    if conn.name() == out_name:
                        out_idx = i
                        break
                node.setInput(len(node.inputs()), src_node, out_idx)
            except Exception as e:
                errors.append(f"Wire error ({inp_spec}): {e}")
    return core._ok(
        {
            "created": [n.path() for n in created.values()],
            "count": len(created),
            "errors": errors,
        }
    )


def eval_hscript(expression: str) -> dict:
    """Evaluate an hscript expression or command."""
    core._require_hou()
    expr = expression.strip()
    if expr.startswith("$") or any(f in expr for f in ("ch(", "chs(", "chf(", "`")):
        try:
            result = core._hou.expandString(expr if "`" in expr else f"`{expr}`")
            return core._ok({"mode": "expand", "result": result})
        except Exception:
            pass
    try:
        stdout, stderr = core._hou.hscript(expr)
        return core._ok(
            {
                "mode": "hscript",
                "stdout": stdout.strip(),
                "stderr": stderr.strip() or None,
            }
        )
    except Exception:
        return core._err(core._traceback.format_exc())


def setup_wire_solver(
    parent_path: str,
    geo_node_path: str,
    stiffness: float = 100.0,
    damping: float = 5.0,
    gravity: float = -9.81,
) -> dict:
    """Create a Wire solver simulation."""
    core._require_hou()
    parent = core._hou.node(parent_path)
    if not parent:
        return core._err(f"Parent not found: {parent_path}")
    try:
        wire_obj = parent.createNode("wireobject", "wire_object")
        sop_net = wire_obj.node("wirenet") or wire_obj.createNode("wirenet")
        om = sop_net.createNode("object_merge", "source_curves")
        om.parm("objpath1").set(geo_node_path)
        om.parm("xformtype").set(1)
        dopnet = parent.createNode("dopnet", "wire_sim")
        dopnet.parm("gravity").set(gravity)
        wire_dop = dopnet.createNode("wireobject", "wire_dop")
        wire_dop.parm("soppath").set(wire_obj.path())
        solver = dopnet.createNode("wiresolver", "wire_solver")
        solver.parm("stiffness").set(stiffness)
        solver.parm("dampingratio").set(damping)
        merge = dopnet.createNode("merge", "merge")
        out = dopnet.createNode("output", "out")
        solver.setInput(0, wire_dop)
        merge.setInput(0, solver)
        out.setInput(0, merge)
        return core._ok(
            {
                "wire_object": wire_obj.path(),
                "dopnet": dopnet.path(),
                "solver": solver.path(),
            }
        )
    except Exception:
        return core._err(core._traceback.format_exc())


def setup_crowd_sim(
    parent_path: str,
    agent_geo_path: str,
    num_agents: int = 100,
    terrain_path: str = None,
) -> dict:
    """Create a Houdini crowd simulation network."""
    core._require_hou()
    parent = core._hou.node(parent_path)
    if not parent:
        return core._err(f"Parent not found: {parent_path}")
    try:
        crowd_obj = parent.createNode("geo", "crowd_setup")
        sop = crowd_obj.createNode("crowdsource", "crowd_source")
        sop.parm("agentdefinitionpath").set(agent_geo_path)
        sop.parm("count").set(num_agents)
        dopnet = parent.createNode("dopnet", "crowd_sim")
        dopnet.parm("gravity").set(-9.81)
        crowd_dop = dopnet.createNode("crowdobject", "crowd_object")
        crowd_dop.parm("soppath").set(crowd_obj.path())
        solver = dopnet.createNode("crowdsolver", "crowd_solver")
        solver.setInput(0, crowd_dop)
        if terrain_path:
            terrain_dop = dopnet.createNode("staticobject", "terrain")
            terrain_dop.parm("soppath").set(terrain_path)
            solver.setInput(1, terrain_dop)
        out = dopnet.createNode("output", "out")
        out.setInput(0, solver)
        return core._ok({"crowd_object": crowd_obj.path(), "dopnet": dopnet.path()})
    except Exception:
        return core._err(core._traceback.format_exc())


def setup_grain_sim(
    parent_path: str,
    source_node_path: str,
    particle_separation: float = 0.05,
    friction: float = 0.5,
    clumping: float = 0.1,
) -> dict:
    """Create a POP Grains simulation."""
    core._require_hou()
    parent = core._hou.node(parent_path)
    if not parent:
        return core._err(f"Parent not found: {parent_path}")
    try:
        geo_obj = parent.createNode("geo", "grain_setup")
        om = geo_obj.createNode("object_merge", "source_geo")
        om.parm("objpath1").set(source_node_path)
        om.parm("xformtype").set(1)
        scatter = geo_obj.createNode("scatter", "scatter_grains")
        scatter.parm("npts").set(5000)
        scatter.setInput(0, om)
        add_attrib = geo_obj.createNode("attribwrangle", "init_grains")
        add_attrib.parm("snippet").set(
            f"f@pscale = {particle_separation};\ni@group_grains = 1;\n"
        )
        add_attrib.setInput(0, scatter)
        dopnet = parent.createNode("dopnet", "grain_sim")
        pop_grains = dopnet.createNode("popgrains", "pop_grains")
        pop_grains.parm("friction").set(friction)
        pop_grains.parm("clumping").set(clumping)
        pop_source = dopnet.createNode("popsource", "grain_source")
        pop_source.parm("soppath").set(add_attrib.path())
        solver = dopnet.createNode("popsolver", "pop_solver")
        solver.setInput(0, pop_source)
        solver.setInput(2, pop_grains)
        out = dopnet.createNode("output", "out")
        out.setInput(0, solver)
        return core._ok({"geo_setup": geo_obj.path(), "dopnet": dopnet.path()})
    except Exception:
        return core._err(core._traceback.format_exc())


def setup_feather_sim(
    parent_path: str,
    quill_geo_path: str,
    barb_count: int = 20,
    wind_strength: float = 0.5,
) -> dict:
    """Create a Houdini Feather grooming and simulation network."""
    core._require_hou()
    parent = core._hou.node(parent_path)
    if not parent:
        return core._err(f"Parent not found: {parent_path}")
    try:
        geo_obj = parent.createNode("geo", "feather_setup")
        om = geo_obj.createNode("object_merge", "quills_in")
        om.parm("objpath1").set(quill_geo_path)
        om.parm("xformtype").set(1)
        try:
            feather_gen = geo_obj.createNode("feathergenerate", "feather_gen")
            feather_gen.parm("barbcount").set(barb_count)
            feather_gen.setInput(0, om)
            last_sop = feather_gen
        except Exception:
            resample = geo_obj.createNode("resample", "resample_quills")
            resample.parm("length").set(0.02)
            resample.setInput(0, om)
            last_sop = resample
        dopnet = parent.createNode("dopnet", "feather_sim")
        dopnet.parm("gravity").set(-9.81)
        v_source = dopnet.createNode("vellumsource", "feather_source")
        v_source.parm("soppath").set(last_sop.path())
        v_solver = dopnet.createNode("vellumsolver", "vellum_solver")
        wind = dopnet.createNode("popwind", "wind_force")
        wind.parm("airresist").set(wind_strength)
        v_solver.setInput(0, v_source)
        v_solver.setInput(2, wind)
        out = dopnet.createNode("output", "out")
        out.setInput(0, v_solver)
        return core._ok({"feather_geo": geo_obj.path(), "dopnet": dopnet.path()})
    except Exception:
        return core._err(core._traceback.format_exc())


def setup_karma_material(
    mat_name: str,
    base_color: list = None,
    roughness: float = 0.5,
    metallic: float = 0.0,
    emission_color: list = None,
    texture_path: str = None,
) -> dict:
    """Create a Karma-native MaterialX (mtlx) material."""
    core._require_hou()
    try:
        mat_network = core._hou.node("/mat") or core._hou.node("/").createNode(
            "matnet", "mat"
        )
        subnet = mat_network.createNode("subnet", mat_name)
        std_surf = subnet.createNode("mtlxstandard_surface", "standard_surface")
        if base_color and len(base_color) >= 3:
            std_surf.parmTuple("base_color").set(base_color[:3])
        if texture_path:
            tex_node = subnet.createNode("mtlximage", "base_tex")
            tex_node.parm("file").set(texture_path)
            std_surf.setNamedInput("base_color", tex_node, "out")
        std_surf.parm("specular_roughness").set(roughness)
        std_surf.parm("metalness").set(metallic)
        if emission_color and len(emission_color) >= 3:
            std_surf.parmTuple("emission_color").set(emission_color[:3])
            std_surf.parm("emission").set(1.0)
        surf_out = subnet.createNode("mtlxsurface", "surface_out")
        surf_out.setInput(0, std_surf)
        return core._ok({"material_path": subnet.path()})
    except Exception:
        return core._err(core._traceback.format_exc())


def setup_aov_passes(rop_path: str, passes: list = None) -> dict:
    """Add render AOV passes to a Mantra or Karma ROP."""
    core._require_hou()
    rop = core._hou.node(rop_path)
    if not rop:
        return core._err(f"ROP not found: {rop_path}")
    if passes is None:
        passes = [
            "diffuse_direct",
            "specular_direct",
            "emission",
            "shadow_matte",
            "depth",
            "crypto_object",
        ]
    rop_type, added = rop.type().name().lower(), []
    try:
        if "karma" in rop_type:
            existing = rop.parm("aov_count")
            if not existing:
                return core._err("No aov_count parm.")
            base_idx = int(existing.eval())
            for i, p in enumerate(passes):
                idx = base_idx + i + 1
                existing.set(idx)
                rop.parm(f"aov_label{idx}").set(p)
                rop.parm(f"aov_variable{idx}").set(p)
                added.append(p)
        elif "ifd" in rop_type or "mantra" in rop_type:
            count_parm = rop.parm("vm_numaux")
            if not count_parm:
                return core._err("No vm_numaux parm.")
            base_idx = int(count_parm.eval())
            for i, p in enumerate(passes):
                idx = base_idx + i + 1
                count_parm.set(idx)
                rop.parm(f"vm_channel_plane{idx}").set(p)
                rop.parm(f"vm_variable_plane{idx}").set(p)
                added.append(p)
        return core._ok({"rop": rop_path, "added": added})
    except Exception:
        return core._err(core._traceback.format_exc())


def list_material_assignments(root: str = "/obj") -> dict:
    """Scan all geometry nodes and return material assignments."""
    core._require_hou()
    root_node = core._hou.node(root)
    if not root_node:
        return core._err(f"Root not found: {root}")
    assignments = []

    def scan(node):
        p = node.parm("shop_materialpath")
        if p and p.evalAsString():
            assignments.append(
                {
                    "node": node.path(),
                    "type": "object_parm",
                    "material": p.evalAsString(),
                }
            )
        if hasattr(node, "children"):
            for child in node.children():
                if child.type().name() == "material":
                    p2 = child.parm("shop_materialpath1")
                    if p2:
                        assignments.append(
                            {
                                "node": child.path(),
                                "type": "material_sop",
                                "material": p2.evalAsString(),
                            }
                        )
                scan(child)

    scan(root_node)
    return core._ok({"assignments": assignments})


def setup_render_output(
    parent_path: str = "/out",
    renderer: str = "karma",
    output_path: str = "$HIP/render/$HIPNAME.$F4.exr",
    start_frame: int = None,
    end_frame: int = None,
    camera_path: str = None,
) -> dict:
    """Create and configure a ROP node with correct output paths."""
    core._require_hou()
    parent = core._hou.node(parent_path)
    if not parent:
        return core._err(f"Parent not found: {parent_path}")
    try:
        sf = (
            start_frame
            if start_frame is not None
            else int(core._hou.playbar.frameRange()[0])
        )
        ef = (
            end_frame
            if end_frame is not None
            else int(core._hou.playbar.frameRange()[1])
        )
        if not camera_path:
            for n in core._hou.node("/obj").children():
                if n.type().name() == "cam":
                    camera_path = n.path()
                    break
        rmap = {
            "karma": "karma",
            "mantra": "ifd",
            "opengl": "opengl",
            "usdrender": "usdrender",
        }
        rtype = rmap.get(renderer.lower(), renderer)
        rop = parent.createNode(rtype, f"{renderer}_render")
        for p, v in [
            ("picture", output_path),
            ("vm_picture", output_path),
            ("camera", camera_path),
            ("f1", sf),
            ("f2", ef),
            ("trange", 1),
        ]:
            if rop.parm(p):
                rop.parm(p).set(v)
        os.makedirs(os.path.dirname(core._hou.expandString(output_path)), exist_ok=True)
        return core._ok(
            {"rop": rop.path(), "renderer": renderer, "output": output_path}
        )
    except Exception:
        return core._err(core._traceback.format_exc())


def submit_render(rop_path: str, farm: str = "local", priority: int = 50) -> dict:
    """Submit a ROP for rendering."""
    core._require_hou()
    rop = core._hou.node(rop_path)
    if not rop:
        return core._err(f"ROP not found: {rop_path}")
    try:
        if farm == "local":
            rop.render()
            return core._ok({"farm": "local", "rop": rop_path})
        elif farm == "deadline":
            core._hou.hipFile.save()
            hip = core._hou.hipFile.path()
            with tempfile.NamedTemporaryFile(
                "w", suffix="_job.txt", delete=False
            ) as jf:
                jf.write(
                    f"Plugin=Houdini\nName=HoudiniMind_{rop.name()}\nFrames={rop.parm('f1').eval()}-{rop.parm('f2').eval()}\n"
                )
            with tempfile.NamedTemporaryFile(
                "w", suffix="_plugin.txt", delete=False
            ) as pf:
                pf.write(f"SceneFile={hip}\nOutputDriver={rop_path}\n")
            res = subprocess.run(
                ["deadlinecommand", "-SubmitMultipleJobs", jf.name, pf.name],
                capture_output=True,
                text=True,
            )
            if res.returncode != 0:
                return core._err(f"Deadline failed: {res.stderr}")
            return core._ok(
                {"farm": "deadline", "job_id": res.stdout.strip().split()[-1]}
            )
        return core._err(f"Unknown farm '{farm}'.")
    except Exception:
        return core._err(core._traceback.format_exc())


def set_viewport_camera(camera_path: str, pane_index: int = 0) -> dict:
    """Point the Houdini viewport at a specific camera node."""
    core._require_hou()
    cam = core._hou.node(camera_path)
    if not cam:
        return core._err(f"Camera not found: {camera_path}")
    try:
        viewers = [
            p
            for d in core._hou.ui.desktops()
            for p in d.paneTabs()
            if p.type() == core._hou.paneTabType.SceneViewer
        ]
        if not viewers:
            return core._err("No Scene Viewer found.")
        viewer = viewers[min(pane_index, len(viewers) - 1)]
        viewer.curViewport().setCamera(cam)
        return core._ok({"camera": camera_path})
    except Exception:
        return core._err(core._traceback.format_exc())


def set_viewport_display_mode(mode: str, pane_index: int = 0) -> dict:
    """Change the viewport shading mode."""
    core._require_hou()
    mmap = {
        "smooth": core._hou.glShadingType.Smooth,
        "wire": core._hou.glShadingType.Wire,
        "wireghost": core._hou.glShadingType.WireGhost,
        "flat": core._hou.glShadingType.Flat,
        "points": core._hou.glShadingType.Points,
    }
    shading = mmap.get(mode.lower())
    if shading is None:
        return core._err(f"Unknown mode '{mode}'.")
    try:
        viewers = [
            p
            for d in core._hou.ui.desktops()
            for p in d.paneTabs()
            if p.type() == core._hou.paneTabType.SceneViewer
        ]
        if not viewers:
            return core._err("No Scene Viewer found.")
        viewer = viewers[min(pane_index, len(viewers) - 1)]
        viewer.curViewport().settings().setShadingMode(shading)
        return core._ok({"mode": mode})
    except Exception:
        return core._err(core._traceback.format_exc())


def assign_usd_material(
    lop_parent_path: str, prim_path: str, material_path: str
) -> dict:
    """Add a LOP Assign Material node to bind a mtlx material to a USD prim."""
    core._require_hou()
    parent = core._hou.node(lop_parent_path)
    if not parent:
        return core._err(f"LOP parent not found: {lop_parent_path}")
    try:
        assign = parent.createNode("assignmaterial", "assign_material")
        assign.parm("primpattern").set(prim_path)
        assign.parm("matspecpath1").set(material_path)
        last = next((c for c in reversed(parent.children()) if c != assign), None)
        if last:
            assign.setInput(0, last)
        parent.layoutChildren()
        return core._ok({"assign_node": assign.path()})
    except Exception:
        return core._err(core._traceback.format_exc())


def get_usd_prim_attributes(
    lop_node_path: str, prim_path: str, frame: int = None
) -> dict:
    """Read all USD attributes on a specific prim."""
    core._require_hou()
    node = core._hou.node(lop_node_path)
    if not node:
        return core._err(f"LOP node not found: {lop_node_path}")
    try:
        if frame is not None:
            core._hou.setFrame(frame)
        stage = node.stage()
        if stage is None:
            return core._err("Node has no USD stage.")
        prim = stage.GetPrimAtPath(prim_path)
        if not prim or not prim.IsValid():
            return core._err(f"USD prim not found at '{prim_path}'.")
        attrs = []
        for attr in prim.GetAttributes():
            try:
                val = attr.Get()
                vstr = (
                    str(val)[:200] + "..."
                    if val is not None and len(str(val)) > 200
                    else str(val)
                )
                attrs.append(
                    {
                        "name": attr.GetName(),
                        "type": str(attr.GetTypeName()),
                        "value": vstr,
                    }
                )
            except Exception:
                pass
        return core._ok(
            {
                "prim_path": prim_path,
                "prim_type": prim.GetTypeName(),
                "attributes": attrs,
            }
        )
    except Exception:
        return core._err(core._traceback.format_exc())


def create_usd_light(
    lop_parent_path: str,
    light_type: str = "rectlight",
    name: str = "key_light",
    intensity: float = 10.0,
    color: list = None,
    translate: list = None,
) -> dict:
    """Add a USD light to a Solaris stage."""
    core._require_hou()
    parent = core._hou.node(lop_parent_path)
    if not parent:
        return core._err(f"LOP parent not found: {lop_parent_path}")
    lt_map = {
        "rectlight": "rectlight",
        "spherelight": "spherelight",
        "distantlight": "distantlight",
        "domelight": "domelight",
    }
    ltype = lt_map.get(light_type.lower(), light_type)
    try:
        light = parent.createNode(ltype, name)
        for p in ("intensity", "light_intensity", "xn__inputsintensity_n2a"):
            if light.parm(p):
                light.parm(p).set(intensity)
                break
        if color and len(color) >= 3:
            for tp in ("light_color", "xn__inputscolor_tza"):
                if light.parmTuple(tp):
                    light.parmTuple(tp).set(color[:3])
                    break
        if translate and len(translate) >= 3:
            if light.parmTuple("t"):
                light.parmTuple("t").set(translate[:3])
        last = next((c for c in reversed(parent.children()) if c != light), None)
        if last:
            light.setInput(0, last)
        parent.layoutChildren()
        return core._ok({"light": light.path()})
    except Exception:
        return core._err(core._traceback.format_exc())


def validate_usd_stage(lop_node_path: str) -> dict:
    """Check a USD stage for common problems."""
    core._require_hou()
    node = core._hou.node(lop_node_path)
    if not node:
        return core._err(f"LOP node not found: {lop_node_path}")
    try:
        stage = node.stage()
        if stage is None:
            return core._err("Node has no USD stage.")
        errors, warnings, pcount = [], [], 0
        for prim in stage.TraverseAll():
            pcount += 1
            if not prim.GetTypeName() and not prim.IsPseudoRoot():
                warnings.append(
                    {"prim": str(prim.GetPath()), "issue": "No type defined"}
                )
        for e in node.errors():
            errors.append({"source": "lop_node", "message": str(e)})
        return core._ok(
            {
                "prim_count": pcount,
                "error_count": len(errors),
                "warning_count": len(warnings),
                "errors": errors,
                "warnings": warnings[:10],
            }
        )
    except Exception:
        return core._err(core._traceback.format_exc())


def reload_hda_definition(hda_node_path: str = None, hda_file_path: str = None) -> dict:
    """Reload an HDA definition from disk."""
    core._require_hou()
    try:
        if hda_file_path:
            core._hou.hda.reloadFile(hda_file_path)
            return core._ok(message=f"Reloaded file: {hda_file_path}")
        if hda_node_path:
            node = core._hou.node(hda_node_path)
            if not node or not node.type().definition():
                return core._err("Not an HDA.")
            fpath = node.type().definition().libraryFilePath()
            core._hou.hda.reloadFile(fpath)
            return core._ok(message=f"Reloaded def from: {fpath}")
        core._hou.hda.reloadAllFiles()
        return core._ok(message="Reloaded all.")
    except Exception:
        return core._err(core._traceback.format_exc())


def list_installed_hdas(filter_name: str = None) -> dict:
    """List all installed HDA definitions."""
    core._require_hou()
    try:
        hdas = []
        for fp in core._hou.hda.loadedFiles():
            try:
                defs = core._hou.hda.definitionsInFile(fp)
            except Exception:
                continue
            for d in defs:
                name = d.nodeType().name()
                if filter_name and filter_name.lower() not in name.lower():
                    continue
                hdas.append(
                    {
                        "name": name,
                        "label": d.description(),
                        "category": d.nodeTypeCategory().name(),
                        "file": fp,
                    }
                )
        hdas.sort(key=lambda h: h["name"])
        return core._ok({"hdas": hdas})
    except Exception:
        return core._err(core._traceback.format_exc())


def diff_hda_versions(node_path_a: str, node_path_b: str) -> dict:
    """Compare the parameter interfaces of two HDA instances."""
    core._require_hou()

    def get_p(path):
        n = core._hou.node(path)
        defn = n.type().definition() if n else None
        if not defn:
            return None, "Not an HDA."
        return {
            pt.name(): str(pt.type()) for pt in n.parmTemplateGroup().parmTemplates()
        }, None

    pa, ea = get_p(node_path_a)
    pb, eb = get_p(node_path_b)
    if ea or eb:
        return core._err(ea or eb)
    ka, kb = set(pa.keys()), set(pb.keys())
    return core._ok(
        {"only_in_a": list(ka - kb), "only_in_b": list(kb - ka), "both": list(ka & kb)}
    )


def create_documentation_snapshot(parent_path: str, output_path: str = None) -> dict:
    """Export a full network as an annotated Markdown report."""
    core._require_hou()
    parent = core._hou.node(parent_path)
    if not parent:
        return core._err(f"Node not found: {parent_path}")
    try:
        fpath = output_path or os.path.join(
            core._hou.expandString("$HIP"), "docs", f"{parent.name()}.md"
        )
        os.makedirs(os.path.dirname(fpath), exist_ok=True)
        nodes = list(parent.allSubChildren())
        lines = [
            f"# Network Documentation: `{parent_path}`",
            f"Generated: {time.ctime()}",
            "## Node Inventory",
            "| Path | Type |",
            "|---|---|",
        ]
        for n in nodes:
            lines.append(f"| `{n.path()}` | `{n.type().name()}` |")
        with open(fpath, "w") as f:
            f.write("\n".join(lines))
        return core._ok({"output": fpath, "count": len(nodes)})
    except Exception:
        return core._err(core._traceback.format_exc())


def auto_color_by_type(parent_path: str) -> dict:
    """Automatically color-code all nodes in a network by their category."""
    core._require_hou()
    parent = core._hou.node(parent_path)
    if not parent:
        return core._err(f"Node not found: {parent_path}")
    cmap = {
        "generator": core._hou.Color(0.2, 0.5, 0.4),
        "deformer": core._hou.Color(0.2, 0.4, 0.6),
        "merge": core._hou.Color(0.4, 0.4, 0.4),
        "vex": core._hou.Color(0.7, 0.4, 0.1),
        "sim": core._hou.Color(0.6, 0.2, 0.2),
        "output": core._hou.Color(0.2, 0.4, 0.1),
    }
    typed = {
        "box": "generator",
        "sphere": "generator",
        "bend": "deformer",
        "merge": "merge",
        "attribwrangle": "vex",
        "dopnet": "sim",
        "output": "output",
    }
    count = 0
    for n in parent.allSubChildren():
        key = typed.get(n.type().name().lower(), "default")
        if key in cmap:
            n.setColor(cmap[key])
            count += 1
    return core._ok({"colored": count})


def get_memory_usage() -> dict:
    """Return Houdini process memory usage in MB."""
    core._require_hou()
    try:
        import psutil

        proc = psutil.Process()
        return core._ok({"rss_mb": proc.memory_info().rss / 1024 / 1024})
    except ImportError:
        return core._err("psutil not found.")
    except Exception:
        return core._err(core._traceback.format_exc())


def suggest_optimization(parent_path: str) -> dict:
    """Analyze a SOP network and return actionable optimization suggestions."""
    core._require_hou()
    parent = core._hou.node(parent_path)
    if not parent:
        return core._err(f"Node not found: {parent_path}")
    suggs = []
    for n in parent.allSubChildren():
        if n.type().name().lower() in ("boolean", "polyreduce", "remesh"):
            suggs.append(
                {"node": n.path(), "issue": f"'{n.type().name()}' is potentially slow."}
            )
    return core._ok({"suggestions": suggs})


def convert_to_hda(
    node_path: str,
    hda_name: str,
    hda_label: str = None,
    save_path: str = None,
    version: str = "1.0",
) -> dict:
    """Convert a subnet to an HDA digital asset and save to disk."""
    core._require_hou()
    node = core._hou.node(node_path)
    if not node:
        return core._err(f"Node not found: {node_path}")
    if not node.type().name().startswith("subnet"):
        return core._err("Node must be a subnet to convert to HDA.")
    try:
        label = hda_label or hda_name
        save_dir = save_path or core._hou.expandString("$HOME/houdini19.5/otls")
        core._os.makedirs(save_dir, exist_ok=True)
        hda_path = core._os.path.join(save_dir, f"{hda_name}.hda")
        definition = node.type().definition()
        if definition is None:
            hda_file = core._hou.hda.createNewHdaFile(
                hda_path, hda_name, label, version
            )
            node.changeNodeType(hda_name)
            definition = node.type().definition()
        definition.setVersion(version)
        definition.save(hda_path, save_as_library=True)
        return core._ok({"hda_path": hda_path, "hda_name": hda_name})
    except Exception:
        return core._err(core._traceback.format_exc())


def get_hda_parameters(node_path: str) -> dict:
    """List all interface parameters on an HDA."""
    core._require_hou()
    node = core._hou.node(node_path)
    if not node:
        return core._err(f"Node not found: {node_path}")
    try:
        defn = node.type().definition()
        if not defn:
            return core._err("Node is not an HDA.")
        params = []
        for pt in node.parmTemplateGroup().parmTemplates():
            try:
                current = node.parm(pt.name()).eval() if node.parm(pt.name()) else None
            except Exception:
                current = None
            params.append(
                {
                    "name": pt.name(),
                    "label": pt.label(),
                    "type": str(pt.type()),
                    "default": pt.defaultValue()
                    if hasattr(pt, "defaultValue")
                    else None,
                    "current": current,
                }
            )
        return core._ok(
            {
                "hda": node.type().name(),
                "parameter_count": len(params),
                "parameters": params,
            }
        )
    except Exception:
        return core._err(core._traceback.format_exc())
