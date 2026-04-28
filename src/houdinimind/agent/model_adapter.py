# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
import json
import re


class ModelAdapter:
    def __init__(self, model_name: str, context_window: int, config: dict):
        self.model_name = model_name.lower()
        self.context_window = context_window
        self.config = config or {}
        self.tier = self._detect_tier()

    def _detect_tier(self) -> str:
        """Detect the model tier based on name hints or context window."""
        if (
            "cloud" in self.model_name
            or "kimi" in self.model_name
            or "gpt" in self.model_name
            or "claude" in self.model_name
        ):
            return "cloud"
        size_matches = re.findall(r"(\d+(?:\.\d+)?)b", self.model_name)
        if size_matches:
            try:
                largest_b = max(float(v) for v in size_matches)
                if largest_b >= 30:
                    return "large"
                if largest_b >= 12:
                    return "medium"
                if largest_b >= 7:
                    return "small"
                return "tiny"
            except Exception:
                pass
        if any(x in self.model_name for x in ["30b", "32b", "70b", "72b"]):
            return "large"
        if any(x in self.model_name for x in ["13b", "14b", "27b"]):
            return "medium"
        if any(x in self.model_name for x in ["7b", "8b", "9b"]):
            return "small"
        if re.search(r"\b[1-6]b\b", self.model_name):
            return "tiny"
        return "large"  # Default if unknown

    def adapt_system_prompt(self, system_prompt: str) -> str:
        """Compress the system prompt to save tokens for medium-tier models only."""
        if self.tier in ["cloud", "large", "small", "tiny"]:
            return system_prompt

        # For medium-tier models, trim verbose sections but do not inject any
        # model-size-specific operating contract.
        adapted = system_prompt
        adapted = re.sub(r"### VEX EXAMPLES.*?(?=###|$)", "", adapted, flags=re.DOTALL)
        adapted = re.sub(r"### ADDITIONAL RULES.*?(?=###|$)", "", adapted, flags=re.DOTALL)
        return adapted.strip()

    def get_few_shot_message(self, user_message: str) -> list:
        """Inject few-shot messages to teach weaker models the tool call format.

        Small and tiny tiers benefit the most from explicit examples —
        without them these models frequently emit broken tool calls,
        repeat failing node paths, and struggle with self-repair.
        """
        if self.tier in ["cloud", "large"]:
            # Large / cloud models handle native tool calling reliably
            return []

        return [
            {"role": "user", "content": "Example request: create a simple box in an empty scene."},
            {
                "role": "assistant",
                "content": (
                    "Plan:\n"
                    "1. create_node(parent_path='/obj', node_type='geo', name='geo')\n"
                    "2. create_node(parent_path='/obj/geo', node_type='box', name='box1')\n"
                    "3. finalize_sop_network(parent_path='/obj/geo')\n"
                    "Rule: SOP nodes belong inside the geo container, not inside another SOP.\n\n"
                    "```json\n"
                    "[\n"
                    '  {"name": "create_node", "parameters": {"parent_path": "/obj", "node_type": "geo", "name": "geo"}},\n'
                    '  {"name": "create_node", "parameters": {"parent_path": "/obj/geo", "node_type": "box", "name": "box1"}},\n'
                    '  {"name": "finalize_sop_network", "parameters": {"parent_path": "/obj/geo"}}\n'
                    "]\n"
                    "```"
                ),
            },
            {
                "role": "user",
                "content": "Example request: the parent path was wrong and the create step failed.",
            },
            {
                "role": "assistant",
                "content": (
                    "First inspect the scene, then move the new node to the containing network.\n"
                    "Do not repeat the same failing create_node call. Fix parent_path or node_type before retrying."
                ),
            },
            {"role": "user", "content": "Example request: build a table with four legs."},
            {
                "role": "assistant",
                "content": (
                    "Plan:\n"
                    "CRITICAL: Every node MUST be created BEFORE setting parameters on it.\n"
                    "1. create_node(parent_path='/obj', node_type='geo', name='Table_Geo')\n"
                    "2. create_node(parent_path='/obj/Table_Geo', node_type='box', name='Table_Top')\n"
                    "3. safe_set_parameter(node_path='/obj/Table_Geo/Table_Top', parm_name='size', value=[2, 0.1, 1])\n"
                    "4. create_node(parent_path='/obj/Table_Geo', node_type='box', name='Leg_FL')\n"
                    "5. safe_set_parameter(node_path='/obj/Table_Geo/Leg_FL', parm_name='size', value=[0.1, 1, 0.1])\n"
                    "6. ... repeat create_node then safe_set_parameter for each remaining leg ...\n"
                    "7. finalize_sop_network(parent_path='/obj/Table_Geo')\n"
                    "Rule: NEVER call safe_set_parameter on a node path that hasn't been created yet.\n\n"
                    "```json\n"
                    "[\n"
                    '  {"name": "create_node", "parameters": {"parent_path": "/obj", "node_type": "geo", "name": "Table_Geo"}},\n'
                    '  {"name": "create_node", "parameters": {"parent_path": "/obj/Table_Geo", "node_type": "box", "name": "Table_Top"}},\n'
                    '  {"name": "safe_set_parameter", "parameters": {"node_path": "/obj/Table_Geo/Table_Top", "parm_name": "size", "value": [2, 0.1, 1]}}\n'
                    "]\n"
                    "```"
                ),
            },
            {
                "role": "user",
                "content": "Example error: safe_set_parameter returned 'Node not found: /obj/Table_Geo/Leg_FR'",
            },
            {
                "role": "assistant",
                "content": (
                    "The node does not exist yet. I must create it first, then set the parameter.\n"
                    "NEVER ask the user to confirm — just create the missing node and continue.\n\n"
                    "```json\n"
                    "[\n"
                    '  {"name": "create_node", "parameters": {"parent_path": "/obj/Table_Geo", "node_type": "box", "name": "Leg_FR"}},\n'
                    '  {"name": "safe_set_parameter", "parameters": {"node_path": "/obj/Table_Geo/Leg_FR", "parm_name": "size", "value": [0.1, 1, 0.1]}}\n'
                    "]\n"
                    "```"
                ),
            },
        ]

    def extract_fallback_tool_calls(self, text: str) -> list:
        """Extract tool calls from markdown JSON blocks if the model failed to use native tool calling."""
        tool_calls = []
        # Find JSON blocks
        json_matches = re.finditer(r"```json\s*(.*?)\s*```", text, re.DOTALL)
        for match in json_matches:
            try:
                parsed = json.loads(match.group(1).strip())
                if isinstance(parsed, list):
                    for item in parsed:
                        if isinstance(item, dict) and "name" in item and "parameters" in item:
                            tool_calls.append(
                                {
                                    "function": {
                                        "name": item["name"],
                                        "arguments": json.dumps(item["parameters"]),
                                    }
                                }
                            )
                elif isinstance(parsed, dict) and "name" in parsed and "parameters" in parsed:
                    tool_calls.append(
                        {
                            "function": {
                                "name": parsed["name"],
                                "arguments": json.dumps(parsed["parameters"]),
                            }
                        }
                    )
            except json.JSONDecodeError:
                continue

        # Also try to catch naked JSON arrays or objects at the end of the text
        if not tool_calls:
            try:
                # Find the last block that looks like it could be JSON
                naked_match = re.search(
                    r"(\[\s*\{.*\}\s*\]|\{\s*\"name\".*\})\s*$", text, re.DOTALL
                )
                if naked_match:
                    parsed = json.loads(naked_match.group(1).strip())
                    if isinstance(parsed, list):
                        for item in parsed:
                            if isinstance(item, dict) and "name" in item and "parameters" in item:
                                tool_calls.append(
                                    {
                                        "function": {
                                            "name": item["name"],
                                            "arguments": json.dumps(item["parameters"]),
                                        }
                                    }
                                )
                    elif isinstance(parsed, dict) and "name" in parsed and "parameters" in parsed:
                        tool_calls.append(
                            {
                                "function": {
                                    "name": parsed["name"],
                                    "arguments": json.dumps(parsed["parameters"]),
                                }
                            }
                        )
            except Exception:
                pass

        return tool_calls

    def trim_history(self, messages: list) -> list:
        """Trim message history depending on the model's tier context window capability."""
        if not messages:
            return messages

        system_msgs = [m for m in messages if m.get("role") == "system"]
        chat_msgs = [m for m in messages if m.get("role") != "system"]

        limit = 20
        if self.tier == "tiny":
            limit = 6
        elif self.tier == "small":
            limit = 8
        elif self.tier == "medium":
            limit = 10

        if len(chat_msgs) > limit:
            chat_msgs = chat_msgs[-limit:]

        return system_msgs + chat_msgs

    def is_small_llm(self) -> bool:
        """Small-model special handling has been retired."""
        return False

    def slim_tool_schemas(self, schemas: list, max_tools: int = 14) -> list:
        return schemas
