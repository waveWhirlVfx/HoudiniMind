# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
"""
HoudiniMind Panel v6
New in v6:
  - Ollama model selector (chat + vision) — live-fetches available models
  - Quick-prompt toolbar (templates for common Houdini tasks)
  - Settings panel (temperature, context window, tool rounds)
  - Token/context usage indicator
  - Clear conversation button
  - Multi-line input (Shift+Enter for newline, Enter to send)
  - Copy-to-clipboard button on every bubble
  - Prompt history (↑/↓ in input box)
  - Connection status indicator with reconnect button
  - Model is now included in chat exports
  - All v5 features preserved
"""

import json
import os
import sys

# Resolve root dynamically so the project works on any machine / any path.
# _widgets.py lives at python/agent/ui/_widgets.py  →  root = project root
HOUDINIMIND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
if HOUDINIMIND_ROOT not in sys.path:
    sys.path.insert(0, HOUDINIMIND_ROOT)

from PySide6 import QtCore, QtGui, QtWidgets

try:
    from ._asr import ASR_MODEL_OPTIONS, list_asr_input_devices
except Exception:
    ASR_MODEL_OPTIONS = [
        ("tiny.en", "Tiny English - fastest"),
        ("base.en", "Base English - balanced"),
        ("small.en", "Small English - more accurate"),
        ("medium.en", "Medium English - best local accuracy"),
    ]

    def list_asr_input_devices():
        return []


try:
    import hou

    HOU_AVAILABLE = True
except ImportError:
    HOU_AVAILABLE = False


# ── Modern UI System ──────────────────────────────────────────────────
class ModernStyles:
    """Design tokens exactly matching Houdini's native UI palette."""

    # Houdini base surfaces — sampled directly from Houdini 20 dark theme
    BG = "#1c1c1c"  # main background (identical to Houdini pane bg)
    BG_ALT = "#222222"  # very slight lift for alternating rows
    PANEL = "#1c1c1c"  # panels sit flush, no elevation
    PANEL_ELEVATED = "#252525"  # hover / slightly raised surface
    PANEL_SOFT = "#181818"  # recessed areas (input bg)
    CHAT_LANE = "#191919"
    ASSISTANT_BUBBLE = "#202020"
    USER_BUBBLE = "#242832"
    CODE_BG = "#121417"
    INLINE_CODE_BG = "#171a1f"
    BORDER = "#2e2e2e"  # standard 1px separator
    BORDER_SOFT = "#282828"  # subtle separator
    # Houdini's own orange-gold accent (toolbar icons, selection)
    ACCENT = "#c8822a"  # Houdini orange
    ACCENT_ALT = "#a86a1e"
    TEXT = "#c8c8c8"  # primary text — exactly Houdini's default
    TEXT_DIM = "#888888"  # secondary / metadata
    TEXT_SUBTLE = "#555555"  # placeholder / disabled

    ACCENT_RESEARCH = "#7aaac8"
    ACCENT_VISION = "#7ab892"
    ACCENT_DANGER = "#c85a5a"
    ACCENT_SUCCESS = "#5aaa78"
    ACCENT_WARN = "#c8a050"

    # Legacy aliases — keep so other code doesn't break
    GLASS_PANEL = f"background: {PANEL}; border: 1px solid {BORDER_SOFT}; border-radius: 0px;"
    BUTTON_PRIMARY = f"""
        QPushButton {{
            background: {ACCENT}; border: none; border-radius: 0px;
            padding: 5px 12px; color: #ffffff; font-weight: bold;
        }}
        QPushButton:hover {{ background: {ACCENT_ALT}; }}
        QPushButton:disabled {{ background: #383838; color: #606060; }}
    """


STYLESHEET = f"""
/* ═══════════════════════════════════════════════════════════════════
   HoudiniMind — stylesheet matched to Houdini 20 dark UI
   Rule: zero border-radius everywhere, flat surfaces, no gradients
   ═══════════════════════════════════════════════════════════════════ */

/* ── Base ─────────────────────────────────────────────────────────── */
QWidget {{
    background: {ModernStyles.BG};
    color: {ModernStyles.TEXT};
    font-family: 'Segoe UI', 'Lucida Grande', sans-serif;
    font-size: 12px;
    border-radius: 0px;
}}
QLabel  {{ background: transparent; border-radius: 0px; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{
    background: {ModernStyles.BG};
    width: 6px;
    border: none;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: #383838;
    border-radius: 0px;
    min-height: 20px;
}}
QScrollBar::handle:vertical:hover {{ background: #505050; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}

/* ── Text inputs ──────────────────────────────────────────────────── */
QTextEdit, QLineEdit {{
    background: {ModernStyles.PANEL_SOFT};
    border: 1px solid {ModernStyles.BORDER_SOFT};
    border-radius: 0px;
    padding: 6px 8px;
    color: {ModernStyles.TEXT};
    selection-background-color: {ModernStyles.ACCENT};
    selection-color: #ffffff;
}}
QTextEdit:focus, QLineEdit:focus {{
    border-color: {ModernStyles.ACCENT};
    background: {ModernStyles.BG};
}}

/* ── Buttons — flat Houdini style ─────────────────────────────────── */
QPushButton {{
    background: {ModernStyles.PANEL_ELEVATED};
    border: 1px solid {ModernStyles.BORDER};
    border-radius: 0px;
    padding: 4px 10px;
    color: {ModernStyles.TEXT_DIM};
    font-weight: 400;
}}
QPushButton:hover {{
    background: #303030;
    color: {ModernStyles.TEXT};
    border-color: #404040;
}}
QPushButton:pressed {{ background: #181818; }}
QPushButton:disabled {{
    background: {ModernStyles.BG};
    color: {ModernStyles.TEXT_SUBTLE};
    border-color: {ModernStyles.BORDER_SOFT};
}}

QToolButton {{
    background: {ModernStyles.PANEL_ELEVATED};
    border: 1px solid {ModernStyles.BORDER};
    border-radius: 0px;
    padding: 4px 8px;
    color: {ModernStyles.TEXT_DIM};
}}
QToolButton:hover {{ background: #303030; color: {ModernStyles.TEXT}; }}
QToolButton:pressed {{ background: #181818; }}
QToolButton::menu-indicator {{ width: 8px; image: none; }}

/* ── Named buttons ────────────────────────────────────────────────── */
QPushButton#send_btn {{
    background: {ModernStyles.ACCENT};
    border: 1px solid {ModernStyles.ACCENT_ALT};
    border-radius: 0px;
    color: #ffffff;
    font-weight: 600;
    font-size: 14px;
    padding: 0px;
}}
QPushButton#send_btn:hover {{ background: #d8922e; border-color: {ModernStyles.ACCENT}; }}
QPushButton#send_btn:pressed {{ background: {ModernStyles.ACCENT_ALT}; }}

QPushButton#mic_btn {{
    background: {ModernStyles.PANEL_ELEVATED};
    border: 1px solid {ModernStyles.BORDER};
    border-radius: 0px;
    color: {ModernStyles.TEXT_DIM};
    font-size: 13px;
    font-weight: 700;
}}
QPushButton#mic_btn:hover {{ background: #303030; color: {ModernStyles.TEXT}; }}
QPushButton#mic_btn:checked {{
    background: #3a2520;
    border-color: {ModernStyles.ACCENT};
    color: {ModernStyles.ACCENT};
}}
QPushButton#mic_btn:disabled {{
    background: #242424;
    border-color: #303030;
    color: #5a5a5a;
}}

QPushButton#stop_btn {{
    background: #5a2020;
    border: 1px solid #883030;
    border-radius: 0px;
    color: #f0b0b0;
    font-weight: 600;
    font-size: 13px;
    padding: 0px;
}}
QPushButton#stop_btn:hover {{ background: #6e2828; }}

QPushButton#research_btn {{
    background: #1e2a36;
    border: 1px solid #2a3c50;
    border-radius: 0px;
    color: {ModernStyles.ACCENT_RESEARCH};
    padding: 4px 10px;
}}
QPushButton#research_btn:hover {{ background: #253444; color: #9ac0d8; }}

QPushButton#autoresearch_btn {{
    background: {ModernStyles.PANEL_ELEVATED};
    border: 1px solid {ModernStyles.BORDER};
    border-radius: 0px;
    color: {ModernStyles.TEXT_DIM};
    font-weight: 400;
    padding: 4px 9px;
}}
QPushButton#autoresearch_btn:hover {{ background: #303030; color: {ModernStyles.TEXT}; }}
QPushButton#autoresearch_btn:checked {{
    background: #3a1a1a;
    border-color: #882020;
    color: #e09090;
}}

QPushButton#attach_btn, QToolButton#icon_btn, QPushButton#icon_btn {{
    min-width: 26px; max-width: 26px;
    min-height: 26px; max-height: 26px;
    padding: 0;
    border-radius: 0px;
    background: {ModernStyles.PANEL_ELEVATED};
    border: 1px solid {ModernStyles.BORDER};
    color: {ModernStyles.TEXT_DIM};
    font-size: 13px;
}}
QPushButton#attach_btn:hover, QToolButton#icon_btn:hover, QPushButton#icon_btn:hover {{
    background: #303030;
    color: {ModernStyles.TEXT};
}}

QPushButton#vision_toggle_btn {{
    min-width: 34px; max-width: 34px;
    min-height: 30px; max-height: 30px;
    padding: 0;
    border-radius: 4px;
    background: {ModernStyles.PANEL_ELEVATED};
    border: 1px solid {ModernStyles.BORDER};
    color: {ModernStyles.TEXT_DIM};
    font-size: 11px;
    font-weight: 700;
}}
QPushButton#vision_toggle_btn:hover {{
    background: #303030;
    color: {ModernStyles.TEXT};
}}
QPushButton#vision_toggle_btn:checked {{
    background: #203025;
    border-color: #3e6848;
    color: {ModernStyles.ACCENT_SUCCESS};
}}

QPushButton#fast_toggle_btn {{
    min-width: 52px; max-width: 52px;
    min-height: 30px; max-height: 30px;
    padding: 0;
    border-radius: 4px;
    background: {ModernStyles.PANEL_ELEVATED};
    border: 1px solid {ModernStyles.BORDER};
    color: {ModernStyles.TEXT_DIM};
    font-size: 11px;
    font-weight: 700;
}}
QPushButton#fast_toggle_btn:hover {{
    background: #303030;
    color: {ModernStyles.TEXT};
}}
QPushButton#fast_toggle_btn:checked {{
    background: #3a3020;
    border-color: #8a6428;
    color: {ModernStyles.ACCENT_WARN};
}}

QPushButton#ghost_btn, QToolButton#ghost_btn {{
    background: transparent;
    border: 1px solid {ModernStyles.BORDER_SOFT};
    border-radius: 0px;
    color: {ModernStyles.TEXT_DIM};
    padding: 4px 10px;
}}
QPushButton#ghost_btn:hover, QToolButton#ghost_btn:hover {{
    background: {ModernStyles.PANEL_ELEVATED};
    color: {ModernStyles.TEXT};
    border-color: {ModernStyles.BORDER};
}}

/* ── Accept / Reject ──────────────────────────────────────────────── */
QPushButton#accept_btn {{
    background: #1a3020;
    border: 1px solid #2a5030;
    border-radius: 0px;
    color: {ModernStyles.ACCENT_SUCCESS};
    font-size: 11px;
    font-weight: 700;
    padding: 0px;
}}
QPushButton#accept_btn:hover {{ background: #203828; border-color: #3a6840; }}
QPushButton#accept_btn:disabled {{
    background: {ModernStyles.PANEL_ELEVATED};
    color: {ModernStyles.TEXT_SUBTLE};
    border-color: {ModernStyles.BORDER_SOFT};
}}

QPushButton#reject_btn {{
    background: transparent;
    border: 1px solid #502020;
    border-radius: 0px;
    color: {ModernStyles.ACCENT_DANGER};
    font-size: 11px;
    font-weight: 700;
    padding: 0px;
}}
QPushButton#reject_btn:hover {{ background: #2a1010; border-color: #883030; }}
QPushButton#reject_btn:disabled {{
    background: transparent;
    color: {ModernStyles.TEXT_SUBTLE};
    border-color: {ModernStyles.BORDER_SOFT};
}}

/* ── Labels ───────────────────────────────────────────────────────── */
QLabel#title_lbl {{
    font-weight: 600;
    font-size: 12px;
    color: {ModernStyles.TEXT};
    letter-spacing: 0px;
}}
QLabel#header_meta_chip {{
    background: transparent;
    color: {ModernStyles.TEXT_SUBTLE};
    font-size: 12px;
    padding: 0;
}}
QLabel#composer_mode_chip {{
    background: transparent;
    color: {ModernStyles.TEXT_SUBTLE};
    font-size: 10px;
    padding: 2px 0;
}}
QLabel#progress_chip {{
    background: #252525;
    color: {ModernStyles.ACCENT};
    border: 1px solid {ModernStyles.BORDER};
    border-radius: 0px;
    padding: 1px 6px;
    font-size: 10px;
    font-weight: 600;
}}
QLabel#token_bar {{
    color: {ModernStyles.TEXT_SUBTLE};
    font-size: 10px;
    font-family: 'Consolas', 'Courier New', monospace;
}}
QLabel#section_title {{
    color: {ModernStyles.TEXT_SUBTLE};
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.4px;
}}
QLabel#header_meta  {{ color: {ModernStyles.TEXT_SUBTLE}; font-size: 10px; }}
QLabel#empty_state_title   {{ color: {ModernStyles.TEXT}; font-size: 13px; font-weight: 600; }}
QLabel#empty_state_subtitle {{ color: {ModernStyles.TEXT_DIM}; font-size: 11px; }}
QLabel#composer_hint {{ color: {ModernStyles.TEXT_SUBTLE}; font-size: 10px; }}
QLabel#feedback_chip {{
    background: #1e2e1e;
    color: {ModernStyles.ACCENT_SUCCESS};
    border: 1px solid #2a4a2a;
    border-radius: 0px;
    padding: 2px 6px;
    font-size: 10px;
    font-weight: 600;
}}
QLabel#feedback_chip_reject {{
    background: #2e1e1e;
    color: {ModernStyles.ACCENT_DANGER};
    border: 1px solid #4a2a2a;
    border-radius: 0px;
    padding: 2px 6px;
    font-size: 10px;
    font-weight: 600;
}}

/* ── Panels & frames ──────────────────────────────────────────────── */
QFrame#top_details_panel {{ background: transparent; border: none; }}
QFrame#chat_lane         {{ background: transparent; border: none; }}
QFrame#chat_empty_state {{
    background: {ModernStyles.CHAT_LANE};
    border: 1px solid {ModernStyles.BORDER_SOFT};
    border-radius: 6px;
}}
QFrame#model_bar {{
    background: {ModernStyles.BG_ALT};
    border: 1px solid {ModernStyles.BORDER_SOFT};
    border-radius: 0px;
    padding: 2px 0;
}}
QFrame#status_notice {{
    background: {ModernStyles.BG_ALT};
    border: 1px solid {ModernStyles.BORDER_SOFT};
    border-radius: 0px;
}}
QWidget#bubble_footer_bar {{ background: transparent; }}

/* ── Composer shell — flat inset input area ───────────────────────── */
QFrame#composer_shell {{
    background: {ModernStyles.PANEL_ELEVATED};
    border: 1px solid #3a3a3a;
    border-radius: 6px;
}}
QFrame#composer_shell:focus-within {{
    border-color: {ModernStyles.ACCENT};
}}

/* ── Tabs ─────────────────────────────────────────────────────────── */
QTabWidget::pane {{
    border: 1px solid {ModernStyles.BORDER_SOFT};
    border-radius: 0px;
    background: {ModernStyles.PANEL};
}}
QTabBar::tab {{
    background: {ModernStyles.BG_ALT};
    color: {ModernStyles.TEXT_DIM};
    padding: 4px 10px;
    margin-right: 1px;
    border: 1px solid {ModernStyles.BORDER_SOFT};
    border-bottom: none;
    border-radius: 0px;
}}
QTabBar::tab:selected {{
    background: {ModernStyles.PANEL};
    color: {ModernStyles.TEXT};
    border-bottom: 2px solid {ModernStyles.ACCENT};
}}
QTabBar::tab:hover {{ background: #2a2a2a; color: {ModernStyles.TEXT}; }}

/* ── Mode buttons ─────────────────────────────────────────────────── */
QPushButton#mode_btn {{
    background: transparent;
    border: none;
    border-radius: 0px;
    color: {ModernStyles.TEXT_DIM};
    padding: 3px 7px;
}}
QPushButton#mode_btn:hover {{ background: {ModernStyles.PANEL_ELEVATED}; color: {ModernStyles.TEXT}; }}
QPushButton#mode_btn:checked {{
    background: {ModernStyles.PANEL_ELEVATED};
    color: {ModernStyles.ACCENT};
    border-bottom: 2px solid {ModernStyles.ACCENT};
    font-weight: 600;
}}

QPushButton#empty_prompt_btn {{
    background: #232323;
    border: 1px solid {ModernStyles.BORDER};
    border-left: 2px solid {ModernStyles.ACCENT};
    border-radius: 4px;
    color: {ModernStyles.TEXT};
    font-size: 11px;
    font-weight: 500;
    padding: 9px 12px;
    text-align: left;
    min-height: 38px;
}}
QPushButton#empty_prompt_btn:hover {{
    background: #2c2c2c;
    color: #ffffff;
    border-color: {ModernStyles.ACCENT};
    border-left: 2px solid {ModernStyles.ACCENT};
}}

QLabel#agent_context_note {{
    color: {ModernStyles.TEXT_DIM};
    font-size: 10px;
}}
/* ── Combos ───────────────────────────────────────────────────────── */
QComboBox {{
    background: {ModernStyles.PANEL_SOFT};
    border: 1px solid {ModernStyles.BORDER_SOFT};
    border-radius: 0px;
    padding: 3px 7px;
    color: {ModernStyles.TEXT};
}}
QComboBox::drop-down {{ border: none; width: 12px; }}
QComboBox QAbstractItemView {{
    background: {ModernStyles.BG_ALT};
    border: 1px solid {ModernStyles.BORDER};
    selection-background-color: {ModernStyles.ACCENT};
    selection-color: #ffffff;
    border-radius: 0px;
}}
QComboBox:hover {{ border-color: #404040; }}
QComboBox:focus {{ border-color: {ModernStyles.ACCENT}; }}

QGroupBox {{
    border: 1px solid {ModernStyles.BORDER_SOFT};
    border-radius: 0px;
    margin-top: 10px;
    font-weight: 600;
    font-size: 10px;
}}
QGroupBox::title {{
    color: {ModernStyles.TEXT_DIM};
    subcontrol-position: top left;
    left: 8px;
    padding: 0 3px;
}}

/* ── Typing indicator ─────────────────────────────────────────────── */
/* typing_dot styles are set inline in TypingIndicator._tick() */

/* ── Menu ─────────────────────────────────────────────────────────── */
QMenu {{
    background: {ModernStyles.BG_ALT};
    border: 1px solid {ModernStyles.BORDER};
    border-radius: 0px;
    padding: 2px 0;
    color: {ModernStyles.TEXT};
}}
QMenu::item {{ padding: 4px 20px 4px 12px; }}
QMenu::item:selected {{ background: {ModernStyles.ACCENT}; color: #ffffff; }}
QMenu::separator {{ height: 1px; background: {ModernStyles.BORDER}; margin: 2px 0; }}
"""

