# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
"""
HoudiniMind — Shared Core Utilities
All sub-modules import from here. Safe, no circular imports.
"""

import traceback

_traceback = traceback
import ast
import difflib
import json
import os
import re
import subprocess
import tempfile
import threading
import time

HOUDINIMIND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
SCHEMA_PATH = os.path.join(HOUDINIMIND_ROOT, "data", "schema", "houdini_full_schema.json")

_search_retriever_lock = threading.Lock()
_search_retriever_cache = {"cache_key": None, "retriever": None}
_shared_embed_fn = None
_shared_chat_simple_fn = None

try:
    import hou

    HOU_AVAILABLE = True
    _hou = hou
except ImportError:
    HOU_AVAILABLE = False
    hou = None
    _hou = None

try:
    from ..interceptor import HoudiniPipelineInterceptor

    _pipeline_interceptor = HoudiniPipelineInterceptor(SCHEMA_PATH)
except Exception:
    _pipeline_interceptor = None


# ── Response helpers ────────────────────────────────────────────────────────


def _ok(data=None, message="OK"):
    return {"status": "ok", "message": message, "data": data}


def _err(msg):
    return {"status": "error", "message": msg, "data": None}


def _require_hou():
    if not HOU_AVAILABLE:
        raise RuntimeError("hou module not available — run inside Houdini")


def _snapshot_parm_value(parm):
    try:
        return parm.eval()
    except Exception:
        pass
    for attr in ("unexpandedString", "rawValue"):
        getter = getattr(parm, attr, None)
        if callable(getter):
            try:
                return getter()
            except Exception:
                pass
    return None


def _parse_expression_value(value):
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    lower = stripped.lower()
    if lower.startswith("python:"):
        expr = stripped.split(":", 1)[1].strip()
        return ("python", expr) if expr else None
    markers = (
        "$F",
        "$T",
        "$HIP",
        "$JOB",
        "$OS",
        "$FF",
        "$SF",
        "`",
        "ch(",
        "chs(",
        "chi(",
        "chf(",
        "detail(",
        "details(",
        "point(",
        "prim(",
        "vertex(",
        "bbox(",
        "centroid(",
        "fit(",
        "clamp(",
        "sin(",
        "cos(",
        "noise(",
        "rand(",
        "opinputpath(",
        "stamp(",
    )
    if any(m in stripped for m in markers):
        return ("hscript", stripped)
    return None


def _ordered_unique(values):
    seen = set()
    ordered = []
    for v in values:
        if v in seen or v in (None, ""):
            continue
        seen.add(v)
        ordered.append(v)
    return ordered


# ── Parameter helpers ────────────────────────────────────────────────────────


def _infer_child_context_core(parent):
    """Infer which child category can be created inside `parent`. Safe to call from _core."""
    try:
        child_cat = parent.childTypeCategory()
        if child_cat:
            return child_cat.name()
    except Exception:
        pass
    try:
        parent_type = parent.type().name().lower()
    except Exception:
        parent_type = ""
    fallback_map = {
        "geo": "Sop",
        "dopnet": "Dop",
        "lopnet": "Lop",
        "matnet": "Vop",
        "shopnet": "Shop",
        "chopnet": "Chop",
        "cop2net": "Cop2",
        "img": "Cop2",
        "topnet": "Top",
        "ropnet": "Driver",
    }
    if parent_type in fallback_map:
        return fallback_map[parent_type]
    try:
        return parent.type().category().name()
    except Exception:
        return "Object"


_infer_child_context = _infer_child_context_core


def _normalize_node_path(path):
    """Normalize Houdini node paths and accept common root aliases."""
    if not isinstance(path, str):
        return path
    normalized = path.strip()
    if not normalized:
        return path
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    normalized = re.sub(r"/+", "/", normalized)
    if len(normalized) > 1:
        normalized = normalized.rstrip("/")
    root_aliases = {
        "obj": "obj",
        "object": "obj",
        "objects": "obj",
    }
    parts = normalized.split("/")
    if len(parts) > 1:
        canonical_root = root_aliases.get(parts[1].lower())
        if canonical_root:
            parts[1] = canonical_root
            normalized = "/".join(parts) or "/"
    return normalized


def _ensure_parent_exists(path):
    path = _normalize_node_path(path)
    if not path or path == "/":
        return True
    if not HOU_AVAILABLE:
        return False
    try:
        node = hou.node(path)
        if node:
            return True
        parent_path = os.path.dirname(path)
        if not _ensure_parent_exists(parent_path):
            return False
        parent = hou.node(parent_path)
        if not parent:
            return False
        name = os.path.basename(path)
        context = _infer_child_context_core(parent)
        node_type = "geo" if context == "Object" else "subnet"
        parent.createNode(node_type, name)
        return True
    except Exception:
        return False


def _resolve_menu_value(parm, value):
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return value
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped:
        return value
    try:
        if stripped.isdigit() or (stripped.startswith("-") and stripped[1:].isdigit()):
            return int(stripped)
        tmpl = parm.parmTemplate()
        if not hasattr(hou, "MenuParmTemplate") or not isinstance(tmpl, (hou.MenuParmTemplate,)):
            return value
        labels = list(tmpl.menuLabels())
        tokens = list(tmpl.menuItems())
        val_lower = stripped.lower()
        for i, tok in enumerate(tokens):
            if tok.lower() == val_lower:
                return i
        for i, lbl in enumerate(labels):
            if lbl.lower() == val_lower:
                return i
        matches = [i for i, lbl in enumerate(labels) if val_lower in lbl.lower()]
        if len(matches) == 1:
            return matches[0]
    except Exception:
        pass
    return value


def _ensure_multiparm_count(node, parm_name):
    if not hasattr(hou, "parmTemplateType"):
        return False
    match = re.search(r"(\D+)(\d+)(\D*)", parm_name)
    if not match:
        return False
    prefix = match.group(1)
    index = int(match.group(2))
    count_candidates = [prefix + "s", prefix + "count", prefix + "_count", prefix]
    if prefix == "pt":
        count_candidates.append("points")
    if prefix == "val":
        count_candidates.append("values")
    for candidate in count_candidates:
        p = node.parm(candidate)
        if p and p.parmTemplate().type() == hou.parmTemplateType.Int:
            current = p.eval()
            if current <= index:
                p.set(index + 1)
                return True
    for p in node.parms():
        if p.name().startswith(prefix) and p.parentMultiParm():
            count_parm = p.parentMultiParm()
            if count_parm and count_parm.eval() <= index:
                count_parm.set(index + 1)
                return True
    return False


