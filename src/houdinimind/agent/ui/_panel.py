# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
"""Modular HoudiniMind panel shell."""

import threading
from collections import deque

from PySide6 import QtWidgets, QtCore

from ._panel_backend import PanelBackendMixin
from ._panel_dispatch import PanelDispatchMixin
from ._panel_layout import PanelLayoutMixin
from ._panel_state import PanelStateMixin
from ._panel_workflows import PanelWorkflowMixin


class HoudiniMindPanel(
    PanelBackendMixin,
    PanelStateMixin,
    PanelLayoutMixin,
    PanelDispatchMixin,
    PanelWorkflowMixin,
    QtWidgets.QWidget,
):
    sig_stream_chunk = QtCore.Signal(str)
    sig_response_done = QtCore.Signal(str)
    sig_status = QtCore.Signal(str)
    sig_tool_called = QtCore.Signal(str, dict, dict)
    sig_confirm_request = QtCore.Signal(str)
    sig_scene_error = QtCore.Signal(str, str)
    sig_models_loaded = QtCore.Signal(list)
    sig_asr_partial = QtCore.Signal(str)
    sig_asr_status = QtCore.Signal(str)
    sig_research_options = QtCore.Signal(str, list)
    sig_autoresearch_progress = QtCore.Signal(dict)
    # Fired from background init thread when backend is ready
    sig_backend_ready = QtCore.Signal(str)  # carries error message or ""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._busy = False
        self._current_dry_run = False
        self._pending_image_bytes = None
        self._vision_for_next_message = True
        self._fast_for_next_message = False
        self._current_bubble = None
        self._status_row = None
        self._current_tool_group = None
        self._current_mode = "chat"
        self._image_preview_widget = None
        self._total_chars = 0
        self._current_turn_tools = []
        self._last_turn_tools = []
        self._current_turn_started_at = 0.0
        self._last_turn_elapsed_s = 0
        self._current_turn_outputs = []
        self._last_turn_outputs = []
        self._current_turn_failures = []
        self._last_turn_failures = []
        self._current_turn_llm_notes = []
        self._last_turn_llm_notes = []
        self._last_live_progress_line = ""
        self._live_stream_text = ""
        self._last_user_request = ""
        self._last_result_text = ""
        self._last_workspace_sizes = [760, 360]
        self._has_conversation_content = False
        self._feedback_owner_bubble = None
        self._debug_log_dialog = None
        self._failure_strip = None
        self._show_quick_prompts = False
        self._detail_mode = "simple"
        self._focus_mode = False
        self._autoresearch_loop = None
        self._autoresearch_running = False
        self._active_job_id = ""
        self.agent = None
        self.job_manager = None
        self.memory = None
        self.event_hooks = None
        self.config = {}
        self._turn_timer = QtCore.QTimer(self)
        self._turn_timer.setInterval(500)
        self._turn_timer.timeout.connect(self._refresh_turn_status)
        self._live_stream_queue = deque()
        self._live_stream_timer = QtCore.QTimer(self)
        self._live_stream_timer.setInterval(22)
        self._live_stream_timer.timeout.connect(self._drain_live_stream_queue)

        self._backend_ready = False
        self._asr_controller = None
        self._last_asr_note = ""
        self._last_asr_note_at = 0.0

        # Build UI immediately — Houdini panel opens with zero blocking
        self._build_ui()
        self._connect_signals()
        # Wire backend-ready signal before starting the thread
        self.sig_backend_ready.connect(self._on_backend_ready)

        # Show "Initializing…" state while backend loads
        self._set_init_loading_state(True)

        # Load RAG + MemoryManager + AgentLoop off the main thread
        threading.Thread(
            target=self._init_backend_async,
            daemon=True,
            name="hm-backend-init",
        ).start()


    # ── Async backend init helpers ────────────────────────────────────

    def _set_init_loading_state(self, loading: bool) -> None:
        """Show/hide the 'Initializing…' overlay in the turn strip."""
        lbl = getattr(self, "turn_status_lbl", None)
        send = getattr(self, "send_btn", None)
        mic = getattr(self, "mic_btn", None)
        inp = getattr(self, "input_box", None)
        if loading:
            if lbl:
                lbl.setText("Initializing — loading knowledge base…")
            if send:
                send.setEnabled(False)
                send.setToolTip("Wait for initialization to complete")
            if mic:
                mic.setEnabled(False)
                mic.setToolTip("Wait for initialization to complete")
            if inp:
                inp.setEnabled(False)
                inp.setPlaceholderText("Initializing HoudiniMind…")
        else:
            if send:
                send.setEnabled(True)
                send.setToolTip("")
            if mic:
                mic.setEnabled(True)
                mic.setToolTip("Start speech input")
            if inp:
                inp.setEnabled(True)
                inp.setPlaceholderText("Message HoudiniMind")
            if lbl:
                lbl.setText("Ready")

    def _init_backend_async(self) -> None:
        """Heavy init work — runs on a daemon thread, never blocks the UI."""
        error_msg = ""
        try:
            self._setup_backend()
        except Exception as exc:
            import traceback as _tb
            error_msg = str(exc)
            _tb.print_exc()
        # Marshal back to the Qt main thread via signal
        self.sig_backend_ready.emit(error_msg)

    def _on_backend_ready(self, error_msg: str) -> None:
        """Called on the Qt main thread once the backend has loaded."""
        self._backend_ready = True
        self._set_init_loading_state(False)
        if error_msg:
            lbl = getattr(self, "turn_status_lbl", None)
            if lbl:
                lbl.setText(f"Init error: {error_msg[:60]}")
        else:
            # Wire everything that depends on agent/memory being present
            self._setup_asr_ui()
            self._start_event_hooks()
            self._refresh_models_async()
            self._restore_conversation_ui()
            # Refresh header meta (connection dot, model label)
            try:
                self._refresh_header_meta()
            except Exception:
                pass


def createInterface():
    return HoudiniMindPanel()
