# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
"""
HoudiniMind — PDG / TOPs Integration Tools
Workflow orchestration for batch caching, rendering, and data processing.
"""

from . import _core as core


def create_top_network(parent_path: str = "/obj", name: str = "topnet1") -> dict:
    """Create a TOP network (topnet) for PDG workflow orchestration."""
    core._require_hou()
    parent = core._hou.node(parent_path)
    if not parent:
        return core._err(f"Parent not found: {parent_path}")
    try:
        topnet = parent.createNode("topnet", name)
        topnet.moveToGoodPosition()
        return core._ok(
            {
                "path": topnet.path(),
                "message": f"Created TOP network: {topnet.path()}",
            }
        )
    except Exception as e:
        return core._err(str(e))


def create_top_node(
    parent_path: str, node_type: str, name: str = None, parms: dict = None
) -> dict:
    """Create a node inside a TOP network (e.g. pythonscript, filecache, ropfetch)."""
    core._require_hou()
    parent = core._hou.node(parent_path)
    if not parent:
        return core._err(f"Parent not found: {parent_path}")
    try:
        node = (
            parent.createNode(node_type, name) if name else parent.createNode(node_type)
        )
        if parms:
            for k, v in parms.items():
                p = node.parm(k)
                if p:
                    p.set(v)
        node.moveToGoodPosition()
        return core._ok({"path": node.path(), "type": node_type})
    except Exception as e:
        return core._err(str(e))


def submit_pdg_cook(top_node_path: str, mode: str = "blocking") -> dict:
    """Cook a PDG graph from the specified TOP node."""
    core._require_hou()
    node = core._hou.node(top_node_path)
    if not node:
        return core._err(f"Node not found: {top_node_path}")
    try:
        topnet = node
        while topnet and not isinstance(topnet.type().definition(), type(None)):
            if topnet.type().name() == "topnet":
                break
            topnet = topnet.parent()

        if not topnet:
            topnet = node.parent()

        pdg_node = node.getPDGNode()
        if not pdg_node:
            return core._err(
                "Node has no PDG representation. Is it inside a TOP network?"
            )

        context = topnet.getPDGGraphContext()
        if not context:
            return core._err("No PDG graph context found.")

        if mode == "blocking":
            context.cookNode(pdg_node, blocking=True)
            return core._ok({"message": f"PDG cook completed for {top_node_path}"})
        else:
            context.cookNode(pdg_node, blocking=False)
            return core._ok(
                {"message": f"PDG cook started (async) for {top_node_path}"}
            )
    except Exception as e:
        return core._err(str(e))


def get_pdg_work_items(top_node_path: str) -> dict:
    """List work items and their states for a TOP node."""
    core._require_hou()
    node = core._hou.node(top_node_path)
    if not node:
        return core._err(f"Node not found: {top_node_path}")
    try:
        pdg_node = node.getPDGNode()
        if not pdg_node:
            return core._err("Node has no PDG representation.")

        items = []
        for wi in pdg_node.workItems:
            items.append(
                {
                    "id": wi.id,
                    "name": wi.name,
                    "state": str(wi.state).split(".")[-1],
                    "frame": wi.frame if hasattr(wi, "frame") else None,
                }
            )
            if len(items) >= 100:
                break
        return core._ok({"work_items": items, "count": len(items)})
    except Exception as e:
        return core._err(str(e))


def create_file_cache_top(
    parent_path: str, sop_path: str, cache_dir: str = "$HIP/cache"
) -> dict:
    """Create a File Cache TOP that caches geometry from a SOP path."""
    core._require_hou()
    parent = core._hou.node(parent_path)
    if not parent:
        return core._err(f"Parent not found: {parent_path}")
    try:
        fc = parent.createNode("filecache", "filecache_auto")
        fc.parm("soppath").set(sop_path)
        if fc.parm("basedir"):
            fc.parm("basedir").set(cache_dir)
        fc.moveToGoodPosition()
        return core._ok(
            {
                "path": fc.path(),
                "sop_path": sop_path,
                "cache_dir": cache_dir,
            }
        )
    except Exception as e:
        return core._err(str(e))


def create_python_script_top(
    parent_path: str, code: str, name: str = "pyscript1"
) -> dict:
    """Create a Python Script TOP that executes custom code per work item."""
    core._require_hou()
    parent = core._hou.node(parent_path)
    if not parent:
        return core._err(f"Parent not found: {parent_path}")
    try:
        node = parent.createNode("pythonscript", name)
        if node.parm("script"):
            node.parm("script").set(code)
        elif node.parm("python"):
            node.parm("python").set(code)
        node.moveToGoodPosition()
        return core._ok({"path": node.path(), "code_length": len(code)})
    except Exception as e:
        return core._err(str(e))
