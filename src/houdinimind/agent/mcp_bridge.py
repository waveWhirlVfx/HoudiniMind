# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
"""
HoudiniMind — MCP Bridge v2

FastMCP-based bridge that exposes all HoudiniMind tools to
MCP-compatible clients (Gemini CLI, Claude Desktop, Cursor, VS Code).

Architecture:
  [MCP Client] --(stdio/SSE)--> [This Bridge] --(TCP)--> [Houdini MCP Server]

Transports:
  - stdio (default): For Gemini CLI, Claude Desktop, Cursor
  - sse: For remote/web-based clients

New in v2:
  - Proper type annotations for all tools
  - Scene context resource
  - System prompt resource
  - Health/ping tool
  - SSE transport support
  - Robust error handling
"""

import inspect
import json
import logging
import os
import socket
import sys
import traceback

# Ensure all logs go to stderr to avoid corrupting JSON-RPC stdout stream
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("mcp_bridge")

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    logger.error("FastMCP not installed. Run: pip install fastmcp\nOr: pip install 'mcp[cli]'")
    sys.exit(1)

DEFAULT_HOUDINI_HOST = "127.0.0.1"
DEFAULT_HOUDINI_PORT = 9876


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name, "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        logger.warning("Ignoring invalid integer for %s: %r", name, value)
        return default


# Configuration
HOUDINI_HOST = os.environ.get("HOUDINI_HOST") or os.environ.get(
    "HOUDINIMIND_MCP_HOST", DEFAULT_HOUDINI_HOST
)
HOUDINI_PORT = _env_int("HOUDINI_PORT", _env_int("HOUDINIMIND_MCP_PORT", DEFAULT_HOUDINI_PORT))
HOUDINIMIND_MCP_TOKEN = os.environ.get("HOUDINIMIND_MCP_TOKEN", "").strip()
MCP_TRANSPORT = os.environ.get("MCP_TRANSPORT", "stdio")  # "stdio" or "sse"
MCP_SSE_PORT = int(os.environ.get("MCP_SSE_PORT", 8765))

# Add project root to path to import TOOL_SCHEMAS
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.append(ROOT)

try:
    from houdinimind.agent.tools import TOOL_SCHEMAS
except ImportError:
    logger.warning("Could not import TOOL_SCHEMAS. Falling back to empty list.")
    TOOL_SCHEMAS = []

# Load system prompt for context resource
SYSTEM_PROMPT_PATH = os.path.join(ROOT, "data", "system_prompt_base.txt")


# ══════════════════════════════════════════════════════════════════════
#  FastMCP Server Setup
# ══════════════════════════════════════════════════════════════════════

mcp = FastMCP(
    "HoudiniMind",
    instructions=(
        "AI agent bridge for SideFX Houdini. "
        "Provides 100+ tools for scene inspection, node creation, "
        "simulation setup, material management, USD/Solaris operations, "
        "and more."
    ),
)


# ══════════════════════════════════════════════════════════════════════
#  TCP Communication with Houdini
# ══════════════════════════════════════════════════════════════════════


