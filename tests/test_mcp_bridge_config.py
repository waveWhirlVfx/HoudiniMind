import errno
import importlib
import socket


def test_bridge_unwraps_json_rpc_result(monkeypatch):
    import houdinimind.agent.mcp_bridge as bridge_mod

    class _Socket:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def settimeout(self, timeout):
            self.timeout = timeout

        def connect(self, address):
            self.address = address

        def sendall(self, payload):
            self.payload = payload

        def recv(self, _size):
            if getattr(self, "_sent", False):
                return b""
            self._sent = True
            return b'{"jsonrpc":"2.0","id":1,"result":{"status":"ok","message":"pong"}}'

    monkeypatch.setattr(bridge_mod.socket, "socket", lambda *_args, **_kwargs: _Socket())

    assert bridge_mod.call_houdini("ping", {}) == {"status": "ok", "message": "pong"}


def test_bridge_unwraps_json_rpc_error(monkeypatch):
    import houdinimind.agent.mcp_bridge as bridge_mod

    class _Socket:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def settimeout(self, timeout):
            self.timeout = timeout

        def connect(self, address):
            self.address = address

        def sendall(self, payload):
            self.payload = payload

        def recv(self, _size):
            if getattr(self, "_sent", False):
                return b""
            self._sent = True
            return b'{"jsonrpc":"2.0","id":1,"error":{"code":-32601,"message":"missing"}}'

    monkeypatch.setattr(bridge_mod.socket, "socket", lambda *_args, **_kwargs: _Socket())

    result = bridge_mod.call_houdini("missing", {})

    assert result["status"] == "error"
    assert result["message"] == "missing"
    assert result["error"]["code"] == -32601


def test_houdini_server_uses_env_host_and_port(monkeypatch):
    monkeypatch.setenv("HOUDINIMIND_MCP_HOST", "127.0.0.2")
    monkeypatch.setenv("HOUDINIMIND_MCP_PORT", "7433")

    import houdinimind.agent.mcp_houdini_server as server_mod

    server = server_mod.MCPHoudiniServer()

    assert server.host == "127.0.0.2"
    assert server.port == 7433
    assert server.ws_port == 7434


def test_houdini_server_invalid_env_port_falls_back(monkeypatch):
    monkeypatch.setenv("HOUDINIMIND_MCP_PORT", "not-a-port")

    import houdinimind.agent.mcp_houdini_server as server_mod

    importlib.reload(server_mod)
    server = server_mod.MCPHoudiniServer()

    assert server.port == server_mod.DEFAULT_MCP_PORT


def test_houdini_server_starts_without_websockets(monkeypatch):
    import houdinimind.agent.mcp_houdini_server as server_mod

    monkeypatch.setattr(server_mod, "websockets", None)
    monkeypatch.setattr(server_mod, "HOU_AVAILABLE", False)

    server = server_mod.MCPHoudiniServer(port=0)
    msg = server.start()
    try:
        assert msg.startswith("MCP Houdini Server started on")
        assert "WS on" not in msg
        assert server.running is True
        assert server._ws_thread is None
    finally:
        server.stop()


def test_houdini_server_reports_existing_responsive_server(monkeypatch):
    import houdinimind.agent.mcp_houdini_server as server_mod

    class _Socket:
        def setsockopt(self, *_args):
            pass

        def bind(self, *_args):
            raise OSError(errno.EADDRINUSE, "Address already in use")

        def close(self):
            pass

    monkeypatch.setattr(server_mod.socket, "socket", lambda *_args, **_kwargs: _Socket())
    monkeypatch.setattr(server_mod, "_ping_existing_server", lambda *_args, **_kwargs: True)

    server = server_mod.MCPHoudiniServer(port=9876)
    msg = server.start()

    assert "already running on 127.0.0.1:9876" in msg
    assert server.running is False


def test_ping_existing_server_accepts_json_rpc_ping():
    import houdinimind.agent.mcp_houdini_server as server_mod

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    host, port = listener.getsockname()

    def _serve_once():
        client, _addr = listener.accept()
        with client:
            client.recv(4096)
            client.sendall(b'{"jsonrpc":"2.0","id":null,"result":{"status":"ok","message":"pong"}}')
        listener.close()

    import threading

    thread = threading.Thread(target=_serve_once, daemon=True)
    thread.start()
    try:
        assert server_mod._ping_existing_server(host, port) is True
    finally:
        thread.join(timeout=2.0)
