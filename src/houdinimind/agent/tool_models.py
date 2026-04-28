# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
"""
HoudiniMind — Pydantic Tool Validation v1

Provides BaseModel definitions for tool arguments with automatic validation.
When the LLM sends malformed tool arguments, the validation error is captured
and fed back to the model for self-correction.
"""

import json
import re
from typing import Any

# ── Lightweight validation (no Pydantic dependency required) ──────────
# We use a schema-driven validator that works with the existing JSON schemas
# rather than requiring Pydantic as a hard dependency (Houdini's Python
# environment may not have it installed).


class ToolArgumentError(ValueError):
    """Raised when tool arguments fail validation."""

    def __init__(self, tool_name: str, errors: list[str], hint: str = ""):
        self.tool_name = tool_name
        self.errors = errors
        self.hint = hint
        msg = f"Invalid args for '{tool_name}': {'; '.join(errors)}"
        if hint:
            msg += f"\nHint: {hint}"
        super().__init__(msg)


class ToolValidator:
    """
    Validates tool call arguments against their JSON schemas.
    Zero external dependencies — works in vanilla Python.
    """

    def __init__(self, tool_schemas: list):
        self._schemas: dict[str, dict] = {}
        for schema in tool_schemas:
            func = schema.get("function", {})
            name = func.get("name", "")
            if name:
                self._schemas[name] = func.get("parameters", {})

    def validate(self, tool_name: str, args: dict) -> dict:
        """
        Validate and coerce tool arguments.
        Returns the cleaned arguments dict.
        Raises ToolArgumentError on validation failure.
        """
        args = self._normalize_common_aliases(tool_name, dict(args or {}))

        # Handle common LLM hallucinations
        if tool_name in {"connect", "connect_nodes"}:
            if tool_name == "connect":
                tool_name = "connect_nodes"
            if "source_node" in args and "from_path" not in args:
                args["from_path"] = args.pop("source_node")
            if "source_node_path" in args and "from_path" not in args:
                args["from_path"] = args.pop("source_node_path")
            if "target_node" in args and "to_path" not in args:
                args["to_path"] = args.pop("target_node")
            if "target_node_path" in args and "to_path" not in args:
                args["to_path"] = args.pop("target_node_path")
            tool_name = "connect_nodes"
            if "from_node" in args and "from_path" not in args:
                args["from_path"] = args.pop("from_node")
            if "to_node" in args and "to_path" not in args:
                args["to_path"] = args.pop("to_node")
            if "output_index" in args and "from_out" not in args:
                args["from_out"] = args.pop("output_index")
            if "input_index" in args and "to_in" not in args:
                args["to_in"] = args.pop("input_index")
            # If the user tries to map ports differently, we ignore them or append to path.
            if "from_output" in args:
                from_path = args.get("from_path", "")
                if ":" not in from_path and args["from_output"]:
                    args["from_path"] = f"{from_path}:0"  # naive fallback
            if "to_input" in args:
                to_path = args.get("to_path", "")
                if ":" not in to_path and args["to_input"]:
                    args["to_path"] = f"{to_path}:0"  # naive fallback

        schema = self._schemas.get(tool_name)
        if not schema:
            return args  # no schema → pass through

        properties = schema.get("properties", {})
        required = set(schema.get("required", []))
        errors = []

        if tool_name == "create_node":
            if "type" in args and "node_type" not in args:
                args["node_type"] = args.pop("type")
            if not str(args.get("node_type", "") or "").strip():
                inferred = self._infer_node_type_from_name(args.get("name"))
                if inferred:
                    args["node_type"] = inferred
            if "parent_path" not in args:
                args["parent_path"] = "/obj"
        elif tool_name == "add_spare_parameters":
            if "parameters" in args and "params" not in args:
                args["params"] = args.pop("parameters")
            elif "parameters_list" in args and "params" not in args:
                args["params"] = args.pop("parameters_list")

        # Check required fields
        for field in required:
            if field not in args or args[field] is None:
                field_info = properties.get(field, {})
                desc = field_info.get("description", "")
                errors.append(f"Missing required field '{field}'" + (f" ({desc})" if desc else ""))

        # Type coercion and validation
        cleaned = {}
        for key, value in args.items():
            if key not in properties:
                # Extra fields are allowed (some tools have **kwargs)
                cleaned[key] = value
                continue

            prop = properties[key]
            expected_type = prop.get("type", "")

            try:
                cleaned[key] = self._coerce(key, value, expected_type, prop)
            except (ValueError, TypeError) as e:
                errors.append(str(e))

        if errors:
            # Build hint from schema
            hint_parts = []
            for field, prop in properties.items():
                desc = prop.get("description", "")
                typ = prop.get("type", "any")
                req = " (required)" if field in required else ""
                hint_parts.append(f"  {field}: {typ}{req}" + (f" — {desc}" if desc else ""))
            hint = f"Expected arguments for '{tool_name}':\n" + "\n".join(hint_parts)
            raise ToolArgumentError(tool_name, errors, hint)

        # Add default values for missing optional fields
        for field, prop in properties.items():
            if field not in cleaned and "default" in prop:
                cleaned[field] = prop["default"]

        return cleaned

    @staticmethod
    def _infer_node_type_from_name(name: Any) -> str:
        text = str(name or "").strip().lower()
        if not text:
            return ""
        prefix = re.sub(r"[^a-z_].*$", "", text)
        aliases = {
            "null": "null",
            "out": "null",
            "output": "null",
            "normal": "normal",
            "facet": "facet",
            "merge": "merge",
            "xform": "xform",
            "transform": "xform",
            "box": "box",
            "grid": "grid",
            "sphere": "sphere",
            "scatter": "scatter",
        }
        return aliases.get(prefix, "")

    @staticmethod
    def _normalize_common_aliases(tool_name: str, args: dict) -> dict:
        """Normalize frequent LLM argument aliases before schema validation."""
        if not isinstance(args, dict):
            return {}

        # Houdini parameter tools consistently use parm_name. Several models
        # repeatedly emit parameter / parameter_name despite schema hints.
        parm_tools = {
            "safe_set_parameter",
            "set_parameter",
            "set_expression",
            "set_expression_from_description",
            "set_multiparm_count",
            "set_keyframe",
            "delete_keyframe",
            "get_timeline_keyframes",
            "get_parameter_details",
            "promote_parameter",
        }
        if tool_name in parm_tools and "parm_name" not in args:
            for alias in ("parameter_name", "parameter", "param_name", "param", "parm"):
                if alias in args and args[alias] is not None:
                    args["parm_name"] = args.pop(alias)
                    break

        if tool_name not in {"connect", "connect_nodes"} and "node_path" not in args:
            for alias in ("path", "node", "target_node", "target_path"):
                if alias in args and args[alias] is not None:
                    args["node_path"] = args.pop(alias)
                    break

        return args

    @staticmethod
    def _coerce(field: str, value: Any, expected_type: str, prop: dict) -> Any:
        """Attempt type coercion with clear error messages."""
        if value is None:
            return value

        if expected_type == "string":
            if not isinstance(value, str):
                return str(value)
            return value

        elif expected_type == "integer":
            if isinstance(value, float) and value == int(value):
                return int(value)
            if isinstance(value, str):
                try:
                    return int(value)
                except ValueError:
                    raise ValueError(f"Field '{field}' must be an integer, got '{value}'")
            if not isinstance(value, int):
                raise ValueError(f"Field '{field}' must be an integer, got {type(value).__name__}")
            return value

        elif expected_type == "number":
            if isinstance(value, str):
                try:
                    return float(value)
                except ValueError:
                    raise ValueError(f"Field '{field}' must be a number, got '{value}'")
            if isinstance(value, (int, float)):
                return float(value)
            raise ValueError(f"Field '{field}' must be a number, got {type(value).__name__}")

        elif expected_type == "boolean":
            if isinstance(value, str):
                if value.lower() in ("true", "1", "yes"):
                    return True
                if value.lower() in ("false", "0", "no"):
                    return False
                raise ValueError(f"Field '{field}' must be boolean, got '{value}'")
            return bool(value)

        elif expected_type == "array":
            if isinstance(value, str):
                try:
                    parsed = json.loads(value)
                    if isinstance(parsed, list):
                        return parsed
                except json.JSONDecodeError:
                    pass
                raise ValueError(f"Field '{field}' must be an array, got string")
            if not isinstance(value, list):
                raise ValueError(f"Field '{field}' must be an array, got {type(value).__name__}")
            return value

        elif expected_type == "object":
            if isinstance(value, str):
                try:
                    parsed = json.loads(value)
                    if isinstance(parsed, dict):
                        return parsed
                except json.JSONDecodeError:
                    pass
                raise ValueError(f"Field '{field}' must be an object, got string")
            if not isinstance(value, dict):
                raise ValueError(f"Field '{field}' must be an object, got {type(value).__name__}")
            return value

        # Enum validation
        if "enum" in prop and value not in prop["enum"]:
            raise ValueError(f"Field '{field}' must be one of {prop['enum']}, got '{value}'")

        return value

    def get_correction_prompt(self, error: ToolArgumentError) -> str:
        """
        Generate a prompt to feed back to the LLM for self-correction.
        """
        return (
            f"Your last tool call to '{error.tool_name}' had invalid arguments:\n"
            + "\n".join(f"  • {e}" for e in error.errors)
            + ("\n\n" + error.hint if error.hint else "")
            + "\n\nPlease retry the tool call with corrected arguments."
        )
