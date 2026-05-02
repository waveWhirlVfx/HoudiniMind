import os
import sys
import unittest
from unittest.mock import MagicMock

# Setup path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(ROOT, "src"))

# Mock hou before imports
sys.modules["hou"] = MagicMock()
import hou

hou.parmTemplateType = MagicMock()
hou.parmTemplateType.Int = 1
hou.parmTemplateType.Float = 2
hou.parmTemplateType.Toggle = 3
hou.parmTemplateType.Menu = 4

from houdinimind.agent.scene_observer import SceneObserver
from houdinimind.agent.tool_selection import select_relevant_tool_schemas
from houdinimind.agent.tools import _core as core
from houdinimind.agent.tools import _node_tools as node_tools


class TestIntelligence(unittest.TestCase):
    def test_parameter_aliases(self):
        print("\nTesting Parameter Aliases...")
        # Verify new aliases are present
        self.assertEqual(core._PARM_BASE_ALIASES.get("dimensions"), "size")
        self.assertEqual(core._PARM_BASE_ALIASES.get("resolution"), "divs")
        self.assertEqual(core._PARM_COMPONENT_ALIASES.get("red"), "x")
        print("✓ New aliases verified.")

    def test_fuzzy_matching_logic(self):
        print("\nTesting Fuzzy Matching Logic...")
        # Mock LLM chat function
        mock_chat = MagicMock(return_value="size")
        core._shared_chat_simple_fn = mock_chat

        pool = ["size", "t", "r"]
        labels = {"size": "Dimensions"}

        # Test deterministic resolution still works
        res = core._resolve_parameter_name("dimensions", pool, labels_by_name=labels)
        self.assertEqual(res["resolved"], "size")
        self.assertEqual(res["reason"], "alias")

        # Ambiguous fuzzy resolution must not call the LLM from parameter
        # resolution. This path runs inside Houdini tool execution, often on
        # the main thread.
        res = core._resolve_parameter_name("scale it up", pool, labels_by_name=labels)
        self.assertEqual(res["status"], "unresolved")
        self.assertEqual(res["resolved"], "")
        mock_chat.assert_not_called()
        print("✓ Fuzzy matching logic verified.")

    def test_scene_observer_bypass(self):
        print("\nTesting SceneObserver Bypass Detection...")
        obs = SceneObserver()

        # Mock a node
        mock_node = MagicMock()
        mock_node.path.return_value = "/obj/test"
        mock_node.type().name.return_value = "box"
        mock_node.inputs.return_value = []
        mock_node.isDisplayFlagSet.return_value = True
        mock_node.isRenderFlagSet.return_value = True
        mock_node.isBypassed.return_value = True

        mock_parent = MagicMock()
        mock_parent.children.return_value = [mock_node]
        hou.node.return_value = mock_parent

        # This will use the mock
        graph = obs._build_scene_graph()
        self.assertTrue(graph[0].get("bypass"))
        print("✓ Bypass detection in SceneObserver verified.")

    def test_vex_structured_error(self):
        print("\nTesting VEX Structured Error Return...")
        # Mock node
        mock_node = MagicMock()
        hou.node.return_value = mock_node

        # Mock checker to return failure
        import houdinimind.agent.tools._node_tools as nt

        original_hou = getattr(nt, "hou", None)
        original_available = nt.HOU_AVAILABLE
        original_core_available = core.HOU_AVAILABLE
        original_validator = nt._validate_vex_with_checker
        try:
            nt.hou = hou
            nt.HOU_AVAILABLE = True
            core.HOU_AVAILABLE = True
            nt._validate_vex_with_checker = MagicMock(
                return_value={
                    "success": False,
                    "errors": ["Syntax error at line 1"],
                    "warnings": [],
                }
            )
            res = nt.write_vex_code("/obj/wrangle", "@P.y += 1")
        finally:
            nt.hou = original_hou
            nt.HOU_AVAILABLE = original_available
            core.HOU_AVAILABLE = original_core_available
            nt._validate_vex_with_checker = original_validator

        self.assertEqual(res["status"], "error")
        self.assertEqual(res["data"]["status"], "validation_failed")
        self.assertIn("Syntax error", res["data"]["errors"][0])
        print("✓ VEX structured error return verified.")

    def test_pyro_tool_selection_prefers_sop_diagnostics(self):
        schemas = [
            {"function": {"name": name, "description": name, "parameters": {"type": "object"}}}
            for name in (
                "get_scene_summary",
                "create_node",
                "safe_set_parameter",
                "connect_nodes",
                "verify_node_type",
                "layout_network",
                "get_node_parameters",
                "get_all_errors",
                "search_knowledge",
                "audit_spatial_layout",
                "batch_set_parameters",
                "create_node_chain",
                "set_display_flag",
                "finalize_sop_network",
                "save_hip",
                "setup_pyro_sim",
                "get_simulation_diagnostic",
                "get_sim_stats",
                "get_dop_objects",
            )
        ]

        selected = select_relevant_tool_schemas(
            "create sop level pyro smoke fx",
            schemas,
            top_n=len(schemas),
        )
        names = [schema["function"]["name"] for schema in selected]

        self.assertIn("setup_pyro_sim", names)
        self.assertIn("get_simulation_diagnostic", names)
        self.assertNotIn("get_dop_objects", names[: names.index("get_simulation_diagnostic") + 1])
        print("✓ Pyro tool selection prefers SOP diagnostics.")

    def test_particle_sim_tool_selection_includes_pop_builder(self):
        schemas = [
            {"function": {"name": name, "description": name, "parameters": {"type": "object"}}}
            for name in (
                "get_scene_summary",
                "create_node",
                "safe_set_parameter",
                "connect_nodes",
                "search_knowledge",
                "setup_pop_sim",
                "get_sim_stats",
                "get_dop_objects",
                "bake_simulation",
            )
        ]

        selected = select_relevant_tool_schemas(
            "create a particle simulation with pop forces",
            schemas,
            top_n=len(schemas),
        )
        names = [schema["function"]["name"] for schema in selected]

        self.assertIn("setup_pop_sim", names)
        self.assertIn("get_sim_stats", names)
        self.assertIn("get_dop_objects", names)


if __name__ == "__main__":
    unittest.main()