def _parse_vector_string(value):
    stripped = value.strip()
    if stripped[:1] in {"[", "("}:
        return None
    parts = stripped.split()
    if len(parts) < 2:
        return None
    try:
        return [float(p) for p in parts]
    except ValueError:
        return None


def _set_parm_value(parm, value):
    try:
        value = _resolve_menu_value(parm, value)
        tmpl = parm.parmTemplate()
        parm_template_type = getattr(hou, "parmTemplateType", None)
        tmpl_type = tmpl.type() if hasattr(tmpl, "type") else None
        if parm_template_type is None:
            parm.set(value)
            return {"mode": "value", "value": value}
        if isinstance(value, str) and tmpl.type() in (
            parm_template_type.Int,
            parm_template_type.Menu,
            parm_template_type.Toggle,
        ):
            try:
                value = int(float(value))
            except (ValueError, TypeError):
                pass
        try:
            parm.set(value)
        except (TypeError, hou.Error):
            if isinstance(value, (int, float, str)):
                try:
                    if tmpl_type == parm_template_type.Float:
                        parm.set(float(value))
                        return {"mode": "value", "value": float(value)}
                    elif tmpl_type == parm_template_type.Int:
                        parm.set(int(float(value)))
                        return {"mode": "value", "value": int(float(value))}
                except Exception:
                    pass
            raise
        if isinstance(value, (int, float)) and tmpl_type in (
            parm_template_type.Float,
            parm_template_type.Int,
        ):
            try:
                readback = parm.eval()
                if abs(readback - float(value)) > 1e-6:
                    try:
                        parm.deleteAllKeyframes()
                        parm.set(value)
                        readback2 = parm.eval()
                        if abs(readback2 - float(value)) > 1e-6:
                            return {
                                "mode": "value_mismatch",
                                "value": value,
                                "readback": readback2,
                                "warning": f"Parameter set to {value} but reads back as {readback2}.",
                            }
                    except Exception:
                        return {
                            "mode": "value_mismatch",
                            "value": value,
                            "readback": readback,
                            "warning": f"Parameter set to {value} but reads back as {readback}.",
                        }
            except Exception:
                pass
        return {"mode": "value", "value": value}
    except Exception as set_err:
        expr_info = _parse_expression_value(value)
        if expr_info and hasattr(parm, "setExpression"):
            language, expression = expr_info
            lang = (
                hou.exprLanguage.Python
                if str(language).lower() == "python"
                else hou.exprLanguage.Hscript
            )
            parm.setExpression(expression, lang)
            return {
                "mode": "expression",
                "expression": expression,
                "language": str(language),
            }
        return {"success": False, "error": str(set_err)}


def _resolve_geometry_source_node(node):
    if node is None:
        return None
    geometry_fn = getattr(node, "geometry", None)
    if callable(geometry_fn):
        return node
    for attr in ("displayNode", "renderNode"):
        getter = getattr(node, attr, None)
        if callable(getter):
            try:
                resolved = getter()
            except Exception:
                resolved = None
            if resolved is not None:
                return resolved
    try:
        children = list(node.children())
    except Exception:
        children = []
    flagged, named_out = [], []
    for child in children:
        if not callable(getattr(child, "geometry", None)):
            continue
        child_name = ""
        try:
            child_name = str(child.name() or "")
        except Exception:
            child_name = ""
        if child_name.upper() == "OUT":
            named_out.append(child)
        try:
            if child.isDisplayFlagSet() or child.isRenderFlagSet():
                flagged.append(child)
        except Exception:
            pass
    for candidate in flagged + named_out:
        return candidate
    return node


def _resolve_lop_stage_node(node):
    if node is None:
        return None
    if callable(getattr(node, "stage", None)):
        return node
    for attr in ("displayNode", "renderNode"):
        getter = getattr(node, attr, None)
        if callable(getter):
            try:
                resolved = getter()
            except Exception:
                resolved = None
            if resolved is not None and callable(getattr(resolved, "stage", None)):
                return resolved
    try:
        children = list(node.children())
    except Exception:
        children = []
    for child in children:
        if not callable(getattr(child, "stage", None)):
            continue
        try:
            if child.isDisplayFlagSet() or child.isRenderFlagSet():
                return child
        except Exception:
            pass
    for child in children:
        if callable(getattr(child, "stage", None)):
            return child
    return None


# ── Constants ────────────────────────────────────────────────────────────────

_HINT_STOPWORDS = {
    "a",
    "an",
    "and",
    "the",
    "with",
    "for",
    "from",
    "into",
    "onto",
    "make",
    "create",
    "build",
    "add",
    "set",
    "node",
    "nodes",
    "houdini",
    "geo",
}

_PARM_BASE_ALIASES = {
    "center": "t",
    "centre": "t",
    "position": "t",
    "translate": "t",
    "translation": "t",
    "move": "t",
    "offset": "t",
    "rotate": "r",
    "rotation": "r",
    "orient": "r",
    "pivot": "p",
    "radx": "rad1",
    "rady": "rad2",
    "radius": "rad",
    "radius1": "rad1",
    "radius2": "rad2",
    "top_radius": "rad2",
    "bottom_radius": "rad1",
    "topradius": "rad2",
    "bottomradius": "rad1",
    "toprad": "rad2",
    "bottomrad": "rad1",
    "point": "pt",
    "groundplane": "useground",
    "ground_plane": "useground",
    "enableground": "useground",
    "enable_ground": "useground",
    "showgroundplane": "showground",
    "show_ground_plane": "showground",
    "uniform_scale": "scale",
    "uniscale": "scale",
    "global_scale": "scale",
    "size": "size",
    "dimensions": "size",
    "resolution": "divs",
    "divisions": "divs",
    "segments": "divs",
    "rows": "rows",
    "cols": "cols",
    "columns": "cols",
    "density": "density",
    "amount": "amount",
    "distance": "dist",
}

