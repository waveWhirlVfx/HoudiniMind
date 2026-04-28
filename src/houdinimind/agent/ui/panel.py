# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
"""
HoudiniMind Panel v6 - Backward-Compatible Re-Export
All widget classes are in _widgets.py.
The HoudiniMindPanel class is in _panel.py.
"""

from ._panel import HoudiniMindPanel, createInterface
from ._widgets import (
    HOU_AVAILABLE,
    HOUDINIMIND_ROOT,
    STYLESHEET,
    ConnectionStatus,
    DebugLogDialog,
    EmptyStateWidget,
    ErrorBannerWidget,
    FeedbackChip,
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
)

__all__ = [
    "HOUDINIMIND_ROOT",
    "HOU_AVAILABLE",
    "STYLESHEET",
    "ConnectionStatus",
    "DebugLogDialog",
    "EmptyStateWidget",
    "ErrorBannerWidget",
    "FeedbackChip",
    "HoudiniMindPanel",
    "ImagePreview",
    "LoadingSpinner",
    "MessageBubble",
    "ModelCombo",
    "ModernStyles",
    "QuickPromptBar",
    "RecipeBrowserDialog",
    "ResearchOptionCard",
    "ResearchOptionsWidget",
    "SettingsPanel",
    "SmartInput",
    "StatusNoticeWidget",
    "ToolActivityGroup",
    "ToolCallWidget",
    "createInterface",
]