# Quick-prompt templates for common Houdini tasks
QUICK_PROMPTS = [
    (
        "💥 Pyro",
        "Create a pyro fire and smoke simulation with a sphere emitter using pyrosource, pyrosolver, and pyro shader",
    ),
    (
        "🌊 FLIP",
        "Set up a FLIP fluid simulation in a box container with gravity and surface tension",
    ),
    (
        "🌿 Scatter",
        "Scatter 5000 instances of the selected object on a grid using copy to points with random scale and rotation via VEX",
    ),
    (
        "⚡ VEX Rand",
        "Write a VEX wrangle to randomise point colour (@Cd), scale (@pscale), and orientation (@orient) using noise",
    ),
    (
        "🔗 Constraints",
        "Create a constraint network for a rigid body sim — glue all pieces with strength 1000",
    ),
    (
        "📷 Camera DOF",
        "Create a camera with DOF enabled, focal length 50mm, focused on the selected node bounding box centre",
    ),
    (
        "🔁 For-Each",
        "Build a for-each loop that processes each connected piece separately and merges results",
    ),
    (
        "🌀 Vellum",
        "Set up a Vellum cloth simulation with constraints, colliders, and a solver",
    ),
    (
        "🗺 UV Unwrap",
        "Unwrap UVs on the selected geo using UV Flatten with seams along hard edges",
    ),
    (
        "🎨 MatX",
        "Create a MaterialX principled shader with roughness, metallic, and base colour parameters",
    ),
    (
        "🛌 Bed Asset",
        "Create a procedural bed asset with master controls, frame, and mattress using create_bed_controls",
    ),
    (
        "🧪 Pillow Sim",
        "Set up a realistic vellum pillow with pressure and strut constraints for the selected geometry",
    ),
    (
        "🧵 Fabric Look",
        "Perform automated fabric lookdev: UV unwrap (UV Flatten) and principled shading with fabric presets",
    ),
]


# ══════════════════════════════════════════════════════════════════════
#  Model Selector Combo
# ══════════════════════════════════════════════════════════════════════


class ModelCombo(QtWidgets.QComboBox):
    """ComboBox that can be populated from Ollama /api/tags."""

    def __init__(self, placeholder: str = "Select model…", parent=None):
        super().__init__(parent)
        self._placeholder = placeholder
        self.setEditable(True)
        self.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
        self.addItem(placeholder)
        self.setMinimumWidth(150)

    def populate(self, models: list, current: str = ""):
        self.blockSignals(True)
        self.clear()
        if not models:
            self.addItem("(no models found)")
            if current:
                self.addItem(current)
                self.setCurrentText(current)
        else:
            for m in models:
                self.addItem(m)
            idx = self.findText(current)
            if idx >= 0:
                self.setCurrentIndex(idx)
            else:
                if current:
                    self.addItem(current)
                    self.setCurrentText(current)
                else:
                    self.setCurrentIndex(0)
        self.blockSignals(False)

    def current_model(self) -> str:
        t = self.currentText()
        if t in ("(no models found)", self._placeholder, ""):
            return ""
        return t


# ══════════════════════════════════════════════════════════════════════
#  Settings Panel
# ══════════════════════════════════════════════════════════════════════


