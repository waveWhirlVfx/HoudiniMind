# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
"""
HoudiniMind RAG — Pure Python BM25 (Okapi BM25)
Zero external dependencies. Works with Houdini's bundled Python 3.11.

BM25 is the gold standard for keyword-based retrieval — the same algorithm
behind Elasticsearch, Lucene, and most production search engines.
It beats simple TF-IDF because it:
  - Penalises extremely long documents (length normalisation)
  - Saturates term frequency (a word appearing 100x isn't 100x more relevant)
  - Weights rare terms higher (IDF component)
"""

import math
import re
from collections import Counter, defaultdict
from typing import List, Tuple, Dict


STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "do",
    "does",
    "for",
    "from",
    "give",
    "has",
    "have",
    "how",
    "in",
    "into",
    "is",
    "it",
    "me",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "use",
    "using",
    "what",
    "with",
}

MEANINGFUL_SINGLE_CHAR_TOKENS = {
    "x",
    "y",
    "z",
    "u",
    "v",
    "p",
    "n",
    "r",
    "g",
    "b",
}


class BM25:
    """
    Okapi BM25 retriever.

    k1 = 1.5  — term frequency saturation (1.2–2.0 typical)
    b  = 0.75 — length normalisation (0 = no normalisation, 1 = full)
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.corpus: List[List[str]] = []       # tokenised documents
        self.doc_freqs: List[Dict[str, int]] = []  # term freq per doc
        self.idf: Dict[str, float] = {}
        self.avgdl: float = 0.0
        self.N: int = 0

    # ──────────────────────────────────────────────────────────────────
    # Tokenisation
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _normalise_token(token: str) -> str:
        if token.endswith("ies") and len(token) > 4:
            return token[:-3] + "y"
        if (
            token.endswith("es")
            and len(token) > 4
            and not token.endswith(("ses", "xes", "zes", "ches", "shes"))
        ):
            return token[:-1]
        if (
            token.endswith("s")
            and len(token) > 3
            and not token.endswith(("ss", "us", "is"))
        ):
            return token[:-1]
        return token

    @staticmethod
    def tokenise(text: str) -> List[str]:
        """
        Split text into lowercase tokens.
        Handles CamelCase, snake_case, and Houdini-specific patterns
        like 'attribwrangle', 'dopnet', 'vellumconstraintproperty'.
        """
        # Insert space before uppercase runs (CamelCase → tokens)
        text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
        text = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", text)

        # Replace separators with space
        text = re.sub(r"[_\-/\\\.]+", " ", text)

        # Keep alphanumeric only
        raw_tokens = re.findall(r"[a-z0-9]+", text.lower())

        # Remove generic stopwords while preserving Houdini-significant
        # single-character axis/attribute tokens such as x/y/z/u/v/P/N.
        tokens = []
        for token in raw_tokens:
            if (
                len(token) == 1
                and not token.isdigit()
                and token not in MEANINGFUL_SINGLE_CHAR_TOKENS
            ):
                continue
            token = BM25._normalise_token(token)
            if token in STOPWORDS:
                continue
            tokens.append(token)
        return tokens

    # ──────────────────────────────────────────────────────────────────
    # Index building
    # ──────────────────────────────────────────────────────────────────

    def index(self, documents: List[str]):
        """Build the BM25 index from a list of document strings."""
        self.N = len(documents)
        self.corpus = [self.tokenise(doc) for doc in documents]
        self.doc_freqs = [Counter(tokens) for tokens in self.corpus]

        total_len = sum(len(tokens) for tokens in self.corpus)
        self.avgdl = total_len / self.N if self.N else 1.0

        # Document frequency: how many docs contain each term
        df: Dict[str, int] = defaultdict(int)
        for freq in self.doc_freqs:
            for term in freq:
                df[term] += 1

        # IDF with smoothing (Robertson IDF)
        self.idf = {}
        for term, freq in df.items():
            self.idf[term] = math.log(
                (self.N - freq + 0.5) / (freq + 0.5) + 1
            )

    def add_document(self, document: str):
        """Incrementally add one document and rebuild IDF."""
        tokens = self.tokenise(document)
        self.corpus.append(tokens)
        self.doc_freqs.append(Counter(tokens))
        self.N += 1
        total_len = sum(len(t) for t in self.corpus)
        self.avgdl = total_len / self.N

        # Rebuild IDF (fast enough for <50k docs)
        df: Dict[str, int] = defaultdict(int)
        for freq in self.doc_freqs:
            for term in freq:
                df[term] += 1
        for term, freq in df.items():
            self.idf[term] = math.log(
                (self.N - freq + 0.5) / (freq + 0.5) + 1
            )

    # ──────────────────────────────────────────────────────────────────
    # Scoring
    # ──────────────────────────────────────────────────────────────────

    def score(self, query: str, doc_idx: int) -> float:
        """Compute BM25 score for a single document."""
        query_tokens = self.tokenise(query)
        doc_len = len(self.corpus[doc_idx])
        freq = self.doc_freqs[doc_idx]
        score = 0.0

        for term in query_tokens:
            if term not in self.idf:
                continue
            tf = freq.get(term, 0)
            numerator = tf * (self.k1 + 1)
            denominator = tf + self.k1 * (
                1 - self.b + self.b * doc_len / self.avgdl
            )
            score += self.idf[term] * (numerator / denominator)

        return score

    def get_scores(self, query: str) -> List[float]:
        """Score all documents for a query."""
        return [self.score(query, i) for i in range(self.N)]

    # ──────────────────────────────────────────────────────────────────
    # Top-K retrieval
    # ──────────────────────────────────────────────────────────────────

    def top_k(self, query: str, k: int = 5,
              min_score: float = 0.1) -> List[Tuple[int, float]]:
        """
        Return (doc_index, score) pairs for the top-k documents.
        Filters out documents with score below min_score.
        """
        if not self.corpus:
            return []
        scores = [(i, self.score(query, i)) for i in range(self.N)]
        scores = [(i, s) for i, s in scores if s >= min_score]
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:k]
