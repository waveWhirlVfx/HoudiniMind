# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
"""
HoudiniMind — SOP Knowledge Importer v2
=========================================
Converts the 5 rich data files into KB entries, removes any previously
imported SOP stubs/entries, and saves the updated knowledge_base.json.

Usage:
    python tools/import_sop_knowledge.py

The RAG vector index auto-invalidates on next HoudiniMind launch because
the KB file's mtime will be newer than the .vectors.json sidecar.
"""

import json
import os
import time

# ── Paths ──────────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT       = os.path.dirname(SCRIPT_DIR)
KB_PATH    = os.path.join(ROOT, "data", "knowledge", "knowledge_base.json")
SRC_DIR    = os.path.join(ROOT, "data", "knowledge")

SRC_FILES = {
    "node_docs":       os.path.join(SRC_DIR, "sop_node_docs.json"),
    "recipes":         os.path.join(SRC_DIR, "sop_recipes.json"),
    "workflows":       os.path.join(SRC_DIR, "sop_workflows.json"),
    "decision_guides": os.path.join(SRC_DIR, "sop_decision_guides.json"),
    "errors":          os.path.join(SRC_DIR, "sop_errors.json"),
}

# Sources we own — anything with these is ours to remove and replace
OWN_SOURCES = {
    "sop_node_docs_import",
    "sop_recipes_import",
    "sop_workflows_import",
    "sop_decision_guides_import",
    "sop_errors_import",
}

# ── Expert use-cases / workflow context for nodes not covered by the data files ─
# Keyed by node type string. Injected when the source file has no use_cases.
NODE_EXPERT_FALLBACK = {
    "boolean": {
        "use_cases": [
            "Subtract a cutter shape from solid geometry (doorway, window hole, bolt pocket)",
            "Union two overlapping meshes into one seamless solid",
            "Intersect two shapes to keep only their shared volume",
        ],
        "workflow_context": "Always place Fuse then Clean after Boolean to weld seam points and remove degenerate faces. Both inputs must be watertight (no open edges). If inputs are messy, use VDB Boolean instead.",
    },
    "detail": {
        "use_cases": [
            "Read or write detail-level attributes (one value for the whole geometry)",
            "Store metadata: frame number, object name, bounding box size",
            "Pass global parameters between nodes via detail attributes",
        ],
        "workflow_context": "Used in Attribute Wrangle with detail() / setdetailattrib() functions, or as standalone Detail SOP for simple value storage.",
    },
    "groupbbox": {
        "use_cases": [
            "Select faces inside a spatial region for PolyExtrude (e.g. window cutout on a wall)",
            "Tag the top, bottom, or side of an object by world-space bounding box",
            "Region-based material assignment without manual point selection",
        ],
        "workflow_context": "Place immediately after geometry source. Output feeds PolyExtrude, Blast, Material, or Delete. Bounding box uses centroid containment — partially inside faces are NOT included.",
    },
    "groupbyrange": {
        "use_cases": [
            "Select every Nth point or primitive (e.g. every 3rd for thinning)",
            "Create alternating groups for checkerboard material patterns",
            "Isolate a sequential range of primitives by index",
        ],
        "workflow_context": "Useful after Scatter or Copy to Points to thin out instanced geometry. Set 'Select' to 'Every Nth' and adjust the range step.",
    },
    "foreach_begin": {
        "use_cases": [
            "Process each connected piece of geometry independently (fracture pieces, separate islands)",
            "Apply per-piece transforms, attributes, or operations that depend on piece count",
            "Build iterative procedural growth or stack operations N times",
        ],
        "workflow_context": "Always paired with foreach_end. Set Method to 'Pieces' for per-piece iteration or 'Count' for a fixed number of iterations. The Feedback Each Iteration toggle passes result of each loop back as input for the next.",
    },
    "foreach_end": {
        "use_cases": [
            "Close and execute a For-Each loop block",
            "Collect all per-piece results back into a single merged geometry stream",
        ],
        "workflow_context": "Must be connected to its matching foreach_begin. Middle-click to see iteration count. Enable 'Feedback Each Iteration' on foreach_begin if each loop should modify the previous loop's result (e.g. recursive growth).",
    },
    "points_from_volume": {
        "use_cases": [
            "Fill the interior of a VDB/fog volume with evenly distributed points",
            "Generate volumetric point clouds for pyro emission or particle seeding",
            "Scatter points inside a closed mesh (convert to VDB first)",
        ],
        "workflow_context": "Input must be a VDB volume (fog or SDF). Precede with vdbfrompolygons if your source is a polygon mesh. Output feeds CopyToPoints, Pyro Source, or POP Replicate.",
    },
    "popcreate": {
        "use_cases": [
            "Create a particle system inside a DOP network",
            "Seed particles from a SOP geometry source for POP simulations",
        ],
        "workflow_context": "Lives inside a DOP network. Connect to a POP Solver. Set 'Source' to a SOP path to emit particles from geometry.",
    },
    "loft": {
        "use_cases": [
            "Build a smooth surface interpolated through a series of profile curves",
            "Create hull shapes (boat hulls, car bodies) from cross-section curves",
            "Organic surface skinning between differently-shaped curve profiles",
        ],
        "workflow_context": "Each input curve becomes one cross-section. Order matters — curves are connected sequentially. Resample all input curves to equal point counts for clean topology. Alternative: Skin SOP for more control over U/V direction.",
    },
}


