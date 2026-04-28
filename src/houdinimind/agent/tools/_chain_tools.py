# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
"""
Chain tools: node chains, subnets, networks, parameters, organization.
"""

import re

from . import _core as core
from . import _node_tools as nt

_ok = core._ok
_err = core._err
_require_hou = core._require_hou
_ensure_parent_exists = core._ensure_parent_exists
_normalize_node_path = core._normalize_node_path
_SOP_TYPE_ALIASES = core.SOP_TYPE_ALIASES
_set_node_parameter = nt._set_node_parameter
_infer_child_context = nt._infer_child_context

try:
    import hou

    HOU_AVAILABLE = core.HOU_AVAILABLE
except ImportError:
    HOU_AVAILABLE = False
    hou = None


def create_node_chain(parent_path, chain, cleanup_on_error=False):
    """Create and wire a sequence of nodes in one call.

    Uses a **two-pass** approach:
      Pass 1 — Create all nodes in order, set parameters & VEX.
      Pass 2 — Wire all inputs (resolves forward references).

    This fixes cases where a node references an input that is defined
    later in the chain (e.g. copytopoints referencing a scatter node
    that appears after it).
    """
    try:
        _require_hou()
        parent_path = _normalize_node_path(parent_path) or "/"
        if not _ensure_parent_exists(parent_path):
            return _err(f"Could not fulfill parent path: {parent_path}")
        parent = hou.node(parent_path)
        if not parent:
            return _err(f"Parent not found: {parent_path}")
        if not isinstance(chain, list) or not chain:
            return _err("chain must be a non-empty list of node steps")

        # Pyro safety rule: SOP Pyro Solver must receive rasterized volumes,
        # not raw source points. If an LLM builds a generic chain instead of
        # using setup_pyro_sim, insert Volume Rasterize Attributes immediately
        # before pyrosolver and pass through the same source attributes.
        normalized_chain = []
        rasterize_insertions = 0

        def _step_type(step):
            raw = step.get("type", "")
            return raw.strip().lower() if isinstance(raw, str) else ""

        def _pyro_rasterize_step(name_suffix: int, inputs=None):
            step = {
                "type": "volumerasterizeattributes",
                "name": "pyro_volume_rasterize"
                if name_suffix == 1
                else f"pyro_volume_rasterize{name_suffix}",
                "parms": {
                    "attributes": "density temperature fuel v",
                    "voxelsize": 0.05,
                },
            }
            if inputs is not None:
                step["inputs"] = inputs
            return step

        for step in chain:
            current_type = _step_type(step)
            previous_type = _step_type(normalized_chain[-1]) if normalized_chain else ""
            if current_type.startswith("pyrosolver") and not previous_type.startswith(
                "volumerasterizeattributes"
            ):
                rasterize_insertions += 1
                solver_inputs = step.get("inputs")
                raster_step = _pyro_rasterize_step(rasterize_insertions, inputs=solver_inputs)
                normalized_chain.append(raster_step)
                step = dict(step)
                step["inputs"] = [raster_step["name"]]
            normalized_chain.append(step)
        chain = normalized_chain

        # ── Point-source sanity check ─────────────────────────────────
        _FLAT_TYPES = {"grid", "line", "circle"}

        def _norm_step_type(step):
            raw = step.get("type", "")
            return raw.strip().lower() if isinstance(raw, str) else ""

        _chain_types = [_norm_step_type(s) for s in chain]
        _chain_steps_map = {_norm_step_type(s): s for s in chain if _norm_step_type(s)}
        _pt_source_warning = None
        if "copytopoints" in _chain_types:
            for _ft in _FLAT_TYPES:
                if _ft in _chain_types and _chain_types.index(_ft) < _chain_types.index(
                    "copytopoints"
                ):
                    _src_step = _chain_steps_map.get(_ft, {})
                    _src_parms = _src_step.get("parms", {})
                    _src_center = _src_parms.get("center", [0, 0, 0])
                    _src_ty = _src_parms.get("ty", 0)
                    _y_pos = (
                        _src_center[1]
                        if isinstance(_src_center, list) and len(_src_center) > 1
                        else 0
                    )
                    if abs(_y_pos) < 0.01 and abs(float(_src_ty)) < 0.01:
                        _pt_source_warning = (
                            f"NOTE: '{_src_step.get('name', _ft)}' ({_ft}) is at Y=0 and feeds "
                            f"copytopoints — all copies will be placed at ground level. "
                            f"Set the point source's center.y or ty to the intended world height, "
                            f"or use individually-placed nodes if you need a small number of objects "
                            f"at specific positions."
                        )
                    break

        parent_context = (_infer_child_context(parent) or "").strip().lower()

        # ── Pre-validation: check all node types before creating anything ──
        # Do not dry-create temporary nodes here. In a live Houdini session that
        # can dirty the scene and block the MCP caller before the real build
        # starts. Prefer child type category lookup, and skip pre-validation if
        # the host/fake object cannot provide one.
        def _valid_child_types_for(parent_node):
            try:
                child_cat = parent_node.childTypeCategory()
                if child_cat:
                    return set(child_cat.nodeTypes())
            except Exception:
                pass
            return None

        _pre_errors = []
        _validation_parent = parent
        for _si, _step in enumerate(chain, start=1):
            _raw_value = _step.get("type")
            if not isinstance(_raw_value, str) or not _raw_value.strip():
                continue
            _raw = _raw_value.strip()
            if not _raw:
                _pre_errors.append(f"Step {_si}: missing node type")
                continue
            _canonical = _SOP_TYPE_ALIASES.get(_raw.lower(), _raw)
            _valid_types = _valid_child_types_for(_validation_parent)
            if _valid_types is not None and _canonical not in _valid_types:
                _pre_errors.append(
                    f"Step {_si} ('{_step.get('name', _raw)}'): invalid node type '{_raw}'"
                )
            if (
                _validation_parent is parent
                and parent_context == "object"
                and _canonical.lower() in {"geo", "subnet"}
            ):
                _validation_parent = None
        if _pre_errors:
            return _err(
                "Chain rejected before creation — fix these node type errors first:\n"
                + "\n".join(_pre_errors)
            )

        created = []
        step_errors = []
        created_nodes = []
        active_sop_parent = None
        generators = {
            "box",
            "sphere",
            "grid",
            "tube",
            "torus",
            "platonic",
            "line",
            "circle",
            "null",
        }

        # Map from step name → created node (for forward-reference resolution)
        nodes_by_name = {}

        def _node_parent_signature(node):
            try:
                return node.parent().path()
            except Exception:
                try:
                    return node.path().rsplit("/", 1)[0]
                except Exception:
                    return None

        def _choose_step_parent(canonical_type):
            nonlocal active_sop_parent
            if parent_context != "object":
                return parent
            if active_sop_parent and canonical_type.lower() not in {"geo", "subnet"}:
                return active_sop_parent
            return parent

        # ══════════════════════════════════════════════════════════════
        # PASS 1: Create all nodes, set parameters & VEX.
        #         NO wiring happens here — just node creation.
        # ══════════════════════════════════════════════════════════════
        for step_index, step in enumerate(chain, start=1):
            raw_type = step.get("type", "")
            if not isinstance(raw_type, str) or not raw_type.strip():
                step_errors.append(
                    f"Step {step_index}: node type is required and must be a non-empty string"
                )
                continue
            raw_type = raw_type.strip()
            canonical = _SOP_TYPE_ALIASES.get(raw_type.lower(), raw_type)
            name = step.get("name")
            parms = step.get("parms", {})
            vex = step.get("vex")
            try:
                step_parent = _choose_step_parent(canonical)
                node = step_parent.createNode(canonical, name)
                created_nodes.append(node)
                node.moveToGoodPosition()

                # Set parameters
                p_cache = {"names": [p.name() for p in node.parms()]}
                parm_errors = []
                for pname, val in parms.items():
                    pr = _set_node_parameter(node, pname, val, parm_cache=p_cache)
                    msg = pr.get("message", "")
                    if pr.get("status") != "ok":
                        parm_errors.append(msg or f"parm '{pname}' failed")
                    elif "WARNING:" in msg:
                        parm_errors.append(msg)
                if parm_errors:
                    step_errors.append(
                        f"Step {step_index} '{node.name()}' parm issues: " + "; ".join(parm_errors)
                    )

                # Set VEX
                if vex:
                    vex = vex.replace("\r\n", "\n").replace("\r", "\n")
                    snippet = node.parm("snippet")
                    if snippet:
                        snippet.set(vex)
                    else:
                        step_errors.append(
                            f"Step {step_index} '{node.name()}': no snippet parm for VEX"
                        )

                info = {
                    "path": node.path(),
                    "type": canonical,
                    "name": node.name(),
                    "step_index": step_index,
                }
                created.append(info)
                nodes_by_name[node.name()] = node
                # Also register the requested name (may differ from actual name
                # if Houdini appended a number to avoid collisions).
                if name and name != node.name():
                    nodes_by_name[name] = node

                try:
                    if (
                        parent_context == "object"
                        and (_infer_child_context(node) or "").strip().lower() == "sop"
                    ):
                        active_sop_parent = node
                except Exception:
                    pass
            except Exception as step_err:
                step_errors.append(f"Step {step_index} '{raw_type}': {step_err}")

        # ══════════════════════════════════════════════════════════════
        # PASS 2: Wire all inputs.  Now every node exists, so forward
        #         references resolve correctly.
        # ══════════════════════════════════════════════════════════════
        prev_node = None
        for step_index, step in enumerate(chain, start=1):
            raw_type = step.get("type", "")
            if not isinstance(raw_type, str) or not raw_type.strip():
                continue
            canonical = _SOP_TYPE_ALIASES.get(raw_type.strip().lower(), raw_type.strip())
            name = step.get("name")
            inputs = step.get("inputs")

            # Find the node created for this step
            node = None
            if step_index <= len(created):
                node = hou.node(created[step_index - 1]["path"])
            if not node and name:
                node = nodes_by_name.get(name)
            if not node:
                continue

            try:
                if inputs is not None:
                    # Explicit inputs — resolve by name from the full created set
                    port = 0
                    for inp_name in inputs:
                        inp_node = nodes_by_name.get(inp_name)
                        if not inp_node:
                            # Also try path-based lookup
                            found_path = next(
                                (
                                    c["path"]
                                    for c in created
                                    if c["name"] == inp_name or c["path"] == inp_name
                                ),
                                None,
                            )
                            if found_path:
                                inp_node = hou.node(found_path)
                        if inp_node:
                            node.setInput(port, inp_node)
                            port += 1
                        else:
                            step_errors.append(
                                f"Step {step_index} '{node.name()}': input '{inp_name}' not found in chain"
                            )
                elif canonical == "merge" and len(created) > 0:
                    # Auto-merge: connect only earlier unconnected nodes. Pass 1 creates
                    # downstream nodes too, so scanning all created nodes can wire a future
                    # consumer back into its own upstream merge and create recursion.
                    port = 0
                    for c in created:
                        if c.get("step_index", 0) >= step_index:
                            continue
                        c_node = hou.node(c["path"])
                        if c_node and c_node != node and len(c_node.outputConnections()) == 0:
                            node.setInput(port, c_node)
                            port += 1
                elif canonical not in generators and prev_node:
                    # Auto-wire from previous node in sequence
                    prev_parent_sig = _node_parent_signature(prev_node)
                    this_parent_sig = _node_parent_signature(node)
                    if prev_parent_sig and this_parent_sig and prev_parent_sig == this_parent_sig:
                        # Only auto-wire if this node has no explicit inputs defined
                        if not node.inputConnections():
                            node.setInput(0, prev_node)
            except Exception as wire_err:
                step_errors.append(f"Step {step_index} '{node.name()}' wiring: {wire_err}")

            prev_node = node

        # ══════════════════════════════════════════════════════════════
        # POST: Cook all nodes, set display flag, layout
        # ══════════════════════════════════════════════════════════════
        for step_index, node in enumerate(created_nodes, start=1):
            try:
                node.cook(force=True)
                cook_res = list(node.errors())
                if cook_res:
                    step_errors.append(f"Step {step_index} '{node.name()}' cook failed: {cook_res}")
            except Exception as ce:
                step_errors.append(f"Step {step_index} '{node.name()}' cook exception: {ce}")

        if prev_node:
            try:
                prev_node.setDisplayFlag(True)
                prev_node.setRenderFlag(True)
            except Exception:
                pass
        parent.layoutChildren()

        payload = {
            "created": created,
            "count": len(created),
            "step_errors": step_errors,
            "partial": bool(step_errors),
            "chain_head": created[0]["path"] if created else None,
            "chain_tail": created[-1]["path"] if created else None,
        }
        if cleanup_on_error and step_errors:
            cleaned_up = []
            for n in reversed(created_nodes):
                try:
                    cleaned_up.append(n.path())
                    n.destroy()
                except Exception:
                    pass
            payload["cleaned_up"] = cleaned_up
            return {
                "status": "error",
                "message": f"Chain rolled back in {parent_path}; {len(cleaned_up)} node(s) removed. First issue: {step_errors[0]}",
                "data": payload,
            }
        if not created:
            return _err(
                f"Chain produced 0 nodes in {parent_path}. Errors: {'; '.join(step_errors)}"
            )

        # ── ch() reference audit ──────────────────────────────────────
        ch_ref_warnings = []
        for c_info in created:
            c_node = hou.node(c_info["path"])
            if not c_node:
                continue
            for p in c_node.parms():
                try:
                    raw = p.unexpandedString()
                except Exception:
                    continue
                refs = re.findall(r"ch\(['\"]\.\./([\w]+)/([\w]+)['\"]\)", raw)
                for target_node_name, target_parm_name in refs:
                    ref_node = parent.node(target_node_name)
                    if ref_node and not ref_node.parm(target_parm_name):
                        ch_ref_warnings.append(
                            f"WARNING: {c_info['path']}/{p.name()} references '{target_parm_name}' on {ref_node.path()}, but that parameter does NOT exist."
                        )
        if ch_ref_warnings:
            unique_warnings = list(dict.fromkeys(ch_ref_warnings))[:5]
            step_errors.extend(unique_warnings)
            payload["step_errors"] = step_errors
            payload["partial"] = True
            return {
                "status": "error",
                "message": f"Chain incomplete: created {len(created)}/{len(chain)} nodes in {parent_path} [{len(step_errors)} step issue(s)]",
                "data": payload,
            }
        suffix = f" [{len(step_errors)} step issue(s)]" if step_errors else ""
        if step_errors:
            return {
                "status": "error",
                "message": f"Chain incomplete: created {len(created)}/{len(chain)} nodes in {parent_path}"
                + suffix,
                "data": payload,
            }
        msg = f"UNDO_TRACK: Created {len(created)}/{len(chain)} nodes in {parent_path}" + suffix
        if _pt_source_warning:
            msg += f" | ⚠ {_pt_source_warning}"
        return _ok(payload, message=msg)
    except Exception:
        return _err(core.traceback.format_exc())