_PARM_COMPONENT_ALIASES = {
    "width": "x",
    "height": "y",
    "depth": "z",
    "length": "z",
    "_x": "x",
    "_y": "y",
    "_z": "z",
    "posx": "x",
    "posy": "y",
    "posz": "z",
    "centerx": "x",
    "centery": "y",
    "centerz": "z",
    "centrex": "x",
    "centrey": "y",
    "centrez": "z",
    "translatex": "x",
    "translatey": "y",
    "translatez": "z",
    "rotationx": "x",
    "rotationy": "y",
    "rotationz": "z",
    "rotatex": "x",
    "rotatey": "y",
    "rotatez": "z",
    "u": "x",
    "v": "y",
    "w": "z",
    "x": "x",
    "y": "y",
    "z": "z",
    "r": "x",
    "g": "y",
    "b": "z",
    "red": "x",
    "green": "y",
    "blue": "z",
}

_INTERNAL_PARM_BLACKLIST = {
    "cacheinput",
    "vuelist",
    "stdutils",
    "input1",
    "input2",
    "copyinput",
    "undonode",
    "vop_compiler",
    "vop_force_code_gen",
}

_parm_resolution_cache = {}
_parm_resolution_cache_lock = threading.Lock()

SOP_TYPE_ALIASES = {
    "box": "box",
    "sphere": "sphere",
    "grid": "grid",
    "tube": "tube",
    "torus": "torus",
    "platonic": "platonic",
    "line": "line",
    "circle": "circle",
    "points from volume": "pointsfromvolume",
    "polybevel": "polybevel",
    "polybevel 2": "polybevel",
    "polybevel2": "polybevel",
    "polyextrude": "polyextrude",
    "polyextrude 2": "polyextrude",
    "polyextrude2": "polyextrude",
    "subdivide": "subdivide",
    "smooth": "smooth",
    "peak": "peak",
    "bend": "bend",
    "twist": "twist",
    "lattice": "lattice",
    "mountain": "mountain",
    "attribwrangle": "attribwrangle",
    "attrib wrangle": "attribwrangle",
    "attribute wrangle": "attribwrangle",
    "attribvop": "attribvop",
    "attribpromote": "attribpromote",
    "attribtransfer": "attribtransfer",
    "attribcreate": "attribcreate",
    "attribdelete": "attribdelete",
    "attribcopy": "attribcopy",
    "pointwrangle": "attribwrangle",
    "sweep": "sweep::2.0",
    "sweep_v2": "sweep::2.0",
    "mountain_v2": "mountain::2.0",
    "topobuild_v2": "topobuild::2.0",
    "polybridge_v2": "polybridge::2.0",
    "polybridge": "polybridge::2.0",
    "uvflatten": "uvflatten",
    "uvunwrap": "uvunwrap",
    "uvpelt": "uvpelt",
    "uvlayout": "uvlayout",
    "uvproject": "uvproject",
    "uvcheck": "uvcheck",
    "copytopoints": "copytopoints",
    "copy to points": "copytopoints",
    "copystamp": "copystamp",
    "instance": "instance",
    "packpoints": "packpoints",
    "pack": "pack",
    "unpack": "unpack",
    "boolean": "boolean",
    "merge": "merge",
    "switch": "switch",
    "object_merge": "object_merge",
    "resample": "resample",
    "polywire": "polywire",
    "carve": "carve",
    "sweep": "sweep",
    "dopimport": "dopimport",
    "vellumconstraints": "vellumconstraints",
    "vellumsolver": "vellumsolver",
    "vellumdrape": "vellumdrape",
    "vellumio": "vellumio",
    "name": "name",
    "group": "group",
    "groupcreate": "groupcreate",
    "grouppromote": "grouppromote",
    "null": "null",
    "out": "null",
    "out node": "null",
    "output": "output",
    "transform": "xform",
    "xform": "xform",
    "remesh": "remesh",
    "divide": "divide",
    "triangulate2d": "triangulate2d",
    "normal": "normal",
    "facet": "facet",
    "reverse": "reverse",
    "scatter": "scatter",
    "sort": "sort",
    "delete": "delete",
    "blast": "blast",
    "material": "material",
}

FILTER_NODE_TYPES = {
    "xform",
    "transform",
    "copy",
    "copytopoints",
    "merge",
    "polyextrude",
    "polybevel",
    "subdivide",
    "facet",
    "reverse",
    "attributevop",
    "attributewrangle",
    "group",
    "blast",
    "delete",
    "color",
    "uvunwrap",
    "uvlayout",
    "normal",
    "smooth",
    "resample",
    "clip",
    "boolean",
    "switch",
}


# ── Knowledge base helpers ──────────────────────────────────────────────────


def _knowledge_base_candidates(root_path):
    primary = os.path.join(root_path, "data", "knowledge", "knowledge_base.json")
    generated = os.path.join(root_path, "data", "knowledge", "knowledge_base.generated.json")
    return primary, generated


def _active_knowledge_base_path(root_path):
    primary, generated = _knowledge_base_candidates(root_path)
    if os.path.exists(generated) and (
        not os.path.exists(primary) or os.path.getmtime(generated) >= os.path.getmtime(primary)
    ):
        return generated
    return primary


def _get_search_retriever():
    from ...rag import create_rag_pipeline
    from ...rag import kb_builder as kb_mod
    from ..llm_client import load_config

    config_path = os.path.join(HOUDINIMIND_ROOT, "data", "core_config.json")
    kb_path = _active_knowledge_base_path(HOUDINIMIND_ROOT)
    cache_key = (
        HOUDINIMIND_ROOT,
        os.path.getmtime(config_path) if os.path.exists(config_path) else None,
        kb_path,
        os.path.getmtime(kb_path) if os.path.exists(kb_path) else None,
        os.environ.get("HOUDINIMIND_NODE_CHAINS_PATH", ""),
        os.environ.get("HOUDINIMIND_HIGH_FIDELITY_PATH", ""),
        id(_shared_embed_fn) if callable(_shared_embed_fn) else None,
    )
    with _search_retriever_lock:
        if _search_retriever_cache.get("cache_key") == cache_key:
            return _search_retriever_cache.get("retriever")
        try:
            cfg = load_config(config_path)
            if callable(_shared_embed_fn):
                cfg["_shared_embed_fn"] = _shared_embed_fn
            data_dir = cfg.get("data_dir") or os.path.join(HOUDINIMIND_ROOT, "data")
            original_root = kb_mod.ROOT
            original_data = kb_mod.DATA_DIR
            try:
                kb_mod.ROOT = HOUDINIMIND_ROOT
                kb_mod.DATA_DIR = data_dir
                injector = create_rag_pipeline(data_dir, cfg)
            finally:
                kb_mod.ROOT = original_root
                kb_mod.DATA_DIR = original_data
            retriever = getattr(injector, "retriever", None)
        except Exception:
            retriever = None
        _search_retriever_cache["cache_key"] = cache_key
        _search_retriever_cache["retriever"] = retriever
        return retriever


