"""
RAG Step 4 — Vector Store
All ChromaDB operations: store chunks, MMR search, existence checks.

Flow: retriever.py → store.py → embedder.py (for embedding queries)
                              → ChromaDB (for storage and retrieval)

Rules from PIPELINE.md:
- Collection name: toshi_filings
- ChromaDB storage path: ./chroma_db in project root
- Filter by cik and/or year — never mix companies
- mmr_lambda = 0.7 default — 70% relevance, 30% diversity
- Always return chunks with full metadata
"""

import os
import sys
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import chromadb
from rag import embedder

# ─────────────────────────────────────────────
# ChromaDB setup — persists to disk
# ─────────────────────────────────────────────
CHROMA_PATH = str(Path(__file__).parent.parent / "chroma_db")
COLLECTION_NAME = "toshi_filings"

_client = chromadb.PersistentClient(path=CHROMA_PATH)
_collection = _client.get_or_create_collection(
    name=COLLECTION_NAME,
    metadata={"hnsw:space": "cosine"},  # cosine similarity for normalized vectors
)


# ─────────────────────────────────────────────
# Public functions (spec from PIPELINE.md)
# ─────────────────────────────────────────────

def add_chunks(chunks: list[dict]) -> None:
    """
    Embed and store chunks in ChromaDB.
    Skips chunks that already exist — never creates duplicates.

    Input: list of chunk dicts from chunker.py
    """
    if not chunks:
        return

    # Filter out already-stored chunks
    new_chunks = [c for c in chunks if not chunk_exists(c["chunk_id"])]
    if not new_chunks:
        print(f"All {len(chunks)} chunks already in store — skipping.", file=__import__("sys").stderr)
        return

    print(f"Embedding {len(new_chunks)} new chunks...", file=__import__("sys").stderr)

    # Embed all chunk texts in one batch — GPU processes in parallel
    texts = [c["text"] for c in new_chunks]
    embeddings = embedder.embed_batch(texts)

    # Prepare ChromaDB inputs
    ids = [c["chunk_id"] for c in new_chunks]
    metadatas = [
        {
            "company":      c.get("company", ""),
            "cik":          c.get("cik", ""),
            "year":         c.get("year", ""),
            "filing_type":  c.get("filing_type", "10-K"),
            "section":      c.get("section", ""),
            "parent_section": c.get("parent_section", "")[:2000],  # ChromaDB metadata limit
        }
        for c in new_chunks
    ]

    # Store in batches of 100 to avoid memory issues
    batch_size = 100
    for i in range(0, len(new_chunks), batch_size):
        batch_ids = ids[i:i + batch_size]
        batch_embeddings = embeddings[i:i + batch_size].tolist()
        batch_metadatas = metadatas[i:i + batch_size]
        batch_texts = texts[i:i + batch_size]

        _collection.add(
            ids=batch_ids,
            embeddings=batch_embeddings,
            metadatas=batch_metadatas,
            documents=batch_texts,
        )

    print(f"✓ Stored {len(new_chunks)} chunks in ChromaDB.", file=__import__("sys").stderr)


def search_mmr(query: str, cik: str = None, year: str = None,
               n_results: int = 20, mmr_lambda: float = 0.7) -> list[dict]:
    """
    MMR search — returns diverse, relevant chunks for a query.

    MMR formula per PIPELINE.md:
    score = λ × similarity_to_query - (1-λ) × max_similarity_to_already_selected

    Args:
        query:       search query string
        cik:         filter by company CIK (recommended — never mix companies)
        year:        filter by specific year (optional)
        n_results:   how many chunks to return after MMR (default 20)
        mmr_lambda:  0.7 = 70% relevance, 30% diversity (per spec)
    """
    # Build ChromaDB filter
    where = _build_filter(cik, year)

    # Step 1 — get top 50 candidates by raw similarity
    n_candidates = min(50, _collection.count())
    if n_candidates == 0:
        return []

    query_embedding = embedder.embed_text(query)

    results = _collection.query(
        query_embeddings=[query_embedding.tolist()],
        n_results=n_candidates,
        where=where if where else None,
        include=["documents", "metadatas", "embeddings", "distances"],
    )

    if not results["ids"][0]:
        return []

    # Parse results into candidate dicts
    candidates = _parse_results(results)

    # Step 2 — apply MMR to select diverse results
    selected = _mmr_select(
        query_embedding=query_embedding,
        candidates=candidates,
        n_results=n_results,
        mmr_lambda=mmr_lambda,
    )

    return selected