def create_subnet(parent_path, name, nodes_inside=None):
    """Create a subnet and optionally move existing nodes inside it."""
    try:
        _require_hou()
        parent = hou.node(parent_path)
        if not parent:
            return _err(f"Parent not found: {parent_path}")
        subnet = parent.createNode("subnet", name)
        subnet.moveToGoodPosition()
        moved = []
        if nodes_inside:
            nodes_to_move = [hou.node(p) for p in nodes_inside if hou.node(p)]
            if nodes_to_move:
                subnet.moveNodesToThisNetwork(nodes_to_move)
                moved = [n.path() for n in nodes_to_move]
        return _ok(
            {"subnet_path": subnet.path(), "moved_nodes": moved},
            message=f"UNDO_TRACK: Created subnet {subnet.path()}",
        )
    except Exception as e:
        return _err(str(e))


def auto_connect_chain(node_paths):
    """Connect a list of node paths in sequence (0→1→2→...)."""
    try:
        _require_hou()
        connections = []
        for i in range(1, len(node_paths)):
            src = hou.node(node_paths[i - 1])
            dst = hou.node(node_paths[i])
            if not src:
                return _err(f"Source not found: {node_paths[i - 1]}")
            if not dst:
                return _err(f"Destination not found: {node_paths[i]}")
            dst.setInput(0, src)
            connections.append(f"{src.path()} → {dst.path()}")
        return _ok(
            {"connections": connections},
            message=f"UNDO_TRACK: Chained {len(connections)} connections",
        )
    except Exception as e:
        return _err(str(e))


