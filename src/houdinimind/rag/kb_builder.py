# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
"""
HoudiniMind — Knowledge Base Builder v2
Converts houdini_knowledge.py entries + session feedback into
the JSON file that HybridRetriever loads at startup.

Run this script to rebuild the KB:
  python kb_builder.py

Or call build_kb() from install.py.
"""

import glob
import json
import os
import re
import sys
import time

# ══════════════════════════════════════════════════════════════════════
#  Paths
# ══════════════════════════════════════════════════════════════════════

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(HERE))))  # HoudiniMind root
DATA_DIR = os.path.join(ROOT, "data")
KB_PATH = os.path.join(DATA_DIR, "knowledge", "knowledge_base.json")
KB_GENERATED_PATH = os.path.join(DATA_DIR, "knowledge", "knowledge_base.generated.json")
GEMMA_JSONL_DEFAULT_PATHS = (
    os.path.join(os.path.dirname(ROOT), "gemma4_houdini_dataset.jsonl"),
    os.path.join(os.path.expanduser("~"), "gemma4_houdini_dataset.jsonl"),
    os.path.join(os.path.expanduser("~"), "Downloads", "houdini_finetune.jsonl"),
    os.path.join(os.path.expanduser("~"), "houdini_finetune.jsonl"),
    os.path.join(os.path.dirname(ROOT), "houdini_finetune.jsonl"),
)


# ══════════════════════════════════════════════════════════════════════
#  Load built-in knowledge
# ══════════════════════════════════════════════════════════════════════


def _load_builtin() -> list:
    """Import houdini_knowledge.py and return all entries."""
    knowledge_dir = os.path.join(DATA_DIR, "knowledge")
    if knowledge_dir not in sys.path:
        sys.path.insert(0, knowledge_dir)
    try:
        import houdini_knowledge as hk

        entries = hk.get_all_entries()
        print(f"[KB Builder] Loaded {len(entries)} built-in knowledge entries")
        return entries
    except Exception as e:
        print(f"[KB Builder] Failed to load built-in knowledge: {e}")
        return []


def _node_chain_source_candidates() -> list:
    candidates = []

    env_value = os.environ.get("HOUDINIMIND_NODE_CHAINS_PATH", "").strip()
    if env_value:
        for part in env_value.split(os.pathsep):
            part = part.strip()
            if part:
                candidates.append(part)

    knowledge_dir = os.path.join(DATA_DIR, "knowledge")
    if os.path.exists(knowledge_dir):
        import glob

        for p in glob.glob(os.path.join(knowledge_dir, "*node_chains.json")):
            candidates.append(p)

    candidates.extend(
        [
            os.path.join(ROOT, "houdini_node_chains.json"),
            os.path.join(os.path.dirname(ROOT), "houdini_node_chains.json"),
            os.path.join(os.path.dirname(os.path.dirname(ROOT)), "houdini_node_chains.json"),
        ]
    )

    seen = set()
    unique = []
    for path in candidates:
        norm = os.path.normcase(os.path.abspath(path))
        if norm in seen:
            continue
        seen.add(norm)
        unique.append(path)
    return unique


def _format_chain_parms(parms: dict) -> str:
    if not isinstance(parms, dict) or not parms:
        return "none"
    parts = []
    for key, value in parms.items():
        try:
            rendered = json.dumps(value, ensure_ascii=False)
        except Exception:
            rendered = str(value)
        parts.append(f"{key}={rendered}")
    return ", ".join(parts)


def _chain_to_entry(chain: dict, source_path: str) -> dict:
    chain_id = str(chain.get("id") or "").strip()
    title = str(chain.get("title") or chain_id or "Untitled node chain").strip()
    context = str(chain.get("context") or "general").strip()
    goal = str(chain.get("goal") or "").strip()
    output_description = str(chain.get("output_description") or "").strip()
    tags = [str(tag).strip() for tag in (chain.get("tags") or []) if str(tag).strip()]

    nodes = chain.get("nodes") or []
    node_lines = []
    node_types = []
    for index, node in enumerate(nodes, start=1):
        if not isinstance(node, dict):
            continue
        node_name = str(node.get("name") or f"node{index}").strip()
        node_type = str(node.get("type") or "unknown").strip()
        node_types.append(node_type)
        parms_text = _format_chain_parms(node.get("parms") or {})
        flags = []
        if node.get("display_flag"):
            flags.append("display")
        if node.get("render_flag"):
            flags.append("render")
        flag_text = f" flags={','.join(flags)}" if flags else ""
        node_lines.append(f"{index}. {node_name} ({node_type}) parms: {parms_text}{flag_text}")

    connections = chain.get("connections") or []
    connection_lines = []
    for link in connections:
        if not isinstance(link, dict):
            continue
        connection_lines.append(
            f"- {link.get('from', '?')}[{link.get('from_output', 0)}] -> "
            f"{link.get('to', '?')}[{link.get('to_input', 0)}]"
        )

    merged_tags = (
        tags
        + [
            "node_chain",
            context.lower(),
            chain_id,
        ]
        + [nt.lower() for nt in node_types if nt]
    )
    merged_tags = [tag for tag in merged_tags if tag]

    content_parts = [
        f"Context: {context}",
        f"Goal: {goal or 'Build the described Houdini network.'}",
        f"Chain ID: {chain_id or 'unknown'}",
        f"Node count: {len(node_lines)}",
        "Nodes:\n" + ("\n".join(node_lines) if node_lines else "(no node definitions)"),
        "Connections:\n"
        + ("\n".join(connection_lines) if connection_lines else "(no explicit connections)"),
    ]
    if output_description:
        content_parts.append(f"Expected Output: {output_description}")

    return {
        "title": f"Node Chain: {title}",
        "category": "workflow",
        "tags": merged_tags,
        "content": "\n".join(content_parts),
        "_source": "node_chain_training",
        "_source_path": os.path.basename(source_path),
        "_chain_id": chain_id,
    }


def _load_node_chain_training_data() -> list:
    entries = []
    loaded_paths = []
    seen_chain_keys = set()
    glossary_added = False

    for source_path in _node_chain_source_candidates():
        if not os.path.exists(source_path):
            continue
        try:
            with open(source_path, encoding="utf-8") as f:
                payload = json.load(f)
        except Exception as e:
            print(f"[KB Builder] Failed to read node chain source {source_path}: {e}")
            continue

        chains = payload.get("chains") if isinstance(payload, dict) else None
        if not isinstance(chains, list):
            print(f"[KB Builder] Skipping node chain source {source_path}: no 'chains' list found")
            continue

        metadata = payload.get("metadata") if isinstance(payload, dict) else {}
        terminology = metadata.get("terminology") if isinstance(metadata, dict) else {}
        if (not glossary_added) and isinstance(terminology, dict) and terminology:
            glossary_lines = [
                f"- {term}: {meaning}"
                for term, meaning in terminology.items()
                if str(term).strip() and str(meaning).strip()
            ]
            if glossary_lines:
                entries.append(
                    {
                        "title": "Houdini Node Chain Terminology",
                        "category": "general",
                        "tags": ["glossary", "node_chain", "terminology"],
                        "content": "Terminology:\n" + "\n".join(glossary_lines),
                        "_source": "node_chain_training",
                        "_source_path": os.path.basename(source_path),
                    }
                )
                glossary_added = True

        for chain in chains:
            if not isinstance(chain, dict):
                continue
            chain_id = str(chain.get("id") or "").strip().lower()
            title = str(chain.get("title") or "").strip().lower()
            dedupe_key = chain_id or title
            if dedupe_key and dedupe_key in seen_chain_keys:
                continue
            if dedupe_key:
                seen_chain_keys.add(dedupe_key)
            entries.append(_chain_to_entry(chain, source_path))
        loaded_paths.append(source_path)

    if loaded_paths:
        print(
            f"[KB Builder] Loaded {len(entries)} node-chain knowledge entries "
            f"from {len(loaded_paths)} source file(s)"
        )
    return entries


