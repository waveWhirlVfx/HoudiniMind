# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
from PySide6 import QtWidgets, QtCore, QtGui

from ._widgets import (
    STYLESHEET,
    ModernStyles,
    SettingsPanel,
    SmartInput,
    LoadingSpinner,
    EmptyStateWidget,
    QuickPromptBar,
    ConnectionStatus,
    ErrorBannerWidget,
)


class PanelLayoutMixin:
    @staticmethod
    def _make_mic_icon(color: str = "#c8c8c8") -> QtGui.QIcon:
        pix = QtGui.QPixmap(22, 22)
        pix.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(pix)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        pen = QtGui.QPen(QtGui.QColor(color), 1.8)
        painter.setPen(pen)
        painter.setBrush(QtGui.QColor(color))
        painter.drawRoundedRect(QtCore.QRectF(8, 3, 6, 10), 3, 3)
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawArc(QtCore.QRectF(5, 7, 12, 9), 200 * 16, 140 * 16)
        painter.drawLine(11, 16, 11, 19)
        painter.drawLine(7, 19, 15, 19)
        painter.end()
        return QtGui.QIcon(pix)

    def _build_ui(self):
        self.setStyleSheet(STYLESHEET)
        root = QtWidgets.QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(12, 10, 12, 12)

        header = QtWidgets.QHBoxLayout()
        header.setSpacing(6)
        header.setAlignment(QtCore.Qt.AlignVCenter)

        title_row = QtWidgets.QHBoxLayout()
        title_row.setSpacing(6)
        title_row.setContentsMargins(0, 0, 0, 0)
        self.title_lbl = QtWidgets.QLabel("HoudiniMind")
        self.title_lbl.setObjectName("title_lbl")
        title_row.addWidget(self.title_lbl)
        # Connection dot — just "●" in green/red, no background box
        self.header_status_lbl = QtWidgets.QLabel("●")
        self.header_status_lbl.setObjectName("header_meta_chip")
        self.header_status_lbl.setToolTip("Ollama connection status")
        self.header_status_lbl.setAlignment(QtCore.Qt.AlignCenter)
        self.header_status_lbl.setMinimumWidth(12)
        title_row.addWidget(self.header_status_lbl)
        title_row.addStretch()
        header.addLayout(title_row)
        header.addStretch()

        for attr, label, tip in [
            ("scene_btn", "Sync Scene", "Sync Scene"),
            ("learn_btn", "Learn", "Run learning cycle \u2014 mines conversation history for new recipes and updates the knowledge base."),
            ("hda_btn", "Index HDA", "Index HDA"),
            ("recipes_btn", "Recipes", "Recipes"),
            ("network_inspect_btn", "Inspect Network", "Inspect Network"),
            ("undo_btn", "Undo", "Undo"),
            ("export_btn", "Export", "Export Chat"),
            ("clear_btn", "Clear", "Clear Chat"),
            ("debug_log_btn", "Debug Log", "View Session Debug Log"),
        ]:
            btn = QtWidgets.QPushButton(label, self)
            btn.setToolTip(tip)
            btn.setVisible(False)
            if attr == "clear_btn":
                btn.setObjectName("clear_btn")
            setattr(self, attr, btn)

        self.details_toggle_btn = QtWidgets.QPushButton("☰")
        self.details_toggle_btn.setObjectName("icon_btn")
        self.details_toggle_btn.setToolTip("Details")
        self.details_toggle_btn.setCheckable(True)
        self.details_toggle_btn.setFixedSize(24, 24)
        header.addWidget(self.details_toggle_btn, 0, QtCore.Qt.AlignVCenter)

        self.settings_toggle_btn = QtWidgets.QPushButton("⚙")
        self.settings_toggle_btn.setObjectName("icon_btn")
        self.settings_toggle_btn.setToolTip("Settings")
        self.settings_toggle_btn.setCheckable(True)
        self.settings_toggle_btn.setFixedSize(24, 24)
        header.addWidget(self.settings_toggle_btn, 0, QtCore.Qt.AlignVCenter)

        # Stable popup menu trigger for header actions
        self.more_actions_btn = QtWidgets.QToolButton(self)
        self.more_actions_btn.setText("⋯")
        self.more_actions_btn.setObjectName("icon_btn")
        self.more_actions_btn.setToolTip("More actions")
        self.more_actions_btn.setFixedSize(24, 24)
        self.more_actions_btn.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        self.more_menu = QtWidgets.QMenu(self.more_actions_btn)
        self.more_actions_btn.setMenu(self.more_menu)
        header.addWidget(self.more_actions_btn, 0, QtCore.Qt.AlignVCenter)
        root.addLayout(header)

        self.sync_scene_action = self.more_menu.addAction("Sync Scene")
        self.inspect_network_action = self.more_menu.addAction("Inspect Network")
        self.undo_action = self.more_menu.addAction("Undo Last Turn")
        self.more_menu.addSeparator()
        self.export_action = self.more_menu.addAction("Export Chat")
        self.clear_chat_action = self.more_menu.addAction("Clear Chat")

        # Stub references kept for signal-wiring compatibility — actions not shown in menu
        self.learn_action = QtGui.QAction(self)
        self.index_hda_action = QtGui.QAction(self)
        self.recipes_action = QtGui.QAction(self)
        self.quick_prompts_action = QtGui.QAction(self)
        self.quick_prompts_action.setCheckable(True)
        self.focus_mode_action = QtGui.QAction(self)
        self.focus_mode_action.setCheckable(True)
        self.autoresearch_action = QtGui.QAction(self)
        self.autoresearch_action.setCheckable(True)
        self.autoresearch_stats_action = QtGui.QAction(self)
        self.debug_log_action = QtGui.QAction(self)

        # ── Overlay panels (not in layout — positioned over the UI) ─────────
        # ConnectionStatus: used only for Ollama polling logic, never shown in layout
        self.conn_status = ConnectionStatus()
        self.conn_status.setParent(self)
        self.conn_status.setVisible(False)

        self.model_bar = None

        # Settings overlay — floats below the header, over the chat area
        self.settings_panel = SettingsPanel(self.config)
        self.settings_panel.setParent(self)
        self.settings_panel.setVisible(False)
        self.settings_panel.setObjectName("settings_overlay")
        self.settings_panel.setStyleSheet(
            self.settings_panel.styleSheet() +
            f"""
            QFrame#settings_overlay, SettingsPanel {{
                background: {ModernStyles.PANEL_ELEVATED};
                border: 1px solid {ModernStyles.BORDER};
                border-radius: 0px;
            }}
            """
        )
        # Model controls wired from settings panel
        self.chat_model_combo = self.settings_panel.chat_model_combo
        self.vision_model_combo = self.settings_panel.vision_model_combo
        self.refresh_models_btn = self.settings_panel.refresh_models_btn

        # top_details_panel stub — kept for compatibility with _panel_state references
        self.top_details_panel = QtWidgets.QWidget(self)
        self.top_details_panel.setVisible(False)
        self.top_details_panel.setMaximumHeight(0)

        self.quick_bar = QuickPromptBar()
        self.quick_bar.setParent(self)
        self.quick_bar.setVisible(False)

        self.simple_mode_btn = QtWidgets.QPushButton("Simple", self)
        self.simple_mode_btn.setObjectName("mode_btn")
        self.simple_mode_btn.setCheckable(True)
        self.simple_mode_btn.setVisible(False)

        self.advanced_mode_btn = QtWidgets.QPushButton("Advanced", self)
        self.advanced_mode_btn.setObjectName("mode_btn")
        self.advanced_mode_btn.setCheckable(True)
        self.advanced_mode_btn.setVisible(False)

        self.focus_mode_btn = QtWidgets.QPushButton("Focus", self)
        self.focus_mode_btn.setObjectName("mode_btn")
        self.focus_mode_btn.setCheckable(True)
        self.focus_mode_btn.setVisible(False)
        # (top_details_panel intentionally NOT added to root layout)

        self.error_banner = ErrorBannerWidget()
        root.addWidget(self.error_banner)

        # Legacy turn strip kept for compatibility with existing state logic,
        # but intentionally hidden from UI.
        self.turn_strip = QtWidgets.QFrame(self)
        self.turn_strip.setObjectName("status_strip")
        self.turn_strip.setStyleSheet(f"""
            QFrame#status_strip {{
                background: {ModernStyles.PANEL_SOFT};
                border: none;
                border-top: 1px solid {ModernStyles.BORDER_SOFT};
                border-bottom: 1px solid {ModernStyles.BORDER_SOFT};
                border-left: 2px solid {ModernStyles.ACCENT};
                border-radius: 0px;
            }}
        """)
        self.turn_strip.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed
        )
        self.turn_strip.setMaximumHeight(0)
        self.turn_strip.setMinimumHeight(0)
        turn_layout = QtWidgets.QHBoxLayout(self.turn_strip)
        turn_layout.setContentsMargins(10, 4, 10, 4)
        turn_layout.setSpacing(10)

        self.turn_status_lbl = QtWidgets.QLabel("Ready")
        self.turn_status_lbl.setWordWrap(False)
        self.turn_status_lbl.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed
        )
        self.turn_status_lbl.setStyleSheet(
            f"color: {ModernStyles.TEXT_DIM}; font-size: 11px; font-weight: 500;"
        )
        turn_layout.addWidget(self.turn_status_lbl)

        self.turn_meta_lbl = QtWidgets.QLabel("")
        self.turn_meta_lbl.setStyleSheet(
            f"color: {ModernStyles.TEXT_SUBTLE}; font-size: 10px;"
        )
        self.turn_meta_lbl.setWordWrap(False)
        self.turn_meta_lbl.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        turn_layout.addWidget(self.turn_meta_lbl)
        # Always hidden (UI request: remove top status strip)
        self.turn_strip.setVisible(False)

        self.workspace_splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self.workspace_splitter.setChildrenCollapsible(False)

        self.chat_panel = QtWidgets.QWidget()
        chat_root = QtWidgets.QVBoxLayout(self.chat_panel)
        chat_root.setContentsMargins(0, 0, 0, 0)
        chat_root.setSpacing(8)

        self.chat_stack_host = QtWidgets.QWidget()
        self.chat_stack = QtWidgets.QStackedLayout(self.chat_stack_host)
        self.chat_stack.setContentsMargins(0, 0, 0, 0)

        self.empty_state_page = QtWidgets.QWidget()
        empty_root = QtWidgets.QVBoxLayout(self.empty_state_page)
        empty_root.setContentsMargins(12, 12, 12, 12)
        empty_root.addStretch()
        self.empty_state = EmptyStateWidget()
        empty_root.addWidget(self.empty_state, 0, QtCore.Qt.AlignHCenter)
        empty_root.addStretch()

        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.messages_w = QtWidgets.QWidget()
        messages_root = QtWidgets.QHBoxLayout(self.messages_w)
        messages_root.setContentsMargins(10, 8, 10, 12)
        messages_root.setSpacing(0)
        self.messages_column = QtWidgets.QFrame()
        self.messages_column.setObjectName("chat_lane")
        self.messages_l = QtWidgets.QVBoxLayout(self.messages_column)
        self.messages_l.setAlignment(QtCore.Qt.AlignTop)
        self.messages_l.setContentsMargins(0, 0, 0, 0)
        self.messages_l.setSpacing(8)
        messages_root.addWidget(self.messages_column, 1, QtCore.Qt.AlignTop)
        self.scroll.setWidget(self.messages_w)
        self.chat_stack.addWidget(self.empty_state_page)
        self.chat_stack.addWidget(self.scroll)

        # Scroll-to-bottom button — floats over the chat area
        self.scroll_to_bottom_btn = QtWidgets.QPushButton("↓")
        self.scroll_to_bottom_btn.setParent(self)
        self.scroll_to_bottom_btn.setFixedSize(28, 28)
        self.scroll_to_bottom_btn.setToolTip("Scroll to bottom")
        self.scroll_to_bottom_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.scroll_to_bottom_btn.setStyleSheet(
            f"QPushButton {{ background: {ModernStyles.PANEL_ELEVATED}; border: 1px solid {ModernStyles.BORDER}; "
            f"color: {ModernStyles.TEXT_DIM}; font-size: 14px; border-radius: 14px; }}"
            f"QPushButton:hover {{ background: #303030; color: {ModernStyles.TEXT}; }}"
        )
        self.scroll_to_bottom_btn.setVisible(False)
        self.scroll_to_bottom_btn.clicked.connect(
            lambda: self.scroll.verticalScrollBar().setValue(
                self.scroll.verticalScrollBar().maximum()
            )
        )
        # Hide button when already at bottom
        self.scroll.verticalScrollBar().valueChanged.connect(self._on_scroll_changed)

        chat_root.addWidget(self.chat_stack_host, stretch=1)
        self.workspace_splitter.addWidget(self.chat_panel)

        self.inspector_tabs = QtWidgets.QTabWidget()
        self.inspector_tabs.setDocumentMode(True)
        self.inspector_tabs.setMinimumWidth(320)

        self.tools_tab = QtWidgets.QWidget()
        tools_root = QtWidgets.QVBoxLayout(self.tools_tab)
        tools_root.setContentsMargins(10, 10, 10, 10)
        tools_root.setSpacing(8)
        self.tools_summary_lbl = QtWidgets.QLabel(
            "Tool activity for the current turn will appear here."
        )
        self.tools_summary_lbl.setStyleSheet(f"color: {ModernStyles.TEXT_DIM}; font-size: 11px;")
        self.tools_summary_lbl.setWordWrap(True)
        tools_root.addWidget(self.tools_summary_lbl)

        self.tools_scroll = QtWidgets.QScrollArea()
        self.tools_scroll.setWidgetResizable(True)
        self.tools_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.tools_w = QtWidgets.QWidget()
        self.tools_l = QtWidgets.QVBoxLayout(self.tools_w)
        self.tools_l.setContentsMargins(0, 0, 0, 0)
        self.tools_l.setSpacing(8)
        self.tools_empty_lbl = QtWidgets.QLabel("No tool activity for this turn yet.")
        self.tools_empty_lbl.setStyleSheet(
            f"color: {ModernStyles.TEXT_SUBTLE}; font-size: 11px; font-style: italic;"
        )
        self.tools_empty_lbl.setWordWrap(True)
        self.tools_l.addWidget(self.tools_empty_lbl)
        self.tools_l.addStretch()
        self.tools_scroll.setWidget(self.tools_w)
        tools_root.addWidget(self.tools_scroll, stretch=1)
        self.tools_tab_index = self.inspector_tabs.addTab(self.tools_tab, "Tools")

        self.scene_tab = QtWidgets.QWidget()
        scene_root = QtWidgets.QVBoxLayout(self.scene_tab)
        scene_root.setContentsMargins(10, 10, 10, 10)
        scene_root.setSpacing(8)

        self.scene_overview_lbl = QtWidgets.QLabel("No scene changes yet.")
        self.scene_overview_lbl.setStyleSheet(
            f"color: {ModernStyles.TEXT}; font-size: 12px; font-weight: 600;"
        )
        self.scene_overview_lbl.setWordWrap(True)
        scene_root.addWidget(self.scene_overview_lbl)

        self.scene_meta_lbl = QtWidgets.QLabel("Request: —\nOutput: —\nReview: —")
        self.scene_meta_lbl.setStyleSheet(f"color: {ModernStyles.TEXT_DIM}; font-size: 11px;")
        self.scene_meta_lbl.setWordWrap(True)
        self.scene_meta_lbl.setTextInteractionFlags(
            QtCore.Qt.TextSelectableByMouse | QtCore.Qt.TextSelectableByKeyboard
        )
        scene_root.addWidget(self.scene_meta_lbl)

        thought_hdr = QtWidgets.QLabel("Agent Notes")
        thought_hdr.setObjectName("section_title")
        scene_root.addWidget(thought_hdr)
        self.thought_label = QtWidgets.QLabel("")
        self.thought_label.setObjectName("thought")
        self.thought_label.setWordWrap(True)
        self.thought_label.setStyleSheet(f"color: {ModernStyles.TEXT_DIM}; font-size: 10px;")
        scene_root.addWidget(self.thought_label)

        summary_hdr = QtWidgets.QLabel("Assistant Summary")
        summary_hdr.setObjectName("section_title")
        scene_root.addWidget(summary_hdr)
        self.scene_summary_box = QtWidgets.QPlainTextEdit()
        self.scene_summary_box.setReadOnly(True)
        self.scene_summary_box.setPlaceholderText(
            "The final build summary will appear here."
        )
        self.scene_summary_box.setMaximumBlockCount(500)
        self.scene_summary_box.setStyleSheet(
            f"background: {ModernStyles.BG}; border: 1px solid {ModernStyles.BORDER_SOFT}; border-radius: 0px; color: {ModernStyles.TEXT_DIM}; font-size: 11px;"
        )
        scene_root.addWidget(self.scene_summary_box, stretch=1)

        diff_hdr = QtWidgets.QLabel("Scene Diff")
        diff_hdr.setObjectName("section_title")
        scene_root.addWidget(diff_hdr)
        self.scene_diff_box = QtWidgets.QPlainTextEdit()
        self.scene_diff_box.setReadOnly(True)
        self.scene_diff_box.setPlaceholderText(
            "Scene changes and output paths will appear here."
        )
        self.scene_diff_box.setMaximumHeight(180)
        self.scene_diff_box.setStyleSheet(
            f"background: {ModernStyles.BG}; border: 1px solid {ModernStyles.BORDER_SOFT}; border-radius: 0px; color: {ModernStyles.TEXT_DIM}; font-size: 11px;"
        )
        scene_root.addWidget(self.scene_diff_box)
        self.scene_tab_index = self.inspector_tabs.addTab(self.scene_tab, "Scene")

        self.memory_tab = QtWidgets.QWidget()
        memory_root = QtWidgets.QVBoxLayout(self.memory_tab)
        memory_root.setContentsMargins(10, 10, 10, 10)
        memory_root.setSpacing(8)

        memory_hdr = QtWidgets.QHBoxLayout()
        memory_title = QtWidgets.QLabel("Memory Overview")
        memory_title.setObjectName("section_title")
        memory_hdr.addWidget(memory_title)
        memory_hdr.addStretch()
        self.memory_refresh_btn = QtWidgets.QPushButton("Refresh")
        self.memory_refresh_btn.setFixedHeight(24)
        memory_hdr.addWidget(self.memory_refresh_btn)
        memory_root.addLayout(memory_hdr)

        self.memory_stats_lbl = QtWidgets.QLabel("Memory is loading…")
        self.memory_stats_lbl.setStyleSheet(f"color: {ModernStyles.TEXT_DIM}; font-size: 11px;")
        self.memory_stats_lbl.setWordWrap(True)
        memory_root.addWidget(self.memory_stats_lbl)

        self.memory_recipes_box = QtWidgets.QPlainTextEdit()
        self.memory_recipes_box.setReadOnly(True)
        self.memory_recipes_box.setPlaceholderText(
            "Learned recipes and recent memory stats will appear here."
        )
        self.memory_recipes_box.setStyleSheet(
            f"background: {ModernStyles.BG}; border: 1px solid {ModernStyles.BORDER_SOFT}; border-radius: 0px; color: {ModernStyles.TEXT_DIM}; font-size: 11px;"
        )
        memory_root.addWidget(self.memory_recipes_box, stretch=1)
        self.memory_tab_index = self.inspector_tabs.addTab(self.memory_tab, "Memory")

        self.workspace_splitter.addWidget(self.inspector_tabs)
        self.workspace_splitter.setStretchFactor(0, 3)
        self.workspace_splitter.setStretchFactor(1, 2)
        self.workspace_splitter.setSizes([760, 360])
        root.addWidget(self.workspace_splitter, stretch=1)

        self.feedback_bar = QtWidgets.QWidget()
        feedback_l = QtWidgets.QHBoxLayout(self.feedback_bar)
        feedback_l.setContentsMargins(0, 0, 0, 0)
        feedback_l.addStretch()
        self.accept_btn = QtWidgets.QPushButton("✓")
        self.accept_btn.setObjectName("accept_btn")
        self.accept_btn.setFixedSize(32, 28)
        self.accept_btn.setEnabled(False)
        self.accept_btn.setToolTip("Accept — save this turn to memory as a positive example")
        self.reject_btn = QtWidgets.QPushButton("✕")
        self.reject_btn.setObjectName("reject_btn")
        self.reject_btn.setFixedSize(32, 28)
        self.reject_btn.setEnabled(False)
        self.reject_btn.setToolTip("Reject — log this turn as a failure for the agent to learn from")
        feedback_l.addWidget(self.accept_btn)
        feedback_l.addWidget(self.reject_btn)
        self.feedback_host = QtWidgets.QWidget(self)
        self.feedback_host.setVisible(False)
        self.feedback_bar.setParent(self.feedback_host)

        self.img_preview_container = QtWidgets.QWidget()
        self.img_preview_container.setVisible(False)
        self.img_preview_layout = QtWidgets.QVBoxLayout(self.img_preview_container)
        self.img_preview_layout.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.img_preview_container)

        input_container = QtWidgets.QFrame()
        input_container.setObjectName("composer_shell")
        input_v = QtWidgets.QVBoxLayout(input_container)
        input_v.setContentsMargins(14, 12, 14, 10)
        input_v.setSpacing(8)

        self.input_box = SmartInput()
        self.input_box.setStyleSheet(
            f"QTextEdit {{ background: transparent; border: none; padding: 0; "
            f"color: {ModernStyles.TEXT}; font-size: 12px; line-height: 145%; }}"
        )
        input_v.addWidget(self.input_box)

        action_row = QtWidgets.QHBoxLayout()
        action_row.setSpacing(6)

        self.attach_btn = QtWidgets.QPushButton("+")
        self.attach_btn.setObjectName("attach_btn")
        self.attach_btn.setFixedSize(30, 30)
        self.attach_btn.setToolTip("Attach image and quick actions")
        self.attach_btn.setCursor(QtCore.Qt.PointingHandCursor)
        action_row.addWidget(self.attach_btn)

        self.vision_toggle_btn = QtWidgets.QPushButton("V")
        self.vision_toggle_btn.setObjectName("vision_toggle_btn")
        self.vision_toggle_btn.setCheckable(True)
        self.vision_toggle_btn.setChecked(True)
        self.vision_toggle_btn.setFixedSize(34, 30)
        self.vision_toggle_btn.setToolTip(
            "Vision on for this message. Click to bypass image analysis and vision checks."
        )
        self.vision_toggle_btn.setCursor(QtCore.Qt.PointingHandCursor)
        action_row.addWidget(self.vision_toggle_btn)

        self.fast_toggle_btn = QtWidgets.QPushButton("Fast")
        self.fast_toggle_btn.setObjectName("fast_toggle_btn")
        self.fast_toggle_btn.setCheckable(True)
        self.fast_toggle_btn.setChecked(False)
        self.fast_toggle_btn.setFixedSize(52, 30)
        self.fast_toggle_btn.setToolTip(
            "Fast off: full validation. Click to skip expensive checks for this message."
        )
        self.fast_toggle_btn.setCursor(QtCore.Qt.PointingHandCursor)
        action_row.addWidget(self.fast_toggle_btn)

        self.research_btn = QtWidgets.QPushButton("Research")
        self.research_btn.setObjectName("research_btn")
        self.research_btn.setFixedHeight(28)
        self.research_btn.setVisible(False)

        self.dry_run_btn = QtWidgets.QPushButton("Dry Run")
        self.dry_run_btn.setObjectName("ghost_btn")
        self.dry_run_btn.setFixedHeight(28)
        self.dry_run_btn.setToolTip(
            "Plan and simulate changes without modifying the scene"
        )
        self.dry_run_btn.setVisible(False)

        self.composer_actions_btn = QtWidgets.QToolButton()
        self.composer_actions_btn.setObjectName("ghost_btn")
        self.composer_actions_btn.setText("Actions")
        self.composer_actions_btn.setToolTip("More actions")
        self.composer_actions_btn.setFixedHeight(30)
        self.composer_actions_btn.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        self.composer_actions_menu = QtWidgets.QMenu(self.composer_actions_btn)
        self.composer_research_action = self.composer_actions_menu.addAction("Research")
        self.composer_dry_run_action = self.composer_actions_menu.addAction("Dry Run")
        self.composer_actions_menu.addSeparator()
        self.composer_autoresearch_action = self.composer_actions_menu.addAction(
            "Train"
        )
        self.composer_autoresearch_action.setCheckable(True)
        # removed from menu but kept as stubs for signal compatibility
        self.composer_inspect_network_action = QtGui.QAction("Inspect Network", self)
        self.composer_sync_scene_action = QtGui.QAction("Sync Scene", self)
        self.composer_actions_btn.setMenu(self.composer_actions_menu)
        self.composer_actions_btn.setVisible(False)
        action_row.addWidget(self.composer_actions_btn)

        self.attach_menu = QtWidgets.QMenu(self.attach_btn)
        self.attach_attach_action = self.attach_menu.addAction("Attach Image")
        self.attach_menu.addSeparator()
        self.attach_menu.addAction(self.composer_research_action)
        self.attach_menu.addAction(self.composer_dry_run_action)
        self.attach_menu.addAction(self.composer_autoresearch_action)

        self.autoresearch_btn = QtWidgets.QPushButton("Train")
        self.autoresearch_btn.setObjectName("autoresearch_btn")
        self.autoresearch_btn.setCheckable(True)
        self.autoresearch_btn.setMinimumHeight(30)
        self.autoresearch_btn.setMinimumWidth(62)
        self.autoresearch_btn.setMaximumWidth(90)
        self.autoresearch_btn.setToolTip(
            "Start agent training loop: the agent invents tasks, builds them in Houdini, "
            "learns from errors, and loops indefinitely. Click again to stop."
        )
        self.autoresearch_btn.setVisible(False)
        action_row.addWidget(self.autoresearch_btn, stretch=0)

        action_row.addStretch()

        self.mic_btn = QtWidgets.QPushButton("")
        self.mic_btn.setObjectName("mic_btn")
        self.mic_btn.setToolTip("Start speech input")
        self.mic_btn.setCheckable(True)
        self.mic_btn.setFixedSize(34, 30)
        self.mic_btn.setIcon(self._make_mic_icon(ModernStyles.TEXT_DIM))
        self.mic_btn.setIconSize(QtCore.QSize(18, 18))
        self.mic_btn.setCursor(QtCore.Qt.PointingHandCursor)
        action_row.addWidget(self.mic_btn)

        self.send_btn = QtWidgets.QPushButton("↑")
        self.send_btn.setObjectName("send_btn")
        self.send_btn.setToolTip("Send")
        self.send_btn.setFixedSize(38, 30)
        action_row.addWidget(self.send_btn)

        self.stop_btn = QtWidgets.QPushButton("■")
        self.stop_btn.setObjectName("stop_btn")
        self.stop_btn.setToolTip("Stop")
        self.stop_btn.setFixedSize(38, 30)
        self.stop_btn.setVisible(False)
        action_row.addWidget(self.stop_btn)
        input_v.addLayout(action_row)

        # Legacy composer status row (mode/turn/hints) kept for logic wiring,
        # but hidden from UI.
        self.composer_status_row = QtWidgets.QWidget()
        self.composer_status_row.setVisible(False)
        status_row = QtWidgets.QHBoxLayout(self.composer_status_row)
        status_row.setSpacing(4)

        # Mode label — shows "Ready" / "Busy" / mode name, no "Mode:" prefix
        self.mode_label = QtWidgets.QLabel("Ready")
        self.mode_label.setObjectName("composer_mode_chip")
        status_row.addWidget(self.mode_label)

        # Phase info now shown via PhaseAnimWidget below the agent bubble —
        # keep dummy attrs so existing code doesn't crash on getattr checks
        self.progress_planning_chip = QtWidgets.QLabel()
        self.progress_planning_chip.setVisible(False)
        self.progress_building_chip = QtWidgets.QLabel()
        self.progress_building_chip.setVisible(False)
        self.progress_verifying_chip = QtWidgets.QLabel()
        self.progress_verifying_chip.setVisible(False)

        self.composer_hint_lbl = QtWidgets.QLabel("")
        self.composer_hint_lbl.setObjectName("composer_hint")
        self.composer_hint_lbl.setVisible(False)

        # Spinner — hidden until an agent turn starts
        self.spinner = LoadingSpinner()
        self.spinner.setVisible(False)
        status_row.addWidget(self.spinner)
        status_row.addStretch()

        # Turn counter
        self.turn_counter_lbl = QtWidgets.QLabel("Turn 0")
        self.turn_counter_lbl.setStyleSheet(
            f"color: {ModernStyles.TEXT_SUBTLE}; font-size: 10px;"
        )
        status_row.addWidget(self.turn_counter_lbl)

        # Keyboard hints — shortened so token bar always fits
        self.kb_hint_lbl = QtWidgets.QLabel("↵ ⇧↵ ↑↓")
        self.kb_hint_lbl.setToolTip("↵ Send   ⇧↵ Newline   ↑↓ History")
        self.kb_hint_lbl.setStyleSheet(
            f"color: {ModernStyles.TEXT_SUBTLE}; font-size: 9px; padding-left: 6px;"
        )
        status_row.addWidget(self.kb_hint_lbl)

        self.token_bar = QtWidgets.QLabel("Context: 0 tokens")
        self.token_bar.setObjectName("token_bar")
        self.token_bar.setTextFormat(QtCore.Qt.RichText)
        self.token_bar.setMaximumWidth(200)
        status_row.addWidget(self.token_bar)
        input_v.addWidget(self.composer_status_row)

        root.addWidget(input_container)
        self._apply_view_mode()
        self._update_feedback_visibility()
        self._refresh_tools_panel()
        self._refresh_scene_panel()
        self._refresh_memory_panel()
        self._refresh_turn_status()
        self._update_empty_state_visibility()

    # ── Scroll-to-bottom logic ─────────────────────────────────────────────
    def _on_scroll_changed(self, value: int):
        """Show/hide the scroll-to-bottom button based on scroll position."""
        if not hasattr(self, "scroll_to_bottom_btn"):
            return
        sb = self.scroll.verticalScrollBar()
        at_bottom = value >= sb.maximum() - 20
        self.scroll_to_bottom_btn.setVisible(not at_bottom and sb.maximum() > 0)
        self._reposition_overlays()

    # ── Overlay positioning ────────────────────────────────────────────────
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reposition_overlays()

    def _reposition_overlays(self):
        """Keep floating overlay panels anchored below the header."""
        if not hasattr(self, "settings_panel"):
            return
        # Position settings overlay: full width minus margins, below header row (~46px)
        m = 10          # matches root layout margins
        header_h = 46   # approx header + spacing
        w = self.width() - m * 2
        self.settings_panel.setFixedWidth(w)
        self.settings_panel.adjustSize()
        h = self.settings_panel.sizeHint().height()
        self.settings_panel.setGeometry(m, header_h, w, h)
        self.settings_panel.raise_()

        # Position scroll-to-bottom button: bottom-right of chat area
        if hasattr(self, "scroll_to_bottom_btn") and hasattr(self, "scroll"):
            sb_w = 28
            sb_h = 28
            # Place it just above the composer input (~80px from bottom)
            x = self.width() - sb_w - 20
            y = self.height() - sb_h - 100
            self.scroll_to_bottom_btn.setGeometry(x, y, sb_w, sb_h)
            self.scroll_to_bottom_btn.raise_()