def promote_parameter(node_path, parm_name, label=None, target_levels=1):
    """Promote a parameter up N levels to the parent subnet with a channel reference."""
    try:
        _require_hou()
        node = hou.node(node_path)
        if not node:
            return _err(f"Node not found: {node_path}")
        parm = node.parm(parm_name)
        if not parm:
            return _err(f"Parm '{parm_name}' not found")
        parent = node.parent()
        for _ in range(target_levels - 1):
            if parent.parent():
                parent = parent.parent()
        tmpl = parm.parmTemplate()
        if label:
            tmpl.setLabel(label)
        ptg = parent.parmTemplateGroup()
        ptg.append(tmpl)
        parent.setParmTemplateGroup(ptg)
        rel_path = "../" * target_levels
        parm.setExpression(f'ch("{rel_path}{parm_name}")', hou.exprLanguage.Hscript)
        return _ok(
            {
                "promoted_to": parent.path(),
                "parm": parm_name,
                "expression_set": f'ch("{rel_path}{parm_name}")',
            },
            message=f"UNDO_TRACK: Promoted {node_path}/{parm_name} to {parent.path()}",
        )
    except Exception as e:
        return _err(str(e))


def set_node_color(node_path, r=None, g=None, b=None, color=None):
    """Set the network editor colour of a node (r/g/b in 0-1 range).
    Accepts either separate r/g/b floats or a 'color' list/string like [0.8, 0.4, 0.2].
    """
    try:
        _require_hou()
        # Tolerate model passing color as a list or stringified list
        if color is not None and (r is None or g is None or b is None):
            if isinstance(color, str):
                import ast

                color = ast.literal_eval(color)
            if isinstance(color, (list, tuple)) and len(color) >= 3:
                r, g, b = float(color[0]), float(color[1]), float(color[2])
        if r is None or g is None or b is None:
            return _err("Missing color values. Provide r, g, b floats (0-1) or color=[r,g,b].")
        node = hou.node(node_path)
        if not node:
            return _err(f"Node not found: {node_path}")
        node.setColor(hou.Color(float(r), float(g), float(b)))
        return _ok(message=f"Set color ({r},{g},{b}) on {node_path}")
    except Exception as e:
        return _err(str(e))


