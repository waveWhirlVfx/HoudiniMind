# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
"""Low-latency local speech-to-text for the HoudiniMind composer."""

import os
import queue
import sys
import threading
import time
import traceback

import numpy as np
from PySide6 import QtCore


ASR_MODEL_OPTIONS = [
    ("tiny.en", "Tiny English - fastest"),
    ("base.en", "Base English - balanced"),
    ("small.en", "Small English - more accurate"),
    ("medium.en", "Medium English - best local accuracy"),
]


def list_asr_input_devices():
    try:
        import sounddevice as sd
    except Exception:
        return []
    devices = []
    for idx, info in enumerate(sd.query_devices()):
        try:
            if int(info.get("max_input_channels", 0)) > 0:
                name = str(info.get("name", "") or f"Input {idx}")
                devices.append({"index": idx, "name": name, "label": f"{name} ({idx})"})
        except Exception:
            continue
    return devices


def _configure_multiprocessing_executable():
    """Prevent embedded Houdini from launching a second Houdini app for helpers."""
    try:
        import multiprocessing

        exe_name = os.path.basename(sys.executable or "").lower()
        if exe_name.startswith(("python", "hython")) and os.path.exists(sys.executable):
            multiprocessing.set_executable(sys.executable)
            return

        version = f"python{sys.version_info.major}.{sys.version_info.minor}"
        candidates = []
        for prefix in (getattr(sys, "prefix", ""), getattr(sys, "base_prefix", "")):
            if prefix:
                candidates.extend(
                    [
                        os.path.join(prefix, "bin", version),
                        os.path.join(prefix, "bin", "python3"),
                    ]
                )
        for candidate in candidates:
            if os.path.exists(candidate) and os.access(candidate, os.X_OK):
                multiprocessing.set_executable(candidate)
                return
    except Exception:
        pass


