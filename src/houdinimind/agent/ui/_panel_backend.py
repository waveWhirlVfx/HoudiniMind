# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
import json
import os
import threading
import traceback

from ._widgets import HOUDINIMIND_ROOT, HOU_AVAILABLE

try:
    import hou
except ImportError:
    hou = None


class PanelBackendMixin:
    def _setup_backend(self):
        try:
            self._config_path = os.path.join(
                HOUDINIMIND_ROOT, "data", "core_config.json"
            )
            with open(self._config_path, "r") as f:
                self.config = json.load(f)
        except Exception as e:
            print(f"Config load failed: {e}")
            self.config = {}
            self._config_path = os.path.join(
                HOUDINIMIND_ROOT, "data", "core_config.json"
            )

        data_dir = self.config.get("data_dir", "")
        if not data_dir or data_dir == "__auto__" or not os.path.isdir(data_dir):
            data_dir = os.path.join(HOUDINIMIND_ROOT, "data")
            self.config["data_dir"] = data_dir

        self._ensure_schema(data_dir)

        try:
            from houdinimind.memory.memory_manager import MemoryManager

            self.memory = MemoryManager(self.config.get("data_dir", ""))
        except Exception as e:
            print(f"MemoryManager unavailable: {e}")

        rag_injector = None
        try:
            from houdinimind.rag import create_rag_pipeline

            rag_injector = create_rag_pipeline(
                self.config.get("data_dir", ""), self.config
            )
        except Exception as e:
            print(f"RAG unavailable: {e}")

        try:
            from houdinimind.agent.loop import AgentLoop
            from houdinimind.agent.async_jobs import AsyncJobManager

            self.agent = AgentLoop(
                config=self.config,
                memory_manager=self.memory,
                on_tool_call=self._on_tool_call_from_agent,
                rag_injector=rag_injector,
            )
            self.job_manager = AsyncJobManager()
            self.agent.set_confirmation_callback(
                lambda desc: self.sig_confirm_request.emit(desc)
            )
        except Exception as e:
            print(f"AgentLoop error: {e}")
            traceback.print_exc()

        # ── Scheduled AutoResearch ────────────────────────────────────────
        self._research_scheduler = None
        try:
            from houdinimind.agent.scheduler import ResearchScheduler
            self._research_scheduler = ResearchScheduler(
                agent=getattr(self, "agent", None),
                memory=getattr(self, "memory", None),
                config=self.config,
                stream_callback=self.sig_stream_chunk.emit,
            )
            if self.config.get("schedule_enabled", False):
                self._research_scheduler.start()
        except Exception as e:
            print(f"[HoudiniMind] ResearchScheduler init failed: {e}")

        # ── Skills Platform ───────────────────────────────────────────────
        self._skill_loader = None
        try:
            from houdinimind.agent.skills import SkillLoader
            self._skill_loader = SkillLoader(
                agent=getattr(self, "agent", None),
                config=self.config,
            )
            result = self._skill_loader.load_all()
            if result["total_loaded"]:
                print(f"[HoudiniMind Skills] Loaded {result['total_loaded']} skill(s): {result['loaded']}")
            if result["total_errors"]:
                print(f"[HoudiniMind Skills] {result['total_errors']} skill(s) failed: {result['errors']}")
        except Exception as e:
            print(f"[HoudiniMind] SkillLoader init failed: {e}")

    def _ensure_schema(self, data_dir: str):
        schema_path = os.path.join(data_dir, "schema", "houdini_full_schema.json")
        if not os.path.exists(schema_path) and HOU_AVAILABLE:
            print("Generating Houdini node schema... this may take a moment.")
            try:
                from houdinimind.agent.schema_extractor import generate_full_houdini_schema

                generate_full_houdini_schema(schema_path)
            except Exception as e:
                print(f"Could not generate schema: {e}")

    def _start_event_hooks(self):
        if not HOU_AVAILABLE:
            return
        try:
            from houdinimind.bridge.event_hooks import EventHooks

            self.event_hooks = EventHooks(on_event=self._on_scene_event)
            self.event_hooks.register()
        except Exception as e:
            print(f"EventHooks failed: {e}")
        # ── HipFile save event → learning cycle ───────────────────────────
        try:
            import hou
            hou.hipFile.addEventCallback(self._on_hip_file_event)
            print("[HoudiniMind] HipFile event callback registered.")
        except Exception as e:
            print(f"[HoudiniMind] HipFile event callback failed: {e}")

    def _on_hip_file_event(self, event_type):
        """
        Called by Houdini when the .hip file is saved, opened, or cleared.
        On save: trigger memory learning cycle in background.
        """
        try:
            import hou
            # hou.hipFileEventType.AfterSave is the canonical save event
            after_save = getattr(hou.hipFileEventType, "AfterSave", None)
            before_save = getattr(hou.hipFileEventType, "BeforeSave", None)
            if event_type not in (after_save, before_save):
                return
            if event_type == before_save:
                return  # Only act after a successful save

            hip_path = hou.hipFile.path()
            print(f"[HoudiniMind] Hip saved: {hip_path} — triggering learning cycle.")

            def _post_save_work():
                try:
                    # 1. Notify the UI
                    self.sig_stream_chunk.emit(
                        f"\x00AGENT_PROGRESS\x00Hip saved — running memory learning cycle…"
                    )
                    # 2. Run memory learning cycle (pattern mining + self-update)
                    if hasattr(self, "memory") and self.memory:
                        result = self.memory.run_learning_cycle()
                        new_recipes = result.get("new_recipes", 0)
                        if new_recipes:
                            self.sig_stream_chunk.emit(
                                f"\x00AGENT_PROGRESS\x00Learning: {new_recipes} new recipe(s) promoted from session."
                            )
                except Exception as ex:
                    print(f"[HoudiniMind] Post-save work failed: {ex}")

            threading.Thread(target=_post_save_work, daemon=True, name="hmind-postsave").start()
        except Exception as e:
            print(f"[HoudiniMind] _on_hip_file_event error: {e}")

    def _on_tool_call_from_agent(self, tool_name, args, result):
        self.sig_tool_called.emit(tool_name, args, result)

    def _refresh_models_async(self):
        """Fetch available Ollama models in a background thread."""

        def _fetch():
            try:
                import urllib.request

                url = self.config.get("ollama_url", "http://localhost:11434")
                req = urllib.request.Request(f"{url}/api/tags")
                with urllib.request.urlopen(req, timeout=8) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    models = [m["name"] for m in data.get("models", [])]
                    self.sig_models_loaded.emit(models)
            except Exception:
                self.sig_models_loaded.emit([])

        threading.Thread(target=_fetch, daemon=True).start()

    def _on_models_loaded(self, models: list):
        current_chat = self.config.get("model", "")
        current_vision = self.config.get("vision_model", "")
        # Block signals during populate to prevent spurious config saves on startup
        self.chat_model_combo.blockSignals(True)
        self.vision_model_combo.blockSignals(True)
        self.chat_model_combo.populate(models, current_chat)
        self.vision_model_combo.populate(models, current_vision)
        self.chat_model_combo.blockSignals(False)
        self.vision_model_combo.blockSignals(False)
        if models:
            self.conn_status.set_ok(len(models), self.chat_model_combo.current_model())
        else:
            self.conn_status.set_error()
        self._apply_view_mode()

    def _setup_asr_ui(self):
        try:
            from ._asr import SpeechToTextController
        except Exception as exc:
            print(f"Speech input unavailable: {exc}")
            if hasattr(self, "mic_btn"):
                self.mic_btn.setEnabled(False)
                self.mic_btn.setToolTip("Speech input unavailable")
            return

        if hasattr(self, "settings_panel") and hasattr(self.settings_panel, "asr_model_combo"):
            combo = self.settings_panel.asr_model_combo
            combo.blockSignals(True)
            idx = combo.findData(self.config.get("asr_model", "base.en"))
            if idx < 0:
                idx = combo.findData("base.en")
            combo.setCurrentIndex(idx if idx >= 0 else 0)
            combo.blockSignals(False)

        self._asr_controller = SpeechToTextController(self.config, self)
        self._asr_controller.partial_text.connect(self.sig_asr_partial.emit)
        self._asr_controller.status_changed.connect(self.sig_asr_status.emit)
        self._asr_controller.error.connect(self.sig_asr_status.emit)
        self._asr_controller.state_changed.connect(self._on_asr_state_changed)

    def _on_chat_model_changed(self, _index):
        model = self.chat_model_combo.current_model()
        if not model:
            return
        self.config["model"] = model
        if self.agent:
            self.agent.llm.model = model
            self.agent.llm.config["model"] = model
        self._save_runtime_config()
        self.conn_status.set_active_model(model)
        self._refresh_header_meta()
        self._status(f"Chat model: {model}")

    def _on_vision_model_changed(self, _index):
        model = self.vision_model_combo.current_model()
        if not model:
            return
        self.config["vision_model"] = model
        if self.agent:
            self.agent.llm.vision_model = model
            self.agent.llm.config["vision_model"] = model
        self._save_runtime_config()
        self._refresh_header_meta()
        self._status(f"Vision model: {model}")

    def _apply_settings(self, cfg: dict):
        self.config.update({k: v for k, v in cfg.items() if k not in ("ui",)})
        self.config.setdefault("ui", {}).update(cfg.get("ui", {}))
        self.config["auto_backup"] = bool(cfg.get("auto_backup", False))
        self.config["auto_backup_on_save"] = False
        self.config["turn_checkpoints"] = bool(cfg.get("auto_backup", False))
        self.config["vision_enabled"] = True
        if getattr(self, "_asr_controller", None):
            self._asr_controller.update_config(self.config)
        if self.agent:
            self.agent.llm.apply_runtime_config(self.config)
            self.agent.max_tool_rounds = cfg.get(
                "max_tool_rounds", self.agent.max_tool_rounds
            )
            self.agent.turn_checkpoints_enabled = bool(cfg.get("auto_backup", False))
            self.agent._vision_enabled = True
            self.agent.auto_network_view_checks = bool(
                self.config.get("auto_network_view_checks", True)
            )
        self._save_runtime_config()
        self._refresh_header_meta()
        self._refresh_tools_panel()
        self._refresh_models_async()

    def _save_runtime_config(self):
        path = getattr(self, "_config_path", "")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            print(f"Config save failed: {e}")

    def _on_scene_event(self, category: str, data: dict):
        if self.memory:
            try:
                self.memory.log_scene_event(category, data)
            except Exception:
                pass
        # Scene error detection removed — sig_scene_error was disconnected from
        # the UI banner and the emission loop ran for nothing on every event.
        # Re-enable here if the error banner is reconnected in the future.
