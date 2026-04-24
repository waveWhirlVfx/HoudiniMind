# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
"""
HoudiniMind — Knowledge Search Tools
RAG-driven knowledge base queries for VEX snippets, node recipes, and error fixes.
"""

from . import _core as core


_BUILD_QUERY_FALLBACKS = {
    "cup": ["mug", "tea cup"],
    "mug": ["cup", "tea cup"],
    "chair": ["chair workflow", "dining chair", "kitchen chair"],
    "table": ["table workflow", "dining table", "coffee table"],
    "lamp": ["lamp workflow", "floor lamp", "desk lamp"],
    "bottle": ["wine bottle"],
    "bed": ["bed workflow", "mattress", "pillow"],
    "sofa": ["sofa", "couch"],
}


def _expanded_search_queries(query: str, category_filter: str = None) -> list:
    query = str(query or "").strip()
    if not query:
        return []

    lower = query.lower()
    variants = []

    def add(text: str):
        candidate = str(text or "").strip()
        if candidate and candidate not in variants:
            variants.append(candidate)

    add(query)
    add(f"{query} workflow")
    add(f"{query} node chain")
    add(f"{query} procedural")
    add(f"{query} high fidelity")
    add(f"{query} recipe")

    if category_filter:
        add(f"{query} {category_filter}")

    for term, aliases in _BUILD_QUERY_FALLBACKS.items():
        if term in lower:
            for alias in aliases:
                add(f"{alias} workflow")
                add(f"{alias} node chain")
                add(f"{alias} procedural high fidelity")
    return variants


def search_knowledge(query: str, top_k: int = 5, category_filter: str = None) -> dict:
    """Hybrid keyword search across HoudiniMind knowledge base. Call FIRST before writing VEX or planning a workflow."""
    try:
        retriever = core._get_search_retriever()
        if retriever:
            results = retriever.retrieve(
                query=query,
                top_k=top_k,
                category_filter=category_filter,
                include_memory=False,
                use_rerank=False,
            )
            if not results:
                for fallback_query in _expanded_search_queries(query, category_filter):
                    if fallback_query == query:
                        continue
                    results = retriever.retrieve(
                        query=fallback_query,
                        top_k=top_k,
                        category_filter=category_filter,
                        include_memory=False,
                        use_rerank=False,
                    )
                    if results:
                        break
            formatted = [
                {
                    "id": entry.get("id", entry.get("_id", "")),
                    "title": entry.get("title", ""),
                    "category": entry.get("category", ""),
                    "relevance_score": entry.get("_score", 0),
                    "content": entry.get("content", ""),
                }
                for entry in results
            ]
            return core._ok(
                {"query": query, "results_found": len(formatted), "results": formatted}
            )
    except Exception:
        pass
    return core._lexical_search_knowledge(
        query, top_k=top_k, category_filter=category_filter
    )


def get_vex_snippet(task: str) -> dict:
    """Return VEX code snippets for a task (noise displacement, copy stamp, group by normal, etc)."""
    result = search_knowledge(task, top_k=3, category_filter="vex")
    if result["status"] == "ok" and result["data"]["results"]:
        return core._ok(
            {
                "task": task,
                "snippets": [r["content"] for r in result["data"]["results"]],
                "count": len(result["data"]["results"]),
            }
        )
    return core._ok(
        {
            "task": task,
            "snippets": [],
            "count": 0,
            "note": "No snippet found — write custom VEX based on the task",
        }
    )


def get_node_recipe(workflow: str) -> dict:
    """Return step-by-step recipe for: scatter, vellum cloth, boolean, uv, soft body, etc."""
    result = search_knowledge(workflow, top_k=2, category_filter="recipe")
    if result["status"] == "ok" and result["data"]["results"]:
        return core._ok(
            {
                "workflow": workflow,
                "recipes": [r["content"] for r in result["data"]["results"]],
            }
        )
    return core._ok(
        {
            "workflow": workflow,
            "recipes": [],
            "note": "No recipe found — use research() for full plan",
        }
    )


def explain_node_type(node_type: str) -> dict:
    """Plain-English explanation of a node type, its key parms, and typical usage."""
    try:
        core._require_hou()
        kb = search_knowledge(node_type, top_k=2, category_filter="nodes")
        if not kb["data"]["results"]:
            kb = search_knowledge(node_type, top_k=2)
        results = kb["data"]["results"]
        if not results:
            return core._ok(
                {
                    "node_type": node_type,
                    "explanation": f"No built-in explanation for '{node_type}'. Check Houdini documentation.",
                }
            )
        return core._ok(
            {
                "node_type": node_type,
                "explanation": results[0]["content"],
                "source": results[0].get("title", "Knowledge Base"),
            }
        )
    except Exception as e:
        return core._err(str(e))


def suggest_workflow(goal: str) -> dict:
    """Given a plain-English goal, return recommended node chain and tips."""
    try:
        core._require_hou()
        kb = search_knowledge(goal, top_k=3, category_filter="recipe")
        if not kb["data"]["results"]:
            kb = search_knowledge(goal, top_k=3)
        kb_results = kb["data"]["results"] if kb["status"] == "ok" else []
        if not kb_results:
            return core._ok(
                {
                    "goal": goal,
                    "recommended_chain": "No direct workflow found in Knowledge Base.",
                    "tip": "Use research() to build a custom plan from first principles (Geometry → Deformation → Simulation → Export).",
                }
            )
        return core._ok(
            {
                "goal": goal,
                "knowledge_base_hits": [
                    {"title": r["title"], "content": r["content"]} for r in kb_results
                ],
                "tip": "Deduce the workflow from these examples. Focus on procedural nodes like 'Copy to Points' and 'Attribute Wrangle' for maximum control.",
            }
        )
    except Exception as e:
        return core._err(str(e))


def get_error_fix(error_message: str) -> dict:
    """Look up known fixes for an error message in the knowledge base."""
    kb = search_knowledge(error_message, top_k=3, category_filter="errors")
    fixes = kb["data"]["results"] if kb["status"] == "ok" else []
    broad = search_knowledge(error_message, top_k=2)
    broad_hits = [
        r
        for r in (broad["data"]["results"] if broad["status"] == "ok" else [])
        if r not in fixes
    ]
    return core._ok(
        {
            "error": error_message[:200],
            "known_fixes": fixes,
            "related": broad_hits,
            "action": fixes[0]["content"]
            if fixes
            else "No exact fix found — call deep_error_trace() to trace root cause",
        }
    )
