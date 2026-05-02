# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
"""
Simulation tools: Vellum, FLIP, Pyro, RBD, baking.
"""

import os as _os
import traceback as _tb

from . import _core as core

_ok = core._ok
_err = core._err
_require_hou = core._require_hou

try:
    import hou

    HOU_AVAILABLE = core.HOU_AVAILABLE
except ImportError:
    HOU_AVAILABLE = False
    hou = None


def _set_first_available_parm(node, names, value):
    for name in names:
        parm = node.parm(name)
        if parm is None:
            continue
        try:
            parm.set(value)
            return name
        except Exception:
            continue
    return None


def _set_output_flags(node):
    try:
        node.setDisplayFlag(True)
    except Exception:
        pass
    try:
        node.setRenderFlag(True)
    except Exception:
        pass


def _create_first_available(parent, candidates, default_name):
    last_error = None
    for node_type, node_name in candidates:
        try:
            node = parent.createNode(node_type, node_name or default_name)
            return node, node_type
        except Exception as exc:
            last_error = exc
    tried = ", ".join(node_type for node_type, _node_name in candidates)
    raise RuntimeError(
        f"No available node type in {parent.path()}: {tried}. Last error: {last_error}"
    )


def _set_first_valid_input(node, input_indices, input_node, output_index=0):
    last_error = None
    for input_index in input_indices:
        try:
            node.setInput(input_index, input_node, output_index)
            return input_index
        except Exception as exc:
            last_error = exc
    raise RuntimeError(
        f"Could not connect {input_node.path()} to {node.path()} inputs "
        f"{list(input_indices)}. Last error: {last_error}"
    )


def _geometry_counts(node):
    try:
        geo = node.geometry()
        if not geo:
            return 0, 0, False
        points = list(geo.points())
        prims = list(geo.prims())
        has_volume = False
        for prim in prims:
            try:
                prim_type = str(prim.type().name()).lower()
            except Exception:
                prim_type = str(type(prim).__name__).lower()
            if "volume" in prim_type or "vdb" in prim_type:
                has_volume = True
                break
        return len(points), len(prims), has_volume
    except Exception:
        return 0, 0, False


def _attribute_names(node):
    names = []
    try:
        geo = node.geometry()
    except Exception:
        geo = None
    if geo is None:
        return names
    for method_name in ("pointAttribs", "primAttribs", "vertexAttribs", "globalAttribs"):
        try:
            attribs = getattr(geo, method_name)()
        except Exception:
            continue
        for attrib in attribs or []:
            try:
                name = attrib.name()
            except Exception:
                name = ""
            if name and name not in names:
                names.append(name)
    return names


def _pyro_source_attribute_names(*nodes):
    source_names = []
    for node in nodes:
        for name in _attribute_names(node):
            if name not in source_names:
                source_names.append(name)
    canonical = ["density", "temperature", "fuel", "v"]
    names = [name for name in source_names if name not in {"P", "N", "id"}]
    for name in canonical:
        if name not in names:
            names.append(name)
    return names


_FX_VALIDATION_WORKFLOWS = (
    "flip",
    "vellum_cloth",
    "vellum_pillow",
    "rbd",
    "pyro",
    "pop",
    "grains",
    "wire",
    "cache_export",
)


def _type_name(node):
    try:
        return node.type().name()
    except Exception:
        return ""


def _node_errors(node):
    try:
        return list(node.errors())
    except Exception:
        return []


def _node_warnings(node):
    try:
        return list(node.warnings())
    except Exception:
        return []


def _node_input_path(node, index):
    if index is None:
        return None
    try:
        inputs = node.inputs()
    except Exception:
        inputs = []
    if index >= len(inputs) or inputs[index] is None:
        return None
    try:
        return inputs[index].path()
    except Exception:
        return None


def _source_parent(root, workflow):
    try:
        child_category = root.childTypeCategory().name().lower()
    except Exception:
        child_category = ""
    if child_category == "sop":
        return root
    safe_name = f"hm_validate_{workflow}".replace("-", "_")
    return root.createNode("geo", safe_name)


def _setup_parent(root, source_parent, workflow):
    try:
        child_category = root.childTypeCategory().name().lower()
    except Exception:
        child_category = ""
    if child_category != "sop" and workflow in {"grains", "wire"}:
        return root
    return source_parent


def _create_validation_source(parent, workflow):
    source_specs = {
        "flip": ("sphere", "flip_source"),
        "vellum_cloth": ("grid", "cloth_source"),
        "vellum_pillow": ("box", "pillow_source"),
        "rbd": ("box", "rbd_source"),
        "pyro": ("sphere", "pyro_source_geo"),
        "pop": ("sphere", "pop_source_geo"),
        "grains": ("grid", "grain_source_geo"),
        "wire": ("curve", "wire_source_curve"),
        "cache_export": ("box", "cache_export_source"),
    }
    node_type, name = source_specs[workflow]
    try:
        source = parent.createNode(node_type, name)
    except Exception:
        fallback_type = "line" if workflow == "wire" else "box"
        source = parent.createNode(fallback_type, name)

    if workflow == "vellum_cloth":
        _set_first_available_parm(source, ("sizex", "sizey", "size"), 2.0)
    elif workflow in {"flip", "pyro", "pop"}:
        _set_first_available_parm(source, ("rad", "radius", "scale"), 0.35)
    elif workflow == "grains":
        _set_first_available_parm(source, ("sizex", "sizey", "size"), 1.5)
    return source


