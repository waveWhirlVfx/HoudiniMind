# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
from __future__ import annotations

import argparse
import json
import os
import statistics
from collections.abc import Iterable


def _session_jsonl_path(session_path: str) -> str:
    if os.path.isdir(session_path):
        return os.path.join(session_path, "session.jsonl")
    return session_path


def load_session_events(session_path: str) -> list[dict]:
    path = _session_jsonl_path(session_path)
    events = []
    with open(path, encoding="utf-8") as handle:
        for raw in handle:
            raw = raw.strip()
            if raw:
                events.append(json.loads(raw))
    return events


def _group_turns(events: Iterable[dict]) -> dict[int, list[dict]]:
    grouped: dict[int, list[dict]] = {}
    for event in events:
        turn_index = int(event.get("turn_index", 0) or 0)
        if turn_index > 0:
            grouped.setdefault(turn_index, []).append(event)
    return grouped


def _mean(values: list[float]) -> float:
    return round(statistics.mean(values), 3) if values else 0.0


def summarize_replay_session(session_path: str) -> dict:
    events = load_session_events(session_path)
    turns = _group_turns(events)
    llm_calls = [e for e in events if e.get("event") == "llm_call"]
    tool_calls = [e for e in events if e.get("event") == "tool"]
    responses = [e for e in events if e.get("event") == "response"]
    notes = [e for e in events if e.get("event") == "system_note"]
    screenshots = [e for e in events if e.get("event") == "screenshot"]

    verification_passes = 0
    verification_fails = 0
    semantic_passes = 0
    semantic_fails = 0
    max_round_hits = 0
    per_turn = []

    for turn_index, turn_events in sorted(turns.items()):
        request = ""
        response = ""
        turn_tools = []
        verification = ""
        semantic = ""
        for event in turn_events:
            if event.get("event") == "turn_start":
                request = str(event.get("user_message", "") or "").strip()
            elif event.get("event") == "tool":
                turn_tools.append(str(event.get("tool", "") or ""))
            elif event.get("event") == "response":
                response = str(event.get("content", "") or "")
            elif event.get("event") == "system_note":
                content = str(event.get("content", "") or "")
                if content.startswith("[VERIFICATION]"):
                    verification = content
                elif content.startswith("[SEMANTIC SCORE]"):
                    semantic = content

        response_lower = response.lower()
        if "max tool rounds reached" in response_lower:
            max_round_hits += 1
        if verification.startswith("[VERIFICATION] PASS"):
            verification_passes += 1
        elif verification.startswith("[VERIFICATION] FAIL"):
            verification_fails += 1
        if semantic.startswith("[SEMANTIC SCORE] PASS"):
            semantic_passes += 1
        elif semantic.startswith("[SEMANTIC SCORE] FAIL"):
            semantic_fails += 1

        per_turn.append(
            {
                "turn_index": turn_index,
                "request": request,
                "response_excerpt": response[:200],
                "tool_count": len(turn_tools),
                "tools": turn_tools,
                "verification": verification.splitlines()[0] if verification else "",
                "semantic": semantic.splitlines()[0] if semantic else "",
                "max_round_reached": "max tool rounds reached" in response_lower,
            }
        )

    llm_ms = [
        float(e.get("elapsed_ms", 0) or 0) for e in llm_calls if e.get("elapsed_ms") is not None
    ]
    tool_ms = [
        float(e.get("duration_ms", 0) or 0) for e in tool_calls if e.get("duration_ms") is not None
    ]
    tool_errors = sum(1 for e in tool_calls if e.get("status") != "ok")
    session_id = os.path.basename(os.path.dirname(_session_jsonl_path(session_path)))

    return {
        "session_id": session_id,
        "session_path": os.path.abspath(_session_jsonl_path(session_path)),
        "turn_count": len(per_turn),
        "llm_call_count": len(llm_calls),
        "tool_call_count": len(tool_calls),
        "tool_error_count": tool_errors,
        "response_count": len(responses),
        "screenshot_count": len(screenshots),
        "verification_passes": verification_passes,
        "verification_fails": verification_fails,
        "semantic_passes": semantic_passes,
        "semantic_fails": semantic_fails,
        "max_round_hits": max_round_hits,
        "avg_llm_ms": _mean(llm_ms),
        "avg_tool_ms": _mean(tool_ms),
        "notes_count": len(notes),
        "turns": per_turn,
    }


def run_replay_eval(
    sessions_root: str,
    session_ids: list[str] | None = None,
) -> dict:
    candidates = []
    if session_ids:
        for session_id in session_ids:
            candidates.append(os.path.join(sessions_root, session_id))
    else:
        for name in sorted(os.listdir(sessions_root)):
            session_dir = os.path.join(sessions_root, name)
            if os.path.isdir(session_dir) and os.path.isfile(
                os.path.join(session_dir, "session.jsonl")
            ):
                candidates.append(session_dir)

    sessions = [summarize_replay_session(path) for path in candidates]
    return {
        "sessions_root": os.path.abspath(sessions_root),
        "session_count": len(sessions),
        "sessions": sessions,
        "totals": {
            "turn_count": sum(item["turn_count"] for item in sessions),
            "llm_call_count": sum(item["llm_call_count"] for item in sessions),
            "tool_call_count": sum(item["tool_call_count"] for item in sessions),
            "tool_error_count": sum(item["tool_error_count"] for item in sessions),
            "verification_passes": sum(item["verification_passes"] for item in sessions),
            "verification_fails": sum(item["verification_fails"] for item in sessions),
            "semantic_passes": sum(item["semantic_passes"] for item in sessions),
            "semantic_fails": sum(item["semantic_fails"] for item in sessions),
            "max_round_hits": sum(item["max_round_hits"] for item in sessions),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Replay HoudiniMind debug sessions into aggregate metrics."
    )
    parser.add_argument("--sessions-root", default=os.path.join("data", "debug", "sessions"))
    parser.add_argument("--session", action="append", dest="session_ids")
    parser.add_argument("--output", help="Optional output JSON path.")
    args = parser.parse_args(argv)

    summary = run_replay_eval(args.sessions_root, session_ids=args.session_ids)
    rendered = json.dumps(summary, indent=2, ensure_ascii=False)
    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(rendered)
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
