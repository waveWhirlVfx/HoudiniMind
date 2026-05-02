import sys
from pathlib import Path

sys.path.insert(0, str(Path("src").resolve()))
sys.path.insert(0, str(Path("tests").resolve()))

import sys

import fake_hou

sys.modules["hou"] = fake_hou

from houdinimind.agent.tools._simulation_tools import setup_pop_sim

fake_hou.reset_scene()
obj = fake_hou.node("/obj")
geo = obj.createNode("geo", "tornado_geo")
src = geo.createNode("grid", "base_grid")

result = setup_pop_sim("/obj/tornado_geo", src.path())
print(result)

for child in geo.children():
    print(f"Created: {child.path()} ({child.type().name()})")

if result.get("status") == "ok":
    dopnet = fake_hou.node(result["data"]["dopnet"])
    for d_child in dopnet.children():
        print(f"  DOP Child: {d_child.path()} ({d_child.type().name()})")
