# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
"""
HoudiniMind RAG — Context Injector
Formats retrieved knowledge chunks into a structured context block
that gets prepended to the LLM messages before the user's question.

The injector is responsible for:
  1. Deduplication (no duplicate chunks across turns)
  2. Context window budgeting (don't overflow the model's context)
  3. Formatting chunks clearly so the LLM knows what is injected knowledge
  4. Injecting live scene state at the right priority
"""

import re
from typing import List, Optional

# Maximum tokens to spend on injected context (leave room for conversation)
DEFAULT_MAX_CONTEXT_TOKENS = 3000

# Technical terms used for query complexity estimation
_TECHNICAL_TERMS = re.compile(
    r"\b("
    r"vex|vop|sop|dop|cop|rop|lop|chop|"
    r"hda|otl|wrangle|solver|"
    r"pyro|flip|vellum|rbd|bullet|grain|pop|"
    r"mantra|karma|redshift|octane|"
    r"attribute|prim|point|vertex|detail|"
    r"simulation|sim|scatter|foreach|"
    r"subnet|null|merge|switch|"
    r"obj|geo|mat|shop"
    r")\b",
    re.IGNORECASE,
)
_COMPLEX_KEYWORDS = re.compile(
    r"\b(workflow|pipeline|setup|complete|full)\b", re.IGNORECASE
)

_BUILD_GOAL_FALLBACKS = {
    "cup": ["mug", "tea cup"],
    "mug": ["cup", "tea cup"],
    "chair": ["kitchen chair", "dining chair", "seat"],
    "table": ["dining table", "coffee table", "four-legged table"],
    "lamp": ["floor lamp", "desk lamp", "street lamp"],
    "bottle": ["wine bottle"],
    "bed": ["mattress", "pillow", "bed frame"],
    "sofa": ["couch", "sofa"],
    "couch": ["sofa", "couch"],
    "house": ["room", "building"],
    "tree": ["branch", "trunk"],
}

_BUILD_SCAFFOLD_TEXT = (
    "Procedural build scaffold for small models:\n"
    "1. Create or confirm the correct container network first.\n"
    "2. Build the main silhouette with a small, reliable node chain.\n"
    "3. Add supporting nodes for shape, detail, and controllability.\n"
    "4. End in a clear visible OUT/null/output node.\n"
    "5. For recognizable objects, do not stop at a single primitive."
)