def _add_check(checks, name, passed, detail=None):
    checks.append(
        {
            "name": name,
            "status": "pass" if passed else "fail",
            "detail": detail,
        }
    )


def _check_node(checks, path, expected_type=None, label=None):
    node = hou.node(path) if path else None
    check_name = label or f"node exists: {path}"
    _add_check(checks, check_name, node is not None, path)
    if node is None:
        return None
    actual_type = _type_name(node)
    if expected_type:
        if isinstance(expected_type, (list, tuple, set)):
            type_ok = actual_type in expected_type
            detail = f"{actual_type} in {sorted(expected_type)}"
        else:
            type_ok = actual_type == expected_type
            detail = f"{actual_type} == {expected_type}"
        _add_check(checks, f"{check_name} type", type_ok, detail)
    errors = _node_errors(node)
    _add_check(checks, f"{check_name} has no node errors", not errors, errors)
    return node


def _check_input(checks, node_path, input_index, expected_path=None, label=None):
    node = hou.node(node_path) if node_path else None
    actual_path = _node_input_path(node, input_index) if node is not None else None
    if expected_path:
        passed = actual_path == expected_path
        detail = f"{actual_path} == {expected_path}"
    else:
        passed = actual_path is not None
        detail = actual_path
    _add_check(
        checks,
        label or f"{node_path} input {input_index} is wired",
        passed,
        detail,
    )


def _run_live_cook(checks, parent_path, output_path, start_frame, end_frame):
    if not output_path or end_frame < start_frame:
        return None
    try:
        from . import _advanced_tools

        result = _advanced_tools.cook_network_range(
            parent_path,
            start_frame,
            end_frame,
            node_path=output_path,
        )
    except Exception as exc:
        _add_check(checks, "live cook completed", False, str(exc))
        return None

    passed = result.get("status") == "ok" and not result.get("data", {}).get("error_frames")
    _add_check(checks, "live cook completed", passed, result.get("data") or result.get("error"))
    return result


def _validation_row(workflow, parent_path, source_path, result, checks, cook_result=None):
    failed = [check for check in checks if check["status"] != "pass"]
    warnings = []
    for value in (result.get("data") or {}).values():
        if isinstance(value, str):
            node = hou.node(value)
            if node is not None:
                warnings.extend(_node_warnings(node))
    return {
        "workflow": workflow,
        "status": "pass" if result.get("status") == "ok" and not failed else "fail",
        "parent": parent_path,
        "source": source_path,
        "tool_status": result.get("status"),
        "tool_error": (
            result.get("error") or result.get("message") if result.get("status") != "ok" else None
        ),
        "checks": checks,
        "warnings": warnings,
        "result": result.get("data"),
        "cook": cook_result.get("data")
        if cook_result and cook_result.get("status") == "ok"
        else None,
    }


