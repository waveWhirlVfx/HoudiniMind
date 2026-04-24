# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
"""
Material and USD tools.
"""

import os as _os
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


def create_material(
    mat_name,
    shader_type="principledshader",
    base_color=(0.8, 0.8, 0.8),
    roughness=0.5,
    metallic=0.0,
):
    """Create a material in /mat with base colour, roughness, and metallic."""
    try:
        _require_hou()
        mat_net = hou.node("/mat")
        if not mat_net:
            mat_net = hou.node("/").createNode("matnet", "mat")
        mat = mat_net.createNode(shader_type, mat_name)
        for pname in ("basecolor_r", "diff_colorr", "baseColorr"):
            if mat.parm(pname):
                mat.parm(pname).set(base_color[0])
                break
        for pname, val in [
            ("rough", roughness),
            ("roughness", roughness),
            ("metallic", metallic),
            ("metal", metallic),
        ]:
            p = mat.parm(pname)
            if p:
                p.set(val)
        return _ok(
            {"material_path": mat.path(), "shader_type": shader_type},
            message=f"UNDO_TRACK: Created material {mat.path()}",
        )
    except Exception as e:
        return _err(str(e))


def assign_material(node_path, material_path, group=""):
    """Assign a material to a SOP node by inserting a Material SOP downstream."""
    try:
        _require_hou()
        node = hou.node(node_path)
        if not node:
            return _err(f"Node not found: {node_path}")
        parent = node.parent()
        mat_sop = parent.createNode("material", f"{node.name()}_material")
        mat_sop.setInput(0, node)
        p_mat = mat_sop.parm("shop_materialpath1")
        if p_mat:
            p_mat.set(material_path)
        if group:
            p_grp = mat_sop.parm("group1")
            if p_grp:
                p_grp.set(group)
        mat_sop.moveToGoodPosition()
        return _ok(
            {"material_sop": mat_sop.path(), "material": material_path, "group": group},
            message=f"UNDO_TRACK: Assigned {material_path} to {node_path}",
        )
    except Exception as e:
        return _err(str(e))


def list_materials():
    """List all materials in /mat and /shop networks."""
    try:
        _require_hou()
        mats = []
        for root_path in ["/mat", "/shop"]:
            root = hou.node(root_path)
            if not root:
                continue
            for child in root.recursiveGlob("*"):
                if child.type().category() in (
                    hou.shopNodeTypeCategory(),
                    hou.vopNodeTypeCategory(),
                ):
                    mats.append(
                        {
                            "path": child.path(),
                            "type": child.type().name(),
                            "name": child.name(),
                        }
                    )
        return _ok({"count": len(mats), "materials": mats})
    except Exception as e:
        return _err(str(e))


def setup_fabric_lookdev(
    parent_path, geo_node_path, base_color=(0.7, 0.7, 0.7), texture_path=None
):
    """Automated Fabric Lookdev: UV Flatten + Principled Shader + assignment."""
    try:
        _require_hou()
        parent = hou.node(parent_path)
        geo_node = hou.node(geo_node_path)
        if not geo_node:
            return _err(f"Geo node not found: {geo_node_path}")
        uv_node = parent.createNode("uvflatten", f"{geo_node.name()}_uvs")
        uv_node.setInput(0, geo_node)
        uv_node.moveToGoodPosition()
        mat_name = f"mat_{geo_node.name()}"
        res = create_material(
            mat_name,
            shader_type="principledshader",
            base_color=base_color,
            roughness=0.9,
            metallic=0.0,
        )
        if res["status"] != "ok":
            return res
        mat_path = res["data"]["material_path"]
        mat_node = hou.node(mat_path)
        mat_node.parm("refl_rough").set(0.9)
        if texture_path:
            mat_node.parm("basecolor_useTexture").set(True)
            mat_node.parm("basecolor_texture").set(texture_path)
        assign_res = assign_material(uv_node.path(), mat_path)
        if assign_res["status"] != "ok":
            return assign_res
        return _ok(
            {"uv_node": uv_node.path(), "material": mat_path},
            message=f"UNDO_TRACK: Fabric LookDev setup for {geo_node_path}",
        )
    except Exception as e:
        return _err(_tb.format_exc())


