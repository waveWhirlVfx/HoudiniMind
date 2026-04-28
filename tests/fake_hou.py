# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
class FakeCategory:
    def __init__(self, name: str):
        self._name = name

    def name(self):
        return self._name


class FakeType:
    def __init__(self, name: str, category_name: str):
        self._name = name
        self._category = FakeCategory(category_name)

    def name(self):
        return self._name

    def category(self):
        return self._category


class FakeChildNode:
    def __init__(self, path: str, type_name: str = "box", category_name: str = "Sop"):
        self._path = path
        self._type = FakeType(type_name, category_name)
        self.display_flag = None
        self.render_flag = None
        self.moved = False

    def path(self):
        return self._path

    def type(self):
        return self._type

    def moveToGoodPosition(self):
        self.moved = True

    def setDisplayFlag(self, flag):
        self.display_flag = flag

    def setRenderFlag(self, flag):
        self.render_flag = flag


class FakeParentNode:
    def __init__(self, path: str, parent_category: str = "Object", child_category: str = "Sop"):
        self._path = path
        self._type = FakeType(path.split("/")[-1] or "root", parent_category)
        self._child_category = FakeCategory(child_category)
        self.created = []

    def path(self):
        return self._path

    def type(self):
        return self._type

    def childTypeCategory(self):
        return self._child_category

    def createNode(self, node_type: str, name: str = None):
        node_name = name or f"{node_type}1"
        node = FakeChildNode(f"{self._path.rstrip('/')}/{node_name}", node_type, self._child_category.name())
        self.created.append((node_type, node_name, node))
        return node


class FakeHou:
    def __init__(self, node_map: dict):
        self._node_map = node_map

    def node(self, path: str):
        return self._node_map.get(path)
