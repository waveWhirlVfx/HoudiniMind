# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
"""
HoudiniMind RAG — Package
Hybrid retrieval-augmented generation for Houdini.
"""

from .bm25 import BM25
from .eval_harness import evaluate_retriever, load_eval_cases, run_retrieval_eval
from .injector import ContextInjector
from .kb_builder import (
    _load_high_fidelity_knowledge,
    _load_houdini_python_function_knowledge,
    _load_node_chain_training_data,
    _load_vex_function_db_knowledge,
    build_kb,
    rebuild_kb_from_session_feedback,
)
from .retriever import HybridRetriever, QueryAwareShardRetriever


def _runtime_entry_key(entry: dict):
    return (
        entry.get("_source"),
        entry.get("_chain_id"),
        entry.get("_asset_name"),
        entry.get("_source_path"),
        entry.get("title"),
    )


def _knowledge_base_path(data_dir: str) -> str:
    import os

    primary = os.path.join(data_dir, "knowledge", "knowledge_base.json")
    generated = os.path.join(data_dir, "knowledge", "knowledge_base.generated.json")
    if os.path.exists(generated):
        if (not os.path.exists(primary)) or os.path.getmtime(generated) >= os.path.getmtime(
            primary
        ):
            return generated
    return primary


def _ensure_knowledge_base(data_dir: str) -> str:
    import os

    kb_path = _knowledge_base_path(data_dir)
    if os.path.exists(kb_path):
        return kb_path
    try:
        build_kb(output_path=kb_path, verbose=False)
    except Exception:
        pass
    return kb_path


def _build_embed_fn(config: dict):
    cfg = config or {}
    if not cfg.get("rag_hybrid_search", True):
        return None
    shared_embed_fn = cfg.get("_shared_embed_fn")
    if callable(shared_embed_fn):
        return shared_embed_fn
    try:
        from ..agent.llm_client import OllamaClient

        client = OllamaClient(cfg)
    except Exception:
        return None

    embed_model = cfg.get("model_routing", {}).get("embedding") or cfg.get("embed_model")

    def _embed(text: str):
        return client.embed(text, model=embed_model)

    return _embed


def create_rag_pipeline(data_dir: str, config: dict | None = None) -> ContextInjector:
    """
    Factory: build the full RAG pipeline from a data directory.
    Returns a ready-to-use ContextInjector.

    Usage in AgentLoop:
        injector = create_rag_pipeline(data_dir, config)
        augmented_messages = injector.inject_into_messages(messages, user_query)
    """
    cfg = config or {}
    kb_path = _ensure_knowledge_base(data_dir)
    hybrid_weight = cfg.get(
        "rag_hybrid_weight",
        0.4 if cfg.get("rag_hybrid_search", True) else 0.0,
    )
    if cfg.get("rag_query_routing", True):
        retriever = QueryAwareShardRetriever(
            kb_path=kb_path,
            embed_fn=_build_embed_fn(cfg),
            hybrid_weight=hybrid_weight,
            min_score=cfg.get("rag_min_score", 0.1),
            enable_rerank=cfg.get("rag_enable_rerank", True),
            max_shards_per_query=cfg.get("rag_max_shards_per_query", 3),
            shard_prefetch_embeddings=cfg.get("rag_prefetch_shard_embeddings", False),
        )
    else:
        retriever = HybridRetriever(
            kb_path=kb_path,
            embed_fn=_build_embed_fn(cfg),
            hybrid_weight=hybrid_weight,
            min_score=cfg.get("rag_min_score", 0.1),
            enable_rerank=cfg.get("rag_enable_rerank", True),
        )
    existing_keys = {_runtime_entry_key(entry) for entry in getattr(retriever, "_entries", [])}
    runtime_entries = []
    for entry in _load_node_chain_training_data():
        key = _runtime_entry_key(entry)
        if key not in existing_keys:
            runtime_entries.append(entry)
            existing_keys.add(key)
    for entry in _load_high_fidelity_knowledge():
        key = _runtime_entry_key(entry)
        if key not in existing_keys:
            runtime_entries.append(entry)
            existing_keys.add(key)
    for entry in _load_houdini_python_function_knowledge(data_dir):
        key = _runtime_entry_key(entry)
        if key not in existing_keys:
            runtime_entries.append(entry)
            existing_keys.add(key)
    for entry in _load_vex_function_db_knowledge(data_dir):
        key = _runtime_entry_key(entry)
        if key not in existing_keys:
            runtime_entries.append(entry)
            existing_keys.add(key)
    retriever.extend_entries(runtime_entries)

    injector = ContextInjector(
        retriever=retriever,
        max_context_tokens=cfg.get("rag_max_context_tokens", 3000),
        top_k=cfg.get("rag_top_k", 4),
        min_score=cfg.get("rag_min_score", 0.1),
        model_name=cfg.get("model", ""),
    )
    return injector


__all__ = [
    "BM25",
    "ContextInjector",
    "HybridRetriever",
    "QueryAwareShardRetriever",
    "build_kb",
    "create_rag_pipeline",
    "evaluate_retriever",
    "load_eval_cases",
    "rebuild_kb_from_session_feedback",
    "run_retrieval_eval",
]
