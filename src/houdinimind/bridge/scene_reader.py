# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
"""
HoudiniMind — Scene Reader v2
Deep Houdini scene snapshot for the agent.

New in v2:
  - Full connection topology (wiring map, not just input/output lists)
  - Display and render flag state per node
  - DOP network summary (active solvers, object counts)
  - USD / Solaris stage prim summary
  - Material assignments per geometry node
  - Cook-time hotspots (nodes that took longest to cook)
  - Network box groupings
  - Current selection
  - HDA presence detection
"""

import json
from collections import deque

try:
    import hou

    HOU_AVAILABLE = True
except ImportError:
    HOU_AVAILABLE = False


class SceneReader:
    def __init__(
        self,
        max_nodes: int = 300,
        max_parms_per_node: int = 50,
        include_cook_hotspots: bool = True,
        include_dop_summary: bool = True,
        include_usd_summary: bool = True,
        include_material_assignments: bool = True,
    ):
        self.max_nodes = max_nodes
        self.max_parms_per_node = max_parms_per_node
        self.include_cook_hotspots = include_cook_hotspots
        self.include_dop_summary = include_dop_summary
        self.include_usd_summary = include_usd_summary
        self.include_material_assignments = include_material_assignments

    @staticmethod
    def _safe_children(node) -> list:
        try:
            return list(node.children())
        except Exception:
            return []

    @staticmethod
    def _iter_subchildren(root, limit: int | None = None) -> list:
        direct_children = SceneReader._safe_children(root)
        if direct_children:
            result = []
            queue = deque(direct_children)
            while queue and (limit is None or len(result) < limit):
                node = queue.popleft()
                result.append(node)
                if limit is not None and len(result) >= limit:
                    continue
                for child in SceneReader._safe_children(node):
                    if limit is not None and len(result) + len(queue) >= limit:
                        break
                    queue.append(child)
            return result
        try:
            children = list(root.allSubChildren())
            return children if limit is None else children[:limit]
        except Exception:
            return []

    @staticmethod
    def _safe_type_name(node) -> str:
        try:
            return node.type().name()
        except Exception:
            return ""

    @staticmethod
    def _safe_child_category_name(node) -> str:
        try:
            child_cat = node.childTypeCategory()
            if child_cat:
                return child_cat.name()
        except Exception:
            pass
        return ""

    def _is_dop_network(self, node) -> bool:
        dop_cls = getattr(hou, "DopNetwork", None)
        if dop_cls is not None:
            try:
                if isinstance(node, dop_cls):
                    return True
            except Exception:
                pass
        type_name = self._safe_type_name(node).lower()
        if type_name == "dopnet":
            return True
        return self._safe_child_category_name(node).lower() == "dop"

    # ------------------------------------------------------------------
    # Full snapshot — returns structured dict safe to json.dumps()
    # ------------------------------------------------------------------
    def snapshot(self, root_path: str = "/") -> dict:
        if not HOU_AVAILABLE:
            return {"error": "hou not available", "nodes": []}

        root = hou.node(root_path)
        if root is None:
            return {"error": f"Node not found: {root_path}", "nodes": []}

        nodes = []
        connections = []
        network_boxes = []
        hda_nodes = []
        error_nodes = []
        cook_hotspots = []

        raw_nodes = self._iter_subchildren(root, limit=self.max_nodes)
        for node in raw_nodes:
            s = self._serialise_node(node)
            nodes.append(s)

            # Collect connections (flat list of wires)
            for inp_idx, inp_node in enumerate(node.inputs()):
                if inp_node:
                    connections.append(
                        {
                            "from": inp_node.path(),
                            "to": node.path(),
                            "to_input": inp_idx,
                        }
                    )

            if node.errors():
                error_nodes.append({"path": node.path(), "errors": list(node.errors())})

            if self.include_cook_hotspots and isinstance(node, hou.SopNode):
                try:
                    ms = node.cookTime()
                    if ms > 0.05:
                        cook_hotspots.append({"path": node.path(), "cook_ms": round(ms * 1000, 2)})
                except Exception:
                    pass

            if node.type().definition() is not None:
                hda_nodes.append({"path": node.path(), "type": node.type().name()})

        # Sort cook hotspots by time descending
        cook_hotspots.sort(key=lambda x: x["cook_ms"], reverse=True)

        # Network boxes
        seen_boxes = set()
        for parent in raw_nodes:
            try:
                parent_node = parent.parent()
                if not parent_node:
                    continue
                for box in parent_node.networkBoxes():
                    box_id = (parent_node.path(), box.name())
                    if box_id in seen_boxes:
                        continue
                    seen_boxes.add(box_id)
                    network_boxes.append(
                        {
                            "name": box.name(),
                            "comment": box.comment(),
                            "nodes": [n.path() for n in box.nodes()],
                        }
                    )
            except Exception:
                pass

        return {
            # ── Scene metadata ────────────────────────────────────────
            "houdini_version": hou.applicationVersionString(),
            "hip_file": hou.hipFile.path(),
            "hip_modified": hou.hipFile.hasUnsavedChanges(),
            "fps": hou.fps(),
            "current_frame": hou.frame(),
            "frame_range": list(hou.playbar.frameRange()),
            # ── Node inventory ────────────────────────────────────────
            "node_count": len(nodes),
            "nodes": nodes,
            # ── Wiring topology ───────────────────────────────────────
            "connections": connections,
            # ── Error summary ─────────────────────────────────────────
            "error_count": len(error_nodes),
            "error_nodes": error_nodes[:20],  # cap for token budget
            # ── Performance ───────────────────────────────────────────
            "cook_hotspots": cook_hotspots[:10],
            # ── Organisation ──────────────────────────────────────────
            "network_boxes": network_boxes[:30],
            "hda_nodes": hda_nodes,
            # ── Selection ─────────────────────────────────────────────
            "selected_nodes": [n.path() for n in hou.selectedNodes()],
            # ── Simulation summary ────────────────────────────────────
            "dop_summary": self._dop_summary(limit=self.max_nodes)
            if self.include_dop_summary
            else [],
            # ── USD / Solaris summary ─────────────────────────────────
            "usd_summary": self._usd_summary() if self.include_usd_summary else None,
            # ── Material assignments ──────────────────────────────────
            "material_assignments": self._material_assignments(limit=self.max_nodes)
            if self.include_material_assignments
            else [],
        }

    def snapshot_json(self, root_path: str = "/") -> str:
        return json.dumps(self.snapshot(root_path), indent=2, default=str)

    # ------------------------------------------------------------------
    # Node serialisation
    # ------------------------------------------------------------------
    def _serialise_node(self, node, include_all_parms: bool = False) -> dict:
        parms = {}
        parm_list = node.parms()
        limit = (
            len(parm_list) if include_all_parms else min(len(parm_list), self.max_parms_per_node)
        )

        for parm in parm_list[:limit]:
            try:
                val = parm.eval()
                if isinstance(val, (list, tuple)) and len(val) > 20:
                    val = f"<array len={len(val)}>"
                parms[parm.name()] = val
            except Exception:
                parms[parm.name()] = "<unevaluable>"

        # Full input wiring
        inputs = []
        for i, inp in enumerate(node.inputs()):
            if inp:
                inputs.append(
                    {
                        "input_index": i,
                        "from_node": inp.path(),
                        "from_type": inp.type().name(),
                    }
                )

        # Full output wiring
        outputs = []
        for out_node in node.outputs():
            outputs.append(
                {
                    "to_node": out_node.path(),
                    "to_type": out_node.type().name(),
                }
            )

        # Flags
        display_flag = False
        render_flag = False
        try:
            if hasattr(node, "isDisplayFlagSet"):
                display_flag = node.isDisplayFlagSet()
            if hasattr(node, "isRenderFlagSet"):
                render_flag = node.isRenderFlagSet()
        except Exception:
            pass

        # Cook state
        is_time_dependent = False
        try:
            is_time_dependent = node.isTimeDependent()
        except Exception:
            pass

        # Color label
        color_str = ""
        try:
            c = node.color()
            color_str = f"rgb({c.r():.2f},{c.g():.2f},{c.b():.2f})"
        except Exception:
            pass

        return {
            "path": node.path(),
            "name": node.name(),
            "type": node.type().name(),
            "category": node.type().category().name(),
            "is_bypassed": node.isBypassed() if hasattr(node, "isBypassed") else False,
            "is_displayed": display_flag,
            "is_render_flag": render_flag,
            "is_time_dependent": is_time_dependent,
            "is_hda": node.type().definition() is not None,
            "color": color_str,
            "comment": node.comment(),
            "errors": list(node.errors()),
            "warnings": list(node.warnings()),
            "inputs": inputs,
            "outputs": outputs,
            "parameters": parms,
        }

    def get_selected_nodes(self) -> list:
        if not HOU_AVAILABLE:
            return []
        return [self._serialise_node(n) for n in hou.selectedNodes()]

    def get_node_info(self, node_path: str) -> dict | None:
        if not HOU_AVAILABLE:
            return None
        node = hou.node(node_path)
        if node is None:
            return None
        return self._serialise_node(node, include_all_parms=True)

    # ------------------------------------------------------------------
    # DOP network summary
    # ------------------------------------------------------------------
    def _dop_summary(self, limit: int | None = None) -> list[dict]:
        if not HOU_AVAILABLE:
            return []
        summaries = []
        obj_root = hou.node("/obj")
        if not obj_root:
            return []
        for node in self._iter_subchildren(obj_root, limit=limit):
            if not self._is_dop_network(node):
                continue
            objects = []
            solvers = []
            try:
                objects = [o.name() for o in node.objects()][:20]
                solvers = [
                    n.type().name() for n in node.children() if "solver" in n.type().name().lower()
                ]
            except Exception:
                pass
            summaries.append(
                {
                    "path": node.path(),
                    "frame": hou.frame(),
                    "object_count": len(objects),
                    "objects": objects[:10],
                    "solvers": solvers,
                    "errors": list(node.errors()),
                }
            )
        return summaries

    # ------------------------------------------------------------------
    # USD / Solaris stage summary
    # ------------------------------------------------------------------
    def _usd_summary(self) -> dict | None:
        if not HOU_AVAILABLE:
            return None
        stage_node = hou.node("/stage")
        if not stage_node:
            return None

        prim_count = 0
        prims = []
        try:
            for child in stage_node.children()[:5]:
                prims.append({"path": child.path(), "type": child.type().name()})
            prim_count = len(list(stage_node.children()))
        except Exception:
            pass

        return {
            "prim_count": prim_count,
            "sample_prims": prims,
            "errors": list(stage_node.errors()),
        }

    # ------------------------------------------------------------------
    # Material assignments
    # ------------------------------------------------------------------
    def _material_assignments(self, limit: int | None = None) -> list[dict]:
        if not HOU_AVAILABLE:
            return []
        assignments = []
        obj_root = hou.node("/obj")
        if not obj_root:
            return []
        for node in self._iter_subchildren(obj_root, limit=limit):
            try:
                mat_parm = node.parm("shop_materialpath")
                if mat_parm:
                    mat_path = mat_parm.eval()
                    if mat_path:
                        assignments.append(
                            {
                                "node": node.path(),
                                "material": mat_path,
                            }
                        )
            except Exception:
                pass
        return assignments[:50]
