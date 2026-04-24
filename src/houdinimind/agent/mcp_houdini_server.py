# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
import socket
import json
import threading
import traceback
import os
import sys
import asyncio
import websockets
import time
from concurrent.futures import ThreadPoolExecutor


try:
    import hou
    import hdefereval
    HOU_AVAILABLE = True
except ImportError:
    HOU_AVAILABLE = False

# Add current project to sys.path if not there
HOUDINIMIND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if HOUDINIMIND_ROOT not in sys.path:
    sys.path.append(HOUDINIMIND_ROOT)

from houdinimind.agent.tools import TOOL_FUNCTIONS, TOOL_SAFETY_TIERS

class MCPHoudiniServer:
    def __init__(self, host='127.0.0.1', port=9876):
        self.host = host
        self.port = port
        self.auth_token = os.environ.get("HOUDINIMIND_MCP_TOKEN", "").strip()
        self.allow_dangerous = os.environ.get("HOUDINIMIND_MCP_ALLOW_DANGEROUS", "").strip() == "1"
        self.ws_port = port + 1
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
                # Force close by connecting to it
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.5)
                s.connect((self.host, self.port))
                s.close()
            except Exception:
                pass
            self.server_socket.close()
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
            async with websockets.serve(ws_handler, self.host, self.ws_port):
                await asyncio.Future()  # Run forever

        self._ws_loop.run_until_complete(_run_ws())

    def broadcast_event(self, category, data):
        """Broadcasts an event to all connected WebSocket clients."""
        if not self._ws_loop or not self._ws_clients:
            return
            
        # Standard MCP notification style
        payload = json.dumps({"jsonrpc": "2.0", "method": f"notifications/{category}", "params": data})
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
            except Exception:
                if self.running:
                    print(traceback.format_exc())

    def _handle_client(self, client_socket, addr=None):
        try:
            # FIX-13: Add timeout to prevent zombie connections from leaked recvs
            client_socket.settimeout(45.0) 
            data = client_socket.recv(1024 * 1024).decode('utf-8')
            if not data:
                return
            
            try:
                request = json.loads(data)
            except json.JSONDecodeError:
                self._send_error(client_socket, None, -32700, "Parse error")
                return

            req_id = request.get("id")
            method = request.get("method")
            params = request.get("params", {})
            auth = request.get("auth") or request.get("token") or params.get("auth") or params.get("token")
            if self.auth_token and auth != self.auth_token:
                self._send_error(client_socket, req_id, -32001, "Unauthorized MCP request")
                return

            # MCP standard method: listTools
            if method == "listTools" or method == "tools/list":
                tools = self._get_mcp_tools()
                self._send_response(client_socket, req_id, {"tools": tools})
                return

            # MCP standard method: callTool
            if method == "callTool" or method == "tools/call":
                tool_name = params.get("name")
                tool_args = params.get("arguments", {})
                self._execute_tool_and_respond(client_socket, req_id, tool_name, tool_args)
                return

            # Legacy/Shortcut compatibility
            if not method:
                method = request.get("type")
            
            if method == "ping":
                self._send_response(client_socket, req_id, {"status": "ok", "message": "pong"})
            elif method in TOOL_FUNCTIONS:
                self._execute_tool_and_respond(client_socket, req_id, method, params)
            else:
                self._send_error(client_socket, req_id, -32601, f"Method '{method}' not found")

        except Exception as e:
            self._send_error(client_socket, None, -32603, f"Internal error: {str(e)}")
        finally:
            client_socket.close()

    def _get_mcp_tools(self):
        """Convert TOOL_SCHEMAS to MCP-compliant tool definitions."""
        from houdinimind.agent.tools import TOOL_SCHEMAS
        mcp_tools = []
        for schema in TOOL_SCHEMAS:
            func = schema.get("function", {})
            mcp_tools.append({
                "name": func.get("name"),
                "description": func.get("description"),
                "inputSchema": func.get("parameters", {"type": "object", "properties": {}})
            })
        return mcp_tools

    def _execute_tool_and_respond(self, client_socket, req_id, tool_name, params):
        if tool_name not in TOOL_FUNCTIONS:
            self._send_error(client_socket, req_id, -32601, f"Tool '{tool_name}' not found")
            return
        safety = TOOL_SAFETY_TIERS.get(tool_name, "safe")
        if safety in {"confirm", "dangerous"} and not self.allow_dangerous:
            self._send_error(
                client_socket,
                req_id,
                -32002,
                f"Tool '{tool_name}' requires UI confirmation and is disabled over MCP by default.",
                {"safety": safety},
            )
            return

        try:
            def _run():
                return TOOL_FUNCTIONS[tool_name](**params)
            
            if HOU_AVAILABLE:
                result = hdefereval.executeInMainThreadWithResult(_run)
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
                is_error = (status != "ok")
            else:
                content.append({"type": "text", "text": json.dumps(result, indent=2)})

            self._send_response(client_socket, req_id, {
                "content": content,
                "isError": is_error
            })
            # Safety Throttle: 5ms pause to allow Houdini main loop to breathe
            if HOU_AVAILABLE:
                time.sleep(0.005)
        except Exception as e:

            self._send_error(client_socket, req_id, -32603, str(e), {"traceback": traceback.format_exc()})

    def _send_response(self, client_socket, req_id, result):
        response = {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": result
        }
        client_socket.sendall(json.dumps(response).encode('utf-8'))

    def _send_error(self, client_socket, req_id, code, message, data=None):
        error = {"code": code, "message": message}
        if data:
            error["data"] = data
        response = {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": error
        }
        client_socket.sendall(json.dumps(response).encode('utf-8'))

# Global instance for easy access from Houdini UI
_server_instance = None

def toggle_server(port=9876):
    global _server_instance
    if _server_instance and _server_instance.running:
        msg = _server_instance.stop()
        _server_instance = None
        return msg
    else:
        _server_instance = MCPHoudiniServer(port=port)
        return _server_instance.start()

def is_server_running():
    global _server_instance
    return _server_instance and _server_instance.running