class SettingsPanel(QtWidgets.QFrame):
    settings_changed = QtCore.Signal(dict)
    doctor_requested = QtCore.Signal()

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("settings_panel")
        self.setStyleSheet(
            f"QFrame#settings_panel {{ background: {ModernStyles.PANEL}; border: 1px solid {ModernStyles.BORDER_SOFT}; border-radius: 0px; }}"
        )
        self.setVisible(False)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 14)
        root.setSpacing(10)

        title_row = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("Settings")
        title.setStyleSheet(f"font-weight: 700; font-size: 12px; color: {ModernStyles.TEXT};")
        title_row.addWidget(title)
        title_row.addStretch()
        self.doctor_btn = QtWidgets.QPushButton("Health Check")
        self.doctor_btn.setObjectName("ghost_btn")
        self.doctor_btn.setToolTip("Run startup, model, RAG, memory, Houdini, and MCP checks")
        self.doctor_btn.clicked.connect(self.doctor_requested.emit)
        title_row.addWidget(self.doctor_btn)
        root.addLayout(title_row)

        self.settings_search_edit = QtWidgets.QLineEdit()
        self.settings_search_edit.setPlaceholderText("Search settings")
        self.settings_search_edit.textChanged.connect(self._filter_sections)
        root.addWidget(self.settings_search_edit)

        self.settings_sections = QtWidgets.QToolBox()
        root.addWidget(self.settings_sections)
        self._section_widgets = []

        models_box = QtWidgets.QGroupBox("Models")
        models_layout = QtWidgets.QVBoxLayout(models_box)
        models_layout.setContentsMargins(12, 14, 12, 12)
        models_layout.setSpacing(8)

        model_row = QtWidgets.QHBoxLayout()
        model_row.setSpacing(8)
        for attr, label_text, tip in [
            ("chat_model_combo", "Chat", "Ollama model for chat and tool-calling"),
            ("vision_model_combo", "Vision", "Ollama model for image analysis"),
        ]:
            col = QtWidgets.QVBoxLayout()
            col.setSpacing(4)
            label = QtWidgets.QLabel(label_text)
            label.setStyleSheet(
                f"color: {ModernStyles.TEXT_SUBTLE}; font-size: 10px; font-weight: 600;"
            )
            combo = ModelCombo(f"Select {label_text.lower()} model…")
            combo.setToolTip(tip)
            setattr(self, attr, combo)
            col.addWidget(label)
            col.addWidget(combo)
            model_row.addLayout(col, stretch=1)
        self.refresh_models_btn = QtWidgets.QToolButton()
        self.refresh_models_btn.setObjectName("icon_btn")
        self.refresh_models_btn.setText("⟳")
        self.refresh_models_btn.setToolTip("Refresh models from Ollama")
        model_row.addWidget(self.refresh_models_btn, 0, QtCore.Qt.AlignBottom)
        models_layout.addLayout(model_row)

        self.model_status_lbl = QtWidgets.QLabel("Model status will appear here.")
        self.model_status_lbl.setWordWrap(True)
        self.model_status_lbl.setStyleSheet(f"color: {ModernStyles.TEXT_DIM}; font-size: 10px;")
        models_layout.addWidget(self.model_status_lbl)
        self.settings_sections.addItem(models_box, "Models")
        self._section_widgets.append((models_box, "models chat vision backend ollama nvidia"))

        speech_box = QtWidgets.QGroupBox("Speech")
        speech_layout = QtWidgets.QVBoxLayout(speech_box)
        speech_layout.setContentsMargins(12, 14, 12, 12)
        speech_layout.setSpacing(8)

        asr_row = QtWidgets.QHBoxLayout()
        asr_row.setSpacing(8)
        asr_col = QtWidgets.QVBoxLayout()
        asr_col.setSpacing(4)
        asr_label = QtWidgets.QLabel("Speech")
        asr_label.setStyleSheet(
            f"color: {ModernStyles.TEXT_SUBTLE}; font-size: 10px; font-weight: 600;"
        )
        self.asr_model_combo = QtWidgets.QComboBox()
        self.asr_model_combo.setToolTip(
            "Automatic speech recognition model. Larger models are more accurate but slower."
        )
        current_asr = str(config.get("asr_model", "base.en") or "base.en")
        for model_id, label_text in ASR_MODEL_OPTIONS:
            self.asr_model_combo.addItem(label_text, model_id)
        idx = self.asr_model_combo.findData(current_asr)
        self.asr_model_combo.setCurrentIndex(idx if idx >= 0 else 1)
        self.asr_model_combo.currentIndexChanged.connect(self._emit)
        asr_col.addWidget(asr_label)
        asr_col.addWidget(self.asr_model_combo)
        asr_row.addLayout(asr_col, stretch=1)
        speech_layout.addLayout(asr_row)

        mic_row = QtWidgets.QHBoxLayout()
        mic_row.setSpacing(6)
        mic_label = QtWidgets.QLabel("Mic")
        mic_label.setStyleSheet(
            f"color: {ModernStyles.TEXT_SUBTLE}; font-size: 10px; font-weight: 600;"
        )
        self.asr_input_combo = QtWidgets.QComboBox()
        self.asr_input_combo.setToolTip(
            "Microphone input device. Auto prefers a real built-in microphone over virtual loopback devices."
        )
        self._populate_asr_input_devices(config)
        self.asr_input_combo.currentIndexChanged.connect(self._emit)
        mic_row.addWidget(mic_label)
        mic_row.addWidget(self.asr_input_combo, stretch=1)
        speech_layout.addLayout(mic_row)
        self.settings_sections.addItem(speech_box, "Speech")
        self._section_widgets.append((speech_box, "speech asr mic microphone voice input"))

        runtime_box = QtWidgets.QGroupBox("Runtime")
        grid = QtWidgets.QFormLayout(runtime_box)
        grid.setContentsMargins(12, 14, 12, 12)
        grid.setSpacing(8)
        grid.setLabelAlignment(QtCore.Qt.AlignRight)

        # Backend
        self.backend_combo = QtWidgets.QComboBox()
        self.backend_combo.addItem("Ollama", "ollama")
        self.backend_combo.addItem("NVIDIA NIM", "nvidia")
        backend_value = str(config.get("backend", "ollama") or "ollama").strip().lower()
        backend_index = max(0, self.backend_combo.findData(backend_value))
        self.backend_combo.setCurrentIndex(backend_index)
        grid.addRow("Backend:", self.backend_combo)

        # Temperature
        temp_row = QtWidgets.QHBoxLayout()
        self.temp_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.temp_slider.setRange(0, 100)
        self.temp_slider.setValue(int(config.get("temperature", 0.3) * 100))
        self.temp_lbl = QtWidgets.QLabel(f"{config.get('temperature', 0.3):.2f}")
        self.temp_lbl.setFixedWidth(32)
        self.temp_lbl.setStyleSheet(
            f"color: {ModernStyles.ACCENT}; font-family: monospace; font-size: 10px;"
        )
        self.temp_slider.valueChanged.connect(
            lambda v: (self.temp_lbl.setText(f"{v / 100:.2f}"), self._emit())
        )
        temp_row.addWidget(self.temp_slider)
        temp_row.addWidget(self.temp_lbl)
        grid.addRow("Temperature:", temp_row)

        # Context window
        self.ctx_spin = QtWidgets.QSpinBox()
        self.ctx_spin.setRange(2048, 131072)
        self.ctx_spin.setSingleStep(1024)
        self.ctx_spin.setValue(config.get("context_window", 32768))
        self.ctx_spin.valueChanged.connect(self._emit)
        grid.addRow("Context window:", self.ctx_spin)

        # Max tool rounds
        self.rounds_spin = QtWidgets.QSpinBox()
        self.rounds_spin.setRange(1, 500)
        self.rounds_spin.setValue(config.get("max_tool_rounds", 16))
        self.rounds_spin.valueChanged.connect(self._emit)
        grid.addRow("Max tool rounds:", self.rounds_spin)

        # Ollama URL
        self.url_edit = QtWidgets.QLineEdit(config.get("ollama_url", "http://localhost:11434"))
        self.url_edit.editingFinished.connect(self._emit)
        self.url_label = QtWidgets.QLabel("Ollama URL:")
        grid.addRow(self.url_label, self.url_edit)

        # OpenAI-compatible cloud API settings (NVIDIA NIM)
        self.openai_url_edit = QtWidgets.QLineEdit(
            config.get("openai_base_url", "https://integrate.api.nvidia.com/v1")
        )
        self.openai_url_edit.setToolTip("OpenAI-compatible API base URL.")
        self.openai_url_edit.editingFinished.connect(self._emit)
        self.openai_url_label = QtWidgets.QLabel("API URL:")
        grid.addRow(self.openai_url_label, self.openai_url_edit)

        # SECURITY: Load API key from secure credential store, not plaintext config
        _initial_api_key = ""
        try:
            from houdinimind.agent.credential_store import CredentialStore

            _cred = CredentialStore(config.get("data_dir", ""))
            _initial_api_key = _cred.get_api_key()
        except Exception:
            _initial_api_key = config.get("api_key", "")
        self.api_key_edit = QtWidgets.QLineEdit(_initial_api_key)
        self.api_key_edit.setEchoMode(QtWidgets.QLineEdit.Password)
        self.api_key_edit.setPlaceholderText("Paste NVIDIA API key")
        self.api_key_edit.setToolTip(
            "Bearer API key used for NVIDIA NIM/OpenAI-compatible requests.\n"
            "Stored securely in macOS Keychain / OS credential manager."
        )
        self.api_key_edit.editingFinished.connect(self._emit)
        self.api_key_label = QtWidgets.QLabel("API key:")
        grid.addRow(self.api_key_label, self.api_key_edit)

        self.settings_sections.addItem(runtime_box, "Runtime")
        self._section_widgets.append(
            (
                runtime_box,
                "runtime backend temperature context window max tool rounds url api key nvidia ollama",
            )
        )

        safety_box = QtWidgets.QGroupBox("Scene Safety")
        safety_grid = QtWidgets.QFormLayout(safety_box)
        safety_grid.setContentsMargins(12, 14, 12, 12)
        safety_grid.setSpacing(8)
        safety_grid.setLabelAlignment(QtCore.Qt.AlignRight)

        # Auto-backup
        self.backup_chk = QtWidgets.QCheckBox("Enabled")
        self.backup_chk.setChecked(bool(config.get("auto_backup", False)))
        self.backup_chk.stateChanged.connect(self._emit)
        safety_grid.addRow("Auto-backup:", self.backup_chk)

        # Auto-inject scene
        self.scene_chk = QtWidgets.QCheckBox("Inject scene on every message")
        self.scene_chk.setChecked(config.get("ui", {}).get("auto_inject_scene_on_chat", False))
        self.scene_chk.stateChanged.connect(self._emit)
        safety_grid.addRow("Auto scene:", self.scene_chk)

        # Show tool calls
        self.tools_chk = QtWidgets.QCheckBox("Show tool activity inspector")
        self.tools_chk.setChecked(config.get("ui", {}).get("show_tool_calls", True))
        self.tools_chk.stateChanged.connect(self._emit)
        safety_grid.addRow("Tool display:", self.tools_chk)

        # Network view audit (important for Inspect Network quality)
        self.network_audit_chk = QtWidgets.QCheckBox("Analyze network screenshot + wiring")
        self.network_audit_chk.setChecked(config.get("auto_network_view_checks", True))
        self.network_audit_chk.stateChanged.connect(self._emit)
        safety_grid.addRow("Network Audit:", self.network_audit_chk)

        self.settings_sections.addItem(safety_box, "Scene Safety")
        self._section_widgets.append(
            (safety_box, "scene safety auto backup inject tool display network audit")
        )

        # MCP Server
        mcp_box = QtWidgets.QGroupBox("MCP Server")
        mcp_layout = QtWidgets.QVBoxLayout(mcp_box)
        mcp_layout.setContentsMargins(12, 14, 12, 12)
        mcp_layout.setSpacing(8)

        mcp_row = QtWidgets.QHBoxLayout()
        mcp_row.setSpacing(8)

        mcp_port_col = QtWidgets.QVBoxLayout()
        mcp_port_col.setSpacing(4)
        mcp_port_label = QtWidgets.QLabel("Port")
        mcp_port_label.setStyleSheet(
            f"color: {ModernStyles.TEXT_SUBTLE}; font-size: 10px; font-weight: 600;"
        )
        self.mcp_port_spin = QtWidgets.QSpinBox()
        self.mcp_port_spin.setRange(1024, 65535)
        self.mcp_port_spin.setValue(config.get("mcp_port", 9876))
        self.mcp_port_spin.valueChanged.connect(self._emit)
        mcp_port_col.addWidget(mcp_port_label)
        mcp_port_col.addWidget(self.mcp_port_spin)
        mcp_row.addLayout(mcp_port_col, stretch=1)

        mcp_status_col = QtWidgets.QVBoxLayout()
        mcp_status_col.setSpacing(4)
        mcp_status_label = QtWidgets.QLabel("Status")
        mcp_status_label.setStyleSheet(
            f"color: {ModernStyles.TEXT_SUBTLE}; font-size: 10px; font-weight: 600;"
        )
        self.mcp_status_indicator = QtWidgets.QLabel("● Stopped")
        self.mcp_status_indicator.setStyleSheet(
            f"color: {ModernStyles.TEXT_DIM}; font-size: 11px; font-weight: 600;"
        )
        mcp_status_col.addWidget(mcp_status_label)
        mcp_status_col.addWidget(self.mcp_status_indicator)
        mcp_row.addLayout(mcp_status_col, stretch=1)

        self.mcp_toggle_btn = QtWidgets.QPushButton("Start Server")
        self.mcp_toggle_btn.setFixedHeight(30)
        self.mcp_toggle_btn.setMinimumWidth(100)
        self.mcp_toggle_btn.setCursor(QtCore.Qt.PointingHandCursor)
        mcp_row.addWidget(self.mcp_toggle_btn, 0, QtCore.Qt.AlignBottom)

        mcp_layout.addLayout(mcp_row)
        self.settings_sections.addItem(mcp_box, "MCP")
        self._section_widgets.append((mcp_box, "mcp server port status start stop"))
        self.backend_combo.currentIndexChanged.connect(self._on_backend_changed)
        self._sync_backend_fields()

    def _filter_sections(self, query: str) -> None:
        needle = str(query or "").strip().lower()
        first_match = -1
        for index, (widget, keywords) in enumerate(self._section_widgets):
            haystack = f"{self.settings_sections.itemText(index)} {keywords}".lower()
            visible = not needle or needle in haystack
            widget.setVisible(visible)
            self.settings_sections.setItemEnabled(index, visible)
            if visible and first_match < 0:
                first_match = index
        if first_match >= 0:
            self.settings_sections.setCurrentIndex(first_match)

    def set_model_status(self, text: str, tone: str = "neutral") -> None:
        color = {
            "ok": ModernStyles.ACCENT_SUCCESS,
            "warn": ModernStyles.ACCENT_WARN,
            "error": ModernStyles.ACCENT_DANGER,
        }.get(tone, ModernStyles.TEXT_DIM)
        self.model_status_lbl.setText(text)
        self.model_status_lbl.setStyleSheet(f"color: {color}; font-size: 10px;")

    def load_config(self, config: dict) -> None:
        """Refresh controls from a config loaded after the panel was built."""
        config = config or {}
        controls = [
            self.chat_model_combo,
            self.vision_model_combo,
            self.asr_model_combo,
            self.asr_input_combo,
            self.backend_combo,
            self.temp_slider,
            self.ctx_spin,
            self.rounds_spin,
            self.url_edit,
            self.openai_url_edit,
            self.api_key_edit,
            self.backup_chk,
            self.scene_chk,
            self.tools_chk,
            self.network_audit_chk,
            self.mcp_port_spin,
        ]
        for control in controls:
            control.blockSignals(True)
        try:
            chat_model = str(config.get("model", "") or "")
            vision_model = str(config.get("vision_model", "") or "")
            if chat_model:
                self.chat_model_combo.setCurrentText(chat_model)
            if vision_model:
                self.vision_model_combo.setCurrentText(vision_model)

            backend_value = str(config.get("backend", "ollama") or "ollama").strip().lower()
            backend_index = self.backend_combo.findData(backend_value)
            self.backend_combo.setCurrentIndex(backend_index if backend_index >= 0 else 0)

            self.temp_slider.setValue(int(float(config.get("temperature", 0.3)) * 100))
            self.temp_lbl.setText(f"{self.temp_slider.value() / 100:.2f}")
            self.ctx_spin.setValue(int(config.get("context_window", 32768)))
            self.rounds_spin.setValue(int(config.get("max_tool_rounds", 16)))
            self.url_edit.setText(str(config.get("ollama_url", "http://localhost:11434") or ""))
            self.openai_url_edit.setText(
                str(config.get("openai_base_url", "https://integrate.api.nvidia.com/v1") or "")
            )

            api_key = ""
            try:
                from houdinimind.agent.credential_store import CredentialStore

                api_key = CredentialStore(config.get("data_dir", "")).get_api_key()
            except Exception:
                api_key = str(config.get("api_key", "") or "")
            self.api_key_edit.setText(api_key)

            asr_model = str(config.get("asr_model", "base.en") or "base.en")
            asr_idx = self.asr_model_combo.findData(asr_model)
            self.asr_model_combo.setCurrentIndex(asr_idx if asr_idx >= 0 else 0)
            self._populate_asr_input_devices(config)
            self.backup_chk.setChecked(bool(config.get("auto_backup", False)))
            ui_cfg = config.get("ui", {}) or {}
            self.scene_chk.setChecked(bool(ui_cfg.get("auto_inject_scene_on_chat", False)))
            self.tools_chk.setChecked(bool(ui_cfg.get("show_tool_calls", True)))
            self.network_audit_chk.setChecked(bool(config.get("auto_network_view_checks", True)))
            self.mcp_port_spin.setValue(int(config.get("mcp_port", 9876)))
            self._sync_backend_fields()
        finally:
            for control in controls:
                control.blockSignals(False)

    def _current_backend(self) -> str:
        return str(self.backend_combo.currentData() or "ollama")

    def _on_backend_changed(self, _index):
        self._sync_backend_fields()
        self._emit()

    def _sync_backend_fields(self):
        is_nvidia = self._current_backend() == "nvidia"
        self.url_label.setVisible(not is_nvidia)
        self.url_edit.setVisible(not is_nvidia)
        self.openai_url_label.setVisible(is_nvidia)
        self.openai_url_edit.setVisible(is_nvidia)
        self.api_key_label.setVisible(is_nvidia)
        self.api_key_edit.setVisible(is_nvidia)
        if is_nvidia:
            chat_model = self.chat_model_combo.current_model()
            vision_model = self.vision_model_combo.current_model()
            if not chat_model or "/" not in chat_model:
                self.chat_model_combo.setCurrentText("deepseek-ai/deepseek-v4-pro")
            if not vision_model or "/" not in vision_model:
                self.vision_model_combo.setCurrentText("deepseek-ai/deepseek-v4-pro")

    def _populate_asr_input_devices(self, config: dict):
        selected = str(config.get("asr_input_device", "auto") or "auto")
        self.asr_input_combo.clear()
        self.asr_input_combo.addItem("Auto (prefer built-in microphone)", "auto")
        for device in list_asr_input_devices():
            self.asr_input_combo.addItem(device["label"], device["name"])
        idx = self.asr_input_combo.findData(selected)
        if idx < 0 and selected.lower() != "auto":
            for i in range(self.asr_input_combo.count()):
                data = str(self.asr_input_combo.itemData(i) or "")
                if selected.lower() in data.lower():
                    idx = i
                    break
        self.asr_input_combo.setCurrentIndex(idx if idx >= 0 else 0)

    def _emit(self):
        self.settings_changed.emit(
            {
                "backend": self._current_backend(),
                "temperature": self.temp_slider.value() / 100,
                "context_window": self.ctx_spin.value(),
                "max_tool_rounds": self.rounds_spin.value(),
                "auto_backup": self.backup_chk.isChecked(),
                "auto_backup_on_save": False,
                "turn_checkpoints": self.backup_chk.isChecked(),
                "auto_network_view_checks": self.network_audit_chk.isChecked(),
                "vision_enabled": True,
                "ollama_url": self.url_edit.text().strip(),
                "openai_base_url": self.openai_url_edit.text().strip(),
                "api_key": self.api_key_edit.text().strip(),
                "asr_model": self.asr_model_combo.currentData() or "base.en",
                "asr_input_device": self.asr_input_combo.currentData() or "auto",
                "mcp_port": self.mcp_port_spin.value(),
                "ui": {
                    "auto_inject_scene_on_chat": self.scene_chk.isChecked(),
                    "show_tool_calls": self.tools_chk.isChecked(),
                },
            }
        )

    def toggle(self):
        self.setVisible(not self.isVisible())


# ══════════════════════════════════════════════════════════════════════
#  Smart Multi-line Input with History
# ══════════════════════════════════════════════════════════════════════


class SmartInput(QtWidgets.QTextEdit):
    """
    Multi-line input:
      Enter       → send
      Shift+Enter → newline
      ↑ / ↓       → navigate history (single-line only)
    """

    send_requested = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMaximumHeight(180)
        self.setMinimumHeight(58)
        self.setPlaceholderText("Ask HoudiniMind to build, debug, explain, or write VEX...")
        self._history = []
        self._hist_idx = -1
        self._hist_draft = ""
        self.document().contentsChanged.connect(self._auto_resize)

    def _auto_resize(self):
        doc_h = int(self.document().size().height())
        self.setFixedHeight(max(58, min(doc_h + 18, 180)))

    def keyPressEvent(self, event):
        if event.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            if not (event.modifiers() & QtCore.Qt.ShiftModifier):
                self.send_requested.emit()
                return
        if event.key() == QtCore.Qt.Key_Up and "\n" not in self.toPlainText():
            if self._history:
                if self._hist_idx == -1:
                    self._hist_draft = self.toPlainText()
                    self._hist_idx = len(self._history) - 1
                elif self._hist_idx > 0:
                    self._hist_idx -= 1
                self.setPlainText(self._history[self._hist_idx])
                self._move_end()
            return
        if event.key() == QtCore.Qt.Key_Down and "\n" not in self.toPlainText():
            if self._hist_idx >= 0:
                if self._hist_idx < len(self._history) - 1:
                    self._hist_idx += 1
                    self.setPlainText(self._history[self._hist_idx])
                else:
                    self._hist_idx = -1
                    self.setPlainText(self._hist_draft)
                self._move_end()
            return
        super().keyPressEvent(event)

    def _move_end(self):
        c = self.textCursor()
        c.movePosition(QtGui.QTextCursor.End)
        self.setTextCursor(c)

    def push_history(self, text: str):
        if text and (not self._history or self._history[-1] != text):
            self._history.append(text)
            if len(self._history) > 100:
                self._history.pop(0)
        self._hist_idx = -1
        self._hist_draft = ""

    def get_text(self) -> str:
        return self.toPlainText().strip()

    def clear_text(self):
        self.clear()
        self._hist_idx = -1


