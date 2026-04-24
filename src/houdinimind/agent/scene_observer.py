# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
"""
Scene Intelligence Layer for Houdini Autonomous Control System (HACS).

This module contains the SceneObserver, which acts as the 'eyes' of the agent.
It strictly observes without modifying, extracting a topology graph,
input connections, error/warning states, and semantic roles.
"""

import traceback
from typing import Dict, Any, List

try:
    import hou
    HOU_AVAILABLE = True
except ImportError:
    HOU_AVAILABLE = False
    hou = None

class SceneObserver:
    """
    Actively inspects the Houdini scene to build a snapshot for the World Model.

    Honours a `modeling_fx_only` flag by skipping /stage (Solaris/USD),
    /mat (materials), and /out (render) roots entirely — saves ~30–60% of
    scan time for the common SOP-focused workflows.

    Caches snapshots keyed on a caller-provided scene epoch (normally the
    agent's `_turn_scene_write_epoch`). When no write tool has run since the
    last observe(), the cached snapshot is returned instantly.
    """

    def __init__(self, roots: List[str] = None, modeling_fx_only: bool = False):
        if roots is not None:
            self.roots = roots
        elif modeling_fx_only:
            # Skip materials, USD, and render output — they're out of scope
            # for the modelling + FX agent and inflate the scan cost.
            self.roots = ["/obj"]
        else:
            self.roots = ["/obj", "/stage", "/mat", "/out"]
        # Limit recursive depth to avoid scanning thousands of internal nodes
        self.max_depth = 5
        self._cache_epoch = None
        self._cache_snapshot: Dict[str, Any] = None

    def invalidate_cache(self) -> None:
        self._cache_epoch = None
        self._cache_snapshot = None

    def observe(self, scene_epoch: int = None, force: bool = False) -> Dict[str, Any]:
        """
        Main entry point to perform a full scene scan and generate a snapshot.

        scene_epoch: optional monotonic counter the caller bumps on each
        scene write. When provided, observe() reuses the cached snapshot
        unless the epoch changed. Pass force=True to bypass the cache.
        """
        if not HOU_AVAILABLE:
            return {"error": "Houdini environment not available."}

        if (
            not force
            and scene_epoch is not None
            and scene_epoch == self._cache_epoch
            and self._cache_snapshot is not None
        ):
            return self._cache_snapshot

        topology = self._build_scene_graph()
        issues = self._detect_scene_issues(topology)
        semantics = self._semantic_role_inference(topology)
        context = self._get_current_context()

        snapshot = {
            "topology": topology,
            "issues": issues,
            "semantics": semantics,
            "context": context,
        }
        if scene_epoch is not None:
            self._cache_epoch = scene_epoch
            self._cache_snapshot = snapshot
        return snapshot

    def _build_scene_graph(self) -> List[Dict[str, Any]]:
        """
        Scans specified roots to map node topologies, identifying subnets and connections.
        """
        all_nodes = []
        
        def _is_hda_asset(node) -> bool:
            # True when the node is an instance of an HDA with a sealed
            # definition — its children are internals that shouldn't leak
            # into the agent's scene view.
            try:
                return node.type().definition() is not None
            except Exception:
                return False

        def scan(parent, cur_depth):
            if cur_depth > self.max_depth:
                return
            try:
                for child in parent.children():
                    inputs = []
                    try:
                        for inp in child.inputs():
                            inputs.append(inp.path() if inp else None)
                    except Exception:
                        pass

                    is_display = False
                    is_render = False
                    try:
                        is_display = child.isDisplayFlagSet()
                        is_render = child.isRenderFlagSet()
                    except Exception:
                        pass

                    all_nodes.append({
                        "path": child.path(),
                        "type": child.type().name(),
                        "inputs": inputs,
                        "display": is_display,
                        "render": is_render,
                        "node_ref": child # keep temporary ref for issue detection
                    })

                    # Report the HDA node itself but do not descend into its
                    # internals. Packing hundreds of locked child nodes into
                    # the scene summary exploded context (2% → 8%+) and
                    # produced false "orphan branch" verification failures.
                    if _is_hda_asset(child):
                        continue
                    scan(child, cur_depth + 1)
            except Exception:
                pass

        for r_path in self.roots:
            root_node = hou.node(r_path)
            if root_node:
                scan(root_node, 1)

        # Clean out the node_ref before returning the pure data structure
        clean_topology = []
        for n in all_nodes:
            clean_n = n.copy()
            clean_n.pop("node_ref", None)
            clean_topology.append(clean_n)
            
        # Re-inject the references just for internal pipeline passing
        for i, n in enumerate(all_nodes):
            clean_topology[i]["_ref"] = n.get("node_ref")
            
        return clean_topology

    def _detect_scene_issues(self, topology: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Leverages node.errors() and warnings() to detect dangling/broken states safely.
        """
        issues = []
        
        for n_data in topology:
            node = n_data.pop("_ref", None)
            if not node:
                continue
                
            errs = []
            warns = []
            
            try:
                err_tup = node.errors()
                if err_tup:
                    errs.extend(list(err_tup))
            except Exception:
                pass
                
            try:
                for i, conn in enumerate(node.inputConnectors()):
                    conn_errs = conn.errors()
                    if conn_errs:
                        errs.append(f"Input {i} ({node.inputNames()[i]}): {conn_errs[0]}")
                    elif not node.inputs()[i] and i < node.type().minInConnectors():
                        errs.append(f"Input {i} ({node.inputNames()[i]}): Missing connection.")
            except Exception:
                pass
                
            try:
                warn_tup = node.warnings()
                if warn_tup:
                    warns.extend(list(warn_tup))
            except Exception:
                pass
                
            messages = errs + warns
            if messages:
                issues.append({
                    "path": n_data["path"],
                    "type": n_data["type"],
                    "severity": "error" if errs else "warning",
                    "messages": messages
                })
                
        return issues

    def _semantic_role_inference(self, topology: List[Dict[str, Any]]) -> Dict[str, str]:
        """
        Tags nodes based on their network role via heuristics.
        """
        semantics = {}
        for n_data in topology:
            path = n_data["path"]
            ntype = n_data["type"]
            name = path.split("/")[-1].lower()
            
            role = "Operator"
            
            if "source" in name or "emitter" in name:
                role = "Source/Emitter"
            elif ntype in ["file", "null"] and ("cache" in name or ntype == "file"):
                role = "Geometry Cache"
            elif ntype == "rop_geometry" or "out" in name:
                role = "Output/Export"
            elif ntype == "dopnet":
                role = "Simulation Container"
            elif "solver" in ntype:
                role = "Simulation Solver"
            elif ntype == "geo":
                role = "Geometry Container"
            elif ntype == "cam":
                role = "Camera"
            elif ntype in ["envlight", "distantlight", "pointlight", "spotlight"]:
                role = "Light"
                
            semantics[path] = role
            
        return semantics

    def _get_current_context(self) -> Dict[str, Any]:
        """
        Evaluates the currently scoped network pane and selection.
        """
        ctx = {"path": None, "selection": []}
        try:
            pane = hou.ui.paneTabOfType(hou.paneTabType.NetworkEditor)
            if pane:
                ctx["path"] = pane.pwd().path()
                
            sel = hou.selectedNodes()
            if sel:
                ctx["selection"] = [n.path() for n in sel]
        except Exception:
            pass
            
        return ctx
