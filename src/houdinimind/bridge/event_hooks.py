# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
"""
EventHooks — multiplexed Houdini event listener.

Multiple HoudiniMind subsystems care about scene events (panel memory log,
MCP WebSocket broadcast, agent-loop cache invalidation). Registering a
separate `addEventCallback` per subsystem fires the callback chain N times
per scene change and made small actions (selection, display-flag toggle)
trigger N redundant traversals.

This module keeps the per-instance API the existing call sites already use,
but multiplexes them onto a single shared `addEventCallback` registration.
The first instance to `register()` installs the hou.* callbacks; subsequent
instances just subscribe their `on_event` to the shared dispatcher. The
hou.* callbacks are torn down only when the last instance unregisters.
"""

import threading
import time
from typing import Callable

try:
    import hou

    HOU_AVAILABLE = True
except ImportError:
    HOU_AVAILABLE = False


_shared_lock = threading.Lock()
_shared_subscribers: list["EventHooks"] = []
_shared_track_parm_changes = False
_shared_registered = False
_shared_last_parm_ts: dict[tuple, float] = {}


def _shared_dispatch_node(node, event_type, **kwargs):
    """Single Houdini node-event callback that fans out to all subscribers."""
    if not HOU_AVAILABLE:
        return
    event_name = str(event_type).split(".")[-1]
    # Selective debounce on ParmTupleChanged so a slider drag doesn't flood.
    if event_type == hou.nodeEventType.ParmTupleChanged:
        now = time.time()
        key = (node.path(), "parm")
        if now - _shared_last_parm_ts.get(key, 0) < 0.5:
            return
        _shared_last_parm_ts[key] = now
    data = {"event": event_name, "node_path": node.path(), "node_type": node.type().name()}
    with _shared_lock:
        subs = list(_shared_subscribers)
    for sub in subs:
        sub._emit("node", data)


def _shared_dispatch_hip(event_type, **kwargs):
    if not HOU_AVAILABLE:
        return
    data = {"event": str(event_type).split(".")[-1]}
    with _shared_lock:
        subs = list(_shared_subscribers)
    for sub in subs:
        sub._emit("hip_file", data)


def _ensure_shared_registration(track_parm_changes: bool) -> None:
    global _shared_registered, _shared_track_parm_changes
    if not HOU_AVAILABLE:
        return
    # If a subscriber wants parm tracking and we're already registered without
    # it, re-register with parm tracking enabled. This is rare — at startup
    # the loop subscribes with track_parm_changes=True before most others.
    need_reregister = _shared_registered and track_parm_changes and not _shared_track_parm_changes
    if _shared_registered and not need_reregister:
        return

    if need_reregister:
        try:
            hou.node("/").removeEventCallback(_shared_dispatch_node)
            hou.hipFile.removeEventCallback(_shared_dispatch_hip)
        except Exception:
            pass
        _shared_registered = False

    events = [
        hou.nodeEventType.ChildCreated,
        hou.nodeEventType.ChildDeleted,
        hou.nodeEventType.NameChanged,
        hou.nodeEventType.FlagChanged,
        hou.nodeEventType.InputRewired,
    ]
    if track_parm_changes:
        events.append(hou.nodeEventType.ParmTupleChanged)

    hou.node("/").addEventCallback(tuple(events), _shared_dispatch_node)
    hou.hipFile.addEventCallback(_shared_dispatch_hip)
    _shared_registered = True
    _shared_track_parm_changes = track_parm_changes


def _teardown_shared_registration() -> None:
    global _shared_registered, _shared_track_parm_changes
    if not HOU_AVAILABLE or not _shared_registered:
        return
    try:
        hou.node("/").removeEventCallback(_shared_dispatch_node)
    except Exception:
        pass
    try:
        hou.hipFile.removeEventCallback(_shared_dispatch_hip)
    except Exception:
        pass
    _shared_registered = False
    _shared_track_parm_changes = False
    _shared_last_parm_ts.clear()


class EventHooks:
    def __init__(self, on_event: Callable = None, track_parm_changes: bool = False):
        self.on_event = on_event
        self.track_parm_changes = track_parm_changes
        self._registered = False
        self._session_start = time.time()

    def register(self):
        if not HOU_AVAILABLE or self._registered:
            return
        with _shared_lock:
            _ensure_shared_registration(self.track_parm_changes or _shared_track_parm_changes)
            if self not in _shared_subscribers:
                _shared_subscribers.append(self)
        self._registered = True

    def unregister(self):
        if not HOU_AVAILABLE or not self._registered:
            return
        with _shared_lock:
            try:
                _shared_subscribers.remove(self)
            except ValueError:
                pass
            self._registered = False
            if not _shared_subscribers:
                _teardown_shared_registration()

    def _emit(self, cat: str, data: dict):
        if not self.on_event:
            return
        payload = dict(data)
        payload.update(
            {
                "_category": cat,
                "_ts": time.time(),
                "_age": round(time.time() - self._session_start, 1),
            }
        )
        try:
            self.on_event(cat, payload)
        except Exception:
            pass
