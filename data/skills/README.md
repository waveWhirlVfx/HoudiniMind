# HoudiniMind User Skills

Place custom skill `.py` files here. Each file must export a `register()` function.

## Minimal example

```python
def my_tool(node_path: str) -> dict:
    return {"status": "ok", "message": "done", "data": {"node": node_path}}

def register():
    return {
        "name": "my_skill",
        "version": "1.0",
        "description": "A custom skill",
        "tools": {
            "my_tool": my_tool,
        },
        "schemas": [
            {
                "type": "function",
                "function": {
                    "name": "my_tool",
                    "description": "Does something custom",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "node_path": {"type": "string", "description": "Houdini node path"}
                        },
                        "required": ["node_path"]
                    }
                }
            }
        ],
    }
```

Skills are loaded automatically at panel startup. Hot-reload via `/skill reload <name>` (coming soon).
