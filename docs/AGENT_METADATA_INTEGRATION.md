# Agent Integration: Metadata-Aware Knowledge Retrieval

This guide shows how your Claude agent can use metadata to provide better answers.

## Quick Reference

### 1. Detect User Skill Level

```python
def infer_user_skill(query: str) -> str:
    """Infer whether user is beginner/intermediate/advanced."""
    query_lower = query.lower()
    
    if any(x in query_lower for x in ["how do i", "beginner", "simple", "tutorial"]):
        return "beginner"
    elif any(x in query_lower for x in ["advanced", "optimize", "complex"]):
        return "advanced"
    return "intermediate"

# Usage
skill = infer_user_skill("how do i create a simple VEX wrangle")
results = retriever.retrieve(query, difficulty_filter=skill)
```

### 2. Detect Performance Concerns

```python
def has_performance_concern(query: str) -> bool:
    """Check if query mentions performance issues."""
    perf_keywords = ["slow", "lag", "fast", "optimize", "speed", "performance", "cpu"]
    return any(x in query.lower() for x in perf_keywords)

# Usage
if has_performance_concern(query):
    results = retriever.retrieve(query, prefer_performant=True)
```

### 3. Route to Best Result

```python
def get_best_result_for_context(query: str, results: list) -> dict:
    """Select the best result based on context."""
    if not results:
        return None
    
    # For troubleshooting, prefer critical/high severity
    if "error" in query.lower():
        critical = [r for r in results if r.get("severity") == "critical"]
        if critical:
            return critical[0]
    
    # For performance queries, prefer low-impact solutions
    if has_performance_concern(query):
        low_impact = [r for r in results if r.get("performance_impact") == "low"]
        if low_impact:
            return low_impact[0]
    
    # Default: return highest-scored result
    return results[0]
```

## Full Decision Tree

```
User query arrives
├── Is it a performance issue?
│   └─→ prefer_performant=True
│       └─→ Boost entries with low/medium impact
│
├── Is user a beginner?
│   └─→ difficulty_filter="beginner"
│       └─→ Return only beginner-friendly entries
│
├── Is this a troubleshooting question?
│   └─→ Filter by severity
│       └─→ Priority: critical > high > medium
│
├── Is this a recipe/workflow request?
│   └─→ Look for entries with use_case="procedural asset building"
│       └─→ Prioritize estimated_time_minutes
│
└─→ Default: Return top-scored results across all metadata
```

## Agent Prompt Integration

Add this to your agent system prompt:

```
When retrieving knowledge:
1. Always check the user's apparent skill level from their question
2. Use difficulty_filter="beginner" if they ask "how do I" or use beginner language
3. Use prefer_performant=True if they mention speed/performance/lag/optimization
4. For troubleshooting (crashes, errors), look for severity="critical" or "high"
5. Prefer entries from official sources (_source contains "Built-in" or "Houdini Official")
6. Check performance_impact before suggesting slow solutions

When explaining results:
- Mention difficulty level: "Here's a beginner-friendly approach..."
- Note performance impact: "This solution is low-impact and fast"
- Show the source: "This is from the official Houdini reference"
- Suggest alternatives: "If you're advanced, you could also try..."
```

## Code Examples

### Example 1: Smart Wrangle Suggestion

```python
def suggest_vex_wrangle(task: str) -> dict:
    """Suggest a VEX solution tailored to user context."""
    
    # Infer skill level
    skill = infer_user_skill(task)
    
    # Retrieve with difficulty filter
    results = retriever.retrieve(
        query=task,
        difficulty_filter=skill,
        category_filter="vex"
    )
    
    if not results:
        # Fall back to any VEX solutions
        results = retriever.retrieve(
            query=task,
            category_filter="vex"
        )
    
    best = results[0] if results else None
    
    return {
        "solution": best,
        "difficulty": best.get("difficulty") if best else None,
        "context": best.get("context") if best else None,
        "performance": best.get("performance_impact") if best else None
    }
```

### Example 2: Troubleshooting Helper

```python
def troubleshoot_error(error_msg: str) -> dict:
    """Find solutions for an error."""
    
    results = retriever.retrieve(
        query=error_msg,
        category_filter="errors"
    )
    
    # Sort by severity
    severity_order = {"critical": 0, "high": 1, "medium": 2}
    results.sort(
        key=lambda r: severity_order.get(r.get("severity"), 999)
    )
    
    return {
        "solutions": results[:3],
        "best_match": results[0] if results else None
    }
```