# ── Format helpers ─────────────────────────────────────────────────────────────

def _fmt_default(val) -> str:
    """Format a parameter default value for display."""
    if val is None:
        return "—"
    if isinstance(val, bool):
        return "on" if val else "off"
    if isinstance(val, list):
        if len(val) == 1:
            return str(val[0])
        return f"({', '.join(str(v) for v in val)})"
    return str(val)


def _tags_from_text(*texts: str, extra: list = None) -> list:
    """Extract meaningful tags from text blobs."""
    COMMON_NODES = [
        "box", "sphere", "grid", "tube", "torus", "line", "circle", "merge",
        "xform", "transform", "scatter", "delete", "blast", "boolean", "fuse",
        "divide", "polyextrude", "polybevel", "subdivide", "remesh", "attribwrangle",
        "copytopoints", "vdbfrompolygons", "convertvdb", "mountain", "peak",
        "resample", "sweep", "polywire", "mirror", "clean", "normal", "switch",
        "add", "pack", "unpack", "null", "output", "groupcreate", "groupbbox",
        "smooth", "copy", "instance", "attribcreate", "attribtransfer",
    ]
    DOMAIN_TAGS = {
        "terrain": ["terrain", "height", "landscape", "ground"],
        "furniture": ["chair", "table", "shelf", "lamp", "desk", "sofa"],
        "modeling": ["model", "hard-surface", "polygon", "mesh"],
        "instancing": ["instance", "scatter", "copytopoints", "copy to points"],
        "vex": ["vex", "wrangle", "snippet", "@ptnum", "@P", "attribwrangle"],
        "boolean": ["boolean", "subtract", "intersect", "union", "csg"],
        "curve": ["curve", "spline", "sweep", "resample", "polywire"],
        "vdb": ["vdb", "volume", "sdf", "vdbfrompolygons", "convertvdb"],
        "simulation": ["sim", "flip", "pyro", "rbd", "vellum", "dop"],
        "uv": ["uv", "uvunwrap", "uvlayout", "texture coord"],
        "debug": ["error", "fix", "broken", "symptom", "cause", "solution"],
    }
    combined = " ".join(str(t).lower() for t in texts)
    tags = []
    for node in COMMON_NODES:
        if node in combined:
            tags.append(node)
    for tag, keywords in DOMAIN_TAGS.items():
        if any(kw in combined for kw in keywords):
            tags.append(tag)
    if extra:
        tags.extend(extra)
    return list(dict.fromkeys(tags))[:16]  # deduplicate, cap at 16


# ── Converter: SOP Node Docs ───────────────────────────────────────────────────

