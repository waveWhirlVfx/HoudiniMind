import os
import sys

sys.path.append(os.path.join(os.getcwd(), "src"))
from houdinimind.agent import mcp_houdini_server

print(f"Ping result: {mcp_houdini_server._ping_existing_server('127.0.0.1', 9876)}")