def chunk_exists(chunk_id: str) -> bool:
    """
    Check if a chunk is already stored — prevents duplicate embeddings.
    """
    try:
        result = _collection.get(ids=[chunk_id])
        return len(result["ids"]) > 0
    except Exception:
        return False


def clear_company(cik: str) -> None:
    """
    Delete all chunks for a company — used before re-ingestion.
    """
    try:
        _collection.delete(where={"cik": cik})
        print(f"✓ Cleared all chunks for CIK {cik}.", file=__import__("sys").stderr)
    except Exception as e:
        print(f"Warning: could not clear company {cik}: {e}", file=__import__("sys").stderr)


def get_stats() -> dict:
    """Return store statistics — useful for debugging."""
    count = _collection.count()
    return {
        "total_chunks": count,
        "collection": COLLECTION_NAME,
        "storage_path": CHROMA_PATH,
        "device": embedder.get_device(),
    }


# ─────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────

def _build_filter(cik: str = None, year: str = None) -> dict:
    """Build ChromaDB where filter from optional cik/year."""
    conditions = []
    if cik:
        conditions.append({"cik": {"$eq": cik}})
    if year:
        conditions.append({"year": {"$eq": year}})

    if len(conditions) == 0:
        return {}
    elif len(conditions) == 1:
        return conditions[0]
    else:
        return {"$and": conditions}


def _parse_results(results: dict) -> list[dict]:
    """Parse raw ChromaDB results into clean chunk dicts."""
    chunks = []
    ids = results["ids"][0]
    documents = results["documents"][0]
    metadatas = results["metadatas"][0]
    embeddings = results["embeddings"][0]
    distances = results["distances"][0]

    for i, chunk_id in enumerate(ids):
        chunks.append({
            "chunk_id":      chunk_id,
            "text":          documents[i],
            "company":       metadatas[i].get("company", ""),
            "cik":           metadatas[i].get("cik", ""),
            "year":          metadatas[i].get("year", ""),
            "filing_type":   metadatas[i].get("filing_type", ""),
            "section":       metadatas[i].get("section", ""),
            "parent_section": metadatas[i].get("parent_section", ""),
            "embedding":     np.array(embeddings[i], dtype=np.float32),
            "similarity":    1 - distances[i],  # ChromaDB returns distance, convert to similarity
        })

    return chunks


def _mmr_select(query_embedding: np.ndarray, candidates: list[dict],
                n_results: int, mmr_lambda: float) -> list[dict]:
    """
    MMR selection algorithm per PIPELINE.md spec:
    score = λ × similarity_to_query - (1-λ) × max_similarity_to_selected

    Returns top n_results chunks maximizing relevance + diversity.
    """
    if not candidates:
        return []

    selected = []
    remaining = candidates.copy()

    while remaining and len(selected) < n_results:
        best_score = -float("inf")
        best_candidate = None

        for candidate in remaining:
            # Relevance: similarity to query
            relevance = float(np.dot(candidate["embedding"], query_embedding))

            # Diversity: how different from already selected chunks
            if not selected:
                diversity_penalty = 0.0
            else:
                similarities_to_selected = [
                    float(np.dot(candidate["embedding"], s["embedding"]))
                    for s in selected
                ]
                diversity_penalty = max(similarities_to_selected)

            # MMR score
            score = mmr_lambda * relevance - (1 - mmr_lambda) * diversity_penalty

            if score > best_score:
                best_score = score
                best_candidate = candidate

        if best_candidate:
            selected.append(best_candidate)
            remaining.remove(best_candidate)

    # Remove embeddings from output — tools don't need raw vectors
    for chunk in selected:
        chunk.pop("embedding", None)

    return selected