# ══════════════════════════════════════════════════════════════════════
#  Widgets
# ══════════════════════════════════════════════════════════════════════
#  Widgets
# ══════════════════════════════════════════════════════════════════════


class LoadingSpinner(QtWidgets.QLabel):
    # ASCII rotation — renders correctly in every font
    def __init__(self, parent=None):
        super().__init__(parent)
        self.frames = ["|", "/", "-", "\\"]
        self.idx = 0
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._spin)
        self.timer.setInterval(120)
        self.setText("")
        self.setStyleSheet(f"color: {ModernStyles.ACCENT}; font-size: 12px; font-weight: bold;")
        self.setFixedWidth(14)

    def start(self):
        self.idx = 0
        self.setText(self.frames[0])
        self.setVisible(True)
        self.timer.start()

    def stop(self):
        self.timer.stop()
        self.setText("")
        self.setVisible(False)  # hide so empty text doesn't look like a separator

    def _spin(self):
        self.idx = (self.idx + 1) % len(self.frames)
        self.setText(self.frames[self.idx])


class AgentStatusRow(QtWidgets.QWidget):
    """Inline status row shown below the agent bubble while a tool is running.
    Shows: [spinner] <status text>   elapsed
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 8, 2)
        layout.setSpacing(6)

        self._spinner = LoadingSpinner(self)
        self._spinner.setFixedWidth(16)
        layout.addWidget(self._spinner)

        self._label = QtWidgets.QLabel("")
        self._label.setStyleSheet(
            f"color: {ModernStyles.TEXT_SUBTLE}; font-size: 11px; "
            f"background: transparent; border: none;"
        )
        self._label.setWordWrap(False)
        layout.addWidget(self._label)
        layout.addStretch()

        self._start_ts = 0.0
        self._tick_timer = QtCore.QTimer(self)
        self._tick_timer.setInterval(100)
        self._tick_timer.timeout.connect(self._tick)

    def set_status(self, text: str):
        """Update the status text and start spinner if not already running."""
        self._label.setText(text)
        if not self._tick_timer.isActive():
            import time as _t

            self._start_ts = _t.monotonic()
            self._spinner.start()
            self._tick_timer.start()
        self.setVisible(True)

    def clear(self):
        """Stop spinner and hide."""
        self._spinner.stop()
        self._tick_timer.stop()
        self.setVisible(False)
        self._label.setText("")

    def _tick(self):
        pass


class CompactMessageLabel(QtWidgets.QLabel):
    """QLabel with stable wrapped height inside scroll layouts."""

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        w = max(40, int(width or self.width() or 400))
        text = self.text() or ""
        if not text:
            return max(1, self.fontMetrics().height())
        if self.textFormat() == QtCore.Qt.PlainText:
            flags = QtCore.Qt.TextWordWrap | QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop
            rect = self.fontMetrics().boundingRect(QtCore.QRect(0, 0, w, 200000), int(flags), text)
            return max(self.fontMetrics().height(), rect.height() + 2)
        doc = QtGui.QTextDocument()
        doc.setDefaultFont(self.font())
        doc.setHtml(text)
        doc.setTextWidth(float(w))
        return max(self.fontMetrics().height(), int(doc.size().height()) + 2)

    def sizeHint(self) -> QtCore.QSize:
        w = max(120, int(self.width() or 400))
        return QtCore.QSize(w, self.heightForWidth(w))

    def minimumSizeHint(self) -> QtCore.QSize:
        return QtCore.QSize(40, max(1, self.fontMetrics().height()))


# ══════════════════════════════════════════════════════════════════════
#  Markdown → HTML renderer  (no external deps — pure regex)
# ══════════════════════════════════════════════════════════════════════


def _md_to_html(text: str) -> str:
    """
    Convert Markdown to HTML suitable for QLabel rich text.
    Tries to use the robust `markdown` library with `pygments` if available.
    Falls back to a custom parser if not.
    """
    try:
        import markdown

        extensions = ["fenced_code", "tables", "sane_lists"]
        extension_configs = {}
        try:
            import pygments

            extensions.append("codehilite")
            extension_configs["codehilite"] = {
                "noclasses": True,
                "style": "monokai",
                "cssclass": "highlight",
            }
        except ImportError:
            pass

        html_out = markdown.markdown(
            text, extensions=extensions, extension_configs=extension_configs
        )

        # Inject modern styles into generated html tags
        html_out = html_out.replace(
            "<code>",
            f'<code style="background:{ModernStyles.INLINE_CODE_BG}; color:{ModernStyles.ACCENT}; font-family:Consolas,monospace; font-size:11px; padding:1px 4px">',
        )
        html_out = html_out.replace(
            "<pre>",
            f'<pre style="background:{ModernStyles.CODE_BG}; border:1px solid {ModernStyles.BORDER_SOFT}; border-left:3px solid {ModernStyles.ACCENT}; border-radius:4px; padding:8px 10px; margin:7px 0; font-family:Consolas,monospace; font-size:11px; line-height:140%; color:{ModernStyles.TEXT}; white-space:pre-wrap;">',
        )
        html_out = html_out.replace(
            "<table>",
            f'<table style="border-collapse: collapse; margin: 8px 0; border: 1px solid {ModernStyles.BORDER};">',
        )
        html_out = html_out.replace(
            "<th>",
            f'<th style="border: 1px solid {ModernStyles.BORDER}; padding: 4px 8px; background-color: {ModernStyles.BG_ALT};">',
        )
        html_out = html_out.replace(
            "<td>", f'<td style="border: 1px solid {ModernStyles.BORDER}; padding: 4px 8px;">'
        )
        html_out = html_out.replace("<a>", '<a style="color:#8fb8d8;text-decoration:none">')

        return html_out
    except ImportError:
        pass

    import html
    import re

    lines = text.split("\n")
    out = []
    in_code = False
    code_buf = []
    code_lang = ""
    in_list = False

    def parse_fence_info(info: str) -> tuple[str, str]:
        raw = str(info or "").strip()
        if not raw:
            return "", ""
        known_langs = (
            "python",
            "py",
            "vex",
            "vfl",
            "cpp",
            "c++",
            "c",
            "json",
            "bash",
            "sh",
            "text",
            "hscript",
        )
        lower = raw.lower()
        for lang in known_langs:
            if lower == lang:
                return lang, ""
            if lower.startswith(lang + "#"):
                return lang, raw[len(lang) :].strip()
            if lower.startswith(lang + " "):
                return lang, raw[len(lang) :].strip()
        if raw.startswith("#"):
            return "", raw
        first, _, rest = raw.partition(" ")
        if re.fullmatch(r"[A-Za-z0-9_+.-]{1,24}", first):
            return first, rest.strip()
        return "", raw

    def render_code_block(lang: str, code_lines: list[str]) -> str:
        # LLMs occasionally emit fences with dozens of blank lines or malformed
        # info strings. Trim only outer whitespace so intentional indentation is
        # preserved but empty panels do not consume the whole chat lane.
        while code_lines and not code_lines[0].strip():
            code_lines.pop(0)
        while code_lines and not code_lines[-1].strip():
            code_lines.pop()
        if not code_lines:
            return ""
        code_text = html.escape("\n".join(code_lines))
        lang_label = (
            f'<div style="color:{ModernStyles.TEXT_SUBTLE};font-size:10px;'
            f'margin-bottom:4px">{html.escape(lang)}</div>'
            if lang
            else ""
        )
        return (
            f'<pre style="background:{ModernStyles.CODE_BG};border:1px solid {ModernStyles.BORDER_SOFT};'
            f"border-left:3px solid {ModernStyles.ACCENT};border-radius:4px;"
            f"padding:8px 10px;margin:7px 0;font-family:Consolas,monospace;font-size:11px;"
            f'line-height:140%;color:{ModernStyles.TEXT};white-space:pre-wrap;">'
            f"{lang_label}{code_text}</pre>"
        )

    def flush_list():
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    i = 0
    while i < len(lines):
        line = lines[i]

        # Fenced code block
        if line.strip().startswith("```"):
            if not in_code:
                flush_list()
                in_code = True
                code_lang, first_code_line = parse_fence_info(line.strip()[3:].strip())
                code_buf = []
                if first_code_line:
                    code_buf.append(first_code_line)
            else:
                in_code = False
                rendered = render_code_block(code_lang, code_buf)
                if rendered:
                    out.append(rendered)
                code_buf = []
                code_lang = ""
            i += 1
            continue

        if in_code:
            code_buf.append(line)
            i += 1
            continue

        raw = line

        # Horizontal rule
        if re.match(r"^[-*_]{3,}\s*$", raw):
            flush_list()
            out.append(
                f'<hr style="border:none;border-top:1px solid {ModernStyles.BORDER};margin:6px 0">'
            )
            i += 1
            continue

        # Headings
        m = re.match(r"^(#{1,3})\s+(.*)", raw)
        if m:
            flush_list()
            level = len(m.group(1))
            sizes = {1: "14px", 2: "13px", 3: "12px"}
            content = _inline_md(m.group(2))
            out.append(
                f'<p style="margin:6px 0 2px 0;font-size:{sizes[level]};'
                f'font-weight:700;color:{ModernStyles.TEXT}">{content}</p>'
            )
            i += 1
            continue

        # Bullet list
        m = re.match(r"^(\s*)[-*+]\s+(.*)", raw)
        if m:
            if not in_list:
                out.append('<ul style="margin:4px 0 5px 0;padding-left:18px">')
                in_list = True
            content = _inline_md(m.group(2))
            out.append(f'<li style="margin:2px 0">{content}</li>')
            i += 1
            continue

        # Numbered list
        m = re.match(r"^(\s*)\d+\.\s+(.*)", raw)
        if m:
            flush_list()
            content = _inline_md(m.group(2))
            out.append(f'<p style="margin:2px 0;padding-left:16px">{content}</p>')
            i += 1
            continue

        flush_list()

        # Blank line → paragraph break
        if raw.strip() == "":
            out.append("<br>")
            i += 1
            continue

        out.append(f'<p style="margin:2px 0; line-height:145%">{_inline_md(raw)}</p>')
        i += 1

    flush_list()
    if in_code:
        rendered = render_code_block(code_lang, code_buf)
        if rendered:
            out.append(rendered)
    return "".join(out)


def _inline_md(text: str) -> str:
    """Apply inline markdown: bold, italic, inline code, links."""
    import html
    import re

    # Escape HTML first
    text = html.escape(text)
    # Bold+italic ***text***
    text = re.sub(r"\*\*\*(.*?)\*\*\*", r"<b><i>\1</i></b>", text)
    # Bold **text**
    text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", text)
    # Italic *text* or _text_
    text = re.sub(r"\*(.*?)\*", r"<i>\1</i>", text)
    text = re.sub(r"_(.*?)_", r"<i>\1</i>", text)
    # Inline code `code`
    text = re.sub(
        r"`([^`]+)`",
        lambda m: (
            f'<span style="background:{ModernStyles.INLINE_CODE_BG};color:{ModernStyles.ACCENT};'
            f'font-family:Consolas,monospace;font-size:11px;padding:1px 4px">'
            f"{m.group(1)}</span>"
        ),
        text,
    )
    # Links [label](https://...)
    text = re.sub(
        r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
        r'<a style="color:#8fb8d8;text-decoration:none" href="\2">\1</a>',
        text,
    )
    return text


# ══════════════════════════════════════════════════════════════════════
#  Typing Indicator  (3-dot pulse while agent is thinking)
# ══════════════════════════════════════════════════════════════════════


class TypingIndicator(QtWidgets.QFrame):
    """Three animated dots shown while the agent is generating."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        root = QtWidgets.QHBoxLayout(self)
        root.setContentsMargins(12, 8, 12, 8)
        root.setSpacing(6)  # more space so dots don't clip

        self._dots = []
        for _ in range(3):
            d = QtWidgets.QLabel("●")
            # 20×16 gives the font room to render without clipping
            d.setFixedSize(20, 16)
            d.setAlignment(QtCore.Qt.AlignCenter)
            d.setStyleSheet(
                f"color: {ModernStyles.TEXT_SUBTLE}; font-size: 11px; background: transparent; border: none;"
            )
            root.addWidget(d)
            self._dots.append(d)
        root.addStretch()

        self.setStyleSheet(
            f"QFrame {{ background: {ModernStyles.BG}; border-left: 2px solid {ModernStyles.BORDER}; border-radius: 0px; }}"
        )

        self._step = 0
        # Wave: each dot peaks in sequence, faster for a livelier feel
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(300)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self._tick()

    def _tick(self):
        pos = self._step % 3
        for i, d in enumerate(self._dots):
            if i == pos:
                # Active dot: orange, slightly larger
                d.setStyleSheet(
                    f"color: {ModernStyles.ACCENT}; font-size: 13px; background: transparent; border: none;"
                )
            elif i == (pos - 1) % 3:
                # Previous dot: halfway faded
                d.setStyleSheet(
                    f"color: {ModernStyles.TEXT_DIM}; font-size: 11px; background: transparent; border: none;"
                )
            else:
                d.setStyleSheet(
                    f"color: {ModernStyles.TEXT_SUBTLE}; font-size: 10px; background: transparent; border: none;"
                )
        self._step += 1

    def stop(self):
        self._timer.stop()


# ══════════════════════════════════════════════════════════════════════
#  Phase Animation Widget  (shown below agent bubble during each phase)
# ══════════════════════════════════════════════════════════════════════


