# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
import difflib
import json
import logging
import time
from functools import lru_cache

logger = logging.getLogger("houdinimind.interceptor")
logger.setLevel(logging.INFO)
# Avoid basicConfig which sets up the root logger and might print to stdout
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    logger.addHandler(handler)


class HoudiniPipelineInterceptor:
    """
    Production-grade interceptor for validating Nodes and their specific Parameters.
    Uses difflib.get_close_matches for zero-dependency fuzzy matching string distance.
    """

    def __init__(self, schema_path: str, match_threshold: float = 0.6):
        # Lowered from 0.7 → 0.6 to catch more near-misses (e.g. "transform" → "xform" still
        # requires the alias table, but "attrib_wrangle" → "attribwrangle" now matches).
        self.match_threshold = match_threshold

        self._node_lists_by_context: dict[str, list[str]] = {}
        self._parm_lists_by_node: dict[str, list[str]] = {}
        # Flat set of ALL known node type strings (all contexts combined) for broad search.
        self._all_node_types: list[str] = []
        self.ready = False

        self._load_schema(schema_path)

    def _load_schema(self, path: str) -> None:
        try:
            start_time = time.perf_counter()
            with open(path, encoding="utf-8") as f:
                schema_data = json.load(f)

            for context, nodes in schema_data.items():
                self._node_lists_by_context[context] = list(nodes.keys())
                for node_name, node_data in nodes.items():
                    self._parm_lists_by_node[node_name] = node_data.get("parameters", [])

            # Build the flat all-types list once
            seen = set()
            for types in self._node_lists_by_context.values():
                for t in types:
                    if t not in seen:
                        seen.add(t)
                        self._all_node_types.append(t)

            elapsed = (time.perf_counter() - start_time) * 1000
            logger.info(
                f"Loaded full node/parameter schema in {elapsed:.2f}ms ({len(self._all_node_types)} node types)."
            )
            self.ready = True
        except Exception as e:
            logger.warning(f"Could not load schema from {path}: {e}")
            self.ready = False

    @lru_cache(maxsize=4096)
    def validate_entity(self, guess: str, valid_pool: tuple) -> tuple[bool, str | None]:
        """
        Generic high-speed validator for either a node or a parameter.
        Uses a tuple for valid_pool to allow LRU caching.
        """
        if not guess:
            return False, None

        guess_lower = guess.lower()
        if guess_lower in valid_pool:
            return True, guess_lower

        matches = difflib.get_close_matches(
            guess_lower, valid_pool, n=1, cutoff=self.match_threshold
        )

        if matches:
            return True, matches[0]

        return False, None

    def suggest_node_types(self, query: str, context: str = "", n: int = 5) -> list[str]:
        """
        Return up to n candidate node type strings for a given query.
        Searches the context-specific pool first, then falls back to all types.
        Uses a lower cutoff (0.5) than validate_entity so more candidates surface.
        """
        if not self.ready or not query:
            return []
        query_lower = query.lower().strip()

        # Build search pool: context-specific first, then all types
        if context:
            pool = list(self._node_lists_by_context.get(context.title(), []))
            if not pool:
                for ctx_key in self._node_lists_by_context:
                    if ctx_key.lower() == context.lower():
                        pool = list(self._node_lists_by_context[ctx_key])
                        break
        else:
            pool = []

        if not pool:
            pool = self._all_node_types

        # Exact prefix match first (fast path)
        prefix_matches = [t for t in pool if t.startswith(query_lower)]
        fuzzy_matches = difflib.get_close_matches(query_lower, pool, n=n + 2, cutoff=0.5)

        # Merge: prefix hits first, then fuzzy, deduplicated
        seen: set = set()
        results: list[str] = []
        for t in prefix_matches + fuzzy_matches:
            if t not in seen:
                seen.add(t)
                results.append(t)
            if len(results) >= n:
                break
        return results

    def suggest_parm_names(self, node_type: str, query: str, n: int = 5) -> list[str]:
        """
        Return up to n candidate parameter name strings for a given node type + query.
        Falls back to schema parm list when the live node isn't accessible.
        """
        if not self.ready or not query:
            return []
        query_lower = query.lower().strip()
        node_lower = node_type.lower().strip() if node_type else ""
        parm_pool = self._parm_lists_by_node.get(node_lower, [])
        if not parm_pool:
            return []

        prefix_matches = [p for p in parm_pool if p.startswith(query_lower)]
        fuzzy_matches = difflib.get_close_matches(query_lower, parm_pool, n=n + 2, cutoff=0.5)

        seen: set = set()
        results: list[str] = []
        for p in prefix_matches + fuzzy_matches:
            if p not in seen:
                seen.add(p)
                results.append(p)
            if len(results) >= n:
                break
        return results

    def validate_node(self, context: str, ai_node: str) -> tuple[bool, str | None]:
        if not self.ready:
            return True, ai_node  # Fallback to trusting the AI if schema missing

        context_nodes = tuple(self._node_lists_by_context.get(context.title(), []))
        if not context_nodes:
            for ctx_key in self._node_lists_by_context:
                if ctx_key.lower() == context.lower():
                    context_nodes = tuple(self._node_lists_by_context[ctx_key])
                    break

        if not context_nodes:
            # Unknown context — trust the AI
            return True, ai_node

        ai_lower = (ai_node or "").lower().strip()
        # If the guess is a valid type in *some* context (just not this one),
        # return it unchanged so the caller surfaces a real "wrong parent
        # context" error instead of silently substituting an unrelated type.
        # Without this, e.g. object_merge inside a dopnet fuzzy-matched to
        # smokeobject_sparse, which the agent then trusted.
        if ai_lower and ai_lower in {t.lower() for t in self._all_node_types}:
            if ai_lower not in context_nodes:
                return False, None

        node_ok, safe_node = self.validate_entity(ai_node, context_nodes)
        return node_ok, safe_node

    def validate_parameter(self, safe_node: str, ai_parm: str) -> tuple[bool, str | None]:
        if not self.ready:
            return True, ai_parm

        node_parms = tuple(self._parm_lists_by_node.get(safe_node, []))
        if not node_parms:
            # No parameters registered for this node in the schema (or node unknown)
            return True, ai_parm

        parm_ok, safe_parm = self.validate_entity(ai_parm, node_parms)
        return parm_ok, safe_parm
