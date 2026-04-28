# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
from __future__ import annotations

from collections.abc import Generator


class BackendCapabilityError(ConnectionError):
    """Raised when a backend cannot satisfy a requested capability."""


class BaseInferenceBackend:
    name = "base"
    supports_tools = False
    supports_vision = False
    supports_embeddings = False

    def __init__(self, config: dict):
        self.config = config or {}

    def chat(
        self,
        messages: list,
        tools: list | None = None,
        task: str | None = None,
        model_override: str | None = None,
    ) -> dict:
        raise BackendCapabilityError(f"{self.name} backend does not implement chat().")

    def chat_simple(
        self, system: str, user: str, temperature: float | None = None, task: str = "research"
    ) -> str:
        raise BackendCapabilityError(f"{self.name} backend does not implement chat_simple().")

    def chat_stream(self, messages: list) -> Generator[str, None, None]:
        raise BackendCapabilityError(f"{self.name} backend does not implement chat_stream().")

    def chat_vision(
        self, prompt: str, image_bytes: bytes | None = None, image_b64: str | None = None
    ) -> str:
        raise BackendCapabilityError(f"{self.name} backend does not support vision.")

    def embed(self, text: str, model: str | None = None) -> list[float] | None:
        raise BackendCapabilityError(f"{self.name} backend does not support embeddings.")

    def list_models(self) -> list:
        return []

    def is_available(self) -> bool:
        return False

    def cancel_active_requests(self) -> None:
        return None
