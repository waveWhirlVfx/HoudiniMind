# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
"""
Simulation tools: Vellum, FLIP, Pyro, RBD, baking.
"""

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