def validate_fx_workflow_matrix(
    parent_path="/obj",
    workflows=None,
    cook_frames=0,
    cache_dir="$HIP/cache/houdinimind_validation",
):
    """Build and validate a live low-resolution FX workflow matrix.

    The tool creates disposable validation networks under ``parent_path`` and
    verifies expected nodes, core wiring, errors, cache TOP setup, and geometry
    export. Set ``cook_frames`` above zero to force-cook each output for that
    many frames.
    """
    try:
        _require_hou()
        root = hou.node(parent_path)
        if not root:
            return _err(f"Parent not found: {parent_path}")

        if workflows is None:
            selected = list(_FX_VALIDATION_WORKFLOWS)
        elif isinstance(workflows, str):
            selected = [name.strip() for name in workflows.split(",") if name.strip()]
        else:
            selected = list(workflows)
        unknown = [name for name in selected if name not in _FX_VALIDATION_WORKFLOWS]
        if unknown:
            return _err(
                "Unknown workflow(s): "
                + ", ".join(unknown)
                + ". Expected one or more of: "
                + ", ".join(_FX_VALIDATION_WORKFLOWS)
            )

        rows = []
        start_frame = 1
        end_frame = max(0, int(cook_frames or 0))

        for workflow in selected:
            checks = []
            source_parent = _source_parent(root, workflow)
            parent = _setup_parent(root, source_parent, workflow)
            source = _create_validation_source(source_parent, workflow)
            result = {"status": "error", "error": "workflow did not run", "data": {}}
            cook_result = None
            output_path = None

            if workflow == "flip":
                result = setup_flip_fluid(parent.path(), source.path(), particle_separation=0.25)
                data = result.get("data") or {}
                _check_node(checks, data.get("source"), "flipsource", "FLIP source")
                _check_node(checks, data.get("dopnet"), "dopnet", "FLIP DOP network")
                _check_node(checks, data.get("solver"), "flipsolver", "FLIP solver")
                _check_node(checks, data.get("surface"), "particlefluidsurface", "FLIP surface")
                _check_input(
                    checks, data.get("source"), 0, source.path(), "FLIP source uses input geo"
                )
                _check_input(checks, data.get("solver"), 0, label="FLIP solver has FLIP object")
                _check_input(
                    checks, data.get("surface"), 0, data.get("dopnet"), "FLIP surface reads DOP"
                )
                output_path = data.get("surface")

            elif workflow == "vellum_cloth":
                result = setup_vellum_cloth(parent.path(), source.path())
                data = result.get("data") or {}
                _check_node(
                    checks, data.get("constraints"), "vellumconstraints", "Vellum cloth constraints"
                )
                _check_node(checks, data.get("solver"), "vellumsolver", "Vellum cloth solver")
                _check_node(checks, data.get("cache"), "vellumio", "Vellum cloth cache")
                _check_input(
                    checks, data.get("constraints"), 0, source.path(), "Vellum cloth source wired"
                )
                _check_input(
                    checks, data.get("solver"), 0, data.get("constraints"), "Vellum geometry input"
                )
                _check_input(
                    checks,
                    data.get("solver"),
                    2,
                    data.get("constraints"),
                    "Vellum constraints input",
                )
                _check_input(checks, data.get("cache"), 0, data.get("solver"), "Vellum cache input")
                output_path = data.get("cache")

            elif workflow == "vellum_pillow":
                result = setup_vellum_pillow(parent.path(), source.path())
                data = result.get("data") or {}
                _check_node(
                    checks, data.get("constraints"), "vellumconstraints", "Vellum pillow struts"
                )
                _check_node(checks, data.get("solver"), "vellumsolver", "Vellum pillow solver")
                _check_input(
                    checks, data.get("constraints"), 0, label="Pillow struts read pressure cloth"
                )
                _check_input(
                    checks, data.get("solver"), 0, data.get("constraints"), "Pillow geometry input"
                )
                _check_input(
                    checks,
                    data.get("solver"),
                    2,
                    data.get("constraints"),
                    "Pillow constraints input",
                )
                output_path = data.get("solver")

            elif workflow == "rbd":
                result = setup_rbd_fracture(parent.path(), source.path(), num_pieces=8)
                data = result.get("data") or {}
                _check_node(
                    checks,
                    data.get("fracture"),
                    {"rbdmaterialfracture", "voronoifracture", "voronoifracturesurface"},
                    "RBD fracture",
                )
                _check_node(checks, data.get("solver"), "rbdbulletsolver", "RBD bullet solver")
                _check_node(checks, data.get("output"), "null", "RBD output")
                _check_input(checks, data.get("fracture"), 0, source.path(), "RBD source wired")
                _check_input(
                    checks, data.get("solver"), 0, data.get("fracture"), "RBD solver geometry"
                )
                _check_input(checks, data.get("output"), 0, data.get("solver"), "RBD output wired")
                output_path = data.get("output")

            elif workflow == "pyro":
                result = setup_pyro_sim(parent.path(), source.path(), resolution_scale=2)
                data = result.get("data") or {}
                _check_node(
                    checks, data.get("source_attributes"), "attribwrangle", "Pyro attributes"
                )
                _check_node(checks, data.get("source"), "pyrosource", "Pyro source")
                _check_node(
                    checks,
                    data.get("volume_rasterize"),
                    "volumerasterizeattributes",
                    "Pyro rasterize",
                )
                _check_node(checks, data.get("solver"), "pyrosolver", "Pyro solver")
                _check_node(checks, data.get("output"), "null", "Pyro output")
                _check_input(
                    checks,
                    data.get("source"),
                    0,
                    data.get("source_attributes"),
                    "Pyro source attributes wired",
                )
                _check_input(
                    checks,
                    data.get("volume_rasterize"),
                    0,
                    data.get("source"),
                    "Pyro rasterize wired",
                )
                _check_input(
                    checks,
                    data.get("solver"),
                    0,
                    data.get("volume_rasterize"),
                    "Pyro solver volume input",
                )
                _check_input(
                    checks, data.get("output"), 0, label="Pyro output has solver/postprocess input"
                )
                output_path = data.get("output")

            elif workflow == "pop":
                result = setup_pop_sim(parent.path(), source.path(), birth_rate=100)
                data = result.get("data") or {}
                _check_node(checks, data.get("dopnet"), "dopnet", "POP DOP network")
                _check_node(checks, data.get("pop_object"), "popobject", "POP object")
                _check_node(
                    checks, data.get("pop_solver"), {"popsolver", "popsolver::2.0"}, "POP solver"
                )
                _check_node(
                    checks, data.get("pop_source"), {"popsource", "popsource::2.0"}, "POP source"
                )
                _check_input(
                    checks, data.get("pop_solver"), 0, data.get("pop_object"), "POP object input"
                )
                _check_input(
                    checks,
                    data.get("pop_solver"),
                    (data.get("solver_inputs") or {}).get("source", 1),
                    data.get("pop_source"),
                    "POP source input",
                )
                _check_input(checks, data.get("pop_solver"), 2, label="POP force input")
                output_path = data.get("pop_solver")

            elif workflow == "grains":
                from . import _advanced_tools

                result = _advanced_tools.setup_grain_sim(
                    parent.path(),
                    source.path(),
                    particle_separation=0.08,
                    friction=0.6,
                    clumping=0.05,
                )
                data = result.get("data") or {}
                dopnet = data.get("dopnet")
                _check_node(checks, data.get("geo_setup"), "geo", "Grain SOP setup")
                _check_node(checks, dopnet, "dopnet", "Grain DOP network")
                solver_path = data.get("solver") or (f"{dopnet}/pop_solver" if dopnet else None)
                object_path = data.get("pop_object") or (
                    f"{dopnet}/grain_object" if dopnet else None
                )
                grains_path = data.get("pop_grains") or (f"{dopnet}/pop_grains" if dopnet else None)
                source_path = data.get("pop_source") or (
                    f"{dopnet}/grain_source" if dopnet else None
                )
                _check_node(checks, object_path, "popobject", "Grain POP object")
                _check_node(checks, source_path, "popsource", "Grain POP source")
                _check_node(checks, grains_path, "popgrains", "POP grains")
                _check_node(checks, solver_path, "popsolver", "Grain POP solver")
                _check_input(checks, solver_path, 0, object_path, "Grain object input")
                _check_input(checks, solver_path, 1, source_path, "Grain source input")
                _check_input(checks, solver_path, 2, grains_path, "Grain constraint input")
                output_path = solver_path

            elif workflow == "wire":
                from . import _advanced_tools

                result = _advanced_tools.setup_wire_solver(parent.path(), source.path())
                data = result.get("data") or {}
                dopnet = data.get("dopnet")
                _check_node(checks, data.get("wire_object"), "wireobject", "Wire object")
                _check_node(checks, dopnet, "dopnet", "Wire DOP network")
                _check_node(checks, data.get("solver"), "wiresolver", "Wire solver")
                _check_input(
                    checks, data.get("solver"), 0, label="Wire solver has wire object input"
                )
                output_path = data.get("solver")

            elif workflow == "cache_export":
                from . import _pdg_tools, _perf_org_tools

                expanded_cache_dir = hou.expandString(cache_dir)
                export_path = _os.path.join(expanded_cache_dir, "validation_export.bgeo.sc")
                export_result = _perf_org_tools.export_geometry(source.path(), export_path, frame=1)
                result = export_result
                topnet = root.createNode("topnet", "hm_validate_cache_topnet")
                cache_result = _pdg_tools.create_file_cache_top(
                    topnet.path(), source.path(), cache_dir
                )
                data = {
                    "export": export_result.get("data"),
                    "file_cache": (cache_result.get("data") or {}).get("path"),
                    "topnet": topnet.path(),
                }
                result = {
                    "status": "ok"
                    if export_result.get("status") == "ok" and cache_result.get("status") == "ok"
                    else "error",
                    "data": data,
                    "error": export_result.get("error") or cache_result.get("error"),
                }
                _add_check(
                    checks,
                    "geometry export succeeded",
                    export_result.get("status") == "ok",
                    export_result.get("data") or export_result.get("error"),
                )
                exported_to = (export_result.get("data") or {}).get("exported_to")
                _add_check(
                    checks,
                    "export file exists",
                    bool(exported_to and _os.path.exists(exported_to)),
                    exported_to,
                )
                _check_node(checks, topnet.path(), "topnet", "Cache TOP network")
                _check_node(checks, data.get("file_cache"), "filecache", "File Cache TOP")
                file_cache = hou.node(data.get("file_cache")) if data.get("file_cache") else None
                soppath = (
                    file_cache.parm("soppath").eval()
                    if file_cache and file_cache.parm("soppath")
                    else None
                )
                _add_check(
                    checks, "File Cache TOP points at source SOP", soppath == source.path(), soppath
                )
                output_path = source.path()

            if end_frame >= start_frame and workflow != "cache_export":
                cook_result = _run_live_cook(
                    checks, parent.path(), output_path, start_frame, end_frame
                )

            rows.append(
                _validation_row(
                    workflow,
                    parent.path(),
                    source.path(),
                    result,
                    checks,
                    cook_result,
                )
            )

        failed_rows = [row for row in rows if row["status"] != "pass"]
        return _ok(
            {
                "status": "pass" if not failed_rows else "fail",
                "total": len(rows),
                "passed": len(rows) - len(failed_rows),
                "failed": len(failed_rows),
                "workflows": selected,
                "rows": rows,
            },
            message=(
                f"FX workflow validation matrix: {len(rows) - len(failed_rows)}/{len(rows)} passed."
            ),
        )
    except Exception:
        return _err(_tb.format_exc())


