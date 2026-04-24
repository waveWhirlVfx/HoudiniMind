# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
import os
import time

from PySide6 import QtWidgets, QtGui, QtCore

from ._widgets import ModernStyles, HOU_AVAILABLE


class PanelStateMixin:
    def _active_job_snapshot(self) -> dict:
        if not getattr(self, "job_manager", None):
            return {}
        job_id = getattr(self, "_active_job_id", "") or ""
        if not job_id:
            return {}
        try:
            return self.job_manager.get(job_id) or {}
        except Exception:
            return {}

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

    def _format_elapsed(self, started_at: float) -> str:
        if not started_at:
            return "00:00"
        total = max(0, int(time.time() - started_at))
        return f"{total // 60:02d}:{total % 60:02d}"

    @staticmethod
    def _format_elapsed_seconds(total_seconds: int) -> str:
        total = max(0, int(total_seconds))
        return f"{total // 60:02d}:{total % 60:02d}"

    @staticmethod
    def _elide_text(widget: QtWidgets.QWidget, text: str) -> str:
        if not text:
            return ""
        try:
            width = max(40, widget.width())
            metrics = QtGui.QFontMetrics(widget.font())
            return metrics.elidedText(text, QtCore.Qt.TextElideMode.ElideRight, width)
        except Exception:
            return text[:140]

    def _clear_layout_widgets(self, layout: QtWidgets.QLayout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            child_layout = item.layout()
            if widget is not None:
                widget.deleteLater()
            elif child_layout is not None:
                self._clear_layout_widgets(child_layout)

    def _message_insert_index(self) -> int:
        if not hasattr(self, "messages_l"):
            return 0
        # Defensive cleanup: old sessions may still have a trailing stretch/spacer.
        while self.messages_l.count() > 0:
            last_item = self.messages_l.itemAt(self.messages_l.count() - 1)
            if last_item is None or last_item.spacerItem() is None:
                break
            self.messages_l.takeAt(self.messages_l.count() - 1)
        return self.messages_l.count()

    @staticmethod
    def _turn_placeholder_text(mode: str, dry_run: bool = False) -> str:
        base = {
            "chat": "Planning the next step and preparing the scene actions.",
            "vision": "Inspecting the current view and deciding what to do next.",
            "research": "Breaking the task down and lining up the next actions.",
            "autoresearch": "Generating next training task and preparing to build it.",
        }.get(mode or "chat", "Thinking through the request and preparing the next step.")
        return f"[Dry Run] {base}" if dry_run else base

    def _set_detail_mode(self, mode: str):
        self._detail_mode = "advanced" if mode == "advanced" else "simple"
        self._apply_view_mode()

    def _toggle_details_panel(self, checked: bool = False):
        if checked:
            self._set_focus_mode(False)
            self._set_detail_mode("advanced")
        else:
            self._set_detail_mode("simple")

    def _toggle_focus_mode(self):
        self._focus_mode = not self._focus_mode
        self._apply_view_mode()

    def _set_focus_mode(self, enabled: bool):
        self._focus_mode = bool(enabled)
        self._apply_view_mode()

    def _toggle_settings_panel(self):
        if not hasattr(self, "settings_panel"):
            return
        next_visible = self.settings_panel.isHidden()
        self.settings_panel.setVisible(next_visible)
        if next_visible:
            # Reposition overlay in case widget was resized
            if hasattr(self, "_reposition_overlays"):
                self._reposition_overlays()
            self.settings_panel.raise_()
        if hasattr(self, "settings_toggle_btn"):
            self.settings_toggle_btn.setChecked(next_visible)

    def _set_quick_prompts_visible(self, visible: bool):
        self._show_quick_prompts = bool(visible)
        self._apply_view_mode()

    def _update_feedback_visibility(self):
        visible = bool(
            hasattr(self, "accept_btn")
            and hasattr(self, "reject_btn")
            and (self.accept_btn.isEnabled() or self.reject_btn.isEnabled())
        )
        if hasattr(self, "accept_btn"):
            self.accept_btn.setVisible(visible)
        if hasattr(self, "reject_btn"):
            self.reject_btn.setVisible(visible)
        if hasattr(self, "feedback_bar"):
            self.feedback_bar.setVisible(visible)
        target_bubble = self._current_bubble if visible else None
        self._place_feedback_bar(target_bubble)

    def _place_feedback_bar(self, bubble=None):
        if not hasattr(self, "feedback_bar"):
            return
        current_owner = getattr(self, "_feedback_owner_bubble", None)
        if current_owner is bubble:
            return
        if current_owner is not None:
            current_owner.clear_footer_widget()
        self._feedback_owner_bubble = None
        if bubble is None:
            self.feedback_bar.setParent(self.feedback_host)
            self.feedback_bar.setVisible(False)
            return
        bubble.set_footer_widget(self.feedback_bar)
        self.feedback_bar.setVisible(True)
        self._feedback_owner_bubble = bubble

    def _update_empty_state_visibility(self):
        if not hasattr(self, "chat_stack"):
            return
        self.chat_stack.setCurrentIndex(1 if self._has_conversation_content else 0)

    def _refresh_header_meta(self):
        if not hasattr(self, "header_status_lbl"):
            return
        if (
            hasattr(self, "conn_status")
            and getattr(self.conn_status.retry_btn, "isVisible", lambda: False)()
        ):
            # Red dot only — no text, no background box
            self.header_status_lbl.setText("●")
            self.header_status_lbl.setStyleSheet(
                "color: #c05050; font-size: 13px; background: transparent; padding: 0;"
            )
            self.header_status_lbl.setToolTip("Ollama not reachable — run: ollama serve")
            return
        chat_model = (
            self.chat_model_combo.current_model()
            if hasattr(self, "chat_model_combo")
            else ""
        )
        vision_model = (
            self.vision_model_combo.current_model()
            if hasattr(self, "vision_model_combo")
            else ""
        )
        bits = ["Ollama connected"]
        if chat_model:
            bits.append(f"Chat: {chat_model}")
        if vision_model:
            bits.append(f"Vision: {vision_model}")
        # Green dot only — tooltip shows the details on hover
        self.header_status_lbl.setText("●")
        self.header_status_lbl.setStyleSheet(
            "color: #5aaa78; font-size: 13px; background: transparent; padding: 0;"
        )
        self.header_status_lbl.setToolTip(" • ".join(bits))

    def _apply_view_mode(self):
        simple = self._detail_mode == "simple"
        inspector_visible = (not simple) and (not self._focus_mode)
        if hasattr(self, "simple_mode_btn"):
            self.simple_mode_btn.setChecked(simple)
        if hasattr(self, "advanced_mode_btn"):
            self.advanced_mode_btn.setChecked(not simple)
        if hasattr(self, "focus_mode_btn"):
            self.focus_mode_btn.setChecked(self._focus_mode)
        if hasattr(self, "details_toggle_btn"):
            self.details_toggle_btn.setChecked(inspector_visible)
        if hasattr(self, "settings_toggle_btn") and hasattr(self, "settings_panel"):
            self.settings_toggle_btn.setChecked(not self.settings_panel.isHidden())
        if hasattr(self, "focus_mode_action"):
            self.focus_mode_action.setChecked(self._focus_mode)
        if hasattr(self, "quick_prompts_action"):
            self.quick_prompts_action.setChecked(self._show_quick_prompts)
        if hasattr(self, "inspector_tabs"):
            self.inspector_tabs.setVisible(inspector_visible)
        # model_bar, conn_status, quick_bar, top_details_panel are overlays —
        # they are never in the root layout so no visibility change needed here.
        if hasattr(self, "turn_strip"):
            self.turn_strip.setVisible(False)
        if hasattr(self, "token_bar"):
            self.token_bar.setVisible(True)
        if hasattr(self, "settings_panel") and self._focus_mode:
            # Hide settings overlay when focus mode enabled
            self.settings_panel.setVisible(False)
        if hasattr(self, "workspace_splitter"):
            if inspector_visible:
                self.workspace_splitter.setSizes(self._last_workspace_sizes)
            else:
                current_sizes = self.workspace_splitter.sizes()
                if len(current_sizes) == 2 and current_sizes[1] > 0:
                    self._last_workspace_sizes = current_sizes
                total = sum(current_sizes) or sum(self._last_workspace_sizes) or 1120
                self.workspace_splitter.setSizes([total, 0])
        self._refresh_header_meta()
        self._refresh_action_availability()

    def _refresh_action_availability(self):
        has_agent = bool(getattr(self, "agent", None))
        has_memory = bool(getattr(self, "memory", None))
        has_conversation = bool(self._has_conversation_content)
        if has_agent and not has_conversation:
            try:
                has_conversation = bool(getattr(self.agent, "conversation", None))
            except Exception:
                has_conversation = False

        debug_log_path = ""
        if has_agent and getattr(self.agent, "debug_logger", None):
            try:
                debug_log_path = self.agent.debug_logger.get_session_path() or ""
            except Exception:
                debug_log_path = ""
        has_debug_log = bool(debug_log_path and os.path.isfile(debug_log_path))

        can_general = has_agent and (not self._busy)
        can_scene = not self._busy
        can_memory = (not self._busy) and has_memory
        can_history = (not self._busy) and has_conversation

        controls = {
            "more_actions_btn": not self._busy,
            "refresh_models_btn": not self._busy,
            "mic_btn": not self._busy,
            "scene_btn": can_scene,
            "sync_scene_action": can_scene,
            "composer_sync_scene_action": can_scene,
            "network_inspect_btn": can_scene,
            "inspect_network_action": can_scene,
            "composer_inspect_network_action": can_scene,
            "undo_btn": can_general,
            "undo_action": can_general,
            "learn_btn": can_memory,
            "learn_action": can_memory,
            "hda_btn": can_scene,
            "index_hda_action": can_scene,
            "recipes_btn": can_memory,
            "recipes_action": can_memory,
            "export_btn": can_history,
            "export_action": can_history,
            "clear_btn": can_history,
            "clear_chat_action": can_history,
            "debug_log_btn": has_debug_log,
            "debug_log_action": has_debug_log,
        }
        for name, enabled in controls.items():
            control = getattr(self, name, None)
            if control is not None:
                try:
                    control.setEnabled(bool(enabled))
                except Exception:
                    pass

    def _begin_turn_ui(self, user_text: str, mode: str, dry_run: bool = False):
        if getattr(self, "_failure_strip", None) is not None:
            try:
                self.messages_l.removeWidget(self._failure_strip)
                self._failure_strip.deleteLater()
            except Exception:
                pass
            self._failure_strip = None
        self._current_tool_group = None
        self._current_turn_tools = []
        self._current_turn_outputs = []
        self._current_turn_failures = []
        self._current_turn_llm_notes = []
        self._last_live_progress_line = ""
        self._last_bubble_trace_content = ""
        self._live_stream_text = ""
        if hasattr(self, "_clear_live_stream_queue"):
            self._clear_live_stream_queue()
        self._current_turn_started_at = time.time()
        self._last_turn_elapsed_s = 0
        self._last_user_request = (user_text or "").strip()
        self._last_result_text = ""
        self.accept_btn.setEnabled(False)
        self.reject_btn.setEnabled(False)
        self._update_feedback_visibility()
        if self._current_bubble and not self._current_bubble.text().strip():
            self._current_bubble.set_text(self._turn_placeholder_text(mode, dry_run))
        # Start the live elapsed timer on the agent bubble
        if self._current_bubble and hasattr(self._current_bubble, "start_timer"):
            try:
                self._current_bubble.start_timer()
            except Exception:
                pass
        if hasattr(self, "thought_label"):
            self.thought_label.setText("")
        self._refresh_tools_panel(reset=True)
        self._refresh_scene_panel(
            mode=mode,
            dry_run=dry_run,
            overview="Planning the next step…",
            summary_text="",
            diff_text="",
        )
        self._refresh_turn_status(
            "Mapping out the request and preparing the next action."
        )
        # Show planning animation below the agent bubble
        self._set_phase_anim("planning")

    # ── Phase animation below agent bubble ───────────────────────────

    def _set_phase_anim(self, phase: str) -> None:
        """Phase animation row intentionally disabled (status now lives in-bubble)."""
        self._clear_phase_anim()
        return

    def _clear_phase_anim(self) -> None:
        anim = getattr(self, "_phase_anim", None)
        if anim:
            try:
                anim.stop()
                self.messages_l.removeWidget(anim)
                anim.deleteLater()
            except Exception:
                pass
            self._phase_anim = None

    def _refresh_progress_chips(self):
        chips = [
            getattr(self, "progress_planning_chip", None),
            getattr(self, "progress_building_chip", None),
            getattr(self, "progress_verifying_chip", None),
        ]
        if any(chip is None for chip in chips):
            return
        planning, building, verifying = chips
        state = "idle"
        if self._busy and len(self._current_turn_tools) == 0:
            state = "planning"
        elif self._busy and len(self._current_turn_tools) > 0:
            state = "building"
        elif self._busy and self._last_result_text:
            # verifying only while the turn is still in progress
            state = "verifying"

        def _chip_style(active: bool, done: bool = False, warn: bool = False) -> str:
            if warn:
                return (
                    f"background: #3a3024; color: {ModernStyles.ACCENT_WARN}; "
                    f"border: 1px solid {ModernStyles.ACCENT_WARN}88; border-radius: 999px; padding: 2px 8px; font-size: 10px; font-weight: 700;"
                )
            if active:
                return (
                    f"background: {ModernStyles.ACCENT}22; color: {ModernStyles.ACCENT}; "
                    f"border: 1px solid {ModernStyles.ACCENT}77; border-radius: 999px; padding: 2px 8px; font-size: 10px; font-weight: 700;"
                )
            if done:
                return (
                    f"background: #24342a; color: {ModernStyles.ACCENT_SUCCESS}; "
                    f"border: 1px solid {ModernStyles.ACCENT_SUCCESS}77; border-radius: 999px; padding: 2px 8px; font-size: 10px; font-weight: 700;"
                )
            return (
                f"background: transparent; color: {ModernStyles.TEXT_SUBTLE}44; "
                f"border: 1px solid {ModernStyles.BORDER_SOFT}44; border-radius: 999px; padding: 2px 8px; font-size: 10px; font-weight: 600;"
            )

        planning_done = state in ("building", "verifying")
        building_done = state == "verifying"
        has_failures = bool(self._current_turn_failures if self._busy else self._last_turn_failures)

        # Swap phase animation when state changes
        current_anim = getattr(self, "_phase_anim", None)
        current_phase = getattr(current_anim, "_phase", None) if current_anim else None
        if state in ("planning", "building", "verifying") and state != current_phase:
            self._set_phase_anim(state)
        elif state == "idle":
            self._clear_phase_anim()

        # Show chips only when there is something to show — hide all when idle
        if state == "idle":
            planning.setVisible(False)
            building.setVisible(False)
            verifying.setVisible(False)
        else:
            planning.setVisible(True)
            building.setVisible(state in ("building", "verifying"))
            verifying.setVisible(state == "verifying")
            planning.setStyleSheet(_chip_style(state == "planning", done=planning_done))
            building.setStyleSheet(_chip_style(state == "building", done=building_done))
            verifying.setStyleSheet(
                _chip_style(state == "verifying", done=state == "verifying", warn=has_failures)
            )

    def _refresh_turn_status(self, latest_message: str = ""):
        job_state = self._active_job_snapshot() if self._busy else {}
        if latest_message:
            self.turn_status_lbl.setToolTip(latest_message)
            self.turn_status_lbl.setText(
                self._elide_text(self.turn_status_lbl, latest_message)
            )
        elif job_state.get("latest_substate"):
            substate = job_state.get("latest_substate")
            self.turn_status_lbl.setToolTip(substate)
            self.turn_status_lbl.setText(self._elide_text(self.turn_status_lbl, substate))
        tool_count = len(self._current_turn_tools)
        failure_count = len(
            self._current_turn_failures if self._busy else self._last_turn_failures
        )
        elapsed = (
            self._format_elapsed(self._current_turn_started_at)
            if self._busy
            else self._format_elapsed_seconds(self._last_turn_elapsed_s)
        )
        mode_name = {
            "chat": "Chat",
            "vision": "Vision",
            "research": "Research",
            "autoresearch": "Train",
        }.get(self._current_mode, self._current_mode.title())
        if self._busy:
            meta = f"{mode_name} • {tool_count} step{'s' if tool_count != 1 else ''} • {elapsed}"
            if job_state.get("status"):
                meta += f" • {job_state.get('status')}"
        elif self._last_result_text or self._last_user_request:
            n = len(self._last_turn_tools)
            meta = f"{n} step{'s' if n != 1 else ''} • {elapsed}"
        else:
            meta = "Ready"
        if self._current_dry_run or (
            self.agent
            and getattr(self.agent, "_last_turn_dry_run", False)
            and not self._busy
        ):
            meta += " • Dry Run"
        self.turn_meta_lbl.setToolTip(meta)
        self.turn_meta_lbl.setText(self._elide_text(self.turn_meta_lbl, meta))
        if hasattr(self, "turn_warning_lbl"):
            if failure_count:
                self.turn_warning_lbl.setText(
                    f"{failure_count} issue{'s' if failure_count != 1 else ''} to review"
                )
                self.turn_warning_lbl.setStyleSheet(
                    f"color: {ModernStyles.ACCENT_WARN}; font-size: 10px;"
                )
            elif self._busy:
                self.turn_warning_lbl.setText("In progress")
                self.turn_warning_lbl.setStyleSheet(
                    f"color: {ModernStyles.ACCENT}; font-size: 10px;"
                )
            else:
                self.turn_warning_lbl.setText("Ready")
                self.turn_warning_lbl.setStyleSheet(
                    f"color: {ModernStyles.TEXT_DIM}; font-size: 10px;"
                )
        self._refresh_progress_chips()

    def _refresh_tools_panel(self, reset: bool = False):
        if not hasattr(self, "tools_summary_lbl"):
            return
        if reset:
            self._clear_layout_widgets(self.tools_l)
            self.tools_empty_lbl = QtWidgets.QLabel(
                "No tool activity for this turn yet."
            )
            self.tools_empty_lbl.setStyleSheet(
                f"color: {ModernStyles.TEXT_DIM}; font-size: 11px; font-style: italic;"
            )
            self.tools_empty_lbl.setWordWrap(True)
            self.tools_l.addWidget(self.tools_empty_lbl)
            self.tools_l.addStretch()
        tool_count = len(self._current_turn_tools)
        failure_count = len(self._current_turn_failures)
        latest = (
            self._current_turn_tools[-1]["name"] if self._current_turn_tools else ""
        )
        if tool_count == 0:
            summary = "Tool activity for the current turn will appear here."
        else:
            summary = f"{tool_count} step{'s' if tool_count != 1 else ''}"
            if failure_count:
                summary += (
                    f" • {failure_count} issue{'s' if failure_count != 1 else ''}"
                )
            if latest:
                summary += f" • latest: {latest}"
        self.tools_summary_lbl.setText(summary)
        tab_label = f"Tools ({tool_count})" if tool_count else "Tools"
        if hasattr(self, "inspector_tabs"):
            self.inspector_tabs.setTabText(self.tools_tab_index, tab_label)

    def _refresh_scene_panel(
        self,
        mode: str = "",
        dry_run: bool = False,
        overview: str = "",
        summary_text: str = "",
        diff_text: str = "",
    ):
        if not hasattr(self, "scene_overview_lbl"):
            return
        current_mode = mode or self._current_mode or "chat"
        failures = (
            self._current_turn_failures if self._busy else self._last_turn_failures
        )
        review = "Needs review" if failures else "No warnings"
        if self._busy and not overview:
            overview = (
                "Working through the build and keeping the final output on track."
            )
        if not overview and self._last_result_text:
            overview = self._summarize_scene_diff(
                diff_text or getattr(self.agent, "_last_turn_scene_diff_text", "")
            )
        if not overview:
            overview = "No scene changes yet."
        self.scene_overview_lbl.setText(overview)

        outputs = self._current_turn_outputs if self._busy else self._last_turn_outputs
        job_state = self._active_job_snapshot() if self._busy else {}
        if self.agent and not self._busy:
            agent_outputs = getattr(self.agent, "_last_turn_output_paths", []) or []
            if agent_outputs:
                outputs = list(dict.fromkeys(outputs + agent_outputs))
        output_text = ", ".join(outputs[:4]) if outputs else "—"
        request_text = self._last_user_request or "—"
        checkpoint_text = "—"
        verification_text = "—"
        if self._busy and job_state.get("checkpoints"):
            checkpoint_text = job_state["checkpoints"][-1]
        if self.agent and not self._busy:
            checkpoint_text = (
                getattr(self.agent, "_last_turn_checkpoint_path", "") or "—"
            )
            verification_text = (
                getattr(self.agent, "_last_turn_verification_text", "") or "—"
            )
        mode_label = {
            "chat": "Chat",
            "vision": "Vision",
            "research": "Research",
        }.get(current_mode, current_mode.title())
        if dry_run:
            review = f"{review} • Dry Run"
        self.scene_meta_lbl.setText(
            f"Request: {request_text}\n"
            f"Mode: {mode_label}\n"
            f"Output: {output_text}\n"
            f"Review: {review}\n"
            f"Checkpoint: {checkpoint_text}"
        )
        self.scene_summary_box.setPlainText(summary_text or "")
        combined_diff = diff_text or ""
        if verification_text and verification_text != "—":
            combined_diff = (
                verification_text + ("\n\n" + combined_diff if combined_diff else "")
            ).strip()
        self.scene_diff_box.setPlainText(combined_diff)
        warning_count = len(failures)
        scene_tab_name = f"Scene ({warning_count})" if warning_count else "Scene"
        if hasattr(self, "inspector_tabs"):
            self.inspector_tabs.setTabText(self.scene_tab_index, scene_tab_name)

    def _refresh_memory_panel(self):
        if not hasattr(self, "memory_stats_lbl"):
            return
        if not self.memory:
            self.memory_stats_lbl.setText("Memory is unavailable in this session.")
            self.memory_recipes_box.setPlainText("")
            return
        try:
            dash = self.memory.dashboard() or {}
            log_stats = dash.get("log", {}) or {}
            recipe_stats = dash.get("recipes", {}) or {}
            rule_stats = dash.get("project_rules", {}) or {}
            self.memory_stats_lbl.setText(
                f"Interactions: {log_stats.get('total_interactions', 0)} • "
                f"Accepted: {log_stats.get('accepted', 0)} • "
                f"Recipes: {recipe_stats.get('total_recipes', 0)} • "
                f"Rules: {rule_stats.get('total_rules', 0)}"
            )
            recipes = self.memory.get_recipes()[:8]
            rules = []
            if hasattr(self.memory, "get_project_rules"):
                rules = self.memory.get_project_rules(limit=6)
            preview = []
            if rules:
                preview.append("[Project Rules]")
                for rule in rules:
                    preview.append(f"- {rule.get('rule', '')}")
                preview.append("")
            if recipes:
                preview.append("[Learned Recipes]")
                for recipe in recipes:
                    name = (
                        recipe.get("name") or recipe.get("title") or "Untitled recipe"
                    )
                    domain = recipe.get("domain", "general")
                    confidence = recipe.get("confidence")
                    confidence_text = ""
                    if isinstance(confidence, (int, float)):
                        confidence_text = f" ({confidence:.2f})"
                    preview.append(f"- {name} [{domain}]{confidence_text}")
            if preview:
                self.memory_recipes_box.setPlainText("\n".join(preview))
            else:
                self.memory_recipes_box.setPlainText("No learned recipes yet.")
        except Exception as e:
            self.memory_stats_lbl.setText(f"Memory refresh failed: {e}")
            self.memory_recipes_box.setPlainText("")
