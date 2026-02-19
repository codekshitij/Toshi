"""
RAG Step 5 — Retriever
Full retrieval pipeline: HyDE → MMR → CRAG → Reranking.

Flow: pipeline.py → retriever.py → store.py (for MMR search)
                                 → embedder.py (for CRAG scoring)

Rules from PIPELINE.md:
- HyDE failure must never crash — fall back to raw query
- CRAG must never return fewer than 2 chunks — relax thresholds if needed
- Final output is always top 5 chunks (or fewer if not enough data)
- Sub-steps in order: HyDE → MMR → CRAG → reranking
"""

import re
import sys
import os
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from rag import store, embedder
from sentence_transformers import CrossEncoder

# ─────────────────────────────────────────────
# Cross-encoder loaded once at module level
# ─────────────────────────────────────────────
RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"

print(f"Loading reranker model {RERANKER_MODEL}...", flush=True)
_reranker = CrossEncoder(RERANKER_MODEL)
print("Reranker model ready.", flush=True)

# CRAG thresholds
CRAG_CORRECT   = 0.7
CRAG_AMBIGUOUS = 0.3

# Final output size
TOP_K = 5


# ─────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────

def retrieve(query: str, cik: str, years: list) -> list:
    """
    Full retrieval pipeline per PIPELINE.md:
    1. HyDE  — expand query into SEC filing language (local, no API)
    2. MMR   — retrieve 20 diverse candidates across years
    3. CRAG  — self-critique, filter low quality chunks
    4. Rerank — cross-encoder precision scoring, return top 5
    """
    expanded_query = hyde_expand(query)
    candidates = retrieve_mmr(expanded_query, cik, years)
    if not candidates:
        return []
    filtered = crag_filter(query, candidates)
    final = rerank(query, filtered)
    return final


# ─────────────────────────────────────────────
# 5a — HyDE (local, no API key needed)
# ─────────────────────────────────────────────

def hyde_expand(query: str) -> str:
    """
    Expand query into SEC filing language locally — no API calls needed.

    Why: SEC filings use formal legal language. A conversational query
    won't match well against it. We expand by:
    1. Detecting topic from query keywords
    2. Prepending relevant SEC filing language patterns
    3. Appending extracted keywords

    This achieves most of the HyDE benefit without any API calls.
    """
    query_lower = query.lower()
    expansions = []

    if any(w in query_lower for w in ["risk", "risks", "danger", "threat"]):
        expansions.append(
            "The Company is subject to various risks and uncertainties that could "
            "materially adversely affect its business, financial condition, and results of operations."
        )

    if any(w in query_lower for w in ["china", "chinese", "asia", "international"]):
        expansions.append(
            "The Company's operations outside the United States are subject to risks "
            "associated with international operations including regulatory, political, "
            "and economic risks in foreign jurisdictions."
        )

    if any(w in query_lower for w in ["revenue", "sales", "income", "profit", "earnings"]):
        expansions.append(
            "Net revenues and operating income reflect the Company's financial performance "
            "across its reportable segments for the fiscal year ended."
        )

    if any(w in query_lower for w in ["debt", "borrow", "credit", "loan", "leverage"]):
        expansions.append(
            "The Company's indebtedness and credit facilities may limit its financial "
            "flexibility and ability to fund operations and capital expenditures."
        )

    if any(w in query_lower for w in ["competition", "competitor", "compete", "market"]):
        expansions.append(
            "The Company faces intense competition from existing and new market participants "
            "which may impact pricing, market share, and overall financial performance."
        )

    if any(w in query_lower for w in ["ai", "artificial intelligence", "technology", "innovation"]):
        expansions.append(
            "The Company continues to invest in research and development of emerging technologies "
            "including artificial intelligence to maintain competitive positioning."
        )

    if any(w in query_lower for w in ["supply", "chain", "supplier", "manufacturing"]):
        expansions.append(
            "The Company relies on third-party suppliers and manufacturers which exposes it "
            "to supply chain disruptions, component shortages, and quality control risks."
        )

    if any(w in query_lower for w in ["regulation", "regulatory", "compliance", "law", "legal"]):
        expansions.append(
            "The Company is subject to extensive government regulation across the jurisdictions "
            "in which it operates which may require significant compliance costs."
        )

    keywords = _extract_keywords(query)
    expanded_parts = [query]
    if expansions:
        expanded_parts.extend(expansions[:2])
    if keywords:
        expanded_parts.append(" ".join(keywords))

    return " ".join(expanded_parts)


# ─────────────────────────────────────────────
# 5b — MMR Retrieval
# ─────────────────────────────────────────────

