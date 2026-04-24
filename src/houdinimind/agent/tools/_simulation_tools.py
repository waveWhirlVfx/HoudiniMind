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
    except Exception as e:
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
    except Exception as e:
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
    dop_node_path, start_frame=1, end_frame=100, cache_dir="$HIP/cache"
):
    """Cook and cache a simulation frame-by-frame."""
    try:
        _require_hou()
        node = hou.node(dop_node_path)
        if not node:
            return _err(f"Node not found: {dop_node_path}")
        current = hou.frame()
        times = []
        for f in range(start_frame, end_frame + 1):
            hou.setFrame(f)
            t0 = core.time.perf_counter()
            node.cook(force=True)
            times.append(core.time.perf_counter() - t0)
        hou.setFrame(current)
        return _ok(
            {
                "frames_baked": end_frame - start_frame + 1,
                "avg_cook_s": round(sum(times) / len(times), 3),
                "total_s": round(sum(times), 2),
                "cache_dir": cache_dir,
            },
            message=f"Simulation baked: {start_frame}–{end_frame}",
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
        flip_obj = dopnet.createNode("flipfluidobject", "flipfluidobject1")
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
    """Full Pyro rig: pyrosource → dopnet(pyrosolver) → output."""
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
        pyro_src = parent.createNode("pyrosource", "pyrosource1")
        pyro_src.setInput(0, src_node)
        dopnet = parent.createNode("dopnet", "pyro_dopnet")
        smoke_obj = dopnet.createNode("smokeobject", "smoke_object")
        solver = dopnet.createNode("pyrosolver", "pyrosolver1")
        solver.setInput(0, smoke_obj)
        p_div = solver.parm("divsize")
        if p_div:
            p_div.set(0.1 / resolution_scale)
        output = parent.createNode("null", "pyro_out")
        output.setInput(0, dopnet)
        parent.layoutChildren()
        return _ok(
            {
                "source": pyro_src.path(),
                "dopnet": dopnet.path(),
                "solver": solver.path(),
                "output": output.path(),
            },
            message="UNDO_TRACK: Created full Pyro rig",
        )
    except Exception:
        return _err(_tb.format_exc())


def setup_rbd_fracture(
    parent_path,
    geo_node_path,
    fracture_type="voronoi",
    num_pieces=50,
    constraint_type="glue",
):
    """Create an RBD fracture SOP and wire it to the input geometry.

    Only the SOP-side fracture is built here. Build the DOP network
    separately with create_node + connect_nodes — hardcoding DOP
    solver names here was brittle across Houdini versions.
    """
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

        try:
            parent.layoutChildren()
        except Exception:
            pass

        return _ok(
            {
                "fracture": frac.path(),
                "fracture_type": frac_type,
                "num_pieces": num_pieces,
            },
            message=(
                f"UNDO_TRACK: Created {frac_type} at {frac.path()}. "
                f"For dynamics, create a dopnet and solver with create_node."
            ),
        )
    except Exception:
        return _err(_tb.format_exc())


def get_flip_diagnostic(dopnet_path):
    """Analyse a FLIP simulation: particle count, velocity range, substeps, NaN detection."""
    try:
        _require_hou()
        dopnet = hou.node(dopnet_path)
        if not dopnet:
            return _err(f"DOP net not found: {dopnet_path}")
        diag = {"dopnet": dopnet_path, "errors": list(dopnet.errors())}
        for child in dopnet.children():
            if child.type().name() == "flipsolver":
                diag["solver"] = child.path()
                sub_p = child.parm("substeps")
                if sub_p:
                    diag["substeps"] = sub_p.eval()
            elif "flipfluidobject" in child.type().name():
                diag["fluid_object"] = child.path()
                sep_p = child.parm("particlesep")
                if sep_p:
                    diag["particle_separation"] = sep_p.eval()
        return _ok(diag)
    except Exception as e:
        return _err(str(e))
