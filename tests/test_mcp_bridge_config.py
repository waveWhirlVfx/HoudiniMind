import importlib


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
