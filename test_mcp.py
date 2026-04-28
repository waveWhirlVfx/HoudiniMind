import json
import socket
import sys


def send_cmd(method, params):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect(("127.0.0.1", 9876))
    req = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
    payload = json.dumps(req) + "\n"
    s.sendall(payload.encode("utf-8"))
    buf = b""
    while b"\n" not in buf:
        chunk = s.recv(65536)
        if not chunk:
            break
        buf += chunk
    line = buf.split(b"\n")[0]
    return json.loads(line.decode("utf-8"))


if __name__ == "__main__":
    if sys.argv[1] == "execute":
        code = sys.argv[2]
        print(json.dumps(send_cmd("execute_python", {"code": code}), indent=2))
    elif sys.argv[1] == "get_scene_info":
        print(json.dumps(send_cmd("get_scene_info", {}), indent=2))
