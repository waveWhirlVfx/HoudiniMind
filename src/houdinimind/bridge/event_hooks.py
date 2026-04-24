# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
﻿import time
from typing import Callable

try:
    import hou
    HOU_AVAILABLE = True
except ImportError:
    HOU_AVAILABLE = False

class EventHooks:
    def __init__(self, on_event: Callable = None, track_parm_changes: bool = False):
        self.on_event = on_event
        self.track_parm_changes = track_parm_changes
        self._registered = False
        self._last_event_ts = {}
        self._session_start = time.time()

    def register(self):
        if not HOU_AVAILABLE or self._registered: return
        hou.hipFile.addEventCallback(self._on_hip_event)
        
        events = [
            hou.nodeEventType.ChildCreated,
            hou.nodeEventType.ChildDeleted,
            hou.nodeEventType.NameChanged,
            hou.nodeEventType.FlagChanged,
            hou.nodeEventType.InputRewired
        ]
        if self.track_parm_changes:
            events.append(hou.nodeEventType.ParmTupleChanged)

        hou.node("/").addEventCallback(tuple(events), self._on_node_event)
        self._registered = True

    def unregister(self):
        if not HOU_AVAILABLE or not self._registered: return
        try:
            hou.hipFile.removeEventCallback(self._on_hip_event)
            hou.node("/").removeEventCallback(self._on_node_event)
        except: pass
        self._registered = False

    def _on_hip_event(self, event_type, **kwargs):
        self._emit("hip_file", {"event": str(event_type).split(".")[-1]})

    def _on_node_event(self, node, event_type, **kwargs):
        event_name = str(event_type).split(".")[-1]
        
        # Selective Debounce: only for ParmTupleChanged
        if event_type == hou.nodeEventType.ParmTupleChanged:
            now = time.time()
            key = (node.path(), "parm")
            if now - self._last_event_ts.get(key, 0) < 0.5: return
            self._last_event_ts[key] = now
            
        data = {"event": event_name, "node_path": node.path(), "node_type": node.type().name()}
        self._emit("node", data)

    def _emit(self, cat: str, data: dict):
        if self.on_event:
            data.update({"_category": cat, "_ts": time.time(), "_age": round(time.time()-self._session_start, 1)})
            try: self.on_event(cat, data)
            except: pass