class PhaseAnimWidget(QtWidgets.QFrame):
    """
    Small animated badge shown below the agent bubble during planning /
    building / verifying.  Uses BMP Unicode only — no emoji fonts needed.

      Planning  → ✎  pen writing: dots cycle  "✎ ·  " → "✎ · ·" → "✎ · · ·"
      Building  → ⚙  gear:        spins clockwise via char swap
      Verifying → ◎  lens:        pulses bright/dim
    """

    _PHASE_CONFIG = {
        "planning": {
            "icon": "\u270e",  # ✎  lower-right pencil
            "label": "Planning",
            "color": ModernStyles.ACCENT,
            "frames": [
                "\u270e  \u00b7      ",
                "\u270e  \u00b7 \u00b7   ",
                "\u270e  \u00b7 \u00b7 \u00b7",
                "\u270e  \u00b7 \u00b7   ",
            ],
            "interval": 350,
        },
        "building": {
            "icon": "\u2699",  # ⚙  gear
            "label": "Building",
            "color": "#7aaa88",
            "frames": ["\u2699", "\u25e6", "\u2022", "\u25e6"],
            "interval": 200,
        },
        "verifying": {
            "icon": "\u2299",  # ⊙  circled dot (lens)
            "label": "Verifying",
            "color": ModernStyles.ACCENT_WARN,
            "frames": ["\u2299", "\u25ce", "\u25cb", "\u25ce"],
            "interval": 300,
        },
    }

    def __init__(self, phase: str = "planning", parent=None):
        super().__init__(parent)
        self._phase = phase
        cfg = self._PHASE_CONFIG.get(phase, self._PHASE_CONFIG["planning"])
        self._frames = cfg["frames"]
        self._color = cfg["color"]
        self._step = 0

        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.setStyleSheet("QFrame { background: transparent; border: none; }")

        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(12, 2, 0, 4)
        row.setSpacing(6)

        self._anim_lbl = QtWidgets.QLabel(self._frames[0])
        self._anim_lbl.setStyleSheet(
            f"color: {self._color}; font-size: 13px; background: transparent; border: none;"
        )
        row.addWidget(self._anim_lbl)

        phase_lbl = QtWidgets.QLabel(cfg["label"])
        phase_lbl.setStyleSheet(
            f"color: {self._color}; font-size: 10px; font-weight: 600; "
            f"background: transparent; border: none; letter-spacing: 0.5px;"
        )
        row.addWidget(phase_lbl)
        row.addStretch()

        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(cfg["interval"])
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _tick(self):
        self._step = (self._step + 1) % len(self._frames)
        self._anim_lbl.setText(self._frames[self._step])

    def stop(self):
        self._timer.stop()


class MessageBubble(QtWidgets.QFrame):
    def __init__(self, role: str, text: str = "", mode: str = "chat", parent=None):
        super().__init__(parent)
        self._role = role
        self._mode = mode
        self._text = text or ""
        self._stream_plain_mode = False
        import datetime as _dt

        self._timestamp = _dt.datetime.now().strftime("%H:%M")
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Maximum)

        root = QtWidgets.QHBoxLayout(self)
        root.setContentsMargins(0, 3, 0, 3)
        root.setSpacing(0)

        self.container = QtWidgets.QFrame()
        # Agent: Expanding — fills the full width like Houdini parameter rows
        # User:  Fixed — capped at 60% via _sync_container_width
        if role == "user":
            self.container.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Maximum)
        else:
            self.container.setSizePolicy(
                QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Maximum
            )

        bg_color = self._get_bubble_bg()
        mode_color = self._get_mode_color()
        border_left = (
            f"border: 1px solid {ModernStyles.BORDER_SOFT}; border-left: 3px solid {mode_color};"
            if role != "user"
            else (
                f"border: 1px solid #343947; "
                f"border-right: 3px solid {ModernStyles.ACCENT_RESEARCH};"
            )
        )
        self.container.setStyleSheet(
            f"QFrame {{ background: {bg_color}; border-radius: 6px; {border_left} }}"
        )

        layout = QtWidgets.QVBoxLayout(self.container)
        layout.setContentsMargins(12, 8, 12, 7)
        layout.setSpacing(5)

        # Mode tag header — only for non-chat agent messages
        self._copy_btn = QtWidgets.QPushButton("⎘")
        self._copy_btn.setFixedSize(22, 20)
        self._copy_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self._copy_btn.setStyleSheet(
            f"border: none; color: {ModernStyles.TEXT_DIM}; font-size: 12px; background: transparent;"
        )
        self._copy_btn.clicked.connect(self._copy)

        hdr = QtWidgets.QHBoxLayout()
        hdr.setSpacing(6)
        role_name = "You" if role == "user" else "HoudiniMind"
        avatar = QtWidgets.QLabel("U" if role == "user" else "HM")
        avatar.setFixedHeight(18)
        avatar.setMinimumWidth(22 if role == "user" else 28)
        avatar.setAlignment(QtCore.Qt.AlignCenter)
        avatar.setStyleSheet(
            f"background: {mode_color if role != 'user' else ModernStyles.ACCENT_RESEARCH}; "
            f"color: #ffffff; border-radius: 3px; font-size: 9px; font-weight: 700; "
            f"padding: 1px 5px;"
        )
        hdr.addWidget(avatar)
        name_lbl = QtWidgets.QLabel(role_name)
        name_lbl.setStyleSheet(
            f"color: {ModernStyles.TEXT_DIM}; font-size: 10px; font-weight: 600; "
            f"background: transparent; border: none;"
        )
        hdr.addWidget(name_lbl)
        if role != "user" and mode != "chat":
            tag = QtWidgets.QLabel(mode.upper())
            tag.setStyleSheet(
                f"color: {mode_color}; font-size: 9px; font-weight: 700; "
                f"background: transparent; border: none; letter-spacing: 0.5px;"
            )
            hdr.addWidget(tag)
        hdr.addStretch()
        layout.addLayout(hdr)

        self._trace_expander_btn = QtWidgets.QPushButton("▶ Show Action Log")
        self._trace_expander_btn.setStyleSheet(
            f"color: {ModernStyles.TEXT_DIM}; font-size: 10px; background: transparent; border: none; text-align: left; padding: 0;"
        )
        self._trace_expander_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self._trace_expander_btn.setVisible(False)
        self._trace_expander_btn.setFixedHeight(16)
        layout.addWidget(self._trace_expander_btn)

        self._trace_container = QtWidgets.QFrame()
        self._trace_container.setVisible(False)
        self._trace_container.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed
        )
        self._trace_container.setStyleSheet(
            f"background: {ModernStyles.PANEL_ELEVATED}; border: 1px solid {ModernStyles.BORDER_SOFT}; border-radius: 4px; padding: 0px;"
        )
        self._trace_layout = QtWidgets.QVBoxLayout(self._trace_container)
        self._trace_layout.setContentsMargins(6, 4, 6, 4)
        self._trace_layout.setSpacing(2)

        self._trace_label = CompactMessageLabel()
        self._trace_label.setStyleSheet(
            f"color: {ModernStyles.TEXT_SUBTLE}; font-size: 10px; background: transparent; border: none; line-height: 140%;"
        )
        self._trace_label.setWordWrap(True)
        self._trace_label.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        _sp_trace = QtWidgets.QSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed
        )
        _sp_trace.setHeightForWidth(True)
        self._trace_label.setSizePolicy(_sp_trace)
        self._trace_label.setMinimumHeight(0)
        self._trace_layout.addWidget(self._trace_label)
        layout.addWidget(self._trace_container)

        self._trace_expanded = False
        self._trace_text = ""
        self._trace_expander_btn.clicked.connect(self._toggle_trace)

        self.text_label = CompactMessageLabel()
        self.text_label.setWordWrap(True)
        self.text_label.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        _sp = QtWidgets.QSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Fixed,
        )
        _sp.setHeightForWidth(True)
        self.text_label.setSizePolicy(_sp)
        self.text_label.setMinimumHeight(0)
        self.text_label.setTextFormat(QtCore.Qt.RichText)
        self.text_label.setOpenExternalLinks(False)
        self.text_label.setTextInteractionFlags(
            QtCore.Qt.TextSelectableByMouse | QtCore.Qt.TextSelectableByKeyboard
        )
        self.text_label.setStyleSheet(
            f"background: transparent; border: none; "
            f"color: {ModernStyles.TEXT if self._role != 'user' else '#dde3ef'}; "
            f"font-size: 12px; line-height: 145%;"
        )
        self._render_text()
        layout.addWidget(self.text_label)

        # Inline progress/status line inside the bubble (single-line)
        self._inline_status_raw = ""
        self._inline_status_lbl = QtWidgets.QLabel("")
        self._inline_status_lbl.setWordWrap(False)
        self._inline_status_lbl.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed
        )
        self._inline_status_lbl.setTextFormat(QtCore.Qt.PlainText)
        self._inline_status_lbl.setStyleSheet(
            f"color: {ModernStyles.TEXT_DIM}; font-size: 10px; background: transparent; border: none;"
        )
        self._inline_status_lbl.setVisible(False)
        layout.addWidget(self._inline_status_lbl)

        self.footer = QtWidgets.QWidget()
        self.footer.setObjectName("bubble_footer_bar")
        self.footer.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.footer_layout = QtWidgets.QHBoxLayout(self.footer)
        self.footer_layout.setContentsMargins(0, 4, 0, 0)
        self.footer_layout.setSpacing(6)
        self.footer.setVisible(False)
        self._footer_extra_widget = None
        layout.addWidget(self.footer)

        # Timestamp — far left
        self._ts_label = QtWidgets.QLabel(self._timestamp)
        self._ts_label.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        self._ts_label.setStyleSheet(
            f"color: {ModernStyles.TEXT_SUBTLE}; font-size: 9px; background: transparent; border: none;"
        )
        self.footer_layout.addWidget(self._ts_label)

        # Timer badge
        self._timer_label = QtWidgets.QLabel()
        self._timer_label.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        self._timer_label.setStyleSheet(
            f"color: {ModernStyles.TEXT_DIM}; font-size: 10px; background: transparent; border: none;"
        )
        self._timer_label.setVisible(False)
        self.footer_layout.addWidget(self._timer_label)
        self.footer_layout.addStretch()

        # Copy-code button — only for agent bubbles with code blocks
        if role != "user":
            self._code_copy_btn = QtWidgets.QPushButton("⎘ code")
            self._code_copy_btn.setFixedHeight(18)
            self._code_copy_btn.setStyleSheet(
                f"border: none; color: {ModernStyles.ACCENT}88; font-size: 10px; "
                f"background: transparent; padding: 0 4px;"
            )
            self._code_copy_btn.setToolTip("Copy all code blocks")
            self._code_copy_btn.setVisible(False)
            self._code_copy_btn.clicked.connect(self._copy_code)
            self.footer_layout.addWidget(self._code_copy_btn)

        # Copy button — always visible in footer
        self._copy_btn.setStyleSheet(
            f"border: none; color: {ModernStyles.TEXT_DIM}55; font-size: 11px; background: transparent;"
        )
        self.footer_layout.addWidget(self._copy_btn)
        self.footer.setVisible(True)

        self._timer_qt = QtCore.QTimer(self)
        self._timer_qt.setInterval(100)  # 100 ms ticks for smooth display
        self._timer_qt.timeout.connect(self._tick_timer)
        self._timer_start_ms: float = 0.0
        self._timer_stopped: bool = False

        if role == "user":
            root.addStretch(1)
            root.addWidget(self.container)
        else:
            root.addWidget(self.container)  # Expanding — fills width automatically

        self._sync_container_width()

    def _toggle_trace(self):
        self._trace_expanded = not self._trace_expanded
        self._trace_container.setVisible(self._trace_expanded)
        self._trace_expander_btn.setText(
            "▼ Hide Action Log" if self._trace_expanded else "▶ Show Action Log"
        )
        self._resize()

    def _get_bubble_bg(self):
        if self._role == "user":
            return ModernStyles.USER_BUBBLE
        return ModernStyles.ASSISTANT_BUBBLE

    def _get_mode_color(self):
        # Houdini-native accent strips — subdued, not garish
        return {
            "research": "#5080a0",
            "vision": "#406850",
            "debug": "#904040",
            "error": ModernStyles.ACCENT_DANGER,
        }.get(self._mode, ModernStyles.ACCENT)  # default: Houdini orange

    def _render_text(self):
        """Render self._text as markdown HTML for agent, plain HTML-escaped for user."""
        import re as _re

        if self._role == "user":
            import html

            self.text_label.setTextFormat(QtCore.Qt.RichText)
            escaped = html.escape(self._text).replace("\n", "<br>")
            self.text_label.setText(
                f'<div style="line-height:145%; color:#dde3ef;">{escaped}</div>'
            )
        else:
            if self._stream_plain_mode:
                self.text_label.setTextFormat(QtCore.Qt.PlainText)
                self.text_label.setText(self._text or "")
                if hasattr(self, "_code_copy_btn"):
                    self._code_copy_btn.setVisible(False)
                self._sync_text_label_height()
                return
            self.text_label.setTextFormat(QtCore.Qt.RichText)
            # Collapse runs of 3+ blank lines down to 2 before rendering
            clean = _re.sub(r"\n{3,}", "\n\n", self._text).strip() if self._text else ""
            self.text_label.setText(_md_to_html(clean) if clean else "")
        # Show/hide code-copy button based on whether text has code blocks
        if hasattr(self, "_code_copy_btn"):
            has_code = "```" in self._text
            self._code_copy_btn.setVisible(has_code)
        self._sync_text_label_height()

    def _sync_text_label_height(self) -> bool:
        if not getattr(self, "text_label", None):
            return False
        width = self.text_label.contentsRect().width()
        if width < 120 and getattr(self, "container", None):
            width = self.container.contentsRect().width() - 4
        if width < 120:
            QtCore.QTimer.singleShot(0, self._sync_text_label_height)
            return False
        height = self.text_label.heightForWidth(width)
        if not (self._text or "").strip():
            height = 0
        height = max(
            0, min(int(height) + 2, 10000)
        )  # Increased from 1200 to 10000 to prevent long bubbles from clipping

        changed = False
        if self.text_label.height() != height:
            self.text_label.setFixedHeight(height)
            changed = True

        if getattr(self, "_trace_expanded", False) and getattr(self, "_trace_label", None):
            t_width = self._trace_label.contentsRect().width()
            if t_width < 120 and getattr(self, "container", None):
                t_width = self.container.contentsRect().width() - 16
            if t_width >= 120:
                t_height = self._trace_label.heightForWidth(t_width)
                if not (self._trace_text or "").strip():
                    t_height = 0
                if self._trace_label.height() != t_height:
                    self._trace_label.setFixedHeight(max(0, min(int(t_height) + 2, 5000)))
                    if hasattr(self, "_trace_container"):
                        self._trace_container.setFixedHeight(max(0, min(int(t_height) + 12, 5010)))
                    changed = True

        if changed:
            self.text_label.updateGeometry()
            if getattr(self, "_trace_label", None):
                self._trace_label.updateGeometry()
            if getattr(self, "container", None):
                self.container.updateGeometry()
            self.updateGeometry()
        return changed

    def _resize(self):
        self._sync_container_width()
        height_changed = self._sync_text_label_height()

        self._refresh_inline_status_text()

        if height_changed:
            p = self.parent()
            while p is not None:
                p.updateGeometry()
                # Stop at the scroll area viewport — no need to go further
                if isinstance(p, QtWidgets.QAbstractScrollArea):
                    break
                p = p.parent()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_container_width()
        self._sync_text_label_height()
        self._refresh_inline_status_text()

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_container_width()
        self._sync_text_label_height()
        self._refresh_inline_status_text()

    def _sync_container_width(self):
        # Agent bubbles are Expanding — they fill width automatically, no override needed
        if self._role != "user":
            return
        # User bubbles: cap at 60% of lane width so they stay right-aligned
        w = self.width()
        if w < 60:
            p = self.parent()
            while p and w < 60:
                w = p.width()
                p = p.parent() if p else None
        lane_width = max(0, w - 18)
        if lane_width < 60:
            return  # not laid out yet — will fire again on showEvent/resizeEvent
        target = min(620, max(180, int(lane_width * 0.68)))
        self.container.setFixedWidth(target)

    def _refresh_inline_status_text(self):
        if not self._inline_status_raw:
            return
        metrics = QtGui.QFontMetrics(self._inline_status_lbl.font())
        max_w = max(120, self.container.contentsRect().width() - 12)
        self._inline_status_lbl.setText(
            metrics.elidedText(
                self._inline_status_raw,
                QtCore.Qt.TextElideMode.ElideRight,
                max_w,
            )
        )

    def set_inline_status(self, text: str, phase: str = "building"):
        cleaned = " ".join(str(text or "").strip().split())
        if not cleaned:
            self.clear_inline_status()
            return
        phase_name = str(phase or "building").strip().lower()
        phase_title = {
            "planning": "Planning",
            "building": "Building",
            "verifying": "Verifying",
        }.get(phase_name, "Building")
        color = {
            "planning": ModernStyles.ACCENT,
            "building": ModernStyles.ACCENT_SUCCESS,
            "verifying": ModernStyles.ACCENT_WARN,
        }.get(phase_name, ModernStyles.ACCENT_SUCCESS)
        self._inline_status_raw = f"\u25cb {phase_title} - {cleaned}"
        self._inline_status_lbl.setStyleSheet(
            f"color: {color}; font-size: 10px; background: transparent; border: none;"
        )
        self._inline_status_lbl.setToolTip(self._inline_status_raw)
        self._refresh_inline_status_text()
        self._inline_status_lbl.setVisible(True)
        self._resize()

    def clear_inline_status(self):
        self._inline_status_raw = ""
        self._inline_status_lbl.setToolTip("")
        self._inline_status_lbl.setText("")
        self._inline_status_lbl.setVisible(False)
        self._resize()

    def set_llm_activity(self, text: str):
        if not text:
            return
        if self._trace_text:
            self._trace_text += "\n" + text
        else:
            self._trace_text = text
            self._trace_expander_btn.setVisible(True)

        lines = self._trace_text.split("\n")
        if len(lines) > 20:
            self._trace_text = "\n".join(lines[-20:])

        self._trace_label.setText(self._trace_text)
        self._resize()

    def clear_llm_activity(self):
        self._trace_text = ""
        self._trace_expander_btn.setVisible(False)
        self._trace_container.setVisible(False)
        self._trace_expanded = False
        self._trace_label.setText("")
        self._resize()

    def append_text(self, chunk: str):
        self._text += chunk
        self._render_text()
        self._resize()

    def set_stream_text(self, text: str):
        self._stream_plain_mode = True
        self._text = text or ""
        self._render_text()
        self._resize()
        # The first few stream updates often arrive before the bubble has a
        # real width, so heightForWidth produces a way-too-tall fixed height.
        # Re-sync after the layout pass settles, so the gap collapses.
        QtCore.QTimer.singleShot(0, self._sync_text_label_height)

    def set_text(self, text: str):
        self._stream_plain_mode = False
        self._text = text or ""
        self._render_text()
        self._resize()

    def text(self) -> str:
        return self._text

    # ── Timer ──────────────────────────────────────────────────────────

    def start_timer(self) -> None:
        """Start the live elapsed-time counter for this bubble."""
        import time as _time

        self._timer_start_ms = _time.monotonic()
        self._timer_stopped = False
        self._timer_label.setText("⏱ 0.0s")
        self._timer_label.setVisible(True)
        self.footer.setVisible(True)
        self._timer_qt.start()

    def stop_timer(self) -> None:
        """Freeze the timer and display the final elapsed time."""
        if self._timer_stopped:
            return
        self._timer_qt.stop()
        self._timer_stopped = True
        import time as _time

        elapsed = _time.monotonic() - self._timer_start_ms
        self._timer_label.setText(f"{elapsed:.1f}s")
        self._timer_label.setStyleSheet(
            f"color: {ModernStyles.TEXT_DIM}88; font-size: 10px; background: transparent; border: none;"
        )

    def _tick_timer(self) -> None:
        if self._timer_stopped:
            return
        import time as _time

        elapsed = _time.monotonic() - self._timer_start_ms
        self._timer_label.setText(f"⏱ {elapsed:.1f}s")

    # ── Footer widget (FeedbackChip etc.) ──────────────────────────────

    def set_footer_widget(self, widget: QtWidgets.QWidget):
        """Add a widget to the right side of the footer (e.g. FeedbackChip).
        Does NOT clear the timer label."""
        if widget is None:
            return
        self._clear_footer_chips()
        widget.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        widget.setMaximumHeight(20)
        insert_at = self.footer_layout.indexOf(getattr(self, "_code_copy_btn", None))
        if insert_at < 0:
            insert_at = self.footer_layout.indexOf(self._copy_btn)
        if insert_at < 0:
            insert_at = self.footer_layout.count()
        self.footer_layout.insertWidget(insert_at, widget)
        self._footer_extra_widget = widget
        self.footer.setVisible(True)

    def clear_footer_widget(self):
        """Remove feedback chips from the footer, keeping the timer intact."""
        self._clear_footer_chips()
        # Keep footer visible if timer is showing
        if not self._timer_label.isVisible():
            self.footer.setVisible(False)

    def _clear_footer_chips(self):
        """Remove only the dynamic feedback widget, preserving footer controls."""
        widget = getattr(self, "_footer_extra_widget", None)
        if widget is None:
            return
        self.footer_layout.removeWidget(widget)
        widget.setParent(None)
        self._footer_extra_widget = None

    def _copy(self):
        QtWidgets.QApplication.clipboard().setText(self._text)

    def _copy_code(self):
        """Extract and copy all fenced code blocks from the message."""
        import re

        blocks = re.findall(r"```[^\n]*\n(.*?)```", self._text, re.DOTALL)
        if blocks:
            QtWidgets.QApplication.clipboard().setText("\n\n".join(blocks).strip())

    def set_viewport_image(self, image_b64: str) -> None:
        """Embed a base64 PNG viewport snapshot inline below the text label."""
        try:
            import base64 as _b64

            raw = _b64.b64decode(image_b64)
            pixmap = QtGui.QPixmap()
            pixmap.loadFromData(raw)
            if pixmap.isNull():
                return
            max_w = min(560, self.container.width() - 28)
            if pixmap.width() > max_w:
                pixmap = pixmap.scaledToWidth(
                    max_w,
                    QtCore.Qt.TransformationMode.SmoothTransformation,
                )
            img_label = QtWidgets.QLabel()
            img_label.setPixmap(pixmap)
            img_label.setAlignment(QtCore.Qt.AlignLeft)
            img_label.setStyleSheet("border: none; background: transparent; margin-top: 6px;")
            # Insert before footer so image appears above the footer bar
            container_layout = self.container.layout()
            footer_index = container_layout.indexOf(self.footer)
            if footer_index >= 0:
                container_layout.insertWidget(footer_index, img_label)
            else:
                container_layout.addWidget(img_label)
            self._resize()
        except Exception:
            pass


