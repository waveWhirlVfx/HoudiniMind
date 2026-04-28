# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
"""
HoudiniMind RAG — Retriever v2
Hybrid search: BM25 keyword + cosine vector similarity.

New in v2:
  - Uses Ollama embeddings (nomic-embed-text) for semantic similarity
  - Falls back gracefully to BM25-only when embeddings are unavailable
  - Stores embedding vectors alongside knowledge entries
  - Configurable hybrid_weight to balance keyword vs semantic scoring
"""

import hashlib
import json
import math
import os
import re
import threading

from .bm25 import BM25

_VECTOR_SIDECAR_LOCK = threading.Lock()


# ══════════════════════════════════════════════════════════════════════
#  Houdini-specific query expansion
# ══════════════════════════════════════════════════════════════════════

QUERY_EXPANSIONS: dict[str, list[str]] = {
    # Simulation
    "sim": ["simulation", "solver", "dop", "dopnet"],
    "fluid": ["flip", "liquid", "water", "flipsolver"],
    "smoke": ["pyro", "pyrosolver", "density", "temperature"],
    "fire": ["pyro", "combustion", "temperature", "burn"],
    "cloth": ["vellum", "constraint", "bend", "stretch"],
    "hair": ["vellum", "strand", "guide"],
    "sand": ["grain", "vellum", "granular"],
    "shatter": ["rbd", "fracture", "voronoi", "bullet", "destruction"],
    "break": ["rbd", "fracture", "constraint", "glue"],
    "explode": ["rbd", "destruction", "fracture"],
    "slow": ["performance", "optimise", "cook", "substeps", "speed"],
    "fast": ["performance", "cache", "instancing", "pack"],
    # P2-C: Simulation debugging vocabulary — previously missing, caused wrong
    # entries to surface for NaN/divergence/solver stability queries.
    "nan": ["diverge", "instability", "substep", "cfl", "velocity", "explode"],
    "diverge": ["nan", "instability", "substep", "cfl", "solver"],
    "instability": ["nan", "diverge", "substep", "cfl", "timestep"],
    "surface tension": ["surfacetension", "flip", "curvature", "narrowband"],
    "leak": ["collider", "sdf", "vdb", "gap", "hole", "boundary"],
    "stuck": ["constraint", "glue", "bullet", "rbd", "sleeping"],
    "jitter": ["noise", "substep", "velocity", "damp", "constraint"],
    "popping": ["flip", "particle", "velocity", "substep", "seeding"],
    "constraint": ["glue", "hinge", "spring", "bullet", "vellum", "rbd"],
    # Geometry
    "copy": ["copy to points", "copytopoints", "instancing"],
    "scatter": ["distribute", "points", "spread"],
    "colour": ["Cd", "color", "vertex colour", "attrib"],
    "color": ["Cd", "colour", "vertex color", "attrib"],
    "normal": ["N", "normal vector", "normals sop", "recompute"],
    "boolean": ["csg", "union", "intersect", "subtract"],
    "merge": ["combine", "join"],
    "delete": ["remove", "blast", "delete sop", "removepoint"],
    "group": ["selection", "setpointgroup", "blast"],
    "randomise": ["rand", "random", "pscale", "colour", "vex"],
    "randomize": ["rand", "random", "pscale", "color", "vex"],
    # VEX / Code
    "vex": ["wrangle", "snippet", "attribwrangle", "code"],
    "script": ["vex", "python", "wrangle", "expression"],
    "noise": ["perlin", "curl", "voronoi", "wnoise", "vnoise"],
    "texture": ["uv", "map", "image", "sample"],
    # Rendering
    "render": ["karma", "mantra", "rop", "ifd"],
    "light": ["env light", "area light", "point light", "hdri"],
    "camera": ["frustum", "aperture", "focal length", "dof"],
    # USD
    "usd": ["solaris", "lop", "stage", "prim"],
    # Animation
    "keyframe": ["key", "channel", "fcurve", "chops"],
    "animation": ["keyframe", "channel", "motion", "chops"],
}

LOW_WEIGHT_QUERY_SYNONYMS: dict[str, list[str]] = {
    "move": ["translate", "offset", "displace", "add", "shift"],
    "moving": ["translate", "offset", "displace", "add", "shift"],
    "upward": ["up", "raise", "increase", "add"],
    "downward": ["down", "lower", "decrease", "subtract"],
    "snippet": ["example", "code"],
    "example": ["snippet", "code"],
    "code": ["snippet", "example"],
    "fix": ["solve", "repair", "troubleshoot"],
    "parameter": ["parm", "parms"],
    "parameters": ["parm", "parms", "parameter"],
    "contexts": ["context"],
    "intrinsic": ["intrinsics"],
}

NODE_TITLE_PREFIXES = (
    "sop node:",
    "dop node:",
    "lop node:",
    "obj node:",
    "rop node:",
    "vop node:",
)

NODE_CONTEXT_TO_SHARD = {
    "sop": "sop_nodes",
    "dop": "dop_nodes",
    "lop": "lop_nodes",
    "obj": "obj_nodes",
    "rop": "rop_nodes",
    "vop": "vop_nodes",
}

SHARD_PRIORITY_ORDER = (
    "asset_workflows",
    "recipes",
    "general_reference",
    "python_examples",
    "hda_examples",
    "vex_reference",
    "troubleshooting",
    "simulation",
    "usd_workflows",
    "sop_nodes",
    "dop_nodes",
    "lop_nodes",
    "obj_nodes",
    "rop_nodes",
    "vop_nodes",
)

SHARD_ROUTE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "vex_reference": (
        "vex",
        "wrangle",
        "attribwrangle",
        "pointwrangle",
        "primwrangle",
        "detailwrangle",
        "snippet",
        "@ptnum",
        "@primnum",
        "@class",
        "setpointattrib",
        "addpoint",
        "addprim",
        "setprimattrib",
    ),
    "python_examples": (
        "python",
        "hou.",
        "hom",
        "kwargs",
        "callback",
        "shelf tool",
        "viewer state",
        "python panel",
        "parmtemplate",
        "parm template",
        "node.createnode",
        "python source editor",
    ),
    "hda_examples": (
        "hda",
        "digital asset",
        "otl",
        "type properties",
        "hdamodule",
        "asset definition",
        "operator type",
        "operator style sheet",
    ),
    "troubleshooting": (
        "error",
        "warning",
        "failed",
        "broken",
        "fix",
        "repair",
        "troubleshoot",
        "not working",
        "crash",
        "issue",
    ),
    "simulation": (
        "simulation",
        "sim",
        "vellum",
        "rbd",
        "flip",
        "pyro",
        "solver",
        "cloth",
        "hair",
        "grain",
        "smoke",
        "fire",
        "dopnet",
        "constraint",
    ),
    "usd_workflows": (
        "usd",
        "solaris",
        "stage",
        "prim",
        "karma",
        "lop",
        "materialx",
        "usd render",
        "scene graph",
    ),
    "general_reference": (
        "hscript",
        "intrinsic",
        "expression",
        "variable",
        "variables",
        "stamp",
        "detail intrinsic",
        "primitive intrinsic",
        "chs(",
        "chf(",
    ),
    "recipes": (
        "recipe",
        "workflow",
        "steps",
        "how do i",
        "how to",
    ),
}