class SpeechToTextController(QtCore.QObject):
    partial_text = QtCore.Signal(str)
    status_changed = QtCore.Signal(str)
    state_changed = QtCore.Signal(bool)
    error = QtCore.Signal(str)

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.config = config
        self._thread = None
        self._stop_event = threading.Event()
        self._audio_q = queue.Queue()
        self._model = None
        self._model_name = ""
        self._lock = threading.Lock()
        self._last_level_status = 0.0
        self._last_silence_status = 0.0
        self._last_nonzero_audio = 0.0
        self._max_observed_peak = 0.0
        self._heard_audio = False

    def update_config(self, config: dict):
        self.config = config

    def is_recording(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def toggle(self):
        if self.is_recording():
            self.stop()
        else:
            self.start()

    def start(self):
        if self.is_recording():
            return
        self._stop_event.clear()
        self._audio_q = queue.Queue()
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="hm-asr-stream",
        )
        self._thread.start()
        self.state_changed.emit(True)

    def stop(self):
        self._stop_event.set()
        self.state_changed.emit(False)

    def _selected_model(self) -> str:
        model = str(self.config.get("asr_model", "base.en") or "base.en").strip()
        return model or "base.en"

    def _resolve_device(self) -> str:
        requested = str(self.config.get("asr_device", "auto") or "auto").strip().lower()
        if requested in ("cpu", "cuda"):
            return requested
        try:
            import ctranslate2

            return "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
        except Exception:
            return "cpu"

    def _load_model(self):
        model_name = self._selected_model()
        with self._lock:
            if self._model is not None and self._model_name == model_name:
                return self._model
            _configure_multiprocessing_executable()
            self.status_changed.emit(
                f"Loading speech model: {model_name}. First use may download model files."
            )
            from faster_whisper import WhisperModel

            device = self._resolve_device()
            compute_type = str(
                self.config.get(
                    "asr_compute_type",
                    "float16" if device == "cuda" else "int8",
                )
                or "int8"
            )
            self._model = WhisperModel(model_name, device=device, compute_type=compute_type)
            self._model_name = model_name
            self.status_changed.emit(f"Speech model ready: {model_name}")
            return self._model

    @staticmethod
    def _device_name(info) -> str:
        try:
            return str(info.get("name", "") or "")
        except Exception:
            return ""

    @classmethod
    def _input_devices(cls, sd):
        return [(d["index"], d["name"]) for d in list_asr_input_devices()]

    @staticmethod
    def _device_score(name: str, is_default: bool) -> int:
        lowered = (name or "").lower()
        virtual_terms = (
            "blackhole",
            "soundflower",
            "loopback",
            "aggregate",
            "multi-output",
            "zoomaudio",
            "teams audio",
        )
        built_in_terms = (
            "built-in",
            "internal",
            "macbook",
            "microphone",
            "mic",
        )
        score = 0
        if is_default:
            score += 20
        if any(term in lowered for term in built_in_terms):
            score += 80
        if any(term in lowered for term in virtual_terms):
            score -= 100
        return score

    def _default_input_device(self, sd):
        requested = str(self.config.get("asr_input_device", "auto") or "auto").strip()
        devices = self._input_devices(sd)
        if not devices:
            return None, ""

        if requested and requested.lower() != "auto":
            if requested.isdigit():
                requested_idx = int(requested)
                for idx, name in devices:
                    if idx == requested_idx:
                        return idx, name
            requested_l = requested.lower()
            for idx, name in devices:
                if requested_l in name.lower():
                    return idx, name
            names = ", ".join(f"{idx}: {name}" for idx, name in devices)
            self.status_changed.emit(
                f"Configured microphone '{requested}' was not found. Available inputs: {names}. Falling back to auto."
            )

        default_input = None
        try:
            default_device = sd.default.device
            default_input = default_device[0] if isinstance(default_device, (list, tuple)) else default_device
        except Exception:
            pass

        ranked = sorted(
            devices,
            key=lambda item: self._device_score(item[1], item[0] == default_input),
            reverse=True,
        )
        return ranked[0]

    def _run(self):
        target_sample_rate = int(self.config.get("asr_sample_rate", 16000) or 16000)
        chunk_seconds = float(self.config.get("asr_chunk_seconds", 2.4) or 2.4)
        pending = []

        try:
            _configure_multiprocessing_executable()
            import sounddevice as sd

            device_idx, device_name = self._default_input_device(sd)
            if device_idx is None:
                self.error.emit("Speech recognition failed: no microphone input device found.")
                return
            device_info = sd.query_devices(device_idx)
            input_sample_rate = int(device_info.get("default_samplerate") or 48000)
            min_samples = max(input_sample_rate, int(input_sample_rate * chunk_seconds))
            print(f"[HM-ASR] Using microphone: {device_name} ({input_sample_rate} Hz)")
            model = self._load_model()

            def _callback(indata, frames, time_info, status):
                if status:
                    self.status_changed.emit(str(status))
                self._audio_q.put(indata[:, 0].copy())

            self.status_changed.emit("Listening...")
            with sd.InputStream(
                device=device_idx,
                samplerate=input_sample_rate,
                channels=1,
                dtype="float32",
                blocksize=max(1024, input_sample_rate // 10),
                callback=_callback,
            ):
                last_flush = time.time()
                while not self._stop_event.is_set():
                    try:
                        block = self._audio_q.get(timeout=0.2)
                        pending.append(block)
                        block_peak = float(np.max(np.abs(block))) if block.size else 0.0
                        self._max_observed_peak = max(self._max_observed_peak, block_peak)
                        if block_peak > 0.00002:
                            self._last_nonzero_audio = time.time()
                    except queue.Empty:
                        pass
                    sample_count = sum(len(x) for x in pending)
                    enough_audio = sample_count >= min_samples
                    enough_time = time.time() - last_flush >= chunk_seconds
                    if pending and time.time() - self._last_silence_status >= 8.0:
                        self._last_silence_status = time.time()
                        if not self._last_nonzero_audio:
                            self._last_nonzero_audio = last_flush
                        if time.time() - self._last_nonzero_audio >= 8.0:
                            print("[HM-ASR] Receiving silence from microphone.")
                        elif self._max_observed_peak < 0.001:
                            print(f"[HM-ASR] Microphone signal very low (peak {self._max_observed_peak:.5f}).")
                    if pending and enough_audio and enough_time:
                        self._transcribe_pending(
                            model, pending, input_sample_rate, target_sample_rate
                        )
                        pending = []
                        last_flush = time.time()
                if pending:
                    self._transcribe_pending(
                        model, pending, input_sample_rate, target_sample_rate
                    )
        except ModuleNotFoundError as exc:
            missing = getattr(exc, "name", "") or str(exc)
            self.error.emit(
                f"Speech recognition needs the '{missing}' package. Install requirements, then restart HoudiniMind."
            )
        except Exception as exc:
            traceback.print_exc()
            self.error.emit(f"Speech recognition failed: {exc}")
        finally:
            self.status_changed.emit("Speech input stopped.")
            self.state_changed.emit(False)

    @staticmethod
    def _resample_audio(audio: np.ndarray, input_rate: int, target_rate: int) -> np.ndarray:
        if input_rate == target_rate or audio.size == 0:
            return audio.astype(np.float32, copy=False)
        duration = audio.size / float(input_rate)
        target_size = max(1, int(duration * target_rate))
        old_x = np.linspace(0.0, duration, num=audio.size, endpoint=False)
        new_x = np.linspace(0.0, duration, num=target_size, endpoint=False)
        return np.interp(new_x, old_x, audio).astype(np.float32, copy=False)

    def _transcribe_pending(
        self,
        model,
        pending,
        input_sample_rate: int,
        target_sample_rate: int,
    ):
        audio = np.concatenate(pending).astype(np.float32, copy=False)
        if audio.size < input_sample_rate * 0.4:
            return
        peak = float(np.max(np.abs(audio))) if audio.size else 0.0
        if peak < 0.0002:
            return
        if not self._heard_audio or time.time() - self._last_level_status >= 8.0:
            self._heard_audio = True
            self._last_level_status = time.time()
            print("[HM-ASR] Microphone audio detected. Transcribing...")
        if peak < 0.15:
            gain = min(30.0, 0.15 / max(peak, 0.0002))
            audio = np.clip(audio * gain, -1.0, 1.0).astype(np.float32, copy=False)
        audio = self._resample_audio(audio, input_sample_rate, target_sample_rate)
        segments, _info = model.transcribe(
            audio,
            language="en",
            task="transcribe",
            beam_size=1,
            vad_filter=True,
            condition_on_previous_text=False,
            without_timestamps=True,
        )
        text = " ".join((seg.text or "").strip() for seg in segments).strip()
        if text:
            self.partial_text.emit(text)
        else:
            print("[HM-ASR] Audio detected, but no English speech was recognized yet.")
