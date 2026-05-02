# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
"""
World Model Layer for Houdini Autonomous Control System (HACS).

This module manages the persistent internal representation of the Houdini scene,
storing the scene topology, context scope, detected issues, and semantic roles.
"""

import json
import time
from typing import Any


class WorldModel:
    def __init__(self):
        self.last_update_time: float = 0.0
        self.topology: list[dict[str, Any]] = []
        self.issues: list[dict[str, Any]] = []
        self.semantics: dict[str, str] = {}
        self.context: dict[str, Any] = {}

        # History string used for diff tracking
        self.previous_snapshot_str: str | None = None
        self.current_snapshot_str: str | None = None

    def update(self, observer_snapshot: dict[str, Any]) -> None:
        """
        Ingest the observation data and update the live model.
        """
        self.last_update_time = time.time()
        self.topology = observer_snapshot.get("topology", [])
        self.issues = observer_snapshot.get("issues", [])
        self.semantics = observer_snapshot.get("semantics", {})
        self.context = observer_snapshot.get("context", {})

        self.previous_snapshot_str = self.current_snapshot_str
        self.current_snapshot_str = json.dumps(observer_snapshot, sort_keys=True)

    def update_from_scene_snapshot(self, snapshot: dict[str, Any]) -> None:
        """Translate a SceneReader snapshot into WorldModel shape and ingest.

        Avoids a second full scene scan via SceneObserver when we already have
        a fresh SceneReader snapshot — the two carry the same information in
        different shapes.
        """
        if not snapshot:
            return
        topology: list[dict[str, Any]] = []
        semantics: dict[str, str] = {}
        for nd in snapshot.get("nodes", []) or []:
            path = nd.get("path", "")
            ntype = nd.get("type", "")
            inputs = []
            for inp in nd.get("inputs", []) or []:
                if isinstance(inp, dict):
                    inputs.append(inp.get("from_node"))
                else:
                    inputs.append(inp)
            topology.append(
                {
                    "path": path,
                    "type": ntype,
                    "inputs": inputs,
                    "display": bool(nd.get("is_displayed", False)),
                    "render": bool(nd.get("is_render_flag", False)),
                }
            )
            semantics[path] = self._infer_role(path, ntype)

        issues = []
        for err in snapshot.get("error_nodes", []) or []:
            issues.append(
                {
                    "path": err.get("path", ""),
                    "type": "error",
                    "severity": "error",
                    "messages": list(err.get("errors", []) or []),
                }
            )

        observer_shape = {
            "topology": topology,
            "issues": issues,
            "semantics": semantics,
            "context": {
                "path": None,
                "selection": list(snapshot.get("selected_nodes", []) or []),
            },
        }
        self.update(observer_shape)

    @staticmethod
    def _infer_role(path: str, ntype: str) -> str:
        name = path.rsplit("/", maxsplit=1)[-1].lower()
        if "source" in name or "emitter" in name:
            return "Source/Emitter"
        if ntype in {"file", "null"} and ("cache" in name or ntype == "file"):
            return "Geometry Cache"
        if ntype == "rop_geometry" or "out" in name:
            return "Output/Export"
        if ntype == "dopnet":
            return "Simulation Container"
        if "solver" in ntype:
            return "Simulation Solver"
        if ntype == "geo":
            return "Geometry Container"
        if ntype == "cam":
            return "Camera"
        if ntype in {"envlight", "distantlight", "pointlight", "spotlight"}:
            return "Light"
        return "Operator"

    def to_prompt_context(self) -> str:
        """
        Produce a compressed representation of the Houdini World to inject into the Mission Planner prompt.
        """
        if not self.topology:
            return "Houdini scene is empty or not yet observed."

        lines = ["[WORLD MODEL STATE]"]

        # Context
        if self.context.get("path"):
            lines.append(f"Current Context: {self.context['path']}")
        if self.context.get("selection"):
            lines.append(f"Selected Nodes: {', '.join(self.context['selection'])}")

        # Topology
        lines.append(f"\nScene Topology ({len(self.topology)} nodes):")
        for node in self.topology:
            path = node.get("path", "")
            ntype = node.get("type", "")
            role = self.semantics.get(path, "Unknown")
            flag = ""
            if node.get("display"):
                flag = " [DISPLAY]"
            elif node.get("render"):
                flag = " [RENDER]"

            inputs = ""
            if node.get("inputs"):
                ins = [
                    f"in{i}:{p.split('/')[-1] if p else 'None'}"
                    for i, p in enumerate(node["inputs"])
                ]
                inputs = f" | Inputs: {', '.join(ins)}"

            lines.append(f" - {path} ({ntype}) [Role: {role}]{flag}{inputs}")

        # Issues
        if self.issues:
            lines.append(f"\nDetected Scene Issues ({len(self.issues)}):")
            for issue in self.issues:
                sev = issue.get("severity", "error").upper()
                lines.append(
                    f" - [{sev}] {issue['path']} ({issue['type']}): {', '.join(issue['messages'])}"
                )
        else:
            lines.append("\nDetected Scene Issues: None")

        return "\n".join(lines)

    # ── Query API ─────────────────────────────────────────────────────
    # Used by the agent's planner / tool selection logic. Cheap O(N) scans
    # over `self.topology` — the world model is small enough that indexing
    # would be overkill.

    def has_node(self, path: str) -> bool:
        return any(node.get("path") == path for node in self.topology)

    def find_by_type(self, ntype: str) -> list[str]:
        ntype_l = ntype.lower()
        return [
            node["path"]
            for node in self.topology
            if str(node.get("type", "")).lower() == ntype_l and node.get("path")
        ]

    def find_by_role(self, role: str) -> list[str]:
        role_l = role.lower()
        return [path for path, r in self.semantics.items() if str(r).lower() == role_l]

    def display_outputs(self) -> list[str]:
        return [node["path"] for node in self.topology if node.get("display")]

    def render_outputs(self) -> list[str]:
        return [node["path"] for node in self.topology if node.get("render")]

    def error_paths(self) -> list[str]:
        return [
            issue.get("path", "")
            for issue in self.issues
            if issue.get("severity") in {"error", "fatal"} and issue.get("path")
        ]

    def has_errors(self) -> bool:
        return any(issue.get("severity") in {"error", "fatal"} for issue in self.issues)

    def is_empty(self) -> bool:
        return not self.topology

    def derive_tool_hints(self) -> list[str]:
        """Return a small list of (tool, reason) hints inferred from world state.

        Consumed by AgentLoop as a system-message hint so the LLM gets
        observation-grounded suggestions before the first tool call. Returns
        plain strings (already formatted) — keep the list compact (≤4) so
        we don't bloat the prompt.
        """
        hints: list[str] = []
        if self.is_empty():
            hints.append(
                "World model: scene is empty — start with create_node or "
                "create_node_chain inside /obj before any read/verify tools."
            )
            return hints
        if self.has_errors():
            err_sample = self.error_paths()[:3]
            hints.append(
                "World model: scene has errors at "
                + ", ".join(err_sample)
                + " — run get_all_errors / deep_error_trace before further edits."
            )
        if not self.display_outputs():
            hints.append(
                "World model: no display flag is set — call set_display_flag or "
                "finalize_sop_network on the intended output before claiming completion."
            )
        sources = self.find_by_role("Source/Emitter")
        sims = self.find_by_role("Simulation Container") + self.find_by_role("Simulation Solver")
        if sources and not sims:
            hints.append(
                f"World model: source(s) {sources[:2]} present but no simulation "
                "container/solver — wire them into a dopnet or pop/pyro/flip solver."
            )
        return hints[:4]

    def diff_scene(self) -> dict[str, Any]:
        """
        Compare the previous snapshot to the current snapshot to identify new nodes,
        deleted nodes, and resolved issues.
        """
        if not self.previous_snapshot_str or not self.current_snapshot_str:
            return {"added": [], "removed": [], "new_issues": [], "resolved_issues": []}

        prev_data = json.loads(self.previous_snapshot_str)
        curr_data = json.loads(self.current_snapshot_str)

        prev_paths = {n["path"] for n in prev_data.get("topology", [])}
        curr_paths = {n["path"] for n in curr_data.get("topology", [])}

        added = list(curr_paths - prev_paths)
        removed = list(prev_paths - curr_paths)

        prev_issues = {i["path"]: i["messages"] for i in prev_data.get("issues", [])}
        curr_issues = {i["path"]: i["messages"] for i in curr_data.get("issues", [])}

        new_issues = []
        for p, msgs in curr_issues.items():
            if p not in prev_issues or msgs != prev_issues[p]:
                new_issues.append({"path": p, "messages": msgs})

        resolved_issues = [p for p in prev_issues if p not in curr_issues]

        return {
            "added": added,
            "removed": removed,
            "new_issues": new_issues,
            "resolved_issues": resolved_issues,
        }
