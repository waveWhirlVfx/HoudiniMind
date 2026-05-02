"""
HoudiniMind — Tool preconditions.

Lightweight pre-call checks that prevent whole classes of failures:
  - Tool wants a node path that doesn't exist in the scene.
  - Tool needs a parent that isn't the right network type.
  - Tool needs displayed geometry but the scene is empty.

Checks are intentionally cheap: argument-shape validation plus look-ups in
the most recent scene snapshot. We never call Houdini synchronously here —
the dispatcher is already on a hot path.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PreconditionResult:
    ok: bool
    severity: str = "block"  # "block" | "warn"
    message: str = ""
    suggested_fix: str = ""

    @classmethod
    def passed(cls) -> PreconditionResult:
        return cls(ok=True)

    @classmethod
    def block(cls, message: str, suggested_fix: str = "") -> PreconditionResult:
        return cls(ok=False, severity="block", message=message, suggested_fix=suggested_fix)

    @classmethod
    def warn(cls, message: str, suggested_fix: str = "") -> PreconditionResult:
        return cls(ok=False, severity="warn", message=message, suggested_fix=suggested_fix)


# Args that name an existing node by path.
_EXISTING_NODE_ARGS = (
    "node_path",
    "parent_path",
    "dopnet_path",
    "target_node",
    "camera_path",
    "src_node",
    "dst_node",
    "from_node",
    "to_node",
)

# Tools that explicitly CREATE the node named by their path arg —
# checking existence would be wrong (and would block creation).
_CREATION_TOOLS = frozenset(
    {
        "create_node",
        "create_subnet",
        "create_node_chain",
        "create_network_box",
        "create_lop_node",
        "create_bed_controls",
        "convert_to_hda",
        "convert_network_to_hda",
        "setup_fabric_lookdev",
    }
)

# Tools that need at least one displayed geometry node in the scene.
_NEEDS_DISPLAYED_GEOMETRY = frozenset(
    {
        "render_quad_views",
        "render_scene_view",
        "render_with_camera",
    }
)


def _node_paths_from_snapshot(snapshot: dict | None) -> set[str]:
    if not snapshot:
        return set()
    paths: set[str] = set()
    for node in snapshot.get("nodes") or []:
        path = node.get("path")
        if isinstance(path, str):
            paths.add(path)
    return paths


def _has_displayed_geometry(snapshot: dict | None) -> bool:
    if not snapshot:
        return False
    for node in snapshot.get("nodes") or []:
        if node.get("is_displayed"):
            return True
        # SceneReader may store the flag under different keys depending on version.
        flags = node.get("flags") or {}
        if flags.get("display") or flags.get("displayed"):
            return True
    return False


def _coerce_path(value) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _check_paths_exist(tool_name: str, args: dict, known_paths: set[str]) -> PreconditionResult:
    """For args naming existing nodes, ensure they're in the snapshot."""
    if tool_name in _CREATION_TOOLS:
        return PreconditionResult.passed()

    missing: list[tuple[str, str]] = []
    for key in _EXISTING_NODE_ARGS:
        path = _coerce_path(args.get(key))
        if not path:
            continue
        # If we have no snapshot we can't be confident — pass through.
        if not known_paths:
            return PreconditionResult.passed()
        # Allow root and well-known parents without a hit in the snapshot.
        if path in {"/", "/obj", "/out", "/stage", "/mat"}:
            continue
        if path not in known_paths:
            missing.append((key, path))

    if not missing:
        return PreconditionResult.passed()

    detail = ", ".join(f"{k}={p!r}" for k, p in missing)
    suggestion = (
        "Call get_scene_summary to confirm current node paths, "
        "then retry with a path that actually exists."
    )
    return PreconditionResult.block(
        f"Precondition: node path not found ({detail}).",
        suggested_fix=suggestion,
    )


def _check_displayed_geometry(tool_name: str, snapshot: dict | None) -> PreconditionResult:
    if tool_name not in _NEEDS_DISPLAYED_GEOMETRY:
        return PreconditionResult.passed()
    if snapshot is None:
        # No snapshot, no info — let it run.
        return PreconditionResult.passed()
    if _has_displayed_geometry(snapshot):
        return PreconditionResult.passed()
    return PreconditionResult.block(
        f"Precondition: {tool_name} needs at least one displayed geometry node, "
        "but the scene has none.",
        suggested_fix="Build or display geometry first, then re-render.",
    )


def _check_required_strings(tool_name: str, args: dict) -> PreconditionResult:
    """Catch obviously-empty required string args before shipping to Houdini."""
    # connect_nodes needs both endpoints.
    if tool_name == "connect_nodes":
        for k in ("from_node", "to_node"):
            if not _coerce_path(args.get(k)):
                return PreconditionResult.block(
                    f"Precondition: connect_nodes requires non-empty {k}.",
                    suggested_fix="Provide both from_node and to_node as full paths.",
                )
    # set_parameter / safe_set_parameter need a parm name.
    if tool_name in {"set_parameter", "safe_set_parameter"}:
        if not _coerce_path(args.get("parm_name") or args.get("parameter")):
            return PreconditionResult.block(
                f"Precondition: {tool_name} requires a parameter name.",
                suggested_fix="Pass parm_name (e.g. 'tx', 'scale').",
            )
    return PreconditionResult.passed()


def evaluate(
    tool_name: str,
    args: dict,
    *,
    scene_snapshot: dict | None = None,
) -> PreconditionResult:
    """Run all preconditions for ``tool_name`` against ``args``.

    Returns the first blocking failure, otherwise the first warning, otherwise pass.
    """
    args = dict(args or {})
    known_paths = _node_paths_from_snapshot(scene_snapshot)

    checks = (
        _check_required_strings(tool_name, args),
        _check_paths_exist(tool_name, args, known_paths),
        _check_displayed_geometry(tool_name, scene_snapshot),
    )

    blocking = next((c for c in checks if not c.ok and c.severity == "block"), None)
    if blocking is not None:
        return blocking
    warning = next((c for c in checks if not c.ok and c.severity == "warn"), None)
    if warning is not None:
        return warning
    return PreconditionResult.passed()


def format_failure(result: PreconditionResult) -> str:
    """Render a precondition failure for the LLM tool-result channel."""
    out = result.message
    if result.suggested_fix:
        out += f" Hint: {result.suggested_fix}"
    return out
