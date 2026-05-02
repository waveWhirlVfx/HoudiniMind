# Metadata-Aware Retrieval Guide

Your knowledge base is now enhanced with metadata that enables smarter retrieval and ranking. This guide shows how to leverage these capabilities.

## What's New

The retriever now understands:
- **Difficulty levels**: beginner, intermediate, advanced, reference
- **Performance impact**: low, medium, high
- **Error severity**: critical, high, medium
- **Use cases**: What each entry is best for
- **Context**: Domain information (VEX, Python HOM, SOP, DOP, etc.)
- **Source**: Where content originated

## Basic Usage

### Filter by Difficulty

Return only beginner-friendly content:

```python
results = retriever.retrieve(
    query="vex random color",
    difficulty_filter="beginner"
)
```

Available levels:
- `"beginner"` — Simple, easy-to-understand examples
- `"intermediate"` — More complex, assumes some knowledge
- `"advanced"` — Expert-level techniques
- `"reference"` — API/node documentation

### Filter by Performance Impact

Useful when you want efficient solutions:

```python
results = retriever.retrieve(
    query="smooth geometry",
    max_performance_impact="low"  # Only low-impact solutions
)
```

Valid values: `"low"`, `"medium"`, `"high"`

### Prioritize Performant Solutions

Automatically boost solutions with low performance impact:

```python
results = retriever.retrieve(
    query="my simulation is running slow",
    prefer_performant=True
)
```

## Smart Inference (Automatic)

The retriever detects user intent from natural language:

### Beginner Intent
Queries mentioning "beginner", "simple", "tutorial", "basic", "how do I", or "how to" automatically:
- Prefer beginner-difficulty entries
- Boost simple, straightforward solutions
- Deprioritize advanced techniques

```python
# No difficulty_filter needed — automatically inferred
results = retriever.retrieve("beginner vex tutorial")
```

### Performance Concerns
Queries with "slow", "fast", "optimize", "performance", "speed", or "lag" automatically:
- Boost entries with low/medium performance impact
- Deprioritize expensive operations
- Surface optimization tips

```python
# Automatically prioritizes performant solutions
results = retriever.retrieve("why is my cloth simulation so slow")
```

### Error/Troubleshooting
Queries about "crash", "fatal", "broken", "critical" automatically:
- Prioritize critical/high-severity solutions
- Deprioritize low-severity issues

```python
# Automatically detects troubleshooting intent
results = retriever.retrieve("houdini crashes when i render")
```

## Real-World Examples

### Example 1: User is Learning Houdini

```python
# Query: "How do I create a simple random color in VEX?"
results = retriever.retrieve(
    query="create simple random color vex",
    difficulty_filter="beginner"
)

# Returns:
# 1. VEX: Clamped Random Color (beginner)
# 2. VEX: Simple Random Pscale (beginner)
# 3. VEX: Color Blending Technique (beginner)
```

### Example 2: Optimization Problem

```python
# Query: "My FLIP simulation is taking forever to cook"
results = retriever.retrieve(
    query="flip simulation slow fast optimize",
    prefer_performant=True
)

# Automatically boosted:
# 1. Solutions with performance_impact="low"
# 2. Caching strategies
# 3. Optimization techniques
#
# Deprioritized:
# - Expensive algorithms
# - Detailed simulation setups
```

### Example 3: Error Recovery

```python
# Query: "Division by zero VEX error"
results = retriever.retrieve(
    query="division by zero vex error",
    # Automatically infers troubleshooting intent
)

# Returns:
# 1. VEX: Division by zero fix (severity=high)
# 2. Safe division pattern example
# 3. Related error handling techniques
```

### Example 4: API Reference

```python
# Query: "How to get geometry in Python HOM"
results = retriever.retrieve(
    query="python geometry hom api",
    difficulty_filter="reference"  # API docs
)

# Returns node/function reference entries with full parameter lists
```

## Available Metadata Fields

Each knowledge entry now contains:

```json
{
  "title": "VEX: Simple Random Pscale",
  "category": "vex",
  "content": "...",
  
  // New metadata:
  "_source": "Built-in VEX examples",
  "_source_path": "vex_examples",
  "difficulty": "beginner",
  "use_case": "general geometry",
  "context": "point wrangle / CVEX",
  "performance_impact": "low",
  "tags": ["pscale", "random", "rand"]
}
```

## Agent Integration

For Claude agents using this retriever:

### Check Entry Metadata

```python
for result in results:
    difficulty = result.get("difficulty", "unknown")
    impact = result.get("performance_impact", "unknown")
    source = result.get("_source", "unknown")
    
    if difficulty == "advanced" and impact == "high":
        print(f"⚠️ Warning: Advanced + expensive solution")
```

### Route by Difficulty

```python
easy_results = [r for r in results if r.get("difficulty") == "beginner"]
if not easy_results:
    print("No beginner solutions found. Trying intermediate...")
    results = retriever.retrieve(query, difficulty_filter="intermediate")
```

### Performance-Aware Suggestions

```python
if "slow" in query.lower():
    results = retriever.retrieve(query, prefer_performant=True)
    best = results[0] if results else None
    if best and best.get("performance_impact") == "low":
        print(f"✓ Found fast solution: {best['title']}")
```

## Backward Compatibility

All metadata features are **optional**. Existing code continues to work:

```python
# This still works (no metadata filtering)
results = retriever.retrieve(query="vex random color")

# Metadata filtering is opt-in
results = retriever.retrieve(
    query="vex random color",
    difficulty_filter="beginner"  # Optional
)
```

## Troubleshooting

### No results with strict filtering

```python
# If filtered results are empty, fall back:
results = retriever.retrieve(
    query=query,
    difficulty_filter="beginner"
)

if not results:
    print("No beginner results found, trying all levels...")
    results = retriever.retrieve(query)
```

### Understanding scores

Scores now include:
- BM25 keyword matching
- Semantic similarity (if embeddings available)
- Intent-based boosting
- **Metadata alignment boost** (new)
- Exact match bonuses

Higher scores = better overall match considering all factors.

## Future Enhancements

Potential additions:
- Learn user preferences over time
- Custom difficulty ratings per user skill level
- Performance benchmarking per solution
- Cross-reference related entries
- Community ratings / quality scoring
