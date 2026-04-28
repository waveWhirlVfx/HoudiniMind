# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass

SCORE_KEYS = (
    "identity",
    "completeness",
    "proportion",
    "support",
    "editability",
)

DEFAULT_DIMENSION_WEIGHTS = {
    "identity": 0.38,
    "completeness": 0.22,
    "proportion": 0.18,
    "support": 0.14,
    "editability": 0.08,
}

DEFAULT_VIEW_WEIGHTS = {
    "viewport": 0.34,
    "perspective": 0.24,
    "front": 0.18,
    "left": 0.12,
    "right": 0.12,
    "top": 0.10,
}


def _clamp_score(value) -> float:
    try:
        score = float(value)
    except Exception:
        return 0.0
    if score < 0.0:
        return 0.0
    if score > 1.0:
        return 1.0
    return score


@dataclass
class SemanticViewScore:
    view: str
    scores: dict[str, float]
    overall: float
    summary: str
    issues: list[str]
    verdict: str
    raw: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SemanticScorecard:
    overall: float
    threshold: float
    verdict: str
    scores: dict[str, float]
    per_view: list[dict]
    summary: str
    issues: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def compute_weighted_score(
    scores: dict[str, float],
    weights: dict[str, float] | None = None,
) -> float:
    active_weights = dict(weights or DEFAULT_DIMENSION_WEIGHTS)
    total_weight = 0.0
    weighted = 0.0
    for key in SCORE_KEYS:
        weight = float(active_weights.get(key, 0.0) or 0.0)
        if weight <= 0:
            continue
        weighted += _clamp_score(scores.get(key, 0.0)) * weight
        total_weight += weight
    if total_weight <= 0:
        return 0.0
    return round(weighted / total_weight, 4)


def _extract_json_block(raw: str) -> dict | None:
    text = (raw or "").strip()
    if not text:
        return None
    candidate = text
    if "```" in candidate:
        candidate = re.sub(
            r"^```(?:json)?\s*|\s*```$",
            "",
            candidate.strip(),
            flags=re.IGNORECASE,
        )
    for probe in (candidate,):
        try:
            parsed = json.loads(probe)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            match = re.search(r"\{.*\}", probe, re.DOTALL)
            if match:
                try:
                    parsed = json.loads(match.group(0))
                    if isinstance(parsed, dict):
                        return parsed
                except Exception:
                    pass
    return None


def parse_view_score(
    raw: str | None,
    view: str,
    threshold: float = 0.72,
    weights: dict[str, float] | None = None,
) -> SemanticViewScore:
    text = (raw or "").strip()
    parsed = _extract_json_block(text) or {}
    raw_scores = parsed.get("scores") or parsed
    scores = {key: _clamp_score(raw_scores.get(key, 0.0)) for key in SCORE_KEYS}
    overall = _clamp_score(parsed.get("overall", compute_weighted_score(scores, weights)))
    issues = []
    for item in parsed.get("issues", []) or []:
        if isinstance(item, str) and item.strip():
            issues.append(item.strip())
        elif isinstance(item, dict):
            message = str(item.get("message", "") or "").strip()
            if message:
                issues.append(message)
    summary = str(parsed.get("summary", "") or "").strip()
    verdict = str(parsed.get("verdict", "") or "").strip().upper()
    if verdict not in {"PASS", "FAIL"}:
        verdict = "PASS" if overall >= threshold else "FAIL"
    return SemanticViewScore(
        view=view,
        scores=scores,
        overall=overall,
        summary=summary,
        issues=issues,
        verdict=verdict,
        raw=text,
    )


def aggregate_view_scores(
    views: list[SemanticViewScore],
    threshold: float = 0.72,
    dimension_weights: dict[str, float] | None = None,
    view_weights: dict[str, float] | None = None,
) -> SemanticScorecard:
    if not views:
        return SemanticScorecard(
            overall=0.0,
            threshold=threshold,
            verdict="FAIL",
            scores={key: 0.0 for key in SCORE_KEYS},
            per_view=[],
            summary="No semantic evidence was collected.",
            issues=["No semantic evidence was collected."],
        )

    active_view_weights = dict(DEFAULT_VIEW_WEIGHTS)
    active_view_weights.update(view_weights or {})
    dimension_scores = {}
    for key in SCORE_KEYS:
        weighted = 0.0
        total = 0.0
        for view in views:
            view_weight = float(active_view_weights.get(view.view.lower(), 0.12))
            if view_weight <= 0:
                continue
            weighted += _clamp_score(view.scores.get(key, 0.0)) * view_weight
            total += view_weight
        dimension_scores[key] = round(weighted / total, 4) if total else 0.0

    overall = compute_weighted_score(dimension_scores, dimension_weights)
    issues = []
    seen = set()
    for view in views:
        if view.verdict == "FAIL" and view.summary and view.summary not in seen:
            issues.append(f"{view.view}: {view.summary}")
            seen.add(view.summary)
        for issue in view.issues:
            marker = f"{view.view}:{issue}"
            if marker not in seen:
                issues.append(f"{view.view}: {issue}")
                seen.add(marker)
    weakest = sorted(
        ((key, score) for key, score in dimension_scores.items()),
        key=lambda item: item[1],
    )[:2]
    weak_text = ", ".join(f"{key}={score:.2f}" for key, score in weakest)
    verdict = "PASS" if overall >= threshold else "FAIL"
    summary = (
        f"Semantic score {overall:.2f} against threshold {threshold:.2f}. "
        f"Weakest dimensions: {weak_text}."
    )
    return SemanticScorecard(
        overall=overall,
        threshold=threshold,
        verdict=verdict,
        scores=dimension_scores,
        per_view=[view.to_dict() for view in views],
        summary=summary,
        issues=issues[:10],
    )


def format_scorecard(scorecard: SemanticScorecard | None) -> str:
    if not scorecard:
        return ""
    lines = [
        f"[SEMANTIC SCORE] {scorecard.verdict}",
        f"Overall: {scorecard.overall:.2f} / Threshold: {scorecard.threshold:.2f}",
    ]
    lines.append(
        "Dimensions: "
        + ", ".join(f"{key}={scorecard.scores.get(key, 0.0):.2f}" for key in SCORE_KEYS)
    )
    if scorecard.summary:
        lines.append(scorecard.summary)
    for issue in scorecard.issues[:8]:
        lines.append(f"- {issue}")
    return "\n".join(lines)