### Example 3: Performance Optimization

```python
def optimize_slow_simulation(sim_type: str, current_time: float) -> dict:
    """Find optimization strategies."""
    
    results = retriever.retrieve(
        query=f"{sim_type} slow optimization",
        prefer_performant=True,
        max_performance_impact="low"  # Only fast solutions
    )
    
    return {
        "strategies": [
            {
                "title": r["title"],
                "impact": r.get("performance_impact"),
                "difficulty": r.get("difficulty"),
                "source": r.get("_source")
            }
            for r in results
        ]
    }
```

## Metadata Decision Factors

| Factor | When to Use | Impact |
|--------|------------|--------|
| `difficulty_filter` | Known user skill level | High - eliminates irrelevant complexity |
| `prefer_performant` | "slow/lag/optimize" in query | High - prioritizes fast solutions |
| `max_performance_impact` | Performance-critical context | High - hard filter |
| (auto-inferred) | User says "beginner" or "advanced" | Medium - soft boost |
| Source validation | Technical/production context | Medium - credibility ranking |

## Testing Your Integration

```python
# Test 1: Beginner query
results = retriever.retrieve(
    "how do I randomize particle size",
    difficulty_filter="beginner"
)
assert all(r.get("difficulty") == "beginner" for r in results)

# Test 2: Performance query
results = retriever.retrieve(
    "flip simulation too slow",
    prefer_performant=True
)
assert results[0].get("performance_impact") in ("low", "medium")

# Test 3: Fallback behavior
results = retriever.retrieve(
    "obscure vex function xyz",
    difficulty_filter="beginner"
)
# Should gracefully return results or empty list
assert isinstance(results, list)
```

## Common Patterns

### Pattern 1: Graceful Degradation

```python
def retrieve_with_fallback(query, prefer_difficulty=None):
    """Try strict filter first, fall back to any results."""
    
    if prefer_difficulty:
        results = retriever.retrieve(
            query,
            difficulty_filter=prefer_difficulty
        )
        if results:
            return results
    
    # Fallback to all results
    return retriever.retrieve(query)
```

### Pattern 2: Multi-Step Explanation

```python
def explain_with_metadata(query: str):
    """Explain solution with metadata context."""
    
    skill = infer_user_skill(query)
    results = retriever.retrieve(query, difficulty_filter=skill)
    
    if not results:
        return "No solutions found."
    
    best = results[0]
    response = f"Here's a {best.get('difficulty', 'mixed-level')} solution:\n\n"
    response += best.get("content", "")
    
    # Add metadata context
    if best.get("performance_impact") == "high":
        response += "\n⚠️ Note: This solution is computationally intensive."
    
    if best.get("context"):
        response += f"\n💡 Context: {best.get('context')}"
    
    return response
```

### Pattern 3: Alternative Suggestions

```python
def explain_with_alternatives(query: str):
    """Provide main solution + alternatives."""
    
    skill = infer_user_skill(query)
    results = retriever.retrieve(query, difficulty_filter=skill, top_k=5)
    
    main = results[0] if results else None
    alternatives = results[1:3] if len(results) > 1 else []
    
    response = f"**Main Solution**\n{main['content']}\n"
    
    if alternatives:
        response += "\n**Alternatives**\n"
        for alt in alternatives:
            diff = alt.get("difficulty", "?")
            perf = alt.get("performance_impact", "?")
            response += f"- {alt['title']} [{diff}, {perf} impact]\n"
    
    return response
```

## Monitoring & Debugging

Enable logging to understand retriever decisions:

```python
def retrieve_with_logging(query: str, **filters):
    """Retrieve with detailed logging."""
    
    print(f"[RETRIEVE] Query: {query}")
    print(f"[FILTERS] {filters}")
    
    prefs = retriever._infer_metadata_preferences(query, query.split())
    print(f"[INFERRED] {prefs}")
    
    results = retriever.retrieve(query, **filters)
    
    for i, result in enumerate(results, 1):
        print(f"  [{i}] {result['title']}")
        print(f"      Score: {result['_score']}")
        print(f"      Difficulty: {result.get('difficulty')}")
        print(f"      Source: {result.get('_source')}")
    
    return results
```
