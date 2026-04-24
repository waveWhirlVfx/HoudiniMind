# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
from __future__ import annotations

import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional


@dataclass
class AgentJobState:
    job_id: str
    kind: str
    status: str = "queued"
    started_at: float = 0.0
    finished_at: float = 0.0
    latest_substate: str = ""
    progress_log: List[str] = field(default_factory=list)
    checkpoints: List[str] = field(default_factory=list)
    result: str = ""
    error: str = ""
    meta: Dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "kind": self.kind,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "latest_substate": self.latest_substate,
            "progress_log": list(self.progress_log),
            "checkpoints": list(self.checkpoints),
            "result": self.result,
            "error": self.error,
            "meta": dict(self.meta),
        }


class AsyncJobManager:
    def __init__(self, max_progress_entries: int = 80):
        self._max_progress_entries = max(10, int(max_progress_entries))
        self._jobs: Dict[str, AgentJobState] = {}
        self._lock = threading.Lock()

    def submit(
        self,
        kind: str,
        runner: Callable[[Callable[[str], None], Callable[[dict], None]], str],
        stream_callback: Optional[Callable[[str], None]] = None,
        done_callback: Optional[Callable[[str], None]] = None,
    ) -> str:
        job_id = uuid.uuid4().hex[:12]
        job = AgentJobState(job_id=job_id, kind=kind)
        with self._lock:
            self._jobs[job_id] = job

        def _record_progress(chunk: str):
            text = str(chunk or "")
            message = text.replace("\x00AGENT_PROGRESS\x00", "").replace("\u200b", "").strip()
            if message:
                self._record_substate(job_id, message)
            if stream_callback:
                stream_callback(text)

        def _record_status(payload: dict):
            payload = dict(payload or {})
            self._record_runtime_status(job_id, payload)

        def _worker():
            self._set_status(job_id, "running")
            try:
                result = runner(_record_progress, _record_status)
                self._finish(job_id, status="completed", result=result)
                if done_callback:
                    done_callback(result)
            except Exception as exc:
                error_text = f"⚠️ Agent Error: {exc}"
                traceback.print_exc()
                self._finish(job_id, status="failed", error=error_text)
                if stream_callback:
                    stream_callback(f"\n\n{error_text}")
                if done_callback:
                    done_callback(error_text)

        # ALWAYS use threading.Thread instead of QThreadPool/QRunnable.
        # Running hdefereval from a locked QRunnable blocks PySide's event loop on Mac,
        # leading to the "Houdini main-thread call timed out after 30s" deadlock.
        threading.Thread(target=_worker, daemon=True, name=f"houdinimind-job-{job_id}").start()
        
        return job_id

    def get(self, job_id: str) -> Optional[dict]:
        with self._lock:
            job = self._jobs.get(job_id)
            return job.to_dict() if job else None

    def _set_status(self, job_id: str, status: str):
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.status = status
            if status == "running" and not job.started_at:
                job.started_at = time.time()
            if status in {"completed", "failed", "cancelled"}:
                job.finished_at = time.time()

    def _record_substate(self, job_id: str, message: str):
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.latest_substate = message
            if not job.progress_log or job.progress_log[-1] != message:
                job.progress_log.append(message)
                if len(job.progress_log) > self._max_progress_entries:
                    job.progress_log = job.progress_log[-self._max_progress_entries :]

    def _record_runtime_status(self, job_id: str, payload: dict):
        kind = str(payload.get("kind", "") or "").lower()
        if kind in {"substate", "progress"}:
            self._record_substate(job_id, str(payload.get("message", "") or ""))
            return
        if kind == "checkpoint":
            checkpoint = str(payload.get("path", "") or "").strip()
            if not checkpoint:
                return
            with self._lock:
                job = self._jobs.get(job_id)
                if not job:
                    return
                if checkpoint not in job.checkpoints:
                    job.checkpoints.append(checkpoint)
                job.meta["checkpoint_path"] = checkpoint
            return
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.meta.update(payload)

    def _finish(
        self,
        job_id: str,
        status: str,
        result: str = "",
        error: str = "",
    ):
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.status = status
            job.finished_at = time.time()
            if not job.started_at:
                job.started_at = job.finished_at
            job.result = result or ""
            job.error = error or ""
