# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
"""
Smart fault repair: expert rules for solver wiring errors.
"""

from . import _core as core

_oks = core._ok
_errs = core._err
_require_hou = core._require_hou


def _find_nearby_node_by_type(node, type_name):
    parent = node.parent()
    if not parent:
        return None
    for child in parent.children():
        if child.type().name() == type_name:
            return child
    return None


def _get_flip_solver_repairs(node):
    repairs = []
    if not node.inputs()[1]:
        boundary = _find_nearby_node_by_type(node, "flipboundary")
        if boundary:
            repairs.append(
                {
                    "description": f"Connect {boundary.name()} (Volume Fluid) to {node.name()} (Initial State)",
                    "action": "connect_nodes",
                    "args": {
                        "from_path": boundary.path(),
                        "to_path": node.path(),
                        "from_out": 1,
                        "to_in": 1,
                    },
                }
            )
    if not node.inputs()[0]:
        boundary = _find_nearby_node_by_type(node, "flipboundary")
        if boundary:
            repairs.append(
                {
                    "description": f"Connect {boundary.name()} (Particle Fluid) to {node.name()} (First Input)",
                    "action": "connect_nodes",
                    "args": {
                        "from_path": boundary.path(),
                        "to_path": node.path(),
                        "from_out": 0,
                        "to_in": 0,
                    },
                }
            )
    return repairs


def _get_vellum_solver_repairs(node):
    repairs = []
    if not node.inputs()[0]:
        constraints = _find_nearby_node_by_type(node, "vellumconstraints")
        if constraints:
            repairs.append(
                {
                    "description": f"Connect {constraints.name()} to {node.name()} input 0",
                    "action": "connect_nodes",
                    "args": {
                        "from_path": constraints.path(),
                        "to_path": node.path(),
                        "from_out": 0,
                        "to_in": 0,
                    },
                }
            )
    return repairs


def _get_pyro_solver_repairs(node):
    repairs = []
    if not node.inputs()[0]:
        source = _find_nearby_node_by_type(node, "pyrosource")
        if source:
            repairs.append(
                {
                    "description": f"Connect {source.name()} to {node.name()} input 0",
                    "action": "connect_nodes",
                    "args": {
                        "from_path": source.path(),
                        "to_path": node.path(),
                        "from_out": 0,
                        "to_in": 0,
                    },
                }
            )
    return repairs


def _get_rbd_solver_repairs(node):
    repairs = []
    inputs = []
    try:
        inputs = list(node.inputs())
    except Exception:
        inputs = []
    if not inputs or not inputs[0]:
        packed = _find_nearby_node_by_type(
            node, "rbdpackedobject"
        ) or _find_nearby_node_by_type(node, "assemble")
        if packed:
            repairs.append(
                {
                    "description": f"Connect {packed.name()} to {node.name()} input 0",
                    "action": "connect_nodes",
                    "args": {
                        "from_path": packed.path(),
                        "to_path": node.path(),
                        "from_out": 0,
                        "to_in": 0,
                    },
                }
            )
    return repairs


REPAIR_STRATEGIES = {
    "flipsolver": _get_flip_solver_repairs,
    "vellumsolver": _get_vellum_solver_repairs,
    "pyrosolver": _get_pyro_solver_repairs,
    "rbdbulletsolver": _get_rbd_solver_repairs,
    "rigidbodysolver": _get_rbd_solver_repairs,
}


def suggest_node_repairs(node_path):
    """Expert-level diagnostic tool that identifies common wiring errors for solvers."""
    try:
        _require_hou()
        node = hou.node(node_path)
        if not node:
            return _errs("Node not found")
        node_type = node.type().name()
        strategy = REPAIR_STRATEGIES.get(node_type)
        if not strategy:
            return _oks(
                {"count": 0, "repairs": []},
                message=f"No smart repair rules for {node_type}",
            )
        repairs = strategy(node)
        return _oks(
            {"count": len(repairs), "repairs": repairs},
            message=f"Found {len(repairs)} smart repair suggestions for {node_type}.",
        )
    except Exception as e:
        return _errs(str(e))


try:
    import hou
except ImportError:
    hou = None
