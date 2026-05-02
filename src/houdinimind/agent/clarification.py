"""
HoudiniMind — User clarification channel.

When the user's request is ambiguous enough that one short question would
meaningfully improve the outcome, the agent asks instead of guessing.

Hooked from `HoudiniAgent.chat()` after request-mode classification but
before any Houdini-touching work (planning, scene snapshots, tool calls).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

# --- Static guards ---------------------------------------------------------

# If the user signals "you decide" we never ask back.
_AUTONOMY_HINTS = (
    "you decide",
    "you pick",
    "any way",
    "any approach",
    "doesn't matter",
    "your call",
    "whatever",
    "just pick",
    "just choose",
    "be creative",
    "surprise me",
)

# Lightweight requests that should never trigger a clarification.
_TRIVIAL_INTENTS = (
    "ping",
    "list nodes",
    "list the nodes",
    "what's in the scene",
    "what is in the scene",
    "show errors",
    "undo",
    "redo",
    "save",
    "save the scene",
    "delete",
    "clear",
    "reset",
)

# Request-mode classes where we never clarify.
_NEVER_CLARIFY_MODES = frozenset({"advice", "read", "smalltalk"})


@dataclass
class ClarificationDecision:
    ask: bool
    question: str = ""
    options: list[str] = field(default_factory=list)
    reason: str = ""

    def to_user_text(self) -> str:
        if not self.ask:
            return ""
        lines = [self.question.strip()]
        if self.options:
            lines.append("")
            for i, opt in enumerate(self.options, 1):
                lines.append(f"  {i}. {opt}")
            lines.append("")
            lines.append("(Reply with a number or describe in your own words.)")
        return "\n".join(lines)


_AMBIGUITY_SYSTEM = (
    "You are a Houdini FX expert deciding whether a user request is too "
    "ambiguous to act on without asking ONE short clarifying question.\n\n"
    "Ask ONLY when guessing would likely produce the wrong result and a "
    "single question would resolve it. Do NOT ask when the user has given "
    "enough information for a reasonable default, or when the request is "
    'broad on purpose ("build something cool").\n\n'
    "Return strict JSON, no prose, in this exact shape:\n"
    '{"ask": true|false, "question": "...", "options": ["..."], "reason": "..."}'
    "\n\n"
    "- ask: true only if asking improves the outcome.\n"
    "- question: ≤ 25 words, plain English.\n"
    "- options: 2–4 short example answers, or [] if open-ended.\n"
    "- reason: ≤ 15 words on what's ambiguous.\n"
    "If unsure, prefer ask=false."
)


def _strip_json_block(text: str) -> str:
    text = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fence:
        return fence.group(1).strip()
    return text


def _parse_decision(raw: str) -> ClarificationDecision:
    if not raw:
        return ClarificationDecision(ask=False, reason="empty LLM response")
    cleaned = _strip_json_block(raw)
    # Find the first JSON object — model sometimes prepends commentary.
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        return ClarificationDecision(ask=False, reason="no JSON in response")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as e:
        return ClarificationDecision(ask=False, reason=f"json parse: {e}")
    if not isinstance(data, dict):
        return ClarificationDecision(ask=False, reason="not an object")
    ask = bool(data.get("ask", False))
    question = str(data.get("question") or "").strip()
    if ask and not question:
        return ClarificationDecision(ask=False, reason="ask=true but no question")
    options_raw = data.get("options") or []
    options: list[str] = []
    if isinstance(options_raw, list):
        for opt in options_raw[:4]:
            if isinstance(opt, str) and opt.strip():
                options.append(opt.strip()[:120])
    return ClarificationDecision(
        ask=ask,
        question=question[:240],
        options=options,
        reason=str(data.get("reason") or "")[:160],
    )


class Clarifier:
    """
    Decides if the agent should ask the user a clarifying question.

    Cheap static guards run first. Only when those pass does it spend an
    LLM call on the ambiguity judgment. One clarification per turn maximum.
    """

    def __init__(self, llm, *, enabled: bool = True, min_words: int = 4):
        self.llm = llm
        self.enabled = enabled
        # Below this word-count we treat as too short to warrant LLM cost.
        self.min_words = min_words

    def should_clarify(
        self,
        user_message: str,
        request_mode: str,
        *,
        scene_brief: str = "",
        recent_clarification_in_history: bool = False,
    ) -> ClarificationDecision:
        if not self.enabled or self.llm is None:
            return ClarificationDecision(ask=False, reason="clarifier disabled")

        msg = (user_message or "").strip()
        if not msg:
            return ClarificationDecision(ask=False, reason="empty message")

        lowered = msg.lower()

        if request_mode in _NEVER_CLARIFY_MODES:
            return ClarificationDecision(ask=False, reason=f"mode={request_mode}")

        # Don't pile clarifications on top of clarifications.
        if recent_clarification_in_history:
            return ClarificationDecision(ask=False, reason="just asked")

        if any(hint in lowered for hint in _AUTONOMY_HINTS):
            return ClarificationDecision(ask=False, reason="user delegated choice")

        if any(intent in lowered for intent in _TRIVIAL_INTENTS) and len(msg) < 60:
            return ClarificationDecision(ask=False, reason="trivial intent")

        words = re.findall(r"\w+", msg)
        if len(words) < self.min_words:
            # Too short to bother asking — let the agent take a best-guess path.
            return ClarificationDecision(ask=False, reason="too short")

        scene_section = (
            f"\n\nCURRENT SCENE (brief):\n{scene_brief.strip()[:600]}" if scene_brief else ""
        )
        user_prompt = (
            f"REQUEST_MODE: {request_mode}\n"
            f"USER_REQUEST: {msg}"
            f"{scene_section}\n\n"
            "Decide. Return JSON only."
        )

        try:
            raw = self.llm.chat_simple(
                system=_AMBIGUITY_SYSTEM,
                user=user_prompt,
                temperature=0.0,
                task="critic",
            )
        except Exception as e:
            # Never block a turn on a clarifier failure.
            return ClarificationDecision(ask=False, reason=f"llm error: {e}")

        return _parse_decision(raw)
