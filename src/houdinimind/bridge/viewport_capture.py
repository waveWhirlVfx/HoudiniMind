# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
from __future__ import annotations

"""
HoudiniMind — Viewport & Network Editor Screenshot Capture
Grabs live PNG screenshots of Houdini panes for vision-enabled LLM context.

Capture strategy (tried in order):
  1. hou.ui.paneTabOfType → find matching Qt widget by walking the widget tree
  2. Grab the full Houdini main window as a fallback
"""

import base64
import io
import os
from typing import Optional

try:
    import hou
    from PySide6 import QtWidgets, QtCore, QtGui
    HOU_AVAILABLE = True
except ImportError:
    HOU_AVAILABLE = False
    QtWidgets = None
    QtCore = None
    QtGui = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _pixmap_to_b64(pixmap) -> Optional[str]:
    """Convert a QPixmap → base64-encoded PNG string."""
    try:
        buf = QtCore.QBuffer()
        buf.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
        pixmap.save(buf, "PNG")
        raw = bytes(buf.data())
        buf.close()
        if not raw:
            return None
        return base64.b64encode(raw).decode("utf-8")
    except Exception as e:
        print(f"[HoudiniMind Vision] pixmap_to_b64 error: {e}")
        return None


def _extract_screen_rect(bounds) -> Optional[tuple]:
    """
    Normalize Houdini pane bounds into a plain (left, top, right, bottom) tuple.

    Depending on the Houdini version / API surface, screenBounds() may return a
    tuple-like object or a BoundingRect instance with accessor methods.
    """
    if bounds is None:
        return None

    try:
        values = tuple(bounds)
        if len(values) == 4:
            return tuple(int(v) for v in values)
    except Exception:
        pass

    try:
        as_tuple = bounds.asTuple()
        if len(as_tuple) == 4:
            return tuple(int(v) for v in as_tuple)
    except Exception:
        pass

    def _read_value(obj, *names):
        for name in names:
            if not hasattr(obj, name):
                continue
            value = getattr(obj, name)
            try:
                value = value() if callable(value) else value
            except TypeError:
                continue
            if value is not None:
                return value
        return None

    left = _read_value(bounds, "left", "x1", "xmin", "minX", "minx")
    top = _read_value(bounds, "top", "y1", "ymin", "minY", "miny")
    right = _read_value(bounds, "right", "x2", "xmax", "maxX", "maxx")
    bottom = _read_value(bounds, "bottom", "y2", "ymax", "maxY", "maxy")
    if None not in (left, top, right, bottom):
        return tuple(int(v) for v in (left, top, right, bottom))

    return None


def _find_houdini_main_window() -> Optional[QtWidgets.QWidget]:
    """Return the top-level Houdini main window widget."""
    app = QtWidgets.QApplication.instance()
    if app is None:
        return None

    # Prefer explicit Houdini main window helpers when available.
    try:
        import hou.qt as hqt
        win = hqt.mainWindow()
        if win:
            return win
    except Exception:
        pass

    try:
        active = app.activeWindow()
        if active and active.isVisible():
            return active
    except Exception:
        pass

    # Prefer hou.qt helper if available (H19+)
    try:
        import hou.qt as hqt
        win = hqt.mainWindow()
        if win and win.isVisible():
            return win
    except Exception:
        pass

    # Fallback: walk top-level widgets, score Houdini-looking windows first
    def _score(widget):
        try:
            title = (widget.windowTitle() or "").lower()
        except Exception:
            title = ""
        try:
            obj = (widget.objectName() or "").lower()
        except Exception:
            obj = ""
        score = 0
        if widget.isVisible():
            score += 10
        if widget.width() > 600 and widget.height() > 400:
            score += 5
        if "houdini" in title or "houdini" in obj:
            score += 20
        if "scene" in title or "viewer" in title or "scene" in obj or "viewer" in obj:
            score += 8
        return score

    candidates = [w for w in app.topLevelWidgets() if w.width() > 300 and w.height() > 200]
    if not candidates:
        return None
    return sorted(candidates, key=_score, reverse=True)[0]