def convert_node_doc(item: dict) -> dict:
    """
    Input keys: node, type, description, inputs, parameters, use_cases, workflow_context
    parameters items: {name, label, type, default}
    inputs items: {index, description}
    """
    node_name       = item.get("node", "").strip()
    description     = item.get("description", "").strip()
    inputs          = item.get("inputs") or []
    params          = item.get("parameters") or []
    use_cases       = item.get("use_cases") or []
    workflow_ctx    = item.get("workflow_context", "").strip()

    # Inject expert fallback for nodes the data file left blank
    if (not use_cases or not workflow_ctx) and node_name in NODE_EXPERT_FALLBACK:
        fb = NODE_EXPERT_FALLBACK[node_name]
        if not use_cases:
            use_cases = fb.get("use_cases", [])
        if not workflow_ctx:
            workflow_ctx = fb.get("workflow_context", "")

    lines = [
        f"Node Type: {node_name}",
        "Network Context: SOP",
        f"UI Name: {description}",
        "",
    ]

    # Inputs
    if inputs:
        lines.append("INPUTS:")
        for inp in inputs:
            idx  = inp.get("index", "?")
            desc = inp.get("description", "")
            lines.append(f"  Input {idx}: {desc}")
        lines.append("")
    else:
        lines += ["INPUTS:", "  None — generator node.", ""]

    # Parameters — grouped by type for readability
    if params:
        lines.append("PARAMETERS:")
        # Column widths
        max_label = max((len(p.get("label", "")) for p in params), default=20)
        max_name  = max((len(p.get("name", ""))  for p in params), default=12)
        col_label = min(max_label, 36)
        col_name  = min(max_name, 22)
        header = f"  {'Label':<{col_label}}  {'Parm Name':<{col_name}}  Type       Default"
        lines.append(header)
        lines.append("  " + "-" * (col_label + col_name + 28))
        for p in params:
            label   = p.get("label", "")[:col_label]
            name    = p.get("name", "")[:col_name]
            ptype   = p.get("type", "")
            default = _fmt_default(p.get("default"))
            lines.append(f"  {label:<{col_label}}  {name:<{col_name}}  {ptype:<10} {default}")
        lines.append("")

    # Use cases
    if use_cases:
        lines.append("USE CASES:")
        for i, uc in enumerate(use_cases, 1):
            lines.append(f"  {i}. {uc}")
        lines.append("")

    # Workflow context
    if workflow_ctx:
        lines += ["WORKFLOW CONTEXT:", f"  {workflow_ctx}", ""]

    content = "\n".join(lines)
    tags = ["sop", "node", node_name] + _tags_from_text(
        description, workflow_ctx, " ".join(use_cases),
        extra=[p.get("name", "") for p in params[:6]],
    )

    return {
        "title":    f"SOP Node: {node_name}",
        "category": "nodes",
        "tags":     tags,
        "content":  content,
        "_source":  "sop_node_docs_import",
    }


# ── Converter: Recipes ────────────────────────────────────────────────────────

def convert_recipe(item: dict) -> dict:
    """
    Input keys: asset, description, nodes, node_settings, expected_outcome
    node_settings items: {node, action}
    """
    asset           = item.get("asset", "Unknown Asset")
    description     = item.get("description", "")
    nodes           = item.get("nodes") or []
    node_settings   = item.get("node_settings") or []
    expected_outcome = item.get("expected_outcome", "")

    lines = [
        f"Recipe: Build '{asset}' — Procedural SOP Network",
        "",
        "DESCRIPTION:",
        f"  {description}",
        "",
    ]

    if nodes:
        lines += [
            "NODE CHAIN (in order):",
            "  " + " → ".join(nodes),
            "",
            "REQUIRED SOP NODES (internal type strings):",
        ]
        for n in nodes:
            lines.append(f"  - {n}")
        lines.append("")

    if node_settings:
        lines.append("STEP-BY-STEP NODE SETTINGS:")
        for i, step in enumerate(node_settings, 1):
            node_label = step.get("node", "")
            action     = step.get("action", "")
            lines.append(f"  {i}. [{node_label}]")
            lines.append(f"     {action}")
        lines.append("")

    if expected_outcome:
        lines += [
            "EXPECTED OUTCOME:",
            f"  {expected_outcome}",
            "",
        ]

    lines += [
        "GENERAL RULES FOR ALL PROCEDURAL ASSETS:",
        "  - tx/ty/tz (Center) parameters are the CENTER of the object, not a corner.",
        "  - sizex/sizey/sizez are FULL dimensions (not half-extents).",
        "  - Use copytopoints + add SOP for repeated parts (legs, rungs, bolts).",
        "  - Set copytopoints 'dorot=0' for furniture to prevent unwanted rotation.",
        "  - Final node must be: merge → output1.",
    ]

    content = "\n".join(lines)
    asset_tag = asset.lower().replace(" ", "_").replace("/", "_").replace("'", "")
    tags = ["recipe", "procedural", "modeling", asset_tag] + _tags_from_text(
        description, expected_outcome, " ".join(nodes),
    )

    return {
        "title":    f"Recipe: {asset}",
        "category": "recipe",
        "tags":     tags,
        "content":  content,
        "_source":  "sop_recipes_import",
    }