class ContextInjector:
    def __init__(
        self,
        retriever,
        max_context_tokens: int = DEFAULT_MAX_CONTEXT_TOKENS,
        top_k: int = 4,
        min_score: float = 0.1,
        model_name: str = "",
        debug_logger=None,
    ):
        from ..agent.llm_client import chars_per_token_for_model

        self.retriever = retriever
        self.max_context_tokens = max_context_tokens
        self.top_k = top_k
        self.min_score = min_score
        self.model_name = model_name or ""
        self._chars_per_token = chars_per_token_for_model(self.model_name)
        self._session_chunk_ids: set = set()
        self._turn_chunk_ids: set = set()
        self.last_context_meta: dict = {}
        self.debug_logger = debug_logger  # optional, set after construction

    # ------------------------------------------------------------------
    # Query complexity estimation
    # ------------------------------------------------------------------

    def _estimate_query_complexity(self, query: str) -> str:
        """Return 'simple', 'medium', or 'complex' based on query length and content."""
        words = query.split()
        word_count = len(words)

        # Detect technical domains present
        tech_matches = set(m.group(0).lower() for m in _TECHNICAL_TERMS.finditer(query))
        # Group matches into broad domains
        _sim_terms = {"pyro", "flip", "vellum", "rbd", "bullet", "grain", "pop", "dop", "simulation", "sim", "solver"}
        _vex_terms = {"vex", "vop", "wrangle"}
        _render_terms = {"mantra", "karma", "redshift", "octane", "rop"}
        domains_hit = set()
        for t in tech_matches:
            if t in _sim_terms:
                domains_hit.add("simulation")
            elif t in _vex_terms:
                domains_hit.add("vex")
            elif t in _render_terms:
                domains_hit.add("render")
            else:
                domains_hit.add("general_tech")

        has_complex_keywords = bool(_COMPLEX_KEYWORDS.search(query))
        multiple_domains = len(domains_hit) >= 2

        # Complex: long query, multi-domain, or workflow-style keywords
        if word_count > 20 or multiple_domains or has_complex_keywords:
            return "complex"

        # Simple: short query with no technical terms
        if word_count < 8 and not tech_matches:
            if re.search(r"\b(create|build|make|design|construct|generate|model|sculpt)\b", query, re.IGNORECASE):
                return "medium"
            return "simple"

        return "medium"

    def _build_fallback_queries(self, query: str, request_mode: str) -> List[str]:
        if str(request_mode or "").lower() != "build":
            return []
        query = str(query or "").strip()
        if not query:
            return []

        lower = query.lower()
        variants: List[str] = []

        def add_variant(text: str):
            candidate = str(text or "").strip()
            if candidate and candidate not in variants:
                variants.append(candidate)

        add_variant(f"{query} workflow")
        add_variant(f"{query} node chain")
        add_variant(f"{query} procedural")
        add_variant(f"{query} high fidelity")
        add_variant(f"{query} recipe")

        for term, aliases in _BUILD_GOAL_FALLBACKS.items():
            if term in lower:
                for alias in aliases:
                    add_variant(f"{alias} workflow")
                    add_variant(f"{alias} node chain")
                    add_variant(f"{alias} procedural high fidelity")
        return variants

    # ── Technical synonym map for query enrichment ───────────────────
    _TECH_SYNONYMS: dict = {
        # SOP node aliases
        "extrude":        ["polyextrude", "poly extrude"],
        "bevel":          ["polybevel", "poly bevel", "chamfer"],
        "copy":           ["copytopoints", "copy to points", "instance"],
        "instance":       ["copytopoints", "pack", "copy to points"],
        "scatter":        ["scatter sop", "points on surface", "distribute"],
        "vdb":            ["vdb from polygons", "volume", "sdf"],
        "subdivide":      ["catmull clark", "subdivision surface", "subdivide sop"],
        "smooth":         ["smooth sop", "relax", "laplacian smooth"],
        "noise":          ["mountain", "attribwrangle noise", "displacement"],
        "boolean":        ["boolean sop", "csg", "subtract", "union", "intersect"],
        "sweep":          ["sweep sop", "profile along curve", "tube along path"],
        "fracture":       ["voronoi fracture", "rbd fracture", "boolean fracture"],
        "deform":         ["bend sop", "lattice", "wire deform", "softxform"],
        "uv":             ["uvunwrap", "uv layout", "texture coordinates", "uv project"],
        "material":       ["materialx", "assign material", "shop", "principled shader"],
        # Common build task synonyms
        "legs":           ["support geometry", "vertical elements", "pillars", "struts"],
        "frame":          ["border geometry", "edge loop", "outline"],
        "trim":           ["edge loop", "border", "panel edge"],
        "joint":          ["weld", "connection point", "merge geometry"],
        "pipe":           ["tube", "cylinder", "conduit", "polywire"],
        "wire":           ["polywire", "curve", "tube", "cable"],
        "curve":          ["bezier curve", "nurbs", "spline", "path"],
        "path":           ["curve", "spine", "guide"],
    }

    def _enrich_query(self, query: str, request_mode: Optional[str]) -> List[str]:
        """
        Produce enriched variants of *query* by:
          1. Appending domain context words (sop, houdini, node, workflow)
          2. Substituting known technical synonyms
          3. Extracting key noun phrases and searching for them standalone

        Returns a list of enriched query strings (no duplicates, ordered by
        expected relevance).
        """
        q = str(query or "").strip()
        if not q:
            return []
        ql = q.lower()
        mode = str(request_mode or "").lower()
        enriched: list[str] = []

        def _add(text: str):
            t = text.strip()
            if t and t != q and t not in enriched:
                enriched.append(t)

        # 1. Context word expansions
        if mode in ("build", "debug"):
            _add(f"{q} houdini sop")
            _add(f"{q} node network")
        if mode == "debug":
            _add(f"{q} error fix")
            _add(f"{q} troubleshoot")

        # 2. Synonym substitutions
        for term, synonyms in self._TECH_SYNONYMS.items():
            if term in ql:
                for syn in synonyms[:2]:
                    _add(q.lower().replace(term, syn, 1))

        # 3. Extract key 2–3 word technical noun phrases and search standalone
        #    e.g. "how do I make a procedural railing?" → "procedural railing"
        import re as _re
        noun_phrases = _re.findall(
            r"\b(?:procedural\s+\w+|sop\s+\w+|\w+\s+workflow|\w+\s+recipe|"
            r"\w+\s+network|\w+\s+node|\w+\s+sop)\b",
            ql,
        )
        for phrase in noun_phrases[:3]:
            _add(phrase)

        return enriched[:8]  # cap to avoid excessive retrieval rounds

    @staticmethod
    def _build_scaffold_chunk(query: str) -> dict:
        return {
            "id": "build_scaffold",
            "title": "Small-Model Build Scaffold",
            "category": "workflow",
            "content": _BUILD_SCAFFOLD_TEXT,
            "_score": 0.15,
            "_source": "internal_scaffold",
        }

    # ------------------------------------------------------------------
    # Main inject method
    # ------------------------------------------------------------------

    def build_context_message(
        self,
        query: str,
        request_mode: Optional[str] = None,
        live_scene_json: Optional[str] = None,
        force_chunks: Optional[List[str]] = None,  # chunk IDs to always include
        include_categories: Optional[List[str]] = None,
        exclude_categories: Optional[List[str]] = None,
        include_memory: bool = True,
    ) -> Optional[dict]:
        """
        Build a system-level context message dict for injection into the
        LLM messages list.

        Returns None if no relevant context is found.
        Returns {"role": "system", "content": "..."} otherwise.
        """
        # P1-B: VEX bypass — pure "write VEX to do X" queries that the LLM handles
        # without RAG.  Restricts to vex_reference shard only (function signatures
        # are still useful); trivial remaps/sets skip retrieval entirely.
        _TRIVIAL_VEX_RE = re.compile(
            r"\b(write|create|make|generate)\s+a?\s*(vex|wrangle)\s+\w+\s+"
            r"(to|that|for)\s+(set|get|remap|fit|normalize|add|multiply|copy|"
            r"transfer|read|write|compute|calculate)\b",
            re.IGNORECASE,
        )
        _VEX_ONLY_RE = re.compile(
            r"(@[A-Za-z_]\w*|\b(vex|wrangle|attribwrangle|snippet)\b)",
            re.IGNORECASE,
        )
        query_words = query.split()
        _is_vex_query = bool(_VEX_ONLY_RE.search(query))
        _is_trivial_vex = bool(_TRIVIAL_VEX_RE.search(query)) and len(query_words) < 22
        if _is_trivial_vex and not include_categories:
            return None
        if _is_vex_query and not include_categories:
            include_categories = ["vex"]

        # Dynamic budget based on query complexity
        complexity = self._estimate_query_complexity(query)
        if str(request_mode or "").lower() == "build" and complexity == "simple":
            complexity = "medium"
        # P1-A: raised from 0.3/0.6/1.0 — context window has ample headroom (21K+
        # tokens free after system prompt + tools + history) so a tight 2K cap
        # was leaving complex multi-step FX tasks under-informed.
        budget_map = {"simple": 0.35, "medium": 0.65, "complex": 1.0}
        effective_budget = int(self.max_context_tokens * budget_map[complexity])

        top_k_map = {"simple": 2, "medium": 4, "complex": 6}
        effective_top_k = top_k_map[complexity]

        # ── Primary retrieval ────────────────────────────────────────────
        chunks = self.retriever.retrieve(
            query=query,
            top_k=effective_top_k,
            min_score=self.min_score,
            include_live_scene=live_scene_json,
            include_categories=include_categories,
            exclude_categories=exclude_categories,
            include_memory=include_memory,
        )
        initial_count = len(chunks)

        has_workflow_chunk = any(
            str(c.get("category", "")).lower() == "workflow" for c in chunks
        )

        # ── Query enrichment: expand weak primary results ────────────────
        # If the primary query returns fewer chunks than expected or is missing
        # a workflow chunk for a BUILD request, we enrich the query using
        # domain synonyms and structural expansions before falling back.
        _fallback_queries_tried = []
        weak_primary = len(chunks) < max(2, effective_top_k // 2)
        needs_workflow = (
            str(request_mode or "").lower() == "build" and not has_workflow_chunk
        )

        if not chunks or weak_primary or needs_workflow:
            # Build enriched + fallback queries
            enriched = self._enrich_query(query, request_mode)
            fallback_queries = enriched + self._build_fallback_queries(query, request_mode)

            for fallback_query in fallback_queries:
                alt_chunks = self.retriever.retrieve(
                    query=fallback_query,
                    top_k=effective_top_k,
                    min_score=max(0.03, self.min_score * 0.75),
                    include_live_scene=live_scene_json,
                    include_categories=include_categories,
                    exclude_categories=exclude_categories,
                    include_memory=include_memory,
                    use_rerank=False,
                )
                new_added = 0
                for c in alt_chunks:
                    cid = c.get("id", "")
                    if cid == "live_scene":
                        continue
                    if any(existing.get("id") == cid for existing in chunks):
                        continue
                    chunks.append(c)
                    new_added += 1
                _fallback_queries_tried.append(fallback_query)
                has_workflow_chunk = has_workflow_chunk or any(
                    str(c.get("category", "")).lower() == "workflow" for c in alt_chunks
                )
                # Stop once we have enough chunks and a workflow chunk
                if len(chunks) >= effective_top_k and (
                    not needs_workflow or has_workflow_chunk
                ):
                    break

        # Force-include specific chunks (e.g. always include VEX basics if VEX detected)
        if force_chunks:
            existing_ids = {c["id"] for c in chunks}
            for cid in force_chunks:
                if cid not in existing_ids:
                    extra = self.retriever.get_chunk(cid)
                    if extra:
                        chunks.append(extra)

        if not chunks:
            if str(request_mode or "").lower() == "build":
                chunks = [self._build_scaffold_chunk(query)]
            else:
                self.last_context_meta = {
                    "query": query,
                    "initial_count": initial_count,
                    "used_count": 0,
                    "include_categories": include_categories or [],
                    "exclude_categories": exclude_categories or [],
                    "include_memory": include_memory,
                    "had_live_scene": bool(live_scene_json),
                    "chunk_titles": [],
                    "chunk_categories": [],
                    "chunk_scores": [],
                    "estimated_tokens": 0,
                }
                return None

        if not chunks:
            self.last_context_meta = {
                "query": query,
                "initial_count": initial_count,
                "used_count": 0,
                "include_categories": include_categories or [],
                "exclude_categories": exclude_categories or [],
                "include_memory": include_memory,
                "had_live_scene": bool(live_scene_json),
                "chunk_titles": [],
                "chunk_categories": [],
                "chunk_scores": [],
                "estimated_tokens": 0,
            }
            return None

        # P2-B: Confidence-ratio gate — skip injection when the best retrieval hit
        # is weak AND close to the second hit (low discrimination = noise risk).
        # Live-scene chunks are exempt; build mode skips the gate to keep scaffolds.
        _non_scene_chunks = [c for c in chunks if c.get("id") != "live_scene"]
        if (
            _non_scene_chunks
            and str(request_mode or "").lower() not in ("build",)
            and not force_chunks
            and not live_scene_json
        ):
            top_score = float(_non_scene_chunks[0].get("_score", 0))
            second_score = float(_non_scene_chunks[1].get("_score", 0)) if len(_non_scene_chunks) > 1 else 0.0
            confidence_ratio = top_score / (second_score + 1e-9)
            if top_score < 0.18 and confidence_ratio < 1.4:
                self.last_context_meta = {
                    "query": query,
                    "initial_count": initial_count,
                    "used_count": 0,
                    "gate": "confidence_ratio_failed",
                    "top_score": top_score,
                    "confidence_ratio": round(confidence_ratio, 3),
                    "estimated_tokens": 0,
                }
                return None

        # Deduplicate repeated chunks within the current turn.
        # Session-level dedup is reserved for explicitly sticky chunks only.
        pre_dedup_count = len(chunks)
        new_chunks = []
        dedup_dropped = 0
        for c in chunks:
            cid = c.get("id", "")
            if cid == "live_scene":
                new_chunks.append(c)
                continue
            is_sticky_session = bool(c.get("_sticky_session"))
            if cid and cid in self._turn_chunk_ids:
                dedup_dropped += 1
                continue
            if cid and is_sticky_session and cid in self._session_chunk_ids:
                dedup_dropped += 1
                continue
            new_chunks.append(c)
            if cid:
                self._turn_chunk_ids.add(cid)
                if is_sticky_session:
                    self._session_chunk_ids.add(cid)
        chunks = new_chunks
        if not chunks:
            self.last_context_meta = {
                "query": query,
                "initial_count": initial_count,
                "used_count": 0,
                "include_categories": include_categories or [],
                "exclude_categories": exclude_categories or [],
                "include_memory": include_memory,
                "had_live_scene": bool(live_scene_json),
                "chunk_titles": [],
                "chunk_categories": [],
                "chunk_scores": [],
                "estimated_tokens": 0,
            }
            return None

        # Build the context block
        content = self._format_chunks(chunks, query, max_tokens=effective_budget)
        estimated_tokens = self.estimate_tokens(content)
        # Brief content preview per chunk (first 120 chars) for debug visibility
        chunk_previews = [
            c.get("content", "")[:120].replace("\n", " ")
            for c in chunks[:10]
        ]
        self.last_context_meta = {
            "query": query,
            "query_complexity": complexity,
            "effective_budget_tokens": effective_budget,
            "initial_count": initial_count,
            "used_count": len(chunks),
            "dedup_dropped": dedup_dropped,
            "fallback_queries_tried": _fallback_queries_tried,
            "include_categories": include_categories or [],
            "exclude_categories": exclude_categories or [],
            "include_memory": include_memory,
            "had_live_scene": bool(live_scene_json),
            "chunk_titles": [c.get("title", "") for c in chunks[:10]],
            "chunk_categories": [c.get("category", "") for c in chunks[:10]],
            "chunk_scores": [c.get("_score") for c in chunks[:10]],
            "chunk_ids": [c.get("id") for c in chunks[:10]],
            "chunk_previews": chunk_previews,
            "model_name": self.model_name,
            "estimated_tokens": estimated_tokens,
            "budget_pct_used": round(estimated_tokens / effective_budget * 100, 1) if effective_budget else None,
            "route_meta": getattr(self.retriever, "last_route_meta", {}),
            "fallback_queries": self._build_fallback_queries(query, request_mode),
        }
        if self.debug_logger:
            self.debug_logger.log_rag_detail({
                "query": query,
                "complexity": complexity,
                "budget_tokens": effective_budget,
                "initial_count": initial_count,
                "dedup_dropped": dedup_dropped,
                "fallback_queries_tried": _fallback_queries_tried,
                "used_count": len(chunks),
                "chunk_ids": [c.get("id") for c in chunks[:10]],
                "chunk_titles": [c.get("title", "") for c in chunks[:10]],
                "chunk_categories": [c.get("category", "") for c in chunks[:10]],
                "chunk_scores": [round(float(c.get("_score", 0)), 3) for c in chunks[:10]],
                "chunk_previews": chunk_previews,
                "estimated_tokens": estimated_tokens,
                "budget_pct_used": self.last_context_meta["budget_pct_used"],
                "had_live_scene": bool(live_scene_json),
            })
        return {"role": "system", "content": content}

    def inject_into_messages(
        self,
        messages: List[dict],
        query: str,
        live_scene_json: Optional[str] = None,
        include_categories: Optional[List[str]] = None,
        exclude_categories: Optional[List[str]] = None,
        include_memory: bool = True,
    ) -> List[dict]:
        """
        Insert the RAG context into a messages list at the correct position.
        Context is inserted right before the last user message so it's
        immediately relevant.

        Returns the augmented messages list.
        """
        ctx_msg = self.build_context_message(
            query,
            live_scene_json=live_scene_json,
            include_categories=include_categories,
            exclude_categories=exclude_categories,
            include_memory=include_memory,
        )
        if ctx_msg is None:
            return messages

        # Find insertion point: right before last user message
        insert_at = len(messages)
        for i in reversed(range(len(messages))):
            if messages[i].get("role") == "user":
                insert_at = i
                break

        result = list(messages)
        result.insert(insert_at, ctx_msg)
        return result

    def inject_prebuilt(
        self,
        messages: List[dict],
        prebuilt_msg: dict,
    ) -> List[dict]:
        """
        P2-A: Insert an already-built context message (from the prefetch thread)
        without re-running retrieval. Used by AgentLoop when the prefetch finished
        before the execution path reaches the inject site.
        """
        if not prebuilt_msg or not isinstance(prebuilt_msg, dict):
            return messages
        insert_at = len(messages)
        for i in reversed(range(len(messages))):
            if messages[i].get("role") == "user":
                insert_at = i
                break
        result = list(messages)
        result.insert(insert_at, prebuilt_msg)
        return result

    # ------------------------------------------------------------------
    # Formatting
    # ------------------------------------------------------------------

    def _format_chunks(
        self, chunks: List[dict], query: str, max_tokens: Optional[int] = None
    ) -> str:
        """
        Format retrieved chunks into a clear, structured context block
        that local LLMs can follow easily.
        """
        token_budget = max_tokens if max_tokens is not None else self.max_context_tokens
        budget_chars = int(token_budget * self._chars_per_token)
        used_chars = 0

        header = (
            "═══════════════════════════════════════════════════\n"
            "  HOUDINI KNOWLEDGE BASE — Retrieved for this query\n"
            "═══════════════════════════════════════════════════\n"
            "The following sections contain authoritative Houdini\n"
            "documentation relevant to the user's question.\n"
            "Use this knowledge to support accurate answers or build steps.\n"
            "Do not replace required scene actions with a generic summary.\n"
            "═══════════════════════════════════════════════════\n\n"
        )
        used_chars += len(header)

        section_texts = []
        for i, chunk in enumerate(chunks):
            # Skip live scene if it would overflow
            is_scene = chunk.get("id") == "live_scene"

            title = chunk.get("title", "")
            category = chunk.get("category", "")
            content = chunk.get("content", "").strip()
            score = chunk.get("_score", 0)

            if is_scene:
                # Truncate scene JSON to save budget
                max_scene_chars = int(budget_chars * 0.4)
                if len(content) > max_scene_chars:
                    # Find last complete JSON object boundary to avoid invalid JSON
                    truncated = content[:max_scene_chars]
                    last_brace = max(truncated.rfind('}'), truncated.rfind(']'))
                    if last_brace > max_scene_chars // 2:
                        content = truncated[:last_brace + 1] + "\n... [scene truncated for brevity]"
                    else:
                        content = truncated + "\n... [scene truncated for brevity]"
                section = (
                    f"▶ LIVE SCENE STATE (current Houdini session):\n"
                    f"{content}\n"
                )
            else:
                section = (
                    f"▶ [{category.upper()}] {title}\n"
                    f"{'─' * 50}\n"
                    f"{content}\n"
                )

            if used_chars + len(section) > budget_chars:
                # Truncate this chunk to fit
                remaining = budget_chars - used_chars - 100
                if remaining > 200:
                    section = section[:remaining] + "\n... [truncated]\n"
                    section_texts.append(section)
                break

            section_texts.append(section)
            used_chars += len(section)

        footer = (
            "\n═══════════════════════════════════════════════════\n"
            "  END OF KNOWLEDGE BASE CONTEXT\n"
            "═══════════════════════════════════════════════════\n"
        )

        return header + "\n".join(section_texts) + footer

    # ------------------------------------------------------------------
    # Context window estimation
    # ------------------------------------------------------------------

    def estimate_tokens(self, text: str) -> int:
        return int(len(text) / self._chars_per_token)

    def reset_turn(self):
        self._turn_chunk_ids.clear()

    def reset_session(self):
        """Clear seen chunk IDs between sessions."""
        self._session_chunk_ids.clear()
        self._turn_chunk_ids.clear()