def _houdini_python_source_candidates(data_dir: str | None = None) -> list[str]:
    candidates = []

    env_value = os.environ.get("HOUDINIMIND_HOUDINI_PYTHON_JSON", "").strip()
    if env_value:
        for part in env_value.split(os.pathsep):
            part = part.strip()
            if part:
                candidates.append(part)

    data_roots = [data_dir, DATA_DIR]
    for root in data_roots:
        if not root:
            continue
        candidates.extend(
            [
                os.path.join(root, "knowledge", "houdini_python_functions.json"),
                os.path.join(root, "db", "houdini_python_functions.json"),
                os.path.join(os.path.dirname(root), "houdini_python_functions.json"),
            ]
        )

    candidates.extend(
        [
            os.path.join(ROOT, "houdini_python_functions.json"),
            os.path.join(os.getcwd(), "houdini_python_functions.json"),
            os.path.join(os.path.dirname(os.getcwd()), "houdini_python_functions.json"),
        ]
    )

    seen = set()
    unique = []
    for path in candidates:
        norm = os.path.normcase(os.path.abspath(path))
        if norm in seen:
            continue
        seen.add(norm)
        unique.append(path)
    return unique


def _clean_houdini_python_text(value) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    replacements = {
        "â": "'",
        "â": "'",
        "â": '"',
        "â": '"',
        "â": "-",
        "â": "-",
        "Ã": "x",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return re.sub(r"\s+", " ", text).strip()


def _python_symbol_aliases(name: str, namespace: str, signature: str) -> list[str]:
    raw_name = str(name or "").strip().rstrip("()")
    raw_namespace = str(namespace or "").strip().rstrip(".")
    raw_signature = str(signature or "").strip()
    aliases = [raw_name]
    if raw_namespace and raw_name and not raw_name.startswith(raw_namespace + "."):
        method_name = raw_name.rsplit(".", 1)[-1]
        aliases.append(f"{raw_namespace}.{method_name}")
    if raw_signature:
        sig_name = raw_signature.split("(", 1)[0].strip()
        if sig_name:
            aliases.append(sig_name)
            if raw_namespace and "." not in sig_name:
                aliases.append(f"{raw_namespace}.{sig_name}")
    for alias in list(aliases):
        if "." in alias:
            aliases.append(alias.rsplit(".", 1)[-1])
    return _dedupe_tags(alias.lower() for alias in aliases if alias)


def _houdini_python_function_to_entry(item: dict, source_path: str, index: int) -> dict:
    name = _clean_houdini_python_text(item.get("name")) or f"hou.unknown_{index}"
    namespace = _clean_houdini_python_text(item.get("namespace")) or "hou"
    item_type = _clean_houdini_python_text(item.get("type")) or "function"
    signature = _clean_houdini_python_text(item.get("signature"))
    description = _clean_houdini_python_text(item.get("description"))
    aliases = _python_symbol_aliases(name, namespace, signature)

    content_parts = [
        f"Qualified Name: {name}",
        f"Namespace: {namespace}",
        f"Type: {item_type}",
    ]
    if signature:
        display_signature = signature
        if item_type == "method" and "." not in signature.split("(", 1)[0] and namespace:
            display_signature = f"{namespace}.{signature}"
        content_parts.append(f"Signature: {display_signature}")
    if description:
        content_parts.append(f"Description: {description}")
    if item_type == "method":
        content_parts.append(
            "Usage Note: call methods on the appropriate HOM object instance; verify exact "
            "attribute casing with live hou/dir() when the source name is normalized."
        )

    return {
        "title": f"Houdini Python HOM: {name}",
        "category": "python",
        "tags": _dedupe_tags(
            [
                "python",
                "hom",
                "hou",
                item_type,
                namespace,
                name,
                *aliases,
                *_slug_tokens(namespace),
                *_slug_tokens(name),
                *_slug_tokens(description[:240]),
            ]
        ),
        "content": "\n".join(content_parts),
        "_source": "houdini_python_functions_json",
        "_source_path": os.path.basename(source_path),
        "_python_symbol": aliases[0] if aliases else name.lower(),
        "_python_aliases": aliases,
        "_python_namespace": namespace,
        "_python_type": item_type,
    }


def _load_houdini_python_function_knowledge(data_dir: str | None = None) -> list:
    """Load the Houdini HOM Python reference as one RAG entry per function/method."""
    source_path = next(
        (path for path in _houdini_python_source_candidates(data_dir) if os.path.exists(path)), ""
    )
    if not source_path:
        return []

    try:
        with open(source_path, encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as e:
        print(f"[KB Builder] Failed to read Houdini Python JSON {source_path}: {e}")
        return []

    records = payload.get("functions") if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        print(f"[KB Builder] Skipping Houdini Python JSON {source_path}: no function list found")
        return []

    entries = []
    seen = set()
    for index, item in enumerate(records, start=1):
        if not isinstance(item, dict):
            continue
        name = _clean_houdini_python_text(item.get("name"))
        signature = _clean_houdini_python_text(item.get("signature"))
        dedupe_key = (name.lower(), signature.lower())
        if not name or dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        entries.append(_houdini_python_function_to_entry(item, source_path, index))

    if entries:
        print(
            f"[KB Builder] Loaded {len(entries)} Houdini Python HOM reference entries "
            f"from {os.path.basename(source_path)}"
        )
    return entries


_VEX_TYPE_PREFIXES = (
    "matrix4",
    "matrix3",
    "matrix2",
    "vector4",
    "vector2",
    "vector",
    "string",
    "float",
    "bsdf",
    "dict",
    "void",
    "int",
)


def _vex_db_source_candidates(data_dir: str | None = None) -> list[str]:
    candidates = []

    env_value = os.environ.get("HOUDINIMIND_VEX_FUNCTIONS_DB", "").strip()
    if env_value:
        for part in env_value.split(os.pathsep):
            part = part.strip()
            if part:
                candidates.append(part)

    data_roots = [data_dir, DATA_DIR]
    for root in data_roots:
        if not root:
            continue
        candidates.extend(
            [
                os.path.join(root, "knowledge", "vex_functions.db"),
                os.path.join(root, "db", "vex_functions.db"),
                os.path.join(os.path.dirname(root), "vex_functions.db"),
            ]
        )

    candidates.extend(
        [
            os.path.join(os.getcwd(), "vex_functions.db"),
            os.path.join(os.path.dirname(os.getcwd()), "vex_functions.db"),
        ]
    )

    seen = set()
    unique = []
    for path in candidates:
        norm = os.path.normcase(os.path.abspath(path))
        if norm in seen:
            continue
        seen.add(norm)
        unique.append(path)
    return unique


def _parse_jsonish_list(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if not isinstance(value, str):
        return [str(value).strip()] if str(value).strip() else []
    text = value.strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except Exception:
        parsed = None
    if isinstance(parsed, list):
        return [str(item).strip() for item in parsed if str(item).strip()]
    return [text]


def _format_vex_parameter(param: str) -> str:
    raw = str(param or "").strip()
    if not raw or raw == "...":
        return raw

    default = ""
    if "=" in raw:
        raw, default_value = raw.split("=", 1)
        default = "=" + default_value.strip()

    array_suffix = ""
    while raw.endswith("[]"):
        raw = raw[:-2]
        array_suffix += "[]"

    for type_name in ("<type>", *_VEX_TYPE_PREFIXES):
        if raw == type_name:
            return type_name + array_suffix + default
        if raw.startswith(type_name) and len(raw) > len(type_name):
            return f"{type_name}{array_suffix} {raw[len(type_name) :]}{default}"
    return raw + array_suffix + default


def _format_compact_vex_signature(function_name: str, signature: str) -> str:
    raw = str(signature or "").strip()
    if not raw:
        return ""

    marker = f"{function_name}("
    if marker not in raw:
        return raw

    return_type, rest = raw.split(marker, 1)
    return_type = return_type.strip()
    params_text = rest.rsplit(")", 1)[0] if ")" in rest else rest
    params = [_format_vex_parameter(part.strip()) for part in params_text.split(",")]
    rendered_params = ", ".join(part for part in params if part)
    if return_type:
        return f"{return_type} {function_name}({rendered_params})"
    return f"{function_name}({rendered_params})"


def _vex_db_function_to_entry(row: dict, signatures: list[tuple[str, str]]) -> dict:
    name = str(row.get("name") or "").strip()
    summary = str(row.get("summary") or "").strip()
    description = str(row.get("description") or "").strip()
    category = str(row.get("category") or "").strip()
    examples = _parse_jsonish_list(row.get("examples"))
    related = _parse_jsonish_list(row.get("related_functions"))

    signature_lines = []
    for signature, signature_description in signatures:
        rendered = _format_compact_vex_signature(name, signature)
        if not rendered:
            continue
        sig_desc = str(signature_description or "").strip()
        signature_lines.append(f"- {rendered}" + (f": {sig_desc}" if sig_desc else ""))

    content_parts = [
        f"Function: {name}",
        f"VEX Category: {category or 'uncategorized'}",
    ]
    if summary:
        content_parts.append(f"Summary: {summary}")
    if description and description != summary:
        content_parts.append(f"Description: {description}")
    if signature_lines:
        content_parts.append("Signatures:\n" + "\n".join(signature_lines))
    if examples:
        content_parts.append("Examples:\n" + "\n".join(f"- {example}" for example in examples[:8]))
    if related:
        content_parts.append("Related Functions: " + ", ".join(related[:20]))

    return {
        "title": f"VEX Function: {name}",
        "category": "vex",
        "tags": _dedupe_tags(
            [
                "vex",
                "function",
                name,
                *_slug_tokens(name),
                *_slug_tokens(category),
                *_slug_tokens(summary),
                *related[:20],
            ]
        ),
        "content": "\n".join(content_parts),
        "_source": "vex_functions_db",
        "_source_path": "vex_functions.db",
        "_vex_symbol": name,
        "_vex_category": category,
        "_signature_count": len(signature_lines),
    }


def _load_vex_function_db_knowledge(data_dir: str | None = None) -> list:
    """Load the SQLite VEX function reference as one RAG entry per function."""
    db_path = next(
        (path for path in _vex_db_source_candidates(data_dir) if os.path.exists(path)), ""
    )
    if not db_path:
        return []

    entries = []
    try:
        import sqlite3

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        function_rows = conn.execute(
            "SELECT name, summary, description, category, examples, related_functions "
            "FROM functions ORDER BY name"
        ).fetchall()
        signature_rows = conn.execute(
            "SELECT function_name, signature, description "
            "FROM signatures ORDER BY function_name, id"
        ).fetchall()
        conn.close()
    except Exception as e:
        print(f"[KB Builder] Failed to load VEX function DB {db_path}: {e}")
        return []

    signatures_by_function: dict[str, list[tuple[str, str]]] = {}
    for row in signature_rows:
        signatures_by_function.setdefault(str(row["function_name"]), []).append(
            (str(row["signature"] or ""), str(row["description"] or ""))
        )

    for row in function_rows:
        row_dict = dict(row)
        name = str(row_dict.get("name") or "").strip()
        if not name:
            continue
        entries.append(_vex_db_function_to_entry(row_dict, signatures_by_function.get(name, [])))

    if entries:
        print(
            f"[KB Builder] Loaded {len(entries)} VEX function reference entries "
            f"from {os.path.basename(db_path)}"
        )
    return entries


def _high_fidelity_source_candidates() -> list:
    candidates = []

    env_value = os.environ.get("HOUDINIMIND_HIGH_FIDELITY_PATH", "").strip()
    if env_value:
        for part in env_value.split(os.pathsep):
            part = part.strip()
            if part:
                candidates.append(part)

    knowledge_dir = os.path.join(DATA_DIR, "knowledge")
    if os.path.exists(knowledge_dir):
        patterns = (
            "dataset_high_fidelity.json",
            "dataset_high_fidelity*.json",
            "*high_fidelity*.json",
        )
        for pattern in patterns:
            for p in glob.glob(os.path.join(knowledge_dir, pattern)):
                candidates.append(p)

    seen = set()
    unique = []
    for path in candidates:
        norm = os.path.normcase(os.path.abspath(path))
        if norm in seen:
            continue
        seen.add(norm)
        unique.append(path)
    return unique


def _gemma_jsonl_source_candidates() -> list:
    candidates = []

    env_value = os.environ.get("HOUDINIMIND_GEMMA_DATASET_PATH", "").strip()
    if env_value:
        for part in env_value.split(os.pathsep):
            part = part.strip()
            if part:
                candidates.append(part)

    knowledge_dir = os.path.join(DATA_DIR, "knowledge")
    if os.path.exists(knowledge_dir):
        import glob

        for pattern in (
            "gemma4_houdini_dataset.jsonl",
            "*gemma*_dataset*.jsonl",
            "houdini_finetune.jsonl",
            "*finetune*.jsonl",
        ):
            for p in glob.glob(os.path.join(knowledge_dir, pattern)):
                candidates.append(p)

    candidates.extend(GEMMA_JSONL_DEFAULT_PATHS)

    seen = set()
    unique = []
    for path in candidates:
        norm = os.path.normcase(os.path.abspath(path))
        if norm in seen:
            continue
        seen.add(norm)
        unique.append(path)
    return unique


def _slug_tokens(text: str) -> list:
    parts = re.split(r"[^a-z0-9]+", str(text or "").lower())
    return [part for part in parts if part]


def _format_hf_node_inputs(inputs: list) -> str:
    rendered = []
    for item in inputs or []:
        if not isinstance(item, dict):
            continue
        rendered.append(f"{item.get('source', '?')}[{item.get('index', 0)}]")
    return ", ".join(rendered) if rendered else "none"


def _high_fidelity_to_entry(item: dict, source_path: str, fallback_index: int) -> dict:
    asset_name = str(item.get("asset_name") or f"asset_{fallback_index}").strip()
    approach = str(item.get("approach") or "").strip()
    network = item.get("network") or {}
    context = str(network.get("context") or "").strip()
    nodes = network.get("nodes") or []

    node_types = []
    node_lines = []
    display_nodes = []
    render_nodes = []

    for index, node in enumerate(nodes, start=1):
        if not isinstance(node, dict):
            continue
        node_name = str(node.get("name") or f"node{index}").strip()
        node_type = str(node.get("type") or "unknown").strip()
        params = node.get("parameters") or node.get("parms") or {}
        inputs = node.get("inputs") or []
        flags = node.get("flags") or {}
        node_types.append(node_type)

        flag_parts = []
        if flags.get("display"):
            flag_parts.append("display")
            display_nodes.append(node_name)
        if flags.get("render"):
            flag_parts.append("render")
            render_nodes.append(node_name)
        flag_text = f" flags={','.join(flag_parts)}" if flag_parts else ""

        node_lines.append(
            f"{index}. {node_name} ({node_type}) inputs: {_format_hf_node_inputs(inputs)}; "
            f"parms: {_format_chain_parms(params)}{flag_text}"
        )

    tags = []
    tags.extend(_slug_tokens(asset_name))
    tags.extend(_slug_tokens(context))
    tags.extend(_slug_tokens(approach))
    tags.extend(_slug_tokens(" ".join(node_types)))
    tags.extend(["high_fidelity", "asset_template"])
    deduped_tags = []
    seen = set()
    for tag in tags:
        if tag in seen:
            continue
        seen.add(tag)
        deduped_tags.append(tag)

    visible_nodes = display_nodes or render_nodes
    content_parts = [
        f"Asset: {asset_name}",
        f"Approach: {approach or 'Procedural Houdini network for this asset.'}",
        f"Context: {context or 'unspecified'}",
        f"Visible output nodes: {', '.join(visible_nodes) if visible_nodes else 'not specified'}",
        f"Node count: {len(node_lines)}",
        "Network:\n" + ("\n".join(node_lines) if node_lines else "(no node definitions)"),
    ]

    return {
        "title": f"High-Fidelity Asset: {asset_name.replace('_', ' ').title()}",
        "category": "workflow",
        "tags": deduped_tags,
        "content": "\n".join(content_parts),
        "_source": "high_fidelity_dataset",
        "_source_path": os.path.basename(source_path),
        "_asset_name": asset_name,
        "_context_path": context,
    }


def _load_high_fidelity_knowledge() -> list:
    entries = []
    loaded_paths = []
    seen_asset_keys = set()

    for source_path in _high_fidelity_source_candidates():
        if not os.path.exists(source_path):
            continue
        try:
            with open(source_path, encoding="utf-8") as f:
                payload = json.load(f)
        except Exception as e:
            print(f"[KB Builder] Failed to read high-fidelity dataset {source_path}: {e}")
            continue

        records = []
        if isinstance(payload, list):
            records = payload
        elif isinstance(payload, dict):
            for key in ("assets", "records", "entries", "items"):
                value = payload.get(key)
                if isinstance(value, list):
                    records = value
                    break
            if not records and payload.get("asset_name"):
                records = [payload]

        loaded = 0
        for index, item in enumerate(records, start=1):
            if not isinstance(item, dict) or not item.get("asset_name"):
                continue
            dedupe_key = str(item.get("asset_name") or "").strip().lower()
            if dedupe_key and dedupe_key in seen_asset_keys:
                continue
            if dedupe_key:
                seen_asset_keys.add(dedupe_key)
            entries.append(_high_fidelity_to_entry(item, source_path, index))
            loaded += 1

        if loaded:
            loaded_paths.append(source_path)
            print(
                f"[KB Builder] Loaded {loaded} high-fidelity asset entries from {os.path.basename(source_path)}"
            )

    if loaded_paths:
        print(
            f"[KB Builder] Loaded {len(entries)} total high-fidelity knowledge entries "
            f"from {len(loaded_paths)} source file(s)"
        )
    return entries


def _split_prompt_and_code(messages: list) -> tuple[str, str]:
    user_prompt = ""
    code_text = ""
    if not isinstance(messages, list):
        return user_prompt, code_text

    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "").strip().lower()
        content = str(message.get("content") or "").strip()
        if not content:
            continue
        if role == "user" and not user_prompt:
            user_prompt = content
        elif role in {"model", "assistant"} and not code_text:
            code_text = content

    if not code_text and messages:
        for message in messages:
            if not isinstance(message, dict):
                continue
            content = str(message.get("content") or "").strip()
            if content:
                code_text = content
                break

    return user_prompt, code_text


def _gemini_contents_to_messages(contents: list) -> list:
    """Translate Gemini-format `contents:[{role,parts:[{text}]}]` records
    into the OpenAI-style `messages:[{role,content}]` shape so the rest
    of the ingester can consume them unchanged."""
    messages = []
    if not isinstance(contents, list):
        return messages
    for item in contents:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        parts = item.get("parts") or []
        texts = []
        if isinstance(parts, list):
            for p in parts:
                if isinstance(p, dict) and p.get("text"):
                    texts.append(str(p["text"]))
                elif isinstance(p, str):
                    texts.append(p)
        content = "\n".join(t for t in texts if t).strip()
        if not content:
            continue
        messages.append({"role": role, "content": content})
    return messages


def _extract_fenced_code(text: str) -> str:
    if not text:
        return ""
    match = re.search(r"```(?:python|py)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return text.strip()


def _code_line_count(code: str) -> int:
    """Count non-blank, non-comment Python lines in a code block."""
    return sum(1 for ln in code.splitlines() if ln.strip() and not ln.strip().startswith("#"))


def _gemma_jsonl_record_to_entry(record: dict, source_path: str, index: int) -> dict:
    messages = record.get("messages") or []
    if not messages and record.get("contents"):
        messages = _gemini_contents_to_messages(record.get("contents"))
    prompt, code_text = _split_prompt_and_code(messages)

    base_name = os.path.basename(source_path).lower()
    is_cleaned = "cleaned" in base_name

    # Strip Gemma4 inline reasoning blocks before extracting code.
    if is_cleaned:
        code_text = _THOUGHT_CHANNEL_RE.sub("", code_text).strip()

    code_text = _extract_fenced_code(code_text)
    if not prompt and not code_text:
        return {}

    prompt_clean = prompt.strip()
    code_clean = code_text.strip()

    if is_cleaned:
        # Skip low-value templated entries (Asset Task = box+scale only).
        for skip_prefix in _CLEANED_SKIP_PREFIXES:
            if prompt_clean.startswith(skip_prefix):
                return {}

        # Skip entries with fewer than 4 real code lines — single-param templates.
        if _code_line_count(code_clean) < 4:
            return {}

        # Map question prefix to category.
        category = "recipe"
        for prefix, cat in _CLEANED_PREFIX_CATEGORY.items():
            if prompt_clean.startswith(prefix):
                category = cat
                break

        source_tag = "gemma4_cleaned_dataset"
        dataset_label = "Houdini Example"
    else:
        source_tag = "finetune_dataset"
        dataset_label = "Finetune Dataset"
        category = "workflow"
        if "gemma" in base_name:
            source_tag = "gemma4_houdini_dataset"
            dataset_label = "Gemma Houdini Dataset"

    title = prompt_clean or f"Finetune Example {index}"
    tags = _dedupe_tags(
        [
            source_tag,
            "houdini",
            "jsonl",
            "rag",
            "example",
            *_slug_tokens(prompt_clean),
            *_slug_tokens(code_clean[:400]),
        ]
    )

    content_parts = [f"Task: {prompt_clean or 'unspecified'}"]
    if code_clean:
        content_parts.append("Python:\n" + code_clean)

    return {
        "title": f"{dataset_label}: {title[:120]}",
        "category": category,
        "tags": tags,
        "content": "\n".join(content_parts),
        "_source": source_tag,
        "_source_path": os.path.basename(source_path),
        "_record_index": index,
    }


def _load_gemma_jsonl_knowledge() -> list:
    entries = []
    loaded_paths = []
    seen_prompts = set()

    for source_path in _gemma_jsonl_source_candidates():
        if not os.path.exists(source_path):
            continue
        try:
            with open(source_path, encoding="utf-8") as f:
                lines = [line.strip() for line in f if line.strip()]
        except Exception as e:
            print(f"[KB Builder] Failed to read Gemma JSONL {source_path}: {e}")
            continue

        loaded = 0
        for index, line in enumerate(lines, start=1):
            try:
                record = json.loads(line)
            except Exception:
                continue
            if not isinstance(record, dict):
                continue
            entry = _gemma_jsonl_record_to_entry(record, source_path, index)
            if not entry:
                continue
            prompt_key = entry.get("content", "").splitlines()[0].strip().lower()
            if prompt_key and prompt_key in seen_prompts:
                continue
            if prompt_key:
                seen_prompts.add(prompt_key)
            entries.append(entry)
            loaded += 1

        if loaded:
            loaded_paths.append(source_path)
            print(
                f"[KB Builder] Loaded {loaded} Gemma JSONL knowledge entries from "
                f"{os.path.basename(source_path)}"
            )

    if loaded_paths:
        print(
            f"[KB Builder] Loaded {len(entries)} total Gemma JSONL knowledge entries "
            f"from {len(loaded_paths)} source file(s)"
        )
    return entries


NODE_SECTION_LABELS = {
    "sops": "SOP",
    "Dop": "DOP",
    "Lop": "LOP",
    "Object": "OBJ",
    "Driver": "ROP",
    "Vop": "VOP",
}


def _dedupe_tags(tags: list) -> list:
    deduped = []
    seen = set()
    for tag in tags:
        token = str(tag or "").strip().lower()
        if not token or token in seen:
            continue
        seen.add(token)
        deduped.append(token)
    return deduped


def _render_scalar(value) -> str:
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return str(value)


def _format_list(values) -> str:
    rendered = [str(value).strip() for value in (values or []) if str(value).strip()]
    return ", ".join(rendered) if rendered else "none"


def _format_parameter_lines(parameters: dict) -> str:
    if not isinstance(parameters, dict) or not parameters:
        return "(no parameters documented)"

    lines = []
    for parm_name, spec in parameters.items():
        if isinstance(spec, dict):
            description = str(spec.get("description") or "").strip()
            meta = []
            if spec.get("type") not in (None, ""):
                meta.append(f"type={spec.get('type')}")
            if "default" in spec:
                meta.append(f"default={_render_scalar(spec.get('default'))}")
            meta_text = f" ({', '.join(meta)})" if meta else ""
            detail = description or "No description."
            lines.append(f"- {parm_name}{meta_text}: {detail}")
        else:
            lines.append(f"- {parm_name}: {_render_scalar(spec)}")
    return "\n".join(lines)


def _example_entry_category(source_basename: str) -> tuple:
    lower = source_basename.lower()
    if "vex" in lower:
        return "vex", "VEX"
    if "hda" in lower:
        return "workflow", "HDA Python"
    return "workflow", "Python HOM"


def _example_to_entry(example: dict, source_path: str) -> dict:
    source_basename = os.path.basename(source_path)
    kb_category, language_label = _example_entry_category(source_basename)
    example_name = str(example.get("name") or f"Example {example.get('id', '')}").strip()
    topic = str(example.get("category") or "general").strip()
    explanation = str(example.get("explanation") or "").strip()
    code = str(example.get("code") or "").rstrip()
    source_stem = os.path.splitext(source_basename)[0]

    tags = _dedupe_tags(
        _slug_tokens(source_stem)
        + _slug_tokens(example_name)
        + _slug_tokens(topic)
        + _slug_tokens(language_label)
        + ["example", kb_category]
    )

    content_parts = [
        f"Example ID: {example.get('id', 'unknown')}",
        f"Language: {language_label}",
        f"Topic: {topic}",
    ]
    if explanation:
        content_parts.append(f"Explanation: {explanation}")
    if code:
        content_parts.append("Code:\n" + code)

    return {
        "title": f"{language_label} Example: {example_name}",
        "category": kb_category,
        "tags": tags,
        "content": "\n".join(content_parts),
        "_source": source_stem,
        "_source_path": os.path.basename(source_path),
        "_example_id": example.get("id"),
    }


def _troubleshooting_to_entry(item: dict, source_path: str) -> dict:
    context = str(item.get("context") or "general").strip()
    error = str(item.get("error") or f"Error {item.get('id', '')}").strip()
    fix = str(item.get("fix") or "").strip()

    return {
        "title": f"Troubleshooting: {error}",
        "category": "errors",
        "tags": _dedupe_tags(
            ["troubleshooting", "error", *_slug_tokens(context), *_slug_tokens(error)]
        ),
        "content": "\n".join(
            [
                f"Context: {context}",
                f"Error: {error}",
                f"Fix: {fix or 'No fix documented.'}",
            ]
        ),
        "_source": os.path.splitext(os.path.basename(source_path))[0],
        "_source_path": os.path.basename(source_path),
        "_troubleshooting_id": item.get("id"),
    }


def _looks_like_node_dictionary(section_payload) -> bool:
    if not isinstance(section_payload, dict) or not section_payload:
        return False
    sample = next(iter(section_payload.values()))
    if not isinstance(sample, dict):
        return False
    return any(key in sample for key in ("description", "inputs", "outputs", "parameters", "error"))


def _node_definition_to_entry(
    section_name: str, node_name: str, definition: dict, source_path: str
) -> dict:
    network_label = NODE_SECTION_LABELS.get(section_name, str(section_name).upper())
    description = str(definition.get("description") or "").strip()
    error = str(definition.get("error") or "").strip()
    inputs = definition.get("inputs") or []
    outputs = definition.get("outputs") or []
    parameters = definition.get("parameters") or {}

    content_parts = [
        f"Node Type: {node_name}",
        f"Network Context: {network_label}",
    ]
    if description:
        content_parts.append(f"Description: {description}")
    if error:
        content_parts.append(f"Known Issue: {error}")
    content_parts.extend(
        [
            f"Inputs: {_format_list(inputs)}",
            f"Outputs: {_format_list(outputs)}",
            "Parameters:\n" + _format_parameter_lines(parameters),
        ]
    )

    return {
        "title": f"{network_label} Node: {node_name}",
        "category": "nodes",
        "tags": _dedupe_tags(
            [network_label.lower(), "node", *_slug_tokens(node_name), *_slug_tokens(description)]
        ),
        "content": "\n".join(content_parts),
        "_source": os.path.splitext(os.path.basename(source_path))[0],
        "_source_path": os.path.basename(source_path),
        "_node_type": node_name,
        "_node_context": network_label,
    }


def _vex_function_to_entry(function_name: str, definition: dict, source_path: str) -> dict:
    contexts = [str(ctx).strip() for ctx in (definition.get("contexts") or []) if str(ctx).strip()]
    signatures = [
        str(sig).strip() for sig in (definition.get("signatures") or []) if str(sig).strip()
    ]

    content_parts = [f"Function: {function_name}"]
    content_parts.append(f"Contexts: {', '.join(contexts) if contexts else 'unspecified'}")
    if signatures:
        content_parts.append(
            "Signatures:\n" + "\n".join(f"- {signature}" for signature in signatures)
        )

    return {
        "title": f"VEX Function: {function_name}",
        "category": "vex",
        "tags": _dedupe_tags(
            ["vex", "function", *_slug_tokens(function_name), *_slug_tokens(" ".join(contexts))]
        ),
        "content": "\n".join(content_parts),
        "_source": os.path.splitext(os.path.basename(source_path))[0],
        "_source_path": os.path.basename(source_path),
        "_vex_symbol": function_name,
    }


def _vex_attribute_to_entry(attribute_name: str, definition: dict, source_path: str) -> dict:
    attr_type = str(definition.get("type") or "unknown").strip()
    description = str(definition.get("description") or "").strip()

    return {
        "title": f"VEX Attribute: {attribute_name}",
        "category": "vex",
        "tags": _dedupe_tags(
            [
                "vex",
                "attribute",
                attr_type,
                *_slug_tokens(attribute_name),
                *_slug_tokens(description),
            ]
        ),
        "content": "\n".join(
            [
                f"Attribute: {attribute_name}",
                f"Type: {attr_type}",
                f"Description: {description or 'No description documented.'}",
            ]
        ),
        "_source": os.path.splitext(os.path.basename(source_path))[0],
        "_source_path": os.path.basename(source_path),
        "_vex_symbol": attribute_name,
    }


def _hscript_doc_to_entry(
    section_name: str, symbol_name: str, documentation, source_path: str
) -> dict:
    kind = section_name[:-1] if section_name.endswith("s") else section_name
    return {
        "title": f"HScript {kind}: {symbol_name}",
        "category": "general",
        "tags": _dedupe_tags(["hscript", kind.lower(), *_slug_tokens(symbol_name)]),
        "content": "\n".join(
            [
                f"HScript {kind}: {symbol_name}",
                "Documentation:",
                str(documentation).strip(),
            ]
        ),
        "_source": os.path.splitext(os.path.basename(source_path))[0],
        "_source_path": os.path.basename(source_path),
        "_hscript_symbol": symbol_name,
    }


def _intrinsic_entry_to_title(section_name: str, symbol_name: str) -> str:
    title_prefix = {
        "Definitions": "Intrinsic Definition",
        "Primitive_Types": "Primitive Type",
        "Detail_Intrinsics": "Detail Intrinsic",
    }.get(section_name, section_name.replace("_", " "))
    return f"{title_prefix}: {symbol_name}"


def _intrinsic_to_entry(
    section_name: str, symbol_name: str, documentation, source_path: str
) -> dict:
    label = section_name.replace("_", " ")
    return {
        "title": _intrinsic_entry_to_title(section_name, symbol_name),
        "category": "general",
        "tags": _dedupe_tags(["intrinsic", *_slug_tokens(label), *_slug_tokens(symbol_name)]),
        "content": "\n".join(
            [
                f"Section: {label}",
                f"Name: {symbol_name}",
                f"Description: {str(documentation).strip()}",
            ]
        ),
        "_source": os.path.splitext(os.path.basename(source_path))[0],
        "_source_path": os.path.basename(source_path),
        "_intrinsic_name": symbol_name,
    }


def _infer_list_entry_category(item: dict) -> str:
    """P0-A: Infer category from the keys present in a structured list entry."""
    keys = {k.lower() for k in item}
    if keys & {"error", "symptoms", "cause", "fix", "detailed_solution"}:
        return "errors"
    if keys & {"workflow", "steps", "prerequisites"}:
        return "workflow"
    if keys & {"recipe", "node_settings"}:
        return "recipe"
    if keys & {"topic", "scenario", "recommendation", "decision"}:
        return "best_practice"
    return "general"


def _entries_from_general_json(data, source_path: str) -> list:
    if isinstance(data, list):
        entries = []
        for item in data:
            if not isinstance(item, dict):
                continue
            if "content" in item:
                entries.append(
                    dict(
                        item,
                        _source=os.path.basename(source_path),
                        _source_path=os.path.basename(source_path),
                    )
                )
            else:
                title = "Knowledge Entry"
                for k, v in item.items():
                    if isinstance(v, str) and k.lower() in (
                        "node",
                        "workflow",
                        "error",
                        "asset",
                        "name",
                        "title",
                    ):
                        title = f"{k.title()}: {v}"
                        break
                lines = []
                for k, v in item.items():
                    if isinstance(v, list) and v and isinstance(v[0], str):
                        lines.append(f"{k.title()}: " + ", ".join(v))
                    elif isinstance(v, (dict, list)):
                        lines.append(f"{k.title()}:\n{json.dumps(v, indent=2)}")
                    else:
                        lines.append(f"{k.title()}: {v}")
                # P0-A: infer category from structure instead of always "general"
                inferred_category = _infer_list_entry_category(item)
                entries.append(
                    {
                        "title": title,
                        "category": inferred_category,
                        "tags": _dedupe_tags(_slug_tokens(title)),
                        "content": "\n".join(lines),
                        "_source": os.path.basename(source_path),
                        "_source_path": os.path.basename(source_path),
                    }
                )
        return entries

    if not isinstance(data, dict):
        return []

    if isinstance(data.get("verified_examples"), list):
        return [
            _example_to_entry(item, source_path)
            for item in data["verified_examples"]
            if isinstance(item, dict)
        ]

    if isinstance(data.get("troubleshooting_database"), list):
        return [
            _troubleshooting_to_entry(item, source_path)
            for item in data["troubleshooting_database"]
            if isinstance(item, dict)
        ]

    if isinstance(data.get("Vex_Functions"), dict) or isinstance(
        data.get("Standard_Attributes"), dict
    ):
        entries = []
        for function_name, definition in (data.get("Vex_Functions") or {}).items():
            if isinstance(definition, dict):
                entries.append(_vex_function_to_entry(function_name, definition, source_path))
        for attribute_name, definition in (data.get("Standard_Attributes") or {}).items():
            if isinstance(definition, dict):
                entries.append(_vex_attribute_to_entry(attribute_name, definition, source_path))
        return entries

    if isinstance(data.get("Expressions"), dict) or isinstance(data.get("Variables"), dict):
        entries = []
        for section_name in ("Expressions", "Variables"):
            for symbol_name, documentation in (data.get(section_name) or {}).items():
                entries.append(
                    _hscript_doc_to_entry(section_name, symbol_name, documentation, source_path)
                )
        return entries

    if any(
        isinstance(data.get(key), dict)
        for key in ("Definitions", "Primitive_Types", "Detail_Intrinsics")
    ):
        entries = []
        for section_name in ("Definitions", "Primitive_Types", "Detail_Intrinsics"):
            for symbol_name, documentation in (data.get(section_name) or {}).items():
                entries.append(
                    _intrinsic_to_entry(section_name, symbol_name, documentation, source_path)
                )
        return entries

    entries = []
    for section_name, section_payload in data.items():
        if _looks_like_node_dictionary(section_payload):
            for node_name, definition in section_payload.items():
                if isinstance(definition, dict):
                    entries.append(
                        _node_definition_to_entry(section_name, node_name, definition, source_path)
                    )
    if entries:
        return entries

    entry_list = data.get("entries", [])
    if not entry_list and isinstance(data.get("chains"), list):
        entry_list = data.get("chains")
    if not entry_list and "content" in data:
        entry_list = [data]

    result = []
    for item in entry_list:
        if not isinstance(item, dict):
            continue
        if "content" in item:
            enriched = dict(item)
            enriched["_source"] = os.path.basename(source_path)
            enriched["_source_path"] = os.path.basename(source_path)
            result.append(enriched)
        else:
            title = "Knowledge Entry"
            for k, v in item.items():
                if isinstance(v, str) and k.lower() in (
                    "node",
                    "workflow",
                    "error",
                    "asset",
                    "name",
                    "title",
                    "id",
                ):
                    title = f"{k.title()}: {v}"
                    break
            lines = []
            for k, v in item.items():
                if isinstance(v, list) and v and isinstance(v[0], str):
                    lines.append(f"{k.title()}: " + ", ".join(v))
                elif isinstance(v, (dict, list)):
                    lines.append(f"{k.title()}:\n{json.dumps(v, indent=2)}")
                else:
                    lines.append(f"{k.title()}: {v}")
            result.append(
                {
                    "title": title,
                    "category": "general",
                    "tags": _dedupe_tags(_slug_tokens(title)),
                    "content": "\n".join(lines),
                    "_source": os.path.basename(source_path),
                    "_source_path": os.path.basename(source_path),
                }
            )
    return result


def _load_general_json_knowledge() -> list:
    """Load arbitrary .json files from data/knowledge as standard knowledge entries."""
    entries = []
    knowledge_dir = os.path.join(DATA_DIR, "knowledge")
    if not os.path.exists(knowledge_dir):
        return entries

    exclude = {
        # Files with dedicated loaders — do not double-process
        "houdini_node_chains.json",
        "knowledge_base.json",
        "knowledge_base.generated.json",
        "dataset_high_fidelity.json",
        # Large duplicate Python example sets are excluded to cut index bloat and
        # retrieval noise. Keep the smaller 500-example set for curated coverage.
        "houdini_1000_python_complex_examples.json",
        "houdini_1000_unique_python_examples.json",
    }

    for path in glob.glob(os.path.join(knowledge_dir, "*.json")):
        basename = os.path.basename(path)
        if basename.lower() in exclude or basename.startswith("_"):
            continue

        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)

            converted = _entries_from_general_json(data, path)
            entries.extend(converted)
            loaded = len(converted)

            print(f"[KB Builder] Loaded {loaded} entries from {basename}")
        except Exception as e:
            print(f"[KB Builder] Failed to load JSON knowledge from {basename}: {e}")

    return entries


# ══════════════════════════════════════════════════════════════════════
#  Load accepted session recipes (user feedback learning)
# ══════════════════════════════════════════════════════════════════════


def _load_session_recipes() -> list:
    """
    Read accepted recipes from the SQLite RecipeBook and
    convert them to knowledge entries for the RAG.
    """
    db_path = os.path.join(DATA_DIR, "db", "recipes.db")
    if not os.path.exists(db_path):
        return []

    entries = []
    try:
        import sqlite3

        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT name, description, trigger_pattern, steps, domain "
            "FROM recipes WHERE confidence > 0.5 ORDER BY confidence DESC LIMIT 100"
        ).fetchall()
        conn.close()

        for name, description, trigger, steps_json, domain in rows:
            try:
                steps = json.loads(steps_json) if steps_json else []
            except Exception:
                steps = []
            step_text = (
                "\n".join(
                    f"  {i + 1}. {s.get('tool', '?')} {json.dumps(s.get('args', {}))}"
                    for i, s in enumerate(steps)
                )
                if steps
                else "(no steps recorded)"
            )

            entries.append(
                {
                    "title": f"Learned Recipe: {name}",
                    "category": "recipe",
                    "tags": ["learned", "recipe", domain or "general", trigger or ""],
                    "content": (
                        f"Description: {description}\nTrigger: {trigger}\nSteps:\n{step_text}"
                    ),
                    "_source": "session_recipe",
                }
            )
        print(f"[KB Builder] Loaded {len(entries)} session recipes")
    except Exception as e:
        print(f"[KB Builder] Failed to load session recipes: {e}")

    return entries


# ══════════════════════════════════════════════════════════════════════
#  Normalise and validate entries
# ══════════════════════════════════════════════════════════════════════

REQUIRED_KEYS = {"title", "category", "tags", "content"}
VALID_CATEGORIES = {
    "workflow",
    "recipe",
    "best_practice",
    "errors",
    "vex",
    "nodes",
    "sim",
    "usd",
    "general",
}

# P0-B: Sources that are fine-tuning datasets, not retrieval knowledge.
# They use synthetic numbered titles and inject prior model answers as context,
# which misleads retrieval and anchors the agent to potentially wrong answers.
_EXCLUDED_SOURCES = frozenset(
    {
        "finetune_dataset",
        "gemma4_houdini_dataset",
        # NOTE: "gemma4_cleaned_dataset" is intentionally NOT excluded — it is the
        # quality-filtered, thought-stripped version used for retrieval.
    }
)

# Cleaned JSONL dataset: question-prefix → RAG category mapping.
# "Asset Task" intentionally omitted — entries are trivially box+scale, no retrieval value.
_CLEANED_PREFIX_CATEGORY: dict = {
    "Dynamics Task": "recipe",
    "Python Task": "recipe",
    "Procedural Model": "recipe",
    "Action:": "recipe",
    "Action: ": "recipe",
    "Goal:": "recipe",
    "Build a procedural": "recipe",
    "Variation": "recipe",
    "VEX Script:": "vex",
    "Volumetric Task": "recipe",
}

# Prefixes that produce only trivial/templated one-liner entries.
_CLEANED_SKIP_PREFIXES: tuple = ("Asset Task",)

# Strips Gemma4 inline reasoning: <|channel>thought\n...<channel|>
_THOUGHT_CHANNEL_RE = re.compile(
    r"<\|channel>thought.*?<channel\|>",
    re.DOTALL,
)

# P0-C: Node entries with this sentinel have no parameter data — just a shell
# that consumes index space and returns empty information on retrieval.
_EMPTY_NODE_SENTINEL = "(no parameters documented)"


def _normalise(entries: list) -> list:
    import hashlib
    import re as _re

    def _content_fingerprint(text: str) -> str:
        """Whitespace-collapsed, case-folded SHA1 of the content body.

        Catches near-duplicates that differ only in formatting / casing —
        previously these slipped past the strict equality dedup and bloated
        the KB. We hash rather than store the full text so the seen-set stays
        small even for KBs with hundreds of thousands of entries.
        """
        if not text:
            return ""
        collapsed = _re.sub(r"\s+", " ", text).strip().lower()
        return hashlib.sha1(collapsed.encode("utf-8", "ignore")).hexdigest()

    normalised = []
    seen_keys: set = set()
    duplicates_dropped = 0
    excluded_sources = 0
    empty_nodes = 0
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            print(f"[KB Builder] Skipping entry {i}: not a dict")
            continue

        # P0-B: Drop synthetic fine-tuning dataset entries
        if entry.get("_source") in _EXCLUDED_SOURCES:
            excluded_sources += 1
            continue

        # Fill missing required keys with defaults
        if "title" not in entry:
            entry["title"] = f"Entry {i}"
        if "category" not in entry or entry["category"] not in VALID_CATEGORIES:
            entry["category"] = "general"
        if "tags" not in entry:
            entry["tags"] = []
        if "content" not in entry:
            print(f"[KB Builder] Skipping entry '{entry['title']}': no content")
            continue
        # Strip excessive whitespace from content
        entry["content"] = entry["content"].strip()
        if len(entry["content"]) < 20:
            continue

        # P0-C: Drop node entries that have no parameter data (scrape failures)
        if entry.get("category") == "nodes" and _EMPTY_NODE_SENTINEL in entry["content"]:
            empty_nodes += 1
            continue

        title_norm = _re.sub(r"\s+", " ", entry.get("title", "")).strip().lower()
        category_norm = (entry.get("category") or "").strip().lower()
        dedupe_key = (
            title_norm,
            category_norm,
            _content_fingerprint(entry.get("content", "")),
        )
        if dedupe_key in seen_keys:
            duplicates_dropped += 1
            continue
        seen_keys.add(dedupe_key)
        # Add metadata
        entry["_id"] = i
        entry["_added"] = time.time()
        normalised.append(entry)

    if excluded_sources:
        print(f"[KB Builder] Excluded {excluded_sources} synthetic fine-tuning entries")
    if empty_nodes:
        print(f"[KB Builder] Excluded {empty_nodes} empty node entries (no parameter data)")
    if duplicates_dropped:
        print(f"[KB Builder] Dropped {duplicates_dropped} near-duplicate entries")
    return normalised


# ══════════════════════════════════════════════════════════════════════
#  Main build function
# ══════════════════════════════════════════════════════════════════════


def build_kb(output_path: str | None = None, verbose: bool = True) -> str:
    """
    Build the knowledge base JSON from all sources.
    Returns path to the written file.
    """
    output_path = output_path or KB_PATH
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    if verbose:
        print("[KB Builder] Building knowledge base...")

    all_entries = []
    all_entries.extend(_load_builtin())
    all_entries.extend(_load_node_chain_training_data())
    all_entries.extend(_load_high_fidelity_knowledge())
    all_entries.extend(_load_gemma_jsonl_knowledge())
    all_entries.extend(_load_general_json_knowledge())
    all_entries.extend(_load_houdini_python_function_knowledge())
    all_entries.extend(_load_vex_function_db_knowledge())
    all_entries.extend(_load_session_recipes())

    normalised = _normalise(all_entries)

    kb = {
        "version": 2,
        "built_at": time.time(),
        "entry_count": len(normalised),
        "entries": normalised,
    }

    written_path = output_path
    try:
        with open(written_path, "w", encoding="utf-8") as f:
            json.dump(kb, f, indent=2, ensure_ascii=False)
    except PermissionError:
        fallback_path = KB_GENERATED_PATH
        os.makedirs(os.path.dirname(fallback_path), exist_ok=True)
        with open(fallback_path, "w", encoding="utf-8") as f:
            json.dump(kb, f, indent=2, ensure_ascii=False)
        written_path = fallback_path
        if verbose:
            print(
                f"[KB Builder] Primary KB path was locked. "
                f"Wrote generated KB instead -> {fallback_path}"
            )

    if verbose:
        print(f"[KB Builder] Wrote {len(normalised)} entries -> {written_path}")
        cats = {}
        for e in normalised:
            cats[e["category"]] = cats.get(e["category"], 0) + 1
        for cat, count in sorted(cats.items()):
            print(f"  {cat:20s}: {count}")

    return written_path


def rebuild_kb_from_session_feedback(data_dir: str | None = None):
    """
    Called after user gives feedback (Accept/Reject) to update the KB
    with newly learned patterns.
    """
    global DATA_DIR, KB_PATH
    if data_dir:
        DATA_DIR = data_dir
        KB_PATH = os.path.join(DATA_DIR, "knowledge", "knowledge_base.json")
    build_kb(verbose=False)


if __name__ == "__main__":
    build_kb()