ASSET_BUILD_HINTS = (
    "create",
    "build",
    "make",
    "model",
    "procedural",
    "asset",
    "object",
    "chair",
    "table",
    "bed",
    "sofa",
    "lamp",
    "tree",
    "bridge",
    "vehicle",
    "house",
    "prop",
    "furniture",
)

NODE_LOOKUP_HINTS = (
    "node",
    "nodes",
    "parameter",
    "parameters",
    "parm",
    "parms",
    "input",
    "inputs",
    "output",
    "outputs",
    "node type",
)

SOP_LOOKUP_HINTS = (
    "sop",
    "poly",
    "boolean",
    "blast",
    "group",
    "attrib",
    "copy to points",
    "transform",
    "merge",
    "box",
    "sphere",
    "null",
    "extrude",
)

OBJ_LOOKUP_HINTS = (
    "obj",
    "camera",
    "light",
    "geo object",
)

ROP_LOOKUP_HINTS = (
    "rop",
    "render",
    "mantra",
    "ifd",
    "usd render",
)

VOP_LOOKUP_HINTS = (
    "vop",
    "shader",
    "material builder",
    "vopnet",
)


def _lower_blob(*parts) -> str:
    return " ".join(str(part or "").lower() for part in parts if part)


def _contains_any_phrase(text: str, phrases: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(phrase in lowered for phrase in phrases)


def _entry_shard_name(entry: dict) -> str:
    title = str(entry.get("title", "") or "")
    category = str(entry.get("category", "") or "").lower()
    source = str(entry.get("_source", "") or "")
    source_path = os.path.basename(str(entry.get("_source_path", "") or ""))
    tags = " ".join(str(tag or "") for tag in (entry.get("tags") or []))
    node_context = str(entry.get("_node_context", "") or "").strip().lower()
    text = _lower_blob(title, source, source_path, tags)

    if category == "nodes":
        if node_context in NODE_CONTEXT_TO_SHARD:
            return NODE_CONTEXT_TO_SHARD[node_context]
        for prefix, shard_name in NODE_CONTEXT_TO_SHARD.items():
            if f"{prefix} node:" in title.lower():
                return shard_name
        return "sop_nodes"

    if category == "vex" or "vex function:" in title.lower() or "vex attribute:" in title.lower():
        return "vex_reference"

    if category == "errors" or "troubleshooting" in text:
        return "troubleshooting"

    if category == "recipe":
        return "recipes"

    if category == "sim":
        return "simulation"

    if category == "usd":
        return "usd_workflows"

    if "hda" in text or "digital asset" in text:
        return "hda_examples"

    if "python" in text or "hom" in text or title.lower().startswith("python hom example:"):
        return "python_examples"

    if "intrinsic" in text or "hscript" in text or title.lower().startswith("hscript "):
        return "general_reference"

    if category in {"workflow", "best_practice"}:
        if any(marker in text for marker in ("lop", "solaris", "usd", "karma")):
            return "usd_workflows"
        if any(marker in text for marker in ("dop", "vellum", "flip", "pyro", "rbd", "simulation")):
            return "simulation"
        return "asset_workflows"

    return "general_reference"


def _route_query_shards(query: str) -> list[str]:
    text = str(query or "").strip().lower()
    if not text:
        return list(SHARD_PRIORITY_ORDER[:3])

    scores: dict[str, float] = {}

    def boost(shard_name: str, amount: float):
        scores[shard_name] = scores.get(shard_name, 0.0) + amount

    for shard_name, keywords in SHARD_ROUTE_KEYWORDS.items():
        if _contains_any_phrase(text, keywords):
            boost(shard_name, 6.0)

    if _contains_any_phrase(text, ("hda", "digital asset", "otl", "hdamodule", "asset definition")):
        boost("hda_examples", 4.0)
        boost("python_examples", 1.5)

    if _contains_any_phrase(text, ASSET_BUILD_HINTS):
        boost("asset_workflows", 7.0)
        boost("recipes", 2.0)
        boost("sop_nodes", 2.0)

    if _contains_any_phrase(text, NODE_LOOKUP_HINTS):
        boost("sop_nodes", 4.0)

    if _contains_any_phrase(text, SOP_LOOKUP_HINTS):
        boost("sop_nodes", 6.0)
    if _contains_any_phrase(text, OBJ_LOOKUP_HINTS):
        boost("obj_nodes", 6.0)
    if _contains_any_phrase(text, ROP_LOOKUP_HINTS):
        boost("rop_nodes", 6.0)
    if _contains_any_phrase(text, VOP_LOOKUP_HINTS):
        boost("vop_nodes", 6.0)
    if "dop" in text:
        boost("dop_nodes", 6.0)
        boost("simulation", 3.0)
    if "lop" in text:
        boost("lop_nodes", 6.0)
        boost("usd_workflows", 3.0)
    if "obj" in text:
        boost("obj_nodes", 3.0)
    if "rop" in text:
        boost("rop_nodes", 3.0)
    if "vop" in text:
        boost("vop_nodes", 3.0)

    if "code" in text or "example" in text or "snippet" in text:
        if "vex" in text or "wrangle" in text:
            boost("vex_reference", 2.5)
        elif "python" in text or "hou." in text:
            boost("python_examples", 2.5)

    boost("general_reference", 1.0)

    ranked = sorted(
        scores.items(),
        key=lambda item: (
            -item[1],
            SHARD_PRIORITY_ORDER.index(item[0]) if item[0] in SHARD_PRIORITY_ORDER else 999,
        ),
    )
    ordered = [name for name, _score in ranked]
    for fallback in SHARD_PRIORITY_ORDER:
        if fallback not in ordered:
            ordered.append(fallback)
    return ordered


# ══════════════════════════════════════════════════════════════════════
#  Cosine similarity (zero external deps)
# ══════════════════════════════════════════════════════════════════════


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


# ══════════════════════════════════════════════════════════════════════
#  HybridRetriever
# ══════════════════════════════════════════════════════════════════════


class HybridRetriever:
    """
    Retrieves knowledge base chunks using a two-pass hybrid approach:

      BM25 score  ×  (1 - hybrid_weight)    — keyword / TF-IDF matching
    + cosine score × hybrid_weight          — semantic embedding similarity

    When embeddings are not available (Ollama offline, model not pulled),
    it falls back to BM25-only (hybrid_weight effectively becomes 0).
    """

    def __init__(
        self,
        kb_path: str,
        entries: list[dict] | None = None,
        embed_fn=None,  # callable: text -> Optional[List[float]]
        hybrid_weight: float = 0.4,  # 0 = pure BM25, 1 = pure cosine
        min_score: float = 0.05,
        enable_rerank: bool = True,
        prefetch_embeddings: bool = True,
    ):
        self.kb_path = kb_path
        self._static_entries = (
            [dict(entry) for entry in (entries or [])] if entries is not None else None
        )
        self.embed_fn = embed_fn
        self.hybrid_weight = hybrid_weight
        self.min_score = min_score
        self.enable_rerank = bool(enable_rerank)
        self.prefetch_embeddings = bool(prefetch_embeddings)

        self._entries: list[dict] = []
        self._bm25: BM25 | None = None
        self._vectors: list[list[float] | None] = []  # parallel to _entries
        self._entry_features: list[dict] = []
        self._embed_done: bool = False
        self._ranker = None
        self._rerank_unavailable = False
        self._embed_thread: threading.Thread | None = None
        self._embed_lock = threading.Lock()
        self._embed_generation = 0

        self._load_kb()
        if self.prefetch_embeddings:
            self._start_embedding_prefetch()

    def _rebuild_bm25(self):
        docs = [self._entry_text(e) for e in self._entries]
        self._bm25 = BM25()
        self._bm25.index(docs)
        self._entry_features = [self._build_entry_features(e) for e in self._entries]
        self._vectors = [None] * len(self._entries)
        self._embed_done = False
        self._embed_generation += 1

    def _base_kb_path(self) -> str:
        return str(self.kb_path).split("#", 1)[0]

    def _vectors_path(self) -> str:
        base_path = self._base_kb_path()
        root, ext = os.path.splitext(base_path)
        if ext:
            return f"{root}.vectors.json"
        return base_path + ".vectors.json"

    def _entry_vector_key(self, entry: dict, fallback_index: int) -> str:
        entry_id = entry.get("_id", entry.get("id"))
        if entry_id is None or str(entry_id).strip() == "":
            entry_id = f"runtime:{fallback_index}"
        return str(entry_id)

    def _entry_signature(self, entry: dict) -> str:
        return hashlib.sha1(self._entry_text(entry).encode("utf-8", errors="ignore")).hexdigest()

    def _restore_persisted_vectors(self) -> bool:
        if not self._entries or not self._vectors:
            return False
        base_kb_path = self._base_kb_path()
        vectors_path = self._vectors_path()
        if not os.path.exists(base_kb_path) or not os.path.exists(vectors_path):
            return False
        try:
            if os.path.getmtime(vectors_path) < os.path.getmtime(base_kb_path):
                return False
        except OSError:
            return False

        try:
            with _VECTOR_SIDECAR_LOCK, open(vectors_path, encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception:
            return False

        if isinstance(payload, list):
            restored = 0
            for i, vector in enumerate(payload[: len(self._vectors)]):
                if vector is None:
                    continue
                self._vectors[i] = vector
                restored += 1
            self._embed_done = restored == len(self._entries) and bool(self._entries)
            return restored > 0

        if not isinstance(payload, dict):
            return False

        stored_vectors = payload.get("vectors")
        if not isinstance(stored_vectors, dict):
            return False

        restored = 0
        for i, entry in enumerate(self._entries):
            stored = stored_vectors.get(self._entry_vector_key(entry, i))
            if not isinstance(stored, dict):
                continue
            vector = stored.get("vector")
            if not isinstance(vector, list):
                continue
            if stored.get("sig") != self._entry_signature(entry):
                continue
            self._vectors[i] = vector
            restored += 1

        self._embed_done = restored == len(self._entries) and bool(self._entries)
        return restored > 0

    def _persist_vectors_sidecar(self) -> None:
        if not self._entries or not self._vectors:
            return
        base_kb_path = self._base_kb_path()
        if not os.path.exists(base_kb_path):
            return

        stored_vectors = {}
        for i, entry in enumerate(self._entries):
            if i >= len(self._vectors):
                continue
            vector = self._vectors[i]
            if vector is None:
                continue
            stored_vectors[self._entry_vector_key(entry, i)] = {
                "sig": self._entry_signature(entry),
                "vector": vector,
            }
        if not stored_vectors:
            return

        vectors_path = self._vectors_path()
        payload = {
            "version": 1,
            "kb_mtime": os.path.getmtime(base_kb_path),
            "vectors": stored_vectors,
        }
        tmp_path = vectors_path + ".tmp"
        try:
            with _VECTOR_SIDECAR_LOCK:
                with open(tmp_path, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle)
                os.replace(tmp_path, vectors_path)
        except Exception:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass

    # ------------------------------------------------------------------
    # Knowledge base loading
    # ------------------------------------------------------------------
    def _load_kb(self):
        if self._static_entries is not None:
            self._entries = [dict(entry) for entry in self._static_entries]
            if self._entries:
                self._rebuild_bm25()
                self._restore_persisted_vectors()
            return
        if not os.path.exists(self.kb_path):
            return
        try:
            with open(self.kb_path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                self._entries = data
            elif isinstance(data, dict) and "entries" in data:
                self._entries = data["entries"]
            else:
                self._entries = []
        except Exception as e:
            print(f"[HybridRetriever] Failed to load KB: {e}")
            self._entries = []

        if self._entries:
            self._rebuild_bm25()
            self._restore_persisted_vectors()

    def _entry_text(self, entry: dict) -> str:
        title = str(entry.get("title", ""))
        category = str(entry.get("category", ""))
        tags = " ".join(str(tag) for tag in entry.get("tags", []))
        source = str(entry.get("_source", ""))
        content = str(entry.get("content", ""))

        parts = [
            title,
            title,
            title,
            category,
            category,
            tags,
            tags,
            source,
            content,
        ]
        return " ".join(p for p in parts if p)

    def _build_entry_features(self, entry: dict) -> dict:
        title = str(entry.get("title", ""))
        category = str(entry.get("category", ""))
        tags = [str(tag) for tag in entry.get("tags", [])]
        source = str(entry.get("_source", ""))
        content = str(entry.get("content", ""))
        title_lower = title.lower()
        content_lower = content.lower()
        title_tokens = set(BM25.tokenise(title))
        tag_tokens = set(BM25.tokenise(" ".join(tags)))
        category_tokens = set(BM25.tokenise(category))
        source_tokens = set(BM25.tokenise(source))

        return {
            "title_lower": title_lower,
            "content_lower": content_lower,
            "title_tokens": title_tokens,
            "tag_tokens": tag_tokens,
            "category_tokens": category_tokens,
            "source_tokens": source_tokens,
            "anchor_tokens": title_tokens | tag_tokens | category_tokens | source_tokens,
            "is_node_reference": category == "nodes" or title_lower.startswith(NODE_TITLE_PREFIXES),
            "is_vex_function": title_lower.startswith("vex function:"),
            "is_hscript_expression": title_lower.startswith("hscript expression:"),
            "is_intrinsic_reference": title_lower.startswith("intrinsic definition:"),
            "is_troubleshooting": category == "errors"
            or title_lower.startswith("troubleshooting:"),
            "is_explicit_example": (
                "example" in title_tokens or "example" in tag_tokens or "examples" in source_tokens
            ),
            "is_snippet_reference": ("snippet" in title_tokens or "snippet" in tag_tokens),
            "has_parameters": "parameters:" in content_lower,
            "has_contexts": "contexts:" in content_lower,
        }

    # ------------------------------------------------------------------
    # Background embedding prefetch
    # ------------------------------------------------------------------
    def _start_embedding_prefetch(self):
        if self._embed_done or not self.embed_fn or not self._entries:
            return
        if self._embed_thread and self._embed_thread.is_alive():
            return
        generation = self._embed_generation
        self._embed_thread = threading.Thread(
            target=self._embed_worker,
            args=(generation,),
            name="HoudiniMindRAGEmbed",
            daemon=True,
        )
        self._embed_thread.start()

    def _embed_worker(self, generation: int):
        for i, entry in enumerate(list(self._entries)):
            if generation != self._embed_generation:
                return
            if i >= len(self._vectors) or self._vectors[i] is not None:
                continue
            try:
                vector = self.embed_fn(self._entry_text(entry))
            except Exception:
                vector = None
            with self._embed_lock:
                if generation != self._embed_generation or i >= len(self._vectors):
                    return
                self._vectors[i] = vector
        if generation == self._embed_generation:
            self._embed_done = True
            self._persist_vectors_sidecar()

    def _ensure_embeddings(self):
        self._start_embedding_prefetch()

    # ------------------------------------------------------------------
    # Query expansion
    # ------------------------------------------------------------------
    def _expand_query(self, query: str) -> str:
        q_lower = query.lower()
        extras = []
        for term, expansions in QUERY_EXPANSIONS.items():
            if re.search(r"\b" + re.escape(term) + r"\b", q_lower):
                extras.extend(expansions)
        if extras:
            return query + " " + " ".join(extras)
        return query

    def _expanded_query_terms(self, query: str) -> list[str]:
        expanded_terms = list(BM25.tokenise(query))
        seen = set(expanded_terms)

        expanded_query = self._expand_query(query)
        if expanded_query != query:
            for token in BM25.tokenise(expanded_query):
                if token not in seen:
                    expanded_terms.append(token)
                    seen.add(token)

        for token in list(expanded_terms):
            for synonym in LOW_WEIGHT_QUERY_SYNONYMS.get(token, []):
                for synonym_token in BM25.tokenise(synonym):
                    if synonym_token not in seen:
                        expanded_terms.append(synonym_token)
                        seen.add(synonym_token)
        return expanded_terms

    def _safe_bm25_scores(self, query_text: str) -> list[float]:
        scores = self._bm25.get_scores(query_text)
        if len(scores) != len(self._entries):
            self._rebuild_bm25()
            self._restore_persisted_vectors()
            scores = self._bm25.get_scores(query_text)
        if len(scores) != len(self._entries):
            scores = list(scores[: len(self._entries)])
            if len(scores) < len(self._entries):
                scores.extend([0.0] * (len(self._entries) - len(scores)))
        return scores

    @staticmethod
    def _normalise_scores(scores: list[float]) -> list[float]:
        if not scores:
            return []
        max_score = max(scores)
        if max_score <= 0:
            return [0.0] * len(scores)
        return [score / max_score for score in scores]

    def _detect_query_intents(self, query: str, query_terms: list[str]) -> set:
        query_lower = query.lower()
        terms = set(query_terms)
        intents = set()

        if "node" in terms or any(
            token in terms for token in ("sop", "dop", "lop", "obj", "rop", "vop")
        ):
            intents.add("node")
        if "function" in terms or re.search(r"\bfunction\b", query_lower):
            intents.add("function")
        if "expression" in terms or "hscript" in terms:
            intents.add("expression")
        if "intrinsic" in terms or "intrinsics" in terms:
            intents.add("intrinsic")
        if terms.intersection({"error", "fix", "debug", "troubleshoot", "troubleshooting"}):
            intents.add("troubleshooting")
        if terms.intersection({"snippet", "example", "code", "script"}):
            intents.add("example")
        if "parameter" in terms or "parm" in terms or "parms" in terms:
            intents.add("parameters")
        if "context" in terms or "contexts" in terms:
            intents.add("contexts")
        return intents

    def _infer_metadata_preferences(self, query: str, query_terms: list[str]) -> dict:
        """Infer metadata preferences (difficulty, performance) from query."""
        query_lower = query.lower()
        prefs = {
            "preferred_difficulty": None,
            "prefer_performant": False,
            "prefer_simple": False,
            "avoid_severity": None,
        }

        # Detect difficulty preferences
        if any(x in query_lower for x in ["beginner", "simple", "basic", "easy", "tutorial"]):
            prefs["preferred_difficulty"] = "beginner"
            prefs["prefer_simple"] = True
        elif any(x in query_lower for x in ["advanced", "complex", "expert", "pro"]):
            prefs["preferred_difficulty"] = "advanced"
        elif any(x in query_lower for x in ["how do i", "how to", "example", "snippet"]):
            prefs["preferred_difficulty"] = "beginner"
            prefs["prefer_simple"] = True

        # Detect performance concerns
        if any(x in query_lower for x in ["slow", "fast", "performance", "optimize", "speed", "lag"]):
            prefs["prefer_performant"] = True

        # Detect severity preferences for errors
        if any(x in query_lower for x in ["crash", "fatal", "broken", "critical"]):
            prefs["avoid_severity"] = "low"

        return prefs

    def _metadata_boost(self, entry: dict, prefs: dict) -> float:
        """Calculate boost based on metadata alignment with preferences."""
        boost = 0.0

        difficulty = entry.get("difficulty", "").lower()
        if prefs.get("preferred_difficulty") and difficulty == prefs["preferred_difficulty"]:
            boost += 0.25

        if prefs.get("prefer_simple") and difficulty in ("beginner", "reference"):
            boost += 0.15

        if prefs.get("prefer_performant"):
            perf = entry.get("performance_impact", "").lower()
            if perf in ("low", "optimal"):
                boost += 0.18
            elif perf == "medium":
                boost += 0.06

        severity = entry.get("severity", "").lower()
        if prefs.get("avoid_severity") and severity != prefs["avoid_severity"]:
            boost += 0.08

        return boost

    def _looks_exact_lookup(self, query: str, query_terms: list[str], intents: set) -> bool:
        if intents.intersection({"node", "function", "expression", "intrinsic", "troubleshooting"}):
            return True
        if re.search(r"'[^']+'|\"[^\"]+\"", query):
            return True
        return any(
            self._bm25.idf.get(token, 0.0) >= 6.0 for token in query_terms if len(token) >= 3
        )

    def _intent_boost(self, features: dict, intents: set, query_terms: list[str]) -> float:
        boost = 0.0

        if "node" in intents and features["is_node_reference"]:
            boost += 0.32
            if "parameters" in intents and features["has_parameters"]:
                boost += 0.08
        if "function" in intents and features["is_vex_function"]:
            boost += 0.38
            if "contexts" in intents and features["has_contexts"]:
                boost += 0.07
        if "expression" in intents and features["is_hscript_expression"]:
            boost += 0.38
        if "intrinsic" in intents and features["is_intrinsic_reference"]:
            boost += 0.38
        if "troubleshooting" in intents and features["is_troubleshooting"]:
            boost += 0.34
        if "example" in intents:
            if features["is_explicit_example"]:
                boost += 0.2
                if "vex" in query_terms and "vex" in features["anchor_tokens"]:
                    boost += 0.06
            elif features["is_snippet_reference"]:
                boost += 0.08

        return boost

    def _exact_match_boost(
        self,
        index: int,
        features: dict,
        query_terms: list[str],
        expanded_terms: list[str],
    ) -> float:
        boost = 0.0
        title_tokens = features["title_tokens"]
        tag_tokens = features["tag_tokens"]
        anchor_tokens = features["anchor_tokens"]
        content_lower = features["content_lower"]

        informative_terms = []
        seen = set()
        for token in query_terms:
            if token in seen:
                continue
            seen.add(token)
            if len(token) > 2 or token in {"x", "y", "z", "u", "v"}:
                informative_terms.append(token)

        matched_anchor_terms = 0
        for token in informative_terms:
            in_title = token in title_tokens
            in_tags = token in tag_tokens
            in_anchor = in_title or in_tags or token in anchor_tokens
            if in_anchor:
                matched_anchor_terms += 1
            token_idf = self._bm25.idf.get(token, 0.0)
            if in_title:
                boost += min(token_idf / 12.0, 0.24)
            elif in_tags:
                boost += min(token_idf / 16.0, 0.14)
            elif token in content_lower:
                boost += min(token_idf / 22.0, 0.08)

        if informative_terms:
            coverage = matched_anchor_terms / len(informative_terms)
            boost += 0.12 * coverage

        original_term_set = set(query_terms)
        for token in expanded_terms:
            if token in original_term_set:
                continue
            token_idf = self._bm25.idf.get(token, 0.0)
            if token in title_tokens:
                boost += min(token_idf / 28.0, 0.07)
            elif token in tag_tokens:
                boost += min(token_idf / 36.0, 0.04)

        axis_terms = {"x", "y", "z", "u", "v"}
        if axis_terms.intersection(query_terms):
            axis_matches = axis_terms.intersection(title_tokens | tag_tokens)
            boost += 0.12 * len(axis_matches)

        motion_terms = {"move", "moving", "upward", "downward"}
        if motion_terms.intersection(query_terms):
            motion_matches = {"add", "translate", "offset", "displace", "shift", "raise", "lower"}
            if motion_matches.intersection(title_tokens):
                boost += 0.12
            elif motion_matches.intersection(tag_tokens):
                boost += 0.06

        return boost

    @staticmethod
    def _weighted_rrf(rank_maps: list[tuple[dict[int, int], float]], index: int) -> float:
        score = 0.0
        for rank_map, weight in rank_maps:
            rank = rank_map.get(index)
            if rank is None:
                continue
            score += weight * (1.0 / (60 + rank))
        return score

    def hot_retrieve(self, query: str, top_k: int = 1) -> list[dict]:
        """
        Lightweight retrieval for Fast Mode hints.
        Skips expansion, reranking, and complex intent boosting.
        """
        if not self._entries or not self._bm25:
            return []

        bm25_scores = self._safe_bm25_scores(query)
        bm25_norm = self._normalise_scores(bm25_scores)

        cosine_scores = [0.0] * len(self._entries)
        if self.embed_fn:
            try:
                q_vec = self.embed_fn(query)
                if q_vec:
                    for i, vec in enumerate(self._vectors):
                        if vec:
                            cosine_scores[i] = _cosine(q_vec, vec)
            except Exception:
                pass

        cosine_norm = self._normalise_scores(cosine_scores)

        # Simple blend
        final_scores = []
        for i in range(len(self._entries)):
            score = (bm25_norm[i] * 0.5) + (cosine_norm[i] * 0.5)
            final_scores.append((i, score))

        ranked = sorted(final_scores, key=lambda x: x[1], reverse=True)
        results = []
        for idx, score in ranked[:top_k]:
            if score > 0.1:
                results.append(self._entries[idx])
        return results

    # ------------------------------------------------------------------
    # Main retrieval
    # ------------------------------------------------------------------
    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        category_filter: str | None = None,
        min_score: float | None = None,
        include_live_scene: str | None = None,
        include_categories: list[str] | None = None,
        exclude_categories: list[str] | None = None,
        include_memory: bool = True,
        difficulty_filter: str | None = None,
        max_performance_impact: str | None = None,
        prefer_performant: bool = False,
        **kwargs,
    ) -> list[dict]:
        if not self._entries or not self._bm25:
            return []

        min_score = min_score if min_score is not None else self.min_score
        query_terms = BM25.tokenise(query)
        expanded_terms = self._expanded_query_terms(query)
        expanded_query_text = " ".join(expanded_terms) if expanded_terms else query
        exact_lookup = self._looks_exact_lookup(
            query, query_terms, self._detect_query_intents(query, query_terms)
        )
        intents = self._detect_query_intents(query, query_terms)

        # ── Infer & apply metadata preferences ─────────────────────────
        inferred_prefs = self._infer_metadata_preferences(query, query_terms)
        if prefer_performant:
            inferred_prefs["prefer_performant"] = True
        if difficulty_filter:
            inferred_prefs["preferred_difficulty"] = difficulty_filter

        # ── BM25 scores ──────────────────────────────────────────────
        bm25_scores = self._safe_bm25_scores(query)
        expanded_bm25_scores = (
            self._safe_bm25_scores(expanded_query_text)
            if expanded_query_text and expanded_query_text != query
            else list(bm25_scores)
        )
        bm25_norm = self._normalise_scores(bm25_scores)
        expanded_bm25_norm = self._normalise_scores(expanded_bm25_scores)

        # ── Semantic scores ───────────────────────────────────────────
        cosine_scores = [0.0] * len(self._entries)
        q_vec = None
        if self.embed_fn and self.hybrid_weight > 0:
            self._ensure_embeddings()
            try:
                q_vec = self.embed_fn(query)
            except Exception:
                pass
            if q_vec:
                current_vectors = list(self._vectors)
                for i, vec in enumerate(current_vectors):
                    if vec:
                        cosine_scores[i] = _cosine(q_vec, vec)

        cosine_norm = self._normalise_scores(cosine_scores)
        cosine_active = any(score > 0.0 for score in cosine_scores)

        # ── Setup MMR / RRF  ────────────────────────────────────────────
        use_rrf = kwargs.get("use_rrf", True)
        use_mmr = kwargs.get("use_mmr", True)

        # ── Blend lexical + semantic + exact-match boosts ──────────────
        lexical_weight = max(0.0, 1.0 - self.hybrid_weight)
        expanded_lexical_weight = min(0.25, lexical_weight * 0.35)
        primary_lexical_weight = lexical_weight - expanded_lexical_weight

        rank_maps: list[tuple[dict[int, int], float]] = []
        if use_rrf:
            bm25_ranked = sorted(
                range(len(bm25_scores)), key=lambda i: bm25_scores[i], reverse=True
            )
            rank_maps.append(
                (
                    {idx: rank + 1 for rank, idx in enumerate(bm25_ranked)},
                    primary_lexical_weight or 1.0,
                )
            )

            if expanded_query_text != query and any(score > 0.0 for score in expanded_bm25_scores):
                expanded_ranked = sorted(
                    range(len(expanded_bm25_scores)),
                    key=lambda i: expanded_bm25_scores[i],
                    reverse=True,
                )
                rank_maps.append(
                    (
                        {idx: rank + 1 for rank, idx in enumerate(expanded_ranked)},
                        max(expanded_lexical_weight, 0.12),
                    )
                )

            if cosine_active:
                cosine_ranked = sorted(
                    range(len(cosine_scores)), key=lambda i: cosine_scores[i], reverse=True
                )
                rank_maps.append(
                    ({idx: rank + 1 for rank, idx in enumerate(cosine_ranked)}, self.hybrid_weight)
                )

        scored = []
        for i, entry in enumerate(self._entries):
            category = entry.get("category", "")
            if category_filter and category != category_filter:
                continue
            if include_categories and category not in include_categories:
                continue
            if exclude_categories and category in exclude_categories:
                continue

            # ── Metadata filtering ──────────────────────────────────────
            if difficulty_filter:
                entry_difficulty = entry.get("difficulty", "").lower()
                if entry_difficulty != difficulty_filter.lower():
                    continue

            if max_performance_impact:
                impact = entry.get("performance_impact", "").lower()
                impact_order = {"low": 0, "medium": 1, "high": 2}
                max_order = impact_order.get(max_performance_impact.lower(), 999)
                if impact_order.get(impact, 999) > max_order:
                    continue

            base_score = primary_lexical_weight * bm25_norm[i]
            if expanded_query_text != query:
                base_score += expanded_lexical_weight * expanded_bm25_norm[i]
            if cosine_active:
                base_score += self.hybrid_weight * cosine_norm[i]
            if rank_maps:
                base_score += 8.0 * self._weighted_rrf(rank_maps, i)

            features = (
                self._entry_features[i]
                if i < len(self._entry_features)
                else self._build_entry_features(entry)
            )
            score = (
                base_score
                + self._intent_boost(features, intents, query_terms)
                + self._exact_match_boost(i, features, query_terms, expanded_terms)
                + self._metadata_boost(entry, inferred_prefs)
            )

            if score >= min_score:
                scored.append((score, i))

        scored.sort(key=lambda x: x[0], reverse=True)

        # ── MMR (Maximum Marginal Relevance) ─────────────────────────────
        if use_mmr and q_vec and scored and not exact_lookup:
            candidates = [idx for _, idx in scored[: max(top_k * 2, 10)]]
            selected = []
            unselected = list(candidates)
            lambda_param = 0.5

            while len(selected) < top_k and unselected:
                best_score = -float("inf")
                best_idx = -1

                for idx in unselected:
                    sim_q = cosine_scores[idx]
                    sim_sel = 0.0
                    if selected:
                        sim_sel = max(
                            _cosine(self._vectors[idx], self._vectors[s])
                            if self._vectors[idx] and self._vectors[s]
                            else 0.0
                            for s in selected
                        )

                    mmr_score = lambda_param * sim_q - (1 - lambda_param) * sim_sel
                    if mmr_score > best_score:
                        best_score = mmr_score
                        best_idx = idx

                if best_idx != -1:
                    selected.append(best_idx)
                    unselected.remove(best_idx)

            final_scored = []
            for s_idx in selected:
                orig_score = next((s for s, i in scored if i == s_idx), 0.0)
                final_scored.append((orig_score, s_idx))
            scored = final_scored

        results = []
        # Prepend live scene if provided as a virtual chunk
        if include_live_scene:
            results.append(
                {
                    "id": "live_scene",
                    "title": "Current Houdini Scene",
                    "category": "live",
                    "content": include_live_scene,
                    "_score": 1.0,
                }
            )

        for score, idx in scored[:top_k]:
            entry = dict(self._entries[idx])
            # Map _id to id for injector compatibility
            entry["id"] = entry.get("_id", idx)
            entry["_score"] = round(score, 4)
            results.append(entry)

        # ── FlashRank reranking (skip while embeddings are still warming) ───
        should_rerank = (
            self.enable_rerank
            and kwargs.get("use_rerank", True)
            and self.hybrid_weight > 0
            and not exact_lookup
        )
        embeddings_warming = bool(
            self._embed_thread and self._embed_thread.is_alive() and not self._embed_done
        )
        if should_rerank and not embeddings_warming and not self._rerank_unavailable:
            try:
                from flashrank import Ranker, RerankRequest

                if getattr(self, "_ranker", None) is None:
                    self._ranker = Ranker(model_name="ms-marco-TinyBERT-L-2-v2")

                passages = []
                for res in results:
                    if res.get("id") == "live_scene":
                        continue
                    passages.append(
                        {
                            "id": str(res["id"]),
                            "text": res.get("content", ""),
                            "meta": {"category": res.get("category", "")},
                        }
                    )

                if len(passages) >= 2:
                    rerankrequest = RerankRequest(query=expanded_query_text, passages=passages)
                    reranked = self._ranker.rerank(rerankrequest)

                    new_results = [r for r in results if r.get("id") == "live_scene"]
                    for ranked_item in reranked:
                        orig = next(
                            (r for r in results if str(r["id"]) == str(ranked_item["id"])), None
                        )
                        if orig:
                            orig["_score"] = round(ranked_item["score"], 4)
                            new_results.append(orig)
                    results = new_results
            except ImportError:
                self._rerank_unavailable = True
            except Exception as e:
                self._rerank_unavailable = True
                print(f"[HybridRetriever] FlashRank error: {e}")

        return results

    def get_chunk(self, cid) -> dict | None:
        """Fetch a specific chunk by its ID (usually _id from build)."""
        cid_str = str(cid)
        for entry in self._entries:
            if str(entry.get("_id")) == cid_str or str(entry.get("id")) == cid_str:
                res = dict(entry)
                res["id"] = res.get("_id", cid)
                return res
        return None

    def retrieve_by_category(self, category: str, top_k: int = 10) -> list[dict]:
        return [e for e in self._entries if e.get("category") == category][:top_k]

    def add_entry(self, entry: dict):
        """Dynamically add a new entry and update the BM25 index."""
        self._entries.append(entry)
        if self._static_entries is not None:
            self._static_entries.append(dict(entry))
        self._rebuild_bm25()
        self._restore_persisted_vectors()
        if self.prefetch_embeddings:
            self._start_embedding_prefetch()

    def extend_entries(self, entries: list[dict]):
        """Dynamically append multiple entries and rebuild once."""
        if not entries:
            return
        self._entries.extend(entries)
        if self._static_entries is not None:
            self._static_entries.extend(dict(entry) for entry in entries)
        self._rebuild_bm25()
        self._restore_persisted_vectors()
        if self.prefetch_embeddings:
            self._start_embedding_prefetch()

    def reload(self):
        self._entries = []
        self._bm25 = None
        self._vectors = []
        self._entry_features = []
        self._embed_done = False
        self._embed_generation += 1
        self._load_kb()
        if self._entries and self.prefetch_embeddings:
            self._start_embedding_prefetch()


class QueryAwareShardRetriever:
    """
    Query-routed retriever that keeps one logical knowledge base but lazily
    loads only the most relevant shards for the current query.

    This keeps startup and first-turn latency lower than building one large
    hybrid index across every Houdini corpus at once.
    """

    def __init__(
        self,
        kb_path: str,
        embed_fn=None,
        hybrid_weight: float = 0.4,
        min_score: float = 0.05,
        enable_rerank: bool = True,
        max_shards_per_query: int = 3,
        shard_prefetch_embeddings: bool = False,
    ):
        self.kb_path = kb_path
        self.embed_fn = embed_fn
        self.hybrid_weight = hybrid_weight
        self.min_score = min_score
        self.enable_rerank = bool(enable_rerank)
        self.max_shards_per_query = max(1, int(max_shards_per_query or 3))
        self.shard_prefetch_embeddings = bool(shard_prefetch_embeddings)

        self._entries: list[dict] = []
        self._entry_by_id: dict[str, dict] = {}
        self._entries_by_shard: dict[str, list[dict]] = {}
        self._shard_categories: dict[str, set] = {}
        self._loaded_shards: dict[str, HybridRetriever] = {}
        self._runtime_entries: list[dict] = []
        self.last_route_meta: dict = {}

        self._load_kb()

    def _assign_entry_id(self, entry: dict, fallback_index: int) -> dict:
        assigned = dict(entry)
        if "_id" not in assigned and "id" not in assigned:
            assigned["_id"] = f"runtime:{fallback_index}"
        elif "_id" not in assigned and "id" in assigned:
            assigned["_id"] = assigned.get("id")
        return assigned

    def _index_entries(self, entries: list[dict]):
        indexed = []
        entry_by_id: dict[str, dict] = {}
        entries_by_shard: dict[str, list[dict]] = {}
        shard_categories: dict[str, set] = {}

        for idx, entry in enumerate(entries):
            assigned = self._assign_entry_id(entry, idx)
            indexed.append(assigned)
            entry_by_id[str(assigned.get("_id"))] = assigned
            shard_name = _entry_shard_name(assigned)
            entries_by_shard.setdefault(shard_name, []).append(assigned)
            shard_categories.setdefault(shard_name, set()).add(
                str(assigned.get("category", "") or "").lower()
            )

        self._entries = indexed
        self._entry_by_id = entry_by_id
        self._entries_by_shard = entries_by_shard
        self._shard_categories = shard_categories
        self._loaded_shards = {}

    def _load_kb(self):
        if not os.path.exists(self.kb_path):
            self._index_entries([])
            return
        try:
            with open(self.kb_path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                entries = data
            elif isinstance(data, dict) and "entries" in data:
                entries = data["entries"]
            else:
                entries = []
        except Exception as e:
            print(f"[QueryAwareShardRetriever] Failed to load KB: {e}")
            entries = []
        self._index_entries(list(entries) + list(self._runtime_entries))

    def _eligible_shards(
        self,
        category_filter: str | None = None,
        include_categories: list[str] | None = None,
        exclude_categories: list[str] | None = None,
    ) -> list[str]:
        include_set = {str(cat).lower() for cat in (include_categories or []) if str(cat).strip()}
        exclude_set = {str(cat).lower() for cat in (exclude_categories or []) if str(cat).strip()}
        category_name = str(category_filter or "").lower().strip()

        eligible = []
        for shard_name in SHARD_PRIORITY_ORDER:
            shard_categories = self._shard_categories.get(shard_name, set())
            if not shard_categories:
                continue
            if category_name and category_name not in shard_categories:
                continue
            if include_set and not (shard_categories & include_set):
                continue
            if exclude_set and not (shard_categories - exclude_set):
                continue
            eligible.append(shard_name)

        for shard_name in self._entries_by_shard:
            if shard_name not in eligible:
                shard_categories = self._shard_categories.get(shard_name, set())
                if category_name and category_name not in shard_categories:
                    continue
                if include_set and not (shard_categories & include_set):
                    continue
                if exclude_set and not (shard_categories - exclude_set):
                    continue
                eligible.append(shard_name)
        return eligible

    def _get_shard_retriever(self, shard_name: str) -> HybridRetriever | None:
        retriever = self._loaded_shards.get(shard_name)
        if retriever is not None:
            return retriever
        entries = self._entries_by_shard.get(shard_name) or []
        if not entries:
            return None
        retriever = HybridRetriever(
            kb_path=f"{self.kb_path}#{shard_name}",
            entries=entries,
            embed_fn=self.embed_fn,
            hybrid_weight=self.hybrid_weight,
            min_score=self.min_score,
            enable_rerank=self.enable_rerank,
            prefetch_embeddings=self.shard_prefetch_embeddings,
        )
        self._loaded_shards[shard_name] = retriever
        return retriever

    @staticmethod
    def _result_identity(entry: dict) -> str:
        if entry.get("id") is not None:
            return str(entry.get("id"))
        if entry.get("_id") is not None:
            return str(entry.get("_id"))
        return json.dumps(
            (
                entry.get("title", ""),
                entry.get("category", ""),
                entry.get("_source", ""),
            ),
            sort_keys=True,
            default=str,
        )

    def _merge_results(
        self,
        shard_results: list[tuple[str, list[dict]]],
        top_k: int,
        include_live_scene: str | None = None,
    ) -> list[dict]:
        merged: dict[str, dict] = {}
        for shard_rank, (_shard_name, results) in enumerate(shard_results):
            # Each shard normalises its own scores, so route priority needs to
            # do the cross-shard calibration work.
            shard_boost = max(0.0, 0.85 - (0.25 * shard_rank))
            for entry in results:
                key = self._result_identity(entry)
                candidate = dict(entry)
                candidate["_score"] = round(float(candidate.get("_score", 0.0)) + shard_boost, 4)
                existing = merged.get(key)
                if existing is None or candidate.get("_score", 0.0) > existing.get("_score", 0.0):
                    merged[key] = candidate

        ordered = sorted(
            merged.values(),
            key=lambda item: item.get("_score", 0.0),
            reverse=True,
        )

        results = []
        if include_live_scene:
            results.append(
                {
                    "id": "live_scene",
                    "title": "Current Houdini Scene",
                    "category": "live",
                    "content": include_live_scene,
                    "_score": 1.0,
                }
            )
        results.extend(ordered[:top_k])
        return results

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        min_score: float | None = None,
        include_live_scene: str | None = None,
        category_filter: str | None = None,
        include_categories: list[str] | None = None,
        exclude_categories: list[str] | None = None,
        include_memory: bool = True,
        difficulty_filter: str | None = None,
        max_performance_impact: str | None = None,
        prefer_performant: bool = False,
        **kwargs,
    ) -> list[dict]:
        if not self._entries:
            return []

        min_score = min_score if min_score is not None else self.min_score
        eligible = self._eligible_shards(
            category_filter=category_filter,
            include_categories=include_categories,
            exclude_categories=exclude_categories,
        )
        routed = [name for name in _route_query_shards(query) if name in eligible]
        if not routed:
            routed = list(eligible)

        searched_shards = []
        shard_results: list[tuple[str, list[dict]]] = []

        # P1-D: Compound-query detection — queries that span two simulation domains
        # (e.g. RBD destruction + FLIP water) need more shards than the default 3
        # to retrieve content from both domains.
        _ql = query.lower()
        _is_rbd = any(
            t in _ql
            for t in ("rbd", "fracture", "bullet", "voronoi", "destruction", "shatter", "break")
        )
        _is_flip = any(t in _ql for t in ("flip", "fluid", "water", "liquid", "splash"))
        _is_pyro = any(t in _ql for t in ("pyro", "smoke", "fire", "combustion", "density"))
        _is_vellum = any(t in _ql for t in ("vellum", "cloth", "hair", "grain", "soft body"))
        _sim_domains_hit = sum([_is_rbd, _is_flip, _is_pyro, _is_vellum])
        shard_limit = min(
            len(routed),
            self.max_shards_per_query + (2 if _sim_domains_hit >= 2 else 0),
        )
        local_top_k = max(top_k * 2, 6)

        for shard_name in routed[:shard_limit]:
            retriever = self._get_shard_retriever(shard_name)
            if retriever is None:
                continue
            searched_shards.append(shard_name)
            results = retriever.retrieve(
                query=query,
                top_k=local_top_k,
                min_score=min_score,
                include_live_scene=None,
                category_filter=category_filter,
                include_categories=include_categories,
                exclude_categories=exclude_categories,
                include_memory=include_memory,
                difficulty_filter=difficulty_filter,
                max_performance_impact=max_performance_impact,
                prefer_performant=prefer_performant,
                **kwargs,
            )
            if results:
                shard_results.append((shard_name, results))

        merged = self._merge_results(
            shard_results,
            top_k=top_k,
            include_live_scene=include_live_scene,
        )

        if len([item for item in merged if item.get("id") != "live_scene"]) < top_k:
            for shard_name in eligible:
                if shard_name in searched_shards:
                    continue
                retriever = self._get_shard_retriever(shard_name)
                if retriever is None:
                    continue
                searched_shards.append(shard_name)
                results = retriever.retrieve(
                    query=query,
                    top_k=local_top_k,
                    min_score=min_score,
                    include_live_scene=None,
                    category_filter=category_filter,
                    include_categories=include_categories,
                    exclude_categories=exclude_categories,
                    include_memory=include_memory,
                    difficulty_filter=difficulty_filter,
                    max_performance_impact=max_performance_impact,
                    prefer_performant=prefer_performant,
                    **kwargs,
                )
                if results:
                    shard_results.append((shard_name, results))
                    merged = self._merge_results(
                        shard_results,
                        top_k=top_k,
                        include_live_scene=include_live_scene,
                    )
                if len([item for item in merged if item.get("id") != "live_scene"]) >= top_k:
                    break

        self.last_route_meta = {
            "query": query,
            "eligible_shards": eligible,
            "selected_shards": routed[:shard_limit],
            "searched_shards": searched_shards,
            "loaded_shards": list(self._loaded_shards.keys()),
        }
        return merged

    def get_chunk(self, cid) -> dict | None:
        entry = self._entry_by_id.get(str(cid))
        if not entry:
            return None
        result = dict(entry)
        result["id"] = result.get("_id", cid)
        return result

    def retrieve_by_category(self, category: str, top_k: int = 10) -> list[dict]:
        category_name = str(category or "").lower()
        return [
            dict(entry)
            for entry in self._entries
            if str(entry.get("category", "")).lower() == category_name
        ][:top_k]

    def add_entry(self, entry: dict):
        self.extend_entries([entry])

    def extend_entries(self, entries: list[dict]):
        if not entries:
            return
        self._runtime_entries.extend(dict(entry) for entry in entries)
        combined = list(self._entries) + list(entries)
        self._index_entries(combined)

    def reload(self):
        self._load_kb()