def _lexical_search_knowledge(query, top_k=5, category_filter=None):
    kb_entries = None
    try:
        kb_path = _active_knowledge_base_path(HOUDINIMIND_ROOT)
        if os.path.exists(kb_path):
            with open(kb_path, encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, list):
                kb_entries = data
            elif isinstance(data, dict) and isinstance(data.get("entries"), list):
                kb_entries = data["entries"]
    except Exception:
        kb_entries = None
    if not kb_entries:
        kb_entries = _HYBRID_KNOWLEDGE
    query_lower = query.lower()
    query_tokens = set(re.split(r"\W+", query_lower))
    scored = []
    for entry in kb_entries:
        score = 0
        title_lower = entry.get("title", "").lower()
        content_lower = entry.get("content", "").lower()
        tags = [t.lower() for t in entry.get("tags", [])]
        if query_lower in title_lower:
            score += 10
        for tok in query_tokens:
            if tok in tags:
                score += 5
        for tok in query_tokens:
            if len(tok) > 3 and tok in content_lower:
                score += 2
        if category_filter and entry.get("category") != category_filter:
            continue
        if score > 0:
            scored.append((score, entry))
    scored.sort(key=lambda x: x[0], reverse=True)
    results = [
        {
            "id": e.get("_id", e.get("id", "")),
            "title": e["title"],
            "category": e.get("category", ""),
            "relevance_score": s,
            "content": e["content"],
        }
        for s, e in scored[:top_k]
    ]
    return _ok({"query": query, "results_found": len(results), "results": results})


def _tokenize_hint_text(text):
    parts = re.findall(r"[a-z0-9_]+", (text or "").lower())
    return [p for p in parts if len(p) > 1 and p not in _HINT_STOPWORDS]


# ── Schema lookup helpers ───────────────────────────────────────────────────


def _schema_pool_for_context(context):
    if not _pipeline_interceptor or not _pipeline_interceptor.ready or not context:
        return tuple()
    for ctx_name, nodes in _pipeline_interceptor._node_lists_by_context.items():
        if ctx_name.lower() == context.lower():
            return tuple(nodes)
    return tuple()


def _schema_pool_for_node(node_type):
    if not _pipeline_interceptor or not _pipeline_interceptor.ready or not node_type:
        return tuple()
    return tuple(_pipeline_interceptor._parm_lists_by_node.get(str(node_type).lower(), []))


def _rank_text_candidates(pool, tokens, limit=8):
    if not pool:
        return []
    if not tokens:
        return list(pool)[:limit]
    scored = []
    for candidate in pool:
        lowered = str(candidate).lower()
        score = 0.0
        for token in tokens:
            if token == lowered:
                score += 10.0
            elif token in lowered or lowered in token:
                score += 5.0
            else:
                ratio = difflib.SequenceMatcher(None, token, lowered).ratio()
                if ratio >= 0.72:
                    score += ratio
        if score > 0:
            scored.append((score, candidate))
    scored.sort(key=lambda item: (-item[0], str(item[1])))
    return [candidate for _, candidate in scored[:limit]]


def _close_matches(value, pool, limit=8):
    guess = str(value or "").lower().strip()
    if not guess or not pool:
        return []
    lower_to_original = {str(item).lower(): item for item in pool}
    direct = [item for item in pool if guess in str(item).lower() or str(item).lower() in guess]
    fuzzy = difflib.get_close_matches(guess, list(lower_to_original.keys()), n=limit, cutoff=0.75)
    return _ordered_unique(direct + [lower_to_original[name] for name in fuzzy])[:limit]


def _parm_alias_candidates(parm_name):
    lowered = str(parm_name or "").strip().lower()
    if not lowered:
        return []
    candidates = [lowered]
    mapped_base = _PARM_BASE_ALIASES.get(lowered)
    if mapped_base:
        candidates.append(mapped_base)
    digit_match = re.search(r"(\D+)(\d+.*)$", lowered)
    if digit_match:
        base_part = digit_match.group(1)
        suffix_part = digit_match.group(2)
        if base_part in _PARM_BASE_ALIASES:
            candidates.append(f"{_PARM_BASE_ALIASES[base_part]}{suffix_part}")
    for suffix, mapped_suffix in sorted(
        _PARM_COMPONENT_ALIASES.items(), key=lambda item: len(item[0]), reverse=True
    ):
        if not lowered.endswith(suffix):
            continue
        base = lowered[: -len(suffix)]
        if suffix in {"x", "y", "z", "u", "v", "w"} and base.endswith(("_", "-", " ")):
            base = base[:-1]
        if not base:
            continue
        mapped_base = _PARM_BASE_ALIASES.get(base, base)
        candidates.append(f"{mapped_base}{mapped_suffix}")
    if digit_match:
        base_part = digit_match.group(1)
        suffix_part = digit_match.group(2)
        if base_part in _PARM_BASE_ALIASES:
            for c_suffix, c_mapped in _PARM_COMPONENT_ALIASES.items():
                if suffix_part.endswith(c_suffix):
                    naked_num = suffix_part[: -len(c_suffix)]
                    candidates.append(f"{_PARM_BASE_ALIASES[base_part]}{naked_num}{c_mapped}")
    return _ordered_unique(candidates)