def set_node_comment(node_path, comment):
    """Attach a visible comment string to a node in the network editor."""
    try:
        _require_hou()
        node = hou.node(node_path)
        if not node:
            return _err(f"Node not found: {node_path}")
        node.setComment(comment)
        node.setGenericFlag(hou.nodeFlag.DisplayComment, True)
        return _ok(message=f"Comment set on {node_path}")
    except Exception as e:
        return _err(str(e))


def create_network_box(parent_path, node_paths, label="", color=(0.2, 0.2, 0.2)):
    """Create a labelled network box around a group of nodes."""
    try:
        _require_hou()
        parent = hou.node(parent_path)
        if not parent:
            return _err(f"Parent not found: {parent_path}")
        nodes = [hou.node(p) for p in node_paths if hou.node(p)]
        if not nodes:
            return _err("No valid nodes found")
        netbox = parent.createNetworkBox()
        netbox.setComment(label)
        netbox.setColor(hou.Color(*color))
        for n in nodes:
            netbox.addNode(n)
        netbox.fitAroundContents()
        return _ok(
            {"label": label, "nodes_boxed": len(nodes)},
            message=f"Network box '{label}' created around {len(nodes)} nodes",
        )
    except Exception as e:
        return _err(str(e))


def create_bed_controls(parent_path, name="BED_CONTROLS"):
    """Create a control null with master parameters for procedural bedding."""
    try:
        _require_hou()
        parent = hou.node(parent_path)
        if not parent:
            return _err(f"Parent not found: {parent_path}")
        ctrl = parent.createNode("null", name)
        ctrl.setGenericFlag(hou.nodeFlag.Display, False)
        ptg = ctrl.parmTemplateGroup()
        ptg.addParmTemplate(hou.FloatParmTemplate("width", "Bed Width", 1, default_value=([1.6])))
        ptg.addParmTemplate(hou.FloatParmTemplate("length", "Bed Length", 1, default_value=([2.2])))
        ptg.addParmTemplate(
            hou.FloatParmTemplate("mattress_h", "Mattress Height", 1, default_value=([0.35]))
        )
        ptg.addParmTemplate(
            hou.FloatParmTemplate("duvet_padding", "Duvet Padding", 1, default_value=([0.15]))
        )
        ctrl.setParmTemplateGroup(ptg)
        ctrl.setUserData("nodeshape", "circle")
        ctrl.setColor(hou.Color(0.2, 0.6, 1.0))
        ctrl.moveToGoodPosition()
        return _ok(
            {"path": ctrl.path()},
            message=f"UNDO_TRACK: Bed Control node created: {ctrl.path()}",
        )
    except Exception as e:
        return _err(str(e))