def _find_scene_viewer_widget() -> Optional[QtWidgets.QWidget]:
    """Best-effort lookup for the visible Scene Viewer widget."""
    app = QtWidgets.QApplication.instance()
    if app is None:
        return None

    candidates = []
    for w in app.allWidgets():
        try:
            if not w.isVisible():
                continue
            cls = w.metaObject().className().lower()
            obj = (w.objectName() or "").lower()
            title = ""
            try:
                title = (w.windowTitle() or "").lower()
            except Exception:
                pass
            if any(
                token in cls or token in obj or token in title
                for token in ("sceneviewer", "scene viewer", "viewport", "glview", "glviewport")
            ):
                candidates.append(w)
        except Exception:
            continue
    if not candidates:
        return None
    return sorted(candidates, key=lambda w: w.width() * w.height(), reverse=True)[0]


def _is_scene_viewer_widget(widget: QtWidgets.QWidget) -> bool:
    """Return True only for widgets that identify as a Scene Viewer/viewport."""
    try:
        cls = widget.metaObject().className().lower()
    except Exception:
        cls = ""
    try:
        obj = (widget.objectName() or "").lower()
    except Exception:
        obj = ""
    try:
        title = (widget.windowTitle() or "").lower()
    except Exception:
        title = ""
    text = " ".join([cls, obj, title])
    negative = ("chat", "message", "conversation", "houdinimind", "panel")
    positive = ("sceneviewer", "scene viewer", "viewport", "glview", "glviewport")
    return any(token in text for token in positive) and not any(
        token in text for token in negative
    )


def _widget_for_pane(pane_tab) -> Optional[QtWidgets.QWidget]:
    """
    Try to find the Qt widget that owns a Houdini PaneTab.
    Works by matching the pane's screen rectangle against QWidget geometries.
    """
    try:
        # H20+ exposes paneTab.qtParentWidget()
        if hasattr(pane_tab, "qtParentWidget"):
            w = pane_tab.qtParentWidget()
            if w is not None and _is_scene_viewer_widget(w):
                return w
    except Exception:
        pass

    try:
        pane_type_name = pane_tab.type().name().lower()
    except Exception:
        pane_type_name = ""

    if pane_type_name == "sceneviewer":
        widget = _find_scene_viewer_widget()
        if widget is not None:
            return widget

    # Geometry-matching fallback: get pane global position from hou
    try:
        bounds = _extract_screen_rect(pane_tab.screenBounds())
        if not bounds:
            return None
        target_rect = QtCore.QRect(bounds[0], bounds[1], bounds[2] - bounds[0], bounds[3] - bounds[1])

        app = QtWidgets.QApplication.instance()
        for w in app.allWidgets():
            if not w.isVisible():
                continue
            gr = w.geometry()
            gp = w.mapToGlobal(QtCore.QPoint(0, 0))
            global_rect = QtCore.QRect(gp.x(), gp.y(), gr.width(), gr.height())
            if global_rect == target_rect:
                return w
    except Exception:
        pass

    return None


def _grab_widget(widget: QtWidgets.QWidget, scale: float = 1.0) -> Optional[str]:
    """Grab a widget, optionally downscale, return base64 PNG."""
    try:
        pixmap = widget.grab()
        if pixmap is None or pixmap.isNull():
            pixmap = QtGui.QPixmap(widget.size())
            pixmap.fill(QtCore.Qt.GlobalColor.transparent)
            try:
                widget.render(pixmap)
            except Exception:
                pass
        if scale != 1.0:
            new_w = int(pixmap.width() * scale)
            new_h = int(pixmap.height() * scale)
            pixmap = pixmap.scaled(
                new_w, new_h,
                QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                QtCore.Qt.TransformationMode.SmoothTransformation,
            )
        return _pixmap_to_b64(pixmap)
    except Exception as e:
        print(f"[HoudiniMind Vision] grab_widget error: {e}")
        return None


