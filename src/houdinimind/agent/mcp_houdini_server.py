# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
import asyncio
import json
import os
import socket
import sys
import threading
import time
import traceback
from concurrent.futures import Future, ThreadPoolExecutor

import websockets

try:
    import hdefereval
    import hou

    HOU_AVAILABLE = True
except ImportError:
    HOU_AVAILABLE = False

# Add current project to sys.path if not there
HOUDINIMIND_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
if HOUDINIMIND_ROOT not in sys.path:
    sys.path.append(HOUDINIMIND_ROOT)

DEFAULT_MCP_HOST = "127.0.0.1"
DEFAULT_MCP_PORT = 9876


def _env_int(name, default):
    value = os.environ.get(name, "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        print(f"HoudiniMind: Ignoring invalid integer for {name}: {value!r}")
        return default


def _default_host():
    return os.environ.get("HOUDINIMIND_MCP_HOST", DEFAULT_MCP_HOST)


def _default_port():
    return _env_int("HOUDINIMIND_MCP_PORT", DEFAULT_MCP_PORT)


class MCPHoudiniServer:
    def __init__(self, host=None, port=None):
        self.host = host or _default_host()
        self.port = port if port is not None else _default_port()
        self.auth_token = os.environ.get("HOUDINIMIND_MCP_TOKEN", "").strip()
        self.allow_dangerous = os.environ.get("HOUDINIMIND_MCP_ALLOW_DANGEROUS", "").strip() == "1"
        self.ws_port = self.port + 1
        self.server_socket = None
        self.running = False
        self._thread = None
        self._ws_thread = None
        self._ws_clients = set()
        self._ws_loop = None
        self.event_hooks = None
        self._executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="mcp-client")

    def start(self):
        if self.running:
            return "Server is already running."

        try:
            print(f"HoudiniMind: Starting MCP Server on {self.host}:{self.port}...")
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(5)
            # Use a small timeout so we can check self.running and exit the thread gracefully
            self.server_socket.settimeout(1.0)
            self.running = True

            # Start TCP MCP thread
            self._thread = threading.Thread(target=self._listen_loop, daemon=True)
            self._thread.start()

            # Start WebSocket thread
            self._ws_thread = threading.Thread(target=self._ws_server_thread, daemon=True)
            self._ws_thread.start()

            # Register EventHooks
            try:
                from houdinimind.bridge.event_hooks import EventHooks

                self.event_hooks = EventHooks(on_event=self.broadcast_event)
                self.event_hooks.register()
                print("HoudiniMind: EventHooks registered for WebSocket push.")
            except Exception as eh:
                print(f"HoudiniMind: Failed to register EventHooks: {eh}")

            msg = f"MCP Houdini Server started on {self.host}:{self.port} (WS on {self.ws_port})"
            print(f"HoudiniMind: {msg}")
            return msg
        except Exception as e:
            err_msg = f"Failed to start server: {e}"
            print(f"HoudiniMind: ERROR: {err_msg}")
            return err_msg

    def stop(self):
        self.running = False
        self._executor.shutdown(wait=False)
        if self.event_hooks:
            try:
                self.event_hooks.unregister()
            except Exception:
                pass

        if self._ws_loop:
            self._ws_loop.call_soon_threadsafe(self._ws_loop.stop)

        if self.server_socket:
            try:
                self.server_socket.close()
            except Exception:
                pass
        print("HoudiniMind: MCP Server stopped.")
        return "MCP Houdini Server stopped."

    def _ws_server_thread(self):
        # Bypass Houdini's custom event loop (haio) which is main-thread-only
        asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())
        self._ws_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._ws_loop)

        async def ws_handler(ws):
            self._ws_clients.add(ws)
            try:
                async for _ in ws:
                    pass  # Keep connection alive
            finally:
                self._ws_clients.discard(ws)

        async def _run_ws():
            try:
                async with websockets.serve(ws_handler, self.host, self.ws_port):
                    await asyncio.Future()  # Run forever
            except asyncio.CancelledError:
                pass

        try:
            self._ws_loop.run_until_complete(_run_ws())
        except Exception:
            # Ignore errors during shutdown
            pass
        finally:
            self._ws_loop.close()

    def broadcast_event(self, category, data):
        """Broadcasts an event to all connected WebSocket clients."""
        if not self._ws_loop or not self._ws_clients:
            return

        # Standard MCP notification style
        payload = json.dumps(
            {"jsonrpc": "2.0", "method": f"notifications/{category}", "params": data}
        )
        for ws in list(self._ws_clients):
            try:
                asyncio.run_coroutine_threadsafe(ws.send(payload), self._ws_loop)
            except Exception:
                pass

    def _listen_loop(self):
        while self.running:
            try:
                client_socket, addr = self.server_socket.accept()
                if not self.running:
                    client_socket.close()
                    break

                # FIX-12: Handle each client via thread pool to bound concurrency
                self._executor.submit(self._handle_client, client_socket, addr)
            except TimeoutError:
                # This is expected, allows loop to check self.running
                continue
            except Exception:
                if self.running:
                    # Ignore errors during shutdown
                    try:
                        print(traceback.format_exc())
                    except Exception:
                        pass

    def _handle_client(self, client_socket, addr=None):
        try:
            # FIX-13: Add timeout to prevent zombie connections from leaked recvs
            client_socket.settimeout(45.0)
            buf = b""
            request = None
            max_bytes = 16 * 1024 * 1024
            while len(buf) < max_bytes:
                chunk = client_socket.recv(65536)
                if not chunk:
                    break
                buf += chunk
                newline_idx = buf.find(b"\n")
                candidate = buf[:newline_idx] if newline_idx >= 0 else buf
                try:
                    request = json.loads(candidate.decode("utf-8"))
                    break
                except (UnicodeDecodeError, json.JSONDecodeError):
                    if newline_idx >= 0:
                        self._send_error(client_socket, None, -32700, "Parse error")
                        return
                    continue
            if request is None:
                if buf:
                    self._send_error(client_socket, None, -32700, "Parse error")
                return

            req_id = request.get("id")
            method = request.get("method")
            params = request.get("params", {})
            auth = (
                request.get("auth")
                or request.get("token")
                or params.get("auth")
                or params.get("token")
            )
            if self.auth_token and auth != self.auth_token:
                self._send_error(client_socket, req_id, -32001, "Unauthorized MCP request")
                return

            # MCP standard method: listTools
            if method in {"listTools", "tools/list"}:
                tools = self._get_mcp_tools()
                self._send_response(client_socket, req_id, {"tools": tools})
                return

            # MCP standard method: callTool
            if method in {"callTool", "tools/call"}:
                tool_name = params.get("name")
                tool_args = params.get("arguments", {})
                self._execute_tool_and_respond(client_socket, req_id, tool_name, tool_args)
                return

            if method in {"batch", "tools/batch"}:
                calls = params.get("calls", [])
                if not isinstance(calls, list):
                    self._send_error(
                        client_socket, req_id, -32602, "Batch params.calls must be a list"
                    )
                    return
                results = []
                for index, call in enumerate(calls):
                    if not isinstance(call, dict):
                        results.append(
                            {
                                "index": index,
                                "error": {
                                    "code": -32602,
                                    "message": "Batch call entry must be an object",
                                },
                            }
                        )
                        continue
                    tool_name = call.get("name") or call.get("method")
                    tool_args = call.get("arguments", call.get("params", {}))
                    result = self._execute_tool_payload(tool_name, tool_args)
                    result["index"] = index
                    result["name"] = tool_name
                    results.append(result)
                self._send_response(client_socket, req_id, {"results": results})
                return

            # Legacy/Shortcut compatibility
            if not method:
                method = request.get("type")

            if method == "ping":
                self._send_response(client_socket, req_id, {"status": "ok", "message": "pong"})
            else:
                from houdinimind.agent.tools import TOOL_FUNCTIONS

                if method in TOOL_FUNCTIONS:
                    self._execute_tool_and_respond(client_socket, req_id, method, params)
                else:
                    self._send_error(client_socket, req_id, -32601, f"Method '{method}' not found")

        except Exception as e:
            self._send_error(client_socket, None, -32603, f"Internal error: {e!s}")
        finally:
            client_socket.close()

    def _get_mcp_tools(self):
        """Convert TOOL_SCHEMAS to MCP-compliant tool definitions."""
        from houdinimind.agent.tools import TOOL_SCHEMAS

        mcp_tools = []
        for schema in TOOL_SCHEMAS:
            func = schema.get("function", {})
            mcp_tools.append(
                {
                    "name": func.get("name"),
                    "description": func.get("description"),
                    "inputSchema": func.get("parameters", {"type": "object", "properties": {}}),
                }
            )
        return mcp_tools

    def _execute_tool_and_respond(self, client_socket, req_id, tool_name, params):
        result = self._execute_tool_payload(tool_name, params)
        if "error" in result:
            error = result["error"]
            self._send_error(
                client_socket,
                req_id,
                error.get("code", -32603),
                error.get("message", "Tool failed"),
                error.get("data"),
            )
            return
        self._send_response(client_socket, req_id, result["result"])

    # Per-tool execution timeout (seconds). Keeps the MCP thread from blocking
    # forever when Houdini's main thread is busy cooking or stuck.
    # Override with env var HOUDINIMIND_TOOL_TIMEOUT.
    _TOOL_TIMEOUT_S: int = _env_int("HOUDINIMIND_TOOL_TIMEOUT", 90)

    def _execute_tool_payload(self, tool_name, params):
        from houdinimind.agent.tools import TOOL_FUNCTIONS, TOOL_SAFETY_TIERS

        if tool_name not in TOOL_FUNCTIONS:
            return {"error": {"code": -32601, "message": f"Tool '{tool_name}' not found"}}
        safety = TOOL_SAFETY_TIERS.get(tool_name, "safe")
        if safety in {"confirm", "dangerous"} and not self.allow_dangerous:
            return {
                "error": {
                    "code": -32002,
                    "message": (
                        f"Tool '{tool_name}' requires UI confirmation and is disabled over MCP by default."
                    ),
                    "data": {"safety": safety},
                }
            }

        try:
            if not isinstance(params, dict):
                return {"error": {"code": -32602, "message": "Tool params must be an object"}}

            def _run():
                return TOOL_FUNCTIONS[tool_name](**params)

            if HOU_AVAILABLE:
                # Use executeDeferred (non-blocking enqueue) + Future so we can
                # apply a timeout. executeInMainThreadWithResult blocks the MCP
                # thread indefinitely if Houdini is busy cooking, which makes
                # the whole session appear hung.
                fut: Future = Future()
                cancelled = {"flag": False}

                def _run_deferred():
                    if cancelled["flag"]:
                        return
                    try:
                        fut.set_result(_run())
                    except BaseException as _exc:
                        if not fut.done():
                            fut.set_exception(_exc)

                hdefereval.executeDeferred(_run_deferred)
                try:
                    result = fut.result(timeout=self._TOOL_TIMEOUT_S)
                except TimeoutError:
                    cancelled["flag"] = True
                    return {
                        "error": {
                            "code": -32504,
                            "message": (
                                f"Tool '{tool_name}' timed out after {self._TOOL_TIMEOUT_S}s. "
                                "Houdini's main thread is busy or cooking. "
                                "Retry after the current operation finishes, or set "
                                "HOUDINIMIND_TOOL_TIMEOUT to a higher value."
                            ),
                        }
                    }
            else:
                result = _run()

            # Normalize response for MCP
            content = []
            is_error = False

            if isinstance(result, dict) and "status" in result:
                status = result.get("status")
                msg = result.get("message", "")
                data = result.get("data", {})

                text_out = f"Status: {status}\nMessage: {msg}"
                if data:
                    text_out += f"\nData: {json.dumps(data, indent=2)}"

                content.append({"type": "text", "text": text_out})
                is_error = status != "ok"
            else:
                content.append({"type": "text", "text": json.dumps(result, indent=2)})

            # Brief yield so Houdini's event loop can repaint between consecutive
            # tool calls. Configurable via HOUDINIMIND_MCP_YIELD_MS — set to 0
            # to disable the yield entirely (useful for high-throughput batch clients).
            if HOU_AVAILABLE:
                yield_ms = _env_int("HOUDINIMIND_MCP_YIELD_MS", 50)
                if yield_ms > 0:
                    time.sleep(yield_ms / 1000.0)
            return {"result": {"content": content, "isError": is_error}}
        except Exception as e:
            return {
                "error": {
                    "code": -32603,
                    "message": str(e),
                    "data": {"traceback": traceback.format_exc()},
                }
            }

    def _send_response(self, client_socket, req_id, result):
        response = {"jsonrpc": "2.0", "id": req_id, "result": result}
        try:
            client_socket.sendall(json.dumps(response).encode("utf-8"))
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def _send_error(self, client_socket, req_id, code, message, data=None):
        error = {"code": code, "message": message}
        if data:
            error["data"] = data
        response = {"jsonrpc": "2.0", "id": req_id, "error": error}
        try:
            client_socket.sendall(json.dumps(response).encode("utf-8"))
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass


# Global instance for easy access from Houdini UI
_server_instance = None


def toggle_server(port=None):
    global _server_instance
    if _server_instance and _server_instance.running:
        msg = _server_instance.stop()
        _server_instance = None
        return msg
    else:
        # Clear cached tool modules so the new server always picks up the
        # latest TOOL_FUNCTIONS / TOOL_SCHEMAS on its first tool call.
        import sys

        stale = [k for k in sys.modules if k.startswith("houdinimind.agent.tools")]
        for k in stale:
            del sys.modules[k]
        _server_instance = MCPHoudiniServer(port=port)
        return _server_instance.start()


def is_server_running():
    global _server_instance
    return _server_instance and _server_instance.running