def _normalize_parm_lookup_key(value):
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _resolve_parameter_name(
    parm_name,
    actual_parm_names,
    *,
    labels_by_name=None,
    node_type="",
):
    """Resolve an LLM/user parameter intent to a concrete Houdini parm name.

    This intentionally performs only deterministic, high-confidence resolution:
    exact name, known alias, exact normalized name, and exact normalized label.
    Fuzzy matches are returned as suggestions only and must not be auto-written.
    """
    requested = str(parm_name or "").strip()
    pool = [str(name) for name in (actual_parm_names or []) if str(name or "").strip()]
    if not requested or not pool:
        return {
            "status": "unresolved",
            "requested": requested,
            "resolved": "",
            "suggestions": [],
            "reason": "missing requested name or parameter pool",
        }

    labels_by_name = labels_by_name or {}
    cache_labels = tuple(
        sorted(
            (
                str(name),
                str(label),
            )
            for name, label in labels_by_name.items()
            if str(name or "").strip() and str(label or "").strip()
        )
    )
    cache_key = (
        str(node_type or "").lower(),
        requested.lower(),
        tuple(sorted(pool)),
        cache_labels,
    )
    with _parm_resolution_cache_lock:
        cached = _parm_resolution_cache.get(cache_key)
    if cached is not None:
        return dict(cached)

    lower_lookup = {name.lower(): name for name in pool}
    normalized_lookup = {}
    ambiguous_normalized = set()
    for name in pool:
        key = _normalize_parm_lookup_key(name)
        if not key:
            continue
        if key in normalized_lookup and normalized_lookup[key] != name:
            ambiguous_normalized.add(key)
        else:
            normalized_lookup[key] = name

    label_lookup = {}
    ambiguous_labels = set()
    for name, label in labels_by_name.items():
        if str(name) not in pool:
            continue
        key = _normalize_parm_lookup_key(label)
        if not key:
            continue
        if key in label_lookup and label_lookup[key] != str(name):
            ambiguous_labels.add(key)
        else:
            label_lookup[key] = str(name)

    def _resolved(name, reason):
        result = {
            "status": "resolved",
            "requested": requested,
            "resolved": name,
            "suggestions": [],
            "reason": reason,
        }
        with _parm_resolution_cache_lock:
            if len(_parm_resolution_cache) > 512:
                _parm_resolution_cache.clear()
            _parm_resolution_cache[cache_key] = dict(result)
        return result

    requested_lower = requested.lower()
    if requested_lower in lower_lookup:
        return _resolved(lower_lookup[requested_lower], "exact")

    for candidate in _parm_alias_candidates(requested):
        lowered = str(candidate).lower()
        if lowered in lower_lookup:
            return _resolved(lower_lookup[lowered], "alias")
        normalized = _normalize_parm_lookup_key(candidate)
        if (
            normalized
            and normalized not in ambiguous_normalized
            and normalized in normalized_lookup
        ):
            return _resolved(normalized_lookup[normalized], "normalized_alias")

    requested_key = _normalize_parm_lookup_key(requested)
    if requested_key:
        if requested_key not in ambiguous_normalized and requested_key in normalized_lookup:
            return _resolved(normalized_lookup[requested_key], "normalized_exact")
        if requested_key not in ambiguous_labels and requested_key in label_lookup:
            return _resolved(label_lookup[requested_key], "label")

    suggestions = _suggest_parm_names(pool, requested, limit=8)
    result = {
        "status": "unresolved",
        "requested": requested,
        "resolved": "",
        "suggestions": suggestions,
        "reason": "no deterministic match",
    }
    with _parm_resolution_cache_lock:
        if len(_parm_resolution_cache) > 512:
            _parm_resolution_cache.clear()
        _parm_resolution_cache[cache_key] = dict(result)
    return result


def _fuzzy_match_parameter(requested, pool, labels_by_name, node_type=""):
    """Use the LLM to pick the best parameter match from a pool of names/labels."""
    if not _shared_chat_simple_fn:
        return None
    try:
        pool_with_labels = []
        for name in pool:
            label = labels_by_name.get(name, "")
            if label:
                pool_with_labels.append(f"{name} ({label})")
            else:
                pool_with_labels.append(name)

        system_prompt = (
            "You are a Houdini Parameter Expert.\n"
            "Given a requested parameter name and a list of actual parameter names/labels, "
            "pick the one that MOST CLOSELY matches the intent.\n"
            "Return ONLY the internal name, no quotes, no explanation.\n"
            "If no match is close enough, return 'NONE'."
        )
        user_prompt = (
            f"Node Type: {node_type}\nRequested: {requested}\nPool: {pool_with_labels[:150]}"
        )
        match = _shared_chat_simple_fn(
            system=system_prompt, user=user_prompt, temperature=0.1, task="quick"
        ).strip()
        if match == "NONE":
            return None
        # Handle cases where LLM returns "name (label)"
        if "(" in match:
            match = match.split("(")[0].strip()
        return match
    except Exception:
        return None


def _resolve_node_type_name(node_type, available_node_types=None, aliases=None):
    requested = str(node_type or "").strip()
    if not requested:
        return {
            "status": "unresolved",
            "requested": requested,
            "resolved": "",
            "reason": "missing node type",
        }
    aliases = aliases or SOP_TYPE_ALIASES
    available = [str(name) for name in (available_node_types or []) if str(name or "").strip()]
    available_lower = {name.lower(): name for name in available}
    available_normalized = {}
    ambiguous = set()
    for name in available:
        key = _normalize_parm_lookup_key(name)
        if not key:
            continue
        if key in available_normalized and available_normalized[key] != name:
            ambiguous.add(key)
        else:
            available_normalized[key] = name

    requested_lower = requested.lower()
    alias = aliases.get(requested_lower)
    candidates = _ordered_unique([requested, alias] if alias else [requested])
    for candidate in candidates:
        if not candidate:
            continue
        candidate_lower = str(candidate).lower()
        if candidate_lower in available_lower:
            return {
                "status": "resolved",
                "requested": requested,
                "resolved": available_lower[candidate_lower],
                "reason": "exact_or_alias",
            }
        key = _normalize_parm_lookup_key(candidate)
        if key and key not in ambiguous and key in available_normalized:
            return {
                "status": "resolved",
                "requested": requested,
                "resolved": available_normalized[key],
                "reason": "normalized_exact_or_alias",
            }
    if alias:
        return {
            "status": "resolved",
            "requested": requested,
            "resolved": alias,
            "reason": "alias",
        }
    return {
        "status": "unresolved",
        "requested": requested,
        "resolved": "",
        "reason": "no deterministic match",
    }


