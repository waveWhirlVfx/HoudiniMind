# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
import json
import os
import shutil
import time
import unittest

from tests.fake_hou import FakeHou, FakeParentNode


def _workspace_temp_root():
    root = os.path.join(os.getcwd(), "tests", "scratch")
    os.makedirs(root, exist_ok=True)
    return root


def _workspace_case_dir(name: str):
    path = os.path.join(_workspace_temp_root(), name)
    shutil.rmtree(path, ignore_errors=True)
    os.makedirs(path, exist_ok=True)
    return path


class _FakeParmTemplate:
    def type(self):
        return "Float"


class _FakeParm:
    def __init__(self, name, value=0, label=None):
        self._name = name
        self._value = value
        self._label = label

    def name(self):
        return self._name

    def eval(self):
        return self._value

    def set(self, value):
        self._value = value

    def description(self):
        return self._label or self._name

    def parmTemplate(self):
        return _FakeParmTemplate()


class _FakeParmType:
    def __init__(self, name):
        self._name = name

    def name(self):
        return self._name


class _FakeParmNode:
    def __init__(self, path, type_name="box", parms=None):
        self._path = path
        self._type = _FakeParmType(type_name)
        self._parms = {}
        for name, value in (parms or {}).items():
            label = None
            raw_value = value
            if isinstance(value, tuple) and len(value) == 2 and isinstance(value[1], str):
                raw_value, label = value
            self._parms[name] = _FakeParm(name, raw_value, label=label)

    def path(self):
        return self._path

    def type(self):
        return self._type

    def parm(self, name):
        return self._parms.get(name)

    def parms(self):
        return list(self._parms.values())


class _FakeFinalizerPrimType:
    def __init__(self, name="Polygon"):
        self._name = name

    def name(self):
        return self._name


class _FakeFinalizerPrim:
    def __init__(self, prim_type="Polygon"):
        self._type = _FakeFinalizerPrimType(prim_type)

    def type(self):
        return self._type