# ── Converter: Workflows ──────────────────────────────────────────────────────

def convert_workflow(item: dict) -> dict:
    """
    Input keys: workflow, description, prerequisites, context, steps, tips
    """
    title         = item.get("workflow", "Unknown Workflow")
    description   = item.get("description", "")
    prerequisites = item.get("prerequisites") or []
    context       = item.get("context", "")
    steps         = item.get("steps") or []
    tips          = item.get("tips") or []

    lines = [
        f"Workflow: {title}",
        "",
        f"GOAL: {description}",
        "",
    ]

    if prerequisites:
        lines.append("PREREQUISITES:")
        for p in prerequisites:
            lines.append(f"  - {p}")
        lines.append("")

    if context:
        lines += ["CONTEXT:", f"  {context}", ""]

    if steps:
        lines.append("STEPS:")
        for step in steps:
            lines.append(f"  {step}")
        lines.append("")

    if tips:
        lines.append("TD TIPS:")
        for tip in tips:
            lines.append(f"  • {tip}")
        lines.append("")

    lines += [
        "DATA FLOW RULE:",
        "  SOP networks are sequential — each node receives the output of the node above it.",
        "  Node order directly determines the result. Wrong order = wrong result.",
    ]

    content = "\n".join(lines)
    tags = ["workflow", "sop"] + _tags_from_text(
        title, description, context, " ".join(steps), " ".join(tips),
    )

    return {
        "title":    f"Workflow: {title}",
        "category": "workflow",
        "tags":     tags,
        "content":  content,
        "_source":  "sop_workflows_import",
    }


# ── Converter: Decision Guides ────────────────────────────────────────────────

def convert_decision_guide(item: dict) -> dict:
    """
    Input keys: topic, scenario, comparison (dict of {option: description}), recommendation
    """
    topic          = item.get("topic", "")
    scenario       = item.get("scenario", "")
    comparison     = item.get("comparison") or {}
    recommendation = item.get("recommendation", "")

    lines = [
        f"DECISION GUIDE: {topic}",
        "",
    ]

    if scenario:
        lines += ["SCENARIO:", f"  {scenario}", ""]

    if comparison:
        lines.append("COMPARISON:")
        for option, detail in comparison.items():
            lines.append(f"\n  ▶ {option}")
            # Wrap long detail text
            for sentence in detail.replace(". Pros:", ".\n  Pros:").replace(". Cons:", ".\n  Cons:").split("\n"):
                lines.append(f"    {sentence.strip()}")
        lines.append("")

    if recommendation:
        lines += [
            "RECOMMENDATION:",
            f"  {recommendation}",
            "",
        ]

    lines += [
        "WHEN TO APPLY THIS GUIDE:",
        "  Use this decision when the task could be solved by multiple approaches.",
        "  Choose based on: input geometry quality, required output precision, performance needs.",
    ]

    content = "\n".join(lines)
    # Tags: all option names + topic words
    option_tags = [k.lower().replace(" ", "_").split("(")[0].strip() for k in comparison.keys()]
    tags = ["decision", "best_practice", "sop"] + option_tags + _tags_from_text(
        topic, scenario, recommendation,
    )

    return {
        "title":    f"Decision Guide: {topic}",
        "category": "best_practice",
        "tags":     list(dict.fromkeys(tags))[:16],
        "content":  content,
        "_source":  "sop_decision_guides_import",
    }


# ── Converter: Errors ─────────────────────────────────────────────────────────