def call_houdini(method: str, params: dict, timeout: float = 30.0) -> dict:
    """Send a request to the Houdini TCP server and return the result."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect((HOUDINI_HOST, HOUDINI_PORT))
            request = {"method": method, "params": params}
            if HOUDINIMIND_MCP_TOKEN:
                request["auth"] = HOUDINIMIND_MCP_TOKEN
            payload = json.dumps(request)
            s.sendall(payload.encode("utf-8"))

            # Receive response (up to 10MB for large geometry data)
            chunks = []
            while True:
                chunk = s.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)

            response_data = b"".join(chunks).decode("utf-8")
            if not response_data:
                return {"status": "error", "message": "No response from Houdini."}
            response = json.loads(response_data)
            if isinstance(response, dict) and "jsonrpc" in response:
                if "error" in response:
                    error = response.get("error") or {}
                    return {
                        "status": "error",
                        "message": error.get("message", "Houdini returned a JSON-RPC error."),
                        "error": error,
                    }
                result = response.get("result")
                return result if isinstance(result, dict) else {"status": "ok", "result": result}
            return response
    except ConnectionRefusedError:
        return {
            "status": "error",
            "message": (
                f"Connection refused at {HOUDINI_HOST}:{HOUDINI_PORT}. "
                "Is the MCP server running in Houdini? "
                "(Use 'Houdini Agent > Toggle MCP Server')"
            ),
        }
    except TimeoutError:
        return {
            "status": "error",
            "message": f"Timeout ({timeout}s) waiting for Houdini response.",
        }
    except Exception as e:
        return {"status": "error", "message": f"Bridge error: {e!s}"}


def check_houdini_connection() -> bool:
    """Quick ping to check if Houdini is reachable."""
    result = call_houdini("ping", {}, timeout=15.0)
    return result.get("status") == "ok"


# ══════════════════════════════════════════════════════════════════════
#  MCP Resources (context for the LLM)
# ══════════════════════════════════════════════════════════════════════


@mcp.resource("houdini://scene/summary")
def get_scene_context() -> str:
    """Current Houdini scene summary — nodes, connections, and status."""
    result = call_houdini("get_scene_summary", {}, timeout=10.0)
    if result.get("status") == "error":
        return f"Scene unavailable: {result.get('message', 'unknown error')}"
    return json.dumps(result, indent=2, default=str)


@mcp.resource("houdini://agent/system-prompt")
def get_system_prompt() -> str:
    """The HoudiniMind agent system prompt with execution rules."""
    try:
        if os.path.exists(SYSTEM_PROMPT_PATH):
            with open(SYSTEM_PROMPT_PATH, encoding="utf-8") as f:
                return f.read()
    except Exception:
        pass
    return "HoudiniMind system prompt not found."


# ══════════════════════════════════════════════════════════════════════
#  Built-in Tools
# ══════════════════════════════════════════════════════════════════════


@mcp.tool()
def houdini_ping() -> str:
    """Check if Houdini is running and the MCP server is active."""
    result = call_houdini("ping", {}, timeout=15.0)
    if result.get("status") == "ok":
        return "✅ Houdini is connected and ready."
    return f"❌ Houdini is not reachable: {result.get('message', 'unknown')}"


@mcp.tool()
def houdini_tool_list() -> str:
    """List all available Houdini tools with their descriptions."""
    tools = []
    for schema in TOOL_SCHEMAS:
        func = schema.get("function", {})
        name = func.get("name", "")
        desc = func.get("description", "")
        if name:
            tools.append(f"• {name}: {desc[:80]}")
    return f"Available tools ({len(tools)}):\n" + "\n".join(tools)


# ══════════════════════════════════════════════════════════════════════
#  Dynamic Tool Registration
# ══════════════════════════════════════════════════════════════════════

# Map JSON schema types to Python type annotations
_TYPE_MAP = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}


def register_tools():
    """Dynamically register all TOOL_SCHEMAS as MCP tools."""
    count = 0
    registered = set()

    for schema in TOOL_SCHEMAS:
        func_info = schema.get("function", {})
        name = func_info.get("name")
        if not name or name in registered:
            continue

        description = func_info.get("description", f"Houdini tool: {name}")
        parameters = func_info.get("parameters", {}).get("properties", {})
        required = set(func_info.get("parameters", {}).get("required", []))

        # Build function with proper signature
        def make_tool(tool_name, tool_params, tool_required):
            async def tool_wrapper(**kwargs):
                # Determine timeout based on tool type
                timeout = 30.0
                if any(kw in tool_name for kw in ("render", "bake", "cache", "cook", "sim")):
                    timeout = 120.0

                result = call_houdini(tool_name, kwargs, timeout=timeout)

                # Format result for readability
                if isinstance(result, dict):
                    return json.dumps(result, indent=2, default=str)
                return str(result)

            # Build proper signature for FastMCP
            params = []
            for p_name, p_info in tool_params.items():
                p_type = _TYPE_MAP.get(p_info.get("type", "string"), str)

                if p_name in tool_required:
                    default = inspect.Parameter.empty
                else:
                    default = p_info.get("default", None)

                params.append(
                    inspect.Parameter(
                        p_name,
                        inspect.Parameter.KEYWORD_ONLY,
                        default=default,
                        annotation=p_type,
                    )
                )

            tool_wrapper.__signature__ = inspect.Signature(params, return_annotation=str)
            tool_wrapper.__doc__ = description
            return tool_wrapper

        try:
            wrapper = make_tool(name, parameters, required)
            mcp.tool(name=name, description=description)(wrapper)
            registered.add(name)
            count += 1
        except Exception as e:
            logger.error(f"Failed to register tool {name}: {e}")

    logger.info(f"Registered {count} Houdini tools from TOOL_SCHEMAS.")


# ══════════════════════════════════════════════════════════════════════
#  Entry Point
# ══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    try:
        register_tools()

        transport = MCP_TRANSPORT.lower()
        if transport == "sse":
            logger.info(f"Starting MCP Bridge (SSE) on port {MCP_SSE_PORT}...")
            mcp.run(transport="sse", sse_port=MCP_SSE_PORT)
        else:
            logger.info("Starting MCP Bridge (stdio)...")
            mcp.run(transport="stdio")
    except KeyboardInterrupt:
        logger.info("MCP Bridge stopped.")
    except Exception as e:
        logger.error(f"MCP Bridge failed: {e}\n{traceback.format_exc()}")
        sys.exit(1)