def retrieve_mmr(expanded_query: str, cik: str, years: list,
                 n_results: int = 20) -> list:
    """
    Retrieve diverse chunks using MMR across all specified years.
    Searches each year separately then combines for cross-year diversity.
    """
    all_candidates = []

    for year in years:
        year_results = store.search_mmr(
            query=expanded_query,
            cik=cik,
            year=year,
            n_results=10,
            mmr_lambda=0.7,
        )
        all_candidates.extend(year_results)

    if not all_candidates:
        all_candidates = store.search_mmr(
            query=expanded_query,
            cik=cik,
            n_results=n_results,
            mmr_lambda=0.7,
        )

    return all_candidates[:n_results]


# ─────────────────────────────────────────────
# 5c — CRAG Self-Critique
# ─────────────────────────────────────────────

def crag_filter(query: str, chunks: list,
                correct_threshold: float = CRAG_CORRECT,
                ambiguous_threshold: float = CRAG_AMBIGUOUS) -> list:
    """
    Score each chunk for relevance. Self-correcting filter.
    Scoring: keyword overlap (40%) + embedding similarity (60%)

    CORRECT   (>0.7): keep full chunk
    AMBIGUOUS (0.3-0.7): extract only relevant sentences
    INCORRECT (<0.3): discard

    Relaxes thresholds if fewer than 2 chunks survive.
    """
    if not chunks:
        return []

    query_embedding = embedder.embed_text(query)
    query_keywords = _extract_keywords(query)

    scored = []
    for chunk in chunks:
        score = _crag_score(chunk, query_embedding, query_keywords)
        scored.append((score, chunk))

    result = _apply_crag_thresholds(
        scored, query_keywords, correct_threshold, ambiguous_threshold
    )

    if len(result) < 2:
        print("CRAG: relaxing thresholds...", file=sys.stderr)
        result = _apply_crag_thresholds(scored, query_keywords, 0.4, 0.15)

    if not result:
        result = [c for _, c in scored[:3]]

    return result


def _crag_score(chunk: dict, query_embedding: np.ndarray,
                query_keywords: list) -> float:
    """Score chunk: 60% embedding similarity + 40% keyword overlap."""
    text = chunk.get("text", "").lower()

    if query_keywords:
        keyword_hits = sum(1 for kw in query_keywords if kw in text)
        keyword_score = keyword_hits / len(query_keywords)
    else:
        keyword_score = 0.5

    chunk_embedding = embedder.embed_text(chunk.get("text", ""))
    similarity = float(np.dot(chunk_embedding, query_embedding))
    similarity = max(0.0, min(1.0, similarity))

    return 0.4 * keyword_score + 0.6 * similarity


def _apply_crag_thresholds(scored: list, query_keywords: list,
                            correct_threshold: float,
                            ambiguous_threshold: float) -> list:
    """Apply CRAG thresholds to scored chunks."""
    result = []
    for score, chunk in scored:
        if score >= correct_threshold:
            result.append(chunk)
        elif score >= ambiguous_threshold:
            trimmed = _extract_relevant_sentences(chunk["text"], query_keywords)
            if trimmed:
                trimmed_chunk = chunk.copy()
                trimmed_chunk["text"] = trimmed
                trimmed_chunk["crag_trimmed"] = True
                result.append(trimmed_chunk)
    return result


def _extract_relevant_sentences(text: str, keywords: list) -> str:
    """Extract sentences containing at least one query keyword."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    relevant = [s for s in sentences if any(kw in s.lower() for kw in keywords)]
    return " ".join(relevant).strip()


def _extract_keywords(query: str) -> list:
    """Extract meaningful keywords — ignore stop words."""
    stop_words = {
        "what", "how", "did", "does", "is", "are", "was", "were",
        "the", "a", "an", "in", "on", "at", "to", "for", "of",
        "and", "or", "but", "about", "their", "its", "they", "it",
        "this", "that", "these", "those", "with", "from", "tell",
        "me", "us", "our", "your", "my", "has", "have", "had",
        "been", "be", "do", "say", "says", "said",
    }
    words = re.findall(r"\b[a-z]+\b", query.lower())
    return [w for w in words if w not in stop_words and len(w) > 2]


# ─────────────────────────────────────────────
# 5d — Cross-Encoder Reranking
# ─────────────────────────────────────────────

def rerank(query: str, chunks: list) -> list:
    """
    Rerank chunks with cross-encoder for precision.
    Model: cross-encoder/ms-marco-MiniLM-L-6-v2

    Scores each (query, chunk) pair jointly — more accurate than
    bi-encoder similarity. Used as final step on small candidate set.
    Returns top TOP_K chunks sorted by score.
    """
    if not chunks:
        return []
    if len(chunks) == 1:
        return chunks

    pairs = [(query, chunk["text"]) for chunk in chunks]
    scores = _reranker.predict(pairs)

    scored_chunks = sorted(
        zip(scores, chunks),
        key=lambda x: x[0],
        reverse=True,
    )

    result = []
    for score, chunk in scored_chunks[:TOP_K]:
        chunk_with_score = chunk.copy()
        chunk_with_score["rerank_score"] = round(float(score), 4)
        result.append(chunk_with_score)

    return result