def create_uv_seams(node_path, mode="auto"):
    """Wrapper for UV Autoseam to prepare geometry for unwrapping."""
    try:
        _require_hou()
        node = hou.node(node_path)
        if not node:
            return _err(f"Node not found: {node_path}")
        parent = node.parent()
        seams = parent.createNode("uvautoseam", f"{node.name()}_seams")
        seams.setInput(0, node)
        seams.moveToGoodPosition()
        return _ok(
            {"path": seams.path()}, message=f"UNDO_TRACK: UV Seams created via {mode}"
        )
    except Exception as e:
        return _err(str(e))


def setup_karma_material(
    mat_name,
    base_color=None,
    roughness=0.5,
    metallic=0.0,
    emission_color=None,
    texture_path=None,
):
    """Create a Karma-native MaterialX (mtlx) material."""
    if base_color is None:
        base_color = [0.8, 0.8, 0.8]
    try:
        _require_hou()
        mat_network = hou.node("/mat") or hou.node("/").createNode("matnet", "mat")
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
        return _ok({"material_path": subnet.path()})
    except Exception as e:
        return _err(_tb.format_exc())


def setup_aov_passes(rop_path, passes=None):
    """Add render AOV passes to a Mantra or Karma ROP."""
    if passes is None:
        passes = [
            "diffuse_direct",
            "specular_direct",
            "emission",
            "shadow_matte",
            "depth",
            "crypto_object",
        ]
    try:
        _require_hou()
        rop = hou.node(rop_path)
        if not rop:
            return _err(f"ROP not found: {rop_path}")
        rop_type, added = rop.type().name().lower(), []
        try:
            if "karma" in rop_type:
                existing = rop.parm("aov_count")
                if not existing:
                    return _err("No aov_count parm.")
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
                    return _err("No vm_numaux parm.")
                base_idx = int(count_parm.eval())
                for i, p in enumerate(passes):
                    idx = base_idx + i + 1
                    count_parm.set(idx)
                    rop.parm(f"vm_channel_plane{idx}").set(p)
                    rop.parm(f"vm_variable_plane{idx}").set(p)
                    added.append(p)
            return _ok({"rop": rop_path, "added": added})
        except Exception as e:
            return _err(str(e))
    except Exception as e:
        return _err(_tb.format_exc())


def list_material_assignments(root="/obj"):
    """Scan all geometry nodes and return material assignments."""
    try:
        _require_hou()
        root_node = hou.node(root)
        if not root_node:
            return _err(f"Root not found: {root}")
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
        return _ok({"assignments": assignments})
    except Exception as e:
        return _err(str(e))


# ── USD / Solaris ─────────────────────────────────────────────────────────────


def get_usd_hierarchy(lop_node_path, max_depth=4):
    """Walk the USD stage at a LOP node and return the prim hierarchy."""
    try:
        _require_hou()
        node = hou.node(lop_node_path)
        if not node:
            return _err(f"Node not found: {lop_node_path}")
        stage = node.stage()
        if not stage:
            return _err("No USD stage — is this a LOP node?")

        def _walk(prim, depth):
            if depth > max_depth:
                return None
            entry = {
                "path": str(prim.GetPath()),
                "type": prim.GetTypeName(),
                "children": [],
            }
            for child in prim.GetChildren():
                ce = _walk(child, depth + 1)
                if ce:
                    entry["children"].append(ce)
            return entry

        root = stage.GetPseudoRoot()
        hierarchy = [_walk(c, 1) for c in root.GetChildren()]
        return _ok(
            {
                "stage_path": lop_node_path,
                "hierarchy": hierarchy,
                "root_prim_count": len(list(root.GetChildren())),
            }
        )
    except Exception as e:
        return _err(str(e))