def layout_network(parent_path):
    """Auto-layout all children in a network using Houdini's built-in layoutChildren()."""
    try:
        _require_hou()
        parent = hou.node(parent_path)
        if not parent:
            return _err(f"Node not found: {parent_path}")
        parent.layoutChildren()
        return _ok(message=f"Network laid out: {parent_path}")
    except Exception as e:
        return _err(str(e))


def add_sticky_note(parent_path, text, x=0.0, y=0.0, width=3.0, height=1.5):
    """Add an annotating sticky note to a network at the given position."""
    try:
        _require_hou()
        parent = hou.node(parent_path)
        if not parent:
            return _err(f"Parent not found: {parent_path}")
        note = parent.createStickyNote()
        note.setText(text)
        note.setPosition(hou.Vector2(x, y))
        note.setSize(hou.Vector2(width, height))
        return _ok(message=f"Sticky note added to {parent_path}: {text[:40]}")
    except Exception as e:
        return _err(str(e))


def add_spare_parameters(node_path, params):
    """Dynamically add new custom parameters to a node."""
    try:
        _require_hou()
        node = hou.node(node_path)
        if not node:
            return _err(f"Node not found: {node_path}")
        group = node.parmTemplateGroup()
        for p in params:
            name = p.get("name")
            label = p.get("label", name.capitalize())
            p_type = p.get("type", "float").lower()
            default = p.get("default", 1.0)
            template = None
            if p_type == "float":
                template = hou.FloatParmTemplate(name, label, 1, default_value=(float(default),))
            elif p_type == "int":
                template = hou.IntParmTemplate(name, label, 1, default_value=(int(default),))
            elif p_type == "toggle":
                template = hou.ToggleParmTemplate(name, label, default_value=bool(default))
            elif p_type == "string":
                template = hou.StringParmTemplate(name, label, 1, default_value=(str(default),))
            elif p_type == "color":
                template = hou.FloatParmTemplate(
                    name,
                    label,
                    3,
                    default_value=(0.8, 0.8, 0.8),
                    look=hou.parmLook.Color,
                )
            if template:
                if "min" in p or "max" in p:
                    template.setMinValue(p.get("min", 0.0))
                    template.setMaxValue(p.get("max", 10.0))
                if group.find(name):
                    group.replace(name, template)
                else:
                    group.append(template)
        node.setParmTemplateGroup(group)
        return _ok(
            {"count": len(params)},
            message=f"Added {len(params)} spare parameters to {node.name()}",
        )
    except Exception as e:
        return _err(str(e))