def setup_vellum_cloth(
    parent_path,
    geo_node_path,
    collision_nodes=None,
    thickness=0.01,
    stiffness=1e9,
    pressure=0.0,
    rest_scale=1.0,
):
    """Full Vellum cloth rig: VellumConstraints + VellumSolver + collision + VellumIO."""
    try:
        _require_hou()
        parent = hou.node(parent_path)
        if not parent:
            return _err(f"Parent not found: {parent_path}")
        geo_node = hou.node(geo_node_path)
        if not geo_node:
            return _err(f"Geo node not found: {geo_node_path}")
        cfg = parent.createNode("vellumconstraints", "vellum_cloth_constraints")
        cfg.setInput(0, geo_node)
        for pname, val in [
            ("constrainttype", "cloth"),
            ("thickness", thickness),
            ("bendstiffness", stiffness),
        ]:
            p = cfg.parm(pname)
            if p:
                p.set(val)
        if pressure != 0:
            pres = parent.createNode("vellumconstraints", "vellum_pressure")
            pres.setInput(0, cfg)
            pres.parm("constrainttype").set("pressure")
            pres.parm("pressure").set(pressure)
            pres.parm("restlengthscale").set(rest_scale)
            cfg = pres
        solver = parent.createNode("vellumsolver", "vellum_solver")
        solver.setInput(0, cfg)
        solver.setInput(2, cfg, 1)
        if collision_nodes:
            merge = parent.createNode("merge", "collision_merge")
            for i, cn_path in enumerate(collision_nodes):
                cn = hou.node(cn_path)
                if cn:
                    merge.setInput(i, cn)
            solver.setInput(1, merge)
        vio = parent.createNode("vellumio", "vellum_cache")
        vio.setInput(0, solver)
        vio.setInput(1, solver, 1)
        parent.layoutChildren()
        return _ok(
            {"constraints": cfg.path(), "solver": solver.path(), "cache": vio.path()},
            message=f"UNDO_TRACK: Vellum cloth rig created in {parent_path}",
        )
    except Exception:
        return _err(_tb.format_exc())