def _grab_screen_rect(x: int, y: int, w: int, h: int) -> Optional[str]:
    """Grab an absolute screen rectangle using QScreen."""
    try:
        app = QtWidgets.QApplication.instance()
        screen = app.primaryScreen() if app else None
        if screen is None and app is not None:
            center = QtCore.QPoint(int(x + w / 2), int(y + h / 2))
            screen = app.screenAt(center)
        if screen is None:
            return None
        pixmap = screen.grabWindow(0, x, y, w, h)
        if pixmap is None or pixmap.isNull():
            return None
        return _pixmap_to_b64(pixmap)
    except Exception as e:
        print(f"[HoudiniMind Vision] grab_screen_rect error: {e}")
        return None


def _flipbook_viewport(viewer, scale: float = 0.75) -> Optional[str]:
    """
    Capture the Scene Viewer via Houdini flipbook.
    This is the most reliable path for actual 3D viewport contents.
    """
    try:
        viewport = viewer.curViewport()
        if viewport is None:
            return None

        # Make a best-effort attempt to bring the viewer forward.
        for method_name in ("setIsCurrentTab", "setCurrent", "setFocus", "raise_"):
            try:
                method = getattr(viewer, method_name, None)
                if callable(method):
                    try:
                        method()
                    except TypeError:
                        method(True)
            except Exception:
                pass

        flip_settings = viewer.flipbookSettings().stash()
        import tempfile

        tmp_path = os.path.join(
            tempfile.gettempdir(), "hmind_viewport_capture.png"
        ).replace("\\", "/")
        flip_settings.output(tmp_path)
        flip_settings.frameRange((hou.frame(), hou.frame()))
        if hasattr(flip_settings, "outputToMPlay"):
            flip_settings.outputToMPlay(False)

        viewer.flipbook(viewport, flip_settings)

        # Poll briefly — flipbook sometimes returns before the file is flushed.
        import time as _time
        for _ in range(10):
            if os.path.exists(tmp_path):
                break
            _time.sleep(0.1)
        else:
            return None

        pixmap = QtGui.QPixmap(tmp_path)
        if pixmap.isNull():
            return None
        if scale != 1.0:
            new_w = int(pixmap.width() * scale)
            new_h = int(pixmap.height() * scale)
            pixmap = pixmap.scaled(
                new_w,
                new_h,
                QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                QtCore.Qt.TransformationMode.SmoothTransformation,
            )

        b64_str = _pixmap_to_b64(pixmap)
        try:
            os.remove(tmp_path)
        except Exception:
            pass
        return b64_str
    except Exception as e:
        print(f"[HoudiniMind Vision] flipbook_viewport error: {e}")
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def capture_network_editor(scale: float = 0.75, node_path: str = None) -> Optional[str]:
    """
    Capture the Network Editor pane, optionally framing a specific node.
    Returns base64 PNG string, or None if unavailable.
    """
    if not HOU_AVAILABLE:
        return None
    try:
        pane = hou.ui.paneTabOfType(hou.paneTabType.NetworkEditor)
        if pane is None:
            return None

        # Framing logic: if node_path is provided, focus the editor there
        if node_path:
            node = hou.node(node_path)
            if node:
                parent = node.parent()
                if parent:
                    pane.setPwd(parent)
                node.setSelected(True, clear_all_selected=True)
                pane.homeToSelection()
        
        widget = _widget_for_pane(pane)
        if widget:
            return _grab_widget(widget, scale=scale)

        # Screen-rect fallback
        bounds = _extract_screen_rect(pane.screenBounds())
        if not bounds:
            return None
        return _grab_screen_rect(bounds[0], bounds[1], bounds[2] - bounds[0], bounds[3] - bounds[1])
    except Exception as e:
        print(f"[HoudiniMind Vision] capture_network_editor error: {e}")
        return None