def _suggest_parm_names(pool, parm_name, limit=8):
    if not pool or not parm_name:
        return []
    pool_list = list(pool)
    pool_lookup = {str(item).lower(): item for item in pool_list}
    alias_hits = [
        pool_lookup[candidate]
        for candidate in _parm_alias_candidates(parm_name)
        if candidate in pool_lookup
    ]
    full_pool = _ordered_unique(alias_hits + _close_matches(parm_name, pool_list, limit=limit))
    safe_pool = [p for p in full_pool if str(p).lower() not in _INTERNAL_PARM_BLACKLIST]
    return safe_pool[:limit]


# ── VEX validation ─────────────────────────────────────────────────────────


def _get_vcc_command():
    if not HOU_AVAILABLE:
        return None
    try:
        hfs = os.environ.get("HFS")
        if hfs:
            vcc_path = os.path.join(hfs, "bin", "vcc.exe")
            if os.path.exists(vcc_path):
                return vcc_path
        hou_path = os.path.dirname(hou.__file__)
        candidate = os.path.abspath(
            os.path.join(hou_path, "..", "..", "..", "..", "bin", "vcc.exe")
        )
        if os.path.exists(candidate):
            return candidate
        roots = ["C:\\Program Files\\Side Effects Software"]
        for root in roots:
            if not os.path.exists(root):
                continue
            for version_dir in os.listdir(root):
                vcc_bin = os.path.join(root, version_dir, "bin", "vcc.exe")
                if os.path.exists(vcc_bin):
                    return vcc_bin
    except Exception:
        pass
    return None


def _validate_vex_with_vcc(vex_code):
    vcc_cmd = _get_vcc_command()
    if not vcc_cmd:
        return {"success": False, "status": "compiler_not_found"}
    vfl_wrapper = f"""
#include <math.h>
cvex hmind_validate() {{
    vector P = {{0,0,0}};
    vector N = {{0,1,0}};
    vector Cd = {{1,1,1}};
    int ptnum = 0;
    int numpt = 0;
    {vex_code}
}}
"""
    try:
        with tempfile.NamedTemporaryFile(suffix=".vfl", mode="w", delete=False) as f:
            f.write(vfl_wrapper)
            tmp_vfl = f.name
        vcc_bin_dir = os.path.dirname(vcc_cmd)
        hfs_dir = os.path.dirname(vcc_bin_dir)
        vex_include = os.path.join(hfs_dir, "houdini", "vex", "include")
        vcc_args = [vcc_cmd, "-o", "NUL", "-c", "cvex", "-q"]
        if os.path.exists(vex_include):
            vcc_args.extend(["-I", vex_include])
        vcc_args.append(tmp_vfl)
        result = subprocess.run(vcc_args, capture_output=True, text=True, timeout=5)
        try:
            os.remove(tmp_vfl)
        except Exception:
            pass
        output = result.stderr or result.stdout
        errors = []
        vcc_success = result.returncode == 0
        if not vcc_success:
            for line in output.splitlines():
                match = re.search(r":(\d+): (error|warning): (.+)", line)
                if match:
                    line_num = int(match.group(1))
                    type_str = match.group(2)
                    msg = match.group(3)
                    adjusted_line = line_num - 10
                    if adjusted_line <= 0:
                        errors.append(f"Header {type_str}: {msg}")
                    else:
                        errors.append(f"Line {adjusted_line} {type_str}: {msg}")
                elif "error:" in line:
                    errors.append(line.strip())
        return {
            "success": vcc_success,
            "errors": errors,
            "warnings": [],
            "status": "ok",
        }
    except Exception as e:
        return {"success": False, "errors": [str(e)], "status": "error"}


def _validate_vex_with_checker(vex_code):
    vcc_res = _validate_vex_with_vcc(vex_code)
    if vcc_res.get("status") == "ok":
        return vcc_res
    try:
        if not HOU_AVAILABLE:
            return {"success": False, "errors": ["hou not available"], "warnings": []}
        parent = hou.node("/obj")
        checker_name = "__HOUDINIMIND_VEX_CHECKER__"
        checker = parent.node(checker_name)
        if not checker:
            temp_geo = parent.node("__HOUDINIMIND_TEMP_GEO__")
            if not temp_geo:
                temp_geo = parent.createNode("geo", "__HOUDINIMIND_TEMP_GEO__")
                temp_geo.hide(True)
            checker = temp_geo.createNode("attribwrangle", checker_name)
        snippet_parm = checker.parm("snippet")
        if not snippet_parm:
            return {
                "success": False,
                "errors": ["Could not find snippet parm on checker node"],
                "warnings": [],
            }
        snippet_parm.set(vex_code)
        try:
            checker.cook(force=True)
        except Exception:
            pass
        errors = [str(e) for e in checker.errors()]
        warnings = [str(w) for w in checker.warnings()]
        return {
            "success": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "status": "fallback",
        }
    except Exception as e:
        return {
            "success": False,
            "errors": [f"Validation system error: {e!s}"],
            "warnings": [],
        }


def _validate_python_code(code):
    try:
        ast.parse(code)
    except SyntaxError as e:
        error_msg = f"SyntaxError: {e.msg} (Line {e.lineno}, Offset {e.offset})"
        if e.text:
            error_msg += f"\nContext: {e.text.strip()}"
        return {"success": False, "errors": [error_msg], "status": "syntax_error"}
    except Exception as e:
        return {
            "success": False,
            "errors": [f"AST Parsing Error: {e!s}"],
            "status": "ast_error",
        }
    try:
        compile(code, "<string>", "exec")
    except IndentationError as e:
        return {
            "success": False,
            "errors": [f"IndentationError: {e!s}"],
            "status": "indentation_error",
        }
    except Exception as e:
        return {
            "success": False,
            "errors": [f"Compilation Error: {e!s}"],
            "status": "compile_error",
        }
    return {"success": True, "errors": [], "status": "ok"}