def convert_error(item: dict) -> dict:
    """
    Input keys: error, symptoms, cause, detailed_solution, prevention
    symptoms is a list of strings.
    """
    error            = item.get("error", "Unknown Error")
    symptoms         = item.get("symptoms") or []
    cause            = item.get("cause", "")
    detailed_solution = item.get("detailed_solution", "")
    prevention       = item.get("prevention", "")

    lines = [f"ERROR: {error}", ""]

    if symptoms:
        lines.append("SYMPTOMS:")
        for s in symptoms:
            lines.append(f"  - {s}")
        lines.append("")

    if cause:
        lines += ["CAUSE:", f"  {cause}", ""]

    if detailed_solution:
        lines += ["DETAILED SOLUTION:", f"  {detailed_solution}", ""]

    if prevention:
        lines += ["PREVENTION:", f"  {prevention}", ""]

    lines += [
        "GENERAL DIAGNOSIS STEPS:",
        "  1. Middle-click the failing node → check geometry info (point/prim counts).",
        "  2. Look for the red/yellow error band at the bottom of the node tile.",
        "  3. Verify all input connections are wired and data is flowing.",
        "  4. Check that Group names exist and match the Group Type (Points vs Primitives).",
    ]

    content = "\n".join(lines)
    tags = ["error", "debug", "sop"] + _tags_from_text(
        error, cause, detailed_solution, prevention, " ".join(symptoms),
    )

    return {
        "title":    f"SOP Error: {error}",
        "category": "errors",
        "tags":     tags,
        "content":  content,
        "_source":  "sop_errors_import",
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def run_import():
    print(f"\n{'='*62}")
    print("  HoudiniMind SOP Knowledge Importer v2")
    print(f"{'='*62}\n")

    # 1. Load existing KB
    print(f"[1/6] Loading KB: {KB_PATH}")
    with open(KB_PATH, encoding="utf-8") as f:
        kb = json.load(f)
    if isinstance(kb, dict):
        kb = kb.get("entries", [])
    print(f"      {len(kb)} existing entries.")

    # 2. Strip previously imported entries AND empty SOP stubs
    before = len(kb)
    kb = [
        e for e in kb
        if e.get("_source") not in OWN_SOURCES
        and not (
            e.get("title", "").startswith("SOP Node:")
            and (
                "Scrape failed" in e.get("content", "")
                or len(e.get("content", "")) < 150
            )
        )
    ]
    removed = before - len(kb)
    print(f"[2/6] Stripped {removed} old/empty entries.")

    # 3–5. Convert all source files
    converters = [
        ("node_docs",       convert_node_doc,       "node docs"),
        ("recipes",         convert_recipe,         "recipes"),
        ("workflows",       convert_workflow,       "workflows"),
        ("decision_guides", convert_decision_guide, "decision guides"),
        ("errors",          convert_error,          "error entries"),
    ]

    new_entries = []
    print("[3/6] Converting source files:")
    for key, fn, label in converters:
        path = SRC_FILES[key]
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        converted = [fn(item) for item in data]
        new_entries.extend(converted)
        print(f"      {label:<20} {len(converted):>4} entries  ← {os.path.basename(path)}")

    # 6. Assign IDs + timestamps
    print("[4/6] Assigning IDs and timestamps...")
    max_id = max((e.get("_id", 0) for e in kb), default=0)
    ts = time.time()
    for i, entry in enumerate(new_entries):
        entry["_id"]    = max_id + i + 1
        entry["_added"] = ts

    # 7. Merge and write
    print("[5/6] Merging...")
    kb.extend(new_entries)

    print(f"[6/6] Writing KB ({len(kb)} entries)...")
    with open(KB_PATH, "w", encoding="utf-8") as f:
        json.dump(kb, f, indent=2, ensure_ascii=False)

    # Summary
    cats = {}
    for e in kb:
        c = e.get("category", "unknown")
        cats[c] = cats.get(c, 0) + 1

    print(f"\n{'='*62}")
    print(f"  DONE — {len(kb)} total entries")
    print(f"  Added {len(new_entries)} | Removed {removed} | Net {len(new_entries)-removed:+d}")
    print("\n  Category breakdown:")
    for cat, count in sorted(cats.items(), key=lambda x: -x[1]):
        flag = " ◀ updated" if cat in ("nodes", "recipe", "best_practice", "errors", "workflow") else ""
        print(f"    {cat:<22} {count:>5}{flag}")
    print("\n  Vector index will auto-rebuild on next HoudiniMind launch.")
    print(f"{'='*62}\n")


if __name__ == "__main__":
    run_import()
