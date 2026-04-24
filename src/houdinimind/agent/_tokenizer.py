# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
"""
HoudiniMind — Token Counting Utility v2
Provides accurate token counting via tiktoken (cl100k_base) with
robust fallback to character-based heuristics.

New in v2:
  - tiktoken cl100k_base for GPT-4/Claude-compatible models (Ollama, OpenAI)
  - tiktoken p50k_base for Codex/Davinci models
  - Per-message accounting (role + content overheads)
  - Proactive context sizing (estimate_messages_tokens)
  - Config-aware context budgeting
"""

import re

_tiktoken_encoder = None
_tiktoken_encoding = None


def _get_tiktoken_encoder():
    global _tiktoken_encoder, _tiktoken_encoding
    if _tiktoken_encoder is not None:
        return _tiktoken_encoder

    try:
        import tiktoken

        try:
            _tiktoken_encoder = tiktoken.get_encoding("cl100k_base")
            _tiktoken_encoding = "cl100k_base"
        except KeyError:
            try:
                _tiktoken_encoder = tiktoken.get_encoding("p50k_base")
                _tiktoken_encoding = "p50k_base"
            except KeyError:
                _tiktoken_encoder = tiktoken.get_encoding("gpt2")
                _tiktoken_encoding = "gpt2"
    except ImportError:
        _tiktoken_encoder = None
        _tiktoken_encoding = None

    return _tiktoken_encoder


def count_tokens(text: str) -> int:
    """Count tokens in a string using tiktoken if available, heuristic fallback otherwise."""
    enc = _get_tiktoken_encoder()
    if enc is not None:
        return len(enc.encode(text, disallowed_special=()))
    return _heuristic_tokens(text)