def setup_vellum_pillow(parent_path, geo_node_path, thickness=0.15):
    """Create a pillow rig using Vellum Pressure and Strut constraints."""
    try:
        _require_hou()
        parent = hou.node(parent_path)
        if not parent:
            return _err(f"Parent not found: {parent_path}")
        node = hou.node(geo_node_path)
        if not node:
            return _err(f"Geo node not found: {geo_node_path}")
        cloth = parent.createNode("vellumconstraints", "pillow_cloth")
        cloth.setInput(0, node)
        cloth.parm("constrainttype").set("cloth")
        cloth.parm("thickness").set(0.01)
        pres = parent.createNode("vellumconstraints", "pillow_pressure")
        pres.setInput(0, cloth)
        pres.parm("constrainttype").set("pressure")
        pres.parm("pressure").set(5.0)
        pres.parm("restlengthscale").set(1.1)
        strut = parent.createNode("vellumconstraints", "pillow_struts")
        strut.setInput(0, pres)
        strut.parm("constrainttype").set("strut")
        strut.parm("stiffness").set(1e4)
        solver = parent.createNode("vellumsolver", "pillow_solver")
        solver.setInput(0, strut)
        solver.setInput(2, strut, 1)
        return _ok(
            {"solver": solver.path(), "constraints": strut.path()},
            message="UNDO_TRACK: Vellum Pillow rig created",
        )
    except Exception:
        return _err(_tb.format_exc())


def get_dop_objects(dop_node_path):
    """Inspect DOP network objects, their types and fields."""
    try:
        _require_hou()
        node = hou.node(dop_node_path)
        if not node:
            return _err(f"DOP node not found: {dop_node_path}")
        sim = node.simulation()
        if not sim:
            return _err("No simulation object (not a DOP network?)")
        objects = [
            {
                "name": obj.name(),
                "type": str(obj.objType()),
                "fields": [f.name() for f in obj.fields()][:10],
            }
            for obj in sim.objects()
        ]
        return _ok({"object_count": len(objects), "objects": objects})
    except Exception as e:
        return _err(str(e))


def bake_simulation(
    dop_node_path,
    start_frame=1,
    end_frame=100,
    cache_dir="$HIP/cache",
    max_total_seconds: float = 300.0,
):
    """Cook and cache a simulation frame-by-frame.

    ``max_total_seconds`` prevents the bake from running forever if a frame
    stalls. Qt events are processed between frames so Houdini stays responsive.
    """
    import time as _time

    try:
        from PySide2.QtWidgets import QApplication as _QApp

        _qt = True
    except Exception:
        try:
            from PySide6.QtWidgets import QApplication as _QApp

            _qt = True
        except Exception:
            _qt = False

    try:
        _require_hou()
        node = hou.node(dop_node_path)
        if not node:
            return _err(f"Node not found: {dop_node_path}")
        current = hou.frame()
        times = []
        deadline = _time.time() + max_total_seconds
        frames_baked = 0

        for f in range(start_frame, end_frame + 1):
            if _time.time() >= deadline:
                return _err(
                    f"bake_simulation stopped at frame {f}: exceeded {max_total_seconds}s time limit. "
                    f"Baked {frames_baked} frames."
                )
            hou.setFrame(f)
            t0 = core.time.perf_counter()
            node.cook(force=True)
            times.append(core.time.perf_counter() - t0)
            frames_baked += 1
            if _qt:
                _QApp.processEvents()

        hou.setFrame(current)
        return _ok(
            {
                "frames_baked": frames_baked,
                "avg_cook_s": round(sum(times) / len(times), 3),
                "total_s": round(sum(times), 2),
                "cache_dir": cache_dir,
            },
            message=f"Simulation baked: {start_frame}–{start_frame + frames_baked - 1}",
        )
    except Exception as e:
        return _err(str(e))


def get_sim_stats(solver_node_path):
    """Read sim parameters: substeps, constraint iterations, gravity, errors."""
    try:
        _require_hou()
        node = hou.node(solver_node_path)
        if not node:
            return _err(f"Node not found: {solver_node_path}")

        def _p(n):
            p = node.parm(n)
            return p.eval() if p else None

        stats = {
            "node_type": node.type().name(),
            "substeps": _p("substeps"),
            "constraint_iterations": _p("constraintiterations") or _p("iterations"),
            "gravity": _p("gravity") or _p("gravityy"),
            "scene_scale": _p("scenescale"),
            "errors": list(node.errors()),
            "warnings": list(node.warnings()),
        }
        try:
            geo = node.geometry()
            if geo:
                stats["output_point_count"] = len(geo.points())
        except Exception:
            pass
        return _ok(stats)
    except Exception as e:
        return _err(str(e))