class ToolCallWidget(QtWidgets.QFrame):
    """A polished message-style card for a single tool call event."""

    # Human-readable labels for each tool
    _TOOL_LABELS = {
        "create_node": "Create Node",
        "create_node_chain": "Build Node Chain",
        "set_parameter": "Set Parameter",
        "safe_set_parameter": "Set Parameter",
        "connect_nodes": "Connect Nodes",
        "delete_node": "Delete Node",
        "rename_node": "Rename Node",
        "set_display_flag": "Set Display Flag",
        "finalize_sop_network": "Finalize Network",
        "get_scene_summary": "Read Scene",
        "get_node_info": "Inspect Node",
        "get_node_parameters": "Read Parameters",
        "get_geometry_attributes": "Read Geometry",
        "get_all_errors": "Check Errors",
        "get_node_inputs": "Read Connections",
        "inspect_display_output": "Inspect Output",
        "take_viewport_screenshot": "Capture Viewport",
        "clear_scene": "Clear Scene",
        "undo": "Undo",
    }

    # Icon per tool category
    _TOOL_ICONS = {
        "create_node": "◈",
        "create_node_chain": "◈",
        "set_parameter": "⟐",
        "safe_set_parameter": "⟐",
        "connect_nodes": "⇢",
        "delete_node": "✕",
        "set_display_flag": "◉",
        "finalize_sop_network": "✦",
        "get_scene_summary": "◎",
        "get_node_info": "◎",
        "get_node_parameters": "◎",
        "get_geometry_attributes": "◎",
        "get_all_errors": "◎",
        "get_node_inputs": "◎",
        "inspect_display_output": "◎",
        "take_viewport_screenshot": "⬡",
        "clear_scene": "⊘",
    }

    def __init__(self, tool_name: str, args: dict, result: dict, index: int = 0, parent=None):
        super().__init__(parent)
        self._expanded = False
        result.get("status") == "ok"
        is_err = result.get("status") == "error"
        meta = result.get("_meta", {}) or {}
        is_dry = meta.get("dry_run", False)

        # Card background + left accent border
        accent_color = (
            ModernStyles.ACCENT_DANGER
            if is_err
            else (ModernStyles.ACCENT_WARN if is_dry else ModernStyles.ACCENT_SUCCESS)
        )
        self.setObjectName("tool_card")
        self.setStyleSheet(f"""
            QFrame#tool_card {{
                background: {ModernStyles.PANEL_ELEVATED};
                border: none;
                border-left: 2px solid {accent_color};
                border-radius: 0px;
            }}
        """)

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(10, 7, 8, 7)
        outer.setSpacing(0)

        # ── Header row ──────────────────────────────────────────────────
        header = QtWidgets.QHBoxLayout()
        header.setSpacing(8)

        # Index badge
        idx_lbl = QtWidgets.QLabel(str(index))
        idx_lbl.setFixedSize(18, 18)
        idx_lbl.setAlignment(QtCore.Qt.AlignCenter)
        idx_lbl.setStyleSheet(f"""
            background: {ModernStyles.BORDER};
            color: {ModernStyles.TEXT_SUBTLE};
            border-radius: 0px;
            font-size: 9px;
            font-weight: 600;
        """)
        header.addWidget(idx_lbl)

        # Tool icon
        icon_char = self._TOOL_ICONS.get(tool_name, "⬡")
        icon_lbl = QtWidgets.QLabel(icon_char)
        icon_lbl.setStyleSheet(f"color: {accent_color}; font-size: 13px; background: transparent;")
        icon_lbl.setFixedWidth(16)
        header.addWidget(icon_lbl)

        # Tool name (human label)
        label = self._TOOL_LABELS.get(tool_name, tool_name.replace("_", " ").title())
        name_lbl = QtWidgets.QLabel(label)
        name_lbl.setStyleSheet(
            f"color: {ModernStyles.TEXT}; font-size: 12px; font-weight: 600; background: transparent;"
        )
        header.addWidget(name_lbl)

        # DRY badge
        if is_dry:
            dry_lbl = QtWidgets.QLabel("DRY")
            dry_lbl.setStyleSheet(f"""
                background: {ModernStyles.ACCENT_WARN}22;
                color: {ModernStyles.ACCENT_WARN};
                border: 1px solid {ModernStyles.ACCENT_WARN}55;
                border-radius: 0px;
                font-size: 9px;
                font-weight: 600;
                padding: 1px 5px;
            """)
            header.addWidget(dry_lbl)

        header.addStretch()

        # Status pill
        if is_err:
            status_text, status_bg, status_fg = "Failed", "#3a2424", ModernStyles.ACCENT_DANGER
        elif is_dry:
            status_text, status_bg, status_fg = "Dry", "#3a3024", ModernStyles.ACCENT_WARN
        else:
            status_text, status_bg, status_fg = "Done", "#24342a", ModernStyles.ACCENT_SUCCESS
        pill = QtWidgets.QLabel(status_text)
        pill.setStyleSheet(f"""
            background: {status_bg};
            color: {status_fg};
            border-radius: 0px;
            font-size: 9px;
            font-weight: 600;
            padding: 2px 6px;
        """)
        header.addWidget(pill)

        # Expand button
        self.expand_btn = QtWidgets.QPushButton("›")
        self.expand_btn.setFixedSize(20, 20)
        self.expand_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.expand_btn.setStyleSheet(f"""
            QPushButton {{
                border: none;
                background: transparent;
                color: {ModernStyles.TEXT_SUBTLE};
                font-size: 14px;
                font-weight: bold;
            }}
            QPushButton:hover {{ color: {ModernStyles.TEXT}; }}
        """)
        self.expand_btn.clicked.connect(self._toggle)
        header.addWidget(self.expand_btn)

        outer.addLayout(header)

        # ── Summary line ─────────────────────────────────────────────────
        summary = self._make_summary(tool_name, args, result)
        if summary:
            sum_lbl = QtWidgets.QLabel(summary)
            sum_lbl.setStyleSheet(
                f"color: {ModernStyles.TEXT_SUBTLE}; font-size: 11px; "
                f"padding-left: 42px; padding-top: 2px; background: transparent;"
            )
            sum_lbl.setWordWrap(True)
            outer.addWidget(sum_lbl)

        # ── Detail panel (hidden by default) ─────────────────────────────
        self.detail_box = QtWidgets.QTextEdit()
        self.detail_box.setReadOnly(True)
        self.detail_box.setFixedHeight(90)
        self.detail_box.setStyleSheet(f"""
            QTextEdit {{
                background: {ModernStyles.BG};
                border: none;
                border-top: 1px solid {ModernStyles.BORDER_SOFT};
                border-radius: 0px;
                font-family: 'JetBrains Mono', 'Fira Mono', 'Cascadia Code', monospace;
                font-size: 10px;
                color: {ModernStyles.TEXT_DIM};
                padding: 6px 8px;
                margin-top: 6px;
            }}
        """)
        msg = result.get("message", "") or ""
        data = result.get("data") or {}
        detail_lines = []
        if msg:
            detail_lines.append(f"msg: {msg}")
        if args:
            detail_lines.append("args: " + json.dumps(args, default=str, indent=2))
        if data:
            detail_lines.append("result: " + json.dumps(data, default=str)[:600])
        self.detail_box.setPlainText("\n".join(detail_lines))
        self.detail_box.setVisible(False)
        outer.addWidget(self.detail_box)

    @staticmethod
    def _make_summary(tool_name: str, args: dict, result: dict) -> str:
        """Generate a short human-readable description of what the tool did."""
        msg = (result.get("message") or "").strip()
        data = result.get("data") or {}
        status = result.get("status", "")

        if tool_name in ("create_node", "create_node_chain"):
            name = args.get("name") or args.get("node_type") or ""
            parent_path = args.get("parent") or args.get("parent_path") or ""
            chain = args.get("chain", [])
            if chain and isinstance(chain, list):
                names = [
                    s.get("name") or s.get("type", "") for s in chain[:4] if isinstance(s, dict)
                ]
                names = [n for n in names if n]
                if names:
                    return f"{', '.join(names)}" + (
                        f"  —  {len(chain)} nodes" if len(chain) > 4 else ""
                    )
            if name and parent_path:
                return f"{name}  in  {parent_path}"
            return name or msg[:80] or ""

        if tool_name in ("set_parameter", "safe_set_parameter"):
            node = args.get("node_path") or args.get("node") or ""
            parm = args.get("parm_name") or args.get("parm") or ""
            val = args.get("value")
            node_short = node.split("/")[-1] if node else ""
            if node_short and parm:
                val_str = str(val)[:20] if val is not None else "?"
                return f"{node_short}.{parm} = {val_str}"
            return msg[:80] or ""

        if tool_name == "connect_nodes":
            src = (args.get("from_node") or args.get("source") or "").split("/")[-1]
            dst = (args.get("to_node") or args.get("target") or "").split("/")[-1]
            if src and dst:
                return f"{src}  →  {dst}"
            return msg[:80] or ""

        if tool_name == "finalize_sop_network":
            out = (args.get("output_path") or data.get("output_path") or "").split("/")[-1]
            return f"Output: {out}" if out else "Network finalized"

        if tool_name == "set_display_flag":
            node = (args.get("node_path") or "").split("/")[-1]
            return f"Display → {node}" if node else msg[:80] or ""

        if tool_name in (
            "get_scene_summary",
            "get_node_info",
            "get_node_parameters",
            "get_geometry_attributes",
            "get_all_errors",
            "get_node_inputs",
            "inspect_display_output",
        ):
            if status == "error":
                return msg[:80] or "Read failed"
            return msg[:80] or "Scene data captured"

        return msg[:80] if msg else ""

    def _toggle(self):
        self._expanded = not self._expanded
        self.detail_box.setVisible(self._expanded)
        self.expand_btn.setText("⌄" if self._expanded else "›")


