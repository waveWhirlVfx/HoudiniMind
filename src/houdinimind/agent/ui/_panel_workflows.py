# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
import datetime
import json
import os
import threading
import traceback

from PySide6 import QtWidgets, QtCore

from ._widgets import (
    HOU_AVAILABLE,
    MessageBubble,
    StatusNoticeWidget,
    FeedbackChip,
    DebugLogDialog,
    RecipeBrowserDialog,
    TypingIndicator,
)

try:
    import hou
except ImportError:
    hou = None


class PanelWorkflowMixin:
    def _inject_scene(self, silent: bool = False):
        if self._busy and not silent:
            self._add_system_note(
                "Sync Scene is unavailable while another turn is running."
            )
            self._refresh_turn_status(
                "Finish or stop the current turn before syncing the live scene."
            )
            return
        if not self.agent or not HOU_AVAILABLE:
            if not silent:
                self._add_system_note(
                    "Sync Scene only works inside Houdini with a live scene."
                )
                self._refresh_turn_status("Scene sync is unavailable outside Houdini.")
            return
        try:
            from houdinimind.bridge.scene_reader import SceneReader

            scene_json = SceneReader().snapshot_json()
            self.agent.inject_scene_context(scene_json)
            if not silent:
                summary = "📡 Scene context injected — agent now has live scene state."
                try:
                    scene_data = json.loads(scene_json or "{}")
                    node_count = int(scene_data.get("node_count", 0) or 0)
                    connection_count = len(scene_data.get("connections", []) or [])
                    selected = scene_data.get("selected_nodes", []) or []
                    error_count = int(scene_data.get("error_count", 0) or 0)
                    selected_preview = ", ".join(selected[:2]) if selected else "none"
                    summary = (
                        f"📡 Scene synced: {node_count} nodes, {connection_count} links, "
                        f"{error_count} error/warning node(s), selected: {selected_preview}."
                    )
                except Exception:
                    pass
                self._add_system_note(summary)
                self._refresh_turn_status("Scene context synced successfully.")
        except Exception as e:
            if not silent:
                self._add_system_note(f"Scene inject failed: {e}")
                self._refresh_turn_status(
                    "Scene sync failed. Check the debug log for the snapshot error."
                )

    def _clear_conversation(self):
        reply = QtWidgets.QMessageBox.question(
            self,
            "Clear Conversation",
            "Clear the entire chat history?\n(Cannot be undone.)",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return
        if self.agent:
            self.agent.reset_conversation()
        self.accept_btn.setEnabled(False)
        self.reject_btn.setEnabled(False)
        self._update_feedback_visibility()
        while self.messages_l.count():
            item = self.messages_l.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self._current_turn_tools = []
        self._last_turn_tools = []
        self._current_turn_outputs = []
        self._last_turn_outputs = []
        self._current_turn_failures = []
        self._last_turn_failures = []
        self._last_user_request = ""
        self._last_result_text = ""
        self._current_turn_started_at = 0.0
        self._last_turn_elapsed_s = 0
        self._current_tool_group = None
        self._current_bubble = None
        self._has_conversation_content = False
        self._refresh_tools_panel(reset=True)
        self._refresh_scene_panel(
            overview="No scene changes yet.", summary_text="", diff_text=""
        )
        self._refresh_memory_panel()
        self._refresh_turn_status("Waiting for your next request.")
        self._total_chars = 0
        self.token_bar.setText("Context: 0 tokens")
        self._update_empty_state_visibility()
        # Hide turn strip — fresh conversation, nothing to report
        if hasattr(self, "turn_strip"):
            self.turn_strip.setVisible(False)
        self._status("Conversation cleared.")

    def _run_learning_cycle(self):
        if not self.memory:
            QtWidgets.QMessageBox.information(
                self, "Learning", "MemoryManager not available."
            )
            return
        self.learn_btn.setEnabled(False)
        self.learn_btn.setText("⚡ Learning…")

        def _run():
            try:
                stats = self.memory.run_learning_cycle()
                if self.agent:
                    self.agent.reload_system_prompt()
                    self.agent.reload_knowledge()
                msg = (
                    f"✅ Learning cycle complete\n"
                    f"New recipes: {stats.get('new_recipes', 0)}\n"
                    f"Total: {stats.get('recipe_stats', {}).get('total_recipes', '?')}"
                )
                if stats.get("kb_rebuilt"):
                    msg += "\nKnowledge base refreshed"
                if stats.get("kb_error"):
                    msg += f"\nKB refresh warning: {stats['kb_error']}"
            except Exception as e:
                msg = f"Learning cycle failed: {e}"
            self.sig_status.emit(msg)

        called = [False]

        def _done(msg):
            if called[0]:
                return
            called[0] = True
            try:
                self.sig_status.disconnect(_done)
            except Exception:
                pass
            self.learn_btn.setEnabled(True)
            self.learn_btn.setText("⚡ Learn")
            self._add_system_note(msg)
            self._refresh_memory_panel()

        self.sig_status.connect(_done)
        threading.Thread(target=_run, daemon=True).start()

    def _learn_hda(self):
        if not HOU_AVAILABLE:
            return
        selected = hou.selectedNodes()
        if not selected:
            QtWidgets.QMessageBox.information(self, "Learn HDA", "Select a node first.")
            return
        node = selected[0]
        try:
            from houdinimind.rag.kb_builder import build_kb

            node_type_name = node.type().name()
            # Add a minimal entry to the KB JSON directly, then rebuild
            data_dir = self.config.get("data_dir", "")
            kb_path = os.path.join(data_dir, "knowledge", "knowledge_base.json")
            try:
                with open(kb_path, "r", encoding="utf-8") as f:
                    kb_data = json.load(f)
            except Exception:
                kb_data = {"version": 2, "entries": []}

            # Check if already indexed
            existing_titles = {
                e.get("title", "") for e in kb_data.get("entries", [])
            }
            entry_title = f"HDA Node: {node_type_name}"
            if entry_title in existing_titles:
                self._add_system_note(
                    f"📦 {node_type_name} already in knowledge base."
                )
                return

            # Build entry from live node info
            parms_info = []
            for parm in node.parms()[:50]:
                try:
                    parms_info.append(f"{parm.name()}: {parm.eval()}")
                except Exception:
                    pass
            new_entry = {
                "title": entry_title,
                "category": "nodes",
                "tags": ["hda", node_type_name, "indexed"],
                "content": (
                    f"Node Type: {node_type_name}\n"
                    f"Description: {node.type().description()}\n"
                    f"Parameters:\n" + "\n".join(f"- {p}" for p in parms_info)
                ),
                "_source": "hda_index",
            }
            kb_data.setdefault("entries", []).append(new_entry)
            with open(kb_path, "w", encoding="utf-8") as f:
                json.dump(kb_data, f, indent=2, ensure_ascii=False)

            self._add_system_note(
                f"📦 Added to knowledge base: {node_type_name}\n"
                f"Title: {entry_title}"
            )
            # Rebuild KB index and reload backend on a background thread
            self._add_system_note(f"📦 Indexing {node_type_name} — reloading backend…")
            threading.Thread(target=self._setup_backend, daemon=True).start()
        except Exception as e:
            self._add_system_note(f"Learn HDA failed: {e}")

    def _show_recipes(self):
        if not self.memory:
            QtWidgets.QMessageBox.information(
                self, "Recipes", "MemoryManager not available."
            )
            return
        RecipeBrowserDialog(self.memory, parent=self).exec()

    def _toggle_autoresearch(self):
        if self._autoresearch_running:
            self._stop_autoresearch()
        else:
            self._start_autoresearch()

    def _start_autoresearch(self):
        if self._busy:
            self._add_system_note(
                "Cannot start AutoResearch while another task is running."
            )
            return
        if not self.agent:
            self._add_system_note("AutoResearch requires the agent to be ready.")
            return

        try:
            from houdinimind.agent.autoresearch_loop import AutoResearchLoop

            data_dir = self.config.get("data_dir", "")
            self._autoresearch_loop = AutoResearchLoop(
                agent_loop=self.agent,
                memory_manager=self.memory,
                data_dir=data_dir,
            )
        except Exception as e:
            self._add_system_note(f"AutoResearch init failed: {e}")
            traceback.print_exc()
            return

        self._autoresearch_running = True
        self.autoresearch_btn.setChecked(True)
        self.autoresearch_btn.setText("Stop")
        self.autoresearch_action.setChecked(True)
        if hasattr(self, "composer_autoresearch_action"):
            self.composer_autoresearch_action.setChecked(True)
        self._current_mode = "autoresearch"
        self.mode_label.setText("Mode: Train")

        self._add_msg(
            "user", "[Train] Starting agent training loop", "chat"
        )
        self._current_bubble = self._add_msg("agent", "", "chat")
        self._begin_turn_ui("[Train]", "chat", dry_run=False)
        self._set_busy(True)

        for btn in (
            self.send_btn,
            self.research_btn,
            self.attach_btn,
            self.mic_btn,
            self.vision_toggle_btn,
            self.fast_toggle_btn,
            self.dry_run_btn,
            self.composer_actions_btn,
        ):
            btn.setEnabled(False)
        self.autoresearch_btn.setEnabled(True)
        self.stop_btn.setVisible(True)

        def _run():
            try:
                self._autoresearch_loop.run(
                    stream_callback=self.sig_stream_chunk.emit,
                    tool_callback=lambda name, args, result: self.sig_tool_called.emit(
                        name, args, result
                    ),
                    progress_callback=lambda data: self.sig_autoresearch_progress.emit(
                        data
                    ),
                )
            except Exception as e:
                self.sig_stream_chunk.emit(f"\n\n⚠️ **Train Error:** {e}\n")
                traceback.print_exc()
            self.sig_response_done.emit("Training session complete.")

        threading.Thread(target=_run, daemon=True, name="autoresearch-loop").start()

    def _stop_autoresearch(self):
        if self._autoresearch_loop:
            self._autoresearch_loop.stop()
            self._add_system_note(
                "⏹ Train stop requested — finishing current task…"
            )
            self._refresh_turn_status(
                "Stopping training after the current task completes."
            )
        self._autoresearch_running = False
        self.autoresearch_btn.setChecked(False)
        self.autoresearch_btn.setText("Train")
        self.autoresearch_action.setChecked(False)
        if hasattr(self, "composer_autoresearch_action"):
            self.composer_autoresearch_action.setChecked(False)

    def _on_autoresearch_progress(self, data: dict):
        event = data.get("event", "")
        if event == "started":
            self.mode_label.setText("Mode: Train (running)")
            self.header_status_lbl.setText(
                f"Train • {data.get('lessons', 0)} lessons in memory"
            )
        elif event == "task_start":
            name = data.get("task_name", "?")
            idx = data.get("task_index", 0)
            level = data.get("task_level", 1)
            self.mode_label.setText(f"Train: {name} [#{idx}]")
            self.header_status_lbl.setText(f"Task: {name} (Level {level})")
            self._refresh_turn_status(f"Training — building: {name}")
        elif event == "attempt_start":
            name = data.get("task_name", "?")
            attempt = data.get("attempt", 1)
            max_attempts = data.get("max_attempts", 3)
            self._refresh_turn_status(
                f"Building {name} — attempt {attempt}/{max_attempts}"
            )
        elif event == "task_success":
            name = data.get("task_name", "?")
            self.header_status_lbl.setText(f"✅ {name} succeeded")
        elif event == "task_failed":
            name = data.get("task_name", "?")
            self.header_status_lbl.setText(f"❌ {name} failed — moving on")
        elif event == "stopped":
            stats = data.get("stats", {})
            session = data.get("session", {})
            self._autoresearch_running = False
            self.autoresearch_btn.setChecked(False)
            self.autoresearch_btn.setText("Train")
            self.autoresearch_action.setChecked(False)
            if hasattr(self, "composer_autoresearch_action"):
                self.composer_autoresearch_action.setChecked(False)
            self.mode_label.setText("Ready")
            self.header_status_lbl.setText(
                f"Train done • {session.get('tasks_succeeded', 0)}/"
                f"{session.get('tasks_attempted', 0)} tasks • "
                f"{stats.get('total_lessons', 0)} lessons"
            )
            # Restore the connection-status dot color after training overwrote it
            self._refresh_header_meta()

    def _show_autoresearch_stats(self):
        try:
            from houdinimind.agent.autoresearch_loop import AutoResearchDB

            data_dir = self.config.get("data_dir", "")
            db = AutoResearchDB(os.path.join(data_dir, "db", "autoresearch.db"))
            stats = db.get_stats()
            lessons = db.get_lessons(min_confidence=0.3, limit=10)

            lines = [
                "🔬 **Training Statistics**\n",
                f"Total attempts: {stats['total_attempts']}",
                f"Successes: {stats['successes']} ({stats['success_rate']}%)",
                f"Tasks mastered: {stats['unique_tasks_mastered']}",
                f"Total lessons: {stats['total_lessons']} ({stats['high_confidence_lessons']} high-confidence)\n",
            ]
            if lessons:
                lines.append("**Top Lessons:**")
                for lesson in lessons[:5]:
                    lines.append(
                        f"  • [{lesson['confidence']}] {lesson['error'][:60]} → {lesson['fix'][:60]}"
                    )

            text = "\n".join(lines)
            QtWidgets.QMessageBox.information(self, "Training Stats", text)
        except Exception as e:
            QtWidgets.QMessageBox.information(
                self, "Training Stats", f"No data yet: {e}"
            )

    @staticmethod
    def _extract_text_content(raw_content) -> str:
        """Extract plain text from message content (handles multimodal list format)."""
        if isinstance(raw_content, str):
            return raw_content
        if isinstance(raw_content, list):
            return " ".join(
                b.get("text", "") for b in raw_content
                if isinstance(b, dict) and b.get("type") == "text"
            )
        return str(raw_content)

    def _export_chat(self):
        if not (self.agent and getattr(self.agent, "conversation", None)):
            self._add_system_note(
                "Export Chat is only available after the conversation has content."
            )
            self._refresh_turn_status("Start a conversation before exporting the chat.")
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export Chat", "", "Markdown (*.md);;Text (*.txt)"
        )
        if not path:
            return
        try:
            lines = [
                f"# Houdini Agent Session — {datetime.datetime.now():%Y-%m-%d %H:%M}\n",
                f"**Model:** {self.chat_model_combo.current_model()}\n",
            ]
            for msg in self.agent.conversation if self.agent else []:
                role = msg.get("role", "")
                content = self._extract_text_content(msg.get("content", ""))
                if role == "user":
                    lines.append(f"## You\n{content}\n")
                elif role == "assistant":
                    lines.append(f"## Houdini Agent\n{content}\n")
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            self._add_system_note(f"💾 Chat exported to: {path}")
        except Exception as e:
            self._add_system_note(f"Export failed: {e}")

    def _record_feedback(self, accepted: bool):
        if self.memory:
            self.memory.record_feedback(accepted)
            if not accepted:
                # Extract last tool sequence from conversation and log as a
                # negative recipe so the agent learns to avoid this approach.
                self._record_negative_recipe()
            # Run learning cycle on both accept AND reject so successful
            # patterns are promoted to recipes and persisted for next session.
            # Offload to a background thread to avoid freezing the UI.
            def _feedback_learn():
                try:
                    self.memory.run_learning_cycle()
                    if self.agent:
                        self.agent.reload_system_prompt()
                        self.agent.reload_knowledge()
                except Exception as e:
                    print(f"[HoudiniMind] Feedback learning failed: {e}")
            threading.Thread(target=_feedback_learn, daemon=True).start()
        self.accept_btn.setEnabled(False)
        self.reject_btn.setEnabled(False)
        self._update_feedback_visibility()
        self._show_feedback_chip(accepted)
        self._refresh_memory_panel()

    def _record_negative_recipe(self):
        """
        Extract tool calls from the last agent turn and write them to the
        negative_recipes table so the pattern analyser can penalise this
        approach in future builds.
        """
        try:
            if not self.agent or not self.memory:
                return
            conversation = getattr(self.agent, "conversation", []) or []
            # Walk backwards to collect tool_use blocks from the last assistant turn
            tool_steps = []
            for msg in reversed(conversation):
                if msg.get("role") == "assistant":
                    content = msg.get("content") or []
                    if isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "tool_use":
                                tool_steps.insert(0, {
                                    "tool": block.get("name", "unknown"),
                                    "args": block.get("input", {}),
                                })
                    if tool_steps:
                        break  # stop at the first assistant turn that had tools
            if not tool_steps:
                return  # no tool calls to log
            last_msg = getattr(self.memory, "_last_user_message", "") or "unknown"
            domain = "general"
            for kw in ("chair", "table", "shelf", "lamp", "desk", "sofa", "cabinet"):
                if kw in last_msg.lower():
                    domain = "furniture"
                    break
            tool_summary = " → ".join(s["tool"] for s in tool_steps[:6])
            name = f"rejected_{hash(tool_summary) & 0xFFFFFF:06x}"
            self.memory.recipes.add_negative_recipe(
                name=name,
                description=(
                    f"Rejected approach for: '{last_msg[:120]}'. "
                    f"Tools used: {tool_summary}"
                ),
                trigger_pattern=last_msg[:200],
                steps=tool_steps,
                domain=domain,
            )
            print(f"[HoudiniMind] Negative recipe recorded: {name} ({len(tool_steps)} steps)")
        except Exception as e:
            print(f"[HoudiniMind] _record_negative_recipe error: {e}")

    def _restore_conversation_ui(self):
        if not self.agent or not self.agent.conversation:
            return

        history = self.agent.conversation[1:]
        if not history:
            return

        for msg in history:
            role = msg.get("role")
            raw_content = msg.get("content")
            if role in ("user", "assistant") and raw_content:
                content = self._extract_text_content(raw_content)
                if content:
                    self._add_msg(role, content, _restoring=True)

    def _add_msg(self, role: str, text: str, mode: str = "chat", _restoring: bool = False) -> MessageBubble:
        self._has_conversation_content = True
        self._update_empty_state_visibility()

        # Show typing indicator while agent bubble is empty (before first token)
        if role == "agent" and not text:
            self._show_typing_indicator()

        bubble = MessageBubble(role, text, mode=mode)
        if role == "user":
            self.messages_l.insertWidget(
                self._message_insert_index(),
                bubble,
                0,
                QtCore.Qt.AlignRight | QtCore.Qt.AlignTop,
            )
        else:
            self.messages_l.insertWidget(
                self._message_insert_index(),
                bubble,
                0,
                QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop,
            )
        # Only pump the event loop for live messages, not during bulk restore
        # (pumping during restore allows click events to fire mid-replay).
        if not _restoring:
            QtWidgets.QApplication.processEvents()

        # Scroll to bottom on new message
        self.scroll.verticalScrollBar().setValue(
            self.scroll.verticalScrollBar().maximum()
        )
        return bubble

    def _show_typing_indicator(self):
        """No-op — planning chip + spinner already show activity."""
        pass

    def _hide_typing_indicator(self):
        """No-op — typing indicator removed; nothing to clean up."""
        pass

    def _add_status_notice(self, text: str, tone: str = "neutral"):
        if not self._has_conversation_content:
            self._has_conversation_content = True
            self._update_empty_state_visibility()
        notice = StatusNoticeWidget(text, tone=tone)
        self.messages_l.insertWidget(
            self._message_insert_index(), notice, 0, QtCore.Qt.AlignHCenter
        )
        self.scroll.verticalScrollBar().setValue(
            self.scroll.verticalScrollBar().maximum()
        )

    def _add_system_note(self, text: str):
        self._add_status_notice(text, tone="neutral")

    def _show_feedback_chip(self, accepted: bool):
        bubble = self._feedback_owner_bubble or self._current_bubble
        if bubble is None:
            return
        bubble.set_footer_widget(FeedbackChip(accepted))

    def _status(self, msg: str):
        self.mode_label.setText(msg)
        self._refresh_turn_status(msg)

    def _set_busy(self, busy: bool):
        self._busy = busy
        # Legacy strip is intentionally hidden from UI.
        if hasattr(self, "turn_strip"):
            self.turn_strip.setVisible(False)
        for btn in (
            self.send_btn,
            self.research_btn,
            self.attach_btn,
            self.vision_toggle_btn,
            self.fast_toggle_btn,
            self.scene_btn,
            self.learn_btn,
            self.hda_btn,
            self.dry_run_btn,
            self.composer_actions_btn,
        ):
            btn.setEnabled(not busy)
        self.send_btn.setVisible(not busy)
        self.stop_btn.setVisible(busy)
        if not self._autoresearch_running:
            self.autoresearch_btn.setEnabled(not busy)
        if hasattr(self, "spinner"):
            if busy:
                self.spinner.start()
                self._turn_timer.start()
            else:
                self.spinner.stop()
                self._turn_timer.stop()
        if not busy:
            self.thought_label.setText("")
            if not self._autoresearch_running:
                self.mode_label.setText("Ready")
            self._current_dry_run = False
            self.composer_hint_lbl.setText("Enter to send • Shift+Enter for newline")
        else:
            if self._autoresearch_running:
                self.composer_hint_lbl.setText(
                    "Training running… click Train to stop"
                )
            else:
                self.composer_hint_lbl.setText("Working on your scene…")
        self._update_feedback_visibility()
        self._refresh_turn_status()
        self._refresh_action_availability()

    def _on_stop(self):
        # 1. Signal the agent thread to stop ASAP
        if self._autoresearch_running:
            self._stop_autoresearch()
        if self.agent:
            self.agent.cancel()

        # 2. Reset UI — agent.cancel() sets the cancel event so the background
        #    thread will exit at its next checkpoint.  We must clear _busy now
        #    so the user can immediately issue a new request.
        self._set_busy(False)
        self._hide_status()
        self.stop_btn.setVisible(False)
        self.send_btn.setVisible(True)
        self.input_box.setEnabled(True)

        self._add_system_note("⏹ Stopped.")
        self._refresh_turn_status("Stopped.")

    def _on_undo(self):
        if self._busy:
            self._add_system_note("Undo is unavailable while another turn is running.")
            self._refresh_turn_status(
                "Finish or stop the current turn before restoring the last checkpoint."
            )
            return
        if not self.agent:
            self._add_system_note("Undo is unavailable because the agent is not ready.")
            return
        if (
            hasattr(self.agent, "has_restorable_checkpoint")
            and self.agent.has_restorable_checkpoint()
        ):
            reply = QtWidgets.QMessageBox.question(
                self,
                "Restore Last Turn",
                "Restore the full scene from the last turn checkpoint?\n\nThis is safer than asking the agent to manually undo individual steps.",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.Yes,
            )
            if reply == QtWidgets.QMessageBox.Yes:
                result = self.agent.restore_last_turn_checkpoint()
                self._add_system_note(f"↩ {result}")
                self._refresh_scene_panel(
                    overview="Restored the scene from the last turn checkpoint.",
                    summary_text=result,
                    diff_text=getattr(self.agent, "_last_turn_scene_diff_text", "")
                    or "",
                )
                self._refresh_turn_status("Restored the previous turn checkpoint.")
                return
        if not self.agent.undo_stack:
            QtWidgets.QMessageBox.information(self, "Undo", "Nothing to undo.")
            return
        last = self.agent.undo_stack.pop()
        self._dispatch_chat(f"[UNDO] Please undo the last change: {last}")

    def _show_undo(self):
        if self.agent:
            log = (
                "\n".join(self.agent.undo_stack)
                if self.agent.undo_stack
                else "No changes recorded."
            )
            QtWidgets.QMessageBox.information(self, "Undo Log", log)

    def _get_selection_context(self) -> str:
        if not HOU_AVAILABLE:
            return ""
        try:
            selection = hou.selectedNodes()
            if not selection:
                return ""
            ctx = ["[LIVE CONTEXT: User Selection]"]
            for node in selection[:5]:
                params = []
                for parm in node.parms()[:10]:
                    try:
                        params.append(f"{parm.name()}: {parm.eval()}")
                    except Exception:
                        pass
                ctx.append(
                    f"- {node.path()} ({node.type().name()}) Params: {', '.join(params)}"
                )
            return "\n".join(ctx) + "\n"
        except Exception:
            return ""

    def closeEvent(self, event):
        if getattr(self, "_asr_controller", None):
            try:
                self._asr_controller.stop()
            except Exception:
                pass
        if self.event_hooks:
            try:
                self.event_hooks.unregister()
            except Exception:
                pass
        super().closeEvent(event)

    def _show_debug_log(self):
        if not self.agent or not getattr(self.agent, "debug_logger", None):
            self._add_system_note("No debug log is available yet.")
            self._refresh_turn_status(
                "Run a turn first to generate a session debug log."
            )
            return
        try:
            log_path = self.agent.debug_logger.get_session_path()
        except Exception as exc:
            self._add_system_note(f"Debug log unavailable: {exc}")
            self._refresh_turn_status(
                "The current session debug log could not be opened."
            )
            return
        if not log_path or not os.path.isfile(log_path):
            self._add_system_note(
                "No session debug log file was found for the current run."
            )
            self._refresh_turn_status(
                "Run a turn first to generate a session debug log."
            )
            return
        if self._debug_log_dialog is not None:
            try:
                self._debug_log_dialog.close()
            except Exception:
                pass
        dialog = DebugLogDialog(log_path, self)
        dialog.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
        dialog.destroyed.connect(
            lambda *_args: setattr(self, "_debug_log_dialog", None)
        )
        self._debug_log_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
