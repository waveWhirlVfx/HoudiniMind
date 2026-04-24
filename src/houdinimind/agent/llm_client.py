# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
"""
HoudiniMind — LLM Client v3
Ollama-first. Supports all Ollama models including cloud-routed ones.
New in v3:
  - chat_stream() uses httpx for async streaming with proper chunking
  - tiktoken-based token counting for accurate context budgeting
  - Improved streaming with real-time token emission
New in v2:
  - embed()               : vector embeddings via nomic-embed-text (or any embed model)
  - select_relevant_tools(): returns top-N tool schemas by semantic + keyword relevance
  - load_config()         : resolves data_dir at runtime — no more hardcoded paths
"""

import json
import base64
import time
import os
import math
import re
import io
import threading
import http.client
import urllib.request
import urllib.error
import urllib.parse
from collections import OrderedDict
from typing import Generator, List, Optional

try:
    import httpx

    _HTTPX_AVAILABLE = True
except ImportError:
    _HTTPX_AVAILABLE = False

from ..inference import BackendCapabilityError
from .tool_selection import (
    _TOOL_KEYWORD_MAP,
    _PYTHON_TOOL_HINT_RE,
    select_relevant_tool_schemas,
)


OLLAMA_BASE = "http://localhost:11434"


class RequestCancelledError(ConnectionError):
    pass


class _BoundedEmbedCache(OrderedDict):
    def __init__(self, max_entries: int = 2048):
        super().__init__()
        self.max_entries = max(1, int(max_entries or 2048))
        self._dirty = False

    def __getitem__(self, key):
        value = super().__getitem__(key)
        self.move_to_end(key)
        return value

    def get(self, key, default=None):
        if key in self:
            return self[key]
        return default

    def __setitem__(self, key, value):
        if key in self:
            self.move_to_end(key)
        else:
            self._dirty = True
        super().__setitem__(key, value)
        while len(self) > self.max_entries:
            self.popitem(last=False)

    # ── Disk persistence ─────────────────────────────────────────────
    def save_to_disk(self, path: str, embed_model: str = ""):
        """Persist cache to a JSON file. Only writes if new entries were added."""
        if not self._dirty:
            return
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            payload = {
                "_embed_model": embed_model,
                "_count": len(self),
                "entries": {k: v for k, v in self.items()},
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f)
            self._dirty = False
        except Exception:
            pass  # non-fatal — cache is a performance optimisation

    def load_from_disk(self, path: str, embed_model: str = ""):
        """Load cache from disk. Invalidates if embed_model changed."""
        try:
            if not os.path.isfile(path):
                return
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            # Invalidate if the embed model has changed
            if payload.get("_embed_model", "") != embed_model:
                return
            entries = payload.get("entries", {})
            for k, v in entries.items():
                super().__setitem__(k, v)
            # Trim to max
            while len(self) > self.max_entries:
                self.popitem(last=False)
            self._dirty = False
        except Exception:
            pass  # non-fatal — will re-embed on cache miss


# ══════════════════════════════════════════════════════════════════════
#  Runtime config loader — resolves data_dir relative to this file
# ══════════════════════════════════════════════════════════════════════


def load_config(config_path: str = None) -> dict:
    """
    Load core_config.json and resolve data_dir at runtime.
    Falls back gracefully if the file doesn't exist.
    """
    if config_path is None:
        # Walk up from llm_client.py → python/agent → python → root → data/
        here = os.path.dirname(os.path.abspath(__file__))
        root = os.path.dirname(os.path.dirname(here))  # HoudiniMind root
        config_path = os.path.join(root, "data", "core_config.json")

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except FileNotFoundError:
        cfg = {}

    # Always resolve data_dir relative to the config file itself.
    # The JSON value "__auto__" (or any non-existent path) triggers this.
    json_data_dir = cfg.get("data_dir", "__auto__")
    config_dir = os.path.dirname(os.path.abspath(config_path))

    if (
        not json_data_dir
        or json_data_dir == "__auto__"
        or not os.path.exists(json_data_dir)
    ):
        data_dir = config_dir
    else:
        # If it's a relative path, make it relative to config_dir
        if not os.path.isabs(json_data_dir):
            data_dir = os.path.abspath(os.path.join(config_dir, json_data_dir))
        else:
            data_dir = os.path.abspath(json_data_dir)

    cfg["data_dir"] = data_dir
    cfg["_config_path"] = config_path
    return cfg