class ToolActivityGroup(QtWidgets.QWidget):
    """A clean timeline of tool call cards — no accordion, always expanded."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._count = 0
        self._ok_count = 0
        self._error_count = 0

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # ── Section header ───────────────────────────────────────────────
        hdr = QtWidgets.QHBoxLayout()
        hdr.setSpacing(8)
        self.section_lbl = QtWidgets.QLabel("Steps this turn")
        self.section_lbl.setStyleSheet(
            f"color: {ModernStyles.TEXT_SUBTLE}; font-size: 10px; font-weight: 600; letter-spacing: 0.5px;"
        )
        hdr.addWidget(self.section_lbl)
        hdr.addStretch()
        self.count_lbl = QtWidgets.QLabel("")
        self.count_lbl.setStyleSheet(f"color: {ModernStyles.TEXT_SUBTLE}; font-size: 10px;")
        hdr.addWidget(self.count_lbl)
        layout.addLayout(hdr)

        # ── Cards container ──────────────────────────────────────────────
        self.cards_layout = QtWidgets.QVBoxLayout()
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(3)
        layout.addLayout(self.cards_layout)

    def add_tool_call(self, tool_name: str, args: dict, result: dict):
        self._count += 1
        if result.get("status") == "ok":
            self._ok_count += 1
        elif result.get("status") == "error":
            self._error_count += 1

        card = ToolCallWidget(tool_name, args, result, index=self._count)
        self.cards_layout.addWidget(card)

        # Update header count
        parts = [f"{self._count} step{'s' if self._count != 1 else ''}"]
        if self._error_count:
            parts.append(
                f"<span style='color:{ModernStyles.ACCENT_DANGER}'>{self._error_count} failed</span>"
            )
        elif self._ok_count:
            parts.append(
                f"<span style='color:{ModernStyles.ACCENT_SUCCESS}'>{self._ok_count} ok</span>"
            )
        self.count_lbl.setText(" · ".join(parts))
        self.count_lbl.setTextFormat(QtCore.Qt.RichText)


class ImagePreview(QtWidgets.QFrame):
    remove_requested = QtCore.Signal()

    def __init__(self, pixmap, parent=None):
        super().__init__(parent)
        self.setFixedHeight(56)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)
        thumb = QtWidgets.QLabel()
        thumb.setPixmap(pixmap.scaledToHeight(44, QtCore.Qt.SmoothTransformation))
        thumb.setStyleSheet(f"border: 1px solid {ModernStyles.BORDER}; border-radius: 0px;")
        layout.addWidget(thumb)
        info = QtWidgets.QLabel("Image attached — routes to vision model")
        info.setObjectName("dim")
        layout.addWidget(info)
        layout.addStretch()
        rm = QtWidgets.QPushButton("✕")
        rm.setFixedSize(20, 20)
        rm.setStyleSheet(f"border: none; color: {ModernStyles.TEXT_DIM}; font-size: 10px;")
        rm.clicked.connect(self.remove_requested)
        layout.addWidget(rm)


class EmptyStateWidget(QtWidgets.QFrame):
    prompt_selected = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("chat_empty_state")
        self.setMaximumWidth(820)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(12)

        title = QtWidgets.QLabel("Houdini Agent Workspace")
        title.setObjectName("empty_state_title")
        title.setAlignment(QtCore.Qt.AlignCenter)
        root.addWidget(title)

        subtitle = QtWidgets.QLabel(
            "Select nodes or describe a target. The agent will read scene context, plan Houdini tool work, execute with checkpoints, and report what changed."
        )
        subtitle.setObjectName("empty_state_subtitle")
        subtitle.setAlignment(QtCore.Qt.AlignCenter)
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        flow = QtWidgets.QLabel("CONTEXT  →  PLAN  →  TOOLS  →  VERIFY")
        flow.setObjectName("agent_context_note")
        flow.setAlignment(QtCore.Qt.AlignCenter)
        root.addWidget(flow)

        prompt_grid = QtWidgets.QGridLayout()
        prompt_grid.setHorizontalSpacing(8)
        prompt_grid.setVerticalSpacing(8)
        prompt_grid.setColumnStretch(0, 1)
        prompt_grid.setColumnStretch(1, 1)

        prompts = [
            (
                "Build from selection",
                "Use the selected node or current context as the source, then build a clean procedural asset with master controls, clean naming, and a visible OUT node.",
            ),
            (
                "Fix current network",
                "Inspect the selected/current SOP network, find cooking errors, bad wiring, missing outputs, or parameter issues, then fix them with scene edits.",
            ),
            (
                "Explain selection",
                "READ-ONLY: Explain what the selected nodes are doing, identify risks, and list improvements as text only - do NOT modify the scene.",
            ),
            (
                "Add VEX logic",
                "Create or update a wrangle on the selected geometry with production-ready VEX, clear parameter names, and safe defaults.",
            ),
            (
                "Create scatter system",
                "Build a procedural scatter/copy-to-points setup from the current context with controllable density, random scale, rotation, and an OUT node.",
            ),
            (
                "Set up FX sim",
                "Set up a Houdini FX simulation network appropriate for the selected source, including controls, cache/output nodes, and viewport-friendly defaults.",
            ),
        ]
        for idx, (label, prompt) in enumerate(prompts):
            btn = QtWidgets.QPushButton(label)
            btn.setObjectName("empty_prompt_btn")
            btn.setCursor(QtCore.Qt.PointingHandCursor)
            btn.setMinimumHeight(40)
            btn.setToolTip(prompt)
            btn.clicked.connect(lambda _checked=False, text=prompt: self.prompt_selected.emit(text))
            prompt_grid.addWidget(btn, idx // 2, idx % 2)
        root.addLayout(prompt_grid)

        hint = QtWidgets.QLabel(
            "Tip: include the selected node, target style, scale, and whether scene edits are allowed."
        )
        hint.setObjectName("composer_hint")
        hint.setAlignment(QtCore.Qt.AlignCenter)
        hint.setWordWrap(True)
        root.addWidget(hint)


class StatusNoticeWidget(QtWidgets.QFrame):
    def __init__(self, text: str, tone: str = "neutral", parent=None):
        super().__init__(parent)
        self.setObjectName("status_notice")
        self.setMaximumWidth(720)

        border = {
            "warning": ModernStyles.ACCENT_WARN,
            "danger": ModernStyles.ACCENT_DANGER,
            "success": ModernStyles.ACCENT_SUCCESS,
        }.get(tone, ModernStyles.BORDER)
        fg = {
            "warning": "#ffffff",
            "danger": "#ffffff",
            "success": "#ffffff",
        }.get(tone, ModernStyles.TEXT_DIM)
        bg = {
            "warning": "#4b4131",
            "danger": "#503737",
            "success": "#3b4a3c",
        }.get(tone, ModernStyles.PANEL_ELEVATED)
        self.setStyleSheet(
            f"QFrame#status_notice {{ background: {bg}; border: 1px solid {border}55; border-radius: 0px; }}"
        )

        root = QtWidgets.QHBoxLayout(self)
        root.setContentsMargins(12, 8, 12, 8)
        root.setSpacing(8)

        dot = QtWidgets.QLabel("•")
        dot.setStyleSheet(f"color: {border}; font-size: 18px; font-weight: bold;")
        root.addWidget(dot, 0, QtCore.Qt.AlignTop)

        body = QtWidgets.QLabel(text)
        body.setWordWrap(True)
        body.setStyleSheet(f"color: {fg}; font-size: 11px;")
        body.setTextInteractionFlags(
            QtCore.Qt.TextSelectableByMouse | QtCore.Qt.TextSelectableByKeyboard
        )
        root.addWidget(body, 1)


class FailureActionStrip(QtWidgets.QFrame):
    retry_requested = QtCore.Signal()
    diagnostics_requested = QtCore.Signal()

    def __init__(self, failure_count: int = 1, parent=None):
        super().__init__(parent)
        self.setObjectName("failure_strip")
        self.setMaximumWidth(720)
        self.setStyleSheet(
            f"QFrame#failure_strip {{ background: {ModernStyles.PANEL_SOFT}; border: 1px solid {ModernStyles.ACCENT_WARN}66; border-radius: 0px; }}"
        )

        root = QtWidgets.QHBoxLayout(self)
        root.setContentsMargins(10, 7, 10, 7)
        root.setSpacing(8)

        label = QtWidgets.QLabel(
            f"{failure_count} issue{'s' if failure_count != 1 else ''} detected."
        )
        label.setStyleSheet(f"color: {ModernStyles.TEXT_DIM}; font-size: 11px;")
        root.addWidget(label)
        root.addStretch()

        retry_btn = QtWidgets.QPushButton("Retry last step")
        retry_btn.setObjectName("ghost_btn")
        retry_btn.setFixedHeight(26)
        retry_btn.clicked.connect(self.retry_requested)
        root.addWidget(retry_btn)

        diag_btn = QtWidgets.QPushButton("Show diagnostics")
        diag_btn.setObjectName("ghost_btn")
        diag_btn.setFixedHeight(26)
        diag_btn.clicked.connect(self.diagnostics_requested)
        root.addWidget(diag_btn)


class TurnSummaryWidget(QtWidgets.QFrame):
    details_requested = QtCore.Signal()
    tools_requested = QtCore.Signal()

    def __init__(
        self,
        created: int = 0,
        updated: int = 0,
        output: str = "",
        warnings: int = 0,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("turn_summary")
        accent = ModernStyles.ACCENT_WARN if warnings else ModernStyles.ACCENT_SUCCESS
        self.setStyleSheet(
            f"QFrame#turn_summary {{ background: {ModernStyles.PANEL_SOFT}; "
            f"border: 1px solid {ModernStyles.BORDER_SOFT}; border-left: 2px solid {accent}; "
            "border-radius: 0px; }}"
        )

        root = QtWidgets.QHBoxLayout(self)
        root.setContentsMargins(10, 6, 10, 6)
        root.setSpacing(8)

        parts = [f"Created {created}", f"Updated {updated}", f"Warnings {warnings}"]
        if output:
            parts.append(f"Output {output}")
        label = QtWidgets.QLabel("  |  ".join(parts))
        label.setWordWrap(True)
        label.setTextInteractionFlags(
            QtCore.Qt.TextSelectableByMouse | QtCore.Qt.TextSelectableByKeyboard
        )
        label.setStyleSheet(f"color: {ModernStyles.TEXT_DIM}; font-size: 10px;")
        root.addWidget(label, 1)

        scene_btn = QtWidgets.QPushButton("Scene")
        scene_btn.setObjectName("ghost_btn")
        scene_btn.setFixedHeight(22)
        scene_btn.setToolTip("Open scene details for this turn")
        scene_btn.clicked.connect(self.details_requested.emit)
        root.addWidget(scene_btn)

        tools_btn = QtWidgets.QPushButton("Tools")
        tools_btn.setObjectName("ghost_btn")
        tools_btn.setFixedHeight(22)
        tools_btn.setToolTip("Open tool trace for this turn")
        tools_btn.clicked.connect(self.tools_requested.emit)
        root.addWidget(tools_btn)


class FeedbackChip(QtWidgets.QLabel):
    def __init__(self, accepted: bool, parent=None):
        text = "+1 Saved"
        object_name = "feedback_chip"
        if not accepted:
            text = "-1 Avoid"
            object_name = "feedback_chip_reject"
        super().__init__(text, parent)
        self.setObjectName(object_name)
        self.setFixedHeight(18)
        self.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)


# ══════════════════════════════════════════════════════════════════════
#  Quick-Prompt Toolbar
# ══════════════════════════════════════════════════════════════════════


class QuickPromptBar(QtWidgets.QScrollArea):
    prompt_selected = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(34)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setWidgetResizable(True)
        inner = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(inner)
        row.setContentsMargins(2, 2, 2, 2)
        row.setSpacing(4)
        lbl = QtWidgets.QLabel("Quick:")
        lbl.setStyleSheet(f"color: {ModernStyles.TEXT_DIM}; font-size: 10px;")
        row.addWidget(lbl)
        for label, prompt in QUICK_PROMPTS:
            btn = QtWidgets.QPushButton(label)
            btn.setStyleSheet(
                f"font-size: 10px; padding: 2px 7px; border-radius: 4px; "
                f"background: {ModernStyles.PANEL}; border: 1px solid {ModernStyles.BORDER}; color: {ModernStyles.TEXT_DIM};"
            )
            btn.setCursor(QtCore.Qt.PointingHandCursor)
            btn.setToolTip(prompt)
            btn.clicked.connect(lambda _checked=False, text=prompt: self.prompt_selected.emit(text))
            row.addWidget(btn)
        row.addStretch()
        self.setWidget(inner)
        self.setStyleSheet(f"background: {ModernStyles.BG}; border: none;")


# ══════════════════════════════════════════════════════════════════════
#  Connection Status Bar
# ══════════════════════════════════════════════════════════════════════


class ConnectionStatus(QtWidgets.QFrame):
    reconnect_requested = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(24)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(6)
        self.dot = QtWidgets.QLabel("●")
        self.dot.setFixedWidth(12)
        layout.addWidget(self.dot)
        self.lbl = QtWidgets.QLabel("Checking Ollama…")
        self.lbl.setStyleSheet("font-size: 10px;")
        layout.addWidget(self.lbl)
        layout.addStretch()
        self.model_lbl = QtWidgets.QLabel("")
        self.model_lbl.setStyleSheet(f"font-size: 10px; color: {ModernStyles.ACCENT};")
        layout.addWidget(self.model_lbl)
        self.retry_btn = QtWidgets.QPushButton("⟳ Retry")
        self.retry_btn.setFixedHeight(18)
        self.retry_btn.setStyleSheet(
            f"font-size: 10px; padding: 1px 6px; background: #4a3a3a; "
            f"border: 1px solid {ModernStyles.ACCENT_DANGER}44; color: {ModernStyles.ACCENT_DANGER}; border-radius: 0px;"
        )
        self.retry_btn.setVisible(False)
        self.retry_btn.clicked.connect(self.reconnect_requested)
        layout.addWidget(self.retry_btn)
        self.setStyleSheet(
            f"QFrame {{ background: {ModernStyles.PANEL}; border: none; border-radius: 0px; }}"
        )
        self.set_checking()

    def set_checking(self):
        self.dot.setStyleSheet(f"color: {ModernStyles.ACCENT_WARN};")
        self.lbl.setText("Checking Ollama…")
        self.lbl.setStyleSheet(f"font-size: 10px; color: {ModernStyles.ACCENT_WARN};")
        self.retry_btn.setVisible(False)

    def set_ok(self, model_count: int, active_model: str = ""):
        self.dot.setStyleSheet(f"color: {ModernStyles.ACCENT_SUCCESS};")
        self.lbl.setText(f"Ollama connected · {model_count} model(s)")
        self.lbl.setStyleSheet(f"font-size: 10px; color: {ModernStyles.ACCENT_SUCCESS};")
        self.retry_btn.setVisible(False)
        if active_model:
            self.model_lbl.setText(f"Active: {active_model}")

    def set_error(self):
        self.dot.setStyleSheet(f"color: {ModernStyles.ACCENT_DANGER};")
        self.lbl.setText("Ollama not reachable — run: ollama serve")
        self.lbl.setStyleSheet(f"font-size: 10px; color: {ModernStyles.ACCENT_DANGER};")
        self.retry_btn.setVisible(True)
        self.model_lbl.setText("")

    def set_active_model(self, model: str):
        if model:
            self.model_lbl.setText(f"Active: {model}")


class ErrorBannerWidget(QtWidgets.QFrame):
    diagnose_requested = QtCore.Signal(str, str)
    fix_requested = QtCore.Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("error_banner")
        self.setVisible(False)
        self.setStyleSheet(
            f"QFrame#error_banner {{ background: #4b3434; border: 1px solid {ModernStyles.ACCENT_DANGER}66; border-radius: 0px; }}"
        )

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)

        self.lbl = QtWidgets.QLabel("")
        self.lbl.setWordWrap(True)
        self.lbl.setStyleSheet(f"color: {ModernStyles.ACCENT_DANGER}; font-size: 11px;")
        layout.addWidget(self.lbl, stretch=1)

        self.diag_btn = QtWidgets.QPushButton("Diagnose")
        self.diag_btn.setStyleSheet(
            f"background: #5a4242; border: 1px solid {ModernStyles.ACCENT_DANGER}; color: {ModernStyles.TEXT}; font-size: 10px; padding: 2px 6px;"
        )
        self.diag_btn.clicked.connect(self._on_diag)
        layout.addWidget(self.diag_btn)

        self.fix_btn = QtWidgets.QPushButton("⚡ Auto-Fix")
        self.fix_btn.setStyleSheet(
            f"background: {ModernStyles.ACCENT_DANGER}; border: 1px solid {ModernStyles.ACCENT_DANGER}; color: #ffffff; font-weight: bold; font-size: 10px; padding: 2px 6px;"
        )
        self.fix_btn.clicked.connect(self._on_fix)
        layout.addWidget(self.fix_btn)

        self._node = ""
        self._err = ""

    def show_error(self, node_path: str, error_msg: str):
        self._node = node_path
        self._err = error_msg
        self.lbl.setText(f"⚠️ Error on {node_path}: {error_msg[:80]}")
        self.setVisible(True)

    def _on_diag(self):
        self.setVisible(False)
        self.diagnose_requested.emit(self._node, self._err)

    def _on_fix(self):
        self.setVisible(False)
        self.fix_requested.emit(self._node, self._err)


class DebugLogDialog(QtWidgets.QDialog):
    def __init__(self, log_path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("HoudiniMind — Session Debug Log")
        self.setMinimumSize(800, 600)
        self.setStyleSheet(STYLESHEET)

        layout = QtWidgets.QVBoxLayout(self)

        self.viewer = QtWidgets.QTextBrowser()
        self.viewer.setOpenExternalLinks(True)
        # Use Markdown support in Qt 5.14+ / PySide6
        try:
            with open(log_path, encoding="utf-8") as f:
                md_text = f.read()
            self.viewer.setMarkdown(md_text)
            # Ensure images are loaded from the log's directory
            self.viewer.setSearchPaths([os.path.dirname(log_path)])
        except Exception as e:
            self.viewer.setPlainText(f"Error loading log: {e!s}")

        layout.addWidget(self.viewer)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch()
        refresh_btn = QtWidgets.QPushButton("⟳ Refresh")
        refresh_btn.clicked.connect(self._refresh)
        btn_row.addWidget(refresh_btn)
        self.auto_refresh_chk = QtWidgets.QCheckBox("Auto refresh")
        self.auto_refresh_chk.setChecked(True)
        self.auto_refresh_chk.toggled.connect(self._toggle_auto_refresh)
        btn_row.addWidget(self.auto_refresh_chk)
        close_btn = QtWidgets.QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self.log_path = log_path
        self._last_mtime = 0.0
        self._auto_timer = QtCore.QTimer(self)
        self._auto_timer.setInterval(1000)
        self._auto_timer.timeout.connect(self._refresh_if_changed)
        self._auto_timer.start()

    def closeEvent(self, event):
        try:
            self._auto_timer.stop()
        except Exception:
            pass
        super().closeEvent(event)

    def _toggle_auto_refresh(self, enabled: bool):
        if enabled:
            self._auto_timer.start()
            self._refresh_if_changed()
        else:
            self._auto_timer.stop()

    def _refresh_if_changed(self):
        try:
            mtime = os.path.getmtime(self.log_path)
        except Exception:
            return
        if mtime > self._last_mtime:
            self._refresh()

    def _refresh(self):
        try:
            with open(self.log_path, encoding="utf-8") as f:
                md_text = f.read()
            self._last_mtime = os.path.getmtime(self.log_path)
            self.viewer.setMarkdown(md_text)
            self.viewer.setSearchPaths([os.path.dirname(self.log_path)])
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════
#  Recipe Browser
# ══════════════════════════════════════════════════════════════════════


class RecipeBrowserDialog(QtWidgets.QDialog):
    def __init__(self, memory_manager, parent=None):
        super().__init__(parent)
        self.memory = memory_manager
        self.setWindowTitle("Recipe Browser")
        self.resize(600, 400)
        self.setStyleSheet(STYLESHEET)
        layout = QtWidgets.QVBoxLayout(self)
        search_l = QtWidgets.QHBoxLayout()
        self.search_box = QtWidgets.QLineEdit()
        self.search_box.setPlaceholderText("Search recipes…")
        self.search_box.textChanged.connect(self._reload)
        search_l.addWidget(self.search_box)
        refresh = QtWidgets.QPushButton("⟳")
        refresh.clicked.connect(self._reload)
        search_l.addWidget(refresh)
        layout.addLayout(search_l)
        self.table = QtWidgets.QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Name", "Domain", "Confidence", "Used", "Description"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.table)
        btns = QtWidgets.QHBoxLayout()
        close_btn = QtWidgets.QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btns.addStretch()
        btns.addWidget(close_btn)
        layout.addLayout(btns)
        self._reload()

    def _reload(self):
        q = self.search_box.text()
        try:
            recipes = self.memory.get_recipes(q if q else None)
        except Exception:
            recipes = []
        self.table.setRowCount(len(recipes))
        for r_idx, recipe in enumerate(recipes):
            for c_idx, key in enumerate(
                ["name", "domain", "confidence", "times_used", "description"]
            ):
                val = recipe.get(key, "")
                if key == "confidence":
                    val = f"{float(val or 0):.2f}"
                self.table.setItem(r_idx, c_idx, QtWidgets.QTableWidgetItem(str(val)))


# ══════════════════════════════════════════════════════════════════════
#  Main Panel
# ══════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════
#  ResearchOptionsWidget — rendered when AutoResearch returns options
# ══════════════════════════════════════════════════════════════════════
class ResearchOptionCard(QtWidgets.QFrame):
    """A single option card with label, summary, details, and a Use-This button."""

    use_requested = QtCore.Signal(dict)  # emits the option dict

    # Distinct accent colours per option slot
    _SLOT_COLORS = ["#f28c28", "#79a9d6", "#7cb08c"]

    def __init__(self, option: dict, parent=None):
        super().__init__(parent)
        self._option = option
        slot = (option.get("id", 1) - 1) % len(self._SLOT_COLORS)
        color = self._SLOT_COLORS[slot]

        self.setStyleSheet(f"""
            QFrame {{
                background: #3a3a3a;
                border: 1px solid {color}55;
                border-left: 3px solid {color};
                border-radius: 0px;
            }}
        """)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(6)

        # ── Header row ──────────────────────────────────────────────
        hdr = QtWidgets.QHBoxLayout()

        id_badge = QtWidgets.QLabel(f"  {option.get('id', '?')}  ")
        id_badge.setStyleSheet(
            f"background: {color}; color: #fff; font-size: 10px; "
            "font-weight: bold; border-radius: 0px; padding: 0px 2px;"
        )
        id_badge.setFixedHeight(18)
        hdr.addWidget(id_badge)

        lbl = QtWidgets.QLabel(option.get("label", "Option"))
        lbl.setStyleSheet(f"color: {color}; font-weight: bold; font-size: 12px;")
        hdr.addWidget(lbl, stretch=1)

        # Expand/collapse toggle
        self._expanded = False
        self._toggle_btn = QtWidgets.QPushButton("▶ details")
        self._toggle_btn.setFlat(True)
        self._toggle_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self._toggle_btn.setStyleSheet(f"color: {color}88; font-size: 10px; border: none;")
        self._toggle_btn.clicked.connect(self._toggle_details)
        hdr.addWidget(self._toggle_btn)

        root.addLayout(hdr)

        # ── Summary ─────────────────────────────────────────────────
        summary = QtWidgets.QLabel(option.get("summary", ""))
        summary.setWordWrap(True)
        summary.setStyleSheet(f"color: {ModernStyles.TEXT}; font-size: 11px; padding-left: 2px;")
        root.addWidget(summary)

        # ── use_when pill ────────────────────────────────────────────
        use_when_text = option.get("use_when", "")
        if use_when_text:
            uw = QtWidgets.QLabel(f"⚡ {use_when_text}")
            uw.setWordWrap(True)
            uw.setStyleSheet(
                f"color: {color}cc; font-size: 10px; background: transparent; padding-left: 2px;"
            )
            root.addWidget(uw)

        # ── Details (collapsible) ────────────────────────────────────
        self._detail_box = QtWidgets.QTextEdit()
        self._detail_box.setReadOnly(True)
        self._detail_box.setPlainText(option.get("details", "No details provided."))
        self._detail_box.setStyleSheet(
            f"background: #323232; border: 1px solid {ModernStyles.BORDER}; border-radius: 0px; "
            f"color: {ModernStyles.TEXT}; font-size: 11px; font-family: monospace;"
        )
        self._detail_box.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self._detail_box.setFixedHeight(90)
        self._detail_box.setVisible(False)
        root.addWidget(self._detail_box)

        # ── Use This button ──────────────────────────────────────────
        use_btn = QtWidgets.QPushButton("▶  Use This Approach")
        use_btn.setCursor(QtCore.Qt.PointingHandCursor)
        use_btn.setStyleSheet(f"""
            QPushButton {{
                background: {color}22;
                border: 1px solid {color}88;
                border-radius: 0px;
                color: {color};
                font-weight: bold;
                font-size: 11px;
                padding: 5px 14px;
            }}
            QPushButton:hover {{
                background: {color}44;
                border-color: {color};
            }}
            QPushButton:pressed {{
                background: {color}66;
            }}
        """)
        use_btn.clicked.connect(lambda: self.use_requested.emit(self._option))
        root.addWidget(use_btn)

    def _toggle_details(self):
        self._expanded = not self._expanded
        self._detail_box.setVisible(self._expanded)
        self._toggle_btn.setText("▼ details" if self._expanded else "▶ details")


class ResearchOptionsWidget(QtWidgets.QFrame):
    """
    Displays after AutoResearch completes.
    Shows 3 option cards; emits option_selected(option_dict, query) when
    the user clicks 'Use This' on any card.
    """

    option_selected = QtCore.Signal(dict, str)  # (option, original_query)

    def __init__(self, query: str, options: list, parent=None):
        super().__init__(parent)
        self._query = query
        self._options = options

        self.setStyleSheet("""
            QFrame {
                background: #383838;
                border: 1px solid #575757;
                border-radius: 0px;
            }
        """)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        # ── Header ───────────────────────────────────────────────────
        hdr = QtWidgets.QHBoxLayout()
        icon_lbl = QtWidgets.QLabel("🔍")
        icon_lbl.setStyleSheet("font-size: 16px;")
        hdr.addWidget(icon_lbl)

        title = QtWidgets.QLabel("AutoResearch — Choose an Approach")
        title.setStyleSheet(f"color: {ModernStyles.ACCENT}; font-weight: bold; font-size: 13px;")
        hdr.addWidget(title, stretch=1)

        # Dismiss button
        dismiss = QtWidgets.QPushButton("✕")
        dismiss.setFlat(True)
        dismiss.setFixedSize(22, 22)
        dismiss.setCursor(QtCore.Qt.PointingHandCursor)
        dismiss.setStyleSheet(f"color: {ModernStyles.TEXT_DIM}; font-size: 12px; border: none;")
        dismiss.clicked.connect(self.hide)
        hdr.addWidget(dismiss)
        root.addLayout(hdr)

        # Query preview
        q_preview = QtWidgets.QLabel(f"❝ {query[:90]}{'…' if len(query) > 90 else ''} ❞")
        q_preview.setWordWrap(True)
        q_preview.setStyleSheet(
            f"color: {ModernStyles.TEXT_DIM}; font-size: 10px; font-style: italic; padding-left: 4px;"
        )
        root.addWidget(q_preview)

        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.HLine)
        sep.setStyleSheet(f"color: {ModernStyles.BORDER};")
        root.addWidget(sep)

        # ── Option cards ─────────────────────────────────────────────
        for opt in options:
            card = ResearchOptionCard(opt, parent=self)
            card.use_requested.connect(self._on_use)
            root.addWidget(card)

        if not options:
            fallback = QtWidgets.QLabel("⚠️ No options were generated.")
            fallback.setStyleSheet(f"color: {ModernStyles.ACCENT_DANGER}; font-size: 11px;")
            root.addWidget(fallback)

    def _on_use(self, option: dict):
        self.option_selected.emit(option, self._query)