def _frame_viewport(viewer) -> None:
    """
    Frame all objects in the viewport (equivalent to pressing 'F').
    Runs before every capture so geometry is never cropped or off-screen.
    Silently no-ops if the viewer or viewport is unavailable.
    """
    try:
        viewport = viewer.curViewport()
        if viewport is None:
            return
        viewport.frameAll()
        # Force a UI repaint so the new framing is visible in the grab
        try:
            import hou
            hou.ui.triggerUpdate()
        except Exception:
            pass
    except Exception as e:
        print(f"[HoudiniMind Vision] frameAll error (non-fatal): {e}")


def capture_viewport(scale: float = 0.75) -> Optional[str]:
    """
    Capture the 3-D Scene Viewer (viewport) pane.

    Validation-grade path uses Houdini flipbook first. Widget/screen grabs are
    fallbacks only because they can accidentally capture surrounding UI panels.

    Returns base64 PNG string, or None if unavailable.
    """
    if not HOU_AVAILABLE:
        return None
    try:
        desktop = hou.ui.curDesktop()
        viewer = desktop.paneTabOfType(hou.paneTabType.SceneViewer)
        if not viewer:
            return None

        # Prefer the actual viewport render over Qt/screen grabs. This is
        # slower but avoids feeding chat-panel screenshots into visual QA.
        _frame_viewport(viewer)
        b64 = _flipbook_viewport(viewer, scale=scale)
        if b64:
            return b64

        # Fallback: grab an explicitly identifiable Scene Viewer widget.
        widget = _widget_for_pane(viewer)
        if widget:
            b64 = _grab_widget(widget, scale=scale)
            if b64:
                return b64

        # Last fallback: exact pane rectangle. This may still fail in detached
        # pane layouts, but is safer than a main-window capture.
        bounds = _extract_screen_rect(viewer.screenBounds())
        if bounds:
            b64 = _grab_screen_rect(
                bounds[0], bounds[1], bounds[2] - bounds[0], bounds[3] - bounds[1]
            )
            if b64:
                return b64

        # Final non-invasive fallback: grab the visible Scene Viewer widget if
        # it exists but the pane lookup failed above.
        widget = _find_scene_viewer_widget()
        if widget is not None:
            b64 = _grab_widget(widget, scale=scale)
            if b64:
                return b64

        # Do not fall back to the whole main window for viewport captures:
        # that can capture the chat panel and create false visual evidence.
        return None
    except Exception as e:
        print(f"[HoudiniMind Vision] capture_viewport error: {e}")
        return None


def capture_main_window(scale: float = 0.5) -> Optional[str]:
    """
    Capture the full Houdini main window as a fallback.
    Useful when pane-specific capture fails.
    """
    if not HOU_AVAILABLE:
        return None
    try:
        win = _find_houdini_main_window()
        if win is None:
            return None
        return _grab_widget(win, scale=scale)
    except Exception as e:
        print(f"[HoudiniMind Vision] capture_main_window error: {e}")
        return None


def capture_both(scale: float = 0.75) -> dict:
    """
    Capture both panes.
    Returns dict: { "network_editor": b64|None, "viewport": b64|None }
    Falls back to main window if both specific captures fail.
    """
    ne = capture_network_editor(scale=scale)
    vp = capture_viewport(scale=scale)

    # If both pane-specific grabs failed, grab the whole window
    if ne is None and vp is None:
        fallback = capture_main_window(scale=0.5)
        return {"network_editor": None, "viewport": None, "main_window_fallback": fallback}

    return {"network_editor": ne, "viewport": vp}


def b64_to_data_url(b64: str) -> str:
    """Convert raw base64 PNG string to a data-URL (for Qt image display)."""
    return f"data:image/png;base64,{b64}"