def setup_flip_fluid(
    parent_path,
    geo_node_path,
    container_size=None,
    particle_separation=0.1,
    gravity=-9.8,
    cache_dir="$HIP/cache/flip",
):
    """Full FLIP rig: source → dopnet(flipsolver) → particlefluidsurface → output."""
    if container_size is None:
        container_size = [4, 3, 4]
    try:
        _require_hou()
        parent = hou.node(parent_path)
        if not parent:
            return _err(f"Parent not found: {parent_path}")
        geo = hou.node(geo_node_path)
        if not geo:
            return _err(f"Geo node not found: {geo_node_path}")
        src = parent.createNode("flipsource", "flipsource1")
        src.setInput(0, geo)
        dopnet = parent.createNode("dopnet", "flip_dopnet")
        flip_obj = dopnet.createNode("flipobject", "flipobject1")
        p = flip_obj.parm("particlesep")
        if p:
            p.set(particle_separation)
        solver = dopnet.createNode("flipsolver", "flipsolver1")
        gp = solver.parm("gravity")
        if gp:
            gp.set(gravity)
        solver.setInput(0, flip_obj)
        pfs = parent.createNode("particlefluidsurface", "fluid_surface")
        pfs.setInput(0, dopnet)
        parent.layoutChildren()
        return _ok(
            {
                "source": src.path(),
                "dopnet": dopnet.path(),
                "solver": solver.path(),
                "surface": pfs.path(),
            },
            message="UNDO_TRACK: Created full FLIP rig",
        )
    except Exception:
        return _err(_tb.format_exc())


def setup_pop_sim(
    parent_path,
    source_node_path,
    birth_rate=5000,
):
    """Create a Houdini 21 DOP-based POP simulation (dopnet, popobject, popsolver, popsource)."""
    try:
        _require_hou()
        parent = hou.node(parent_path)
        if not parent:
            return _err(f"Parent not found: {parent_path}")
        src_node = hou.node(source_node_path)
        if not src_node:
            return _err(f"Source node not found: {source_node_path}")

        dopnet = parent.createNode("dopnet", "pop_sim")
        dopnet.setInput(0, src_node)

        pop_obj, pop_obj_type = _create_first_available(
            dopnet,
            (("popobject", "popobject1"),),
            "popobject1",
        )
        pop_solver, pop_solver_type = _create_first_available(
            dopnet,
            (("popsolver::2.0", "popsolver1"), ("popsolver", "popsolver1")),
            "popsolver1",
        )
        pop_src, pop_src_type = _create_first_available(
            dopnet,
            (("popsource::2.0", "popsource1"), ("popsource", "popsource1")),
            "popsource1",
        )

        pop_solver.setInput(0, pop_obj)
        source_input_index = _set_first_valid_input(pop_solver, (1, 3), pop_src)

        output = dopnet.createNode("output", "OUT")
        output.setInput(0, pop_solver)
        _set_output_flags(output)

        p_use = pop_src.parm("usecontextgeo")
        if p_use:
            try:
                p_use.set(1)
            except Exception:
                pass

        p_birth = pop_src.parm("birthrate")
        if p_birth:
            try:
                p_birth.set(birth_rate)
            except Exception:
                pass

        pop_force, pop_force_type = _create_first_available(
            dopnet,
            (
                ("popvortex", "popvortex1"),
                ("popforce", "popforce1"),
                ("popwind", "popwind1"),
            ),
            "popforce1",
        )
        pop_drag, pop_drag_type = _create_first_available(
            dopnet,
            (("popdrag", "popdrag1"),),
            "popdrag1",
        )

        merge_forces = dopnet.createNode("merge", "merge_forces")
        merge_forces.setInput(0, pop_force)
        merge_forces.setInput(1, pop_drag)

        forces_input_index = _set_first_valid_input(pop_solver, (2,), merge_forces)

        dopnet.layoutChildren()
        parent.layoutChildren()

        return _ok(
            {
                "dopnet": dopnet.path(),
                "pop_object": pop_obj.path(),
                "pop_solver": pop_solver.path(),
                "pop_source": pop_src.path(),
                "pop_force": pop_force.path(),
                "pop_vortex": pop_force.path(),
                "pop_drag": pop_drag.path(),
                "solver_inputs": {
                    "object": 0,
                    "source": source_input_index,
                    "forces": forces_input_index,
                },
                "node_types": {
                    "pop_object": pop_obj_type,
                    "pop_solver": pop_solver_type,
                    "pop_source": pop_src_type,
                    "pop_force": pop_force_type,
                    "pop_drag": pop_drag_type,
                },
            },
            message="UNDO_TRACK: Created POP simulation DOP network",
        )
    except Exception:
        return _err(_tb.format_exc())