def create_lop_node(parent_path, node_type, name=None, parms=None):
    """Create a LOP (Solaris/USD) node with alias correction and optional parms."""
    try:
        _require_hou()
        LOP_ALIASES = {
            "reference": "reference",
            "sublayer": "sublayer",
            "merge": "merge",
            "sopimport": "sopimport",
            "sceneimport": "sceneimport",
            "layoutscene": "layoutscene",
            "karma": "karmarendersettings",
            "renderproduct": "renderproduct",
        }
        canonical = LOP_ALIASES.get(node_type.lower(), node_type)
        parent = hou.node(parent_path)
        if not parent:
            return _err(f"Parent not found: {parent_path}")
        node = parent.createNode(canonical, name)
        node.moveToGoodPosition()
        if parms:
            for k, v in parms.items():
                p = node.parm(k)
                if p:
                    p.set(v)
        return _ok(
            {"path": node.path(), "type": canonical},
            message=f"UNDO_TRACK: Created LOP node {node.path()}",
        )
    except Exception as e:
        return _err(str(e))


def assign_usd_material(lop_parent_path, prim_path, material_path):
    """Add a LOP Assign Material node to bind a mtlx material to a USD prim."""
    try:
        _require_hou()
        parent = hou.node(lop_parent_path)
        if not parent:
            return _err(f"LOP parent not found: {lop_parent_path}")
        assign = parent.createNode("assignmaterial", "assign_material")
        assign.parm("primpattern").set(prim_path)
        assign.parm("matspecpath1").set(material_path)
        last = next((c for c in reversed(parent.children()) if c != assign), None)
        if last:
            assign.setInput(0, last)
        parent.layoutChildren()
        return _ok({"assign_node": assign.path()})
    except Exception as e:
        return _err(_tb.format_exc())


def get_usd_prim_attributes(lop_node_path, prim_path, frame=None):
    """Read all USD attributes on a specific prim."""
    try:
        _require_hou()
        node = hou.node(lop_node_path)
        if not node:
            return _err(f"LOP node not found: {lop_node_path}")
        if frame is not None:
            hou.setFrame(frame)
        stage = node.stage()
        if stage is None:
            return _err("Node has no USD stage.")
        prim = stage.GetPrimAtPath(prim_path)
        if not prim or not prim.IsValid():
            return _err(f"USD prim not found at '{prim_path}'.")
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
        return _ok(
            {
                "prim_path": prim_path,
                "prim_type": prim.GetTypeName(),
                "attributes": attrs,
            }
        )
    except Exception as e:
        return _err(_tb.format_exc())


def create_usd_light(
    lop_parent_path,
    light_type="rectlight",
    name="key_light",
    intensity=10.0,
    color=None,
    translate=None,
):
    """Add a USD light to a Solaris stage."""
    if color is None:
        color = [1.0, 1.0, 1.0]
    try:
        _require_hou()
        parent = hou.node(lop_parent_path)
        if not parent:
            return _err(f"LOP parent not found: {lop_parent_path}")
        lt_map = {
            "rectlight": "rectlight",
            "spherelight": "spherelight",
            "distantlight": "distantlight",
            "domelight": "domelight",
        }
        ltype = lt_map.get(light_type.lower(), light_type)
        light = parent.createNode(ltype, name)
        for p in ("intensity", "light_intensity", "xn__inputsintensity_n2a"):
            if light.parm(p):
                light.parm(p).set(intensity)
                break
        if len(color) >= 3:
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
        return _ok({"light": light.path()})
    except Exception as e:
        return _err(_tb.format_exc())


def validate_usd_stage(lop_node_path):
    """Check a USD stage for common problems."""
    try:
        _require_hou()
        node = hou.node(lop_node_path)
        if not node:
            return _err(f"LOP node not found: {lop_node_path}")
        stage = node.stage()
        if stage is None:
            return _err("Node has no USD stage.")
        errors, warnings, pcount = [], [], 0
        for prim in stage.TraverseAll():
            pcount += 1
            if not prim.GetTypeName() and not prim.IsPseudoRoot():
                warnings.append(
                    {"prim": str(prim.GetPath()), "issue": "No type defined"}
                )
        for e in node.errors():
            errors.append({"source": "lop_node", "message": str(e)})
        return _ok(
            {
                "prim_count": pcount,
                "error_count": len(errors),
                "warning_count": len(warnings),
                "errors": errors,
                "warnings": warnings[:10],
            }
        )
    except Exception as e:
        return _err(_tb.format_exc())
