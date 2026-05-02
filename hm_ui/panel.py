# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
"""
HoudiniMind Panel v7 - Backward-Compatible Re-Export
All widget classes and the HoudiniMindPanel class have been moved to
src/houdinimind/agent/ui/ (_widgets.py and _panel.py).
This file exists for backward compatibility only.
"""

import os
import sys

# Ensure `src/` is on the path so `houdinimind.agent.ui` can be imported
# without requiring `pip install -e .` (which isn't available inside Houdini's
# bundled Python at launch time).
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC_ROOT = os.path.join(_PROJECT_ROOT, "src")
_AGENT_ROOT = _PROJECT_ROOT  # kept for backward-compat consumers
if _SRC_ROOT not in sys.path:
    sys.path.insert(0, _SRC_ROOT)

try:
    # Re-export all widget classes for convenience
    from houdinimind.agent.ui.panel import (
        HOU_AVAILABLE,
        HOUDINIMIND_ROOT,
        STYLESHEET,
        ConnectionStatus,
        DebugLogDialog,
        EmptyStateWidget,
        ErrorBannerWidget,
        FeedbackChip,
        HoudiniMindPanel,
        ImagePreview,
        LoadingSpinner,
        MessageBubble,
        ModelCombo,
        ModernStyles,
        QuickPromptBar,
        RecipeBrowserDialog,
        ResearchOptionCard,
        ResearchOptionsWidget,
        SettingsPanel,
        SmartInput,
        StatusNoticeWidget,
        ToolActivityGroup,
        ToolCallWidget,
        TurnSummaryWidget,
        createInterface,
    )
except ModuleNotFoundError as exc:
    if exc.name != "PySide6":
        raise

    STYLESHEET = ""

    class ModernStyles:
        pass

    HOUDINIMIND_ROOT = _AGENT_ROOT
    HOU_AVAILABLE = False
    ModelCombo = SettingsPanel = SmartInput = LoadingSpinner = MessageBubble = None
    ToolCallWidget = ToolActivityGroup = ImagePreview = EmptyStateWidget = None
    StatusNoticeWidget = FeedbackChip = QuickPromptBar = ConnectionStatus = None
    TurnSummaryWidget = None
    ErrorBannerWidget = DebugLogDialog = RecipeBrowserDialog = None
    ResearchOptionCard = ResearchOptionsWidget = None

    class HoudiniMindPanel:
        @staticmethod
        def _extract_primary_response(result_text: str, scene_diff_text: str = "") -> str:
            text = (result_text or "").strip()
            diff = (scene_diff_text or "").strip()
            if not text:
                return ""
            if diff and diff in text:
                return text.replace(diff, "").strip()
            for marker in ("[PLANNED SCENE DIFF]", "[SCENE DIFF]"):
                idx = text.find(marker)
                if idx >= 0:
                    return text[:idx].strip()
            return text

        @staticmethod
        def _summarize_scene_diff(scene_diff_text: str) -> str:
            diff = (scene_diff_text or "").strip()
            if not diff:
                return "No scene diff recorded yet."
            lines = []
            for raw in diff.splitlines():
                line = raw.strip()
                if not line or line.startswith("["):
                    continue
                lines.append(line.lstrip("- ").strip())
            if not lines:
                return "Scene diff recorded."
            return " • ".join(lines[:3])

        @staticmethod
        def _looks_like_status_message(text: str) -> bool:
            lowered = (text or "").strip().lower()
            if not lowered:
                return False
            markers = [
                "ollama is overloaded",
                "please wait about",
                "ollama unavailable",
                "ollama not reachable",
                "restart ollama",
                "connection error",
                "agent error",
                "task cancellation requested",
            ]
            return any(marker in lowered for marker in markers)

    def createInterface():
        raise RuntimeError("PySide6 is required to create the HoudiniMind panel UI.")


_extract_primary_response = HoudiniMindPanel._extract_primary_response
_summarize_scene_diff = HoudiniMindPanel._summarize_scene_diff
_looks_like_status_message = HoudiniMindPanel._looks_like_status_message