def setup_pyro_sim(
    parent_path,
    source_node_path,
    fuel_type="fire_and_smoke",
    container_size=None,
    resolution_scale=2,
):
    """Create a Houdini 21 SOP-level Pyro rig with point attributes rasterized before the solver."""
    if container_size is None:
        container_size = [4, 4, 4]
    try:
        _require_hou()
        parent = hou.node(parent_path)
        if not parent:
            return _err(f"Parent not found: {parent_path}")
        src_node = hou.node(source_node_path)
        if not src_node:
            return _err(f"Source node not found: {source_node_path}")

        point_count, prim_count, has_volume = _geometry_counts(src_node)
        source_points = None
        source_mode = "points"
        source_input = src_node
        if has_volume:
            source_points = parent.createNode("pointsfromvolume", "pyro_volume_scatter")
            source_points.setInput(0, src_node)
            _set_first_available_parm(
                source_points,
                ("pointseparation", "separation", "particlesep", "voxelsize"),
                0.05,
            )
            source_input = source_points
            source_mode = "volume_scatter"
        elif prim_count > 0:
            source_points = parent.createNode("scatter", "pyro_surface_scatter")
            source_points.setInput(0, src_node)
            _set_first_available_parm(
                source_points,
                ("npts", "forcecount", "forcetotalcount", "count"),
                300,
            )
            source_input = source_points
            source_mode = "surface_scatter"
        elif point_count > 0:
            source_mode = "keep_points"

        attr_src = parent.createNode("attribwrangle", "pyro_source_attributes")
        attr_src.setInput(0, source_input)
        pyro_attributes = _pyro_source_attribute_names(src_node, source_input)
        attr_parm = attr_src.parm("snippet")
        if attr_parm:
            attr_parm.set(
                "if (!haspointattrib(0, 'v')) v@v = set(0, 4 + fit01(rand(@ptnum), 0, 2), 0);\n"
                "if (!haspointattrib(0, 'temperature')) f@temperature = 1.0;\n"
                "if (!haspointattrib(0, 'density')) f@density = 1.0;\n"
                "if (!haspointattrib(0, 'fuel')) f@fuel = 0.7;\n"
            )

        pyro_src = parent.createNode("pyrosource", "pyrosource1")
        pyro_src.setInput(0, attr_src)
        _set_first_available_parm(
            pyro_src,
            ("mode", "sourcemode", "initialize", "fueltype"),
            fuel_type,
        )

        rasterize = parent.createNode("volumerasterizeattributes", "pyro_volume_rasterize")
        rasterize.setInput(0, pyro_src)
        attribute_string = " ".join(pyro_attributes)
        _set_first_available_parm(
            rasterize,
            ("attributes", "attribs", "pointattributes", "point_attribs", "attr"),
            attribute_string,
        )
        voxel_size = max(0.005, 0.1 / max(float(resolution_scale or 1), 1.0))
        _set_first_available_parm(
            rasterize,
            ("voxelsize", "voxel_size", "divsize", "particlescale", "radius"),
            voxel_size,
        )

        solver = parent.createNode("pyrosolver", "pyrosolver1")
        solver.setInput(0, rasterize)
        _set_first_available_parm(
            solver,
            ("divsize", "voxelsize", "voxel_size", "res"),
            voxel_size,
        )

        postprocess = None
        try:
            postprocess = parent.createNode("pyropostprocess", "pyro_postprocess")
            postprocess.setInput(0, solver)
            output_source = postprocess
        except Exception:
            output_source = solver

        output = parent.createNode("null", "pyro_out")
        output.setInput(0, output_source)
        _set_output_flags(output)
        parent.layoutChildren()
        return _ok(
            {
                "source": pyro_src.path(),
                "source_points": source_points.path() if source_points else None,
                "source_attributes": attr_src.path(),
                "volume_rasterize": rasterize.path(),
                "source_mode": source_mode,
                "solver": solver.path(),
                "postprocess": postprocess.path() if postprocess else None,
                "output": output.path(),
                "mode": "sop",
                "voxel_size": voxel_size,
                "container_size": container_size,
                "required_attributes": ["density", "temperature", "fuel", "v"],
                "rasterized_attributes": pyro_attributes,
            },
            message="UNDO_TRACK: Created SOP-level Pyro rig with Volume Rasterize Attributes before solver",
        )
    except Exception:
        return _err(_tb.format_exc())


