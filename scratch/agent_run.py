import json
import re
import socket


def call_mcp(method, params):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(10)
            s.connect(("127.0.0.1", 9876))
            request = {"method": method, "params": params}
            s.sendall(json.dumps(request).encode("utf-8"))

            chunks = []
            while True:
                chunk = s.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)

            response_data = b"".join(chunks).decode("utf-8")
            full_res = json.loads(response_data)

            # MCP format check
            if "result" in full_res:
                result = full_res["result"]
                if isinstance(result, dict) and "content" in result:
                    text = result["content"][0]["text"]
                    # Extract Data block if present
                    match = re.search(r"Data:\s*(\{.*\})", text, re.DOTALL)
                    if match:
                        return {"status": "ok", "data": json.loads(match.group(1))}
                    return {"status": "ok", "message": text}
                return result
            return full_res
    except Exception as e:
        return {"status": "error", "message": str(e)}


def build_bridge():
    print("Agent: Starting Bridge Construction via MCP...")

    # 1. Setup Geo
    res = call_mcp(
        "create_node", {"parent_path": "/obj", "node_type": "geo", "name": "procedural_bridge"}
    )
    if res.get("status") != "ok" or "data" not in res:
        print(f"Error creating Geo: {res}")
        return
    geo_path = res["data"]["path"]

    def set_p(path, parm, val):
        return call_mcp("set_parameter", {"node_path": path, "parm_name": parm, "value": val})

    def conn(src, dst, idx=0):
        return call_mcp(
            "connect_nodes", {"output_node": src, "input_node": dst, "input_index": idx}
        )

    # 2. Peak A
    peak_a = call_mcp(
        "create_node", {"parent_path": geo_path, "node_type": "grid", "name": "peak_a"}
    )["data"]["path"]
    set_p(peak_a, "tx", -10)

    mtn_a = call_mcp(
        "create_node", {"parent_path": geo_path, "node_type": "mountain::2.0", "name": "mtn_a"}
    )["data"]["path"]
    conn(peak_a, mtn_a)
    set_p(mtn_a, "height", 10)

    # 3. Peak B
    peak_b = call_mcp(
        "create_node", {"parent_path": geo_path, "node_type": "grid", "name": "peak_b"}
    )["data"]["path"]
    set_p(peak_b, "tx", 10)

    mtn_b = call_mcp(
        "create_node", {"parent_path": geo_path, "node_type": "mountain::2.0", "name": "mtn_b"}
    )["data"]["path"]
    conn(peak_b, mtn_b)
    set_p(mtn_b, "height", 10)

    # 4. Bridge Span
    line = call_mcp(
        "create_node", {"parent_path": geo_path, "node_type": "line", "name": "bridge_span"}
    )["data"]["path"]
    set_p(line, "points", 50)
    set_p(line, "dist", 20)
    set_p(line, "tx", -10)
    set_p(line, "dirx", 1)
    set_p(line, "diry", 0)

    span_vex = call_mcp(
        "create_node",
        {"parent_path": geo_path, "node_type": "attribwrangle", "name": "catenary_logic"},
    )["data"]["path"]
    conn(line, span_vex)
    set_p(
        span_vex,
        "snippet",
        """
float t = (float)@ptnum / (@numpt-1);
@P.y = 10.0 - 4.0 * 4.0 * t * (1.0 - t);
""",
    )

    # 5. Cables
    cable_sweep = call_mcp(
        "create_node", {"parent_path": geo_path, "node_type": "sweep", "name": "cable_mesh"}
    )["data"]["path"]
    conn(span_vex, cable_sweep)
    set_p(cable_sweep, "surfaceshape", 3)
    set_p(cable_sweep, "width", 1.5)

    # 6. Assembly
    merge = call_mcp(
        "create_node", {"parent_path": geo_path, "node_type": "merge", "name": "BRIDGE_OUT"}
    )["data"]["path"]
    conn(mtn_a, merge, 0)
    conn(mtn_b, merge, 1)
    conn(cable_sweep, merge, 2)

    call_mcp(
        "execute_python",
        {"code": f"hou.node('{merge}').setDisplayFlag(True); hou.node('{merge}').cook()"},
    )
    print("Agent: Bridge Construction Complete.")


if __name__ == "__main__":
    build_bridge()
