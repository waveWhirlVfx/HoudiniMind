# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
"""
HoudiniMind — Vision & Scene Analysis Tools
Screenshot, render, and documentation search tools.
"""

import base64
import os
import re
import urllib.parse
import urllib.request

from . import _core as core


def capture_pane(
    pane_type: str = "viewport", node_path: str | None = None, scale: float = 0.75
) -> dict:
    """Capture a screenshot of a Houdini pane (viewport or network)."""
    try:
        core._require_hou()
        from houdinimind.bridge.viewport_capture import (
            capture_network_editor,
            capture_viewport,
        )

        if pane_type == "viewport":
            b64 = capture_viewport(scale=scale)
        elif pane_type == "network":
            b64 = capture_network_editor(scale=scale, node_path=node_path)
        else:
            return core._err(f"Unknown pane type: {pane_type}. Use 'viewport' or 'network'.")

        if not b64:
            return core._err(f"Failed to capture {pane_type}. Ensure the pane is visible.")

        return core._ok(
            {"image_b64": b64, "pane_type": pane_type},
            message=f"Captured {pane_type} screenshot.",
        )
    except Exception as e:
        return core._err(str(e))


def render_scene_view(
    orthographic: bool = False,
    rotation: list | None = None,
    render_engine: str = "opengl",
    karma_engine: str = "cpu",
) -> dict:
    """Advanced render tool: sets up a camera rig and renders the scene."""
    if rotation is None:
        rotation = [0, 90, 0]
    try:
        core._require_hou()
        from houdinimind.bridge.render_tools import render_single_view

        filepath = render_single_view(
            orthographic=orthographic,
            rotation=tuple(rotation),
            render_engine=render_engine,
            karma_engine=karma_engine,
        )

        if not filepath or not os.path.exists(filepath):
            return core._err("Render failed or output file missing.")

        with open(filepath, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")

        return core._ok(
            {"image_b64": b64, "filepath": filepath},
            message="Render completed successfully.",
        )
    except Exception as e:
        return core._err(str(e))


def render_quad_views(orthographic: bool = True, render_engine: str = "opengl") -> dict:
    """Render Front, Left, Top, and Perspective views in one call."""
    try:
        core._require_hou()
        from houdinimind.bridge.render_tools import render_quad_view

        filepaths = render_quad_view(orthographic=orthographic, render_engine=render_engine)
        results = []
        for fp in filepaths:
            if os.path.exists(fp):
                with open(fp, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("utf-8")
                    results.append({"image_b64": b64, "filepath": fp})

        return core._ok({"renders": results}, message=f"Rendered {len(results)} views.")
    except Exception as e:
        return core._err(str(e))


def render_with_camera(camera_path: str, render_engine: str = "opengl") -> dict:
    """Render using a specific camera node in the scene."""
    try:
        core._require_hou()
        from houdinimind.bridge.render_tools import render_specific_camera

        filepath = render_specific_camera(camera_path, render_engine=render_engine)
        if not filepath or not os.path.exists(filepath):
            return core._err(f"Render with camera {camera_path} failed.")

        with open(filepath, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")

        return core._ok(
            {"image_b64": b64, "filepath": filepath},
            message=f"Rendered using camera {camera_path}",
        )
    except Exception as e:
        return core._err(str(e))


def search_docs(query: str) -> dict:
    """Search the official SideFX Houdini documentation."""
    try:
        import ssl

        search_q = f"site:sidefx.com {query}"
        encoded_q = urllib.parse.quote(search_q)
        url = f"https://duckduckgo.com/html/?q={encoded_q}"

        headers = {"User-Agent": "Mozilla/5.0"}
        req = urllib.request.Request(url, headers=headers)

        # Houdini's bundled Python on macOS often lacks the system trust store.
        # Use certifi's bundle when present, fall back to the default context,
        # and finally degrade to unverified rather than failing the search.
        try:
            import certifi

            ctx = ssl.create_default_context(cafile=certifi.where())
        except Exception:
            ctx = ssl.create_default_context()
        try:
            response = urllib.request.urlopen(req, timeout=10, context=ctx)
        except ssl.SSLCertVerificationError:
            response = urllib.request.urlopen(
                req, timeout=10, context=ssl._create_unverified_context()
            )
        with response:
            html = response.read().decode("utf-8")

        links = re.findall(r'class="result__a" href="([^"]+)">([^<]+)</a>', html)
        snippets = re.findall(r'class="result__snippet">([^<]+)</a>', html)

        results = []
        for i in range(min(len(links), 3)):
            results.append(
                {
                    "title": links[i][1],
                    "url": links[i][0],
                    "snippet": snippets[i] if i < len(snippets) else "",
                }
            )

        if not results:
            return core._err("No documentation matches found.")

        return core._ok(
            {"query": query, "results": results},
            message=f"Found {len(results)} doc matches.",
        )
    except Exception as e:
        return core._err(f"Search failed: {e}")