# ── Inline Knowledge Base ───────────────────────────────────────────────────

# ── Lazy registry accessor (populated by _registry.py after module load) ──────
_tool_functions_registry = None
_tool_schemas_registry = None
_tool_meta_registry = None


def _get_tool_functions():
    return _tool_functions_registry


def _get_tool_schemas():
    return _tool_schemas_registry


# ── Inline Knowledge Base ───────────────────────────────────────────────────

_HYBRID_KNOWLEDGE = [
    {
        "id": "vex_noise_displacement",
        "category": "vex",
        "tags": ["noise", "displacement", "mountain", "wrangle"],
        "title": "VEX: Noise-based displacement",
        "content": """// Point Wrangle — noise displacement
float freq = chf('freq');         // 2.0
float amp  = chf('amplitude');    // 0.1
vector seed = chv('seed');        // {0,0,0}
@P += normalize(@N) * noise(@P * freq + seed) * amp;""",
    },
    {
        "id": "vex_copy_stamp_replacement",
        "category": "vex",
        "tags": ["copy", "stamp", "instance", "detail"],
        "title": "VEX: Modern Copy Stamp replacement (Detail Wrangle)",
        "content": """// Detail Wrangle → drives Copy to Points
int count = chi('count');
for (int i = 0; i < count; i++) {
    int pt = addpoint(0, set(i * chf('spacing'), 0, 0));
    setpointattrib(0, 'scale', pt, fit(rand(i),0,1,0.5,2.0));
    setpointattrib(0, 'orient', pt, quaternion(radians(rand(i*7)*360),{0,1,0}));
}""",
    },
    {
        "id": "vex_group_by_normal",
        "category": "vex",
        "tags": ["group", "normal", "facing", "top"],
        "title": "VEX: Group primitives by normal direction",
        "content": """// Prim Wrangle
vector world_up = {0,1,0};
float facing = dot(normalize(@N), world_up);
if (facing > chf('threshold')) {  // 0.7
    setprimgroup(0, 'top_faces', @primnum, 1);
}""",
    },
    {
        "id": "vex_soft_transform",
        "category": "vex",
        "tags": ["soft", "falloff", "transform", "radial"],
        "title": "VEX: Radial soft transform with falloff",
        "content": """// Point Wrangle
vector centre = chv('centre');
float radius   = chf('radius');    // 1.0
float strength = chf('strength');  // 0.5
float dist = distance(@P, centre);
float falloff = pow(1.0 - clamp(dist/radius,0,1), chf('ramp_power'));
@P.y += falloff * strength;""",
    },
    {
        "id": "vex_texture_to_attrib",
        "category": "vex",
        "tags": ["texture", "map", "attribute", "colormap", "uv"],
        "title": "VEX: Sample texture map into a point attribute",
        "content": """// Point Wrangle (needs UV attribute)
string map = chs('texture_path');
vector2 uv = set(@uv.x, @uv.y);
@Cd = texture(map, uv.x, uv.y);""",
    },
    {
        "id": "vex_packed_instancing",
        "category": "vex",
        "tags": ["pack", "instance", "copy", "orient"],
        "title": "VEX: Set orient/scale for packed instancing",
        "content": """// Detail Wrangle — generates copy-to-points source
int pt = addpoint(0, {0,0,0});
vector4 orient = quaternion(radians(rand(@ptnum)*360), {0,1,0});
setpointattrib(0, 'orient', pt, orient);
setpointattrib(0, 'pscale', pt, fit(rand(@ptnum+7),0,1,0.5,1.5));""",
    },
    {
        "id": "vex_bed_variation",
        "category": "vex",
        "tags": ["bed", "random", "variation", "size", "wrangle"],
        "title": "VEX: Procedural Bed Variation (Detail)",
        "content": """// Detail Wrangle — drives bed asset parms
float seed = chf('global_seed');
f@width = fit(rand(seed), 0, 1, 1.4, 2.0); // 1.4m to 2.0m
f@length = fit(rand(seed + 0.1), 0, 1, 1.9, 2.2);
f@stiffness = fit(rand(seed + 0.2), 0, 1, 1e6, 1e9);
printf("Generated Bed: %f x %f", f@width, f@length);""",
    },
    {
        "id": "vex_fabric_normals",
        "category": "vex",
        "tags": ["fabric", "texture", "normal", "map", "uv", "bump"],
        "title": "VEX: Fabric Normal/Bump Perturbation",
        "content": """// Point/Prim Wrangle — add detail normal from map
string map = chs('normal_map_path');
vector2 uv = v@uv; // Ensure @uv exists
vector N_detail = texture(map, uv.x, uv.y);
@N = normalize(@N + (N_detail - 0.5) * chf('bump_strength'));""",
    },
    {
        "id": "recipe_scatter",
        "category": "recipe",
        "tags": ["scatter", "surface", "points", "distribute"],
        "title": "Recipe: Scatter points evenly on a surface",
        "content": """Node chain: Input → Scatter SOP (force_total_count=1, npts=5000, seed=0)
Set Scatter Method=Poisson Disk + Relax Iterations=5 for even distribution.
Downstream: Copy to Points (template geo on input 0, scatter pts on input 1)""",
    },
    {
        "id": "recipe_vellum_cloth",
        "category": "recipe",
        "tags": ["vellum", "cloth", "fabric", "drape"],
        "title": "Recipe: Vellum cloth simulation",
        "content": """1. Mesh → Remesh SOP (targetedgelength=0.05)
2. VellumConstraints (constrainttype=cloth, thickness=0.01, bendstiffness=1e9)
3. VellumSolver: input0=cloth, input1=colliders, input2=constraints
   substeps=3, constraintiterations=100
4. VellumIO for caching
Pin points: Point Wrangle before solver → setpointgroup(0,'pin',0,1); i@pintoanimation=1;""",
    },
    {
        "id": "recipe_boolean",
        "category": "recipe",
        "tags": ["boolean", "subtract", "union", "csg"],
        "title": "Recipe: Clean Boolean workflow",
        "content": """1. Both inputs MUST be closed manifold meshes. Run check_geometry_issues() first.
2. Boolean SOP (operation=subtract/union/intersect)
3. PolyDoctor SOP (fix non-manifold output)
4. Normal SOP (recompute normals)
5. Divide SOP (Remove Shared Edges) for clean topology
Failure = open meshes. Fix upstream: PolyFill → PolyDoctor""",
    },
    {
        "id": "recipe_uv",
        "category": "recipe",
        "tags": ["uv", "unwrap", "texel", "layout"],
        "title": "Recipe: Procedural UV workflow",
        "content": """1. UV Unwrap (method=LSCM) for organic; UV Project for hard surface
2. UV Layout (scale=1, resolution=1024)
3. UV Check (check_overlapping_uvs=1) — must be clean before export
4. Seams: Edge Group → UV Seam SOP before UV Unwrap
5. Validate texel density in Attribute Wrangle:
   f@area2d = surfaceArea(@primnum); // compare against 3D area""",
    },
    {
        "id": "recipe_softbody",
        "category": "recipe",
        "tags": ["vellum", "soft body", "jelly", "solid", "elastic"],
        "title": "Recipe: Vellum soft body (jelly/elastic solid)",
        "content": """1. Closed mesh → Divide SOP (tetrahedral=on) for volume tets
2. VellumConstraints (type=solid, stiffness=1e6, targetlength=1.0)
3. VellumSolver (substeps=4, constraintiterations=150, damping=0.1)
4. VellumIO to cache
Note: mesh MUST be closed watertight. Use check_geometry_issues() to verify.""",
    },
    {
        "id": "recipe_procedural_bed",
        "category": "recipe",
        "tags": ["bed", "furniture", "asset", "modeling", "sops", "procedural"],
        "title": "Recipe: Procedural Bed Asset (Non-Hardcoded)",
        "content": """1. Setup: create_bed_controls(parent_path, name='CONTROLS')
2. Frame: Box SOP (size=[ch('../CONTROLS/width'), 0.4, ch('../CONTROLS/length')])
3. Mattress: Box SOP (ty=ch('../CONTROLS/mattress_h')) → PolyBevel
4. Pillows: create_node(parent_path, 'box', name='pillow_base') → setup_vellum_pillow()
5. Integration: Always reference the CONTROLS node for all dimensions.""",
    },
    {
        "id": "recipe_bedding_vellum",
        "category": "recipe",
        "tags": [
            "bedding",
            "cloth",
            "vellum",
            "simulation",
            "duvet",
            "sheets",
            "procedural",
        ],
        "title": "Recipe: Vellum Bedding (Duvet/Sheets)",
        "content": """1. Master: create_bed_controls() for dimensions.
2. Duvet: Grid SOP (size=[ch('../CONTROLS/width')+0.4, ch('../CONTROLS/length')+0.2])
3. Sim: setup_vellum_cloth(pressure=2.0) for puffy duvets.
4. Collision: Mattress + Frame as static objects.
5. Post: Vellum Post-Process (subdivide=1) for final render.""",
    },
    {
        "id": "recipe_bedding_lookdev",
        "category": "recipe",
        "tags": ["lookdev", "material", "shading", "uv", "fabric", "render"],
        "title": "Recipe: Bedding Lookdev (UV & Shading)",
        "content": """1. Seams: create_uv_seams(duvet_node)
2. Lookdev: setup_fabric_lookdev(parent, duvet_node, base_color=(0.8,0.2,0.2))
3. Detail: Use VEX: Fabric Normal Perturbation for micro-weave detail.
4. Scale: Adjust 'uvscale' parameter on the UV Flatten node if texture repeating is visible.""",
    },
    {
        "id": "error_degenerate",
        "category": "errors",
        "tags": ["degenerate", "open mesh", "non-manifold", "nan"],
        "title": "Fix: Degenerate / bad geometry errors",
        "content": """1. check_geometry_issues() to identify problem type
2. NaN points: Attrib Wrangle → if(isnan(@P.x)||isnan(@P.y)||isnan(@P.z)) removepoint(0,@ptnum);
3. Zero-area prims: Facet SOP (remove inline points) → Divide SOP
4. Open meshes: PolyFill SOP → PolyDoctor SOP
5. Non-manifold: PolyDoctor (Fix Non-Manifold=on)""",
    },
    {
        "id": "error_vex",
        "category": "errors",
        "tags": ["vex", "compile", "syntax", "wrangle"],
        "title": "Fix: VEX compile / runtime errors",
        "content": """write_vex_code() returns compile errors directly.
Common mistakes:
- Missing semicolons
- Type mismatch: @P is vector, @ptnum is int — never mix without cast: (float)@ptnum
- setattrib() vs setpointattrib() — use specific version in wrangles
- @numpt is READ-ONLY in wrangles — use npoints(0) instead
Debug: printf("val=%f\\n", @myval); — visible in Houdini console""",
    },
    {
        "id": "bp_non_destructive",
        "category": "best_practice",
        "tags": ["non-destructive", "channel", "promote", "hda"],
        "title": "Best Practice: Non-destructive workflow",
        "content": """1. Use ch() expressions — never hardcode values
2. CONTROLS null at top of network for parametric builds
3. Channel references: ch('../CONTROLS/my_value')
4. Use promote_parameter() only when user explicitly asks to expose controls outside subnet/HDA
5. set_node_comment() + create_network_box() for documentation
6. save_hip(increment=True) before major changes
7. convert_to_hda() for reusable production assets""",
    },
    {
        "id": "bp_sim_opt",
        "category": "best_practice",
        "tags": ["sim", "optimization", "substeps", "cache", "performance"],
        "title": "Best Practice: Simulation optimisation",
        "content": """Use profile_network() to measure before/after.
1. Proxy geo: low-res for sim, Switch SOP to swap to hi-res
2. Substeps: start=1, increase only if instability (max 5)
3. Constraint iterations: 50 draft, 150+ final
4. Cache: bake_simulation() for sims >30 frames
5. Point budget: Vellum 5k–20k pts; FLIP 100k–500k
6. Remesh upstream: target edge = bbox_diagonal * 0.02""",
    },
]

try:
    from ._repair import REPAIR_STRATEGIES
except ImportError:
    REPAIR_STRATEGIES = {}