def _heuristic_tokens(text: str) -> int:
    """Fallback: ~4 chars per token for English, adjusted for code/Unicode."""
    if not text:
        return 0
    code_chars = sum(1 for c in text if c in "{}[]();,\n\t")
    non_ascii = sum(1 for c in text if ord(c) > 127)
    ascii_text = len([c for c in text if ord(c) < 128])
    code_factor = 0.5
    return max(1, int(ascii_text / 4.0 * code_factor) + non_ascii + code_chars // 2)


_MESSAGE_ROLE_OVERHEAD = {
    "system": 4,
    "user": 4,
    "assistant": 4,
    "tool": 12,
}


# PERF-3: Token counts are recomputed repeatedly for the same messages
# every round (TokenBudget.can_fit runs per LLM round, and the same history
# messages are almost always re-counted). Cache results on a fingerprint of
# (role, len(content), content prefix+suffix, tool_call count). Bounded to
# avoid unbounded growth on long sessions.
_MESSAGE_TOKEN_CACHE: dict = {}
_MESSAGE_TOKEN_CACHE_MAX = 4096


def _message_fingerprint(role: str, content: str, tool_calls_n: int) -> tuple:
    if len(content) <= 128:
        body = content
    else:
        body = content[:64] + content[-64:]
    return (role, len(content), tool_calls_n, body)


def count_message_tokens(msg: dict) -> int:
    """
    Estimate token cost of a single message dict.

    Handles:
      - Plain string content
      - List content (e.g. [{"type": "text", "text": ...}, {"type": "image_url", ...}])
      - Tool result messages
      - Tool call messages
    """
    role = msg.get("role", "user")
    overhead = _MESSAGE_ROLE_OVERHEAD.get(role, 4)

    content = msg.get("content", "")
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                if part.get("type") == "text":
                    parts.append(part.get("text", ""))
                elif part.get("type") == "image_url":
                    parts.append("[image]")
            else:
                parts.append(str(part))
        content = " ".join(parts)
    elif not isinstance(content, str):
        content = str(content)

    tool_calls_n = len(msg["tool_calls"]) if msg.get("tool_calls") else 0
    fp = _message_fingerprint(role, content, tool_calls_n)
    cached = _MESSAGE_TOKEN_CACHE.get(fp)
    if cached is not None:
        return cached

    tokens = count_tokens(content) + overhead
    if tool_calls_n:
        tokens += 15 * tool_calls_n

    if len(_MESSAGE_TOKEN_CACHE) >= _MESSAGE_TOKEN_CACHE_MAX:
        # Evict a single arbitrary entry to keep the cache bounded.
        try:
            _MESSAGE_TOKEN_CACHE.pop(next(iter(_MESSAGE_TOKEN_CACHE)))
        except StopIteration:
            pass
    _MESSAGE_TOKEN_CACHE[fp] = tokens
    return tokens


def count_messages_tokens(messages: list) -> int:
    """Sum token counts for all messages in a conversation history."""
    return sum(count_message_tokens(m) for m in messages)


def estimate_messages_tokens(
    messages: list, include_tool_schemas: list = None, system_prompt: str = ""
) -> dict:
    """
    Estimate total token footprint of a request payload.

    Returns dict with:
      - total: total estimated tokens
      - messages: tokens from message history
      - schemas: tokens from tool schemas (if any)
      - system: tokens from system prompt (if any)
      - available: context_window - total (spare for response)
    """
    system_overhead = count_tokens(system_prompt) if system_prompt else 0
    messages_overhead = count_messages_tokens(messages)
    schemas_overhead = 0
    if include_tool_schemas:
        import json

        schemas_text = json.dumps(include_tool_schemas)
        schemas_overhead = count_tokens(schemas_text)

    total = system_overhead + messages_overhead + schemas_overhead
    return {
        "total": total,
        "messages": messages_overhead,
        "schemas": schemas_overhead,
        "system": system_overhead,
    }


class TokenBudget:
    """
    Token budget tracker for proactive context management.

    Usage:
        budget = TokenBudget(context_window=65536, safety_margin=0.70)
        if not budget.can_fit(messages, schemas):
            messages = budget.truncate(messages, schemas)
    """

    def __init__(
        self,
        context_window: int = 65536,
        safety_margin: float = 0.70,
        max_single_result: int = 2000,
        min_messages_kept: int = 2,
    ):
        self.context_window = context_window
        self.safety_margin = safety_margin
        self.max_single_result = max_single_result
        self.min_messages_kept = min_messages_kept
        self.used_tokens = 0

    @property
    def token_budget(self) -> int:
        return int(self.context_window * self.safety_margin)

    def can_fit(
        self, messages: list, schemas: list = None, system_prompt: str = ""
    ) -> bool:
        est = estimate_messages_tokens(messages, schemas, system_prompt)
        self.used_tokens = est["total"]
        return est["total"] <= self.token_budget

    def truncate(self, messages: list, schemas: list = None) -> list:
        """
        Truncate message history to fit within token budget.

        Strategy:
          1. System prompt + first user message are always kept (anchors)
          2. Cap individual tool results at max_single_result tokens
          3. Greedily include messages newest-first until budget exhausted
          4. Preserve tool_call / tool result pairing (never orphan a tool result)
        """
        if not messages or len(messages) < 2:
            return messages

        sys_msg = messages[0]
        user_msg = messages[1]

        reserved = (
            count_message_tokens(sys_msg)
            + count_message_tokens(user_msg)
            + (count_tokens(str(schemas)) if schemas else 0)
        )

        if reserved >= self.token_budget:
            return [sys_msg, user_msg]

        budget = self.token_budget - reserved

        def cap_tool_result(msg: dict) -> dict:
            if msg.get("role") != "tool":
                return msg
            content = msg.get("content", "")
            if (
                isinstance(content, str)
                and count_tokens(content) > self.max_single_result
            ):
                char_limit = self.max_single_result * 4
                msg = dict(msg)
                msg["content"] = (
                    content[:char_limit] + "\n[...truncated to save context space...]"
                )
            return msg

        history = [m for m in messages[2:] if m.get("role") != "system"]
        if not history:
            return [sys_msg, user_msg]

        selected = []
        for msg in reversed(history):
            msg = cap_tool_result(msg)
            cost = count_message_tokens(msg)
            if cost > budget:
                break
            selected.append(msg)
            budget -= cost

        selected.reverse()

        if selected and selected[0].get("role") == "tool":
            first_idx = next((i for i, m in enumerate(history) if m is selected[0]), -1)
            if first_idx > 0:
                prev = cap_tool_result(history[first_idx - 1])
                if count_message_tokens(prev) <= budget:
                    selected.insert(0, prev)
            else:
                selected = selected[1:]

        if (
            len(selected) < self.min_messages_kept
            and len(history) >= self.min_messages_kept
        ):
            selected = history[-self.min_messages_kept :]

        return [sys_msg, user_msg] + selected