class _FakeFinalizerGeometry:
    def __init__(self, points=0, prims=0, prim_type="Polygon"):
        self._points = [object()] * points
        self._prims = [_FakeFinalizerPrim(prim_type) for _ in range(prims)]

    def points(self):
        return self._points

    def prims(self):
        return self._prims

    def saveToFile(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("fake bgeo\n")


class _FakeFinalizerType:
    def __init__(self, name):
        from tests.fake_hou import FakeCategory

        self._name = name
        self._category = FakeCategory("Sop")

    def name(self):
        return self._name

    def category(self):
        return self._category


class _FakeFinalizerNode:
    def __init__(self, parent, name, node_type, points=0, prims=0, prim_type="Polygon"):
        self._parent = parent
        self._name = name
        self._path = f"{parent.path().rstrip('/')}/{name}"
        self._type = _FakeFinalizerType(node_type)
        self._geometry = _FakeFinalizerGeometry(points=points, prims=prims, prim_type=prim_type)
        self._inputs = []
        self._outputs = []
        self._children = []
        self._parms = {}
        self._display = False
        self._render = False
        self.selected = False

    def path(self):
        return self._path

    def name(self):
        return self._name

    def parent(self):
        return self._parent

    def type(self):
        return self._type

    def geometry(self):
        return self._geometry

    def outputs(self):
        return list(self._outputs)

    def children(self):
        return list(self._children)

    def node(self, name):
        for child in self._children:
            if child.name() == name:
                return child
        return None

    def createNode(self, node_type, name=None):
        node_name = name or f"{node_type}1"
        node = _FakeFinalizerNode(self, node_name, node_type)
        self._children.append(node)
        owner = self
        while owner is not None and not hasattr(owner, "_node_map"):
            owner = owner.parent() if hasattr(owner, "parent") else None
        if owner is not None:
            owner._node_map[node.path()] = node
        return node

    def layoutChildren(self):
        return None

    def inputConnections(self):
        return [node for node in self._inputs if node is not None]

    def outputConnections(self):
        return list(self._outputs)

    def inputs(self):
        return list(self._inputs)

    def inputConnectors(self):
        return self._inputs

    def setInput(self, index, node, *_args):
        while len(self._inputs) <= index:
            self._inputs.append(None)
        self._inputs[index] = node
        if node and self not in node._outputs:
            node._outputs.append(self)

    def parmTuple(self, name):
        return None

    def parm(self, name):
        if name not in self._parms:
            self._parms[name] = _FakeParm(name)
        return self._parms[name]

    def parms(self):
        return list(self._parms.values())

    def errors(self):
        return []

    def isBypassed(self):
        return False

    def isDisplayFlagSet(self):
        return self._display

    def setDisplayFlag(self, flag):
        self._display = flag

    def setRenderFlag(self, flag):
        self._render = flag

    def setGenericFlag(self, flag, value):
        if str(flag).lower().endswith("display"):
            self._display = value
        elif str(flag).lower().endswith("render"):
            self._render = value

    def setSelected(self, flag, **_kwargs):
        self.selected = flag

    def moveToGoodPosition(self):
        return None

    def cook(self, force=False):
        return None


class _FakeFinalizerParent:
    def __init__(self, path):
        from tests.fake_hou import FakeCategory

        self._path = path
        self._child_category = FakeCategory("Sop")
        self._children = []
        self._node_map = {path: self}

    def path(self):
        return self._path

    def childTypeCategory(self):
        return self._child_category

    def children(self):
        return list(self._children)

    def layoutChildren(self):
        return None

    def createNode(self, node_type, name=None):
        node_name = name or f"{node_type}1"
        node = _FakeFinalizerNode(self, node_name, node_type)
        self._children.append(node)
        self._node_map[node.path()] = node
        return node

    def add_child(self, node):
        self._children.append(node)
        self._node_map[node.path()] = node

    def add_source(self, name, node_type="sphere", points=0, prims=0, prim_type="Polygon"):
        node = _FakeFinalizerNode(
            self,
            name,
            node_type,
            points=points,
            prims=prims,
            prim_type=prim_type,
        )
        self.add_child(node)
        return node


class _FakeFinalizerHou:
    class _UI:
        @staticmethod
        def paneTabOfType(_pane_type):
            return None

    class _PaneTabType:
        NetworkEditor = object()

    def __init__(self, parent):
        self._parent = parent
        self._frame = 1
        self.ui = self._UI()
        self.paneTabType = self._PaneTabType()

    def node(self, path):
        return self._parent._node_map.get(path)

    def frame(self):
        return self._frame

    def setFrame(self, frame):
        self._frame = frame

    def expandString(self, value):
        return value.replace("$HIP", _workspace_temp_root())


class _FakeHdefereval:
    def __init__(self):
        self.calls = 0

    def executeInMainThreadWithResult(self, fn, **kwargs):
        self.calls += 1
        return fn(**kwargs)


class _FakeConnection:
    def __init__(self, errors=None):
        self._errors = list(errors or [])

    def errors(self):
        return list(self._errors)


class _FakeInputLabelNode:
    def __init__(self, path):
        self._path = path

    def path(self):
        return self._path


class _FakeInputNode:
    def __init__(self):
        self._inputs = [_FakeInputLabelNode("/obj/geo1/source")]
        self._connectors = [(_FakeConnection(["bad wire"]),)]

    def inputNames(self):
        return ["Input 0"]

    def inputs(self):
        return list(self._inputs)

    def inputConnectors(self):
        return list(self._connectors)


class _FakeAttrib:
    def __init__(self, name):
        self._name = name

    def name(self):
        return self._name


class _FakeGeometry:
    def globalAttribs(self):
        return [_FakeAttrib("foo")]

    def pointAttribs(self):
        return [_FakeAttrib("P"), _FakeAttrib("Cd")]

    def primAttribs(self):
        return [_FakeAttrib("name")]

    def attribValue(self, name):
        return {"foo": 123}[name]

    def points(self):
        return [object(), object()]


class _FakeGeometryNode:
    def geometry(self):
        return _FakeGeometry()


class _FakeHipFile:
    def __init__(self):
        self.loaded = None
        self._path = "C:/project/test_scene.hip"

    def saveAsBackup(self):
        return self._path + ".bak"

    def load(self, path, suppress_save_prompt=True, ignore_load_warnings=True):
        self.loaded = {
            "path": path,
            "suppress_save_prompt": suppress_save_prompt,
            "ignore_load_warnings": ignore_load_warnings,
        }

    def path(self):
        return self._path

    def hasUnsavedChanges(self):
        return False


class _FakeHouWithHip:
    def __init__(self):
        self.hipFile = _FakeHipFile()


class AgentFoundationTests(unittest.TestCase):
    def test_bounded_embed_cache_evicts_oldest_entries(self):
        from houdinimind.agent.llm_client import _BoundedEmbedCache

        cache = _BoundedEmbedCache(max_entries=2)
        cache["a"] = 1
        cache["b"] = 2
        _ = cache["a"]
        cache["c"] = 3

        self.assertIn("a", cache)
        self.assertIn("c", cache)
        self.assertNotIn("b", cache)

    def test_select_relevant_tools_hides_execute_python_without_code_request(self):
        from houdinimind.agent.llm_client import OllamaClient
        from houdinimind.agent.tools import TOOL_SCHEMAS

        client = OllamaClient({"ollama_url": "http://localhost:11434"})
        selected = client.select_relevant_tools(
            "build a chair with proper controls and vellum pillows",
            TOOL_SCHEMAS,
            top_n=12,
        )
        names = [s.get("function", {}).get("name") for s in selected]
        self.assertNotIn("execute_python", names)

        selected_code = client.select_relevant_tools(
            "write python code to iterate over selected nodes and rename them",
            TOOL_SCHEMAS,
            top_n=20,
        )
        code_names = [s.get("function", {}).get("name") for s in selected_code]
        self.assertIn("execute_python", code_names)

    def test_select_relevant_tools_includes_fast_hint_tools_for_build_queries(self):
        from houdinimind.agent.llm_client import OllamaClient
        from houdinimind.agent.tools import TOOL_SCHEMAS

        client = OllamaClient({"ollama_url": "http://localhost:11434"})
        selected = client.select_relevant_tools(
            "create a procedural table with a visible final output",
            TOOL_SCHEMAS,
            top_n=20,
        )
        names = [s.get("function", {}).get("name") for s in selected]

        self.assertIn("resolve_build_hints", names)
        self.assertIn("inspect_display_output", names)

    def test_tool_keyword_map_prefers_general_material_tools_for_lookdev_queries(self):
        from houdinimind.agent.llm_client import _TOOL_KEYWORD_MAP

        self.assertEqual(
            _TOOL_KEYWORD_MAP["shade"][:4],
            ["create_material", "assign_material", "list_materials", "setup_fabric_lookdev"],
        )
        self.assertEqual(
            _TOOL_KEYWORD_MAP["lookdev"][:4],
            ["create_material", "assign_material", "list_materials", "setup_fabric_lookdev"],
        )
        self.assertEqual(_TOOL_KEYWORD_MAP["uv"][0], "create_uv_seams")

    def test_model_adapter_does_not_apply_small_model_special_profile(self):
        from houdinimind.agent.model_adapter import ModelAdapter

        adapter = ModelAdapter("qwen3.5:2b", 65536, {})
        system_prompt = adapter.adapt_system_prompt(
            "### ADDITIONAL RULES\nVerbose section\n### END"
        )
        few_shot = adapter.get_few_shot_message("create a box")

        self.assertEqual(system_prompt, "### ADDITIONAL RULES\nVerbose section\n### END")
        # Small/tiny tiers now correctly receive few-shot examples to help
        # with tool-call formatting — they need the most scaffolding.
        self.assertGreater(len(few_shot), 0)
        self.assertFalse(adapter.is_small_llm())

    def test_model_adapter_treats_cloud_model_names_as_cloud_tier(self):
        from houdinimind.agent.model_adapter import ModelAdapter

        adapter = ModelAdapter("qwen3.5:397b-cloud", 262144, {})
        self.assertEqual(adapter.tier, "cloud")
        self.assertFalse(adapter.is_small_llm())

    def test_rag_context_falls_back_to_relevant_workflow_then_scaffold(self):
        from houdinimind.rag.injector import ContextInjector

        class _FakeRetriever:
            def __init__(self):
                self.last_route_meta = {"route": "fake"}

            def retrieve(
                self,
                query,
                top_k=5,
                min_score=0.1,
                include_live_scene=None,
                include_categories=None,
                exclude_categories=None,
                include_memory=True,
                use_rerank=True,
                **_kwargs,
            ):
                q = str(query).lower()
                if "cup workflow" in q or "mug workflow" in q:
                    return [
                        {
                            "id": "workflow_cup",
                            "title": "Node Chain: Procedural Tea Cup / Mug (High Fidelity)",
                            "category": "workflow",
                            "content": "Context: SOP Goal: Drinking mug with a curved handle",
                            "_score": 0.91,
                        }
                    ]
                return []

            def get_chunk(self, cid):
                return None

        injector = ContextInjector(
            _FakeRetriever(),
            max_context_tokens=1200,
            top_k=4,
            min_score=0.1,
            model_name="qwen3.5:2b",
        )
        msg = injector.build_context_message("create a cup", request_mode="build")
        self.assertIsNotNone(msg)
        self.assertIn("Procedural Tea Cup / Mug", msg["content"])

        empty_injector = ContextInjector(
            type(
                "EmptyRetriever",
                (),
                {
                    "last_route_meta": {},
                    "retrieve": lambda self, **kwargs: [],
                    "get_chunk": lambda self, cid: None,
                },
            )(),
            max_context_tokens=1200,
            top_k=4,
            min_score=0.1,
            model_name="qwen3.5:2b",
        )
        scaffold_msg = empty_injector.build_context_message("create a lamp", request_mode="build")
        self.assertIsNotNone(scaffold_msg)
        self.assertIn("Procedural build scaffold", scaffold_msg["content"])

    def test_chat_uses_selected_chat_model_instead_of_task_routing(self):
        from houdinimind.agent.llm_client import OllamaClient

        client = OllamaClient(
            {
                "ollama_url": "http://localhost:11434",
                "model": "ui-selected-model",
                "model_routing": {"build": "fast-build-model"},
            }
        )
        original_chat = client._ollama_chat
        original_retry = client._request_with_retry
        seen = {}

        def fake_ollama_chat(messages, tools=None, model_override=None):
            seen["model_override"] = model_override
            return {"content": "ok"}

        try:
            client._ollama_chat = fake_ollama_chat
            client._request_with_retry = lambda fn, retries=5: fn()
            result = client.chat([{"role": "user", "content": "build it"}], task="build")
        finally:
            client._ollama_chat = original_chat
            client._request_with_retry = original_retry

        self.assertEqual(result["content"], "ok")
        self.assertEqual(seen["model_override"], "ui-selected-model")

    def test_chat_forwards_explicit_timeout_to_ollama_call(self):
        from houdinimind.agent.llm_client import OllamaClient

        client = OllamaClient({"ollama_url": "http://localhost:11434"})
        original_chat = client._ollama_chat
        original_retry = client._request_with_retry
        seen = {}

        def fake_ollama_chat(messages, tools=None, model_override=None, timeout_s=300):
            seen["timeout_s"] = timeout_s
            return {"content": "ok"}

        try:
            client._ollama_chat = fake_ollama_chat
            client._request_with_retry = lambda fn, retries=5: fn()
            result = client.chat(
                [{"role": "user", "content": "build it"}],
                task="build",
                timeout_s=42,
            )
        finally:
            client._ollama_chat = original_chat
            client._request_with_retry = original_retry

        self.assertEqual(result["content"], "ok")
        self.assertEqual(seen["timeout_s"], 42)

    def test_chat_falls_back_to_selected_model_when_routed_model_missing(self):
        import io
        import urllib.error

        from houdinimind.agent.llm_client import OllamaClient

        client = OllamaClient(
            {
                "ollama_url": "http://localhost:11434",
                "model": "gemma4:e4b",
                "model_routing": {"build": "qwen3.5:9b"},
                "force_model_routing_tasks": ["build"],
            }
        )
        original_chat = client._ollama_chat
        original_retry = client._request_with_retry
        seen_models = []

        def fake_ollama_chat(messages, tools=None, model_override=None, timeout_s=300):
            seen_models.append(model_override)
            if model_override == "qwen3.5:9b":
                raise urllib.error.HTTPError(
                    "http://localhost/api/chat",
                    404,
                    "Not Found",
                    {},
                    io.BytesIO(b""),
                )
            return {"content": "ok"}

        try:
            client._ollama_chat = fake_ollama_chat
            client._request_with_retry = lambda fn, retries=5: fn()
            result = client.chat(
                [{"role": "user", "content": "build it"}],
                task="build",
            )
        finally:
            client._ollama_chat = original_chat
            client._request_with_retry = original_retry

        self.assertEqual(result["content"], "ok")
        self.assertEqual(seen_models, ["qwen3.5:9b", "gemma4:e4b"])

    def test_chat_vision_uses_selected_vision_model_instead_of_routing(self):
        from houdinimind.agent.llm_client import OllamaClient

        client = OllamaClient(
            {
                "ollama_url": "http://localhost:11434",
                "model": "ui-chat-model",
                "vision_model": "ui-vision-model",
                "model_routing": {"vision": "wrong-vision-model"},
            }
        )
        original_json_request = client._json_request
        captured = {}

        def fake_json_request(path, payload=None, timeout=120, method="POST"):
            captured["path"] = path
            captured["model"] = payload["model"]
            return json.dumps({"message": {"content": "vision ok"}})

        try:
            client._json_request = fake_json_request
            result = client.chat_vision(prompt="inspect", image_b64="ZmFrZQ==")
        finally:
            client._json_request = original_json_request

        self.assertEqual(result, "vision ok")
        self.assertEqual(captured["path"], "/api/chat")
        self.assertEqual(captured["model"], "ui-vision-model")

    def test_chat_uses_forced_task_route_for_semantic_task(self):
        from houdinimind.agent.llm_client import OllamaClient

        client = OllamaClient(
            {
                "ollama_url": "http://localhost:11434",
                "model": "ui-selected-model",
                "model_routing": {"semantic": "semantic-router-model"},
                "force_model_routing_tasks": ["semantic"],
            }
        )
        original_chat = client._ollama_chat
        original_retry = client._request_with_retry
        seen = {}

        def fake_ollama_chat(messages, tools=None, model_override=None):
            seen["model_override"] = model_override
            return {"content": "ok"}

        try:
            client._ollama_chat = fake_ollama_chat
            client._request_with_retry = lambda fn, retries=5: fn()
            result = client.chat(
                [{"role": "user", "content": "score this build"}],
                task="semantic",
            )
        finally:
            client._ollama_chat = original_chat
            client._request_with_retry = original_retry

        self.assertEqual(result["content"], "ok")
        self.assertEqual(seen["model_override"], "semantic-router-model")

    def test_viewport_capture_extracts_accessor_based_bounds(self):
        from houdinimind.bridge.viewport_capture import _extract_screen_rect

        class _FakeBounds:
            def left(self):
                return 10

            def top(self):
                return 20

            def right(self):
                return 210

            def bottom(self):
                return 320

        self.assertEqual(_extract_screen_rect(_FakeBounds()), (10, 20, 210, 320))

    def test_create_node_uses_child_context_for_validation(self):
        from houdinimind.agent import tools

        parent = FakeParentNode("/obj/geo1", parent_category="Object", child_category="Sop")
        original_hou = getattr(tools, "hou", None)
        original_available = tools.HOU_AVAILABLE
        original_validate_node = tools.pipeline_interceptor.validate_node
        calls = {}

        def _validate_node(context, node_type):
            calls["context"] = context
            calls["node_type"] = node_type
            return True, node_type

        try:
            tools.hou = FakeHou({"/obj/geo1": parent})
            tools.HOU_AVAILABLE = True
            tools.pipeline_interceptor.validate_node = _validate_node
            result = tools.create_node("/obj/geo1", "box", "box1")
        finally:
            if original_hou is None:
                delattr(tools, "hou")
            else:
                tools.hou = original_hou
            tools.HOU_AVAILABLE = original_available
            tools.pipeline_interceptor.validate_node = original_validate_node

        self.assertEqual(calls["context"], "Sop")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["path"], "/obj/geo1/box1")

    def test_create_node_resolves_label_like_node_type_alias(self):
        from houdinimind.agent import tools

        parent = FakeParentNode("/obj/geo1", parent_category="Object", child_category="Sop")
        original_hou = getattr(tools, "hou", None)
        original_available = tools.HOU_AVAILABLE
        original_validate_node = tools.pipeline_interceptor.validate_node

        def _validate_node(context, node_type):
            return False, None

        try:
            tools.hou = FakeHou({"/obj/geo1": parent})
            tools.HOU_AVAILABLE = True
            tools.pipeline_interceptor.validate_node = _validate_node
            result = tools.create_node("/obj/geo1", "attrib wrangle", "wrangle1")
        finally:
            if original_hou is None:
                delattr(tools, "hou")
            else:
                tools.hou = original_hou
            tools.HOU_AVAILABLE = original_available
            tools.pipeline_interceptor.validate_node = original_validate_node

        self.assertEqual(result["status"], "ok")
        self.assertEqual(parent.created[-1][0], "attribwrangle")
        self.assertEqual(result["data"]["type"], "attribwrangle")

    def test_create_and_verify_node_reject_null_type(self):
        from houdinimind.agent import tools

        create_result = tools.create_node("/obj/geo1", None, "OUT")
        verify_result = tools.verify_node_type(None, "/obj/geo1")

        self.assertEqual(create_result["status"], "error")
        self.assertIn("non-empty string", create_result["message"])
        self.assertEqual(verify_result["status"], "error")
        self.assertIn("non-empty string", verify_result["message"])

    def test_verify_node_type_maps_out_alias_to_null(self):
        from houdinimind.agent import tools

        result = tools.verify_node_type("out", "/obj/geo1")

        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["data"]["valid"])
        self.assertEqual(result["data"]["canonical_type"], "null")
        self.assertIn("null", result["message"].lower())

    def test_safe_set_parameter_parses_stringified_vectors(self):
        from houdinimind.agent import tools

        node = _FakeParmNode(
            "/obj/geo1/tabletop",
            parms={"sizex": 0, "sizey": 0, "sizez": 0},
        )
        original_hou = getattr(tools, "hou", None)
        original_available = tools.HOU_AVAILABLE

        try:
            tools.hou = FakeHou({"/obj/geo1/tabletop": node})
            tools.HOU_AVAILABLE = True
            result = tools.safe_set_parameter("/obj/geo1/tabletop", "size", "[2, 0.1, 1]")
        finally:
            if original_hou is None:
                delattr(tools, "hou")
            else:
                tools.hou = original_hou
            tools.HOU_AVAILABLE = original_available

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["mapped_components"], 3)
        self.assertEqual(node.parm("sizex").eval(), 2)
        self.assertEqual(node.parm("sizey").eval(), 0.1)
        self.assertEqual(node.parm("sizez").eval(), 1)

    def test_safe_set_parameter_maps_center_vector_to_translate_components(self):
        from houdinimind.agent import tools

        node = _FakeParmNode(
            "/obj/geo1/xform1",
            type_name="xform",
            parms={"tx": 0, "ty": 0, "tz": 0},
        )
        original_hou = getattr(tools, "hou", None)
        original_available = tools.HOU_AVAILABLE

        try:
            tools.hou = FakeHou({"/obj/geo1/xform1": node})
            tools.HOU_AVAILABLE = True
            result = tools.safe_set_parameter("/obj/geo1/xform1", "center", [1, 2, 3])
        finally:
            if original_hou is None:
                delattr(tools, "hou")
            else:
                tools.hou = original_hou
            tools.HOU_AVAILABLE = original_available

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["mapped_components"], 3)
        self.assertEqual(node.parm("tx").eval(), 1)
        self.assertEqual(node.parm("ty").eval(), 2)
        self.assertEqual(node.parm("tz").eval(), 3)

    def test_safe_set_parameter_maps_groundplane_alias_to_useground(self):
        from houdinimind.agent import tools

        node = _FakeParmNode(
            "/obj/geo1/rbdbulletsolver1",
            type_name="rbdbulletsolver",
            parms={"useground": 0, "showground": 0},
        )
        original_hou = getattr(tools, "hou", None)
        original_available = tools.HOU_AVAILABLE

        try:
            tools.hou = FakeHou({"/obj/geo1/rbdbulletsolver1": node})
            tools.HOU_AVAILABLE = True
            result = tools.safe_set_parameter(
                "/obj/geo1/rbdbulletsolver1",
                "groundplane",
                1,
            )
        finally:
            if original_hou is None:
                delattr(tools, "hou")
            else:
                tools.hou = original_hou
            tools.HOU_AVAILABLE = original_available

        self.assertEqual(result["status"], "ok")
        self.assertEqual(node.parm("useground").eval(), 1)

    def test_setup_rbd_fracture_builds_sop_solver_output(self):
        from houdinimind.agent import tools

        parent = _FakeFinalizerParent("/obj/rbd_geo")
        source = parent.createNode("box", "source_box")
        fake_hou = _FakeFinalizerHou(parent)
        original_hou = getattr(tools, "hou", None)
        original_available = tools.HOU_AVAILABLE

        try:
            tools.hou = fake_hou
            tools.HOU_AVAILABLE = True
            result = tools.setup_rbd_fracture(
                "/obj/rbd_geo",
                source.path(),
                num_pieces=8,
            )
        finally:
            if original_hou is None:
                delattr(tools, "hou")
            else:
                tools.hou = original_hou
            tools.HOU_AVAILABLE = original_available

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["mode"], "sop")
        self.assertEqual(result["data"]["solver"], "/obj/rbd_geo/rbd_bullet_solver")
        self.assertEqual(result["data"]["output"], "/obj/rbd_geo/rbd_out")
        solver = parent._node_map["/obj/rbd_geo/rbd_bullet_solver"]
        output = parent._node_map["/obj/rbd_geo/rbd_out"]
        self.assertEqual(solver.inputs()[0].path(), "/obj/rbd_geo/fracture1")
        self.assertEqual(output.inputs()[0].path(), "/obj/rbd_geo/rbd_bullet_solver")
        self.assertTrue(output.isDisplayFlagSet())

    def test_setup_pop_sim_uses_houdini21_pop_fallback_nodes(self):
        from houdinimind.agent import tools

        class _RejectingDopNode(_FakeFinalizerNode):
            def createNode(self, node_type, name=None):
                if node_type in {"popsolver", "popvortex"}:
                    raise RuntimeError(f"Unknown node type: {node_type}")
                return super().createNode(node_type, name)

        class _PopParent(_FakeFinalizerParent):
            def createNode(self, node_type, name=None):
                node_name = name or f"{node_type}1"
                if node_type == "dopnet":
                    node = _RejectingDopNode(self, node_name, node_type)
                    self._children.append(node)
                    self._node_map[node.path()] = node
                    return node
                return super().createNode(node_type, name)

        parent = _PopParent("/obj/pop_geo")
        source = parent.createNode("sphere", "source_sphere")
        fake_hou = _FakeFinalizerHou(parent)
        original_hou = getattr(tools, "hou", None)
        original_available = tools.HOU_AVAILABLE

        try:
            tools.hou = fake_hou
            tools.HOU_AVAILABLE = True
            result = tools.setup_pop_sim("/obj/pop_geo", source.path(), birth_rate=123)
        finally:
            if original_hou is None:
                delattr(tools, "hou")
            else:
                tools.hou = original_hou
            tools.HOU_AVAILABLE = original_available

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["node_types"]["pop_solver"], "popsolver::2.0")
        self.assertEqual(result["data"]["node_types"]["pop_force"], "popforce")
        self.assertEqual(result["data"]["solver_inputs"], {"object": 0, "source": 1, "forces": 2})
        solver = parent._node_map["/obj/pop_geo/pop_sim/popsolver1"]
        source_node = parent._node_map["/obj/pop_geo/pop_sim/popsource1"]
        force_merge = parent._node_map["/obj/pop_geo/pop_sim/merge_forces"]
        self.assertEqual(solver.inputs()[0].path(), "/obj/pop_geo/pop_sim/popobject1")
        self.assertEqual(solver.inputs()[1], source_node)
        self.assertEqual(solver.inputs()[2], force_merge)

    def test_setup_pyro_sim_builds_sop_solver_chain(self):
        from houdinimind.agent import tools

        parent = _FakeFinalizerParent("/obj/pyro_geo")
        source = parent.add_source("source_sphere", "sphere", points=42, prims=8)
        fake_hou = _FakeFinalizerHou(parent)
        original_hou = getattr(tools, "hou", None)
        original_available = tools.HOU_AVAILABLE

        try:
            tools.hou = fake_hou
            tools.HOU_AVAILABLE = True
            result = tools.setup_pyro_sim(
                "/obj/pyro_geo",
                source.path(),
                resolution_scale=4,
            )
        finally:
            if original_hou is None:
                delattr(tools, "hou")
            else:
                tools.hou = original_hou
            tools.HOU_AVAILABLE = original_available

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["mode"], "sop")
        self.assertEqual(result["data"]["source"], "/obj/pyro_geo/pyrosource1")
        self.assertEqual(result["data"]["source_points"], "/obj/pyro_geo/pyro_surface_scatter")
        self.assertEqual(
            result["data"]["source_attributes"], "/obj/pyro_geo/pyro_source_attributes"
        )
        self.assertEqual(result["data"]["source_mode"], "surface_scatter")
        self.assertEqual(
            result["data"]["required_attributes"],
            ["density", "temperature", "fuel", "v"],
        )
        self.assertEqual(
            result["data"]["rasterized_attributes"],
            ["density", "temperature", "fuel", "v"],
        )
        self.assertEqual(
            result["data"]["volume_rasterize"],
            "/obj/pyro_geo/pyro_volume_rasterize",
        )
        self.assertEqual(result["data"]["solver"], "/obj/pyro_geo/pyrosolver1")
        self.assertEqual(result["data"]["output"], "/obj/pyro_geo/pyro_out")
        scatter = parent._node_map["/obj/pyro_geo/pyro_surface_scatter"]
        attrs = parent._node_map["/obj/pyro_geo/pyro_source_attributes"]
        pyro_src = parent._node_map["/obj/pyro_geo/pyrosource1"]
        rasterize = parent._node_map["/obj/pyro_geo/pyro_volume_rasterize"]
        solver = parent._node_map["/obj/pyro_geo/pyrosolver1"]
        output = parent._node_map["/obj/pyro_geo/pyro_out"]
        self.assertEqual(scatter.inputs()[0].path(), "/obj/pyro_geo/source_sphere")
        self.assertEqual(attrs.inputs()[0].path(), "/obj/pyro_geo/pyro_surface_scatter")
        self.assertEqual(pyro_src.inputs()[0].path(), "/obj/pyro_geo/pyro_source_attributes")
        self.assertEqual(rasterize.inputs()[0].path(), "/obj/pyro_geo/pyrosource1")
        self.assertEqual(solver.inputs()[0].path(), "/obj/pyro_geo/pyro_volume_rasterize")
        self.assertEqual(rasterize.parm("attributes").eval(), "density temperature fuel v")
        self.assertEqual(output.inputs()[0].path(), "/obj/pyro_geo/pyro_postprocess")
        self.assertTrue(output.isDisplayFlagSet())

    def test_setup_pyro_sim_keeps_point_source_before_attributes(self):
        from houdinimind.agent import tools

        parent = _FakeFinalizerParent("/obj/pyro_points")
        source = parent.add_source("source_points", "add", points=12, prims=0)
        fake_hou = _FakeFinalizerHou(parent)
        original_hou = getattr(tools, "hou", None)
        original_available = tools.HOU_AVAILABLE

        try:
            tools.hou = fake_hou
            tools.HOU_AVAILABLE = True
            result = tools.setup_pyro_sim("/obj/pyro_points", source.path())
        finally:
            if original_hou is None:
                delattr(tools, "hou")
            else:
                tools.hou = original_hou
            tools.HOU_AVAILABLE = original_available

        self.assertEqual(result["status"], "ok")
        self.assertIsNone(result["data"]["source_points"])
        self.assertEqual(result["data"]["source_mode"], "keep_points")
        attrs = parent._node_map["/obj/pyro_points/pyro_source_attributes"]
        pyro_src = parent._node_map["/obj/pyro_points/pyrosource1"]
        rasterize = parent._node_map["/obj/pyro_points/pyro_volume_rasterize"]
        solver = parent._node_map["/obj/pyro_points/pyrosolver1"]
        self.assertEqual(attrs.inputs()[0].path(), "/obj/pyro_points/source_points")
        self.assertEqual(pyro_src.inputs()[0].path(), "/obj/pyro_points/pyro_source_attributes")
        self.assertEqual(rasterize.inputs()[0].path(), "/obj/pyro_points/pyrosource1")
        self.assertEqual(solver.inputs()[0].path(), "/obj/pyro_points/pyro_volume_rasterize")

    def test_setup_pyro_sim_uses_points_from_volume_for_volume_source(self):
        from houdinimind.agent import tools

        parent = _FakeFinalizerParent("/obj/pyro_volume")
        source = parent.add_source("source_volume", "volume", points=0, prims=1, prim_type="Volume")
        fake_hou = _FakeFinalizerHou(parent)
        original_hou = getattr(tools, "hou", None)
        original_available = tools.HOU_AVAILABLE

        try:
            tools.hou = fake_hou
            tools.HOU_AVAILABLE = True
            result = tools.setup_pyro_sim("/obj/pyro_volume", source.path())
        finally:
            if original_hou is None:
                delattr(tools, "hou")
            else:
                tools.hou = original_hou
            tools.HOU_AVAILABLE = original_available

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["source_points"], "/obj/pyro_volume/pyro_volume_scatter")
        self.assertEqual(result["data"]["source_mode"], "volume_scatter")
        volume_scatter = parent._node_map["/obj/pyro_volume/pyro_volume_scatter"]
        attrs = parent._node_map["/obj/pyro_volume/pyro_source_attributes"]
        pyro_src = parent._node_map["/obj/pyro_volume/pyrosource1"]
        rasterize = parent._node_map["/obj/pyro_volume/pyro_volume_rasterize"]
        solver = parent._node_map["/obj/pyro_volume/pyrosolver1"]
        self.assertEqual(volume_scatter.inputs()[0].path(), "/obj/pyro_volume/source_volume")
        self.assertEqual(attrs.inputs()[0].path(), "/obj/pyro_volume/pyro_volume_scatter")
        self.assertEqual(pyro_src.inputs()[0].path(), "/obj/pyro_volume/pyro_source_attributes")
        self.assertEqual(rasterize.inputs()[0].path(), "/obj/pyro_volume/pyrosource1")
        self.assertEqual(solver.inputs()[0].path(), "/obj/pyro_volume/pyro_volume_rasterize")

    def test_validate_fx_workflow_matrix_covers_expert_sim_and_cache_workflows(self):
        from houdinimind.agent import tools
        from tests.fake_hou import FakeCategory

        class _ObjectRoot(_FakeFinalizerParent):
            def __init__(self, path):
                super().__init__(path)
                self._child_category = FakeCategory("Object")

        parent = _ObjectRoot("/obj")
        fake_hou = _FakeFinalizerHou(parent)
        original_hou = getattr(tools, "hou", None)
        original_available = tools.HOU_AVAILABLE

        try:
            tools.hou = fake_hou
            tools.HOU_AVAILABLE = True
            result = tools.validate_fx_workflow_matrix("/obj", cook_frames=1)
        finally:
            if original_hou is None:
                delattr(tools, "hou")
            else:
                tools.hou = original_hou
            tools.HOU_AVAILABLE = original_available

        self.assertEqual(result["status"], "ok")
        data = result["data"]
        self.assertEqual(data["status"], "pass")
        self.assertEqual(data["total"], 9)
        self.assertEqual(data["passed"], 9)
        self.assertEqual(
            data["workflows"],
            [
                "flip",
                "vellum_cloth",
                "vellum_pillow",
                "rbd",
                "pyro",
                "pop",
                "grains",
                "wire",
                "cache_export",
            ],
        )
        rows = {row["workflow"]: row for row in data["rows"]}
        self.assertEqual(
            rows["flip"]["result"]["solver"], "/obj/hm_validate_flip/flip_dopnet/flipsolver1"
        )
        self.assertEqual(
            rows["pyro"]["result"]["volume_rasterize"],
            "/obj/hm_validate_pyro/pyro_volume_rasterize",
        )
        vellum_cache = parent._node_map["/obj/hm_validate_vellum_cloth/vellum_cache"]
        self.assertEqual(
            vellum_cache.inputs()[1].path(), "/obj/hm_validate_vellum_cloth/vellum_solver"
        )
        self.assertEqual(rows["grains"]["result"]["dopnet"], "/obj/grain_sim")
        self.assertEqual(rows["grains"]["result"]["solver"], "/obj/grain_sim/pop_solver")
        grain_solver = parent._node_map["/obj/grain_sim/pop_solver"]
        self.assertEqual(grain_solver.inputs()[0].path(), "/obj/grain_sim/grain_object")
        self.assertEqual(grain_solver.inputs()[1].path(), "/obj/grain_sim/grain_source")
        self.assertEqual(grain_solver.inputs()[2].path(), "/obj/grain_sim/pop_grains")
        self.assertEqual(rows["wire"]["result"]["solver"], "/obj/wire_sim/wire_solver")
        self.assertTrue(os.path.exists(rows["cache_export"]["result"]["export"]["exported_to"]))
        self.assertIn("validate_fx_workflow_matrix", tools.TOOL_FUNCTIONS)

    def test_create_node_chain_inserts_pyro_volume_rasterize_before_solver(self):
        from houdinimind.agent import tools

        parent = _FakeFinalizerParent("/obj/pyro_chain")
        fake_hou = _FakeFinalizerHou(parent)
        original_hou = getattr(tools, "hou", None)
        original_available = tools.HOU_AVAILABLE

        try:
            tools.hou = fake_hou
            tools.HOU_AVAILABLE = True
            result = tools.create_node_chain(
                "/obj/pyro_chain",
                [
                    {"type": "pyrosource", "name": "pyrosource1"},
                    {"type": "pyrosolver", "name": "pyrosolver1"},
                    {"type": "null", "name": "pyro_out"},
                ],
            )
        finally:
            if original_hou is None:
                delattr(tools, "hou")
            else:
                tools.hou = original_hou
            tools.HOU_AVAILABLE = original_available

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["count"], 4)
        rasterize = parent._node_map["/obj/pyro_chain/pyro_volume_rasterize"]
        solver = parent._node_map["/obj/pyro_chain/pyrosolver1"]
        self.assertEqual(rasterize.inputs()[0].path(), "/obj/pyro_chain/pyrosource1")
        self.assertEqual(solver.inputs()[0].path(), "/obj/pyro_chain/pyro_volume_rasterize")
        self.assertEqual(rasterize.parm("attributes").eval(), "density temperature fuel v")

    def test_safe_set_parameter_resolves_exact_parameter_label(self):
        from houdinimind.agent import tools

        node = _FakeParmNode(
            "/obj/geo1/rbdbulletsolver1",
            type_name="rbdbulletsolver",
            parms={"useground": (0, "Use Ground Plane")},
        )
        original_hou = getattr(tools, "hou", None)
        original_available = tools.HOU_AVAILABLE

        try:
            tools.hou = FakeHou({"/obj/geo1/rbdbulletsolver1": node})
            tools.HOU_AVAILABLE = True
            result = tools.safe_set_parameter(
                "/obj/geo1/rbdbulletsolver1",
                "Use Ground Plane",
                1,
            )
        finally:
            if original_hou is None:
                delattr(tools, "hou")
            else:
                tools.hou = original_hou
            tools.HOU_AVAILABLE = original_available

        self.assertEqual(result["status"], "ok")
        self.assertEqual(node.parm("useground").eval(), 1)

    def test_safe_set_parameter_resolver_blocks_loose_fuzzy_write(self):
        from houdinimind.agent import tools

        node = _FakeParmNode(
            "/obj/geo1/box1",
            type_name="box",
            parms={"scale": 1},
        )
        original_hou = getattr(tools, "hou", None)
        original_available = tools.HOU_AVAILABLE

        try:
            tools.hou = FakeHou({"/obj/geo1/box1": node})
            tools.HOU_AVAILABLE = True
            result = tools.safe_set_parameter("/obj/geo1/box1", "sale", 5)
        finally:
            if original_hou is None:
                delattr(tools, "hou")
            else:
                tools.hou = original_hou
            tools.HOU_AVAILABLE = original_available

        self.assertEqual(result["status"], "error")
        self.assertEqual(node.parm("scale").eval(), 1)
        self.assertIn("Parameter 'sale' not found", result["message"])

    def test_tool_validator_normalizes_parameter_name_alias(self):
        from houdinimind.agent.tool_models import ToolValidator
        from houdinimind.agent.tools._registry import TOOL_SCHEMAS

        validator = ToolValidator(TOOL_SCHEMAS)
        cleaned = validator.validate(
            "safe_set_parameter",
            {
                "node_path": "/obj/geo1/rbdbulletsolver1",
                "parameter_name": "useground",
                "value": "1",
            },
        )

        self.assertEqual(cleaned["parm_name"], "useground")
        self.assertNotIn("parameter_name", cleaned)

    def test_tool_validator_normalizes_connect_node_aliases(self):
        from houdinimind.agent.tool_models import ToolValidator
        from houdinimind.agent.tools._registry import TOOL_SCHEMAS

        validator = ToolValidator(TOOL_SCHEMAS)
        cleaned = validator.validate(
            "connect_nodes",
            {
                "source_node": "/obj/geo1/scatter1",
                "target_node": "/obj/geo1/facet1",
                "input_index": "0",
            },
        )

        self.assertEqual(cleaned["from_path"], "/obj/geo1/scatter1")
        self.assertEqual(cleaned["to_path"], "/obj/geo1/facet1")
        self.assertEqual(cleaned["to_in"], 0)
        self.assertNotIn("source_node", cleaned)
        self.assertNotIn("target_node", cleaned)

    def test_tool_validator_normalizes_connect_port_aliases(self):
        from houdinimind.agent.tool_models import ToolValidator
        from houdinimind.agent.tools._registry import TOOL_SCHEMAS

        validator = ToolValidator(TOOL_SCHEMAS)
        cleaned = validator.validate(
            "connect_nodes",
            {
                "from_path": "/obj/geo1/box1",
                "to_path": "/obj/geo1/xform1",
                "from_output": "1",
                "to_input": "2",
            },
        )

        self.assertEqual(cleaned["from_path"], "/obj/geo1/box1")
        self.assertEqual(cleaned["to_path"], "/obj/geo1/xform1")
        self.assertEqual(cleaned["from_out"], 1)
        self.assertEqual(cleaned["to_in"], 2)
        self.assertNotIn("from_output", cleaned)
        self.assertNotIn("to_input", cleaned)

    def test_tool_validator_rejects_invalid_enum_value(self):
        from houdinimind.agent.tool_models import ToolArgumentError, ToolValidator
        from houdinimind.agent.tools._registry import TOOL_SCHEMAS

        validator = ToolValidator(TOOL_SCHEMAS)

        with self.assertRaises(ToolArgumentError):
            validator.validate("list_node_types", {"category": "definitely_not_a_category"})

    def test_tool_schemas_expose_signature_controls(self):
        from houdinimind.agent.tools._registry import TOOL_SCHEMAS

        schemas = {
            schema["function"]["name"]: schema["function"]["parameters"]["properties"]
            for schema in TOOL_SCHEMAS
        }

        self.assertIn("compact", schemas["get_node_parameters"])
        self.assertIn("only_connected", schemas["get_node_inputs"])
        self.assertIn("max_inputs", schemas["get_node_inputs"])
        self.assertIn("max_attribs", schemas["get_geometry_attributes"])
        self.assertIn("cleanup_on_error", schemas["create_node_chain"])
        self.assertIn("cook", schemas["create_node"])
        self.assertIn("extra_parameters", schemas["convert_network_to_hda"])
        self.assertIn("max_total_seconds", schemas["cook_network_range"])

    def test_agent_loop_image_hash_normalizes_base64_payload(self):
        from houdinimind.agent.loop import AgentLoop

        raw_hash = AgentLoop._compute_image_hash("aGVsbG8=")
        spaced_hash = AgentLoop._compute_image_hash("data:image/png;base64,aG Vs\nbG8=")

        self.assertEqual(raw_hash, spaced_hash)
        self.assertEqual(len(raw_hash), 64)

    def test_tool_validator_infers_null_node_type_from_name(self):
        from houdinimind.agent.tool_models import ToolValidator
        from houdinimind.agent.tools._registry import TOOL_SCHEMAS

        validator = ToolValidator(TOOL_SCHEMAS)
        cleaned = validator.validate(
            "create_node",
            {
                "parent_path": "/obj/geo1",
                "node_type": "",
                "name": "null1",
            },
        )

        self.assertEqual(cleaned["node_type"], "null")

    def test_safe_set_parameter_does_not_apply_fuzzy_wrong_parameter(self):
        from houdinimind.agent import tools

        node = _FakeParmNode(
            "/obj/geo1/fracture1",
            type_name="rbdmaterialfracture::3.0",
            parms={"cutpiecesgroup": ""},
        )
        original_hou = getattr(tools, "hou", None)
        original_available = tools.HOU_AVAILABLE

        try:
            tools.hou = FakeHou({"/obj/geo1/fracture1": node})
            tools.HOU_AVAILABLE = True
            result = tools.safe_set_parameter("/obj/geo1/fracture1", "numpieces", 150)
        finally:
            if original_hou is None:
                delattr(tools, "hou")
            else:
                tools.hou = original_hou
            tools.HOU_AVAILABLE = original_available

        self.assertEqual(result["status"], "error")
        self.assertEqual(node.parm("cutpiecesgroup").eval(), "")
        self.assertIn("Parameter 'numpieces' not found", result["message"])

    def test_safe_set_parameter_maps_vex_code_to_snippet(self):
        import houdinimind.agent.tools._node_tools as node_tools
        from houdinimind.agent import tools

        node = _FakeParmNode(
            "/obj/geo1/wrangle1",
            type_name="attribwrangle",
            parms={"snippet": ""},
        )
        original_hou = getattr(tools, "hou", None)
        original_available = tools.HOU_AVAILABLE
        original_validator = node_tools._validate_vex_with_checker

        try:
            tools.hou = FakeHou({"/obj/geo1/wrangle1": node})
            tools.HOU_AVAILABLE = True
            node_tools._validate_vex_with_checker = lambda _code: {
                "success": True,
                "errors": [],
                "warnings": [],
                "status": "fallback",
            }
            result = tools.safe_set_parameter(
                "/obj/geo1/wrangle1",
                "vex_code",
                "@Cd = {1, 0, 0};",
            )
        finally:
            if original_hou is None:
                delattr(tools, "hou")
            else:
                tools.hou = original_hou
            tools.HOU_AVAILABLE = original_available
            node_tools._validate_vex_with_checker = original_validator

        self.assertEqual(result["status"], "ok")
        self.assertEqual(node.parm("snippet").eval(), "@Cd = {1, 0, 0};")

    def test_safe_set_parameter_rejects_invalid_vex_snippet(self):
        import houdinimind.agent.tools._node_tools as node_tools
        from houdinimind.agent import tools

        node = _FakeParmNode(
            "/obj/geo1/wrangle1",
            type_name="attribwrangle",
            parms={"snippet": "@P.y += 1;"},
        )
        original_hou = getattr(tools, "hou", None)
        original_available = tools.HOU_AVAILABLE
        original_validator = node_tools._validate_vex_with_checker

        try:
            tools.hou = FakeHou({"/obj/geo1/wrangle1": node})
            tools.HOU_AVAILABLE = True
            node_tools._validate_vex_with_checker = lambda _code: {
                "success": False,
                "errors": ["Call to undefined function 'rayhittest'"],
                "warnings": [],
                "status": "fallback",
            }
            result = tools.safe_set_parameter(
                "/obj/geo1/wrangle1",
                "snippet",
                "float d = rayhittest(@P, {0,1,0}, 0.1);",
            )
        finally:
            if original_hou is None:
                delattr(tools, "hou")
            else:
                tools.hou = original_hou
            tools.HOU_AVAILABLE = original_available
            node_tools._validate_vex_with_checker = original_validator

        self.assertEqual(result["status"], "error")
        self.assertIn("VEX validation failed", result["message"])
        self.assertEqual(node.parm("snippet").eval(), "@P.y += 1;")

    def test_execute_python_blocks_direct_wrangle_snippet_write(self):
        from houdinimind.agent import tools

        result = tools.execute_python(
            "node = hou.node('/obj/geo1/wrangle1')\nnode.parm('snippet').set('@P.y += 1;')\n"
        )

        self.assertEqual(result["status"], "error")
        self.assertIn("write_vex_code", result["message"])

    def test_attempt_parameter_recovery_rejects_semantically_different_fuzzy_match(self):
        import houdinimind.agent.loop as loop_mod
        from houdinimind.agent.loop import AgentLoop

        tmp = _workspace_case_dir("param_recovery_reject_fuzzy")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        loop = AgentLoop({"data_dir": tmp, "ollama_url": "http://localhost:11434"})
        original_tools = dict(loop_mod.TOOL_FUNCTIONS)
        original_hou_call = loop._hou_call

        calls = {"safe_set_parameter": 0}

        def fake_get_node_parameters(node_path, compact=False):
            return {
                "status": "ok",
                "data": {
                    "parameters": {
                        "speed": {"type": "Float"},
                    }
                },
            }

        def fake_safe_set_parameter(node_path, parm_name, value):
            calls["safe_set_parameter"] += 1
            return {"status": "ok", "data": {"node_path": node_path, "parm_name": parm_name}}

        try:
            loop_mod.TOOL_FUNCTIONS["get_node_parameters"] = fake_get_node_parameters
            loop_mod.TOOL_FUNCTIONS["safe_set_parameter"] = fake_safe_set_parameter
            loop._hou_call = lambda fn, **kwargs: fn(**kwargs)

            recovered = loop._attempt_parameter_recovery(
                "safe_set_parameter",
                {"node_path": "/obj/geo1/box1", "parm_name": "seed", "value": 7},
                {"status": "error", "message": "Parameter 'seed' not found"},
            )
        finally:
            loop_mod.TOOL_FUNCTIONS.clear()
            loop_mod.TOOL_FUNCTIONS.update(original_tools)
            loop._hou_call = original_hou_call

        self.assertIsNone(recovered)
        self.assertEqual(calls["safe_set_parameter"], 0)

    def test_attempt_parameter_recovery_allows_component_to_tuple_base(self):
        import houdinimind.agent.loop as loop_mod
        from houdinimind.agent.loop import AgentLoop

        tmp = _workspace_case_dir("param_recovery_component_base")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        loop = AgentLoop({"data_dir": tmp, "ollama_url": "http://localhost:11434"})
        original_tools = dict(loop_mod.TOOL_FUNCTIONS)
        original_hou_call = loop._hou_call

        def fake_get_node_parameters(node_path, compact=False):
            return {
                "status": "ok",
                "data": {
                    "parameters": {
                        "size": {"type": "tuple"},
                    }
                },
            }

        def fake_set_parameter(node_path, parm_name, value):
            return {
                "status": "ok",
                "message": "set",
                "data": {"node_path": node_path, "parm_name": parm_name, "value": value},
            }

        try:
            loop_mod.TOOL_FUNCTIONS["get_node_parameters"] = fake_get_node_parameters
            loop_mod.TOOL_FUNCTIONS["set_parameter"] = fake_set_parameter
            loop._hou_call = lambda fn, **kwargs: fn(**kwargs)

            recovered = loop._attempt_parameter_recovery(
                "set_parameter",
                {
                    "node_path": "/obj/geo1/box1",
                    "parm_name": "sizex",
                    "value": [2.0, 0.5, 1.5],
                },
                {"status": "error", "message": "Parameter 'sizex' not found"},
            )
        finally:
            loop_mod.TOOL_FUNCTIONS.clear()
            loop_mod.TOOL_FUNCTIONS.update(original_tools)
            loop._hou_call = original_hou_call

        self.assertIsNotNone(recovered)
        self.assertEqual(recovered["status"], "ok")
        self.assertTrue(recovered.get("_meta", {}).get("auto_param_recovery"))
        self.assertEqual(recovered.get("_meta", {}).get("auto_recovered_to"), "size")

    def test_resolve_build_hints_suggests_canonical_parameter_names(self):
        from houdinimind.agent import tools

        node = _FakeParmNode(
            "/obj/geo1/xform1",
            type_name="xform",
            parms={"tx": 0, "ty": 0, "tz": 0, "scale": 1},
        )
        original_hou = getattr(tools, "hou", None)
        original_available = tools.HOU_AVAILABLE

        try:
            tools.hou = FakeHou({"/obj/geo1/xform1": node})
            tools.HOU_AVAILABLE = True
            result = tools.resolve_build_hints(
                goal="move the object to the side",
                node_path="/obj/geo1/xform1",
                parm_name="centerx",
            )
        finally:
            if original_hou is None:
                delattr(tools, "hou")
            else:
                tools.hou = original_hou
            tools.HOU_AVAILABLE = original_available

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["resolved_node_type"], "xform")
        self.assertIn("tx", result["data"]["parm_suggestions"])

    def test_batch_set_parameters_returns_error_on_partial_failure(self):
        from houdinimind.agent import tools

        node = _FakeParmNode("/obj/geo1/tabletop", parms={"sizex": 0})
        original_hou = getattr(tools, "hou", None)
        original_available = tools.HOU_AVAILABLE

        try:
            tools.hou = FakeHou({"/obj/geo1/tabletop": node})
            tools.HOU_AVAILABLE = True
            result = tools.batch_set_parameters(
                [
                    {"node_path": "/obj/geo1/tabletop", "parm_name": "sizex", "value": 2},
                    {"node_path": "/obj/geo1/tabletop", "parm_name": "missingparm", "value": 1},
                ]
            )
        finally:
            if original_hou is None:
                delattr(tools, "hou")
            else:
                tools.hou = original_hou
            tools.HOU_AVAILABLE = original_available

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["data"]["failed"], 1)
        self.assertEqual(node.parm("sizex").eval(), 2)

    def test_finalize_sop_network_reuses_existing_terminal_merge(self):
        from houdinimind.agent import tools

        parent = _FakeFinalizerParent("/obj/geo1")
        merge = _FakeFinalizerNode(parent, "merge_table", "merge", points=8, prims=6)
        parent.add_child(merge)

        original_hou = getattr(tools, "hou", None)
        original_available = tools.HOU_AVAILABLE

        try:
            tools.hou = _FakeFinalizerHou(parent)
            tools.HOU_AVAILABLE = True
            result = tools.finalize_sop_network(
                "/obj/geo1",
                output_name="OUT",
                merge_name="merge_table",
            )
        finally:
            if original_hou is None:
                delattr(tools, "hou")
            else:
                tools.hou = original_hou
            tools.HOU_AVAILABLE = original_available

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["output_path"], "/obj/geo1/OUT")
        self.assertIsNone(result["data"]["merge_path"])
        self.assertEqual(result["data"]["source_paths"], ["/obj/geo1/merge_table"])

    def test_create_node_accepts_object_root_alias(self):
        from houdinimind.agent import tools

        parent = FakeParentNode("/obj")
        original_hou = getattr(tools, "hou", None)
        original_available = tools.HOU_AVAILABLE

        try:
            tools.hou = FakeHou({"/obj": parent})
            tools.HOU_AVAILABLE = True
            result = tools.create_node("/object", "geo", "geo1")
        finally:
            if original_hou is None:
                delattr(tools, "hou")
            else:
                tools.hou = original_hou
            tools.HOU_AVAILABLE = original_available

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["path"], "/obj/geo1")
        self.assertEqual(parent.created[0][0], "geo")
        self.assertEqual(parent.created[0][1], "geo1")

    def test_hou_call_executes_directly_on_main_thread(self):
        import sys

        from houdinimind.agent.loop import AgentLoop

        fake_hdefereval = _FakeHdefereval()
        original_module = sys.modules.get("hdefereval")

        try:
            sys.modules["hdefereval"] = fake_hdefereval
            result = AgentLoop._hou_call(lambda value: value + 1, value=41)
        finally:
            if original_module is None:
                sys.modules.pop("hdefereval", None)
            else:
                sys.modules["hdefereval"] = original_module

        self.assertEqual(result, 42)
        self.assertEqual(fake_hdefereval.calls, 0)

    def test_hou_call_dispatch_binds_code_kwarg_before_hdefereval(self):
        import sys
        from concurrent.futures import ThreadPoolExecutor

        from houdinimind.agent.loop import AgentLoop

        class FakeHdeferevalWithCodeParam:
            def __init__(self):
                self.calls = 0

            def executeInMainThreadWithResult(self, code):
                self.calls += 1
                return code()

        fake_hdefereval = FakeHdeferevalWithCodeParam()
        original_module = sys.modules.get("hdefereval")

        def run_call():
            return AgentLoop._hou_call(lambda code: f"ran:{code}", code="print('ok')")

        try:
            sys.modules["hdefereval"] = fake_hdefereval
            with ThreadPoolExecutor(max_workers=1) as pool:
                result = pool.submit(run_call).result(timeout=5)
        finally:
            if original_module is None:
                sys.modules.pop("hdefereval", None)
            else:
                sys.modules["hdefereval"] = original_module

        self.assertEqual(result, "ran:print('ok')")
        self.assertEqual(fake_hdefereval.calls, 1)

    def test_parameter_resolution_does_not_call_llm_fuzzy_matcher(self):
        from houdinimind.agent.tools import _core

        calls = []
        original_chat = _core._shared_chat_simple_fn

        def fail_if_called(**_kwargs):
            calls.append(_kwargs)
            raise AssertionError("parameter resolution must not call the LLM")

        try:
            _core._shared_chat_simple_fn = fail_if_called
            result = _core._resolve_parameter_name(
                "origin",
                ["originx", "originy", "originz", "dirx", "diry", "dirz"],
                node_type="line",
            )
        finally:
            _core._shared_chat_simple_fn = original_chat

        self.assertEqual(result["status"], "unresolved")
        self.assertEqual(calls, [])

    def test_query_needs_workflow_grounding_requires_explicit_workflow_or_multi_part_asset(self):
        from houdinimind.agent.request_modes import _query_needs_workflow_grounding

        self.assertFalse(_query_needs_workflow_grounding("make a sphere"))
        self.assertFalse(_query_needs_workflow_grounding("move the box up"))
        self.assertTrue(_query_needs_workflow_grounding("build a table"))
        self.assertTrue(_query_needs_workflow_grounding("show me the workflow for a sphere"))

    def test_detect_table_leg_support_issues_flags_floating_legs(self):
        from houdinimind.agent.loop import AgentLoop

        bbox_map = {
            "/obj/geo1/tabletop": {
                "min": [-1.0, 0.45, -0.5],
                "max": [1.0, 0.55, 0.5],
            },
            "/obj/geo1/leg1": {
                "min": [-0.95, -0.5, -0.45],
                "max": [-0.85, 0.0, -0.35],
            },
            "/obj/geo1/leg2": {
                "min": [0.85, -0.5, -0.45],
                "max": [0.95, 0.0, -0.35],
            },
        }

        issues = AgentLoop._detect_table_leg_support_issues(
            bbox_map,
            "/obj/geo1/tabletop",
            ["/obj/geo1/leg1", "/obj/geo1/leg2"],
        )

        self.assertEqual(len(issues), 2)
        self.assertTrue(all(issue["severity"] == "repair" for issue in issues))
        self.assertIn("does not support the tabletop", issues[0]["message"])

    def test_apply_scope_filter_keeps_direct_keyframe_tools(self):
        import houdinimind.agent.tools as tools_mod

        filtered_funcs, filtered_schemas = tools_mod.apply_scope_filter({"modeling_fx_only": True})
        schema_names = {
            s.get("function", {}).get("name") for s in filtered_schemas if isinstance(s, dict)
        }

        for tool_name in (
            "set_keyframe",
            "delete_keyframe",
            "get_timeline_keyframes",
            "set_frame_range",
            "go_to_frame",
            "edit_animation_curve",
        ):
            self.assertIn(tool_name, filtered_funcs)
            self.assertIn(tool_name, schema_names)

    def test_self_updater_preserves_existing_guidance(self):
        from houdinimind.memory.memory_manager import SelfUpdater

        class FakeRecipeBook:
            def get_all(self, min_confidence=0.5):
                return [
                    {
                        "name": "test_recipe",
                        "description": "Test recipe",
                        "steps": [{"tool": "create_node", "args": {"node_type": "box"}}],
                        "confidence": 0.8,
                        "domain": "general",
                    }
                ]

            def decay_stale(self):
                return None

        tmp = _workspace_case_dir("self_updater")
        try:
            learned_path = os.path.join(tmp, "system_prompt_learned.txt")
            with open(learned_path, "w", encoding="utf-8") as f:
                f.write(
                    "# Learned knowledge (auto-generated — do not edit manually)\n"
                    "# Last updated: 2026-03-31 13:29\n\n"
                    "## High-confidence workflow recipes\n\n"
                    "## Domain observations\n\n"
                    "## Behavioural guidance (learned from accepted interactions)\n"
                    "- Prefer suggesting specific parameter values over generic advice.\n"
                    "- When the user accepts a suggestion, remember it for similar future situations.\n"
                    "- High-confidence recipes should be offered proactively when context matches.\n"
                    "- **Custom Guidance**: Keep this line.\n"
                )

            updater = SelfUpdater(FakeRecipeBook(), tmp)
            content = updater.update()
            del updater
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        self.assertIn("**Custom Guidance**: Keep this line.", content)

    def test_dry_run_simulates_write_tools_with_virtual_paths(self):
        from houdinimind.agent.loop import AgentLoop

        tmp = _workspace_case_dir("dry_run_create")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        loop = AgentLoop({"data_dir": tmp, "ollama_url": "http://localhost:11434"})
        result = loop._execute_tool(
            "create_node",
            {"parent_path": "/obj/geo1", "node_type": "box", "name": "box1"},
            dry_run=True,
        )

        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["_meta"]["dry_run"])
        self.assertEqual(result["data"]["path"], "/obj/geo1/box1")

    def test_dry_run_simulates_finalize_sop_network_output_paths(self):
        from houdinimind.agent.loop import AgentLoop

        tmp = _workspace_case_dir("dry_run_finalize")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        loop = AgentLoop({"data_dir": tmp, "ollama_url": "http://localhost:11434"})
        result = loop._execute_tool(
            "finalize_sop_network",
            {"parent_path": "/obj/geo_table"},
            dry_run=True,
        )

        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["_meta"]["dry_run"])
        self.assertEqual(result["data"]["output_path"], "/obj/geo_table/OUT")
        self.assertEqual(result["data"]["merge_path"], "/obj/geo_table/MERGE_FINAL")

    def test_fast_mode_keeps_long_timeout_for_create_node_chain(self):
        from houdinimind.agent.loop import AgentLoop

        tmp = _workspace_case_dir("fast_mode_hou_timeout")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        loop = AgentLoop(
            {
                "data_dir": tmp,
                "ollama_url": "http://localhost:11434",
                "fast_read_hou_call_timeout_s": 15,
                "fast_write_hou_call_timeout_s": 90,
            }
        )
        loop._fast_message_mode = True

        self.assertEqual(loop._tool_hou_timeout("get_scene_summary", is_read=True), 15)
        self.assertEqual(loop._tool_hou_timeout("create_node_chain", is_read=False), 180)
        self.assertEqual(loop._tool_hou_timeout("setup_pyro_sim", is_read=False), 240)

    def test_build_queries_surface_finalize_tool(self):
        from houdinimind.agent.llm_client import OllamaClient
        from houdinimind.agent.tools import TOOL_SCHEMAS

        client = OllamaClient({"ollama_url": "http://localhost:11434"})
        selected = client.select_relevant_tools(
            "build a table and make sure the final output is merged and visible",
            TOOL_SCHEMAS,
            top_n=20,
        )
        names = [s.get("function", {}).get("name") for s in selected]
        self.assertIn("finalize_sop_network", names)
        self.assertNotIn("capture_pane", names[:12])

    def test_build_mode_disabled_tools_keep_workflow_grounding_for_asset_queries(self):
        from houdinimind.agent.loop import _build_mode_disabled_tools_for_query

        primitive_disabled = _build_mode_disabled_tools_for_query("create a box with rounded edges")
        asset_disabled = _build_mode_disabled_tools_for_query("create a table")

        self.assertIn("search_knowledge", primitive_disabled)
        self.assertIn("suggest_workflow", primitive_disabled)
        self.assertNotIn("search_knowledge", asset_disabled)
        self.assertNotIn("suggest_workflow", asset_disabled)

    def test_build_mode_guidance_includes_step_zero_plan_instruction(self):
        from houdinimind.agent.loop import AgentLoop

        tmp = _workspace_case_dir("build_guidance_step_zero")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        loop = AgentLoop({"data_dir": tmp, "ollama_url": "http://localhost:11434"})

        guidance = loop._build_mode_guidance("build", "Create a table")

        self.assertIn("STEP 0", guidance)
        self.assertIn("STEP 1 — PLAN", guidance)
        self.assertIn("Before calling create_node()", guidance)
        self.assertIn("resolve_build_hints()", guidance)

    def test_truncate_tool_history_enforces_hard_message_cap(self):
        from houdinimind.agent.loop import AgentLoop

        tmp = _workspace_case_dir("truncate_tool_history_cap")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        loop = AgentLoop({"data_dir": tmp, "ollama_url": "http://localhost:11434"})
        messages = [{"role": "system", "content": "sys"}]
        for idx in range(8):
            messages.append({"role": "user", "content": f"user {idx}"})
            messages.append({"role": "assistant", "content": f"assistant {idx}"})

        truncated = loop._truncate_tool_history(messages, max_messages=6)

        self.assertEqual(truncated[0]["role"], "system")
        self.assertLessEqual(len(truncated), 6)
        self.assertEqual(truncated[-1]["content"], "assistant 7")

    def test_reset_conversation_persists_cleared_history(self):
        from houdinimind.agent.loop import AgentLoop

        tmp = _workspace_case_dir("reset_conversation_persists")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))

        class _FakeMemory:
            def __init__(self):
                self.saved = []

            def load_conversation(self):
                return [
                    {"role": "system", "content": "old system"},
                    {"role": "user", "content": "old chat"},
                ]

            def save_conversation(self, conversation):
                self.saved.append(list(conversation))

        memory = _FakeMemory()
        loop = AgentLoop(
            {"data_dir": tmp, "ollama_url": "http://localhost:11434"},
            memory_manager=memory,
        )
        loop.conversation.extend(
            [
                {"role": "user", "content": "create a sphere"},
                {"role": "assistant", "content": "Done."},
            ]
        )

        loop.reset_conversation()
        restored = memory.saved[-1]

        self.assertEqual(len(restored), 1)
        self.assertEqual(restored[0]["role"], "system")
        self.assertNotIn("create a sphere", json.dumps(restored))

    def test_tool_schema_selection_is_cached_within_turn(self):
        from houdinimind.agent.loop import AgentLoop

        tmp = _workspace_case_dir("tool_schema_turn_cache")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        loop = AgentLoop({"data_dir": tmp, "ollama_url": "http://localhost:11434"})
        calls = {"count": 0}
        original_select = loop.llm.select_relevant_tools

        def fake_select_relevant_tools(query, all_schemas, top_n=None):
            calls["count"] += 1
            return [{"function": {"name": "create_node"}}]

        try:
            loop.llm.select_relevant_tools = fake_select_relevant_tools
            loop._reset_turn_state()
            first = loop._get_tool_schemas_for_request("Create a table", "build")
            second = loop._get_tool_schemas_for_request("Create a table", "build")
        finally:
            loop.llm.select_relevant_tools = original_select

        self.assertEqual(calls["count"], 1)
        self.assertEqual(first, second)

    def test_generate_plan_includes_workflow_grounding_context(self):
        from houdinimind.agent.loop import AgentLoop

        tmp = _workspace_case_dir("plan_grounding")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        # Force-enable the planner: fast_execution would otherwise disable it.
        loop = AgentLoop(
            {
                "data_dir": tmp,
                "ollama_url": "http://localhost:11434",
                "plan_enabled": True,
                "fast_execution": False,
            }
        )
        captured = {}

        def fake_generate_plan(user_goal, scene_context=""):
            captured["user_goal"] = user_goal
            captured["scene_context"] = scene_context
            return {"mission": "Create a table", "phases": []}

        original_generate_plan = loop._planner.generate_plan
        try:
            loop._planner.generate_plan = fake_generate_plan
            plan = loop._generate_plan(
                "Create a procedural table using a VEX wrangle and USD-ready material setup",
                "build",
                workflow_grounding="[WORKFLOW GROUNDING]\n- Node Chain: Procedural Four-Legged Table",
            )
        finally:
            loop._planner.generate_plan = original_generate_plan

        self.assertEqual(plan["mission"], "Create a table")
        self.assertIn("Procedural Four-Legged Table", captured["scene_context"])

    def test_planner_sanitizes_to_prototype_level_details(self):
        from houdinimind.agent.sub_agents import PlannerAgent

        plan = PlannerAgent._parse_plan(
            json.dumps(
                {
                    "mission": "Fracture table",
                    "prototype_scale": {
                        "unit": "Houdini units",
                        "overall_size": "2 x 1 x 1",
                    },
                    "phases": [
                        {
                            "phase": "Setup",
                            "steps": [
                                {
                                    "step": 99,
                                    "action": "Create RBD material fracture node after /obj/geo1/merge1",
                                    "node_type": "rbdmaterialfracture",
                                    "recommended_tools": ["create_node"],
                                    "prototype_detail": "RBD bullet solver node makes pieces fall",
                                    "placement": "downstream from OUT null",
                                    "validation": "parameters should show no red errors",
                                    "relationships": [
                                        "wire connection from /obj/geo1/a to /obj/geo1/b"
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ),
            "Fracture table",
        )

        step = plan["phases"][0]["steps"][0]
        self.assertEqual(step["step"], 1)
        self.assertIn("node_type", step)
        self.assertEqual(step["node_type"], "rbdmaterialfracture")
        self.assertNotIn("recommended_tools", step)
        self.assertIn("/obj/geo1/merge1", step["action"])
        self.assertIn("wire connection from /obj/geo1/a to /obj/geo1/b", step["relationships"])

    def test_query_is_complex_skips_simple_asset_builds(self):
        from houdinimind.agent.loop import _query_is_complex

        self.assertFalse(_query_is_complex("Create a procedural table with a visible OUT node."))
        self.assertTrue(
            _query_is_complex(
                "Debug why the vellum simulation keeps failing after I added a wrangle and USD export."
            )
        )

    def test_generate_plan_times_out_gracefully(self):
        from houdinimind.agent.loop import AgentLoop

        tmp = _workspace_case_dir("plan_timeout")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        loop = AgentLoop({"data_dir": tmp, "ollama_url": "http://localhost:11434"})
        original_execute_with_timeout = loop._execute_with_timeout

        try:
            loop._execute_with_timeout = lambda func, timeout_s, **kwargs: (
                None,
                "planning timed out",
            )
            plan = loop._generate_plan(
                "Debug why the vellum simulation keeps failing after I added a wrangle and USD export.",
                "debug",
            )
        finally:
            loop._execute_with_timeout = original_execute_with_timeout

        self.assertIsNone(plan)

    def test_run_verification_suite_flags_single_primitive_asset_mismatch(self):
        import houdinimind.agent.loop as loop_mod
        from houdinimind.agent.loop import AgentLoop

        tmp = _workspace_case_dir("goal_match_verification")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        loop = AgentLoop({"data_dir": tmp, "ollama_url": "http://localhost:11434"})
        original_hou_available = loop_mod.HOU_AVAILABLE
        original_lookup = loop._lookup_workflow_reference_hits
        original_observation = loop._run_observation_tool
        original_network_review = loop._analyze_network_view

        before_snapshot = {"nodes": [], "connections": [], "error_count": 0}
        after_snapshot = {
            "nodes": [
                {
                    "path": "/obj/geo1/sphere1",
                    "type": "sphere",
                    "category": "Sop",
                    "outputs": [{"to_node": "/obj/geo1/out1"}],
                    "is_displayed": False,
                    "is_render_flag": False,
                },
                {
                    "path": "/obj/geo1/out1",
                    "type": "null",
                    "category": "Sop",
                    "outputs": [{"to_node": "/obj/geo1/OUT"}],
                    "is_displayed": False,
                    "is_render_flag": False,
                },
                {
                    "path": "/obj/geo1/OUT",
                    "type": "null",
                    "category": "Sop",
                    "outputs": [],
                    "is_displayed": True,
                    "is_render_flag": True,
                },
            ],
            "connections": [
                {"from": "/obj/geo1/sphere1", "to": "/obj/geo1/out1", "to_input": 0},
                {"from": "/obj/geo1/out1", "to": "/obj/geo1/OUT", "to_input": 0},
            ],
            "error_count": 0,
        }

        def fake_observation(tool_name, args, stream_callback=None):
            if tool_name == "get_all_errors":
                return {"status": "ok", "data": {"nodes": []}}
            if tool_name == "get_geometry_attributes":
                return {"status": "ok", "data": {"point_count": 8}}
            if tool_name == "get_node_inputs":
                return {"status": "ok", "data": {"inputs": []}}
            return {"status": "ok", "data": {}}

        try:
            loop_mod.HOU_AVAILABLE = True
            loop._lookup_workflow_reference_hits = lambda query, top_k=3: [
                {"title": "Node Chain: Procedural Four-Legged Table"}
            ]
            loop._run_observation_tool = fake_observation
            loop._analyze_network_view = lambda *args, **kwargs: None
            report = loop._run_verification_suite(
                "Create a table",
                before_snapshot,
                after_snapshot,
                "build",
            )
        finally:
            loop_mod.HOU_AVAILABLE = original_hou_available
            loop._lookup_workflow_reference_hits = original_lookup
            loop._run_observation_tool = original_observation
            loop._analyze_network_view = original_network_review

        self.assertEqual(report["status"], "fail")
        self.assertTrue(
            any(
                "single sphere primitive" in issue["message"] and "table" in issue["message"]
                for issue in report["issues"]
            )
        )

    def test_candidate_finalize_networks_collapses_nested_changed_parents(self):
        from houdinimind.agent.loop import AgentLoop

        tmp = _workspace_case_dir("finalize_candidate_collapse")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        loop = AgentLoop({"data_dir": tmp, "ollama_url": "http://localhost:11434"})

        before_snapshot = {"nodes": [], "connections": []}
        after_snapshot = {
            "nodes": [
                {"path": "/obj/table_geo", "category": "Object"},
                {"path": "/obj/table_geo/color_tabletop", "category": "Sop"},
                {"path": "/obj/table_geo/color_tabletop/attribvop1", "category": "Vop"},
                {"path": "/obj/table_geo/color_legs", "category": "Sop"},
                {"path": "/obj/table_geo/color_legs/attribvop1", "category": "Vop"},
            ],
            "connections": [],
        }

        parents = loop._candidate_finalize_networks(before_snapshot, after_snapshot)

        self.assertEqual(parents, ["/obj/table_geo"])

    def test_extract_display_output_paths_prefers_shallowest_visible_nodes(self):
        from houdinimind.agent.loop import AgentLoop

        tmp = _workspace_case_dir("display_output_shallowest")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        loop = AgentLoop({"data_dir": tmp, "ollama_url": "http://localhost:11434"})
        snapshot = {
            "nodes": [
                {
                    "path": "/obj/table_geo/final_merge",
                    "name": "final_merge",
                    "is_displayed": True,
                    "is_render_flag": True,
                },
                {
                    "path": "/obj/table_geo/color_tabletop/attribvop1",
                    "name": "attribvop1",
                    "is_displayed": True,
                    "is_render_flag": True,
                },
                {
                    "path": "/obj/table_geo/color_legs/attribvop1",
                    "name": "attribvop1",
                    "is_displayed": True,
                    "is_render_flag": True,
                },
            ]
        }

        outputs = loop._extract_display_output_paths(snapshot, ["/obj/table_geo"])

        self.assertEqual(outputs, ["/obj/table_geo/final_merge"])

    def test_run_verification_suite_skips_network_review_on_clean_build_when_configured(self):
        import houdinimind.agent.loop as loop_mod
        from houdinimind.agent.loop import AgentLoop

        tmp = _workspace_case_dir("verification_skip_network_review")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        loop = AgentLoop(
            {
                "data_dir": tmp,
                "ollama_url": "http://localhost:11434",
                "verify_skip_vision": True,
            }
        )
        calls = {"network_review": 0}
        original_hou_available = loop_mod.HOU_AVAILABLE
        original_candidate_parents = loop._candidate_finalize_networks
        original_extract_outputs = loop._extract_display_output_paths
        original_goal_match = loop._goal_match_verification_issues
        original_observation = loop._run_observation_tool
        original_network_review = loop._analyze_network_view
        original_vision_enabled = loop.llm.vision_enabled
        after_snapshot = {
            "nodes": [
                {
                    "path": "/obj/geo1/box1",
                    "name": "box1",
                    "type": "box",
                    "category": "Sop",
                    "outputs": [{"to_node": "/obj/geo1/OUT"}],
                },
                {
                    "path": "/obj/geo1/OUT",
                    "name": "OUT",
                    "type": "null",
                    "category": "Sop",
                    "is_displayed": True,
                    "is_render_flag": True,
                    "outputs": [],
                },
            ],
            "connections": [{"from": "/obj/geo1/box1", "to": "/obj/geo1/OUT", "to_input": 0}],
            "error_count": 0,
        }

        try:
            loop_mod.HOU_AVAILABLE = True
            loop.llm.vision_enabled = True
            loop._candidate_finalize_networks = lambda before, after: ["/obj/geo1"]
            loop._extract_display_output_paths = lambda after, parents: ["/obj/geo1/OUT"]
            loop._goal_match_verification_issues = lambda *args, **kwargs: []

            def fake_observation(tool_name, args, stream_callback=None):
                if tool_name == "get_all_errors":
                    return {"status": "ok", "data": {"nodes": []}}
                if tool_name == "get_geometry_attributes":
                    return {"status": "ok", "data": {"point_count": 12}}
                if tool_name == "get_node_inputs":
                    return {"status": "ok", "data": {"inputs": []}}
                return {"status": "ok", "data": {}}

            loop._run_observation_tool = fake_observation

            def fake_network_review(*args, **kwargs):
                calls["network_review"] += 1
                return {"verdict": "PASS", "summary": "Looks fine", "issues": []}

            loop._analyze_network_view = fake_network_review

            report = loop._run_verification_suite(
                "Create a box",
                {"nodes": [], "connections": []},
                after_snapshot,
                "build",
            )
        finally:
            loop_mod.HOU_AVAILABLE = original_hou_available
            loop._candidate_finalize_networks = original_candidate_parents
            loop._extract_display_output_paths = original_extract_outputs
            loop._goal_match_verification_issues = original_goal_match
            loop._run_observation_tool = original_observation
            loop._analyze_network_view = original_network_review
            loop.llm.vision_enabled = original_vision_enabled

        self.assertEqual(report["status"], "pass")
        self.assertEqual(calls["network_review"], 0)

    def test_run_verification_suite_light_profile_skips_heavy_vision_checks(self):
        import houdinimind.agent.loop as loop_mod
        from houdinimind.agent.loop import AgentLoop

        tmp = _workspace_case_dir("verification_light_profile")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        loop = AgentLoop({"data_dir": tmp, "ollama_url": "http://localhost:11434"})
        original_hou_available = loop_mod.HOU_AVAILABLE
        original_candidate_parents = loop._candidate_finalize_networks
        original_extract_outputs = loop._extract_display_output_paths
        original_goal_match_issues = loop._goal_match_verification_issues
        original_observation = loop._run_observation_tool
        original_goal_match_review = loop._goal_match_vision_review
        original_semantic_eval = loop._evaluate_semantic_views
        original_network_review = loop._analyze_network_view

        calls = {"goal_match_review": 0, "semantic_eval": 0, "network_review": 0}
        after_snapshot = {
            "nodes": [
                {
                    "path": "/obj/geo1/box1",
                    "name": "box1",
                    "type": "box",
                    "category": "Sop",
                    "outputs": [{"to_node": "/obj/geo1/OUT"}],
                },
                {
                    "path": "/obj/geo1/OUT",
                    "name": "OUT",
                    "type": "null",
                    "category": "Sop",
                    "is_displayed": True,
                    "is_render_flag": True,
                    "outputs": [],
                },
            ],
            "connections": [{"from": "/obj/geo1/box1", "to": "/obj/geo1/OUT", "to_input": 0}],
            "error_count": 0,
        }

        def fake_observation(tool_name, args, stream_callback=None):
            if tool_name == "get_all_errors":
                return {"status": "ok", "data": {"nodes": []}}
            if tool_name == "get_geometry_attributes":
                return {"status": "ok", "data": {"point_count": 32}}
            if tool_name == "get_node_inputs":
                return {"status": "ok", "data": {"inputs": []}}
            if tool_name == "get_bounding_box":
                return {"status": "ok", "data": {"size": [1.0, 1.0, 1.0]}}
            return {"status": "ok", "data": {}}

        try:
            loop_mod.HOU_AVAILABLE = True
            loop._candidate_finalize_networks = lambda before, after: ["/obj/geo1"]
            loop._extract_display_output_paths = lambda after, parents: ["/obj/geo1/OUT"]
            loop._goal_match_verification_issues = lambda *args, **kwargs: []
            loop._run_observation_tool = fake_observation
            loop._goal_match_vision_review = lambda *args, **kwargs: (
                calls.__setitem__("goal_match_review", calls["goal_match_review"] + 1) or None
            )
            loop._evaluate_semantic_views = lambda *args, **kwargs: (
                calls.__setitem__("semantic_eval", calls["semantic_eval"] + 1) or None
            )
            loop._analyze_network_view = lambda *args, **kwargs: (
                calls.__setitem__("network_review", calls["network_review"] + 1) or None
            )

            report = loop._run_verification_suite(
                "Create a procedural chair",
                {"nodes": [], "connections": []},
                after_snapshot,
                "build",
                verification_profile="light",
            )
        finally:
            loop_mod.HOU_AVAILABLE = original_hou_available
            loop._candidate_finalize_networks = original_candidate_parents
            loop._extract_display_output_paths = original_extract_outputs
            loop._goal_match_verification_issues = original_goal_match_issues
            loop._run_observation_tool = original_observation
            loop._goal_match_vision_review = original_goal_match_review
            loop._evaluate_semantic_views = original_semantic_eval
            loop._analyze_network_view = original_network_review

        self.assertEqual(report["profile"], "light")
        self.assertEqual(report["status"], "pass")
        self.assertEqual(calls["goal_match_review"], 0)
        self.assertEqual(calls["semantic_eval"], 0)
        self.assertEqual(calls["network_review"], 0)

    def test_run_verification_suite_fails_when_goal_match_vision_rejects_result(self):
        import houdinimind.agent.loop as loop_mod
        from houdinimind.agent.loop import AgentLoop

        tmp = _workspace_case_dir("verification_goal_match_vision")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        loop = AgentLoop({"data_dir": tmp, "ollama_url": "http://localhost:11434"})
        original_hou_available = loop_mod.HOU_AVAILABLE
        original_candidate_parents = loop._candidate_finalize_networks
        original_extract_outputs = loop._extract_display_output_paths
        original_goal_match = loop._goal_match_verification_issues
        original_observation = loop._run_observation_tool
        original_network_review = loop._analyze_network_view
        original_capture = loop._capture_debug_screenshot
        original_chat_vision = loop.llm.chat_vision

        after_snapshot = {
            "nodes": [
                {
                    "path": "/obj/sofa_geo/base",
                    "name": "base",
                    "type": "box",
                    "category": "Sop",
                    "outputs": [{"to_node": "/obj/sofa_geo/OUT"}],
                },
                {
                    "path": "/obj/sofa_geo/OUT",
                    "name": "OUT",
                    "type": "null",
                    "category": "Sop",
                    "outputs": [],
                    "is_displayed": True,
                    "is_render_flag": True,
                },
            ],
            "connections": [
                {"from": "/obj/sofa_geo/base", "to": "/obj/sofa_geo/OUT", "to_input": 0}
            ],
            "error_count": 0,
        }

        def fake_observation(tool_name, args, stream_callback=None):
            if tool_name == "get_all_errors":
                return {"status": "ok", "data": {"nodes": []}}
            if tool_name == "get_geometry_attributes":
                return {"status": "ok", "data": {"point_count": 104}}
            if tool_name == "get_node_inputs":
                return {"status": "ok", "data": {"inputs": []}}
            if tool_name == "get_bounding_box":
                return {"status": "ok", "data": {"size": [2.0, 0.8, 1.0]}}
            return {"status": "ok", "data": {}}

        try:
            loop_mod.HOU_AVAILABLE = True
            loop._candidate_finalize_networks = lambda before, after: ["/obj/sofa_geo"]
            loop._extract_display_output_paths = lambda after, parents: ["/obj/sofa_geo/OUT"]
            loop._goal_match_verification_issues = lambda *args, **kwargs: []
            loop._run_observation_tool = fake_observation
            loop._analyze_network_view = lambda *args, **kwargs: None
            loop._capture_debug_screenshot = lambda *args, **kwargs: "ZmFrZQ=="
            loop.llm.chat_vision = lambda *args, **kwargs: json.dumps(
                {
                    "verdict": "FAIL",
                    "summary": "The shape is visible, but it still reads like a generic box blockout instead of a recognizable sofa.",
                    "issues": ["No clear cushion or sofa silhouette is visible."],
                }
            )

            report = loop._run_verification_suite(
                "Create a sofa",
                {"nodes": [], "connections": []},
                after_snapshot,
                "build",
            )
        finally:
            loop_mod.HOU_AVAILABLE = original_hou_available
            loop._candidate_finalize_networks = original_candidate_parents
            loop._extract_display_output_paths = original_extract_outputs
            loop._goal_match_verification_issues = original_goal_match
            loop._run_observation_tool = original_observation
            loop._analyze_network_view = original_network_review
            loop._capture_debug_screenshot = original_capture
            loop.llm.chat_vision = original_chat_vision

        self.assertEqual(report["status"], "fail")
        self.assertEqual(report["semantic_review"]["verdict"], "FAIL")
        self.assertTrue(
            any(
                "does not yet clearly read as the requested object" in issue["message"]
                for issue in report["issues"]
            )
        )
        self.assertIn("[GOAL MATCH] FAIL", report["text"])

    def test_run_verification_suite_fails_when_semantic_score_is_below_threshold(self):
        import houdinimind.agent.loop as loop_mod
        from houdinimind.agent.loop import AgentLoop

        tmp = _workspace_case_dir("verification_semantic_score")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        loop = AgentLoop({"data_dir": tmp, "ollama_url": "http://localhost:11434"})
        original_hou_available = loop_mod.HOU_AVAILABLE
        original_candidate_parents = loop._candidate_finalize_networks
        original_extract_outputs = loop._extract_display_output_paths
        original_goal_match = loop._goal_match_vision_review
        original_goal_match_issues = loop._goal_match_verification_issues
        original_semantic = loop._evaluate_semantic_views
        original_observation = loop._run_observation_tool
        original_network_review = loop._analyze_network_view

        after_snapshot = {
            "nodes": [
                {
                    "path": "/obj/sofa_geo/base",
                    "name": "base",
                    "type": "box",
                    "category": "Sop",
                    "outputs": [{"to_node": "/obj/sofa_geo/OUT"}],
                },
                {
                    "path": "/obj/sofa_geo/OUT",
                    "name": "OUT",
                    "type": "null",
                    "category": "Sop",
                    "is_displayed": True,
                    "is_render_flag": True,
                    "outputs": [],
                },
            ],
            "connections": [
                {"from": "/obj/sofa_geo/base", "to": "/obj/sofa_geo/OUT", "to_input": 0}
            ],
            "error_count": 0,
        }

        def fake_observation(tool_name, args, stream_callback=None):
            if tool_name == "get_all_errors":
                return {"status": "ok", "data": {"nodes": []}}
            if tool_name == "get_geometry_attributes":
                return {"status": "ok", "data": {"point_count": 104}}
            if tool_name == "get_node_inputs":
                return {"status": "ok", "data": {"inputs": []}}
            if tool_name == "get_bounding_box":
                return {"status": "ok", "data": {"size": [2.0, 0.9, 1.0]}}
            return {"status": "ok", "data": {}}

        def fake_semantic(*_args, **_kwargs):
            loop._last_turn_semantic_text = "[SEMANTIC SCORE] FAIL\nOverall: 0.55 / Threshold: 0.72"
            return {
                "verdict": "FAIL",
                "overall": 0.55,
                "threshold": 0.72,
                "scores": {"identity": 0.5},
            }

        try:
            loop_mod.HOU_AVAILABLE = True
            loop._candidate_finalize_networks = lambda before, after: ["/obj/sofa_geo"]
            loop._extract_display_output_paths = lambda after, parents: ["/obj/sofa_geo/OUT"]
            loop._goal_match_vision_review = lambda *args, **kwargs: None
            loop._goal_match_verification_issues = lambda *args, **kwargs: []
            loop._evaluate_semantic_views = fake_semantic
            loop._run_observation_tool = fake_observation
            loop._analyze_network_view = lambda *args, **kwargs: None

            report = loop._run_verification_suite(
                "Create a sofa",
                {"nodes": [], "connections": []},
                after_snapshot,
                "build",
            )
        finally:
            loop_mod.HOU_AVAILABLE = original_hou_available
            loop._candidate_finalize_networks = original_candidate_parents
            loop._extract_display_output_paths = original_extract_outputs
            loop._goal_match_vision_review = original_goal_match
            loop._goal_match_verification_issues = original_goal_match_issues
            loop._evaluate_semantic_views = original_semantic
            loop._run_observation_tool = original_observation
            loop._analyze_network_view = original_network_review

        self.assertEqual(report["status"], "fail")
        self.assertEqual(report["semantic_scorecard"]["verdict"], "FAIL")
        self.assertIn("[SEMANTIC SCORE] FAIL", report["text"])
        self.assertTrue(
            any(
                "Multi-view semantic scoring is below the required threshold" in issue["message"]
                for issue in report["issues"]
            )
        )

    def test_analyze_geometry_supports_getter_based_attribute_api(self):
        import houdinimind.agent.tools as tools_mod

        class _FakeDataType:
            def __str__(self):
                return "Float"

        class _FakeAttr:
            def __init__(self, name, size=3):
                self._name = name
                self._size = size

            def name(self):
                return self._name

            def dataType(self):
                return _FakeDataType()

            def size(self):
                return self._size

        class _FakeBBox:
            def minvec(self):
                return (0.0, 0.0, 0.0)

            def maxvec(self):
                return (1.0, 2.0, 3.0)

            def sizevec(self):
                return (1.0, 2.0, 3.0)

            def center(self):
                return (0.5, 1.0, 1.5)

        class _FakePrimType:
            def __str__(self):
                return "Polygon"

        class _FakePrim:
            def type(self):
                return _FakePrimType()

        class _FakeGeo:
            def boundingBox(self):
                return _FakeBBox()

            def points(self):
                return [object(), object(), object()]

            def prims(self):
                return [_FakePrim(), _FakePrim()]

            def globalAttribs(self):
                return [_FakeAttr("detail_id", 1)]

            def pointAttribs(self):
                return [_FakeAttr("P"), _FakeAttr("Cd")]

            def primAttribs(self):
                return [_FakeAttr("name", 1)]

            def vertexAttribs(self):
                return [_FakeAttr("uv", 2)]

        class _FakeNode:
            def __init__(self, path):
                self._path = path

            def path(self):
                return self._path

            def geometry(self):
                return _FakeGeo()

        class _FakeHou:
            def __init__(self, node):
                self._node = node

            def node(self, path):
                return self._node if path == self._node.path() else None

        original_hou = getattr(tools_mod, "hou", None)
        original_available = tools_mod.HOU_AVAILABLE
        node = _FakeNode("/obj/geo1/box1")

        try:
            tools_mod.HOU_AVAILABLE = True
            tools_mod.hou = _FakeHou(node)
            result = tools_mod.analyze_geometry("/obj/geo1/box1")
        finally:
            tools_mod.hou = original_hou
            tools_mod.HOU_AVAILABLE = original_available

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["resolved_node_path"], "/obj/geo1/box1")
        self.assertEqual(result["data"]["point_count"], 3)
        self.assertTrue(result["data"]["has_cd"])
        self.assertEqual(result["data"]["attributes"]["detail"][0]["name"], "detail_id")

    def test_run_verification_suite_flags_new_orphan_error_branch(self):
        import houdinimind.agent.loop as loop_mod
        from houdinimind.agent.loop import AgentLoop

        tmp = _workspace_case_dir("verification_new_orphan_error_branch")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        loop = AgentLoop({"data_dir": tmp, "ollama_url": "http://localhost:11434"})
        original_hou_available = loop_mod.HOU_AVAILABLE
        original_candidate_parents = loop._candidate_finalize_networks
        original_extract_outputs = loop._extract_display_output_paths
        original_goal_match = loop._goal_match_verification_issues
        original_observation = loop._run_observation_tool
        original_network_review = loop._analyze_network_view

        before_snapshot = {
            "nodes": [
                {
                    "path": "/obj/geo1/old_bad",
                    "type": "xform",
                    "category": "Sop",
                    "outputs": [],
                },
                {
                    "path": "/obj/geo1/good1",
                    "type": "box",
                    "category": "Sop",
                    "outputs": [{"to_node": "/obj/geo1/OUT"}],
                },
                {
                    "path": "/obj/geo1/OUT",
                    "type": "null",
                    "category": "Sop",
                    "outputs": [],
                    "is_displayed": True,
                    "is_render_flag": True,
                },
            ],
            "connections": [{"from": "/obj/geo1/good1", "to": "/obj/geo1/OUT", "to_input": 0}],
        }
        after_snapshot = {
            "nodes": before_snapshot["nodes"]
            + [
                {
                    "path": "/obj/geo1/new_bad",
                    "type": "xform",
                    "category": "Sop",
                    "outputs": [],
                }
            ],
            "connections": before_snapshot["connections"],
        }

        def fake_observation(tool_name, args, stream_callback=None):
            if tool_name == "get_all_errors":
                return {
                    "status": "ok",
                    "data": {
                        "nodes": [
                            {
                                "path": "/obj/geo1/old_bad",
                                "errors": ["Old orphan error"],
                                "warnings": [],
                            },
                            {
                                "path": "/obj/geo1/new_bad",
                                "errors": ["New orphan error"],
                                "warnings": [],
                            },
                        ]
                    },
                }
            if tool_name == "get_geometry_attributes":
                return {"status": "ok", "data": {"point_count": 12}}
            if tool_name == "get_node_inputs":
                return {"status": "ok", "data": {"inputs": []}}
            return {"status": "ok", "data": {}}

        try:
            loop_mod.HOU_AVAILABLE = True
            loop._candidate_finalize_networks = lambda before, after: ["/obj/geo1"]
            loop._extract_display_output_paths = lambda after, parents: ["/obj/geo1/OUT"]
            loop._goal_match_verification_issues = lambda *args, **kwargs: []
            loop._run_observation_tool = fake_observation
            loop._analyze_network_view = lambda *args, **kwargs: None
            report = loop._run_verification_suite(
                "Create a table",
                before_snapshot,
                after_snapshot,
                "build",
            )
        finally:
            loop_mod.HOU_AVAILABLE = original_hou_available
            loop._candidate_finalize_networks = original_candidate_parents
            loop._extract_display_output_paths = original_extract_outputs
            loop._goal_match_verification_issues = original_goal_match
            loop._run_observation_tool = original_observation
            loop._analyze_network_view = original_network_review

        issue_paths = [issue["path"] for issue in report["issues"]]
        self.assertEqual(report["status"], "fail")
        self.assertIn("/obj/geo1/new_bad", issue_paths)
        self.assertNotIn("/obj/geo1/old_bad", issue_paths)

    def test_audit_spatial_layout_does_not_flag_single_centered_shape(self):
        from houdinimind.agent import tools

        class _Pos:
            def x(self):
                return 0

            def y(self):
                return 0

        class _Center:
            def __getitem__(self, index):
                return 0.0

        class _BBox:
            def center(self):
                return _Center()

        class _Geo:
            def points(self):
                return [object()]

            def boundingBox(self):
                return _BBox()

        class _Type:
            def name(self):
                return "sphere"

        class _Child:
            def name(self):
                return "sphere1"

            def type(self):
                return _Type()

            def position(self):
                return _Pos()

            def geometry(self):
                return _Geo()

            def parm(self, _name):
                return None

        class _Parent:
            def children(self):
                return [_Child()]

        class _Hou:
            def node(self, path):
                if path == "/obj/geo1":
                    return _Parent()
                return None

        original_hou = getattr(tools, "hou", None)
        original_available = tools.HOU_AVAILABLE

        try:
            tools.hou = _Hou()
            tools.HOU_AVAILABLE = True
            result = tools.audit_spatial_layout("/obj/geo1")
        finally:
            if original_hou is None:
                delattr(tools, "hou")
            else:
                tools.hou = original_hou
            tools.HOU_AVAILABLE = original_available

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["at_origin_issues"], [])

    def test_audit_spatial_layout_reports_generic_support_gap(self):
        from houdinimind.agent import tools

        class _Pos:
            def x(self):
                return 0

            def y(self):
                return 0

        class _BBox:
            def __init__(self, minv, maxv):
                self._min = minv
                self._max = maxv

            def minvec(self):
                return self._min

            def maxvec(self):
                return self._max

            def sizevec(self):
                return tuple(self._max[i] - self._min[i] for i in range(3))

            def center(self):
                return tuple((self._min[i] + self._max[i]) / 2 for i in range(3))

        class _Geo:
            def __init__(self, bbox):
                self._bbox = bbox

            def points(self):
                return [object()]

            def boundingBox(self):
                return self._bbox

        class _Type:
            def name(self):
                return "box"

        class _Child:
            def __init__(self, name, bbox):
                self._name = name
                self._geo = _Geo(bbox)

            def name(self):
                return self._name

            def type(self):
                return _Type()

            def position(self):
                return _Pos()

            def geometry(self):
                return self._geo

            def parm(self, _name):
                return None

            def outputs(self):
                return []

        class _Parent:
            def children(self):
                return [
                    _Child("support_post", _BBox((-0.05, 0.0, -0.05), (0.05, 1.0, 0.05))),
                    _Child("upper_piece", _BBox((-1.0, 1.2, -1.0), (1.0, 1.3, 1.0))),
                ]

        class _Hou:
            def node(self, path):
                if path == "/obj/geo1":
                    return _Parent()
                return None

        original_hou = getattr(tools, "hou", None)
        original_available = tools.HOU_AVAILABLE

        try:
            tools.hou = _Hou()
            tools.HOU_AVAILABLE = True
            result = tools.audit_spatial_layout("/obj/geo1")
        finally:
            if original_hou is None:
                delattr(tools, "hou")
            else:
                tools.hou = original_hou
            tools.HOU_AVAILABLE = original_available

        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["data"]["contact_issues"]), 1)
        self.assertIn("vertical gap", result["data"]["contact_issues"][0])

    def test_get_node_inputs_handles_tuple_connectors(self):
        from houdinimind.agent import tools

        original_hou = getattr(tools, "hou", None)
        original_available = tools.HOU_AVAILABLE

        try:
            tools.hou = FakeHou({"/obj/geo1/merge1": _FakeInputNode()})
            tools.HOU_AVAILABLE = True
            result = tools.get_node_inputs("/obj/geo1/merge1")
        finally:
            if original_hou is None:
                delattr(tools, "hou")
            else:
                tools.hou = original_hou
            tools.HOU_AVAILABLE = original_available

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["inputs"][0]["connected_to"], "/obj/geo1/source")
        self.assertEqual(result["data"]["inputs"][0]["errors"], ["bad wire"])

    def test_get_node_inputs_caps_unconnected_variable_inputs(self):
        from houdinimind.agent import tools

        class _LargeInputNode:
            def __init__(self):
                self._connected = _FakeInputLabelNode("/obj/geo1/source99")

            def inputNames(self):
                return ["input1"]

            def inputs(self):
                inputs = [None] * 100
                inputs[99] = self._connected
                return inputs

            def inputConnectors(self):
                return [None] * 100

        original_hou = getattr(tools, "hou", None)
        original_available = tools.HOU_AVAILABLE

        try:
            tools.hou = FakeHou({"/obj/geo1/merge1": _LargeInputNode()})
            tools.HOU_AVAILABLE = True
            result = tools.get_node_inputs(
                "/obj/geo1/merge1",
                only_connected=False,
                max_inputs=4,
            )
        finally:
            if original_hou is None:
                delattr(tools, "hou")
            else:
                tools.hou = original_hou
            tools.HOU_AVAILABLE = original_available

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["total_input_slots"], 100)
        self.assertEqual(result["data"]["reported_input_slots"], 5)
        self.assertTrue(result["data"]["truncated"])
        self.assertEqual(result["data"]["connected_count"], 1)
        self.assertEqual(result["data"]["inputs"][-1]["index"], 99)
        self.assertEqual(result["data"]["inputs"][-1]["connected_to"], "/obj/geo1/source99")

    def test_get_geometry_attributes_supports_global_attribs_api(self):
        from houdinimind.agent import tools

        original_hou = getattr(tools, "hou", None)
        original_available = tools.HOU_AVAILABLE

        try:
            tools.hou = FakeHou({"/obj/geo1/out1": _FakeGeometryNode()})
            tools.HOU_AVAILABLE = True
            result = tools.get_geometry_attributes("/obj/geo1/out1")
        finally:
            if original_hou is None:
                delattr(tools, "hou")
            else:
                tools.hou = original_hou
            tools.HOU_AVAILABLE = original_available

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["detail"]["foo"], 123)
        self.assertEqual(result["data"]["point_attrs"], ["P", "Cd"])
        self.assertEqual(result["data"]["prim_attrs"], ["name"])

    def test_get_geometry_attributes_resolves_displayed_sop_from_geo_object(self):
        from houdinimind.agent import tools

        class _FakeOutputNode(_FakeGeometryNode):
            def path(self):
                return "/obj/bus/OUT"

        class _FakeObjNode:
            def __init__(self, child):
                self._child = child

            def displayNode(self):
                return self._child

            def path(self):
                return "/obj/bus"

        original_hou = getattr(tools, "hou", None)
        original_available = tools.HOU_AVAILABLE

        try:
            tools.hou = FakeHou(
                {
                    "/obj/bus": _FakeObjNode(_FakeOutputNode()),
                    "/obj/bus/OUT": _FakeOutputNode(),
                }
            )
            tools.HOU_AVAILABLE = True
            result = tools.get_geometry_attributes("/obj/bus")
        finally:
            if original_hou is None:
                delattr(tools, "hou")
            else:
                tools.hou = original_hou
            tools.HOU_AVAILABLE = original_available

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["resolved_node_path"], "/obj/bus/OUT")
        self.assertEqual(result["data"]["point_count"], 2)

    def test_inspect_display_output_reports_resolved_visible_geometry(self):
        from houdinimind.agent import tools

        class _FakeInspectGeometry:
            def points(self):
                return [object(), object(), object()]

            def prims(self):
                return [object()]

        class _FakeInspectOutputNode:
            def path(self):
                return "/obj/bus/OUT"

            def geometry(self):
                return _FakeInspectGeometry()

            def errors(self):
                return []

            def warnings(self):
                return ["minor warning"]

        class _FakeInspectObjNode:
            def __init__(self, child):
                self._child = child

            def displayNode(self):
                return self._child

            def renderNode(self):
                return self._child

            def children(self):
                return [self._child]

        output_node = _FakeInspectOutputNode()
        original_hou = getattr(tools, "hou", None)
        original_available = tools.HOU_AVAILABLE

        try:
            tools.hou = FakeHou(
                {
                    "/obj/bus": _FakeInspectObjNode(output_node),
                    "/obj/bus/OUT": output_node,
                }
            )
            tools.HOU_AVAILABLE = True
            result = tools.inspect_display_output("/obj/bus")
        finally:
            if original_hou is None:
                delattr(tools, "hou")
            else:
                tools.hou = original_hou
            tools.HOU_AVAILABLE = original_available

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["resolved_geometry_path"], "/obj/bus/OUT")
        self.assertEqual(result["data"]["point_count"], 3)
        self.assertEqual(result["data"]["warning_count"], 1)

    def test_search_knowledge_prefers_real_kb_file_when_available(self):
        from houdinimind.agent import tools

        tmp = _workspace_case_dir("search_knowledge_real_kb")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        knowledge_dir = os.path.join(tmp, "data", "knowledge")
        os.makedirs(knowledge_dir, exist_ok=True)
        kb_path = os.path.join(knowledge_dir, "knowledge_base.json")
        with open(kb_path, "w", encoding="utf-8") as handle:
            json.dump(
                [
                    {
                        "_id": "workflow_bus",
                        "title": "Bus Workflow",
                        "category": "workflow",
                        "tags": ["bus", "vehicle"],
                        "content": "Create the bus body first, then windows and wheels.",
                    }
                ],
                handle,
            )

        original_root = tools.HOUDINIMIND_ROOT
        try:
            tools.HOUDINIMIND_ROOT = tmp
            result = tools.search_knowledge("bus", top_k=3)
        finally:
            tools.HOUDINIMIND_ROOT = original_root

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["results_found"], 1)
        self.assertEqual(result["data"]["results"][0]["title"], "Bus Workflow")

    def test_search_knowledge_uses_shared_rag_retriever_when_available(self):
        from houdinimind.agent import tools

        class _FakeRetriever:
            def __init__(self):
                self.calls = []

            def retrieve(self, **kwargs):
                self.calls.append(kwargs)
                return [
                    {
                        "id": "rag_bus",
                        "title": "Semantic Bus Workflow",
                        "category": "workflow",
                        "content": "Use a bus body blockout and refine proportions.",
                        "_score": 0.87,
                    }
                ]

        fake = _FakeRetriever()
        original_getter = tools._get_search_retriever
        try:
            tools._get_search_retriever = lambda: fake
            result = tools.search_knowledge("build a bus", top_k=2, category_filter="workflow")
        finally:
            tools._get_search_retriever = original_getter

        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(fake.calls[0]["query"], "build a bus")
        self.assertEqual(fake.calls[0]["top_k"], 2)
        self.assertEqual(fake.calls[0]["category_filter"], "workflow")
        self.assertFalse(fake.calls[0]["include_memory"])
        self.assertFalse(fake.calls[0]["use_rerank"])

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["results_found"], 1)
        self.assertEqual(result["data"]["results"][0]["title"], "Semantic Bus Workflow")
        self.assertEqual(result["data"]["results"][0]["relevance_score"], 0.87)

    def test_get_search_retriever_forwards_shared_embed_fn_without_forcing_bm25(self):
        import houdinimind.rag as rag_mod
        from houdinimind.agent import llm_client, tools

        tmp = _workspace_case_dir("search_retriever_shared_embed_fn")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        data_dir = os.path.join(tmp, "data")
        knowledge_dir = os.path.join(data_dir, "knowledge")
        os.makedirs(knowledge_dir, exist_ok=True)
        with open(os.path.join(data_dir, "core_config.json"), "w", encoding="utf-8") as handle:
            json.dump({}, handle)
        with open(
            os.path.join(knowledge_dir, "knowledge_base.json"), "w", encoding="utf-8"
        ) as handle:
            json.dump([], handle)

        captured = {}

        class _FakeInjector:
            def __init__(self):
                self.retriever = object()

        def shared_embed(_text):
            return [1.0, 0.0]

        def fake_load_config(_path):
            return {"data_dir": data_dir}

        def fake_create_rag_pipeline(_data_dir, config=None):
            captured["data_dir"] = _data_dir
            captured["config"] = dict(config or {})
            return _FakeInjector()

        original_root = tools.HOUDINIMIND_ROOT
        original_shared = tools._SHARED_EMBED_FN
        original_cache = dict(tools._SEARCH_RETRIEVER_CACHE)
        original_load_config = llm_client.load_config
        original_create_rag_pipeline = rag_mod.create_rag_pipeline
        try:
            tools.HOUDINIMIND_ROOT = tmp
            tools._SHARED_EMBED_FN = shared_embed
            tools._SEARCH_RETRIEVER_CACHE["cache_key"] = None
            tools._SEARCH_RETRIEVER_CACHE["retriever"] = None
            llm_client.load_config = fake_load_config
            rag_mod.create_rag_pipeline = fake_create_rag_pipeline

            retriever = tools._get_search_retriever()
        finally:
            tools.HOUDINIMIND_ROOT = original_root
            tools._SHARED_EMBED_FN = original_shared
            tools._SEARCH_RETRIEVER_CACHE.clear()
            tools._SEARCH_RETRIEVER_CACHE.update(original_cache)
            llm_client.load_config = original_load_config
            rag_mod.create_rag_pipeline = original_create_rag_pipeline

        self.assertIsNotNone(retriever)
        self.assertEqual(captured["data_dir"], data_dir)
        self.assertIs(captured["config"].get("_shared_embed_fn"), shared_embed)
        self.assertNotIn("rag_hybrid_search", captured["config"])

    def test_get_rag_category_policy_expands_build_categories_from_query(self):
        from houdinimind.agent.loop import get_rag_category_policy

        policy = get_rag_category_policy(
            "build",
            "Create a Solaris material with a wrangle and explain the parameter syntax.",
        )

        self.assertIn("nodes", policy["include_categories"])
        self.assertIn("vex", policy["include_categories"])
        self.assertIn("usd", policy["include_categories"])
        self.assertIn("general", policy["include_categories"])
        self.assertEqual(policy["exclude_categories"], ["errors"])

    def test_vex_build_turn_keeps_vex_rag_tools_available(self):
        from houdinimind.agent.request_modes import _build_mode_disabled_tools_for_query

        disabled = _build_mode_disabled_tools_for_query(
            "Write a VEX wrangle using pcopen to gather nearby point colors."
        )

        self.assertNotIn("search_knowledge", disabled)
        self.assertNotIn("get_vex_snippet", disabled)

    def test_python_build_turn_keeps_python_rag_available(self):
        from houdinimind.agent.request_modes import (
            _build_mode_disabled_tools_for_query,
            get_rag_category_policy,
        )

        query = "Write Houdini Python using hou.Node.createNode and setParmTemplateGroup."
        disabled = _build_mode_disabled_tools_for_query(query)
        policy = get_rag_category_policy("build", query)

        self.assertNotIn("search_knowledge", disabled)
        self.assertIn("python", policy["include_categories"])
        self.assertIn("general", policy["include_categories"])

    def test_agent_loop_injects_vex_contract_and_vex_rag_categories(self):
        from houdinimind.agent.loop import AgentLoop

        class _FakeRetriever:
            def _query_mentions_vex_symbol(self, query):
                return "pcopen" in query

        class _FakeRag:
            retriever = _FakeRetriever()

        tmp = _workspace_case_dir("vex_contract_guidance")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        loop = AgentLoop(
            {"data_dir": tmp, "ollama_url": "http://localhost:11434"}, rag_injector=_FakeRag()
        )

        guidance = loop._build_vex_contract_guidance(
            "Use pcopen to average nearby colors in a point wrangle.",
            "build",
        )
        kwargs = loop._get_rag_injection_kwargs(
            "build",
            "Use pcopen to average nearby colors in a point wrangle.",
        )

        self.assertIn('category_filter="vex"', guidance)
        self.assertIn("write_vex_code", guidance)
        self.assertIn("validation_failed", guidance)
        self.assertIn("vex", kwargs["include_categories"])
        self.assertIn("nodes", kwargs["include_categories"])
        self.assertIn("general", kwargs["include_categories"])

    def test_dust_contact_request_uses_build_mode_and_contract_rag(self):
        from houdinimind.agent.loop import AgentLoop
        from houdinimind.agent.task_contracts import build_task_contract

        query = (
            "I want wherever crag is touching feet to the ground "
            "I want you to emit dust from those points"
        )
        tmp = _workspace_case_dir("dust_contact_contract_mode")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        loop = AgentLoop({"data_dir": tmp, "ollama_url": "http://localhost:11434"})

        mode, confidence = loop._classify_request_mode(query)
        contract = build_task_contract(query)
        kwargs = loop._get_rag_injection_kwargs(mode, query)

        self.assertEqual(mode, "build")
        self.assertGreaterEqual(confidence, 0.9)
        self.assertIsNotNone(contract)
        self.assertEqual(contract.contract_id, "dust_contact_emission")
        self.assertIn("vex", kwargs["include_categories"])
        self.assertIn("nodes", kwargs["include_categories"])
        self.assertIn("workflow", kwargs["include_categories"])
        self.assertIn("sim", kwargs["include_categories"])

    def test_dust_contact_contract_flags_container_only_vopnet_result(self):
        from houdinimind.agent.task_contracts import build_task_contract, verify_task_contract

        query = (
            "I want wherever crag is touching feet to the ground "
            "I want you to emit dust from those points"
        )
        contract = build_task_contract(query)
        before_snapshot = {
            "nodes": [
                {
                    "path": "/obj/testgeometry_crag1/testgeometry_crag1",
                    "type": "testgeometry_crag",
                    "category": "Sop",
                }
            ],
            "connections": [],
        }
        after_snapshot = {
            "nodes": [
                *before_snapshot["nodes"],
                {"path": "/obj/ground", "type": "geo", "category": "Obj"},
                {"path": "/obj/dust_sim", "type": "geo", "category": "Obj"},
                {
                    "path": "/obj/dust_sim/dust_emission",
                    "type": "vopnet",
                    "category": "Sop",
                },
                {"path": "/obj/dust_sim/crag_geo", "type": "object_merge", "category": "Sop"},
                {"path": "/obj/dust_sim/ground_geo", "type": "object_merge", "category": "Sop"},
            ],
            "connections": [],
        }

        issues = verify_task_contract(
            contract,
            before_snapshot,
            after_snapshot,
            ["/obj/dust_sim"],
            ["/obj/dust_sim"],
        )
        messages = "\n".join(issue["message"] for issue in issues)

        self.assertIn("vopnet", messages)
        self.assertIn("contact-point", messages)
        self.assertIn("visible output", messages)

    def test_task_contract_guidance_mentions_acceptance_and_repair(self):
        from houdinimind.agent.task_contracts import (
            build_task_contract,
            format_task_contract_guidance,
        )

        contract = build_task_contract("emit dust where particles hit the ground")
        guidance = format_task_contract_guidance(contract)

        self.assertIn("Dust emission from ground-contact points", guidance)
        self.assertIn("contact points", guidance)
        self.assertIn("dust/particle source", guidance)
        self.assertIn("repair", guidance.lower())

    def test_rag_eval_harness_reports_hit_at_k_and_mrr(self):
        from houdinimind.rag.eval_harness import evaluate_retriever, load_eval_cases
        from houdinimind.rag.retriever import HybridRetriever

        tmp = _workspace_case_dir("rag_eval_harness")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        kb_path = os.path.join(tmp, "knowledge_base.json")
        dataset_path = os.path.join(tmp, "eval.json")

        with open(kb_path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "entries": [
                        {
                            "_id": "box_workflow",
                            "title": "Box Workflow",
                            "category": "workflow",
                            "tags": ["box", "workflow"],
                            "content": "Create a box SOP and end on OUT.",
                        },
                        {
                            "_id": "merge_workflow",
                            "title": "Merge Workflow",
                            "category": "workflow",
                            "tags": ["merge"],
                            "content": "Merge branches before the final output.",
                        },
                    ]
                },
                handle,
            )

        with open(dataset_path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "name": "unit_eval",
                    "cases": [
                        {
                            "id": "box_case",
                            "query": "How do I build a box output?",
                            "expected_any": [{"title": "Box Workflow"}],
                            "expected_categories": ["workflow"],
                        }
                    ],
                },
                handle,
            )

        dataset = load_eval_cases(dataset_path)
        retriever = HybridRetriever(kb_path=kb_path, hybrid_weight=0.0)
        summary = evaluate_retriever(retriever, dataset["cases"], top_k=2)

        self.assertEqual(summary["case_count"], 1)
        self.assertEqual(summary["top_k"], 2)
        self.assertEqual(summary["hit_at_k"], 1.0)
        self.assertEqual(summary["mrr"], 1.0)
        self.assertEqual(summary["category_hit_rate"], 1.0)
        self.assertTrue(summary["cases"][0]["hit"])
        self.assertEqual(summary["cases"][0]["match_rank"], 1)

    def test_bm25_tokenise_preserves_houdini_axis_tokens(self):
        from houdinimind.rag.bm25 import BM25

        tokens = BM25.tokenise("Move points upward in Y using @P.y")

        self.assertIn("y", tokens)
        self.assertIn("point", tokens)

    def test_hybrid_retriever_prioritises_exact_node_reference_for_parameter_queries(self):
        from houdinimind.rag.retriever import HybridRetriever

        tmp = _workspace_case_dir("hybrid_retriever_exact_node_ranking")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        kb_path = os.path.join(tmp, "knowledge_base.json")
        with open(kb_path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "entries": [
                        {
                            "_id": "stamps",
                            "title": "HScript Expression: stamps",
                            "category": "general",
                            "tags": ["hscript", "expression", "parameter"],
                            "content": (
                                "What does stamps do? It works with node parameters and "
                                "returns string values from parameters."
                            ),
                        },
                        {
                            "_id": "adaptiveprune",
                            "title": "SOP Node: adaptiveprune",
                            "category": "nodes",
                            "tags": ["sop", "node", "adaptiveprune", "adaptive", "prune"],
                            "content": (
                                "Node Type: adaptiveprune\n"
                                "Network Context: SOP\n"
                                "Parameters:\n"
                                "- group: Group\n"
                                "- seed: Seed"
                            ),
                        },
                    ]
                },
                handle,
            )

        retriever = HybridRetriever(kb_path=kb_path, hybrid_weight=0.0)
        results = retriever.retrieve(
            "What does the adaptiveprune SOP node do and what parameters does it have?",
            top_k=2,
            min_score=0.0,
        )

        self.assertEqual(results[0]["title"], "SOP Node: adaptiveprune")

    def test_hybrid_retriever_ranks_explicit_vex_example_first_for_axis_motion_query(self):
        from houdinimind.rag.retriever import HybridRetriever

        tmp = _workspace_case_dir("hybrid_retriever_exact_vex_example")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        kb_path = os.path.join(tmp, "knowledge_base.json")
        with open(kb_path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "entries": [
                        {
                            "_id": "patterns",
                            "title": "VEX — Common Attribute Wrangle Patterns",
                            "category": "vex",
                            "tags": ["vex", "wrangle", "snippet", "code"],
                            "content": "Generic snippet patterns for Attribute Wrangle SOPs.",
                        },
                        {
                            "_id": "mirror_x",
                            "title": "VEX: Mirror geometry on X (Simple logic)",
                            "category": "vex",
                            "tags": ["mirror", "projection"],
                            "content": "Simple logic for mirroring geometry along X.",
                        },
                        {
                            "_id": "add_to_y",
                            "title": "VEX Example: Add to Y",
                            "category": "vex",
                            "tags": ["vex", "example", "add", "y", "point"],
                            "content": (
                                "Explanation: displaces the point position upward.\n"
                                "Code:\n"
                                "@P.y += 1.0;"
                            ),
                        },
                    ]
                },
                handle,
            )

        retriever = HybridRetriever(kb_path=kb_path, hybrid_weight=0.0)
        results = retriever.retrieve(
            "Give me a simple VEX snippet to move points upward in Y.",
            top_k=3,
            min_score=0.0,
        )

        self.assertEqual(results[0]["title"], "VEX Example: Add to Y")

    def test_context_injector_reset_turn_allows_reusing_same_chunk_next_turn(self):
        from houdinimind.rag.injector import ContextInjector

        class _FakeRetriever:
            def retrieve(self, **_kwargs):
                return [
                    {
                        "id": "workflow_1",
                        "title": "Table Workflow",
                        "category": "workflow",
                        "content": "Create a box, then finalize to OUT.",
                        "_score": 0.9,
                    }
                ]

            def get_chunk(self, _cid):
                return None

        injector = ContextInjector(
            retriever=_FakeRetriever(),
            max_context_tokens=128,
            model_name="qwen3.5:32b",
        )

        first = injector.build_context_message("create a table")
        second = injector.build_context_message("create a table")
        injector.reset_turn()
        third = injector.build_context_message("create a table")

        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertIsNotNone(third)

    def test_hybrid_retriever_prefetches_embeddings_without_blocking_first_retrieve(self):
        import threading
        import time

        from houdinimind.rag.retriever import HybridRetriever

        tmp = _workspace_case_dir("hybrid_retriever_prefetch")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        kb_path = os.path.join(tmp, "knowledge_base.json")
        with open(kb_path, "w", encoding="utf-8") as handle:
            json.dump(
                [
                    {
                        "_id": "box_workflow",
                        "title": "Box Workflow",
                        "category": "workflow",
                        "tags": ["box"],
                        "content": "Use a box SOP.",
                    },
                    {
                        "_id": "merge_workflow",
                        "title": "Merge Workflow",
                        "category": "workflow",
                        "tags": ["merge"],
                        "content": "Use a merge and OUT node.",
                    },
                ],
                handle,
            )

        gate = threading.Event()

        def embed_fn(text):
            if text == "box":
                return [1.0, 0.0]
            gate.wait(0.25)
            return [1.0, 0.0]

        retriever = HybridRetriever(kb_path=kb_path, embed_fn=embed_fn, hybrid_weight=0.4)
        started = time.perf_counter()
        results = retriever.retrieve("box", top_k=1)
        elapsed = time.perf_counter() - started
        gate.set()

        self.assertTrue(results)
        self.assertLess(elapsed, 0.2)

    def test_hybrid_retriever_restores_persisted_vectors_for_shard_subset(self):
        from houdinimind.rag.retriever import HybridRetriever

        tmp = _workspace_case_dir("hybrid_retriever_vectors_sidecar")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        kb_path = os.path.join(tmp, "knowledge_base.json")
        entries = [
            {
                "_id": "table_workflow",
                "title": "Table Workflow",
                "category": "workflow",
                "tags": ["table", "workflow"],
                "content": "Create a tabletop and four legs, then merge and finalize to OUT.",
            },
            {
                "_id": "chair_workflow",
                "title": "Chair Workflow",
                "category": "workflow",
                "tags": ["chair", "workflow"],
                "content": "Create a seat, back, and legs, then merge and finalize.",
            },
        ]
        with open(kb_path, "w", encoding="utf-8") as handle:
            json.dump({"entries": entries}, handle)

        embed_calls = {"count": 0}

        def embed_fn(text):
            embed_calls["count"] += 1
            return [float(len(text) % 11), 1.0]

        retriever = HybridRetriever(
            kb_path=kb_path,
            embed_fn=embed_fn,
            hybrid_weight=0.4,
            prefetch_embeddings=False,
        )
        retriever._embed_worker(retriever._embed_generation)

        vectors_path = os.path.splitext(kb_path)[0] + ".vectors.json"
        self.assertTrue(os.path.exists(vectors_path))
        self.assertGreaterEqual(embed_calls["count"], len(entries))

        restore_calls = {"count": 0}

        def restore_embed_fn(_text):
            restore_calls["count"] += 1
            return [0.0, 0.0]

        shard_retriever = HybridRetriever(
            kb_path=kb_path + "#workflow_assets",
            entries=[entries[0]],
            embed_fn=restore_embed_fn,
            hybrid_weight=0.4,
            prefetch_embeddings=False,
        )

        self.assertTrue(shard_retriever._embed_done)
        self.assertIsNotNone(shard_retriever._vectors[0])
        self.assertEqual(restore_calls["count"], 0)

    def test_hybrid_retriever_mmr_limits_candidate_pool_to_two_x_top_k_floor_ten(self):
        import houdinimind.rag.retriever as retriever_mod
        from houdinimind.rag.retriever import HybridRetriever

        tmp = _workspace_case_dir("hybrid_retriever_mmr_candidate_pool")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        kb_path = os.path.join(tmp, "knowledge_base.json")
        entries = []
        for idx in range(12):
            entries.append(
                {
                    "_id": f"entry_{idx}",
                    "title": f"Workflow Example {idx}",
                    "category": "workflow",
                    "tags": ["workflow", "example", f"asset{idx}"],
                    "content": f"Generic workflow example {idx} for a procedural asset.",
                }
            )
        with open(kb_path, "w", encoding="utf-8") as handle:
            json.dump({"entries": entries}, handle)

        def embed_fn(_text):
            return [1.0, 0.0]

        retriever = HybridRetriever(
            kb_path=kb_path,
            embed_fn=embed_fn,
            hybrid_weight=0.4,
            prefetch_embeddings=False,
        )
        retriever._embed_worker(retriever._embed_generation)

        original_cosine = retriever_mod._cosine
        cosine_calls = {"count": 0}

        def counting_cosine(a, b):
            cosine_calls["count"] += 1
            return original_cosine(a, b)

        try:
            retriever_mod._cosine = counting_cosine
            retriever.retrieve(
                "show me a procedural asset workflow",
                top_k=2,
                min_score=0.0,
                use_rerank=False,
            )
        finally:
            retriever_mod._cosine = original_cosine

        self.assertEqual(cosine_calls["count"], 21)

    def test_read_only_tools_are_cached_per_turn(self):
        import houdinimind.agent.loop as loop_mod
        from houdinimind.agent.loop import AgentLoop

        tmp = _workspace_case_dir("loop_cache")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        loop = AgentLoop({"data_dir": tmp, "ollama_url": "http://localhost:11434"})
        original_tool = loop_mod.TOOL_FUNCTIONS["get_scene_summary"]
        calls = {"count": 0}

        def fake_scene_summary(depth=3):
            calls["count"] += 1
            return {
                "status": "ok",
                "message": "OK",
                "data": {"depth": depth, "count": calls["count"]},
            }

        try:
            loop_mod.TOOL_FUNCTIONS["get_scene_summary"] = fake_scene_summary
            first = loop._execute_tool("get_scene_summary", {"depth": 2})
            second = loop._execute_tool("get_scene_summary", {"depth": 2})
        finally:
            loop_mod.TOOL_FUNCTIONS["get_scene_summary"] = original_tool

        self.assertEqual(first["status"], "ok")
        self.assertEqual(second["status"], "ok")
        self.assertEqual(calls["count"], 1)
        self.assertTrue(second["_meta"]["cached"])
        self.assertIn("valid for this turn", first["message"])
        self.assertIn("Returned from the turn cache", second["message"])

    def test_agent_loop_followup_build_requests_stay_in_build_mode(self):
        from houdinimind.agent.loop import AgentLoop

        tmp = _workspace_case_dir("loop_followup_build_mode")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        loop = AgentLoop({"data_dir": tmp, "ollama_url": "http://localhost:11434"})
        loop.conversation = [
            {"role": "user", "content": "Create a table with four legs."},
            {
                "role": "assistant",
                "content": "Created /obj/table1 and finalized to /obj/table1/OUT.",
            },
        ]

        mode, confidence = loop._classify_request_mode("now make it bigger and add materials")
        alt_mode, alt_confidence = loop._classify_request_mode("what if we used a sphere instead?")
        fx_mode, fx_confidence = loop._classify_request_mode(
            "Now fracture this object using an RBD workflow."
        )
        direct_fx_mode, direct_fx_confidence = loop._classify_request_mode(
            "fracture the selected geometry"
        )

        self.assertEqual(mode, "build")
        self.assertGreaterEqual(confidence, 0.8)
        self.assertEqual(alt_mode, "build")
        self.assertGreaterEqual(alt_confidence, 0.8)
        self.assertEqual(fx_mode, "build")
        self.assertGreaterEqual(fx_confidence, 0.8)
        self.assertEqual(direct_fx_mode, "build")
        self.assertGreaterEqual(direct_fx_confidence, 0.9)

    def test_advice_mode_tool_schemas_are_read_only(self):
        from houdinimind.agent.loop import AgentLoop

        tmp = _workspace_case_dir("loop_advice_read_only_tools")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        loop = AgentLoop({"data_dir": tmp, "ollama_url": "http://localhost:11434"})
        original_select = loop.llm.select_relevant_tools

        schemas = [
            {"function": {"name": "get_scene_summary"}},
            {"function": {"name": "create_node"}},
            {"function": {"name": "safe_set_parameter"}},
            {"function": {"name": "search_knowledge"}},
        ]
        try:
            loop.llm.select_relevant_tools = lambda **_kwargs: schemas
            selected = loop._get_tool_schemas_for_request("how should I approach this?", "advice")
        finally:
            loop.llm.select_relevant_tools = original_select

        names = [s["function"]["name"] for s in selected]
        self.assertEqual(names, ["get_scene_summary", "search_knowledge"])

    def test_history_compression_prompt_keeps_connection_topology(self):
        from houdinimind.agent.loop import AgentLoop

        tmp = _workspace_case_dir("loop_history_connections")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        loop = AgentLoop({"data_dir": tmp, "ollama_url": "http://localhost:11434"})
        captured = {}
        original_chat_simple = loop.llm.chat_simple

        long_scene_diff = (
            "[SCENE DIFF]\n" + ("x" * 350) + "\nConnected: /obj/geo1/box1 -> /obj/geo1/merge1[0]"
        )

        def fake_chat_simple(system, user, temperature=0.05, task="quick"):
            captured["system"] = system
            captured["user"] = user
            return (
                "GOAL: Maintain the build state\n"
                "NODES_CREATED: /obj/geo1/box1, /obj/geo1/merge1\n"
                "CONNECTIONS: /obj/geo1/box1→/obj/geo1/merge1:0\n"
                "PARMS_SET: NONE\n"
                "ERRORS_FIXED: NONE\n"
                "INCOMPLETE: NONE"
            )

        try:
            loop.llm.chat_simple = fake_chat_simple
            loop.conversation = []
            for idx in range(loop.compress_at + 2):
                loop.conversation.append({"role": "user", "content": f"user turn {idx}"})
                assistant_content = long_scene_diff if idx == 0 else f"assistant turn {idx}"
                loop.conversation.append({"role": "assistant", "content": assistant_content})
            loop._compress_history_if_needed()
        finally:
            loop.llm.chat_simple = original_chat_simple

        self.assertIn("CONNECTIONS:", captured["system"])
        self.assertIn("Connected: /obj/geo1/box1 -> /obj/geo1/merge1[0]", captured["user"])
        self.assertTrue(loop.conversation[0]["content"].startswith("[COMPRESSED HISTORY]"))

    def test_build_loop_uses_fast_route_then_skips_duplicate_failures(self):
        import houdinimind.agent.loop as loop_mod
        from houdinimind.agent.loop import AgentLoop

        tmp = _workspace_case_dir("loop_fast_route")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        loop = AgentLoop(
            {
                "data_dir": tmp,
                "ollama_url": "http://localhost:11434",
                "fast_build_rounds": 3,
            }
        )
        original_tool = loop_mod.TOOL_FUNCTIONS["create_node"]
        tool_calls = {"count": 0}
        llm_calls = {"tasks": [], "index": 0}
        repeated_args = {"parent_path": "/obj", "node_type": "badnode", "name": "test1"}
        responses = [
            {
                "content": "",
                "tool_calls": [
                    {"function": {"name": "create_node", "arguments": json.dumps(repeated_args)}}
                ],
            },
            {
                "content": "",
                "tool_calls": [
                    {"function": {"name": "create_node", "arguments": json.dumps(repeated_args)}}
                ],
            },
            {"content": "Recovered.", "tool_calls": []},
        ]

        def fake_create_node(**_kwargs):
            tool_calls["count"] += 1
            return {"status": "error", "message": "Unknown node type", "data": None}

        def fake_chat(messages, tools=None, task=None, model_override=None, **kwargs):
            llm_calls["tasks"].append(task)
            response = responses[llm_calls["index"]]
            llm_calls["index"] += 1
            return response

        try:
            loop_mod.TOOL_FUNCTIONS["create_node"] = fake_create_node
            loop.llm.chat = fake_chat
            result = loop._run_loop(
                [{"role": "user", "content": "build a quick test"}],
                request_mode="build",
            )
        finally:
            loop_mod.TOOL_FUNCTIONS["create_node"] = original_tool

        self.assertEqual(result, "Recovered.")
        self.assertEqual(tool_calls["count"], 1)
        self.assertEqual(llm_calls["tasks"][0], "build")
        self.assertIsNone(llm_calls["tasks"][1])

    def test_run_loop_falls_back_to_local_summary_after_late_llm_timeout(self):
        import houdinimind.agent.loop as loop_mod
        from houdinimind.agent.loop import AgentLoop

        tmp = _workspace_case_dir("loop_local_fallback_timeout")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        loop = AgentLoop({"data_dir": tmp, "ollama_url": "http://localhost:11434"})
        original_tool = loop_mod.TOOL_FUNCTIONS["create_node"]
        llm_calls = {"count": 0}

        def fake_create_node(**_kwargs):
            return {
                "status": "ok",
                "message": "UNDO_TRACK: Created /obj/geo1/box1",
                "data": {"path": "/obj/geo1/box1"},
            }

        def fake_chat(*_args, **_kwargs):
            if llm_calls["count"] == 0:
                llm_calls["count"] += 1
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "create_node",
                                "arguments": json.dumps(
                                    {
                                        "parent_path": "/obj/geo1",
                                        "node_type": "box",
                                        "name": "box1",
                                    }
                                ),
                            }
                        }
                    ],
                }
            raise ConnectionError("Cannot reach Ollama at http://localhost:11434. timed out")

        try:
            loop_mod.TOOL_FUNCTIONS["create_node"] = fake_create_node
            loop.llm.chat = fake_chat
            result = loop._run_loop(
                [{"role": "user", "content": "Build a quick box"}],
                request_mode="build",
            )
        finally:
            loop_mod.TOOL_FUNCTIONS["create_node"] = original_tool

        self.assertIn("Scene edits were applied", result)
        self.assertIn("[SCENE DIFF]", result)
        self.assertIn("/obj/geo1/box1", result)

    def test_run_loop_exits_with_local_summary_near_round_limit_when_output_is_stable(self):
        import houdinimind.agent.loop as loop_mod
        from houdinimind.agent.loop import AgentLoop

        tmp = _workspace_case_dir("loop_stable_round_limit_exit")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        loop = AgentLoop(
            {
                "data_dir": tmp,
                "ollama_url": "http://localhost:11434",
                "max_tool_rounds": 3,
            }
        )
        original_create = loop_mod.TOOL_FUNCTIONS["create_node"]
        original_display = loop_mod.TOOL_FUNCTIONS["set_display_flag"]
        original_summary = loop_mod.TOOL_FUNCTIONS["get_scene_summary"]
        original_snapshot = loop._capture_scene_snapshot
        llm_calls = {"index": 0}
        responses = [
            {
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "create_node",
                            "arguments": json.dumps(
                                {
                                    "parent_path": "/obj/geo1",
                                    "node_type": "box",
                                    "name": "box1",
                                }
                            ),
                        }
                    }
                ],
            },
            {
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "set_display_flag",
                            "arguments": json.dumps(
                                {
                                    "node_path": "/obj/geo1/OUT",
                                    "display": True,
                                    "render": True,
                                }
                            ),
                        }
                    }
                ],
            },
            {
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "get_scene_summary",
                            "arguments": json.dumps({"depth": 2}),
                        }
                    }
                ],
            },
        ]

        def fake_create_node(**_kwargs):
            return {
                "status": "ok",
                "message": "UNDO_TRACK: Created /obj/geo1/box1",
                "data": {"path": "/obj/geo1/box1"},
            }

        def fake_set_display_flag(**_kwargs):
            return {
                "status": "ok",
                "message": "UNDO_TRACK: Set display=True on /obj/geo1/OUT",
                "data": {"node_path": "/obj/geo1/OUT"},
            }

        def fake_scene_summary(**_kwargs):
            return {"status": "ok", "message": "Scene summary ready", "data": {}}

        def fake_chat(*_args, **_kwargs):
            response = responses[llm_calls["index"]]
            llm_calls["index"] += 1
            return response

        try:
            loop_mod.TOOL_FUNCTIONS["create_node"] = fake_create_node
            loop_mod.TOOL_FUNCTIONS["set_display_flag"] = fake_set_display_flag
            loop_mod.TOOL_FUNCTIONS["get_scene_summary"] = fake_scene_summary
            loop._capture_scene_snapshot = lambda: {
                "nodes": [
                    {
                        "path": "/obj/geo1/OUT",
                        "name": "OUT",
                        "is_displayed": True,
                        "is_render_flag": True,
                    }
                ],
                "connections": [],
            }
            loop.llm.chat = fake_chat
            result = loop._run_loop(
                [{"role": "user", "content": "Build a quick box"}],
                request_mode="build",
            )
        finally:
            loop_mod.TOOL_FUNCTIONS["create_node"] = original_create
            loop_mod.TOOL_FUNCTIONS["set_display_flag"] = original_display
            loop_mod.TOOL_FUNCTIONS["get_scene_summary"] = original_summary
            loop._capture_scene_snapshot = original_snapshot

        self.assertIn("Visible output: /obj/geo1/OUT", result)
        self.assertIn("[SCENE DIFF]", result)
        self.assertNotIn("Max tool rounds reached", result)

    def test_run_loop_resets_failure_streak_after_successful_rounds(self):
        import houdinimind.agent.loop as loop_mod
        from houdinimind.agent.loop import AgentLoop

        tmp = _workspace_case_dir("loop_failure_streak_reset")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        loop = AgentLoop({"data_dir": tmp, "ollama_url": "http://localhost:11434"})
        original_create = loop_mod.TOOL_FUNCTIONS["create_node"]
        original_summary = loop_mod.TOOL_FUNCTIONS["get_scene_summary"]
        failure_calls = {"count": 0}
        success_calls = {"count": 0}
        llm_calls = {"index": 0}
        responses = [
            {
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "create_node",
                            "arguments": json.dumps(
                                {
                                    "parent_path": "/obj",
                                    "node_type": "badnode",
                                    "name": "bad1",
                                }
                            ),
                        }
                    }
                ],
            },
            {
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "get_scene_summary",
                            "arguments": json.dumps({"depth": 1}),
                        }
                    }
                ],
            },
            {
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "create_node",
                            "arguments": json.dumps(
                                {
                                    "parent_path": "/obj",
                                    "node_type": "badnode",
                                    "name": "bad2",
                                }
                            ),
                        }
                    }
                ],
            },
            {
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "get_scene_summary",
                            "arguments": json.dumps({"depth": 2}),
                        }
                    }
                ],
            },
            {
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "create_node",
                            "arguments": json.dumps(
                                {
                                    "parent_path": "/obj",
                                    "node_type": "badnode",
                                    "name": "bad3",
                                }
                            ),
                        }
                    }
                ],
            },
            {"content": "Recovered.", "tool_calls": []},
        ]

        def fake_create_node(**_kwargs):
            failure_calls["count"] += 1
            return {
                "status": "error",
                "message": f"Unknown node type {failure_calls['count']}",
                "data": None,
            }

        def fake_scene_summary(**_kwargs):
            success_calls["count"] += 1
            return {"status": "ok", "message": "Scene summary ready", "data": {}}

        def fake_chat(*_args, **_kwargs):
            response = responses[llm_calls["index"]]
            llm_calls["index"] += 1
            return response

        try:
            loop_mod.TOOL_FUNCTIONS["create_node"] = fake_create_node
            loop_mod.TOOL_FUNCTIONS["get_scene_summary"] = fake_scene_summary
            loop.llm.chat = fake_chat
            result = loop._run_loop(
                [{"role": "user", "content": "Build a quick test network"}],
                request_mode="build",
            )
        finally:
            loop_mod.TOOL_FUNCTIONS["create_node"] = original_create
            loop_mod.TOOL_FUNCTIONS["get_scene_summary"] = original_summary

        self.assertEqual(result, "Recovered.")
        self.assertEqual(failure_calls["count"], 3)
        self.assertEqual(success_calls["count"], 2)

    def test_run_loop_recovers_from_malformed_tool_arguments(self):
        import houdinimind.agent.loop as loop_mod
        from houdinimind.agent.loop import AgentLoop

        tmp = _workspace_case_dir("loop_bad_tool_json_recovery")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        loop = AgentLoop({"data_dir": tmp, "ollama_url": "http://localhost:11434"})
        original_create = loop_mod.TOOL_FUNCTIONS["create_node"]
        create_calls = {"count": 0}
        llm_calls = {"index": 0}
        responses = [
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_bad_json",
                        "function": {
                            "name": "create_node",
                            "arguments": '{"parent_path": "/obj", "node_type": "box",',
                        },
                    }
                ],
            },
            {"content": "Recovered after correcting the tool call.", "tool_calls": []},
        ]

        def fake_create_node(**_kwargs):
            create_calls["count"] += 1
            return {"status": "ok", "message": "created", "data": {}}

        def fake_chat(messages, *_args, **_kwargs):
            if llm_calls["index"] == 1:
                tool_messages = [m for m in messages if m.get("role") == "tool"]
                self.assertTrue(tool_messages)
                self.assertEqual(tool_messages[-1].get("tool_call_id"), "call_bad_json")
                self.assertIn("Argument JSON parsing failed", tool_messages[-1]["content"])
            response = responses[llm_calls["index"]]
            llm_calls["index"] += 1
            return response

        try:
            loop_mod.TOOL_FUNCTIONS["create_node"] = fake_create_node
            loop.llm.chat = fake_chat
            result = loop._run_loop(
                [{"role": "user", "content": "Build a box"}],
                request_mode="build",
            )
        finally:
            loop_mod.TOOL_FUNCTIONS["create_node"] = original_create

        self.assertEqual(result, "Recovered after correcting the tool call.")
        self.assertEqual(create_calls["count"], 0)

    def test_build_loop_returns_friendly_message_on_llm_overload(self):
        from houdinimind.agent.loop import AgentLoop

        tmp = _workspace_case_dir("loop_llm_overload")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        loop = AgentLoop({"data_dir": tmp, "ollama_url": "http://localhost:11434"})
        loop.llm.chat = lambda *args, **kwargs: (_ for _ in ()).throw(
            ConnectionError("Ollama is overloaded (429). Please wait about 12s before retrying.")
        )

        result = loop._run_loop(
            [{"role": "user", "content": "build a table"}],
            request_mode="build",
        )

        self.assertIn("overloaded", result.lower())
        self.assertIn("wait", result.lower())

    def test_run_loop_streams_final_text_in_chunks(self):
        from houdinimind.agent.loop import AgentLoop

        tmp = _workspace_case_dir("loop_stream_chunks")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        loop = AgentLoop({"data_dir": tmp, "ollama_url": "http://localhost:11434"})
        text = " ".join(f"word{i}" for i in range(45))
        chunks = []
        original_chat = loop.llm.chat

        try:
            loop.llm.chat = lambda *args, **kwargs: {"content": text, "tool_calls": []}
            result = loop._run_loop(
                [{"role": "user", "content": "Explain the result"}],
                stream_callback=chunks.append,
            )
        finally:
            loop.llm.chat = original_chat

        self.assertEqual(result, text)
        self.assertEqual("".join(chunks), text)
        self.assertEqual(len(chunks), 3)

    def test_transient_llm_failure_detects_connection_errors(self):
        from houdinimind.agent.loop import AgentLoop

        self.assertTrue(
            AgentLoop._is_transient_llm_failure(
                "⚠️ Cannot reach Ollama at http://localhost:11434. [WinError 10048] Only one usage of each socket address is normally permitted"
            )
        )
        self.assertTrue(
            AgentLoop._is_transient_llm_failure(
                "⚠️ Cannot reach Ollama at http://localhost:11434. [WinError 10061] No connection could be made because the target machine actively refused it"
            )
        )

    def test_reconcile_final_response_after_verification_rewrites_stale_failure(self):
        from houdinimind.agent.loop import AgentLoop

        tmp = _workspace_case_dir("reconcile_final_response")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        loop = AgentLoop({"data_dir": tmp, "ollama_url": "http://localhost:11434"})

        result = loop._reconcile_final_response_after_verification(
            "Max tool rounds reached — some steps may be incomplete.",
            {"status": "pass", "outputs": ["/obj/geo1/OUT"]},
        )

        self.assertIn("Verification passed", result)
        self.assertIn("/obj/geo1/OUT", result)
        self.assertNotIn("Max tool rounds reached", result)

    def test_build_grounded_turn_response_uses_verified_scene_facts(self):
        from houdinimind.agent.loop import AgentLoop

        tmp = _workspace_case_dir("grounded_turn_response")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        loop = AgentLoop({"data_dir": tmp, "ollama_url": "http://localhost:11434"})
        loop._last_turn_write_tools = ["create_node_chain", "finalize_sop_network"]
        loop._last_turn_output_paths = ["/obj/sofa_geo/OUT"]
        loop._last_turn_scene_diff_text = (
            "[SCENE DIFF]\n"
            "- Create chain: /obj/sofa_geo/base, /obj/sofa_geo/OUT\n"
            "- Finalize visible SOP output /obj/sofa_geo/OUT"
        )
        loop._last_turn_verification_report = {
            "status": "pass",
            "summary": "Verification passed. The current result looks structurally sound.",
            "outputs": ["/obj/sofa_geo/OUT"],
        }
        loop._last_turn_verification_text = (
            "[VERIFICATION] PASS\nOutputs checked: /obj/sofa_geo/OUT"
        )

        result = loop._build_grounded_turn_response(
            "build",
            "Sofa build complete with box_backrest and box_seat nodes.",
        )

        self.assertIn("Build completed successfully.", result)
        self.assertIn("Visible output: /obj/sofa_geo/OUT", result)
        self.assertIn("[SCENE DIFF]", result)
        self.assertNotIn("box_backrest", result)

    def test_chat_with_vision_injects_reference_proxy_spec_for_builds(self):
        from houdinimind.agent.loop import AgentLoop

        tmp = _workspace_case_dir("vision_proxy_spec")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        loop = AgentLoop({"data_dir": tmp, "ollama_url": "http://localhost:11434"})
        original_chat_vision = loop.llm.chat_vision
        original_classify = loop._classify_request_mode
        original_chat = loop.chat
        original_build_proxy = loop._reference_proxy_planner.build_proxy_spec
        captured = {}

        try:
            loop.llm.chat_vision = lambda *args, **kwargs: (
                "A blocky three-seat sofa with broad arms."
            )
            loop._classify_request_mode = lambda _msg: ("build", 0.95)
            loop._reference_proxy_planner.build_proxy_spec = lambda *args, **kwargs: {
                "object": "sofa",
                "components": [{"name": "seat", "primitive": "box", "notes": "wide low cushion"}],
                "assembly_notes": ["keep the arms level with the seat"],
            }

            def fake_chat(message, stream_callback=None, dry_run=False, status_callback=None):
                captured["message"] = message
                return "ok"

            loop.chat = fake_chat
            result = loop.chat_with_vision("Create this sofa", b"fake-image")
        finally:
            loop.llm.chat_vision = original_chat_vision
            loop._classify_request_mode = original_classify
            loop.chat = original_chat
            loop._reference_proxy_planner.build_proxy_spec = original_build_proxy

        self.assertEqual(result, "ok")
        self.assertIn("[VISION ANALYSIS OF ATTACHED IMAGE]", captured["message"])
        self.assertIn("[REFERENCE PROXY SPEC]", captured["message"])
        self.assertIn("Target object: sofa", captured["message"])

    def test_chat_skips_verification_after_backend_connection_failure(self):
        from houdinimind.agent.loop import AgentLoop

        tmp = _workspace_case_dir("chat_connection_failure")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        loop = AgentLoop({"data_dir": tmp, "ollama_url": "http://localhost:11434"})
        calls = {"verification": 0}

        original_run_loop = loop._run_loop
        original_verify = loop._run_verification_suite
        original_capture = loop._capture_debug_screenshot
        original_refresh = loop._refresh_live_scene_context
        original_snapshot = loop._capture_scene_snapshot
        original_plan = loop._generate_plan
        original_grounding = loop._build_workflow_grounding_message

        try:
            loop._run_loop = lambda *args, **kwargs: (
                "⚠️ Cannot reach Ollama at http://localhost:11434. "
                "[WinError 10048] Only one usage of each socket address "
                "(protocol/network address/port) is normally permitted"
            )

            def fake_verify(*_args, **_kwargs):
                calls["verification"] += 1
                return {"status": "fail", "text": "[VERIFICATION] FAIL"}

            loop._run_verification_suite = fake_verify
            loop._capture_debug_screenshot = lambda *args, **kwargs: None
            loop._refresh_live_scene_context = lambda *args, **kwargs: None
            loop._capture_scene_snapshot = lambda *args, **kwargs: {"nodes": [], "connections": []}
            loop._generate_plan = lambda *args, **kwargs: None
            loop._build_workflow_grounding_message = lambda *args, **kwargs: None

            result = loop.chat("Create a bed with a headboard")
        finally:
            loop._run_loop = original_run_loop
            loop._run_verification_suite = original_verify
            loop._capture_debug_screenshot = original_capture
            loop._refresh_live_scene_context = original_refresh
            loop._capture_scene_snapshot = original_snapshot
            loop._generate_plan = original_plan
            loop._build_workflow_grounding_message = original_grounding

        self.assertIn("Cannot reach Ollama", result)
        self.assertEqual(calls["verification"], 0)
        self.assertNotIn("[VERIFICATION]", result)

    def test_chat_build_turn_does_not_preload_live_scene_context_when_unused(self):
        from houdinimind.agent.loop import AgentLoop

        tmp = _workspace_case_dir("chat_skip_live_scene_preload")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        loop = AgentLoop({"data_dir": tmp, "ollama_url": "http://localhost:11434"})
        calls = {"refresh": 0}

        original_run_loop = loop._run_loop
        original_capture = loop._capture_debug_screenshot
        original_snapshot = loop._capture_scene_snapshot
        original_plan = loop._generate_plan
        original_grounding = loop._build_workflow_grounding_message
        original_retry_check = loop._should_retry_build_turn
        original_refresh = loop._refresh_live_scene_context

        try:
            loop._run_loop = lambda *args, **kwargs: (
                "Created /obj/table1 and finalized /obj/table1/OUT."
            )
            loop._capture_debug_screenshot = lambda *args, **kwargs: None
            loop._capture_scene_snapshot = lambda: {"nodes": [], "connections": []}
            loop._generate_plan = lambda *args, **kwargs: None
            loop._build_workflow_grounding_message = lambda *args, **kwargs: None
            loop._should_retry_build_turn = lambda *args, **kwargs: False

            def fake_refresh(depth=3):
                calls["refresh"] += 1
                return "{}"

            loop._refresh_live_scene_context = fake_refresh
            result = loop.chat("Create a table", dry_run=False)
        finally:
            loop._run_loop = original_run_loop
            loop._capture_debug_screenshot = original_capture
            loop._capture_scene_snapshot = original_snapshot
            loop._generate_plan = original_plan
            loop._build_workflow_grounding_message = original_grounding
            loop._should_retry_build_turn = original_retry_check
            loop._refresh_live_scene_context = original_refresh

        self.assertIn("Created /obj/table1", result)
        self.assertEqual(calls["refresh"], 0)

    def test_chat_skips_verification_when_build_turn_makes_no_writes(self):
        from houdinimind.agent.loop import AgentLoop

        tmp = _workspace_case_dir("chat_no_write_skip_verification")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        loop = AgentLoop({"data_dir": tmp, "ollama_url": "http://localhost:11434"})
        calls = {"verification": 0}

        original_run_loop = loop._run_loop
        original_verify = loop._run_verification_suite
        original_capture = loop._capture_debug_screenshot
        original_refresh = loop._refresh_live_scene_context
        original_snapshot = loop._capture_scene_snapshot
        original_plan = loop._generate_plan
        original_grounding = loop._build_workflow_grounding_message
        original_retry_check = loop._should_retry_build_turn

        try:
            loop._run_loop = lambda *args, **kwargs: "No scene changes were needed."
            loop._run_verification_suite = lambda *args, **kwargs: (
                calls.__setitem__("verification", calls["verification"] + 1) or {"status": "pass"}
            )
            loop._capture_debug_screenshot = lambda *args, **kwargs: None
            loop._refresh_live_scene_context = lambda *args, **kwargs: None
            loop._capture_scene_snapshot = lambda *args, **kwargs: {"nodes": [], "connections": []}
            loop._generate_plan = lambda *args, **kwargs: None
            loop._build_workflow_grounding_message = lambda *args, **kwargs: None
            loop._should_retry_build_turn = lambda *args, **kwargs: False

            result = loop.chat("Create a table")
        finally:
            loop._run_loop = original_run_loop
            loop._run_verification_suite = original_verify
            loop._capture_debug_screenshot = original_capture
            loop._refresh_live_scene_context = original_refresh
            loop._capture_scene_snapshot = original_snapshot
            loop._generate_plan = original_plan
            loop._build_workflow_grounding_message = original_grounding
            loop._should_retry_build_turn = original_retry_check

        self.assertIn("No scene changes", result)
        self.assertEqual(calls["verification"], 0)
        self.assertNotIn("[VERIFICATION]", result)

    def test_tool_progress_messages_are_human_readable(self):
        from houdinimind.agent.loop import AgentLoop

        create_msg = AgentLoop._describe_tool_action(
            "create_node",
            {"parent_path": "/obj/geo1", "node_type": "box", "name": "tabletop"},
        )
        parm_msg = AgentLoop._describe_tool_action(
            "safe_set_parameter",
            {"node_path": "/obj/geo1/tabletop", "parm_name": "sizey"},
        )
        fail_msg = AgentLoop._describe_tool_failure(
            "safe_set_parameter",
            {"node_path": "/obj/geo1/tabletop", "parm_name": "sizey"},
            "parm not found",
        )

        self.assertIn("creating", create_msg.lower())
        self.assertIn("tabletop", create_msg.lower())
        self.assertIn("adjusting", parm_msg.lower())
        self.assertIn("sizey", parm_msg.lower())
        self.assertIn("parameter", fail_msg.lower())

    def test_panel_extracts_primary_response_without_scene_diff(self):
        from hm_ui.panel import HoudiniMindPanel

        result = (
            "Built the table with four legs and a visible OUT.\n\n"
            "[SCENE DIFF]\n"
            "- Create /obj/table\n"
            "- Set /obj/table/OUT display flag"
        )
        diff = "[SCENE DIFF]\n- Create /obj/table\n- Set /obj/table/OUT display flag"

        summary = HoudiniMindPanel._extract_primary_response(result, diff)

        self.assertEqual(summary, "Built the table with four legs and a visible OUT.")

    def test_panel_summarizes_scene_diff_compactly(self):
        from hm_ui.panel import HoudiniMindPanel

        diff = (
            "[PLANNED SCENE DIFF]\n"
            "- Create /obj/table\n"
            "- Create /obj/table/merge_final\n"
            "- Set /obj/table/OUT display flag\n"
            "- Layout children"
        )

        summary = HoudiniMindPanel._summarize_scene_diff(diff)

        self.assertIn("Create /obj/table", summary)
        self.assertIn("Create /obj/table/merge_final", summary)
        self.assertIn("Set /obj/table/OUT display flag", summary)

    def test_panel_identifies_status_only_messages(self):
        from hm_ui.panel import HoudiniMindPanel

        self.assertTrue(
            HoudiniMindPanel._looks_like_status_message(
                "Ollama is overloaded (429). Please wait about 12s before retrying."
            )
        )
        self.assertFalse(
            HoudiniMindPanel._looks_like_status_message(
                "Built the table with a visible OUT and clean merge."
            )
        )

    def test_auto_researcher_prefers_simple_reliable_build_option(self):
        from houdinimind.agent.loop import AutoResearcher

        researcher = AutoResearcher(llm=None)
        options = [
            {
                "id": 1,
                "label": "Quick Primitive Table Blockout",
                "summary": "Uses basic Box and Merge SOPs into a Null.",
                "details": "Box SOP.\nMerge SOP.\nNull SOP.\nEnable display flag on Null.",
                "use_when": "Fast, reliable prop creation.",
            },
            {
                "id": 2,
                "label": "Procedural Leg Instancing System",
                "summary": "Uses Copy to Points for variable leg placement.",
                "details": "Box SOP.\nGrid SOP.\nCopy to Points.\nNull SOP.",
                "use_when": "Variable leg counts are needed.",
            },
        ]

        selected = researcher.select_best_option(
            "Create a procedural table with a visible OUT node.",
            options,
            request_mode="build",
        )

        self.assertEqual(selected["id"], 1)
        self.assertIn("output", selected["_selection_reason"].lower())

    def test_research_auto_executes_best_option_by_default(self):
        from houdinimind.agent.loop import AgentLoop

        tmp = _workspace_case_dir("research_auto_execute")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        loop = AgentLoop(
            {
                "data_dir": tmp,
                "ollama_url": "http://localhost:11434",
                "auto_research_execute_best_option": True,
            }
        )
        options = [
            {
                "id": 1,
                "label": "Quick Primitive Table Blockout",
                "summary": "Best fit",
                "details": "Null SOP",
                "use_when": "Reliable",
            },
            {
                "id": 2,
                "label": "Fancy Advanced Variant",
                "summary": "Riskier",
                "details": "Copy to Points",
                "use_when": "Custom",
            },
        ]
        captured = {"selected": None, "messages": []}
        original_run = loop.auto_researcher.run
        original_select = loop.auto_researcher.select_best_option
        original_execute = loop.execute_research_option

        try:
            loop.auto_researcher.run = lambda query, progress_callback=None: options
            loop.auto_researcher.select_best_option = lambda query, opts, request_mode="advice": (
                dict(opts[0], _selection_reason="it is the lowest-risk fit")
            )

            def fake_execute(
                option,
                original_query,
                stream_callback=None,
                log_interaction=True,
                interaction_message=None,
            ):
                captured["selected"] = option["id"]
                if stream_callback:
                    stream_callback(
                        loop.PROGRESS_SENTINEL + "Executing the selected research option."
                    )
                return "Executed best option."

            loop.execute_research_option = fake_execute
            result = loop.research(
                "Create a procedural table with a visible OUT node.",
                stream_callback=captured["messages"].append,
            )
        finally:
            loop.auto_researcher.run = original_run
            loop.auto_researcher.select_best_option = original_select
            loop.execute_research_option = original_execute

        self.assertEqual(result, "Executed best option.")
        self.assertEqual(captured["selected"], 1)
        self.assertTrue(any("I compared 2 approaches" in msg for msg in captured["messages"]))
        self.assertFalse(any("RESEARCH_OPTIONS" in msg for msg in captured["messages"]))

    def test_research_keeps_manual_choice_for_compare_queries(self):
        from houdinimind.agent.loop import AgentLoop, AutoResearcher

        tmp = _workspace_case_dir("research_manual_compare")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        loop = AgentLoop(
            {
                "data_dir": tmp,
                "ollama_url": "http://localhost:11434",
                "auto_research_execute_best_option": True,
            }
        )
        options = [
            {
                "id": 1,
                "label": "Option A",
                "summary": "A",
                "details": "Null SOP",
                "use_when": "When A",
            },
            {
                "id": 2,
                "label": "Option B",
                "summary": "B",
                "details": "Merge SOP",
                "use_when": "When B",
            },
        ]
        captured = []
        original_run = loop.auto_researcher.run

        try:
            loop.auto_researcher.run = lambda query, progress_callback=None: options
            result = loop.research(
                "Compare the best approaches for building a procedural table.",
                stream_callback=captured.append,
            )
        finally:
            loop.auto_researcher.run = original_run

        self.assertTrue(
            AutoResearcher.should_offer_manual_choice(
                "Compare the best approaches for building a procedural table."
            )
        )
        self.assertIn('"options"', result)
        self.assertTrue(any("RESEARCH_OPTIONS" in msg for msg in captured))

    def test_project_rule_book_learns_explicit_user_preferences(self):
        from houdinimind.memory.memory_manager import ProjectRuleBook

        tmp = _workspace_case_dir("project_rules")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        book = ProjectRuleBook(os.path.join(tmp, "project_rules.db"))

        remembered = book.remember_from_message(
            "Whatever model shows in the UI it should use that only. The main focus is the agent message."
        )
        prompt = book.render_for_prompt()

        self.assertEqual(len(remembered), 2)
        self.assertIn("Whatever model shows in the UI it should use that only", prompt)
        self.assertIn("The main focus is the agent message", prompt)

    def test_agent_restore_last_turn_checkpoint_loads_saved_backup(self):
        from houdinimind.agent import tools
        from houdinimind.agent.loop import AgentLoop

        tmp = _workspace_case_dir("restore_checkpoint")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        backup_path = os.path.join(tmp, "checkpoint_scene.hip")
        with open(backup_path, "w", encoding="utf-8") as f:
            f.write("fake hip")

        loop = AgentLoop({"data_dir": tmp, "ollama_url": "http://localhost:11434"})
        fake_hou = _FakeHouWithHip()
        original_hou = getattr(tools, "hou", None)
        original_available = tools.HOU_AVAILABLE
        original_refresh = loop._refresh_live_scene_context

        try:
            tools.hou = fake_hou
            tools.HOU_AVAILABLE = True
            loop._refresh_live_scene_context = lambda depth=3: None
            loop._last_turn_checkpoint_path = backup_path
            result = loop.restore_last_turn_checkpoint()
        finally:
            if original_hou is None:
                delattr(tools, "hou")
            else:
                tools.hou = original_hou
            tools.HOU_AVAILABLE = original_available
            loop._refresh_live_scene_context = original_refresh

        self.assertIn("Restored backup", result)
        self.assertEqual(fake_hou.hipFile.loaded["path"], backup_path)
        self.assertTrue(fake_hou.hipFile.loaded["suppress_save_prompt"])

    def test_auto_restore_failed_turn_restores_when_budget_exhausted(self):
        from houdinimind.agent.loop import AgentLoop

        tmp = _workspace_case_dir("auto_restore_failed_turn")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        loop = AgentLoop({"data_dir": tmp, "ollama_url": "http://localhost:11434"})

        loop._last_turn_verification_report = {
            "status": "fail",
            "issues": [{"severity": "repair", "message": "display node disconnected"}],
        }
        loop._last_turn_write_tools = ["create_node"]
        loop._last_turn_checkpoint_path = "/tmp/fake_checkpoint.hip"

        original_restore = loop.restore_last_turn_checkpoint
        try:
            loop.restore_last_turn_checkpoint = lambda: "Restored backup: /tmp/fake_checkpoint.hip"
            note = loop._auto_restore_failed_turn_if_needed(
                request_mode="build",
                dry_run=False,
                remaining_repair_budget=0,
            )
        finally:
            loop.restore_last_turn_checkpoint = original_restore

        self.assertIsNotNone(note)
        self.assertIn("Automatic rollback succeeded", note)

    def test_ensure_turn_checkpoint_is_disabled_by_default(self):
        import houdinimind.agent.loop as loop_mod
        from houdinimind.agent.loop import AgentLoop

        tmp = _workspace_case_dir("checkpoint_default_disabled")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        loop = AgentLoop(
            {
                "data_dir": tmp,
                "ollama_url": "http://localhost:11434",
            }
        )

        original_hou_available = loop_mod.HOU_AVAILABLE
        original_tools = dict(loop_mod.TOOL_FUNCTIONS)
        calls = {"create_backup": 0}
        try:
            loop_mod.HOU_AVAILABLE = True
            loop_mod.TOOL_FUNCTIONS["create_backup"] = lambda: (
                calls.__setitem__("create_backup", calls["create_backup"] + 1)
                or {"status": "ok", "data": {"backup_path": "/tmp/should_not_exist.hip.bak"}}
            )
            loop._ensure_turn_checkpoint()
        finally:
            loop_mod.HOU_AVAILABLE = original_hou_available
            loop_mod.TOOL_FUNCTIONS.clear()
            loop_mod.TOOL_FUNCTIONS.update(original_tools)

        self.assertFalse(loop.turn_checkpoints_enabled)
        self.assertEqual(calls["create_backup"], 0)
        self.assertIsNone(loop._current_turn_checkpoint_path)

    def test_ensure_turn_checkpoint_runs_when_auto_backup_is_enabled(self):
        import houdinimind.agent.loop as loop_mod
        from houdinimind.agent.loop import AgentLoop

        tmp = _workspace_case_dir("checkpoint_auto_backup_enabled")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        loop = AgentLoop(
            {
                "data_dir": tmp,
                "ollama_url": "http://localhost:11434",
                "auto_backup": True,
            }
        )

        original_hou_available = loop_mod.HOU_AVAILABLE
        original_hou_call = loop._hou_call
        original_tools = dict(loop_mod.TOOL_FUNCTIONS)
        try:
            loop_mod.HOU_AVAILABLE = True
            loop_mod.TOOL_FUNCTIONS["create_backup"] = lambda: {
                "status": "ok",
                "data": {"backup_path": "/tmp/checkpoint_enabled.hip.bak"},
            }
            loop._hou_call = lambda fn, **kwargs: fn(**kwargs)
            loop._ensure_turn_checkpoint()
        finally:
            loop_mod.HOU_AVAILABLE = original_hou_available
            loop._hou_call = original_hou_call
            loop_mod.TOOL_FUNCTIONS.clear()
            loop_mod.TOOL_FUNCTIONS.update(original_tools)

        self.assertTrue(loop.turn_checkpoints_enabled)
        self.assertEqual(loop._current_turn_checkpoint_path, "/tmp/checkpoint_enabled.hip.bak")

    def test_inject_scene_context_compacts_large_snapshot(self):
        from houdinimind.agent.loop import AgentLoop

        tmp = _workspace_case_dir("inject_scene_context_compact")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        loop = AgentLoop(
            {
                "data_dir": tmp,
                "ollama_url": "http://localhost:11434",
                "live_scene_max_chars": 2400,
                "live_scene_max_nodes": 20,
                "live_scene_max_connections": 30,
            }
        )

        nodes = []
        connections = []
        for i in range(120):
            path = f"/obj/geo1/node_{i}"
            nodes.append(
                {
                    "path": path,
                    "type": "xform" if i else "box",
                    "category": "Sop",
                    "is_displayed": i == 119,
                    "is_render_flag": i == 119,
                    "errors": [],
                    "warnings": [],
                }
            )
            if i > 0:
                connections.append(
                    {
                        "from": f"/obj/geo1/node_{i - 1}",
                        "to": path,
                        "to_input": 0,
                    }
                )

        scene_json = json.dumps(
            {
                "hip_file": "/tmp/test_scene.hip",
                "current_frame": 1,
                "selected_nodes": ["/obj/geo1/node_119"],
                "nodes": nodes,
                "connections": connections,
                "error_count": 0,
            }
        )

        loop.inject_scene_context(scene_json)
        compact = json.loads(loop._live_scene_json)

        self.assertLessEqual(len(loop._live_scene_json), loop.live_scene_max_chars + 32)
        self.assertLessEqual(compact["node_count"], loop.live_scene_max_nodes)
        self.assertLessEqual(compact["connection_count"], loop.live_scene_max_connections)
        self.assertEqual(compact["selected_nodes"], ["/obj/geo1/node_119"])

    def test_extract_display_output_paths_filters_candidate_parents(self):
        from houdinimind.agent.loop import AgentLoop

        tmp = _workspace_case_dir("display_outputs")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        loop = AgentLoop({"data_dir": tmp, "ollama_url": "http://localhost:11434"})
        snapshot = {
            "nodes": [
                {"path": "/obj/table/OUT", "is_displayed": True, "is_render_flag": True},
                {"path": "/obj/table/merge_final", "is_displayed": False, "is_render_flag": False},
                {"path": "/obj/chair/OUT", "is_displayed": True, "is_render_flag": True},
            ]
        }

        outputs = loop._extract_display_output_paths(snapshot, ["/obj/table"])

        self.assertEqual(outputs, ["/obj/table/OUT"])

    def test_extract_display_output_paths_prefers_descendants_over_object_container(self):
        from houdinimind.agent.loop import AgentLoop

        tmp = _workspace_case_dir("display_outputs_descendants")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        loop = AgentLoop({"data_dir": tmp, "ollama_url": "http://localhost:11434"})
        snapshot = {
            "nodes": [
                {
                    "path": "/obj/BUS",
                    "category": "Object",
                    "is_displayed": True,
                    "is_render_flag": True,
                },
                {
                    "path": "/obj/BUS/OUT",
                    "category": "Sop",
                    "is_displayed": True,
                    "is_render_flag": True,
                },
                {
                    "path": "/obj/BUS/FINAL_MERGE",
                    "category": "Sop",
                    "is_displayed": False,
                    "is_render_flag": False,
                },
            ]
        }

        outputs = loop._extract_display_output_paths(snapshot, ["/obj/BUS"])

        self.assertEqual(outputs, ["/obj/BUS/OUT"])

    def test_analyze_network_view_combines_snapshot_and_image_prompt(self):
        import houdinimind.agent.loop as loop_mod
        from houdinimind.agent.loop import AgentLoop

        tmp = _workspace_case_dir("network_vision_prompt")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        loop = AgentLoop({"data_dir": tmp, "ollama_url": "http://localhost:11434"})
        snapshot = {
            "selected_nodes": ["/obj/table/OUT"],
            "nodes": [
                {
                    "path": "/obj/table/OUT",
                    "type": "null",
                    "is_displayed": True,
                    "is_render_flag": True,
                    "errors": [],
                    "warnings": [],
                    "inputs": [{"from_node": "/obj/table/merge_final"}],
                    "outputs": [],
                }
            ],
            "connections": [
                {"from": "/obj/table/merge_final", "to": "/obj/table/OUT", "to_input": 0}
            ],
            "error_count": 0,
        }
        captured = {}
        original_hou_available = loop_mod.HOU_AVAILABLE
        original_capture = loop._capture_debug_screenshot
        original_vision = loop.llm.chat_vision

        try:
            loop_mod.HOU_AVAILABLE = True
            loop._capture_debug_screenshot = lambda label, pane_type="viewport", node_path=None: (
                "ZmFrZQ=="
            )
            loop.llm.chat_vision = lambda prompt, image_b64=None, image_bytes=None: (
                captured.update(
                    {
                        "prompt": prompt,
                        "image_b64": image_b64,
                    }
                )
                or '{"verdict":"PASS","summary":"Looks organized","issues":[]}'
            )
            report = loop._analyze_network_view(
                "Inspect the table network", snapshot, parent_paths=["/obj/table"]
            )
        finally:
            loop_mod.HOU_AVAILABLE = original_hou_available
            loop._capture_debug_screenshot = original_capture
            loop.llm.chat_vision = original_vision

        self.assertEqual(report["verdict"], "PASS")
        self.assertEqual(captured["image_b64"], "ZmFrZQ==")
        self.assertIn("Structured network summary", captured["prompt"])
        self.assertIn("/obj/table/OUT", captured["prompt"])

    def test_inspect_network_view_returns_human_readable_report(self):
        from houdinimind.agent.loop import AgentLoop

        tmp = _workspace_case_dir("inspect_network_view")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        loop = AgentLoop({"data_dir": tmp, "ollama_url": "http://localhost:11434"})
        original_refresh = loop._refresh_live_scene_context
        original_snapshot = loop._capture_scene_snapshot
        original_observe = loop._run_observation_tool
        original_analyze = loop._analyze_network_view

        try:
            loop._refresh_live_scene_context = lambda depth=3: None
            loop._capture_scene_snapshot = lambda: {"selected_nodes": ["/obj/table/OUT"]}
            loop._run_observation_tool = lambda tool_name, args, stream_callback=None: {
                "status": "ok",
                "data": {
                    "nodes": [
                        {
                            "path": "/obj/table/merge_final",
                            "errors": ["missing input"],
                            "warnings": [],
                        }
                    ]
                },
            }
            loop._analyze_network_view = lambda *args, **kwargs: {
                "verdict": "FAIL",
                "summary": "I can see a loose branch near the final merge.",
                "issues": [
                    {"severity": "repair", "message": "The final merge still has a loose branch."}
                ],
            }
            result = loop.inspect_network_view()
        finally:
            loop._refresh_live_scene_context = original_refresh
            loop._capture_scene_snapshot = original_snapshot
            loop._run_observation_tool = original_observe
            loop._analyze_network_view = original_analyze

        self.assertIn("Network inspection complete.", result)
        self.assertIn("loose branch", result)
        self.assertIn("/obj/table/merge_final", result)

    def test_network_capture_failure_is_suppressed_after_first_attempt(self):
        from houdinimind.agent.loop import AgentLoop

        tmp = _workspace_case_dir("network_capture_guard")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        loop = AgentLoop({"data_dir": tmp, "ollama_url": "http://localhost:11434"})
        calls = {"count": 0}
        original_hou_call = loop._hou_call

        def fake_hou_call(fn, **kwargs):
            calls["count"] += 1
            return {"status": "error", "message": "capture failed", "data": None}

        try:
            loop._hou_call = fake_hou_call
            first = loop._capture_debug_screenshot("Network Audit", pane_type="network")
            second = loop._capture_debug_screenshot("Network Audit", pane_type="network")
        finally:
            loop._hou_call = original_hou_call

        self.assertIsNone(first)
        self.assertIsNone(second)
        self.assertEqual(calls["count"], 1)

    def test_capture_debug_screenshot_skips_houdini_call_when_vision_disabled(self):
        from houdinimind.agent.loop import AgentLoop

        tmp = _workspace_case_dir("debug_capture_vision_disabled")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        loop = AgentLoop({"data_dir": tmp, "ollama_url": "http://localhost:11434"})
        calls = {"count": 0}
        original_hou_call = loop._hou_call
        original_vision_enabled = loop.llm.vision_enabled

        def fake_hou_call(fn, **kwargs):
            calls["count"] += 1
            return {"status": "ok", "data": {"image_b64": "ZmFrZQ=="}}

        try:
            loop.llm.vision_enabled = False
            loop._hou_call = fake_hou_call
            captured = loop._capture_debug_screenshot("Before Viewport")
        finally:
            loop.llm.vision_enabled = original_vision_enabled
            loop._hou_call = original_hou_call

        self.assertIsNone(captured)
        self.assertEqual(calls["count"], 0)

    def test_capture_debug_screenshot_skips_houdini_call_when_vision_bypassed(self):
        from houdinimind.agent.loop import AgentLoop

        tmp = _workspace_case_dir("debug_capture_vision_bypassed")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        loop = AgentLoop({"data_dir": tmp, "ollama_url": "http://localhost:11434"})
        calls = {"count": 0}
        original_hou_call = loop._hou_call

        def fake_hou_call(fn, **kwargs):
            calls["count"] += 1
            return {"status": "ok", "data": {"image_b64": "ZmFrZQ=="}}

        try:
            loop._vision_bypass_active = True
            loop._hou_call = fake_hou_call
            captured = loop._capture_debug_screenshot("After Viewport")
        finally:
            loop._vision_bypass_active = False
            loop._hou_call = original_hou_call

        self.assertIsNone(captured)
        self.assertEqual(calls["count"], 0)

    def test_visual_self_check_capture_failure_does_not_trigger_repair(self):
        import houdinimind.agent.loop as loop_mod
        from houdinimind.agent.loop import AgentLoop

        tmp = _workspace_case_dir("visual_capture_failure_no_repair")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        loop = AgentLoop({"data_dir": tmp, "ollama_url": "http://localhost:11434"})
        original_hou_available = loop_mod.HOU_AVAILABLE
        original_vision = loop.llm.vision_enabled
        original_chat_vision = loop.llm.chat_vision

        try:
            loop_mod.HOU_AVAILABLE = True
            loop.llm.vision_enabled = True
            loop.llm.chat_vision = lambda **_kwargs: (
                "FAIL_CAPTURE\n- Screenshot shows chat UI text, not the viewport."
            )
            result = loop._perform_visual_self_check(
                "modify the current scene",
                "Scene was modified.",
                image_b64="ZmFrZQ==",
            )
        finally:
            loop_mod.HOU_AVAILABLE = original_hou_available
            loop.llm.vision_enabled = original_vision
            loop.llm.chat_vision = original_chat_vision

        self.assertTrue(result)
        self.assertIsNone(getattr(loop, "_last_visual_verdict", None))

    def test_hybrid_retriever_builds_bm25_index_from_kb_entries(self):
        from houdinimind.rag.retriever import HybridRetriever

        tmp = _workspace_case_dir("hybrid_retriever")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        kb_path = os.path.join(tmp, "knowledge_base.json")
        with open(kb_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "entries": [
                        {
                            "_id": 1,
                            "title": "Vellum Pillow Setup",
                            "category": "recipe",
                            "tags": ["vellum", "pillow"],
                            "content": "Use vellum constraints and cloth setup for pillows.",
                        },
                        {
                            "_id": 2,
                            "title": "Chair Modeling Basics",
                            "category": "workflow",
                            "tags": ["chair", "modeling"],
                            "content": "Start from a box and refine proportions.",
                        },
                    ]
                },
                f,
            )

        retriever = HybridRetriever(kb_path=kb_path, hybrid_weight=0.0)
        results = retriever.retrieve("build a vellum pillow", top_k=2, min_score=0.0)

        self.assertEqual(retriever._bm25.N, 2)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["title"], "Vellum Pillow Setup")

    def test_query_aware_shard_retriever_routes_vex_queries_to_vex_knowledge(self):
        from houdinimind.rag.retriever import QueryAwareShardRetriever

        tmp = _workspace_case_dir("query_routed_vex")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        kb_path = os.path.join(tmp, "knowledge_base.json")
        with open(kb_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "entries": [
                        {
                            "_id": "vex1",
                            "title": "VEX Function: noise",
                            "category": "vex",
                            "tags": ["vex", "noise", "wrangle"],
                            "content": "Function: noise\nContexts: surface, sop",
                            "_source": "houdini_vex_knowledge",
                        },
                        {
                            "_id": "py1",
                            "title": "Python HOM Example: Create Node",
                            "category": "workflow",
                            "tags": ["python", "hou", "example"],
                            "content": "Use hou.node('/obj').createNode('geo') to build geometry.",
                            "_source": "houdini_500_python_examples",
                        },
                    ]
                },
                f,
            )

        retriever = QueryAwareShardRetriever(
            kb_path=kb_path,
            hybrid_weight=0.0,
            max_shards_per_query=2,
        )

        self.assertEqual(retriever._loaded_shards, {})

        results = retriever.retrieve("write a vex wrangle noise example", top_k=2, min_score=0.0)

        self.assertEqual(results[0]["title"], "VEX Function: noise")
        self.assertIn("vex_reference", retriever.last_route_meta.get("selected_shards", []))
        self.assertNotIn(
            "python_examples", retriever.last_route_meta.get("selected_shards", [])[:1]
        )
        self.assertLessEqual(len(retriever._loaded_shards), 2)

    def test_query_aware_shard_retriever_routes_exact_vex_symbol_without_vex_keyword(self):
        from houdinimind.rag.retriever import QueryAwareShardRetriever

        tmp = _workspace_case_dir("query_routed_exact_vex_symbol")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        kb_path = os.path.join(tmp, "knowledge_base.json")
        with open(kb_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "entries": [
                        {
                            "_id": "pcopen",
                            "title": "VEX Function: pcopen",
                            "category": "vex",
                            "tags": ["vex", "function", "pcopen"],
                            "content": "Function: pcopen\nSignatures:\n- int pcopen(...)",
                            "_source": "vex_functions_db",
                            "_vex_symbol": "pcopen",
                        },
                        {
                            "_id": "workflow",
                            "title": "Point Cloud Workflow",
                            "category": "workflow",
                            "tags": ["point", "cloud", "workflow"],
                            "content": "Build points, scatter them, and cache the result.",
                        },
                    ]
                },
                f,
            )

        retriever = QueryAwareShardRetriever(
            kb_path=kb_path,
            hybrid_weight=0.0,
            max_shards_per_query=1,
        )
        results = retriever.retrieve(
            "Which arguments does pcopen take for radius and maxpoints?",
            top_k=1,
            min_score=0.0,
        )

        self.assertEqual(results[0]["title"], "VEX Function: pcopen")
        self.assertEqual(retriever.last_route_meta.get("selected_shards"), ["vex_reference"])

    def test_query_aware_shard_retriever_routes_exact_hou_symbol_to_python(self):
        from houdinimind.rag.retriever import QueryAwareShardRetriever

        tmp = _workspace_case_dir("query_routed_exact_hou_symbol")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        kb_path = os.path.join(tmp, "knowledge_base.json")
        with open(kb_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "entries": [
                        {
                            "_id": "hou-node-createnode",
                            "title": "Houdini Python HOM: hou.node.createnode",
                            "category": "python",
                            "tags": ["python", "hom", "hou.node.createnode", "createnode"],
                            "content": "Qualified Name: hou.node.createnode\nSignature: hou.node.createnode(node_type_name)",
                            "_source": "houdini_python_functions_json",
                            "_python_symbol": "hou.node.createnode",
                            "_python_aliases": ["hou.node.createnode", "createnode"],
                        },
                        {
                            "_id": "workflow",
                            "title": "Node Creation Workflow",
                            "category": "workflow",
                            "tags": ["node", "creation"],
                            "content": "Create nodes using Houdini tools.",
                        },
                    ]
                },
                f,
            )

        retriever = QueryAwareShardRetriever(
            kb_path=kb_path,
            hybrid_weight=0.0,
            max_shards_per_query=1,
        )
        results = retriever.retrieve(
            "What arguments does hou.Node.createNode take?",
            top_k=1,
            min_score=0.0,
        )

        self.assertEqual(results[0]["title"], "Houdini Python HOM: hou.node.createnode")
        self.assertEqual(retriever.last_route_meta.get("selected_shards"), ["python_examples"])

    def test_query_aware_shard_retriever_prefers_hda_and_python_for_asset_tooling_queries(self):
        from houdinimind.rag.retriever import QueryAwareShardRetriever

        tmp = _workspace_case_dir("query_routed_hda")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        kb_path = os.path.join(tmp, "knowledge_base.json")
        with open(kb_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "entries": [
                        {
                            "_id": "hda1",
                            "title": "HDA Python Example: Button Callback",
                            "category": "workflow",
                            "tags": ["hda", "python", "callback"],
                            "content": "Add a callback script to the digital asset button parameter.",
                            "_source": "houdini_500_hda_examples",
                        },
                        {
                            "_id": "py1",
                            "title": "Python HOM Example: Parameter Template Group",
                            "category": "workflow",
                            "tags": ["python", "hom", "parmtemplategroup"],
                            "content": "Use hou.ParmTemplateGroup to edit parameters.",
                            "_source": "houdini_500_python_examples",
                        },
                        {
                            "_id": "node1",
                            "title": "SOP Node: box",
                            "category": "nodes",
                            "tags": ["sop", "node", "box"],
                            "content": "Node Type: box\nNetwork Context: SOP",
                            "_source": "houdini_all_sops_knowledge",
                            "_node_context": "SOP",
                        },
                    ]
                },
                f,
            )

        retriever = QueryAwareShardRetriever(
            kb_path=kb_path,
            hybrid_weight=0.0,
            max_shards_per_query=3,
        )

        results = retriever.retrieve("create an hda python callback button", top_k=2, min_score=0.0)

        self.assertEqual(results[0]["title"], "HDA Python Example: Button Callback")
        selected = retriever.last_route_meta.get("selected_shards", [])
        self.assertIn("hda_examples", selected)
        self.assertIn("python_examples", selected)

    def test_create_rag_pipeline_uses_query_routed_retriever_by_default(self):
        from houdinimind.rag import create_rag_pipeline
        from houdinimind.rag.retriever import QueryAwareShardRetriever

        tmp = _workspace_case_dir("query_routed_pipeline")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        os.makedirs(os.path.join(tmp, "knowledge"), exist_ok=True)
        kb_path = os.path.join(tmp, "knowledge", "knowledge_base.generated.json")
        with open(kb_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "entries": [
                        {
                            "_id": 1,
                            "title": "VEX Function: fit",
                            "category": "vex",
                            "tags": ["vex", "fit"],
                            "content": "Function: fit\nContexts: vex",
                            "_source": "houdini_vex_knowledge",
                        }
                    ]
                },
                f,
            )

        injector = create_rag_pipeline(
            tmp,
            {
                "data_dir": tmp,
                "rag_hybrid_search": False,
            },
        )

        self.assertIsInstance(injector.retriever, QueryAwareShardRetriever)
        self.assertEqual(injector.retriever._loaded_shards, {})

    def test_scene_snapshot_is_cached_until_scene_changes(self):
        import houdinimind.agent.loop as loop_mod
        import houdinimind.bridge.scene_reader as scene_reader_mod
        from houdinimind.agent.loop import AgentLoop

        tmp = _workspace_case_dir("snapshot_cache")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        loop = AgentLoop({"data_dir": tmp, "ollama_url": "http://localhost:11434"})
        calls = {"count": 0}

        class _FakeSceneReader:
            def __init__(self, *args, **kwargs):
                pass

            def snapshot(self, root_path):
                calls["count"] += 1
                return {"nodes": [{"path": f"/obj/node{calls['count']}"}], "root": root_path}

        original_hou_available = loop_mod.HOU_AVAILABLE
        original_scene_reader = scene_reader_mod.SceneReader
        original_hou_call = loop._hou_call

        try:
            loop_mod.HOU_AVAILABLE = True
            scene_reader_mod.SceneReader = _FakeSceneReader
            loop._hou_call = lambda fn, **kwargs: fn(**kwargs)

            first = loop._capture_scene_snapshot()
            second = loop._capture_scene_snapshot()
            loop._mark_scene_dirty("create_node")
            third = loop._capture_scene_snapshot()
        finally:
            loop_mod.HOU_AVAILABLE = original_hou_available
            scene_reader_mod.SceneReader = original_scene_reader
            loop._hou_call = original_hou_call

        self.assertEqual(calls["count"], 2)
        self.assertIs(first, second)
        self.assertEqual(first["nodes"][0]["path"], "/obj/node1")
        self.assertEqual(third["nodes"][0]["path"], "/obj/node2")

    def test_scene_snapshot_returns_none_on_timeout(self):
        import houdinimind.agent.loop as loop_mod
        from houdinimind.agent.loop import AgentLoop

        tmp = _workspace_case_dir("snapshot_timeout")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        loop = AgentLoop({"data_dir": tmp, "ollama_url": "http://localhost:11434"})

        original_hou_available = loop_mod.HOU_AVAILABLE
        original_execute_with_timeout = loop._execute_with_timeout

        try:
            loop_mod.HOU_AVAILABLE = True
            loop._execute_with_timeout = lambda func, timeout_s, **kwargs: (None, "timed out")
            snapshot = loop._capture_scene_snapshot()
        finally:
            loop_mod.HOU_AVAILABLE = original_hou_available
            loop._execute_with_timeout = original_execute_with_timeout

        self.assertIsNone(snapshot)

    def test_scene_snapshot_bypasses_timeout_thread_when_main_thread_dispatch_exists(self):
        import houdinimind.agent.loop as loop_mod
        import houdinimind.bridge.scene_reader as scene_reader_mod
        from houdinimind.agent.loop import AgentLoop

        tmp = _workspace_case_dir("snapshot_direct_dispatch")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        loop = AgentLoop({"data_dir": tmp, "ollama_url": "http://localhost:11434"})

        class _FakeSceneReader:
            def __init__(self, *args, **kwargs):
                pass

            def snapshot(self, root_path):
                return {
                    "nodes": [{"path": "/obj/direct"}],
                    "connections": [],
                    "root": root_path,
                }

        original_hou_available = loop_mod.HOU_AVAILABLE
        original_scene_reader = scene_reader_mod.SceneReader
        original_hou_call = loop._hou_call
        original_has_dispatch = loop._has_houdini_main_thread_dispatch
        original_execute_with_timeout = loop._execute_with_timeout

        try:
            loop_mod.HOU_AVAILABLE = True
            scene_reader_mod.SceneReader = _FakeSceneReader
            loop._hou_call = lambda fn, **kwargs: fn(**kwargs)
            loop._has_houdini_main_thread_dispatch = lambda: True

            def _boom(*args, **kwargs):
                raise AssertionError("timeout thread should not be used")

            loop._execute_with_timeout = _boom
            snapshot = loop._capture_scene_snapshot()
        finally:
            loop_mod.HOU_AVAILABLE = original_hou_available
            scene_reader_mod.SceneReader = original_scene_reader
            loop._hou_call = original_hou_call
            loop._has_houdini_main_thread_dispatch = original_has_dispatch
            loop._execute_with_timeout = original_execute_with_timeout

        self.assertEqual(snapshot["nodes"][0]["path"], "/obj/direct")

    def test_capture_pane_reuses_cached_result_until_scene_changes(self):
        from houdinimind.agent.loop import AgentLoop

        tmp = _workspace_case_dir("capture_cache")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        loop = AgentLoop({"data_dir": tmp, "ollama_url": "http://localhost:11434"})
        calls = {"hou": 0, "vision": 0}
        original_hou_call = loop._hou_call
        original_vision = loop.llm.chat_vision

        def fake_hou_call(fn, **kwargs):
            calls["hou"] += 1
            return {
                "status": "ok",
                "message": "Captured screenshot.",
                "data": {
                    "image_b64": "ZmFrZQ==",
                    "pane_type": kwargs.get("pane_type", "viewport"),
                },
            }

        def fake_chat_vision(prompt, image_b64=None, image_bytes=None):
            calls["vision"] += 1
            return "Looks correct."

        try:
            loop._hou_call = fake_hou_call
            loop.llm.chat_vision = fake_chat_vision

            first = loop._execute_tool("capture_pane", {"pane_type": "viewport"}, dry_run=False)
            second = loop._execute_tool("capture_pane", {"pane_type": "viewport"}, dry_run=False)
            loop._mark_scene_dirty("create_node")
            third = loop._execute_tool("capture_pane", {"pane_type": "viewport"}, dry_run=False)
        finally:
            loop._hou_call = original_hou_call
            loop.llm.chat_vision = original_vision

        self.assertEqual(calls["hou"], 2)
        self.assertEqual(calls["vision"], 2)
        self.assertEqual(first.get("status"), "ok")
        self.assertTrue(second.get("_meta", {}).get("cached"))
        self.assertEqual(third.get("status"), "ok")

    def test_capture_debug_screenshot_distinguishes_focus_node_and_force_refresh(self):
        from houdinimind.agent.loop import AgentLoop

        tmp = _workspace_case_dir("debug_capture_cache")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        loop = AgentLoop({"data_dir": tmp, "ollama_url": "http://localhost:11434"})
        calls = []
        original_hou_call = loop._hou_call

        def fake_hou_call(fn, **kwargs):
            calls.append(kwargs.get("node_path"))
            return {
                "status": "ok",
                "message": "Captured screenshot.",
                "data": {"image_b64": f"img{len(calls)}"},
            }

        try:
            loop._hou_call = fake_hou_call
            first = loop._capture_debug_screenshot(
                "Network A",
                pane_type="network",
                node_path="/obj/geo1/A",
            )
            second = loop._capture_debug_screenshot(
                "Network B",
                pane_type="network",
                node_path="/obj/geo1/B",
            )
            third = loop._capture_debug_screenshot(
                "Network B Cached",
                pane_type="network",
                node_path="/obj/geo1/B",
            )
            fourth = loop._capture_debug_screenshot(
                "Network B Fresh",
                pane_type="network",
                node_path="/obj/geo1/B",
                force_refresh=True,
            )
        finally:
            loop._hou_call = original_hou_call

        self.assertEqual(first, "img1")
        self.assertEqual(second, "img2")
        self.assertEqual(third, "img2")
        self.assertEqual(fourth, "img3")
        self.assertEqual(calls, ["/obj/geo1/A", "/obj/geo1/B", "/obj/geo1/B"])

    def test_async_job_manager_tracks_progress_and_checkpoints(self):
        from houdinimind.agent.async_jobs import AsyncJobManager

        manager = AsyncJobManager()
        events = []
        done = {"result": ""}

        job_id = manager.submit(
            kind="chat",
            runner=lambda progress_cb, status_cb: (
                status_cb({"kind": "checkpoint", "path": "/tmp/checkpoint.hip"}),
                progress_cb("\x00AGENT_PROGRESS\x00Planning the build."),
                "done",
            )[-1],
            stream_callback=events.append,
            done_callback=lambda result: done.__setitem__("result", result),
        )

        deadline = time.time() + 2.0
        snapshot = manager.get(job_id)
        while snapshot and snapshot.get("status") != "completed" and time.time() < deadline:
            time.sleep(0.02)
            snapshot = manager.get(job_id)

        self.assertEqual(done["result"], "done")
        self.assertEqual(snapshot["status"], "completed")
        self.assertEqual(snapshot["checkpoints"], ["/tmp/checkpoint.hip"])
        self.assertEqual(snapshot["latest_substate"], "Planning the build.")
        self.assertTrue(events)

    def test_replay_eval_summarizes_debug_session_metrics(self):
        from houdinimind.agent.replay_eval import run_replay_eval, summarize_replay_session

        root = _workspace_case_dir("replay_eval")
        session_dir = os.path.join(root, "20260409_123000")
        os.makedirs(session_dir, exist_ok=True)
        jsonl_path = os.path.join(session_dir, "session.jsonl")
        with open(jsonl_path, "w", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "event": "turn_start",
                        "turn_index": 1,
                        "user_message": "Create a chair",
                    }
                )
                + "\n"
            )
            handle.write(
                json.dumps(
                    {
                        "event": "llm_call",
                        "turn_index": 1,
                        "elapsed_ms": 1200,
                    }
                )
                + "\n"
            )
            handle.write(
                json.dumps(
                    {
                        "event": "tool",
                        "turn_index": 1,
                        "tool": "create_node",
                        "status": "ok",
                        "duration_ms": 40,
                    }
                )
                + "\n"
            )
            handle.write(
                json.dumps(
                    {
                        "event": "system_note",
                        "turn_index": 1,
                        "content": "[VERIFICATION] PASS\nOutputs checked: /obj/chair_geo/OUT",
                    }
                )
                + "\n"
            )
            handle.write(
                json.dumps(
                    {
                        "event": "system_note",
                        "turn_index": 1,
                        "content": "[SEMANTIC SCORE] PASS\nOverall: 0.84 / Threshold: 0.72",
                    }
                )
                + "\n"
            )
            handle.write(
                json.dumps(
                    {
                        "event": "response",
                        "turn_index": 1,
                        "content": "Build completed successfully.",
                    }
                )
                + "\n"
            )

        session_summary = summarize_replay_session(session_dir)
        summary = run_replay_eval(root)

        self.assertEqual(session_summary["turn_count"], 1)
        self.assertEqual(session_summary["verification_passes"], 1)
        self.assertEqual(session_summary["semantic_passes"], 1)
        self.assertEqual(summary["session_count"], 1)
        self.assertEqual(summary["totals"]["tool_call_count"], 1)

    def test_semantic_scoring_aggregates_multi_view_reports(self):
        from houdinimind.agent.semantic_scoring import (
            aggregate_view_scores,
            format_scorecard,
            parse_view_score,
        )

        front = parse_view_score(
            json.dumps(
                {
                    "scores": {
                        "identity": 0.8,
                        "completeness": 0.7,
                        "proportion": 0.75,
                        "support": 0.72,
                        "editability": 0.9,
                    },
                    "overall": 0.78,
                    "verdict": "PASS",
                    "summary": "Front view reads clearly.",
                }
            ),
            view="front",
        )
        top = parse_view_score(
            json.dumps(
                {
                    "scores": {
                        "identity": 0.35,
                        "completeness": 0.45,
                        "proportion": 0.5,
                        "support": 0.4,
                        "editability": 0.7,
                    },
                    "overall": 0.46,
                    "verdict": "FAIL",
                    "summary": "Top view still feels boxy.",
                    "issues": ["Silhouette is too generic."],
                }
            ),
            view="top",
        )

        scorecard = aggregate_view_scores([front, top], threshold=0.72)
        rendered = format_scorecard(scorecard)

        self.assertLess(scorecard.overall, 0.72)
        self.assertEqual(scorecard.verdict, "FAIL")
        self.assertIn("top: Top view still feels boxy.", scorecard.issues)
        self.assertIn("[SEMANTIC SCORE] FAIL", rendered)

    def test_kb_builder_loads_external_node_chain_training_data(self):
        from houdinimind.rag import kb_builder as kb_mod

        tmp = _workspace_case_dir("node_chain_training")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        chain_path = os.path.join(tmp, "houdini_node_chains.json")
        with open(chain_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "metadata": {
                        "terminology": {
                            "node": "A single Houdini operator.",
                        }
                    },
                    "chains": [
                        {
                            "id": "sop_900",
                            "title": "Test chain",
                            "context": "SOP",
                            "goal": "Create a box and transform it.",
                            "tags": ["test", "box"],
                            "nodes": [
                                {
                                    "name": "box1",
                                    "type": "box",
                                    "parms": {"size": [1, 1, 1]},
                                },
                                {
                                    "name": "xform1",
                                    "type": "xform",
                                    "parms": {"t": [0, 1, 0]},
                                    "display_flag": True,
                                },
                            ],
                            "connections": [
                                {
                                    "from": "box1",
                                    "from_output": 0,
                                    "to": "xform1",
                                    "to_input": 0,
                                }
                            ],
                            "output_description": "A moved box.",
                        }
                    ],
                },
                f,
            )

        previous = os.environ.get("HOUDINIMIND_NODE_CHAINS_PATH")
        os.environ["HOUDINIMIND_NODE_CHAINS_PATH"] = chain_path
        try:
            entries = kb_mod._load_node_chain_training_data()
        finally:
            if previous is None:
                os.environ.pop("HOUDINIMIND_NODE_CHAINS_PATH", None)
            else:
                os.environ["HOUDINIMIND_NODE_CHAINS_PATH"] = previous

        titles = [entry.get("title", "") for entry in entries]
        self.assertIn("Houdini Node Chain Terminology", titles)
        chain_entry = next(entry for entry in entries if entry.get("_chain_id") == "sop_900")
        self.assertEqual(chain_entry["category"], "workflow")
        self.assertIn("box", chain_entry["tags"])
        self.assertIn("Nodes:", chain_entry["content"])
        self.assertIn("box1 (box)", chain_entry["content"])
        self.assertIn("box1[0] -> xform1[0]", chain_entry["content"])

    def test_kb_builder_loads_high_fidelity_asset_dataset(self):
        from houdinimind.rag import kb_builder as kb_mod

        tmp = _workspace_case_dir("high_fidelity_dataset")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        dataset_path = os.path.join(tmp, "dataset_high_fidelity.json")
        with open(dataset_path, "w", encoding="utf-8") as f:
            json.dump(
                [
                    {
                        "asset_name": "double_decker_bus",
                        "approach": "Build a long bus body, cut window bands, then copy wheels.",
                        "network": {
                            "context": "/obj/double_decker_bus",
                            "nodes": [
                                {
                                    "name": "body",
                                    "type": "box",
                                    "parameters": {"sizex": 8.0, "sizey": 2.8, "sizez": 2.4},
                                    "inputs": [],
                                    "flags": {"display": False},
                                },
                                {
                                    "name": "wheel_copy",
                                    "type": "copytopoints::2.0",
                                    "parameters": {},
                                    "inputs": [{"index": 0, "source": "wheel_geo"}],
                                    "flags": {"display": True},
                                },
                            ],
                        },
                    }
                ],
                f,
            )

        previous = os.environ.get("HOUDINIMIND_HIGH_FIDELITY_PATH")
        original_data = kb_mod.DATA_DIR
        os.environ["HOUDINIMIND_HIGH_FIDELITY_PATH"] = dataset_path
        kb_mod.DATA_DIR = tmp
        try:
            entries = kb_mod._load_high_fidelity_knowledge()
        finally:
            kb_mod.DATA_DIR = original_data
            if previous is None:
                os.environ.pop("HOUDINIMIND_HIGH_FIDELITY_PATH", None)
            else:
                os.environ["HOUDINIMIND_HIGH_FIDELITY_PATH"] = previous

        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry["category"], "workflow")
        self.assertEqual(entry["_asset_name"], "double_decker_bus")
        self.assertIn("double", entry["tags"])
        self.assertIn("bus", entry["tags"])
        self.assertIn("Approach:", entry["content"])
        self.assertIn("wheel_copy (copytopoints::2.0)", entry["content"])
        self.assertIn("Visible output nodes: wheel_copy", entry["content"])

    def test_kb_builder_loads_vex_function_database(self):
        import sqlite3

        from houdinimind.rag import kb_builder as kb_mod

        tmp = _workspace_case_dir("vex_function_db")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        db_path = os.path.join(tmp, "vex_functions.db")
        conn = sqlite3.connect(db_path)
        conn.executescript(
            """
            CREATE TABLE functions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                summary TEXT,
                description TEXT,
                category TEXT,
                examples TEXT,
                related_functions TEXT
            );
            CREATE TABLE signatures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                function_name TEXT NOT NULL,
                signature TEXT NOT NULL,
                description TEXT
            );
            CREATE TABLE categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                function_count INTEGER
            );
            """
        )
        conn.execute(
            "INSERT INTO functions "
            "(name, summary, description, category, examples, related_functions) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                "pcopen",
                "Returns a handle to a point cloud file.",
                "Returns a handle to a point cloud file.",
                "Point Clouds and 3D Images",
                '["int handle = pcopen(0, \\"P\\", @P, 1.0, 16);"]',
                '["pciterate", "pcimport"]',
            ),
        )
        conn.execute(
            "INSERT INTO signatures (function_name, signature, description) VALUES (?, ?, ?)",
            (
                "pcopen",
                "intpcopen(intopinput,stringPchannel,vectorP,floatradius,intmaxpoints)",
                "",
            ),
        )
        conn.commit()
        conn.close()

        previous = os.environ.get("HOUDINIMIND_VEX_FUNCTIONS_DB")
        os.environ["HOUDINIMIND_VEX_FUNCTIONS_DB"] = db_path
        try:
            entries = kb_mod._load_vex_function_db_knowledge(tmp)
        finally:
            if previous is None:
                os.environ.pop("HOUDINIMIND_VEX_FUNCTIONS_DB", None)
            else:
                os.environ["HOUDINIMIND_VEX_FUNCTIONS_DB"] = previous

        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry["title"], "VEX Function: pcopen")
        self.assertEqual(entry["category"], "vex")
        self.assertEqual(entry["_source"], "vex_functions_db")
        self.assertEqual(entry["_vex_symbol"], "pcopen")
        self.assertIn("Point Clouds and 3D Images", entry["content"])
        self.assertIn(
            "int pcopen(int opinput, string Pchannel, vector P, float radius, int maxpoints)",
            entry["content"],
        )
        self.assertIn("pciterate", entry["content"])

    def test_kb_builder_loads_houdini_python_function_json(self):
        from houdinimind.rag import kb_builder as kb_mod

        tmp = _workspace_case_dir("houdini_python_function_json")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        json_path = os.path.join(tmp, "houdini_python_functions.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "metadata": {"source": "test"},
                    "functions": [
                        {
                            "name": "hou.node.createnode",
                            "namespace": "hou.node",
                            "type": "method",
                            "signature": "createnode(node_type_name, node_name=none)  -> hou.node",
                            "description": "Create a new node of type node_type_name as a child.",
                        }
                    ],
                },
                f,
            )

        previous = os.environ.get("HOUDINIMIND_HOUDINI_PYTHON_JSON")
        os.environ["HOUDINIMIND_HOUDINI_PYTHON_JSON"] = json_path
        try:
            entries = kb_mod._load_houdini_python_function_knowledge(tmp)
        finally:
            if previous is None:
                os.environ.pop("HOUDINIMIND_HOUDINI_PYTHON_JSON", None)
            else:
                os.environ["HOUDINIMIND_HOUDINI_PYTHON_JSON"] = previous

        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry["title"], "Houdini Python HOM: hou.node.createnode")
        self.assertEqual(entry["category"], "python")
        self.assertEqual(entry["_source"], "houdini_python_functions_json")
        self.assertIn("hou.node.createnode", entry["_python_aliases"])
        self.assertIn("Signature: hou.node.createnode", entry["content"])

    def test_rag_prefers_generated_kb_when_newer(self):
        from houdinimind.rag import _knowledge_base_path

        tmp = _workspace_case_dir("kb_generated_preference")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        knowledge_dir = os.path.join(tmp, "knowledge")
        os.makedirs(knowledge_dir, exist_ok=True)
        primary = os.path.join(knowledge_dir, "knowledge_base.json")
        generated = os.path.join(knowledge_dir, "knowledge_base.generated.json")

        with open(primary, "w", encoding="utf-8") as f:
            json.dump({"entries": []}, f)
        with open(generated, "w", encoding="utf-8") as f:
            json.dump({"entries": [{"title": "generated"}]}, f)

        os.utime(primary, (1, 1))
        os.utime(generated, None)

        self.assertEqual(_knowledge_base_path(tmp), generated)

    def test_create_rag_pipeline_merges_runtime_node_chain_entries(self):
        from houdinimind.rag import create_rag_pipeline

        tmp = _workspace_case_dir("rag_runtime_node_chains")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        knowledge_dir = os.path.join(tmp, "knowledge")
        os.makedirs(knowledge_dir, exist_ok=True)
        with open(os.path.join(knowledge_dir, "knowledge_base.json"), "w", encoding="utf-8") as f:
            json.dump({"entries": []}, f)

        chain_path = os.path.join(tmp, "houdini_node_chains.json")
        with open(chain_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "chains": [
                        {
                            "id": "lop_001",
                            "title": "Runtime chain",
                            "context": "LOP",
                            "goal": "Create a simple Solaris chain.",
                            "tags": ["usd", "solaris"],
                            "nodes": [
                                {"name": "stage1", "type": "stage", "parms": {}},
                            ],
                            "connections": [],
                            "output_description": "A Solaris stage.",
                        }
                    ]
                },
                f,
            )

        previous = os.environ.get("HOUDINIMIND_NODE_CHAINS_PATH")
        os.environ["HOUDINIMIND_NODE_CHAINS_PATH"] = chain_path
        try:
            injector = create_rag_pipeline(tmp, {"rag_hybrid_search": False})
        finally:
            if previous is None:
                os.environ.pop("HOUDINIMIND_NODE_CHAINS_PATH", None)
            else:
                os.environ["HOUDINIMIND_NODE_CHAINS_PATH"] = previous

        titles = [entry.get("title") for entry in injector.retriever._entries]
        self.assertIn("Node Chain: Runtime chain", titles)

    def test_create_rag_pipeline_merges_runtime_high_fidelity_entries(self):
        from houdinimind.rag import create_rag_pipeline

        tmp = _workspace_case_dir("rag_runtime_high_fidelity")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        knowledge_dir = os.path.join(tmp, "knowledge")
        os.makedirs(knowledge_dir, exist_ok=True)
        with open(os.path.join(knowledge_dir, "knowledge_base.json"), "w", encoding="utf-8") as f:
            json.dump({"entries": []}, f)

        dataset_path = os.path.join(tmp, "dataset_high_fidelity.json")
        with open(dataset_path, "w", encoding="utf-8") as f:
            json.dump(
                [
                    {
                        "asset_name": "gothic_arch",
                        "approach": "Boolean a tube out of a wall for an arched opening.",
                        "network": {
                            "context": "/obj/gothic_arch_window",
                            "nodes": [
                                {
                                    "name": "wall",
                                    "type": "box",
                                    "parameters": {},
                                    "inputs": [],
                                    "flags": {},
                                },
                                {
                                    "name": "carve",
                                    "type": "boolean::2.0",
                                    "parameters": {"booleanop": 1},
                                    "inputs": [{"index": 0, "source": "wall"}],
                                    "flags": {"display": True},
                                },
                            ],
                        },
                    }
                ],
                f,
            )

        previous = os.environ.get("HOUDINIMIND_HIGH_FIDELITY_PATH")
        os.environ["HOUDINIMIND_HIGH_FIDELITY_PATH"] = dataset_path
        try:
            injector = create_rag_pipeline(tmp, {"rag_hybrid_search": False})
        finally:
            if previous is None:
                os.environ.pop("HOUDINIMIND_HIGH_FIDELITY_PATH", None)
            else:
                os.environ["HOUDINIMIND_HIGH_FIDELITY_PATH"] = previous

        titles = [entry.get("title") for entry in injector.retriever._entries]
        self.assertIn("High-Fidelity Asset: Gothic Arch", titles)
        self.assertEqual(titles.count("High-Fidelity Asset: Gothic Arch"), 1)

    def test_create_rag_pipeline_merges_runtime_vex_function_database(self):
        import sqlite3

        from houdinimind.rag import create_rag_pipeline

        tmp = _workspace_case_dir("rag_runtime_vex_db")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        knowledge_dir = os.path.join(tmp, "knowledge")
        os.makedirs(knowledge_dir, exist_ok=True)
        with open(os.path.join(knowledge_dir, "knowledge_base.json"), "w", encoding="utf-8") as f:
            json.dump({"entries": []}, f)

        db_path = os.path.join(tmp, "vex_functions.db")
        conn = sqlite3.connect(db_path)
        conn.executescript(
            """
            CREATE TABLE functions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                summary TEXT,
                description TEXT,
                category TEXT,
                examples TEXT,
                related_functions TEXT
            );
            CREATE TABLE signatures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                function_name TEXT NOT NULL,
                signature TEXT NOT NULL,
                description TEXT
            );
            CREATE TABLE categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                function_count INTEGER
            );
            """
        )
        conn.execute(
            "INSERT INTO functions "
            "(name, summary, description, category, examples, related_functions) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("chramp", "Evaluates a ramp parameter.", "", "Nodes", "[]", "[]"),
        )
        conn.execute(
            "INSERT INTO signatures (function_name, signature, description) VALUES (?, ?, ?)",
            ("chramp", "floatchramp(stringchannel,floatramppos)", ""),
        )
        conn.commit()
        conn.close()

        previous = os.environ.get("HOUDINIMIND_VEX_FUNCTIONS_DB")
        os.environ["HOUDINIMIND_VEX_FUNCTIONS_DB"] = db_path
        try:
            injector = create_rag_pipeline(tmp, {"rag_hybrid_search": False})
        finally:
            if previous is None:
                os.environ.pop("HOUDINIMIND_VEX_FUNCTIONS_DB", None)
            else:
                os.environ["HOUDINIMIND_VEX_FUNCTIONS_DB"] = previous

        results = injector.retriever.retrieve(
            "How should I call chramp for a float ramp parameter?",
            top_k=1,
            min_score=0.0,
        )

        self.assertEqual(results[0]["title"], "VEX Function: chramp")
        self.assertIn("vex_reference", injector.retriever.last_route_meta["selected_shards"])

    def test_create_rag_pipeline_merges_runtime_houdini_python_json(self):
        from houdinimind.rag import create_rag_pipeline

        tmp = _workspace_case_dir("rag_runtime_houdini_python_json")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        knowledge_dir = os.path.join(tmp, "knowledge")
        os.makedirs(knowledge_dir, exist_ok=True)
        with open(os.path.join(knowledge_dir, "knowledge_base.json"), "w", encoding="utf-8") as f:
            json.dump({"entries": []}, f)

        json_path = os.path.join(tmp, "houdini_python_functions.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "functions": [
                        {
                            "name": "hou.node.setparmtemplategroup",
                            "namespace": "hou.node",
                            "type": "method",
                            "signature": "setparmtemplategroup(parm_template_group)",
                            "description": "Change the spare parameters for this node.",
                        }
                    ]
                },
                f,
            )

        previous = os.environ.get("HOUDINIMIND_HOUDINI_PYTHON_JSON")
        os.environ["HOUDINIMIND_HOUDINI_PYTHON_JSON"] = json_path
        try:
            injector = create_rag_pipeline(tmp, {"rag_hybrid_search": False})
        finally:
            if previous is None:
                os.environ.pop("HOUDINIMIND_HOUDINI_PYTHON_JSON", None)
            else:
                os.environ["HOUDINIMIND_HOUDINI_PYTHON_JSON"] = previous

        results = injector.retriever.retrieve(
            "How do I use hou.Node.setParmTemplateGroup to add spare parameters?",
            top_k=1,
            min_score=0.0,
        )

        self.assertEqual(results[0]["title"], "Houdini Python HOM: hou.node.setparmtemplategroup")
        self.assertIn("python_examples", injector.retriever.last_route_meta["selected_shards"])

    def test_general_json_loader_transforms_examples_and_troubleshooting(self):
        from houdinimind.rag import kb_builder as kb_mod

        tmp = _workspace_case_dir("general_json_examples")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        knowledge_dir = os.path.join(tmp, "knowledge")
        os.makedirs(knowledge_dir, exist_ok=True)

        with open(
            os.path.join(knowledge_dir, "houdini_500_python_examples.json"), "w", encoding="utf-8"
        ) as f:
            json.dump(
                {
                    "verified_examples": [
                        {
                            "id": 7,
                            "name": "Create Box",
                            "category": "Nodes",
                            "code": "geo = hou.node('/obj').createNode('geo')",
                            "explanation": "Creates a geometry container.",
                        }
                    ]
                },
                f,
            )

        with open(
            os.path.join(knowledge_dir, "houdini_100_vex_examples.json"), "w", encoding="utf-8"
        ) as f:
            json.dump(
                {
                    "verified_examples": [
                        {
                            "id": 8,
                            "name": "Lift Points",
                            "category": "Point",
                            "code": "@P.y += 1.0;",
                            "explanation": "Offsets points upward.",
                        }
                    ]
                },
                f,
            )

        with open(
            os.path.join(knowledge_dir, "houdini_troubleshooting_knowledge.json"),
            "w",
            encoding="utf-8",
        ) as f:
            json.dump(
                {
                    "troubleshooting_database": [
                        {
                            "id": 3,
                            "context": "VEX",
                            "error": "Call to undefined function 'fit'",
                            "fix": "Use a valid VEX function for the active context.",
                        }
                    ]
                },
                f,
            )

        original_data = kb_mod.DATA_DIR
        kb_mod.DATA_DIR = tmp
        try:
            entries = kb_mod._load_general_json_knowledge()
        finally:
            kb_mod.DATA_DIR = original_data

        by_title = {entry["title"]: entry for entry in entries}
        self.assertIn("Python HOM Example: Create Box", by_title)
        self.assertEqual(by_title["Python HOM Example: Create Box"]["category"], "workflow")
        self.assertIn("Code:", by_title["Python HOM Example: Create Box"]["content"])

        self.assertIn("VEX Example: Lift Points", by_title)
        self.assertEqual(by_title["VEX Example: Lift Points"]["category"], "vex")
        self.assertIn("@P.y += 1.0;", by_title["VEX Example: Lift Points"]["content"])

        error_title = "Troubleshooting: Call to undefined function 'fit'"
        self.assertIn(error_title, by_title)
        self.assertEqual(by_title[error_title]["category"], "errors")
        self.assertIn("Fix: Use a valid VEX function", by_title[error_title]["content"])

    def test_general_json_loader_transforms_reference_dictionaries(self):
        from houdinimind.rag import kb_builder as kb_mod

        tmp = _workspace_case_dir("general_json_reference_maps")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        knowledge_dir = os.path.join(tmp, "knowledge")
        os.makedirs(knowledge_dir, exist_ok=True)

        with open(
            os.path.join(knowledge_dir, "houdini_all_sops_knowledge.json"), "w", encoding="utf-8"
        ) as f:
            json.dump(
                {
                    "sops": {
                        "attribwrangle": {
                            "description": "Runs VEX over geometry.",
                            "inputs": ["input1"],
                            "outputs": ["output1"],
                            "parameters": {
                                "snippet": {
                                    "description": "Inline VEX code",
                                    "default": "",
                                    "type": "String",
                                }
                            },
                        }
                    }
                },
                f,
            )

        with open(
            os.path.join(knowledge_dir, "houdini_vex_knowledge.json"), "w", encoding="utf-8"
        ) as f:
            json.dump(
                {
                    "Vex_Functions": {
                        "snoise": {
                            "contexts": ["sop", "cvex"],
                            "signatures": ["float snoise(vector pos)"],
                        }
                    },
                    "Standard_Attributes": {
                        "P": {
                            "type": "vector",
                            "description": "Point position",
                        }
                    },
                },
                f,
            )

        with open(
            os.path.join(knowledge_dir, "houdini_hscript_vars_knowledge.json"),
            "w",
            encoding="utf-8",
        ) as f:
            json.dump(
                {
                    "Expressions": {"bbox": "Returns the bounding box value for an object."},
                    "Variables": {"HIP": "Path to the current hip file."},
                },
                f,
            )

        with open(
            os.path.join(knowledge_dir, "houdini_intrinsics_knowledge.json"), "w", encoding="utf-8"
        ) as f:
            json.dump(
                {
                    "Definitions": {"measuredarea": "Surface area in square units."},
                    "Primitive_Types": {"Polygon": "Standard polygon primitive."},
                    "Detail_Intrinsics": {"pointcount": "Total point count on the geometry."},
                },
                f,
            )

        original_data = kb_mod.DATA_DIR
        kb_mod.DATA_DIR = tmp
        try:
            entries = kb_mod._load_general_json_knowledge()
        finally:
            kb_mod.DATA_DIR = original_data

        by_title = {entry["title"]: entry for entry in entries}
        self.assertIn("SOP Node: attribwrangle", by_title)
        self.assertEqual(by_title["SOP Node: attribwrangle"]["category"], "nodes")
        self.assertIn("Parameters:", by_title["SOP Node: attribwrangle"]["content"])

        self.assertIn("VEX Function: snoise", by_title)
        self.assertEqual(by_title["VEX Function: snoise"]["category"], "vex")
        self.assertIn("float snoise(vector pos)", by_title["VEX Function: snoise"]["content"])

        self.assertIn("VEX Attribute: P", by_title)
        self.assertEqual(by_title["VEX Attribute: P"]["category"], "vex")

        self.assertIn("HScript Expression: bbox", by_title)
        self.assertIn("HScript Variable: HIP", by_title)

        self.assertIn("Intrinsic Definition: measuredarea", by_title)
        self.assertIn("Primitive Type: Polygon", by_title)
        self.assertIn("Detail Intrinsic: pointcount", by_title)

    def test_node_chain_loader_prefers_repo_root_and_dedupes_chain_ids(self):
        from houdinimind.rag import kb_builder as kb_mod

        tmp = _workspace_case_dir("node_chain_dedupe")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        root_dir = os.path.join(tmp, "repo")
        data_dir = os.path.join(root_dir, "data")
        os.makedirs(os.path.join(data_dir, "knowledge"), exist_ok=True)
        parent_dir = os.path.dirname(root_dir)
        os.makedirs(root_dir, exist_ok=True)

        root_file = os.path.join(root_dir, "houdini_node_chains.json")
        parent_file = os.path.join(parent_dir, "houdini_node_chains.json")
        with open(root_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "metadata": {"terminology": {"node": "Repo root glossary"}},
                    "chains": [
                        {
                            "id": "shared_001",
                            "title": "Root chain",
                            "context": "SOP",
                            "goal": "Use the repo root version.",
                            "tags": ["root"],
                            "nodes": [{"name": "box1", "type": "box", "parms": {}}],
                            "connections": [],
                        }
                    ],
                },
                f,
            )
        with open(parent_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "metadata": {"terminology": {"node": "Parent glossary"}},
                    "chains": [
                        {
                            "id": "shared_001",
                            "title": "Parent duplicate",
                            "context": "SOP",
                            "goal": "Should be skipped as duplicate.",
                            "tags": ["parent"],
                            "nodes": [{"name": "sphere1", "type": "sphere", "parms": {}}],
                            "connections": [],
                        },
                        {
                            "id": "unique_parent",
                            "title": "Parent unique",
                            "context": "DOP",
                            "goal": "Should still load.",
                            "tags": ["parent"],
                            "nodes": [{"name": "dopnet1", "type": "dopnet", "parms": {}}],
                            "connections": [],
                        },
                    ],
                },
                f,
            )

        original_root = kb_mod.ROOT
        original_data = kb_mod.DATA_DIR
        try:
            kb_mod.ROOT = root_dir
            kb_mod.DATA_DIR = data_dir
            entries = kb_mod._load_node_chain_training_data()
        finally:
            kb_mod.ROOT = original_root
            kb_mod.DATA_DIR = original_data

        chain_titles = [entry["title"] for entry in entries if entry.get("_chain_id")]
        self.assertIn("Node Chain: Root chain", chain_titles)
        self.assertIn("Node Chain: Parent unique", chain_titles)
        self.assertNotIn("Node Chain: Parent duplicate", chain_titles)
        self.assertEqual(
            len(
                [
                    entry
                    for entry in entries
                    if entry.get("title") == "Houdini Node Chain Terminology"
                ]
            ),
            1,
        )

    def test_context_injector_records_last_context_meta(self):
        from houdinimind.rag.injector import ContextInjector

        class _FakeRetriever:
            def retrieve(self, **kwargs):
                return [
                    {
                        "id": "chunk1",
                        "title": "Box Workflow",
                        "category": "workflow",
                        "content": "Create a box and end on OUT.",
                        "_score": 0.91,
                    }
                ]

            def get_chunk(self, _cid):
                return None

        injector = ContextInjector(_FakeRetriever(), max_context_tokens=200, top_k=2, min_score=0.1)
        ctx = injector.build_context_message("create a box")

        self.assertIsNotNone(ctx)
        self.assertEqual(injector.last_context_meta["used_count"], 1)
        self.assertIn("Box Workflow", injector.last_context_meta["chunk_titles"])
        self.assertGreater(injector.last_context_meta["estimated_tokens"], 0)

    def test_debug_logger_writes_basic_session_files(self):
        from houdinimind.debug.debug_logger import DebugLogger

        tmp = _workspace_case_dir("debug_logger_meta")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        logger = DebugLogger(tmp)
        logger.log_session_config({"model": "test-model"}, extra={"max_tool_rounds": 40})
        logger.log_turn_start("Create a box", meta={"request_mode": "build", "dry_run": False})
        logger.log_tool_call(
            "create_node",
            {"node_type": "box"},
            {"status": "ok", "message": "Created", "data": {}, "_meta": {"duration_ms": 45}},
        )
        logger.log_system_note("Scene snapshot failed: example")
        logger.log_response("Built the box.")
        logger.log_turn_end("Built the box.")

        with open(logger.meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        self.assertEqual(meta["turn_count"], 1)
        self.assertEqual(meta["config"]["config"]["model"], "test-model")
        with open(logger.md_path, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("## Turn: Create a box", text)
        self.assertIn("#### ✅ `create_node`", text)
        self.assertIn("### Agent Response", text)

    def test_debug_logger_writes_planning_to_markdown(self):
        from houdinimind.debug.debug_logger import DebugLogger

        tmp = _workspace_case_dir("debug_logger_planning_md")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        logger = DebugLogger(tmp)
        logger.log_turn_start("Create a table")
        started = logger.log_phase_start("planning")
        logger.log_plan(
            {
                "prototype_scale": {
                    "unit": "Houdini units",
                    "overall_size": "4 x 2.5 x 3",
                    "notes": "table prototype",
                },
                "phases": [
                    {
                        "phase": "Build",
                        "steps": [
                            {
                                "step": 1,
                                "action": "Build tabletop",
                                "risk_level": "medium",
                                "measurements": {"width": 4, "height": 0.2, "depth": 3},
                                "placement": "centered",
                                "spacing": "four legs 3.4 units apart across width",
                                "relationships": ["legs touch underside"],
                                "validation": "tabletop is flat and supported",
                            },
                        ],
                    }
                ],
            }
        )
        logger.log_phase_end("planning", started_at=started, meta={"phases": 1})
        logger.log_turn_end()

        with open(logger.md_path, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("### Planning", text)
        self.assertIn("#### Prototype Scale", text)
        self.assertIn("overall_size: 4 x 2.5 x 3", text)
        self.assertIn("#### Stage: Build", text)
        self.assertIn("measurements: width=4", text)
        self.assertIn("spacing: four legs 3.4 units apart across width", text)
        self.assertIn("risk=medium", text)

    def test_run_loop_blocks_success_after_failed_validation_without_repair(self):
        from houdinimind.agent.loop import AgentLoop

        tmp = _workspace_case_dir("validation_failure_blocks_success")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        loop = AgentLoop({"data_dir": tmp, "ollama_url": "http://localhost:11434"})
        original_chat = loop.llm.chat
        try:
            loop.llm.chat = lambda *args, **kwargs: {
                "content": "Done. Everything is complete.",
                "tool_calls": [],
            }
            loop._turn_validation_failed = True
            loop._turn_validation_issues = ["ground plane was not created"]
            result = loop._run_loop(
                [{"role": "user", "content": "fracture the table and add ground"}],
                request_mode="build",
            )
        finally:
            loop.llm.chat = original_chat

        self.assertIn("Validation did not pass", result)
        self.assertIn("ground plane was not created", result)
        self.assertNotIn("Everything is complete", result)

    def test_capture_viewport_does_not_fallback_to_main_window(self):
        import houdinimind.bridge.viewport_capture as vc

        class _FakeDesktop:
            def paneTabOfType(self, _pane_type):
                return object()

        class _FakeUi:
            def curDesktop(self):
                return _FakeDesktop()

        class _FakePaneTabType:
            SceneViewer = object()

        class _FakeHou:
            ui = _FakeUi()
            paneTabType = _FakePaneTabType()

        calls = {"main_window": 0}
        originals = {
            "HOU_AVAILABLE": vc.HOU_AVAILABLE,
            "hou": getattr(vc, "hou", None),
            "_widget_for_pane": vc._widget_for_pane,
            "_extract_screen_rect": vc._extract_screen_rect,
            "_flipbook_viewport": vc._flipbook_viewport,
            "_find_scene_viewer_widget": vc._find_scene_viewer_widget,
            "capture_main_window": vc.capture_main_window,
        }

        try:
            vc.HOU_AVAILABLE = True
            vc.hou = _FakeHou()
            vc._widget_for_pane = lambda _viewer: None
            vc._extract_screen_rect = lambda _bounds: None
            vc._flipbook_viewport = lambda _viewer, scale=0.75: None
            vc._find_scene_viewer_widget = lambda: None

            def fake_main_window(scale=0.5):
                calls["main_window"] += 1
                return "main-window-image"

            vc.capture_main_window = fake_main_window
            result = vc.capture_viewport()
        finally:
            vc.HOU_AVAILABLE = originals["HOU_AVAILABLE"]
            if originals["hou"] is None:
                try:
                    delattr(vc, "hou")
                except AttributeError:
                    pass
            else:
                vc.hou = originals["hou"]
            vc._widget_for_pane = originals["_widget_for_pane"]
            vc._extract_screen_rect = originals["_extract_screen_rect"]
            vc._flipbook_viewport = originals["_flipbook_viewport"]
            vc._find_scene_viewer_widget = originals["_find_scene_viewer_widget"]
            vc.capture_main_window = originals["capture_main_window"]

        self.assertIsNone(result)
        self.assertEqual(calls["main_window"], 0)

    def test_small_model_no_longer_disables_planning_or_vision(self):
        from houdinimind.agent.loop import AgentLoop

        tmp = _workspace_case_dir("small_model_runtime_flags")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        loop = AgentLoop(
            {
                "data_dir": tmp,
                "ollama_url": "http://localhost:11434",
                "model": "qwen3.5:2b",
                "vision_enabled": True,
                "plan_enabled": True,
            }
        )

        self.assertTrue(loop._vision_enabled)
        self.assertTrue(loop._plan_enabled)

    def test_set_node_parameter_falls_back_to_expression_for_expression_strings(self):
        import houdinimind.agent.tools as tools_mod

        class _FakeExprLanguage:
            Hscript = "hscript"
            Python = "python"

        class _FakeExprParm(_FakeParm):
            def __init__(self, name, value=0):
                super().__init__(name, value)
                self.expression = None

            def set(self, value):
                if isinstance(value, str) and "ch(" in value:
                    raise TypeError("Cannot set numeric parm to a string expression")
                self._value = value

            def setExpression(self, expression, language):
                self.expression = (expression, language)

        class _FakeExprNode(_FakeParmNode):
            def __init__(self, path):
                super().__init__(path, type_name="box", parms={})
                self._parms["tx"] = _FakeExprParm("tx", 0)

        original_hou = getattr(tools_mod, "hou", None)
        node = _FakeExprNode("/obj/geo1/box1")

        class _FakeHou:
            exprLanguage = _FakeExprLanguage()

        try:
            tools_mod.hou = _FakeHou()
            result = tools_mod._set_node_parameter(node, "tx", "ch('/obj/CTRL/tx')")
        finally:
            tools_mod.hou = original_hou

        self.assertEqual(result["status"], "ok")
        self.assertIn("Set expression", result["message"])
        self.assertEqual(node.parm("tx").expression, ("ch('/obj/CTRL/tx')", "hscript"))

    def test_set_node_parameter_sets_scalar_tuple_uniformly(self):
        import houdinimind.agent.tools as tools_mod

        class ParmTuple:
            def __init__(self, name, size):
                self._name = name
                self._size = size
                self._value = [0.0] * size

            def __len__(self):
                return self._size

            def eval(self):
                return list(self._value)

            def set(self, value):
                self._value = list(value)

            def parmTemplate(self):
                return _FakeParmTemplate()

        class _FakeTupleNode(_FakeParmNode):
            def __init__(self, path):
                super().__init__(path, type_name="sphere", parms={})
                self.radius = ParmTuple("rad", 3)

            def parmTuple(self, name):
                if name == "rad":
                    return self.radius
                return None

        original_hou = getattr(tools_mod, "hou", None)
        node = _FakeTupleNode("/obj/geo1/sphere1")

        try:
            tools_mod.hou = None
            result = tools_mod._set_node_parameter(node, "rad", 0.35)
        finally:
            tools_mod.hou = original_hou

        self.assertEqual(result["status"], "ok")
        self.assertEqual(node.radius.eval(), [0.35, 0.35, 0.35])
        self.assertEqual(result["data"]["new"], [0.35, 0.35, 0.35])

    def test_create_node_chain_returns_error_on_partial_failure(self):
        import houdinimind.agent.tools as tools_mod

        class _FakeChainNode:
            def __init__(self, parent, name, node_type):
                self._parent = parent
                self._name = name
                self._path = f"{parent.path().rstrip('/')}/{name}"
                self._type = _FakeParmType(node_type)
                self._inputs = []
                self._outputs = []
                self._parms = {}
                self.destroyed = False

            def path(self):
                return self._path

            def name(self):
                return self._name

            def type(self):
                return self._type

            def moveToGoodPosition(self):
                return None

            def setInput(self, index, node, *_args):
                while len(self._inputs) <= index:
                    self._inputs.append(None)
                self._inputs[index] = node
                if node and self not in node._outputs:
                    node._outputs.append(self)

            def outputConnections(self):
                return list(self._outputs)

            def parm(self, name):
                return self._parms.get(name)

            def parms(self):
                return list(self._parms.values())

            def cook(self, force=False):
                return None

            def errors(self):
                return []

            def setDisplayFlag(self, flag):
                self.display = flag

            def setRenderFlag(self, flag):
                self.render = flag

            def destroy(self):
                self.destroyed = True

        class _FakeChainParent:
            def __init__(self, path, fail_types=None):
                self._path = path
                self._nodes = {path: self}
                self._created = []
                self._fail_types = set(fail_types or [])

            def path(self):
                return self._path

            def createNode(self, node_type, name=None):
                if node_type in self._fail_types:
                    raise RuntimeError(f"cannot create {node_type}")
                node_name = name or f"{node_type}1"
                node = _FakeChainNode(self, node_name, node_type)
                self._nodes[node.path()] = node
                self._created.append(node)
                return node

            def layoutChildren(self):
                return None

        class _FakeChainHou:
            def __init__(self, parent):
                self._parent = parent

            def node(self, path):
                return self._parent._nodes.get(path)

        original_hou = getattr(tools_mod, "hou", None)
        original_available = tools_mod.HOU_AVAILABLE
        parent = _FakeChainParent("/obj/geo1")

        try:
            tools_mod.HOU_AVAILABLE = True
            tools_mod.hou = _FakeChainHou(parent)
            result = tools_mod.create_node_chain(
                "/obj/geo1",
                [
                    {"type": "box", "name": "box1"},
                    {"type": "xform", "name": "xform1", "parms": {"missingparm": 1}},
                ],
                cleanup_on_error=False,
            )

            cleanup_parent = _FakeChainParent("/obj/geo_cleanup")
            tools_mod.hou = _FakeChainHou(cleanup_parent)
            cleanup_result = tools_mod.create_node_chain(
                "/obj/geo_cleanup",
                [
                    {"type": "box", "name": "box1"},
                    {"type": "xform", "name": "xform1", "parms": {"missingparm": 1}},
                ],
                cleanup_on_error=True,
            )

            failed_parent = _FakeChainParent("/obj/geo_failed", fail_types={"badtype"})
            tools_mod.hou = _FakeChainHou(failed_parent)
            failed_result = tools_mod.create_node_chain(
                "/obj/geo_failed",
                [
                    {"type": "box", "name": "box1"},
                    {"type": "badtype", "name": "bad1", "inputs": ["box1"]},
                    {"type": "null", "name": "OUT"},
                ],
                cleanup_on_error=False,
            )
        finally:
            tools_mod.hou = original_hou
            tools_mod.HOU_AVAILABLE = original_available

        self.assertEqual(result["status"], "error")
        self.assertTrue(result["data"]["partial"])
        self.assertEqual(result["data"]["count"], 2)
        self.assertIn("Chain incomplete", result["message"])
        self.assertTrue(all(not node.destroyed for node in parent._created))

        self.assertEqual(cleanup_result["status"], "error")
        self.assertEqual(cleanup_result["data"]["count"], 2)
        self.assertEqual(len(cleanup_result["data"]["cleaned_up"]), 2)
        self.assertTrue(all(node.destroyed for node in cleanup_parent._created))

        self.assertEqual(failed_result["status"], "error")
        out_node = failed_parent._nodes["/obj/geo_failed/OUT"]
        self.assertEqual(out_node._inputs, [])

    def test_create_node_chain_rejects_missing_step_type(self):
        import houdinimind.agent.tools as tools_mod

        class _FakeChainNode:
            def __init__(self, parent, name, node_type):
                self._parent = parent
                self._name = name
                self._path = f"{parent.path().rstrip('/')}/{name}"
                self._type = _FakeParmType(node_type)
                self._inputs = []
                self._outputs = []
                self._parms = {}

            def path(self):
                return self._path

            def name(self):
                return self._name

            def type(self):
                return self._type

            def moveToGoodPosition(self):
                return None

            def setInput(self, index, node, *_args):
                while len(self._inputs) <= index:
                    self._inputs.append(None)
                self._inputs[index] = node
                if node and self not in node._outputs:
                    node._outputs.append(self)

            def outputConnections(self):
                return list(self._outputs)

            def parm(self, name):
                return self._parms.get(name)

            def parms(self):
                return list(self._parms.values())

            def cook(self, force=False):
                return None

            def errors(self):
                return []

            def setDisplayFlag(self, flag):
                self.display = flag

            def setRenderFlag(self, flag):
                self.render = flag

        class _FakeChainParent:
            def __init__(self, path):
                self._path = path
                self._nodes = {path: self}

            def path(self):
                return self._path

            def createNode(self, node_type, name=None):
                node_name = name or f"{node_type}1"
                node = _FakeChainNode(self, node_name, node_type)
                self._nodes[node.path()] = node
                return node

            def layoutChildren(self):
                return None

        class _FakeChainHou:
            def __init__(self, parent):
                self._parent = parent

            def node(self, path):
                return self._parent._nodes.get(path)

        original_hou = getattr(tools_mod, "hou", None)
        original_available = tools_mod.HOU_AVAILABLE
        parent = _FakeChainParent("/obj/geo1")

        try:
            tools_mod.HOU_AVAILABLE = True
            tools_mod.hou = _FakeChainHou(parent)
            result = tools_mod.create_node_chain(
                "/obj/geo1",
                [
                    {"type": "box", "name": "box1"},
                    {"type": None, "name": "bad_step"},
                ],
            )
        finally:
            tools_mod.hou = original_hou
            tools_mod.HOU_AVAILABLE = original_available

        self.assertEqual(result["status"], "error")
        self.assertTrue(result["data"]["partial"])
        self.assertIn("non-empty string", result["data"]["step_errors"][0])

    def test_create_node_chain_merge_auto_gather_ignores_downstream_nodes(self):
        import houdinimind.agent.tools as tools_mod

        class _FakeChainNode:
            def __init__(self, parent, name, node_type):
                self._parent = parent
                self._name = name
                self._path = f"{parent.path().rstrip('/')}/{name}"
                self._type = _FakeParmType(node_type)
                self._inputs = []
                self._outputs = []

            def path(self):
                return self._path

            def name(self):
                return self._name

            def type(self):
                return self._type

            def parent(self):
                return self._parent

            def moveToGoodPosition(self):
                return None

            def setInput(self, index, node, *_args):
                while len(self._inputs) <= index:
                    self._inputs.append(None)
                self._inputs[index] = node
                if node and self not in node._outputs:
                    node._outputs.append(self)

            def inputConnections(self):
                return [node for node in self._inputs if node is not None]

            def outputConnections(self):
                return list(self._outputs)

            def parm(self, _name):
                return None

            def parms(self):
                return []

            def cook(self, force=False):
                return None

            def errors(self):
                return []

            def setDisplayFlag(self, flag):
                self.display = flag

            def setRenderFlag(self, flag):
                self.render = flag

        class _FakeChainParent:
            def __init__(self, path):
                self._path = path
                self._nodes = {path: self}

            def path(self):
                return self._path

            def createNode(self, node_type, name=None):
                node_name = name or f"{node_type}1"
                node = _FakeChainNode(self, node_name, node_type)
                self._nodes[node.path()] = node
                return node

            def node(self, name):
                return self._nodes.get(f"{self._path.rstrip('/')}/{name}")

            def layoutChildren(self):
                return None

        class _FakeChainHou:
            def __init__(self, parent):
                self._parent = parent

            def node(self, path):
                return self._parent._nodes.get(path)

        original_hou = getattr(tools_mod, "hou", None)
        original_available = tools_mod.HOU_AVAILABLE
        parent = _FakeChainParent("/obj/geo1")

        try:
            tools_mod.HOU_AVAILABLE = True
            tools_mod.hou = _FakeChainHou(parent)
            result = tools_mod.create_node_chain(
                "/obj/geo1",
                [
                    {"type": "box", "name": "box1"},
                    {"type": "merge", "name": "merge1"},
                    {"type": "color", "name": "color1", "inputs": ["merge1"]},
                    {"type": "null", "name": "OUT", "inputs": ["color1"]},
                ],
            )
        finally:
            tools_mod.hou = original_hou
            tools_mod.HOU_AVAILABLE = original_available

        self.assertEqual(result["status"], "ok")
        merge = parent._nodes["/obj/geo1/merge1"]
        color = parent._nodes["/obj/geo1/color1"]
        self.assertEqual([node.path() for node in merge._inputs], ["/obj/geo1/box1"])
        self.assertEqual([node.path() for node in color._inputs], ["/obj/geo1/merge1"])

    def test_create_node_chain_prevalidation_does_not_create_temp_nodes(self):
        import houdinimind.agent.tools as tools_mod

        class _FakeCategory:
            def name(self):
                return "Sop"

            def nodeTypes(self):
                return {"box": object(), "null": object()}

        class _FakeChainNode:
            def __init__(self, parent, name, node_type):
                self._parent = parent
                self._name = name
                self._path = f"{parent.path().rstrip('/')}/{name}"
                self._type = _FakeParmType(node_type)
                self._inputs = []
                self._outputs = []

            def path(self):
                return self._path

            def name(self):
                return self._name

            def type(self):
                return self._type

            def parent(self):
                return self._parent

            def childTypeCategory(self):
                return _FakeCategory()

            def moveToGoodPosition(self):
                return None

            def setInput(self, index, node, *_args):
                while len(self._inputs) <= index:
                    self._inputs.append(None)
                self._inputs[index] = node
                if node and self not in node._outputs:
                    node._outputs.append(self)

            def inputConnections(self):
                return [node for node in self._inputs if node is not None]

            def outputConnections(self):
                return list(self._outputs)

            def parm(self, _name):
                return None

            def parms(self):
                return []

            def cook(self, force=False):
                return None

            def errors(self):
                return []

            def setDisplayFlag(self, flag):
                self.display = flag

            def setRenderFlag(self, flag):
                self.render = flag

        class _FakeChainParent:
            def __init__(self, path):
                self._path = path
                self._nodes = {path: self}
                self.created_names = []

            def path(self):
                return self._path

            def type(self):
                return _FakeParmType("geo")

            def childTypeCategory(self):
                return _FakeCategory()

            def createNode(self, node_type, name=None):
                node_name = name or f"{node_type}1"
                self.created_names.append(node_name)
                node = _FakeChainNode(self, node_name, node_type)
                self._nodes[node.path()] = node
                return node

            def node(self, name):
                return self._nodes.get(f"{self._path.rstrip('/')}/{name}")

            def layoutChildren(self):
                return None

        class _FakeChainHou:
            def __init__(self, parent):
                self._parent = parent

            def node(self, path):
                return self._parent._nodes.get(path)

        original_hou = getattr(tools_mod, "hou", None)
        original_available = tools_mod.HOU_AVAILABLE
        parent = _FakeChainParent("/obj/geo1")

        try:
            tools_mod.HOU_AVAILABLE = True
            tools_mod.hou = _FakeChainHou(parent)
            result = tools_mod.create_node_chain(
                "/obj/geo1",
                [
                    {"type": "box", "name": "box1"},
                    {"type": "null", "name": "OUT", "inputs": ["box1"]},
                ],
            )
        finally:
            tools_mod.hou = original_hou
            tools_mod.HOU_AVAILABLE = original_available

        self.assertEqual(result["status"], "ok")
        self.assertNotIn("__type_check_tmp__", parent.created_names)
        self.assertEqual(parent.created_names, ["box1", "OUT"])

    def test_list_node_types_truncates_large_unfiltered_categories(self):
        import houdinimind.agent.tools as tools_mod

        class _FakeTypeCategory:
            def nodeTypes(self):
                return {f"type_{i:03d}": object() for i in range(120)}

        class _FakeHou:
            @staticmethod
            def sopNodeTypeCategory():
                return _FakeTypeCategory()

            @staticmethod
            def dopNodeTypeCategory():
                return _FakeTypeCategory()

            @staticmethod
            def objNodeTypeCategory():
                return _FakeTypeCategory()

            @staticmethod
            def lopNodeTypeCategory():
                return _FakeTypeCategory()

            @staticmethod
            def vopNodeTypeCategory():
                return _FakeTypeCategory()

            @staticmethod
            def ropNodeTypeCategory():
                return _FakeTypeCategory()

        original_hou = getattr(tools_mod, "hou", None)
        original_available = tools_mod.HOU_AVAILABLE
        try:
            tools_mod.HOU_AVAILABLE = True
            tools_mod.hou = _FakeHou()
            result = tools_mod.list_node_types("sop", None)
        finally:
            tools_mod.hou = original_hou
            tools_mod.HOU_AVAILABLE = original_available

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["count"], 120)
        self.assertEqual(len(result["data"]["types"]), 40)
        self.assertTrue(result["data"]["truncated"])

    def test_scene_reader_dop_summary_does_not_require_hou_dopnetwork_class(self):
        import houdinimind.bridge.scene_reader as scene_reader_mod

        class _FakeCategory:
            def __init__(self, name):
                self._name = name

            def name(self):
                return self._name

        class _FakeType:
            def __init__(self, name):
                self._name = name

            def name(self):
                return self._name

        class _FakeObj:
            def __init__(self, name):
                self._name = name

            def name(self):
                return self._name

        class _FakeSolverNode:
            def __init__(self, node_type):
                self._type = _FakeType(node_type)

            def type(self):
                return self._type

        class _FakeDopNode:
            def __init__(self, path, type_name, child_category):
                self._path = path
                self._type = _FakeType(type_name)
                self._child_category = _FakeCategory(child_category)

            def path(self):
                return self._path

            def type(self):
                return self._type

            def childTypeCategory(self):
                return self._child_category

            def objects(self):
                return [_FakeObj("cloth1"), _FakeObj("cloth2")]

            def children(self):
                return [_FakeSolverNode("vellumsolver"), _FakeSolverNode("merge")]

            def errors(self):
                return ["solver warning"]

        class _FakeObjRoot:
            def allSubChildren(self):
                return [
                    _FakeDopNode("/obj/dopnet1", "dopnet", "Dop"),
                    _FakeDopNode("/obj/geo1", "geo", "Sop"),
                ]

        class _FakeHou:
            def node(self, path):
                if path == "/obj":
                    return _FakeObjRoot()
                return None

            @staticmethod
            def frame():
                return 24

        original_hou = getattr(scene_reader_mod, "hou", None)
        original_available = scene_reader_mod.HOU_AVAILABLE
        try:
            scene_reader_mod.HOU_AVAILABLE = True
            scene_reader_mod.hou = _FakeHou()
            summary = scene_reader_mod.SceneReader()._dop_summary()
        finally:
            scene_reader_mod.hou = original_hou
            scene_reader_mod.HOU_AVAILABLE = original_available

        self.assertEqual(len(summary), 1)
        self.assertEqual(summary[0]["path"], "/obj/dopnet1")
        self.assertEqual(summary[0]["object_count"], 2)
        self.assertIn("vellumsolver", summary[0]["solvers"])

    def test_scene_reader_prefers_limited_children_traversal_over_allsubchildren(self):
        import houdinimind.bridge.scene_reader as scene_reader_mod

        class _Node:
            def __init__(self, path, children=None):
                self._path = path
                self._children = list(children or [])

            def path(self):
                return self._path

            def children(self):
                return list(self._children)

        root = _Node(
            "/",
            [
                _Node("/obj", [_Node("/obj/geo1"), _Node("/obj/geo2")]),
                _Node("/mat", [_Node("/mat/matnet1")]),
            ],
        )

        def _boom():
            raise AssertionError("allSubChildren should not be used for bounded traversal")

        root.allSubChildren = _boom

        nodes = scene_reader_mod.SceneReader._iter_subchildren(root, limit=3)
        self.assertEqual([node.path() for node in nodes], ["/obj", "/mat", "/obj/geo1"])

    def test_panel_positive_feedback_records_reusable_recipe(self):
        try:
            from PySide6 import QtWidgets

            from hm_ui.panel import HoudiniMindPanel
        except Exception as exc:
            self.skipTest(f"PySide6 unavailable: {exc}")

        QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        case_dir = _workspace_case_dir("panel_positive_feedback_recipe")

        class _Recipes:
            def __init__(self):
                self.added = []
                self.used = []

            def add_recipe(self, **kwargs):
                self.added.append(kwargs)
                return 7

            def record_use(self, recipe_id, accepted, complexity_weight=1.0):
                self.used.append((recipe_id, accepted, complexity_weight))

        class _Memory:
            def __init__(self):
                self.recipes = _Recipes()
                self._last_user_message = "create a clean table"

            def record_feedback(self, accepted):
                self.accepted = accepted

            def run_learning_cycle(self):
                return {}

            def dashboard(self):
                return {"log": {}, "recipes": {}, "project_rules": {}}

            def get_recipes(self):
                return []

        class _Agent:
            def reload_system_prompt(self):
                return None

            def reload_knowledge(self):
                return None

        original_setup = HoudiniMindPanel._setup_backend
        original_hooks = HoudiniMindPanel._start_event_hooks
        original_refresh = HoudiniMindPanel._refresh_models_async
        panel = None

        def _fake_setup(self):
            self._config_path = os.path.join(case_dir, "core_config.json")
            self.config = {"ui": {}, "backend": "ollama", "model": "", "vision_model": ""}
            self.agent = _Agent()
            self.memory = _Memory()
            self.event_hooks = None

        try:
            HoudiniMindPanel._setup_backend = _fake_setup
            HoudiniMindPanel._start_event_hooks = lambda self: None
            HoudiniMindPanel._refresh_models_async = lambda self: None
            panel = HoudiniMindPanel()
            panel._last_turn_tools = [
                {"name": "create_node", "args": {"node_type": "box", "name": "tabletop"}},
                {"name": "set_parameter", "args": {"parm_name": "scale"}},
            ]
            panel._record_positive_recipe()

            self.assertEqual(len(panel.memory.recipes.added), 1)
            self.assertEqual(panel.memory.recipes.added[0]["domain"], "furniture")
            self.assertEqual(panel.memory.recipes.added[0]["steps"][0]["tool"], "create_node")
            self.assertEqual(panel.memory.recipes.used, [(7, True, 1.5)])
        finally:
            if panel is not None:
                try:
                    panel.close()
                except Exception:
                    pass
            HoudiniMindPanel._setup_backend = original_setup
            HoudiniMindPanel._start_event_hooks = original_hooks
            HoudiniMindPanel._refresh_models_async = original_refresh

    def test_panel_disables_more_actions_while_busy_and_scene_actions_without_houdini(self):
        try:
            from PySide6 import QtWidgets

            from hm_ui.panel import HoudiniMindPanel
        except Exception as exc:
            self.skipTest(f"PySide6 unavailable: {exc}")

        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        case_dir = _workspace_case_dir("panel_action_availability")
        log_path = os.path.join(case_dir, "session.md")
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("# debug\n")

        class _DummyLogger:
            def get_session_path(self):
                return log_path

        class _DummyAgent:
            def __init__(self):
                self.debug_logger = _DummyLogger()
                self.conversation = [{"role": "user", "content": "hello"}]
                self.undo_stack = []

        original_setup = HoudiniMindPanel._setup_backend
        original_hooks = HoudiniMindPanel._start_event_hooks
        original_refresh = HoudiniMindPanel._refresh_models_async
        panel = None

        def _fake_setup(self):
            self._config_path = os.path.join(case_dir, "core_config.json")
            self.config = {"ui": {}, "backend": "ollama", "model": "", "vision_model": ""}
            self.agent = _DummyAgent()
            self.memory = None
            self.event_hooks = None

        try:
            HoudiniMindPanel._setup_backend = _fake_setup
            HoudiniMindPanel._start_event_hooks = lambda self: None
            HoudiniMindPanel._refresh_models_async = lambda self: None
            panel = HoudiniMindPanel()
            panel._has_conversation_content = True
            panel._refresh_action_availability()

            self.assertFalse(panel.inspect_network_action.isEnabled())
            self.assertFalse(panel.composer_inspect_network_action.isEnabled())
            self.assertTrue(panel.debug_log_action.isEnabled())
            self.assertTrue(panel.more_actions_btn.isEnabled())

            panel._set_busy(True)
            app.processEvents()

            self.assertFalse(panel.more_actions_btn.isEnabled())
            self.assertFalse(panel.refresh_models_btn.isEnabled())
            self.assertFalse(panel.debug_log_action.isEnabled())
        finally:
            if panel is not None:
                try:
                    panel.close()
                except Exception:
                    pass
            HoudiniMindPanel._setup_backend = original_setup
            HoudiniMindPanel._start_event_hooks = original_hooks
            HoudiniMindPanel._refresh_models_async = original_refresh

    def test_panel_show_debug_log_keeps_dialog_alive(self):
        try:
            from PySide6 import QtWidgets

            from hm_ui.panel import HoudiniMindPanel
        except Exception as exc:
            self.skipTest(f"PySide6 unavailable: {exc}")

        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        case_dir = _workspace_case_dir("panel_debug_log_dialog")
        log_path = os.path.join(case_dir, "session.md")
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("# debug\n\nhello")

        class _DummyLogger:
            def get_session_path(self):
                return log_path

        class _DummyAgent:
            def __init__(self):
                self.debug_logger = _DummyLogger()
                self.conversation = [{"role": "user", "content": "hello"}]
                self.undo_stack = []

        original_setup = HoudiniMindPanel._setup_backend
        original_hooks = HoudiniMindPanel._start_event_hooks
        original_refresh = HoudiniMindPanel._refresh_models_async
        panel = None

        def _fake_setup(self):
            self._config_path = os.path.join(case_dir, "core_config.json")
            self.config = {"ui": {}, "backend": "ollama", "model": "", "vision_model": ""}
            self.agent = _DummyAgent()
            self.memory = None
            self.event_hooks = None

        try:
            HoudiniMindPanel._setup_backend = _fake_setup
            HoudiniMindPanel._start_event_hooks = lambda self: None
            HoudiniMindPanel._refresh_models_async = lambda self: None
            panel = HoudiniMindPanel()
            panel._show_debug_log()
            app.processEvents()

            self.assertIsNotNone(panel._debug_log_dialog)
            self.assertEqual(panel._debug_log_dialog.log_path, log_path)
        finally:
            if panel is not None:
                try:
                    if getattr(panel, "_debug_log_dialog", None) is not None:
                        panel._debug_log_dialog.close()
                except Exception:
                    pass
                try:
                    panel.close()
                except Exception:
                    pass
            HoudiniMindPanel._setup_backend = original_setup
            HoudiniMindPanel._start_event_hooks = original_hooks
            HoudiniMindPanel._refresh_models_async = original_refresh

    def test_settings_panel_emits_nvidia_api_key_config(self):
        try:
            from PySide6 import QtWidgets

            from houdinimind.agent.ui._widgets import SettingsPanel
        except Exception as exc:
            self.skipTest(f"PySide6 unavailable: {exc}")

        QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        panel = SettingsPanel(
            {
                "ui": {},
                "backend": "nvidia",
                "model": "deepseek-ai/deepseek-v4-pro",
                "vision_model": "deepseek-ai/deepseek-v4-pro",
                "api_key": "old-key",
                "openai_base_url": "https://integrate.api.nvidia.com/v1",
            }
        )
        emitted = []
        panel.settings_changed.connect(emitted.append)

        panel.backend_combo.setCurrentIndex(panel.backend_combo.findData("nvidia"))
        panel.chat_model_combo.setCurrentText("deepseek-ai/deepseek-v4-pro")
        panel.api_key_edit.setText("nvapi-test")
        panel.openai_url_edit.setText("https://integrate.api.nvidia.com/v1")
        panel._emit()

        self.assertEqual(emitted[-1]["backend"], "nvidia")
        self.assertEqual(emitted[-1]["api_key"], "nvapi-test")
        self.assertEqual(emitted[-1]["openai_base_url"], "https://integrate.api.nvidia.com/v1")
        self.assertTrue(panel.url_edit.isHidden())
        self.assertFalse(panel.api_key_edit.isHidden())

    def test_nvidia_backend_dispatches_to_openai_compatible_chat(self):
        from houdinimind.agent.llm_client import OllamaClient

        client = OllamaClient(
            {
                "backend": "nvidia",
                "model": "deepseek-ai/deepseek-v4-pro",
                "api_key": "nvapi-test",
                "openai_base_url": "https://integrate.api.nvidia.com/v1",
                "context_window": 32768,
            }
        )
        seen = {}

        def fake_openai_chat(messages, tools=None, model_override=None, **kwargs):
            seen["messages"] = messages
            seen["tools"] = tools
            seen["model_override"] = model_override
            seen["kwargs"] = kwargs
            return {"role": "assistant", "content": "ok"}

        client._openai_compatible_chat = fake_openai_chat
        result = client.chat(
            [{"role": "user", "content": "hello"}],
            tools=[{"type": "function", "function": {"name": "noop", "parameters": {}}}],
            chunk_callback=lambda _delta: None,
        )

        self.assertEqual(result["content"], "ok")
        self.assertEqual(client.backend_name, "nvidia")
        self.assertEqual(client.base_url, "https://integrate.api.nvidia.com/v1")
        self.assertEqual(seen["model_override"], "deepseek-ai/deepseek-v4-pro")
        self.assertEqual(seen["tools"][0]["function"]["name"], "noop")
        self.assertIn("chunk_callback", seen["kwargs"])


if __name__ == "__main__":
    unittest.main()
