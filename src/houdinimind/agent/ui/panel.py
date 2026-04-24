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

from ._widgets import (
    STYLESHEET,
    ModernStyles,
    HOUDINIMIND_ROOT,
    HOU_AVAILABLE,
    ModelCombo,
    SettingsPanel,
    SmartInput,
    LoadingSpinner,
    MessageBubble,
    ToolCallWidget,
    ToolActivityGroup,
    ImagePreview,
    EmptyStateWidget,
    StatusNoticeWidget,
    FeedbackChip,
    QuickPromptBar,
    ConnectionStatus,
    ErrorBannerWidget,
    DebugLogDialog,
    RecipeBrowserDialog,
    ResearchOptionCard,
    ResearchOptionsWidget,
)

from ._panel import (
    HoudiniMindPanel,
    createInterface,
)