def setup_rbd_fracture(
    parent_path,
    geo_node_path,
    fracture_type="voronoi",
    num_pieces=50,
    constraint_type="glue",
    create_solver=True,
):
    """Create a Houdini 21 SOP-level RBD fracture and optional Bullet Solver network."""
    try:
        _require_hou()
        parent = hou.node(parent_path)
        if not parent:
            return _err(f"Parent not found: {parent_path}")
        geo = hou.node(geo_node_path)
        if not geo:
            return _err(f"Geo node not found: {geo_node_path}")

        frac = None
        last_err = None
        for candidate in ("rbdmaterialfracture", "voronoifracture", "voronoifracturesurface"):
            try:
                frac = parent.createNode(candidate, "fracture1")
                frac_type = candidate
                break
            except Exception as e:
                last_err = f"{candidate}: {e}"
        if not frac:
            return _err(
                f"No valid fracture node type available in this parent context. "
                f"Tried rbdmaterialfracture, voronoifracture, voronoifracturesurface. "
                f"Last error: {last_err}"
            )

        try:
            frac.setInput(0, geo)
        except Exception as e:
            return _err(f"Created {frac.path()} but could not wire input: {e}")

        for parm_name in ("npts", "numpieces", "nfragments"):
            p = frac.parm(parm_name)
            if p is not None:
                try:
                    p.set(num_pieces)
                    break
                except Exception:
                    continue

        final_node = frac

        solver = None
        output = None
        if create_solver:
            try:
                solver = parent.createNode("rbdbulletsolver", "rbd_bullet_solver")
                solver.setInput(0, final_node)
                # rbdmaterialfracture exposes constraints on out 1 and proxy on out 2;
                # rbdbulletsolver expects them on in 1 and in 2. Always wire both —
                # leaving them empty is the most common manual-fixup users hit.
                try:
                    if frac.type().name().startswith("rbdmaterialfracture"):
                        if len(frac.outputConnectors()) > 1:
                            solver.setInput(1, frac, 1)
                        if len(frac.outputConnectors()) > 2:
                            solver.setInput(2, frac, 2)
                except Exception:
                    pass
                _set_first_available_parm(solver, ("useground", "groundplane", "showground"), 1)
                _set_first_available_parm(
                    solver, ("constrainttype", "constraint_type"), constraint_type
                )
                output = parent.createNode("null", "rbd_out")
                output.setInput(0, solver)
                _set_output_flags(output)
                final_node = output
            except Exception as e:
                try:
                    if solver is not None:
                        solver.addWarning(f"Could not finish SOP RBD solver setup: {e}")
                except Exception:
                    pass

        try:
            parent.layoutChildren()
        except Exception:
            pass

        return _ok(
            {
                "fracture": frac.path(),
                "output_node": final_node.path(),
                "solver": solver.path() if solver else None,
                "output": output.path() if output else final_node.path(),
                "fracture_type": frac_type,
                "num_pieces": num_pieces,
                "constraint_type": constraint_type,
                "mode": "sop",
            },
            message=(
                f"UNDO_TRACK: Created SOP-level {frac_type} RBD setup ending at "
                f"{final_node.path()}."
            ),
        )
    except Exception:
        return _err(_tb.format_exc())


def get_simulation_diagnostic(solver_path):
    """Analyse a simulation solver (SOP or DOP) for common issues.

    Checks for: active objects, gravity settings, substeps, and geometry errors.
    """
    try:
        _require_hou()
        node = hou.node(solver_path)
        if not node:
            return _err(f"Solver not found: {solver_path}")

        diag = {
            "path": solver_path,
            "type": node.type().name(),
            "errors": list(node.errors()),
            "warnings": list(node.warnings()),
            "is_time_dependent": node.isTimeDependent(),
        }

        # SOP Solver Specifics (RBD Bullet Solver)
        if node.type().name() == "rbdbulletsolver":
            diag["active_objects_count"] = 0
            geo = node.geometry()
            if geo:
                diag["point_count"] = len(geo.points())
                active_attr = geo.findPointAttrib("active")
                if active_attr:
                    active_vals = geo.pointIntAttribValues("active")
                    diag["active_objects_count"] = sum(active_vals)
                else:
                    diag["warning"] = "Missing 'active' attribute. Solver may treat all as static."

            grav = node.parmTuple("gravity")
            if grav:
                diag["gravity"] = list(grav.eval())

        # DOP Net Specifics
        elif node.type().name() == "dopnet":
            diag["objects"] = [obj.name() for obj in node.objects()]
            grav = node.parm("gravity")
            if grav:
                diag["gravity"] = grav.eval()

        return _ok(diag)
    except Exception as e:
        return _err(str(e))


def get_flip_diagnostic(dopnet_path):
    """Analyse a FLIP simulation: particle count, velocity range, substeps, NaN detection."""
    try:
        _require_hou()
        node = hou.node(dopnet_path)
        if not node:
            return _err(f"DOP network not found: {dopnet_path}")

        diag = {
            "path": dopnet_path,
            "type": node.type().name(),
            "errors": list(node.errors()),
            "warnings": list(node.warnings()),
        }

        substeps_parm = node.parm("substep") or node.parm("substeps")
        if substeps_parm:
            diag["substeps"] = substeps_parm.eval()

        flip_object = None
        try:
            for obj in node.objects():
                obj_type = obj.type().name() if hasattr(obj, "type") else ""
                if "flip" in obj_type.lower():
                    flip_object = obj
                    break
        except Exception:
            pass

        if flip_object is not None:
            try:
                geo = flip_object.geometry()
                if geo:
                    points = geo.points()
                    diag["particle_count"] = len(points)
                    if points:
                        v_attr = geo.findPointAttrib("v")
                        if v_attr:
                            speeds = []
                            nan_count = 0
                            for p in points[:5000]:
                                vx, vy, vz = p.attribValue("v")
                                if vx != vx or vy != vy or vz != vz:
                                    nan_count += 1
                                    continue
                                speeds.append((vx * vx + vy * vy + vz * vz) ** 0.5)
                            if speeds:
                                diag["velocity_min"] = min(speeds)
                                diag["velocity_max"] = max(speeds)
                                diag["velocity_avg"] = sum(speeds) / len(speeds)
                            diag["nan_velocities"] = nan_count
            except Exception as inner:
                diag["flip_object_error"] = str(inner)
        else:
            diag["warning"] = "No FLIP object found inside the DOP network."

        return _ok(diag)
    except Exception as e:
        return _err(str(e))
