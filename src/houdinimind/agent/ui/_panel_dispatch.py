# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
import threading
import time
import traceback
import json
import re

from PySide6 import QtWidgets, QtCore, QtGui

from ._widgets import (
    ModernStyles,
    HOU_AVAILABLE,
    ToolActivityGroup,
    ImagePreview,
    ResearchOptionsWidget,
    FailureActionStrip,
    PhaseAnimWidget,
)


class PanelDispatchMixin:
    @staticmethod
    def _tokenize_live_text(text: str) -> list:
        normalized = str(text or "").replace("\r\n", " ").replace("\r", " ").replace(
            "\n", " "
        )
        normalized = re.sub(r"\s+", " ", normalized).strip()
        if not normalized:
            return []
        # Keep punctuation attached to words and animate chunk-by-chunk.
        return re.findall(r"\S+\s*", normalized)

    def _clear_live_stream_queue(self):
        queue = getattr(self, "_live_stream_queue", None)
        if queue is not None:
            queue.clear()
        self._live_stream_text = ""
        timer = getattr(self, "_live_stream_timer", None)
        if timer is not None:
            timer.stop()

    def _drain_live_stream_queue(self):
        if not self._current_bubble:
            self._clear_live_stream_queue()
            return
        queue = getattr(self, "_live_stream_queue", None)
        timer = getattr(self, "_live_stream_timer", None)
        if queue is None or not queue:
            if timer is not None:
                timer.stop()
            return
        batch = []
        for _ in range(3):
            if not queue:
                break
            batch.append(queue.popleft())
        if not batch:
            if timer is not None:
                timer.stop()
            return
        merged = (self._live_stream_text or "") + "".join(batch)
        # Absolute compaction guard: no newline inflation during live streaming.
        # Collapse any whitespace run to a single space, but preserve the trailing
        # space so the next batch's first token doesn't get jammed against the
        # previous one ("youmodify", "thelatest").  Only strip leading whitespace.
        merged = re.sub(r"\s+", " ", merged).lstrip()
        self._live_stream_text = merged
        if hasattr(self._current_bubble, "set_stream_text"):
            self._current_bubble.set_stream_text(self._live_stream_text)
        else:
            self._current_bubble.set_text(self._live_stream_text)
        self.scroll.verticalScrollBar().setValue(
            self.scroll.verticalScrollBar().maximum()
        )
        if not queue and timer is not None:
            timer.stop()

    def _connect_signals(self):
        self.send_btn.clicked.connect(self._send)
        self.mic_btn.clicked.connect(self._toggle_speech_input)
        self.dry_run_btn.clicked.connect(self._send_dry_run)
        self.input_box.send_requested.connect(self._send)
        self.research_btn.clicked.connect(self._send_research)
        self.composer_research_action.triggered.connect(self._send_research)
        self.composer_dry_run_action.triggered.connect(self._send_dry_run)
        self.composer_autoresearch_action.triggered.connect(self._toggle_autoresearch)
        self.composer_inspect_network_action.triggered.connect(
            self._inspect_network_view
        )
        self.composer_sync_scene_action.triggered.connect(self._inject_scene)
        self.attach_btn.clicked.connect(self._open_attach_menu)
        self.vision_toggle_btn.toggled.connect(self._on_vision_toggle)
        self.fast_toggle_btn.toggled.connect(self._on_fast_toggle)
        if hasattr(self, "attach_attach_action"):
            self.attach_attach_action.triggered.connect(self._attach_image_dialog)
        self.stop_btn.clicked.connect(self._on_stop)
        self.undo_btn.clicked.connect(self._on_undo)
        self.learn_btn.clicked.connect(self._run_learning_cycle)
        self.hda_btn.clicked.connect(self._learn_hda)
        self.recipes_btn.clicked.connect(self._show_recipes)
        self.network_inspect_btn.clicked.connect(self._inspect_network_view)
        self.export_btn.clicked.connect(self._export_chat)
        self.scene_btn.clicked.connect(self._inject_scene)
        self.clear_btn.clicked.connect(self._clear_conversation)
        self.details_toggle_btn.clicked.connect(self._toggle_details_panel)
        self.settings_toggle_btn.clicked.connect(self._toggle_settings_panel)
        self.debug_log_btn.clicked.connect(self._show_debug_log)
        self.sync_scene_action.triggered.connect(self._inject_scene)
        self.inspect_network_action.triggered.connect(self._inspect_network_view)
        self.undo_action.triggered.connect(self._on_undo)
        self.learn_action.triggered.connect(self._run_learning_cycle)
        self.index_hda_action.triggered.connect(self._learn_hda)
        self.recipes_action.triggered.connect(self._show_recipes)
        self.quick_prompts_action.toggled.connect(self._set_quick_prompts_visible)
        self.focus_mode_action.toggled.connect(self._set_focus_mode)
        self.export_action.triggered.connect(self._export_chat)
        self.debug_log_action.triggered.connect(self._show_debug_log)
        self.clear_chat_action.triggered.connect(self._clear_conversation)
        self.refresh_models_btn.clicked.connect(self._refresh_models_async)
        self.accept_btn.clicked.connect(lambda: self._record_feedback(True))
        self.reject_btn.clicked.connect(lambda: self._record_feedback(False))
        self.chat_model_combo.currentIndexChanged.connect(self._on_chat_model_changed)
        self.vision_model_combo.currentIndexChanged.connect(
            self._on_vision_model_changed
        )
        self.settings_panel.settings_changed.connect(self._apply_settings)
        self.quick_bar.prompt_selected.connect(self._apply_quick_prompt)
        self.empty_state.prompt_selected.connect(self._apply_quick_prompt)
        self.conn_status.reconnect_requested.connect(self._refresh_models_async)
        self.simple_mode_btn.clicked.connect(lambda: self._set_detail_mode("simple"))
        self.advanced_mode_btn.clicked.connect(
            lambda: self._set_detail_mode("advanced")
        )
        self.focus_mode_btn.clicked.connect(self._toggle_focus_mode)
        self.memory_refresh_btn.clicked.connect(self._refresh_memory_panel)
        self.sig_stream_chunk.connect(self._on_chunk)
        self.sig_response_done.connect(self._on_done)
        self.sig_research_options.connect(self._on_research_options)
        self.sig_tool_called.connect(self._on_tool_display)
        self.sig_confirm_request.connect(self._show_confirm_dialog)
        # Red error banner functionality removed as user found it intrusive
        # self.sig_scene_error.connect(self._show_error_banner)
        # self.error_banner.diagnose_requested.connect(self._diagnose_error_from_banner)
        # self.error_banner.fix_requested.connect(self._fix_error_from_banner)
        self.sig_models_loaded.connect(self._on_models_loaded)
        self.sig_asr_partial.connect(self._append_speech_text)
        self.sig_asr_status.connect(self._on_speech_status)
        self.autoresearch_btn.clicked.connect(self._toggle_autoresearch)
        self.autoresearch_action.triggered.connect(self._toggle_autoresearch)
        self.autoresearch_stats_action.triggered.connect(self._show_autoresearch_stats)
        self.sig_autoresearch_progress.connect(self._on_autoresearch_progress)
        self.input_box.installEventFilter(self)

    def _toggle_speech_input(self):
        controller = getattr(self, "_asr_controller", None)
        if controller is None:
            self._add_system_note(
                "Speech input is still initializing. Try again after HoudiniMind finishes loading."
            )
            if hasattr(self, "mic_btn"):
                self.mic_btn.setChecked(False)
            return
        controller.toggle()

    def _on_asr_state_changed(self, recording: bool):
        if hasattr(self, "mic_btn"):
            self.mic_btn.blockSignals(True)
            self.mic_btn.setChecked(bool(recording))
            if hasattr(self, "_make_mic_icon"):
                color = ModernStyles.ACCENT if recording else ModernStyles.TEXT_DIM
                self.mic_btn.setIcon(self._make_mic_icon(color))
            self.mic_btn.setToolTip("Stop speech input" if recording else "Start speech input")
            self.mic_btn.blockSignals(False)
        if recording:
            self._status("Listening...")

    def _on_speech_status(self, message: str):
        text = (message or "").strip()
        if not text:
            return
        lowered = text.lower()
        if "failed" in lowered or "needs the" in lowered or "unavailable" in lowered:
            self._add_system_note(text)
        else:
            self._status(text)

    def _append_speech_text(self, text: str):
        text = (text or "").strip()
        if not text:
            return
        current = self.input_box.toPlainText()
        sep = "" if not current or current.endswith((" ", "\n")) else " "
        self.input_box.setPlainText(f"{current}{sep}{text}")
        cursor = self.input_box.textCursor()
        cursor.movePosition(QtGui.QTextCursor.End)
        self.input_box.setTextCursor(cursor)
        self.input_box.setFocus()

    def eventFilter(self, obj, event):
        if obj is self.input_box and event.type() == QtCore.QEvent.KeyPress:
            if (
                event.key() == QtCore.Qt.Key_V
                and event.modifiers() & QtCore.Qt.ControlModifier
            ):
                cb = QtWidgets.QApplication.clipboard()
                if cb.mimeData().hasImage():
                    self._load_image_from_pixmap(cb.pixmap())
                    return True
        return super().eventFilter(obj, event)

    def _apply_quick_prompt(self, prompt: str):
        self.input_box.setPlainText(prompt)
        self.input_box.setFocus()

    def _vision_next_enabled(self) -> bool:
        btn = getattr(self, "vision_toggle_btn", None)
        if btn is None:
            return True
        return bool(btn.isChecked())

    def _on_vision_toggle(self, enabled: bool):
        self._vision_for_next_message = bool(enabled)
        btn = getattr(self, "vision_toggle_btn", None)
        if btn is not None:
            # Keep text as "V", don't change to "V-"
            btn.setToolTip(
                "Vision on for this message. Click to bypass image analysis and vision checks."
                if enabled
                else "Vision bypassed for this message. Text will use chat only; attached images will not be analysed."
            )
        if not self._busy:
            self.mode_label.setText("Ready" if enabled else "Vision bypass")

    def _fast_next_enabled(self) -> bool:
        btn = getattr(self, "fast_toggle_btn", None)
        if btn is None:
            return False
        return bool(btn.isChecked())

    def _on_fast_toggle(self, enabled: bool):
        self._fast_for_next_message = bool(enabled)
        btn = getattr(self, "fast_toggle_btn", None)
        if btn is not None:
            btn.setToolTip(
                "Fast on: skips expensive verification, network audit, and auto-repair for this message."
                if enabled
                else "Fast off: full validation. Click to skip expensive checks for this message."
            )
        if not self._busy:
            self.mode_label.setText("Fast mode" if enabled else "Ready")

    def _open_attach_menu(self):
        menu = getattr(self, "attach_menu", None)
        if menu is None:
            self._attach_image_dialog()
            return
        menu.exec(self.attach_btn.mapToGlobal(self.attach_btn.rect().bottomLeft()))

    def _attach_image_dialog(self):
        import os as _os
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Attach Image", "", "Images (*.png *.jpg *.jpeg *.bmp *.webp)"
        )
        if path:
            MAX_IMG = 20 * 1024 * 1024  # 20 MB
            size = _os.path.getsize(path)
            if size > MAX_IMG:
                QtWidgets.QMessageBox.warning(
                    self, "Image too large",
                    f"File is {size // 1024 // 1024} MB. Limit is 20 MB."
                )
                return
            pixmap = QtGui.QPixmap(path)
            if not pixmap.isNull():
                with open(path, "rb") as f:
                    self._pending_image_bytes = f.read()
                self._show_image_preview(pixmap)

    def _load_image_from_pixmap(self, pixmap):
        if pixmap.isNull():
            return
        ba = QtCore.QByteArray()
        buf = QtCore.QBuffer(ba)
        buf.open(QtCore.QIODevice.WriteOnly)
        pixmap.save(buf, "PNG")
        self._pending_image_bytes = bytes(ba)
        self._show_image_preview(pixmap)

    def _show_image_preview(self, pixmap):
        if self._image_preview_widget:
            self._image_preview_widget.setParent(None)
        self._image_preview_widget = ImagePreview(pixmap)
        self._image_preview_widget.remove_requested.connect(self._clear_image)
        self.img_preview_layout.addWidget(self._image_preview_widget)
        self.img_preview_container.setVisible(True)
        self.mode_label.setText("Mode: Vision (image attached)")

    def _clear_image(self):
        self._pending_image_bytes = None
        if self._image_preview_widget:
            self._image_preview_widget.setParent(None)
            self._image_preview_widget = None
        self.img_preview_container.setVisible(False)
        self.mode_label.setText("Ready")

    def _handle_slash_command(self, text: str) -> bool:
        """
        Handle /command shortcuts typed in the chat box.
        Returns True if the input was consumed as a command (no further action needed).

        Supported commands:
          /model <name>     — Select chat model from UI model list
          /vision <name>    — Select vision model from UI model list
          /models           — List currently available Ollama models
          /clear            — Clear conversation history
          /doctor           — Run a quick health-check on agent, Ollama, RAG, memory
          /help             — Show available slash commands
        """
        stripped = (text or "").strip()
        if not stripped.startswith("/"):
            return False

        parts = stripped.split(None, 1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if cmd == "/model":
            if not arg:
                current = (
                    self.chat_model_combo.current_model()
                    if hasattr(self, "chat_model_combo")
                    else (getattr(self.agent.llm, "model", "?") if self.agent else "?")
                )
                self._add_system_note(f"Current chat model: **{current}**\nUsage: /model <model-name>")
                return True
            idx = self.chat_model_combo.findText(arg)
            if idx < 0:
                for i in range(self.chat_model_combo.count()):
                    if self.chat_model_combo.itemText(i).strip().lower() == arg.strip().lower():
                        idx = i
                        break
            if idx < 0:
                self._add_system_note(
                    f"Model **{arg}** is not in the UI selector list. Choose a listed model in Settings → Models."
                )
                return True
            self.chat_model_combo.setCurrentIndex(idx)
            selected = self.chat_model_combo.current_model()
            self._add_system_note(f"Chat model set via UI selector: **{selected}**")
            return True

        if cmd == "/vision":
            if not arg:
                current = (
                    self.vision_model_combo.current_model()
                    if hasattr(self, "vision_model_combo")
                    else (getattr(self.agent.llm, "vision_model", "?") if self.agent else "?")
                )
                self._add_system_note(f"Current vision model: **{current}**\nUsage: /vision <model-name>")
                return True
            idx = self.vision_model_combo.findText(arg)
            if idx < 0:
                for i in range(self.vision_model_combo.count()):
                    if self.vision_model_combo.itemText(i).strip().lower() == arg.strip().lower():
                        idx = i
                        break
            if idx < 0:
                self._add_system_note(
                    f"Vision model **{arg}** is not in the UI selector list. Choose a listed model in Settings → Models."
                )
                return True
            self.vision_model_combo.setCurrentIndex(idx)
            selected = self.vision_model_combo.current_model()
            self._add_system_note(f"Vision model set via UI selector: **{selected}**")
            return True

        if cmd == "/models":
            if self.agent:
                try:
                    models = self.agent.llm.list_models() or []
                    lines = "\n".join(f"  • {m}" for m in sorted(models)) or "  (none found)"
                    self._add_system_note(f"Available Ollama models:\n{lines}")
                except Exception as e:
                    self._add_system_note(f"Could not list models: {e}")
            return True

        if cmd == "/clear":
            self._clear_conversation()
            return True

        if cmd == "/doctor":
            self._run_doctor()
            return True

        if cmd == "/schedule":
            sched = getattr(self, "_research_scheduler", None)
            if arg in ("on", "start"):
                self.config["schedule_enabled"] = True
                if sched:
                    sched.config["schedule_enabled"] = True
                    sched.start()
                self._add_system_note("Scheduled Training **enabled**.")
            elif arg in ("off", "stop"):
                self.config["schedule_enabled"] = False
                if sched:
                    sched.config["schedule_enabled"] = False
                    sched.stop()
                self._add_system_note("Scheduled Training **disabled**.")
            elif arg == "now":
                if sched:
                    sched.trigger_now()
                    self._add_system_note("Training triggered manually.")
                else:
                    self._add_system_note("Scheduler not initialized.")
            elif arg == "status":
                if sched:
                    stats = sched.stats()
                    import time as _t
                    last = _t.strftime("%H:%M:%S", _t.localtime(stats["last_run_ts"])) if stats["last_run_ts"] else "never"
                    self._add_system_note(
                        f"**Scheduler Status**\n"
                        f"  Enabled: {stats['enabled']}\n"
                        f"  Interval: {stats['interval_h']}h\n"
                        f"  Last run: {last}\n"
                        f"  Total runs: {stats['run_count']}"
                    )
                else:
                    self._add_system_note("Scheduler not initialized.")
            else:
                self._add_system_note(
                    "Usage: `/schedule on|off|now|status`"
                )
            return True

        if cmd == "/skill":
            loader = getattr(self, "_skill_loader", None)
            if arg == "list":
                if loader:
                    st = loader.status()
                    loaded = ", ".join(st["loaded"]) or "(none)"
                    errors = ", ".join(f"{k}: {v}" for k, v in st["errors"].items()) or "(none)"
                    self._add_system_note(
                        f"**Skills loaded ({st['total_loaded']}):** {loaded}\n"
                        f"**Errors ({st['total_errors']}):** {errors}"
                    )
                else:
                    self._add_system_note("SkillLoader not initialized.")
            elif arg.startswith("reload"):
                parts = arg.split(None, 1)
                skill_name = parts[1].strip() if len(parts) > 1 else ""
                if not skill_name:
                    self._add_system_note("Usage: `/skill reload <name>`")
                elif loader:
                    ok = loader.reload_skill(skill_name)
                    if ok:
                        self._add_system_note(f"Skill '{skill_name}' reloaded.")
                    else:
                        self._add_system_note(f"Skill '{skill_name}' not found.")
                else:
                    self._add_system_note("SkillLoader not initialized.")
            else:
                self._add_system_note("Usage: `/skill list` or `/skill reload <name>`")
            return True

        if cmd == "/help":
            self._add_system_note(
                "**Slash Commands**\n"
                "  `/model <name>`        — Select chat model from UI list\n"
                "  `/vision <name>`       — Select vision model from UI list\n"
                "  `/models`              — List available Ollama models\n"
                "  `/clear`               — Clear conversation history\n"
                "  `/doctor`              — Agent health check\n"
                "  `/schedule on|off|now|status` — Control scheduled AutoResearch\n"
                "  `/skill list`          — List loaded skills\n"
                "  `/skill reload <name>` — Hot-reload a skill by name\n"
                "  `/help`                — Show this message"
            )
            return True

        # Unknown slash command — let it through as normal text
        return False

    def _run_doctor(self):
        """Quick health-check: Ollama reachable, vision model, RAG, memory DB."""
        lines = ["**HoudiniMind Doctor**\n"]
        # Ollama connectivity
        try:
            models = self.agent.llm.list_models() if self.agent else []
            lines.append(f"✅ Ollama: reachable — {len(models)} model(s) loaded")
        except Exception as e:
            lines.append(f"❌ Ollama: unreachable — {e}")
        # Chat model
        if self.agent:
            m = getattr(self.agent.llm, "model", "?")
            lines.append(f"✅ Chat model: **{m}**")
            vm = getattr(self.agent.llm, "vision_model", "?")
            ve = getattr(self.agent.llm, "vision_enabled", False)
            lines.append(f"{'✅' if ve else '⚠️'} Vision model: **{vm}** (enabled={ve})")
        # RAG
        try:
            if self.agent and self.agent.rag:
                lines.append("✅ RAG: injector loaded")
            else:
                lines.append("⚠️ RAG: not loaded")
        except Exception:
            lines.append("⚠️ RAG: check failed")
        # Memory
        try:
            if hasattr(self, "memory") and self.memory:
                stats = self.memory.dashboard()
                total_interactions = stats.get("log", {}).get("total_interactions", 0)
                total_recipes = stats.get("recipes", {}).get("total_recipes", 0)
                total_rules = stats.get("project_rules", {}).get("total_rules", 0)
                lines.append(
                    f"✅ Memory: {total_interactions} interactions, "
                    f"{total_recipes} recipes, {total_rules} rules"
                )
            else:
                lines.append("⚠️ Memory: not initialized")
        except Exception as e:
            lines.append(f"⚠️ Memory: {e}")
        # Houdini
        try:
            from houdinimind.agent.tools._core import HOU_AVAILABLE
            if HOU_AVAILABLE:
                import hou
                lines.append(f"✅ Houdini: connected — v{hou.applicationVersionString()}")
            else:
                lines.append("⚠️ Houdini: not connected (running outside Houdini)")
        except Exception:
            lines.append("⚠️ Houdini: check failed")
        self._add_system_note("\n".join(lines))

    def _send(self):
        print(f"[HM-DEBUG] _send called: _busy={self._busy}, agent={self.agent is not None}, pending_img={self._pending_image_bytes is not None}")
        if self._busy or not self.agent:
            print(f"[HM-DEBUG] _send BLOCKED: _busy={self._busy}, agent={self.agent}")
            return
        text = self.input_box.get_text()
        if not text and not self._pending_image_bytes:
            return
        self.input_box.push_history(text)
        self.input_box.clear_text()
        # Handle slash commands before dispatching to agent
        if text and self._handle_slash_command(text):
            return
        if self.config.get("ui", {}).get("auto_inject_scene_on_chat", False):
            self._inject_scene(silent=True)
        vision_enabled = self._vision_next_enabled()
        fast_enabled = self._fast_next_enabled()
        if self._pending_image_bytes and vision_enabled:
            self._dispatch_vision(
                text or "Analyse this Houdini screenshot",
                dry_run=False,
                fast=fast_enabled,
            )
        else:
            if self._pending_image_bytes and not text:
                self._add_system_note(
                    "Vision is bypassed. Add text to send a chat-only request, or turn Vision on to analyse the attached image."
                )
                return
            if self._pending_image_bytes:
                self._clear_image()
            self._dispatch_chat(text, dry_run=False, fast=fast_enabled)

    def _send_dry_run(self):
        if self._busy or not self.agent:
            return
        text = self.input_box.get_text()
        if not text and not self._pending_image_bytes:
            return
        self.input_box.push_history(text)
        self.input_box.clear_text()
        if self.config.get("ui", {}).get("auto_inject_scene_on_chat", False):
            self._inject_scene(silent=True)
        vision_enabled = self._vision_next_enabled()
        fast_enabled = self._fast_next_enabled()
        if self._pending_image_bytes and vision_enabled:
            self._dispatch_vision(
                text or "Analyse this Houdini screenshot",
                dry_run=True,
                fast=fast_enabled,
            )
        else:
            if self._pending_image_bytes and not text:
                self._add_system_note(
                    "Vision is bypassed. Add text to run a chat-only dry run, or turn Vision on to analyse the attached image."
                )
                return
            if self._pending_image_bytes:
                self._clear_image()
            self._dispatch_chat(text, dry_run=True, fast=fast_enabled)

    def _send_research(self):
        if self._busy or not self.agent:
            return
        text = self.input_box.get_text()
        if not text:
            return
        self.input_box.push_history(text)
        self.input_box.clear_text()
        self._dispatch_research(text)

    def _inspect_network_view(self):
        print(f"[HM-DEBUG] _inspect_network_view called: _busy={self._busy}, agent={self.agent is not None}")
        if self._busy:
            self._add_system_note(
                "Inspect Network is unavailable while another turn is running."
            )
            self._refresh_turn_status(
                "Finish or stop the current turn before inspecting the network."
            )
            return
        if not self.agent:
            self._add_system_note(
                "Inspect Network is unavailable because the agent is not ready."
            )
            self._refresh_turn_status("The agent is still starting up.")
            return
        if not HOU_AVAILABLE:
            self._add_system_note(
                "Inspect Network only works inside Houdini with a live scene."
            )
            self._refresh_turn_status(
                "Open the panel inside Houdini to inspect the current network view."
            )
            return
        user_text = "[Network] Inspect the current network view."
        self._current_dry_run = False
        self._current_mode = "vision"
        self.mode_label.setText("Mode: Network Inspect")
        self._add_msg("user", user_text, "vision")
        self._current_bubble = self._add_msg("agent", "", "vision")
        self._begin_turn_ui(user_text, "vision", dry_run=False)
        self._set_busy(True)
        self._submit_agent_job(
            "network_inspect",
            lambda progress_cb, status_cb: self.agent.inspect_network_view(
                progress_cb,
                status_callback=status_cb,
            ),
        )

    def _dispatch_chat(self, text: str, dry_run: bool = False, fast: bool = False):
        self._current_dry_run = dry_run
        self._current_mode = "chat"
        vision_enabled = self._vision_next_enabled()
        if dry_run:
            self.mode_label.setText(
                "Mode: Dry Run - Fast"
                if fast
                else "Mode: Dry Run - Vision Bypass"
                if not vision_enabled
                else "Mode: Dry Run"
            )
        else:
            self.mode_label.setText(
                "Mode: Chat - Fast"
                if fast
                else "Mode: Chat - Vision Bypass"
                if not vision_enabled
                else "Mode: Chat"
            )
        tags = []
        if fast:
            tags.append("Fast")
        if not vision_enabled:
            tags.append("Vision Off")
        prefix = "".join(f"[{tag}] " for tag in tags)
        user_text = f"[Dry Run] {prefix}{text}" if dry_run else f"{prefix}{text}"
        self._add_msg("user", user_text, "chat")
        self._current_bubble = self._add_msg("agent", "", "chat")
        self._begin_turn_ui(user_text, "chat", dry_run=dry_run)
        self._set_busy(True)
        self._total_chars += len(text)

        context_prefix = self._get_selection_context()
        full_text = f"{context_prefix}\n\n{text}" if context_prefix else text

        runner = lambda progress_cb, status_cb: self.agent.chat(
            full_text,
            progress_cb,
            dry_run=dry_run,
            status_callback=status_cb,
        )
        self._submit_agent_job(
            "chat",
            self._wrap_turn_overrides(runner, vision_enabled, fast, text=text),
        )

    @staticmethod
    def _count_tasks(text: str) -> int:
        """Estimate the number of distinct tasks in a user message."""
        # Numbered list: "1. do X\n2. do Y"
        if len(re.findall(r'(?:^|\n)\s*\d+[.)]\s+\S', text)) >= 2:
            return len(re.findall(r'(?:^|\n)\s*\d+[.)]\s+\S', text))
        # Bullet list
        if len(re.findall(r'(?:^|\n)\s*[-*•]\s+\S', text)) >= 2:
            return 2
        # Explicit multi-task markers
        if re.search(r'\b(also|additionally|furthermore|then\s+also|and\s+also)\b', text, re.IGNORECASE):
            return 2
        # Multiple action verbs suggest multiple tasks
        actions = re.findall(
            r'\b(create|add|set|connect|delete|move|rename|build|make|apply|change|update|fix|enable|disable)\b',
            text, re.IGNORECASE,
        )
        if len(actions) >= 3:
            return 2
        return 1

    def _wrap_turn_overrides(self, runner, vision_enabled: bool, fast: bool = False, text: str = ""):
        if vision_enabled and not fast:
            return runner

        def _run(progress_cb, status_cb):
            agent = getattr(self, "agent", None)
            llm = getattr(agent, "llm", None) if agent is not None else None
            old_llm_vision = getattr(llm, "vision_enabled", None)
            old_agent_vision = getattr(agent, "_vision_enabled", None)
            old_verify_skip = getattr(agent, "verify_skip_vision", None)
            old_network_checks = getattr(agent, "auto_network_view_checks", None)
            old_max_repairs = getattr(agent, "max_auto_repairs", None)
            old_repair_budget = getattr(agent, "_turn_repair_budget", None)
            old_fast_skip_validator = getattr(agent, "_fast_skip_validator", None)
            old_fast_message_mode = getattr(agent, "_fast_message_mode", None)
            old_max_tool_rounds = getattr(agent, "max_tool_rounds", None)
            old_fast_build_rounds = getattr(agent, "fast_build_rounds", None)
            old_fast_debug_rounds = getattr(agent, "fast_debug_rounds", None)
            old_early_min_round = getattr(agent, "early_completion_min_round", None)
            old_vision_bypass_active = getattr(agent, "_vision_bypass_active", None)
            old_llm_temperature = getattr(llm, "temperature", None)
            try:
                if llm is not None and old_llm_vision is not None:
                    llm.vision_enabled = bool(vision_enabled)
                if agent is not None:
                    agent._vision_bypass_active = bool(not vision_enabled)
                    if old_agent_vision is not None and not vision_enabled:
                        agent._vision_enabled = False
                    if old_verify_skip is not None and not vision_enabled:
                        agent.verify_skip_vision = True
                    if fast:
                        task_count = max(1, self._count_tasks(text))
                        if llm is not None and old_llm_temperature is not None:
                            fast_temp = float(
                                (agent.config or {}).get("fast_temperature", 0.1)
                            )
                            llm.temperature = fast_temp
                        if old_network_checks is not None:
                            agent.auto_network_view_checks = False
                        if old_max_repairs is not None:
                            agent.max_auto_repairs = 0
                        if old_repair_budget is not None:
                            agent._turn_repair_budget = 0
                        agent._fast_skip_validator = True
                        agent._fast_message_mode = True
                        if old_max_tool_rounds is not None:
                            agent.max_tool_rounds = min(int(old_max_tool_rounds), 4 * task_count)
                        if old_fast_build_rounds is not None:
                            agent.fast_build_rounds = min(int(old_fast_build_rounds), 4 * task_count)
                        if old_fast_debug_rounds is not None:
                            agent.fast_debug_rounds = min(int(old_fast_debug_rounds), 3 * task_count)
                        if old_early_min_round is not None:
                            agent.early_completion_min_round = task_count
                return runner(progress_cb, status_cb)
            finally:
                if llm is not None and old_llm_vision is not None:
                    llm.vision_enabled = old_llm_vision
                if llm is not None and old_llm_temperature is not None:
                    llm.temperature = old_llm_temperature
                if agent is not None:
                    if old_agent_vision is not None:
                        agent._vision_enabled = old_agent_vision
                    if old_verify_skip is not None:
                        agent.verify_skip_vision = old_verify_skip
                    if old_network_checks is not None:
                        agent.auto_network_view_checks = old_network_checks
                    if old_max_repairs is not None:
                        agent.max_auto_repairs = old_max_repairs
                    if old_repair_budget is not None:
                        agent._turn_repair_budget = old_repair_budget
                    if old_fast_skip_validator is None:
                        try:
                            delattr(agent, "_fast_skip_validator")
                        except Exception:
                            pass
                    else:
                        agent._fast_skip_validator = old_fast_skip_validator
                    if old_fast_message_mode is None:
                        try:
                            delattr(agent, "_fast_message_mode")
                        except Exception:
                            pass
                    else:
                        agent._fast_message_mode = old_fast_message_mode
                    if old_max_tool_rounds is not None:
                        agent.max_tool_rounds = old_max_tool_rounds
                    if old_fast_build_rounds is not None:
                        agent.fast_build_rounds = old_fast_build_rounds
                    if old_fast_debug_rounds is not None:
                        agent.fast_debug_rounds = old_fast_debug_rounds
                    if old_early_min_round is not None:
                        agent.early_completion_min_round = old_early_min_round
                    if old_vision_bypass_active is not None:
                        agent._vision_bypass_active = old_vision_bypass_active
                    else:
                        try:
                            delattr(agent, "_vision_bypass_active")
                        except AttributeError:
                            pass

        return _run

    def _dispatch_vision(self, text: str, dry_run: bool = False, fast: bool = False):
        self._current_dry_run = dry_run
        img = self._pending_image_bytes
        self._clear_image()
        self._current_mode = "vision"
        if dry_run:
            self.mode_label.setText(
                "Mode: Vision Dry Run - Fast" if fast else "Mode: Vision Dry Run"
            )
        else:
            self.mode_label.setText("Mode: Vision - Fast" if fast else "Mode: Vision")
        fast_tag = "[Fast]" if fast else ""
        user_text = f"[Image]{fast_tag}[Dry Run] {text}" if dry_run else f"[Image]{fast_tag} {text}"
        self._add_msg("user", user_text, "vision")
        self._current_bubble = self._add_msg("agent", "", "vision")
        self._begin_turn_ui(user_text, "vision", dry_run=dry_run)
        self._set_busy(True)
        self._total_chars += len(text)

        self._submit_agent_job(
            "vision",
            self._wrap_turn_overrides(lambda progress_cb, status_cb: (
                print(f"[HM-DEBUG] vision runner started, calling agent.chat_with_vision"),
                self.agent.chat_with_vision(
                    text,
                    img,
                    progress_cb,
                    dry_run=dry_run,
                    status_callback=status_cb,
                ),
            )[-1], vision_enabled=True, fast=fast),
        )

    def _dispatch_research(self, text: str):
        self._current_mode = "research"
        self._current_dry_run = False
        self.mode_label.setText("Mode: AutoResearch")
        self._add_msg("user", text, "research")
        self._current_bubble = self._add_msg("agent", "", "research")
        self._begin_turn_ui(text, "research", dry_run=False)
        self._set_busy(True)
        self._total_chars += len(text)

        # Capture vision state at dispatch time; fast mode is always disabled for research
        # — research needs RAG, planning, and full tool rounds to produce quality results.
        self._research_vision_enabled = self._vision_next_enabled()
        self._research_fast_enabled = False

        context_prefix = self._get_selection_context()
        full_text = f"{context_prefix}\n\n{text}" if context_prefix else text

        runner = lambda progress_cb, status_cb: self.agent.research(
            full_text,
            progress_cb,
            status_callback=status_cb,
        )
        self._submit_agent_job(
            "research",
            self._wrap_turn_overrides(runner, self._research_vision_enabled, self._research_fast_enabled),
        )

    def _run_and_finish(self, fn):
        try:
            result = fn()
        except Exception as e:
            err_msg = f"\n\n⚠️ **Agent Error:** {e}"
            self.sig_stream_chunk.emit(err_msg)
            result = err_msg
            traceback.print_exc()
        self.sig_response_done.emit(result)

    def _submit_agent_job(self, kind: str, runner):
        print(f"[HM-DEBUG] _submit_agent_job kind={kind}, job_manager={getattr(self, 'job_manager', None) is not None}, async_enabled={self.config.get('async_jobs_enabled', True)}")
        if getattr(self, "job_manager", None) and self.config.get(
            "async_jobs_enabled", True
        ):
            self._active_job_id = self.job_manager.submit(
                kind=kind,
                runner=runner,
                stream_callback=self.sig_stream_chunk.emit,
                done_callback=self.sig_response_done.emit,
            )
            return
        threading.Thread(
            target=lambda: self._run_and_finish(
                lambda: runner(self.sig_stream_chunk.emit, lambda _payload: None)
            ),
            daemon=True,
        ).start()

    def _show_status(self, text: str):
        """Show/update a single-line status inside the active agent bubble."""
        message = (text or "").strip()
        if not message:
            return
        if self._current_bubble and hasattr(self._current_bubble, "set_inline_status"):
            phase = "building" if self._current_turn_tools else "planning"
            self._current_bubble.set_inline_status(message, phase=phase)
            return
        if self._status_row is None:
            from houdinimind.agent.ui._widgets import AgentStatusRow

            self._status_row = AgentStatusRow(self.messages_w)
            if self._current_bubble:
                idx = self.messages_l.indexOf(self._current_bubble)
                self.messages_l.insertWidget(idx + 1, self._status_row)
            else:
                self.messages_l.addWidget(self._status_row)
        self._status_row.set_status(message)

    def _hide_status(self):
        """Clear in-bubble status and remove fallback row if present."""
        if self._current_bubble and hasattr(self._current_bubble, "clear_inline_status"):
            self._current_bubble.clear_inline_status()
        if self._status_row:
            self._status_row.clear()
            self.messages_l.removeWidget(self._status_row)
            self._status_row.deleteLater()
            self._status_row = None

    def _append_progress_to_bubble(self, text: str):
        message = (text or "").strip()
        if not message:
            return
        self._show_status(message)
        self._refresh_turn_status(message)
        self._refresh_scene_panel(
            overview=message,
            summary_text=self._extract_primary_response(
                self._current_bubble.text() if self._current_bubble else ""
            ),
            diff_text=getattr(self.agent, "_last_turn_scene_diff_text", "") or "",
        )

    def _append_live_text_to_bubble(self, chunk: str):
        if not self._current_bubble:
            return
        text = str(chunk or "")
        if not text.strip():
            return
        placeholder = self._turn_placeholder_text(
            getattr(self, "_current_mode", "chat"),
            getattr(self, "_current_dry_run", False),
        )
        if (self._current_bubble.text() or "").strip() == placeholder.strip():
            self._current_bubble.set_text("")
            current_text = ""
        else:
            current_text = self._current_bubble.text() or ""
        queue = getattr(self, "_live_stream_queue", None)
        queue_empty = not queue
        if not current_text.strip() and queue_empty:
            text = text.lstrip()
        text = text.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
        text = re.sub(r"\s+", " ", text)
        tokens = self._tokenize_live_text(text)
        if not tokens:
            return
        # Ensure chunks join naturally as one flowing chat line.
        tail = ""
        if queue:
            tail = str(queue[-1])[-1:]
        elif current_text:
            tail = current_text[-1:]
        if tail and not tail.isspace():
            first = tokens[0]
            if first and first[0] not in ".,!?;:)]}":
                tokens[0] = " " + first
        queue.extend(tokens)
        timer = getattr(self, "_live_stream_timer", None)
        if timer is not None and not timer.isActive():
            timer.start()
        self._drain_live_stream_queue()

    def _append_live_line_to_bubble(self, line: str):
        if not self._current_bubble:
            return
        normalized = " ".join(str(line or "").strip().split())
        if not normalized:
            return
        self._append_live_text_to_bubble(normalized)

    def _on_chunk(self, chunk: str):
        research_sentinel = "\x00RESEARCH_OPTIONS\x00"
        progress_sentinel = "\x00AGENT_PROGRESS\x00"
        llm_trace_sentinel = "\x00LLM_TRACE\x00"
        if research_sentinel in chunk:
            payload = chunk.split(research_sentinel, 1)[1]
            try:
                data = json.loads(payload)
                query = data.get("query", "")
                options = data.get("options", [])
                self.sig_research_options.emit(query, options)
            except Exception:
                pass
            return
        if chunk.startswith(llm_trace_sentinel):
            payload = chunk.split(llm_trace_sentinel, 1)[1]
            try:
                data = json.loads(payload)
            except Exception:
                data = {"content": payload}
            round_num = int(data.get("round", 0)) + 1
            task = str(data.get("task", "") or "chat")
            tool_call_count = int(data.get("tool_call_count", 0) or 0)
            tool_names = [str(n) for n in (data.get("tool_names") or []) if str(n)]
            content = str(data.get("content", "") or "").strip()
            if content or tool_names:
                if content:
                    summary = f"R{round_num} [{task}] tc={tool_call_count}: {content[:240]}"
                else:
                    names = ", ".join(tool_names[:5])
                    summary = f"R{round_num} [{task}] selected tool call{'s' if tool_call_count != 1 else ''}: {names}"
                if summary not in self._current_turn_llm_notes:
                    self._current_turn_llm_notes.append(summary)
                self.thought_label.setText(summary)
                if self._current_bubble and hasattr(self._current_bubble, "set_llm_activity"):
                    self._current_bubble.set_llm_activity(summary)
            return
        if chunk.startswith(progress_sentinel):
            progress_text = chunk.split(progress_sentinel, 1)[1]
            # Show the progress *only* in the inline status pill at the bottom of
            # the bubble.  Do NOT also append it into the streaming body — that
            # used to mix progress sentences into the LLM token stream and
            # produce garbled text like "Reviewing thelatest scene state...".
            self._append_progress_to_bubble(progress_text)
            self._last_live_progress_line = (progress_text or "").strip()
            return
        if chunk.startswith("\u200b"):
            # Zero-width-space prefixed chunks are agent activity descriptors
            # (tool calls, tool results, vision/plan notes, etc).  They are
            # NOT model response text and must never be inserted into the
            # message bubble — that's what produced the "create_node(...) ✅
            # create_node → UNDO_TRACK ..." text and the giant gaps inside
            # the bubble.  Surface them only via the thought/debug label;
            # the dedicated Tools panel already shows full tool history.
            live_chunk = chunk.replace("\u200b", "")
            live_text = live_chunk.strip()
            if live_text:
                self.thought_label.setText(live_text)
                if self._current_bubble and hasattr(self._current_bubble, "set_llm_activity"):
                    self._current_bubble.set_llm_activity(live_text)
            self._refresh_scene_panel(
                summary_text=self._extract_primary_response(
                    self._current_bubble.text() if self._current_bubble else ""
                ),
                diff_text=getattr(self.agent, "_last_turn_scene_diff_text", "") or "",
            )
        else:
            self._total_chars += len(chunk)
            self._append_live_text_to_bubble(chunk)
            self._refresh_scene_panel(
                summary_text=self._extract_primary_response(
                    self._current_bubble.text() if self._current_bubble else ""
                ),
                diff_text=getattr(self.agent, "_last_turn_scene_diff_text", "")
                or "",
            )
        ctx = self.config.get("context_window", 65536)
        try:
            from houdinimind.agent._tokenizer import count_tokens

            approx = count_tokens(
                self._current_bubble.text() if self._current_bubble else chunk
            )
        except Exception:
            approx = self._total_chars // 4
        pct = min(100, int(approx / ctx * 100))
        bar_color = (
            ModernStyles.ACCENT_SUCCESS
            if pct < 60
            else (ModernStyles.ACCENT_WARN if pct < 85 else ModernStyles.ACCENT_DANGER)
        )
        filled = "█" * (pct // 10)
        empty = "░" * (10 - pct // 10)
        self.token_bar.setText(
            f"Context: ~{approx:,} tokens / {ctx:,}  "
            f"<span style='color:{bar_color}'>{filled}{empty}</span>  {pct}%"
        )

    def _on_research_options(self, query: str, options: list):
        if not options:
            return
        if hasattr(self, "_options_widget") and self._options_widget:
            try:
                self._options_widget.hide()
                self.messages_l.removeWidget(self._options_widget)
                self._options_widget.deleteLater()
            except Exception:
                pass

        self._options_widget = ResearchOptionsWidget(
            query, options, parent=self.messages_w
        )
        self._options_widget.option_selected.connect(self._on_option_selected)
        self.messages_l.insertWidget(self._message_insert_index(), self._options_widget)
        self.scroll.verticalScrollBar().setValue(
            self.scroll.verticalScrollBar().maximum()
        )

    def _on_option_selected(self, option: dict, query: str):
        if self._busy or not self.agent:
            return

        label = option.get("label", "Selected Option")

        if hasattr(self, "_options_widget") and self._options_widget:
            self._options_widget.hide()

        self._add_msg("user", f"▶ {label}", "research")
        self._current_bubble = self._add_msg("agent", "", "research")
        self._current_mode = "research"
        self._current_dry_run = False
        self.mode_label.setText("Mode: Executing Option…")
        self._begin_turn_ui(label, "research", dry_run=False)
        self._set_busy(True)

        vision_enabled = getattr(self, "_research_vision_enabled", self._vision_next_enabled())
        fast = False  # research option execution always runs in full mode
        option_runner = lambda progress_cb, status_cb: self.agent.execute_research_option(
            option,
            query,
            progress_cb,
        )
        self._submit_agent_job(
            "research_option",
            self._wrap_turn_overrides(option_runner, vision_enabled, fast),
        )

    def _on_done(self, result: str):
        self._clear_live_stream_queue()
        self._active_job_id = ""
        self._hide_typing_indicator()
        self._last_turn_elapsed_s = max(
            0, int(time.time() - self._current_turn_started_at)
        )
        # Increment turn counter
        self._turn_number = getattr(self, "_turn_number", 0) + 1
        if hasattr(self, "turn_counter_lbl"):
            self.turn_counter_lbl.setText(f"Turn {self._turn_number}")
        # Freeze the elapsed-time badge on the bubble
        if self._current_bubble and hasattr(self._current_bubble, "stop_timer"):
            try:
                self._current_bubble.stop_timer()
            except Exception:
                pass
        self._hide_status()
        self._set_busy(False)
        self._clear_phase_anim()  # after busy=False so chip refresh sees idle
        # Keep turn strip visible after turn ends so user can see the summary
        if hasattr(self, "turn_strip"):
            self.turn_strip.setVisible(True)
        result_text = (result or "").strip()
        self._last_result_text = result_text
        self._last_turn_tools = list(self._current_turn_tools)
        self._last_turn_outputs = list(dict.fromkeys(self._current_turn_outputs))
        self._last_turn_llm_notes = list(self._current_turn_llm_notes)
        if self.agent:
            agent_outputs = getattr(self.agent, "_last_turn_output_paths", []) or []
            if agent_outputs:
                self._last_turn_outputs = list(
                    dict.fromkeys(self._last_turn_outputs + agent_outputs)
                )
        self._last_turn_failures = list(self._current_turn_failures)
        scene_diff_text = (
            getattr(self.agent, "_last_turn_scene_diff_text", "") if self.agent else ""
        )
        summary_text = self._extract_primary_response(result_text, scene_diff_text)
        overview = self._summarize_scene_diff(scene_diff_text)
        status_only_message = self._looks_like_status_message(result_text)
        if status_only_message and self._current_bubble is not None:
            self.messages_l.removeWidget(self._current_bubble)
            self._current_bubble.deleteLater()
            self._current_bubble = None
            self._add_status_notice(result_text, tone="warning")
            summary_text = ""
            overview = result_text
        elif self._current_bubble is not None:
            display_text = summary_text.strip() if summary_text and summary_text.strip() else result_text
            if (
                self._last_turn_llm_notes
                and self.config.get("ui", {}).get("show_llm_trace_history", True)
            ):
                trace_block = "### LLM Trace\n" + "\n".join(
                    f"- {line}" for line in self._last_turn_llm_notes[:12]
                )
                display_text = f"{trace_block}\n\n---\n\n{display_text}".strip()
            # Style bubble red if response is an error or cancellation
            _is_error = any(
                marker in result_text[:80]
                for marker in ("⏹", "⚠️", "Error:", "error:", "cancelled", "Cancelled", "failed", "Failed")
            )
            if _is_error and hasattr(self._current_bubble, "_mode"):
                self._current_bubble._mode = "error"
                # Re-apply container border color
                from houdinimind.agent.ui._widgets import ModernStyles as _MS
                self._current_bubble.container.setStyleSheet(
                    f"QFrame {{ background: #1a0e0e; border-radius: 0px; "
                    f"border-left: 2px solid {_MS.ACCENT_DANGER}; border-top: none; border-right: none; border-bottom: none; }}"
                )
            if hasattr(self._current_bubble, "clear_llm_activity"):
                self._current_bubble.clear_llm_activity()
            self._current_bubble.set_text(display_text)
            # Embed final viewport snapshot inline if the agent captured one
            if self.agent:
                # Viewport screenshot embedding removed — user can see viewport in Houdini directly
                pass
        if self._last_turn_failures:
            overview = (
                f"{overview} • {len(self._last_turn_failures)} issue"
                f"{'s' if len(self._last_turn_failures) != 1 else ''} need review."
            )
        self._refresh_scene_panel(
            mode=self._current_mode,
            dry_run=bool(
                self.agent and getattr(self.agent, "_last_turn_dry_run", False)
            ),
            overview=overview,
            summary_text=summary_text,
            diff_text=scene_diff_text or "",
        )
        self._refresh_tools_panel()
        self._refresh_turn_status(
            "Finished this turn. Review the assistant summary and scene details when you're ready."
        )
        self.scroll.verticalScrollBar().setValue(
            self.scroll.verticalScrollBar().maximum()
        )
        if self._last_turn_failures and self._current_bubble is not None:
            if self._failure_strip is not None:
                try:
                    self.messages_l.removeWidget(self._failure_strip)
                    self._failure_strip.deleteLater()
                except Exception:
                    pass
            self._failure_strip = FailureActionStrip(len(self._last_turn_failures))
            self._failure_strip.retry_requested.connect(self._retry_last_failed_turn)
            self._failure_strip.diagnostics_requested.connect(
                self._show_turn_diagnostics
            )
            insert_index = self._message_insert_index()
            self.messages_l.insertWidget(
                insert_index,
                self._failure_strip,
                0,
                QtCore.Qt.AlignLeft,
            )
        if (
            self._current_mode in ("chat", "vision", "research", "autoresearch")
            and not status_only_message
        ):
            self.accept_btn.setEnabled(True)
            self.reject_btn.setEnabled(True)
        self._update_feedback_visibility()
        if hasattr(self, "composer_autoresearch_action"):
            self.composer_autoresearch_action.setChecked(
                bool(getattr(self, "_autoresearch_running", False))
            )

    def _retry_last_failed_turn(self):
        if self._busy:
            return
        prompt = (self._last_user_request or "").strip()
        if not prompt:
            self._add_status_notice("No previous request to retry.", tone="warning")
            return
        for marker in ("[Dry Run] ", "[Image] ", "[Network] "):
            prompt = prompt.replace(marker, "")
        self.input_box.setPlainText(prompt.strip())
        self._send()

    def _show_turn_diagnostics(self):
        self._set_detail_mode("advanced")
        if hasattr(self, "inspector_tabs"):
            self.inspector_tabs.setCurrentIndex(self.tools_tab_index)
        self._refresh_turn_status("Diagnostics opened for the last failed turn.")

    def _on_tool_display(self, tool_name, args, result):
        tool_entry = {"name": tool_name, "args": args or {}, "result": result or {}}
        self._current_turn_tools.append(tool_entry)

        message = (result or {}).get("message", "")
        if (result or {}).get("status") == "error":
            self._current_turn_failures.append(
                f"{tool_name}: {message or 'Unknown error'}"
            )

        data = (result or {}).get("data") or {}
        output_path = data.get("output_path") or data.get("path")
        if output_path and output_path not in self._current_turn_outputs:
            if tool_name in ("finalize_sop_network", "set_display_flag", "create_node"):
                self._current_turn_outputs.append(output_path)

        tool_status = f"Running `{tool_name}`…"
        self._show_status(tool_status)
        self._refresh_turn_status(tool_status)
        self._refresh_tools_panel()
        self._refresh_scene_panel(
            overview=f"Latest step: {tool_name}",
            summary_text=self._extract_primary_response(
                self._current_bubble.text() if self._current_bubble else ""
            ),
            diff_text=getattr(self.agent, "_last_turn_scene_diff_text", "") or "",
        )

        if not self.config.get("ui", {}).get("show_tool_calls", True):
            return
        if self._current_tool_group is None:
            self._clear_layout_widgets(self.tools_l)
            self._current_tool_group = ToolActivityGroup(self.tools_w)
            self.tools_l.addWidget(self._current_tool_group)
            self.tools_l.addStretch()
        self._current_tool_group.add_tool_call(tool_name, args, result)
        self.tools_scroll.verticalScrollBar().setValue(
            self.tools_scroll.verticalScrollBar().maximum()
        )

    def _show_confirm_dialog(self, description: str):
        if not self.agent:
            return
        reply = QtWidgets.QMessageBox.question(
            self,
            "⚠️ Destructive Action — Confirm?",
            f"The agent wants to:\n\n{description}\n\nA backup has already been created.\nAllow?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        self.agent.resolve_confirmation(reply == QtWidgets.QMessageBox.Yes)

    def _show_error_banner(self, node_path: str, error_msg: str):
        pass

    def _diagnose_error_from_banner(self, node_path: str, error_msg: str):
        if not self.agent:
            return
        self._dispatch_chat(f"Diagnose this error on {node_path}: {error_msg}")

    def _fix_error_from_banner(self, node_path: str, error_msg: str):
        if not self.agent:
            return
        self._dispatch_research(
            f"Fix this error on {node_path}:\n{error_msg}\n\nInvestigate and execute the solution to fix this issue."
        )