# ══════════════════════════════════════════════════════════════════════
#  Cosine similarity helper (zero external deps)
# ══════════════════════════════════════════════════════════════════════


def _cosine(a: list, b: list) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def chars_per_token_for_model(model_name: str) -> float:
    lowered = str(model_name or "").lower()
    if any(name in lowered for name in ("qwen", "kimi")):
        return 2.75
    if "deepseek" in lowered:
        return 2.8
    if "llama" in lowered:
        return 3.1
    if "mistral" in lowered:
        return 3.1
    return 3.5


def _is_small_local_model(model_name: str) -> bool:
    lowered = str(model_name or "").lower()
    return any(tag in lowered for tag in ("2b", "3b", "4b", "tiny", "small"))


class OllamaClient:
    def __init__(self, config: dict):
        self.config = dict(config or {})
        self._embed_cache = _BoundedEmbedCache()
        self._active_connections = set()
        self._connection_lock = threading.Lock()
        self._cancel_requests = threading.Event()
        self._rate_limited_until = 0.0
        self.debug_logger = None       # set by AgentLoop after construction
        self._last_token_usage: dict = {}  # populated after each _ollama_chat call
        self.request_retries = self.config.get(
            "request_retries", 5
        )  # Increased to 5 for better server recovery
        self.apply_runtime_config(self.config)

    def apply_runtime_config(self, config: dict):
        self.config = dict(config or {})
        self.model = self.config.get("model", "qwen2.5-coder:32b")
        self.vision_model = self.config.get("vision_model", "llava:13b")
        self.vision_enabled = self.config.get("vision_enabled", True)
        self.embed_model = self.config.get("embed_model", "nomic-embed-text")
        self.base_url = self.config.get("ollama_url", OLLAMA_BASE).rstrip("/")
        self.temperature = self.config.get("temperature", 0.3)
        self.api_key = self.config.get("api_key", "").strip()
        # CRIT-10: resolving the context window issues a /api/show request with
        # a 10s timeout. Running it inside __init__ froze Houdini on panel load
        # whenever Ollama was down. Defer it — first consumer triggers lookup.
        self._context_window_config = int(self.config.get("context_window", 32768))
        self._context_window_resolved: Optional[int] = None
        self._model_routing = self.config.get("model_routing", {})
        self._force_model_routing_tasks = {
            str(task).strip().lower()
            for task in (self.config.get("force_model_routing_tasks", []) or [])
            if str(task).strip()
        }
        self.max_tools = self.config.get("max_tools_per_request", 20)
        self.request_retries = max(1, int(self.config.get("request_retries", 5)))
        self.rate_limit_cooldown_s = max(
            1.0,
            float(self.config.get("rate_limit_cooldown_s", 15.0)),
        )

        self.backend_name = (
            str(self.config.get("backend", "ollama") or "ollama").strip().lower()
        )
        self._embed_cache = _BoundedEmbedCache(
            max_entries=int(self.config.get("embed_cache_size", 2048))
        )
        # Load persisted embeddings from disk (survives Houdini restarts)
        data_dir = self.config.get("data_dir", "")
        if data_dir and data_dir != "__auto__":
            self._embed_cache_path = os.path.join(data_dir, "db", "embed_cache.json")
            self._embed_cache.load_from_disk(
                self._embed_cache_path, embed_model=self.embed_model
            )
        else:
            self._embed_cache_path = ""

    # ------------------------------------------------------------------
    # Auto-detect model context window from Ollama (lazy)
    # ------------------------------------------------------------------
    @property
    def context_window(self) -> int:
        if self._context_window_resolved is not None:
            return self._context_window_resolved
        resolved = self._resolve_context_window(self._context_window_config)
        self._context_window_resolved = resolved
        return resolved

    @context_window.setter
    def context_window(self, value: int):
        self._context_window_resolved = int(value)
        self._context_window_config = int(value)

    def _resolve_context_window(self, config_value: int) -> int:
        """
        Query Ollama's /api/show for the model's native context length.
        Returns max(config_value, detected_value) so we never under-allocate.
        Falls back to config_value on any error (network, cloud models, etc.).
        """
        try:
            resp = self._json_request(
                "/api/show", payload={"model": self.model}, timeout=10
            )
            info = json.loads(resp)

            # Method 1: Parse from model_info metadata (most reliable)
            model_info = info.get("model_info", {})
            for key, val in model_info.items():
                if "context_length" in key.lower():
                    detected = int(val)
                    if detected > 0:
                        return max(config_value, detected)

            # Method 2: Parse num_ctx from modelfile parameters string
            params = info.get("parameters", "")
            for line in str(params).split("\n"):
                line_stripped = line.strip().lower()
                if line_stripped.startswith("num_ctx"):
                    parts = line_stripped.split()
                    if len(parts) >= 2:
                        detected = int(parts[-1])
                        if detected > 0:
                            return max(config_value, detected)
        except Exception:
            pass  # Non-fatal: cloud-routed models may not support /api/show
        return config_value

    # ------------------------------------------------------------------
    # Model selection
    # ------------------------------------------------------------------
    def _get_model_for(self, task: Optional[str] = None) -> str:
        """
        Model selection:
        - Vision tasks always use the UI-selected vision model.
        - Tasks listed in force_model_routing_tasks pull from model_routing.
        - All other tasks use the UI-selected chat model.
        """
        task = str(task or "").strip().lower()

        if task == "vision":
            routed = (self._model_routing.get("vision") or "").strip()
            chosen = routed or self.vision_model or self.model
            if self.debug_logger:
                self.debug_logger.log_model_routing(
                    task=task, selected_model=chosen,
                    default_model=self.model,
                    routed_via="model_routing" if routed else "ui_selected_vision_model",
                )
            return chosen

        routed = (self._model_routing.get(task) or "").strip()
        if routed and task in self._force_model_routing_tasks:
            if self.debug_logger:
                self.debug_logger.log_model_routing(
                    task=task, selected_model=routed,
                    default_model=self.model, routed_via="model_routing",
                )
            return routed

        if self.debug_logger and task:
            self.debug_logger.log_model_routing(
                task=task,
                selected_model=self.model,
                default_model=self.model,
                routed_via="ui_selected_chat_model",
            )
        return self.model

    # ------------------------------------------------------------------
    # Structured vision chat (system + user + image)
    # ------------------------------------------------------------------
    def chat_with_image(
        self,
        system: str,
        user: str,
        image_bytes: bytes = None,
        image_b64: str = None,
        temperature: float = 0.2,
    ) -> str:
        """
        Vision analysis with structured system/user prompts.
        Used by the vision feedback loop and the repair critic.
        """
        if not self.vision_enabled:
            return "Vision analysis is disabled."

        b64 = (
            base64.b64encode(image_bytes).decode("utf-8")
            if image_bytes is not None
            else image_b64
        )
        if b64 is None:
            raise ValueError("Provide image_bytes or image_b64")

        vision_model = self._get_model_for("vision")
        payload = {
            "model": vision_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user, "images": [b64]},
            ],
            "stream": False,
            "options": {"temperature": temperature, "num_ctx": self.context_window},
        }

        def _do():
            return (
                json.loads(
                    self._json_request("/api/chat", payload=payload, timeout=180)
                )
                .get("message", {})
                .get("content", "")
            )

        try:
            return self._request_with_retry(_do)
        except RequestCancelledError:
            raise
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise ConnectionError(
                    f"Vision model '{vision_model}' not found. "
                    f"Run: ollama pull {vision_model}"
                )
            raise ConnectionError(f"Vision HTTP Error {e.code}: {e.reason}")
        except ConnectionError:
            raise
        except Exception as e:
            raise ConnectionError(f"Vision request failed: {e}")

    def _rate_limit_error_message(self) -> str:
        remaining = max(0.0, self._rate_limited_until - time.time())
        if remaining >= 1.0:
            return (
                "Ollama is overloaded (429). "
                f"Please wait about {int(math.ceil(remaining))}s before retrying."
            )
        return "Ollama is overloaded (429). Please wait a moment and retry."

    def _retry_delay_for_http_error(
        self, error: urllib.error.HTTPError, attempt: int
    ) -> float:
        retry_after = None
        try:
            retry_after = error.headers.get("Retry-After")
        except Exception:
            retry_after = None
        if retry_after:
            try:
                return max(1.0, min(float(retry_after), 10.0))
            except Exception:
                pass

        # 429: Too Many Requests (Rate limit)
        if error.code == 429:
            return min(2.0 * (attempt + 1), 8.0)

        # 500, 502, 503, 504: Server errors (VRAM/Context/Stability)
        # We use a progressively longer backoff to allow the server to recover.
        if error.code in (500, 502, 503, 504):
            return min(3.0 * (attempt + 1), 15.0)

        return min(2.0 ** (attempt + 1), 10.0)

    # ------------------------------------------------------------------
    # Retry wrapper
    # ------------------------------------------------------------------
    def _request_with_retry(self, req_fn, retries: int = None):
        retries = retries or self.request_retries
        if time.time() < self._rate_limited_until:
            raise ConnectionError(self._rate_limit_error_message())
        for attempt in range(retries):
            try:
                return req_fn()
            except RequestCancelledError:
                raise
            except urllib.error.HTTPError as e:
                # 429 Too Many Requests or 500/502/503/504 Server-side issues
                if e.code in (429, 500, 502, 503, 504):
                    # Set rate-limit flag immediately (not just on final attempt)
                    if e.code == 429:
                        self._rate_limited_until = max(
                            self._rate_limited_until,
                            time.time() + self.rate_limit_cooldown_s,
                        )
                    if attempt == retries - 1:
                        raise
                    delay = self._retry_delay_for_http_error(e, attempt)
                    # Exponential backoff for server errors; honour the rate-limit window for 429
                    if e.code == 429:
                        delay = max(delay, min(self.rate_limit_cooldown_s, 60.0))
                    if self.debug_logger:
                        self.debug_logger.log_llm_retry(
                            attempt=attempt + 1, max_retries=retries,
                            http_code=e.code, error_type=type(e).__name__,
                            delay_s=delay, model=getattr(self, "model", None),
                        )
                    time.sleep(delay)
                    continue
                # For other HTTP errors (like 404), raise immediately so chat() can handle it
                raise
            except (ConnectionError, urllib.error.URLError, TimeoutError, OSError) as e:
                if attempt == retries - 1:
                    raise
                delay = 2 ** (attempt + 1)
                if self.debug_logger:
                    self.debug_logger.log_llm_retry(
                        attempt=attempt + 1, max_retries=retries,
                        error_type=type(e).__name__, delay_s=delay,
                        model=getattr(self, "model", None),
                    )
                # Standard exponential backoff: 2, 4, 8, 16s
                time.sleep(delay)

    def _base_parts(self):
        parsed = urllib.parse.urlparse(self.base_url)
        scheme = parsed.scheme or "http"
        host = parsed.hostname or "localhost"
        port = parsed.port or (443 if scheme == "https" else 80)
        base_path = parsed.path.rstrip("/")
        return scheme, host, port, base_path

    def _open_connection(self, timeout: int):
        scheme, host, port, _ = self._base_parts()
        conn_cls = (
            http.client.HTTPSConnection
            if scheme == "https"
            else http.client.HTTPConnection
        )
        conn = conn_cls(host, port, timeout=timeout)
        with self._connection_lock:
            self._active_connections.add(conn)
        return conn

    def _close_connection(self, conn):
        with self._connection_lock:
            self._active_connections.discard(conn)
        try:
            conn.close()
        except Exception:
            pass

    def cancel_active_requests(self):
        self._cancel_requests.set()
        with self._connection_lock:
            connections = list(self._active_connections)
            self._active_connections.clear()
        for conn in connections:
            try:
                conn.close()
            except Exception:
                pass

    def _json_request(
        self,
        path: str,
        payload: dict = None,
        timeout: int = 120,
        method: str = "POST",
    ) -> str:
        self._cancel_requests.clear()
        _, _, _, base_path = self._base_parts()
        full_path = f"{base_path}{path}"
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Content-Type": "application/json"} if payload is not None else {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        
        conn = self._open_connection(timeout)
        try:
            conn.request(method, full_path, body=body, headers=headers)
            response = conn.getresponse()
            raw = response.read()
            if response.status >= 400:
                raise urllib.error.HTTPError(
                    f"{self.base_url}{path}",
                    response.status,
                    response.reason,
                    response.headers,
                    io.BytesIO(raw),
                )
            return raw.decode("utf-8")
        except Exception:
            if self._cancel_requests.is_set():
                raise RequestCancelledError("Request cancelled by user.")
            raise
        finally:
            self._close_connection(conn)

    # ------------------------------------------------------------------
    # Core Ollama chat
    # ------------------------------------------------------------------
    def _ollama_chat(
        self,
        messages: list,
        tools: list = None,
        model_override: str = None,
        timeout_s: int = 300,
        chunk_callback=None,
    ) -> dict:
        """
        Stream Ollama's response line-by-line so that cancel_active_requests()
        can interrupt mid-generation instead of waiting for the full response.
        """
        payload = {
            "model": model_override or self.model,
            "messages": messages,
            "stream": True,          # ← streaming enabled for fast cancel
            "options": {
                "temperature": self.temperature,
                "num_ctx": self.context_window,
            },
        }
        if tools:
            payload["tools"] = tools

        self._cancel_requests.clear()
        _, _, _, base_path = self._base_parts()
        full_path = f"{base_path}/api/chat"
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        # _open_connection already registers in _active_connections
        conn = self._open_connection(timeout_s)
        started_at = time.time()
        try:
            conn.request("POST", full_path, body=body, headers=headers)
            response = conn.getresponse()
            if response.status >= 400:
                raw = response.read()
                raise urllib.error.HTTPError(
                    f"{self.base_url}/api/chat",
                    response.status,
                    response.reason,
                    response.headers,
                    io.BytesIO(raw),
                )

            # Read streamed NDJSON lines — check cancel before every chunk
            content_parts = []
            tool_calls_final = []
            last_chunk = {}
            buf = b""
            while True:
                if timeout_s and (time.time() - started_at) > float(timeout_s):
                    raise TimeoutError(
                        f"LLM request exceeded timeout ({timeout_s}s)."
                    )
                if self._cancel_requests.is_set():
                    raise RequestCancelledError("Request cancelled by user.")
                try:
                    chunk = response.read(4096)
                except Exception:
                    if self._cancel_requests.is_set():
                        raise RequestCancelledError("Request cancelled by user.")
                    raise
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    if timeout_s and (time.time() - started_at) > float(timeout_s):
                        raise TimeoutError(
                            f"LLM request exceeded timeout ({timeout_s}s)."
                        )
                    line, buf = buf.split(b"\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    last_chunk = data
                    msg = data.get("message", {})
                    part = msg.get("content", "")
                    if part:
                        content_parts.append(part)
                        # Real-time token streaming for the UI.  Failures here
                        # must never break the LLM read loop — UI is best-effort.
                        if chunk_callback is not None:
                            try:
                                chunk_callback(part)
                            except Exception:
                                pass
                    if msg.get("tool_calls"):
                        tool_calls_final = msg["tool_calls"]
                    if data.get("done"):
                        break
                if last_chunk.get("done"):
                    break

        except RequestCancelledError:
            raise
        except Exception:
            if self._cancel_requests.is_set():
                raise RequestCancelledError("Request cancelled by user.")
            raise
        finally:
            self._close_connection(conn)

        # Token usage from the final done-chunk
        self._last_token_usage = {
            "tokens_in":  last_chunk.get("prompt_eval_count"),
            "tokens_out": last_chunk.get("eval_count"),
            "total_duration_ms": int(last_chunk.get("total_duration", 0) / 1_000_000) or None,
            "model": last_chunk.get("model", payload.get("model")),
        }

        assembled = {"role": "assistant", "content": "".join(content_parts)}
        if tool_calls_final:
            assembled["tool_calls"] = tool_calls_final
        return assembled

    def _chat_via_ollama(
        self,
        messages: list,
        tools: list = None,
        task: Optional[str] = None,
        model_override: str = None,
        timeout_s: Optional[float] = None,
        chunk_callback=None,
    ) -> dict:
        # UI model selection is authoritative. Ignore explicit model overrides.
        model = self._get_model_for(task)
        if model_override and self.debug_logger:
            self.debug_logger.log_system_note(
                f"Ignoring model_override='{model_override}' in favor of UI-selected model '{model}'."
            )

        def _do(chosen_model: str):
            kwargs = {"model_override": chosen_model}
            if timeout_s is not None:
                kwargs["timeout_s"] = timeout_s
            if chunk_callback is not None:
                kwargs["chunk_callback"] = chunk_callback
            return self._ollama_chat(messages, tools, **kwargs)

        try:
            return self._request_with_retry(lambda: _do(model))
        except RequestCancelledError:
            raise
        except urllib.error.HTTPError as e:
            # Inspection of error body for 403/401
            body_msg = ""
            try:
                if hasattr(e, "fp") and e.fp:
                    body_msg = f" | Body: {e.fp.read().decode('utf-8')[:300]}"
            except Exception:
                pass

            if e.code in (404, 403, 401):
                # Try to find a local fallback if the cloud model failed
                fallback_model = self.model
                if ":cloud" in model.lower():
                    # If current is cloud, try self.model if it's different, 
                    # otherwise try to find any local model from the list.
                    if fallback_model == model:
                        available = self.list_models()
                        local_models = [m for m in available if ":cloud" not in m.lower()]
                        if local_models:
                            # Prioritize gemma models as they are known to be stable
                            gemma_models = [m for m in local_models if "gemma" in m.lower()]
                            fallback_model = gemma_models[0] if gemma_models else local_models[0]
                
                if (
                    fallback_model
                    and model != fallback_model
                ):
                    try:
                        if self.debug_logger:
                            note = f"Model '{model}' failed (HTTP {e.code}{body_msg}); "
                            note += f"trying local fallback '{fallback_model}'."
                            self.debug_logger.log_system_note(note)
                        return self._request_with_retry(
                            lambda: _do(fallback_model)
                        )
                    except Exception:
                        pass
                
                if e.code == 404:
                    raise ConnectionError(
                        f"Model '{model}' not found in Ollama. Run: ollama pull {model}"
                    )
                if e.code in (403, 401):
                    raise ConnectionError(
                        f"HTTP {e.code} Forbidden/Unauthorized: access denied for '{model}'{body_msg}. "
                        "Check your API key in core_config.json if using a cloud model."
                    )
            if e.code == 429:
                self._rate_limited_until = max(
                    self._rate_limited_until,
                    time.time() + self.rate_limit_cooldown_s,
                )
                raise ConnectionError(self._rate_limit_error_message())
            if e.code == 500:
                raise ConnectionError(
                    f"HTTP 500: Internal Server Error. The LLM backend (Ollama/Kimi) crashed. "
                    "This often happens because the prompt history is too complex or the VRAM is full."
                )
            if e.code == 400:
                raise ConnectionError(
                    f"HTTP 400: Bad Request. The context window (history/verification data) "
                    f"likely exceeded the {self.context_window} token limit for '{model}'."
                )
            raise ConnectionError(f"HTTP Error {e.code}: {e.reason}")
        except ConnectionError:
            raise
        except Exception as e:
            raise ConnectionError(f"Cannot reach Ollama at {self.base_url}. {e}")

    # ------------------------------------------------------------------
    # Unified chat dispatch
    # ------------------------------------------------------------------
    def chat(
        self,
        messages: list,
        tools: list = None,
        task: Optional[str] = None,
        model_override: str = None,
        timeout_s: Optional[float] = None,
        chunk_callback=None,
    ) -> dict:
        return self._chat_via_ollama(
            messages,
            tools=tools,
            task=task,
            model_override=model_override,
            timeout_s=timeout_s,
            chunk_callback=chunk_callback,
        )

    # ------------------------------------------------------------------
    # Vision chat
    # ------------------------------------------------------------------
    def chat_vision(
        self, prompt: str, image_bytes: bytes = None, image_b64: str = None
    ) -> str:
        """Sends an image + text prompt to a vision-capable Ollama model."""
        return self._chat_vision_via_ollama(
            prompt, image_bytes=image_bytes, image_b64=image_b64
        )

    def _chat_vision_via_ollama(
        self, prompt: str, image_bytes: bytes = None, image_b64: str = None
    ) -> str:
        """Sends an image + text prompt to a vision-capable Ollama model."""
        if not self.vision_enabled:
            return "Vision analysis is disabled by the user. Please proceed with text-only context."

        b64 = (
            base64.b64encode(image_bytes).decode("utf-8")
            if image_bytes is not None
            else image_b64
        )
        if b64 is None:
            raise ValueError("Provide image_bytes or image_b64")

        vision_model = self.vision_model
        payload = {
            "model": vision_model,
            "messages": [{"role": "user", "content": prompt, "images": [b64]}],
            "stream": False,
            "options": {"temperature": 0.2, "num_ctx": self.context_window},
        }

        def _do():
            return (
                json.loads(
                    self._json_request("/api/chat", payload=payload, timeout=180)
                )
                .get("message", {})
                .get("content", "")
            )

        try:
            return self._request_with_retry(_do)
        except RequestCancelledError:
            raise
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise ConnectionError(
                    f"Vision model '{vision_model}' not found in Ollama. "
                    f"Run: ollama pull {vision_model}"
                )
            if e.code == 400:
                raise ConnectionError(
                    f"Vision HTTP 400: Bad Request. The payload (image + prompt) "
                    f"likely exceeded the {self.context_window} token limit for '{vision_model}'."
                )
            raise ConnectionError(f"Vision HTTP Error {e.code}: {e.reason}")
        except urllib.error.URLError as e:
            raise ConnectionError(
                f"Vision model '{vision_model}' unavailable. "
                f"Pull it: ollama pull {vision_model}    Error: {e}"
            )
        except ConnectionError:
            raise

    # ------------------------------------------------------------------
    # Simple one-shot (no tools) — used by AutoResearch sub-steps
    # ------------------------------------------------------------------
    def chat_simple(
        self, system: str, user: str, temperature: float = None, task: str = "research"
    ) -> str:
        return self._chat_simple_via_ollama(
            system, user, temperature=temperature, task=task
        )

    def _chat_simple_via_ollama(
        self, system: str, user: str, temperature: float = None, task: str = "research"
    ) -> str:
        model = self._get_model_for(task)

        def _do(chosen_model: str):
            # PERF-4: stream=True so big-model calls (compression, critic, plan
            # refinement, research) don't buffer the entire response on the server
            # for 30–60s. We accumulate chunks but read them as they arrive,
            # freeing the Houdini main thread if this is called from it.
            payload = {
                "model": chosen_model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "stream": True,
                "options": {
                    "temperature": temperature
                    if temperature is not None
                    else self.temperature,
                    "num_ctx": self.context_window,
                },
            }
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                f"{self.base_url}/api/chat",
                data=data,
                headers={
                    "Content-Type": "application/json",
                    **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}),
                },
                method="POST",
            )
            parts: List[str] = []
            with urllib.request.urlopen(req, timeout=120) as resp:
                for line in resp:
                    if not line or not line.strip():
                        continue
                    try:
                        chunk = json.loads(line.decode("utf-8"))
                    except json.JSONDecodeError:
                        continue
                    delta = chunk.get("message", {}).get("content", "")
                    if delta:
                        parts.append(delta)
                    if chunk.get("done"):
                        break
            return "".join(parts)

        try:
            return self._request_with_retry(lambda: _do(model))
        except RequestCancelledError:
            raise
        except urllib.error.URLError as e:
            if hasattr(e, "code") and e.code == 404:
                fallback_model = self.model
                if fallback_model and model != fallback_model:
                    if self.debug_logger:
                        self.debug_logger.log_system_note(
                            f"Model '{model}' unavailable for task '{task}'; "
                            f"falling back to selected chat model '{fallback_model}'."
                        )
                    return self._request_with_retry(lambda: _do(fallback_model))
                raise ConnectionError(
                    f"Model '{model}' not found in Ollama. Run: ollama pull {model}"
                )
            raise ConnectionError(f"LLM error: {e}")

    # ------------------------------------------------------------------
    # Streaming — uses httpx when available for proper async chunking
    # Falls back to urllib for compatibility
    # ------------------------------------------------------------------
    def chat_stream(self, messages: list) -> Generator[str, None, None]:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": self.temperature,
                "num_ctx": self.context_window,
            },
        }
        data = json.dumps(payload).encode("utf-8")

        if _HTTPX_AVAILABLE:
            try:
                with httpx.stream(
                    "POST",
                    f"{self.base_url}/api/chat",
                    content=data,
                    headers={
                        "Content-Type": "application/json",
                        **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {})
                    },
                    timeout=httpx.Timeout(120.0, connect=10.0),
                ) as resp:
                    resp.raise_for_status()
                    for line in resp.iter_lines():
                        if line.strip():
                            try:
                                chunk = json.loads(line)
                                delta = chunk.get("message", {}).get("content", "")
                                if delta:
                                    yield delta
                                if chunk.get("done"):
                                    break
                            except json.JSONDecodeError:
                                continue
            except httpx.TimeoutException:
                yield "\n[ERROR] Request timed out after 120s."
            except httpx.HTTPStatusError as e:
                yield f"\n[ERROR] HTTP {e.response.status_code}: {e.response.text[:200]}"
            except Exception as e:
                yield f"\n[ERROR] Streaming error: {e}"
        else:
            req = urllib.request.Request(
                f"{self.base_url}/api/chat",
                data=data,
                headers={
                    "Content-Type": "application/json",
                    **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {})
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    for line in resp:
                        if line.strip():
                            try:
                                chunk = json.loads(line.decode("utf-8"))
                                delta = chunk.get("message", {}).get("content", "")
                                if delta:
                                    yield delta
                                if chunk.get("done"):
                                    break
                            except json.JSONDecodeError:
                                continue
            except urllib.error.URLError as e:
                yield f"\n[ERROR] Cannot reach Ollama: {e}"

    # ------------------------------------------------------------------
    # Embeddings — uses Ollama /api/embeddings endpoint
    # ------------------------------------------------------------------
    def embed(self, text: str, model: str = None) -> Optional[List[float]]:
        """
        Get an embedding vector from Ollama.
        Requires: ollama pull nomic-embed-text
        Returns None silently if the model isn't available.

        PERF-1: The cache used to flush the entire dict to disk after every
        new embedding — ~3MB × 60 warmup calls = ~180MB of startup I/O.
        Flushing is now debounced: mark the cache dirty here, and
        select_relevant_tools / flush_embed_cache writes when it makes sense.
        """
        model = model or self.embed_model
        if text in self._embed_cache:
            return self._embed_cache[text]

        payload = {"model": model, "prompt": text}
        try:
            vec = json.loads(
                self._json_request("/api/embeddings", payload=payload, timeout=30)
            ).get("embedding")
            if vec:
                self._embed_cache[text] = vec  # marks _dirty internally
            return vec
        except Exception:
            return None

    def flush_embed_cache(self) -> None:
        """Persist the embed cache if dirty. Call at natural checkpoints
        (end of tool-selection batches, shutdown) rather than per-embed."""
        if not self._embed_cache_path:
            return
        if getattr(self._embed_cache, "_dirty", False):
            try:
                self._embed_cache.save_to_disk(
                    self._embed_cache_path, embed_model=self.embed_model
                )
            except Exception:
                pass

    # ------------------------------------------------------------------
    # FIX: Dynamic tool selection — send only relevant schemas per request
    # ------------------------------------------------------------------
    def select_relevant_tools(
        self,
        query: str,
        all_schemas: list,
        top_n: int = None,
    ) -> list:
        """
        Return the top_n most relevant tool schemas for this query.

        Strategy (two-pass):
          Pass 1 — Always include "always-on" tools (scene read, create, save…).
          Pass 2 — Keyword match: check query words against _TOOL_KEYWORD_MAP.
          Pass 3 — If embed_model is available, score remaining tools by cosine
                   similarity and fill up to top_n.

        This keeps the prompt under 32k tokens even with 61 tools defined.
        """
        result = select_relevant_tool_schemas(
            query=query,
            all_schemas=all_schemas,
            top_n=top_n or self.max_tools,
            embed_fn=self.embed,
            config=self.config,
            model_name=self.model,
        )
        if self._embed_cache_path and getattr(self._embed_cache, "_dirty", False):
            self._embed_cache.save_to_disk(
                self._embed_cache_path, embed_model=self.embed_model
            )
        return result

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------
    def list_models(self) -> list:
        return self._list_models_via_ollama()

    def _list_models_via_ollama(self) -> list:
        try:
            data = json.loads(self._json_request("/api/tags", timeout=10, method="GET"))
            return [m["name"] for m in data.get("models", [])]
        except Exception:
            return []

    def is_available(self) -> bool:
        return self._is_ollama_available()

    def _is_ollama_available(self) -> bool:
        try:
            self._json_request("/api/tags", timeout=5, method="GET")
            return True
        except Exception:
            return False
