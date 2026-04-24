# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
"""
Scene tools: backup, scene summary, errors, hip info.
"""

import os
import traceback

from . import _core as core

_ok = core._ok
_err = core._err
_require_hou = core._require_hou
_ensure_parent_exists = core._ensure_parent_exists

try:
    import hou

    HOU_AVAILABLE = core.HOU_AVAILABLE
except ImportError:
    HOU_AVAILABLE = False
    hou = None


def create_backup():
    """Save a timestamped .bak copy of the current hip file."""
    try:
        _require_hou()
        is_untitled = False
        try:
            if hasattr(hou.hipFile, "isUntitled"):
                is_untitled = hou.hipFile.isUntitled()
            else:
                path = hou.hipFile.path()
                is_untitled = path == "untitled.hip" or not os.path.isabs(path)
        except Exception:
            is_untitled = True
        if is_untitled:
            return _err("Backup skipped: No active HIP file saved yet.")
        path = hou.hipFile.saveAsBackup()
        return _ok({"backup_path": path}, message=f"Backup saved: {path}")
    except Exception as e:
        return _err(f"Backup failed (non-fatal): {e}")


def restore_backup(backup_path):
    """Restore the current Houdini session from a previously created backup hip file."""
    try:
        _require_hou()
        if not isinstance(backup_path, str) or not backup_path.strip():
            return _err("backup_path must be a non-empty string")
        resolved = os.path.abspath(
            os.path.expanduser(os.path.expandvars(backup_path.strip()))
        )
        if not os.path.exists(resolved):
            return _err(f"Backup not found: {resolved}")
        hou.hipFile.load(resolved, suppress_save_prompt=True, ignore_load_warnings=True)
        return _ok({"path": resolved}, message=f"Restored backup: {resolved}")
    except Exception as e:
        return _err(str(e))


def get_scene_summary(depth=3):
    """Smart scan of /obj, /stage, /mat, /out — errors-first."""
    try:
        _require_hou()
        from ..scene_observer import SceneObserver
        observer = SceneObserver()
        observer.max_depth = depth
        snapshot = observer.observe()
        
        topology = snapshot.get("topology", [])
        return _ok({"node_count": len(topology), "nodes": topology})
    except Exception:
        return _err(traceback.format_exc())


def get_all_errors(include_warnings=True):
    """Fast triage — returns only nodes with errors or warnings, sorted by severity."""
    try:
        _require_hou()
        from ..scene_observer import SceneObserver
        observer = SceneObserver()
        snapshot = observer.observe()
        
        results = []
        for issue in snapshot.get("issues", []):
            if not include_warnings and issue.get("severity") == "warning":
                continue
            results.append(issue)
            
        results.sort(key=lambda n: (0 if n.get("severity") == "error" else 1, n.get("path")))
        return _ok({"count": len(results), "nodes": results})
    except Exception:
        return _err(traceback.format_exc())


def get_hip_info():
    """Return hip file path, unsaved changes, frame, FPS, frame range, Houdini version."""
    try:
        _require_hou()
        import os as _os

        return _ok(
            {
                "path": hou.hipFile.path(),
                "basename": _os.path.basename(hou.hipFile.path()),
                "has_unsaved_changes": hou.hipFile.hasUnsavedChanges(),
                "current_frame": hou.frame(),
                "fps": hou.fps(),
                "frame_range": (
                    hou.playbar.frameRange()[0],
                    hou.playbar.frameRange()[1],
                ),
                "houdini_version": ".".join(str(v) for v in hou.applicationVersion()),
            }
        )
    except Exception as e:
        return _err(str(e))


def save_hip(increment=False):
    """Save the current hip file. If increment=True, saves to a new version."""
    try:
        _require_hou()
        if increment:
            hou.hipFile.saveAndIncrementFileName()
            path = hou.hipFile.path()
        else:
            path = hou.hipFile.path()
            hou.hipFile.save(path)
        return _ok({"path": path}, message=f"Saved: {path}")
    except Exception as e:
        return _err(str(e))
