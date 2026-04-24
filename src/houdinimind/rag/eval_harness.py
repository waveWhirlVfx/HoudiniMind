# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
"""
Lightweight retrieval evaluation helpers for HoudiniMind RAG.
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Dict, List, Optional


def load_eval_cases(dataset_path: str) -> Dict:
    with open(dataset_path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)

    if isinstance(payload, list):
        cases = payload
        name = os.path.splitext(os.path.basename(dataset_path))[0]
    elif isinstance(payload, dict):
        cases = payload.get("cases", [])
        name = payload.get("name") or os.path.splitext(os.path.basename(dataset_path))[0]
    else:
        raise ValueError("Evaluation dataset must be a list or a dict with a 'cases' key.")

    if not isinstance(cases, list):
        raise ValueError("Evaluation dataset 'cases' must be a list.")

    return {"name": name, "cases": cases}


def _entry_matches_spec(entry: dict, spec: dict) -> bool:
    if not isinstance(entry, dict) or not isinstance(spec, dict):
        return False

    title = str(entry.get("title", ""))
    title_lower = title.lower()
    category = str(entry.get("category", ""))
    source = str(entry.get("_source", ""))
    tags = {str(tag).lower() for tag in entry.get("tags", [])}

    expected_title = spec.get("title")
    if expected_title is not None and title != expected_title:
        return False

    title_contains = spec.get("title_contains")
    if title_contains is not None and str(title_contains).lower() not in title_lower:
        return False

    expected_category = spec.get("category")
    if expected_category is not None and category != expected_category:
        return False

    expected_source = spec.get("source")
    if expected_source is not None and source != expected_source:
        return False

    tag_contains = spec.get("tag")
    if tag_contains is not None and str(tag_contains).lower() not in tags:
        return False

    content_contains = spec.get("content_contains")
    if content_contains is not None:
        content_lower = str(entry.get("content", "")).lower()
        if str(content_contains).lower() not in content_lower:
            return False

    return True


def _first_match_rank(results: List[dict], expected_any: List[dict]) -> Optional[int]:
    if not expected_any:
        return None
    for rank, entry in enumerate(results, start=1):
        if any(_entry_matches_spec(entry, spec) for spec in expected_any):
            return rank
    return None


def evaluate_retriever(retriever, cases: List[dict], top_k: int = 5) -> Dict:
    per_case = []
    hit_count = 0
    reciprocal_rank_sum = 0.0
    category_hit_count = 0

    for index, case in enumerate(cases, start=1):
        query = str(case.get("query") or "").strip()
        expected_any = case.get("expected_any") or []
        expected_categories = [
            str(value).strip()
            for value in (case.get("expected_categories") or [])
            if str(value).strip()
        ]

        results = retriever.retrieve(
            query=query,
            top_k=top_k,
            include_memory=False,
            use_rerank=False,
        )
        match_rank = _first_match_rank(results, expected_any)
        hit = match_rank is not None
        if hit:
            hit_count += 1
            reciprocal_rank_sum += 1.0 / match_rank

        category_hit = False
        if expected_categories:
            retrieved_categories = {str(entry.get("category", "")) for entry in results}
            category_hit = any(category in retrieved_categories for category in expected_categories)
            if category_hit:
                category_hit_count += 1

        per_case.append(
            {
                "id": case.get("id") or f"case_{index}",
                "query": query,
                "hit": hit,
                "match_rank": match_rank,
                "category_hit": category_hit,
                "expected_any": expected_any,
                "expected_categories": expected_categories,
                "results": [
                    {
                        "title": entry.get("title", ""),
                        "category": entry.get("category", ""),
                        "score": entry.get("_score", 0),
                    }
                    for entry in results
                ],
            }
        )

    case_count = len(cases)
    return {
        "case_count": case_count,
        "hit_at_k": (hit_count / case_count) if case_count else 0.0,
        "mrr": (reciprocal_rank_sum / case_count) if case_count else 0.0,
        "category_hit_rate": (category_hit_count / case_count) if case_count else 0.0,
        "top_k": top_k,
        "cases": per_case,
    }


def run_retrieval_eval(
    data_dir: str,
    dataset_path: str,
    top_k: int = 5,
    config: dict = None,
) -> Dict:
    from . import create_rag_pipeline

    cfg = dict(config or {})
    cfg.setdefault("rag_hybrid_search", False)
    dataset = load_eval_cases(dataset_path)
    injector = create_rag_pipeline(data_dir, cfg)
    summary = evaluate_retriever(injector.retriever, dataset["cases"], top_k=top_k)
    summary["dataset_name"] = dataset["name"]
    summary["dataset_path"] = os.path.abspath(dataset_path)
    summary["data_dir"] = os.path.abspath(data_dir)
    return summary


def _default_data_dir() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(os.path.dirname(os.path.dirname(here)))
    return os.path.join(root, "data")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run a HoudiniMind RAG retrieval eval.")
    parser.add_argument("--dataset", required=True, help="Path to the eval dataset JSON file.")
    parser.add_argument("--data-dir", default=_default_data_dir(), help="Path to the project data directory.")
    parser.add_argument("--top-k", type=int, default=5, help="Number of chunks to retrieve per query.")
    parser.add_argument("--hybrid", choices=("config", "on", "off"), default="config")
    parser.add_argument("--output", help="Optional path to write the JSON summary.")
    args = parser.parse_args(argv)

    config = {}
    if args.hybrid == "on":
        config["rag_hybrid_search"] = True
    elif args.hybrid == "off":
        config["rag_hybrid_search"] = False

    summary = run_retrieval_eval(
        data_dir=args.data_dir,
        dataset_path=args.dataset,
        top_k=args.top_k,
        config=config,
    )
    rendered = json.dumps(summary, indent=2, ensure_ascii=False)
    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(rendered)
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
