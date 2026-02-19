"""
RAG Step 6 — Pipeline
Orchestrates the full RAG flow. Single entry point for tools/.

Flow: tools/filings_qa.py → pipeline.py → ingestion.py (if needed)
                                        → chunker.py   (if needed)
                                        → store.py     (if needed)
                                        → retriever.py (always)

Rules from PIPELINE.md:
- Check ChromaDB before downloading — never re-ingest what we already have
- Ingest on demand — only when a query comes in for a company
- Return chunks with full metadata so tools/ can format citations properly
- Never return raw embeddings to tools/ — only text + metadata
"""

import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from rag import ingestion, chunker, store, retriever


def search_filing(cik_padded: str, query: str,
                  filing_type: str = "10-K", years: int = 3) -> list:
    """
    Full RAG pipeline — single entry point called by tools/filings_qa.py

    Steps:
    1. Determine which years to search
    2. Check if filings already ingested in ChromaDB
    3. If not → ingest → chunk → embed → store
    4. Retrieve via HyDE + MMR + CRAG + reranking
    5. Return top 5 chunks with full metadata

    Input:
        cik_padded:  10-digit CIK e.g. "0000320193"
        query:       search query (pre-expanded by Claude via tool description)
        filing_type: "10-K" (default)
        years:       how many recent annual filings to search (default 3)

    Output: list of chunk dicts with text + metadata, no raw embeddings
    """
    # Step 1 — determine target years
    target_years = _get_target_years(years)

    # Step 2 — check which years are already ingested
    missing_years = _find_missing_years(cik_padded, target_years)

    # Step 3 — ingest missing years on demand
    if missing_years:
        print(f"Ingesting {len(missing_years)} filing(s) for CIK {cik_padded}...")
        _ingest_and_store(cik_padded, filing_type, len(missing_years))

    # Step 4 — retrieve
    results = retriever.retrieve(
        query=query,
        cik=cik_padded,
        years=target_years,
    )

    # Step 5 — strip internal fields before returning to tools/
    return _clean_chunks(results)


# ─────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────

def _get_target_years(n: int) -> list:
    """Return list of the last N years e.g. ['2024', '2023', '2022']"""
    current_year = datetime.now().year
    return [str(current_year - i) for i in range(n)]


def _find_missing_years(cik_padded: str, years: list) -> list:
    """
    Check ChromaDB for which years are already stored for this company.
    Returns list of years that still need ingestion.
    """
    missing = []
    for year in years:
        sample_id = f"{cik_padded}_{year}_risk_factors_0"
        if not store.chunk_exists(sample_id):
            missing.append(year)
    return missing


def _ingest_and_store(cik_padded: str, filing_type: str, n_filings: int) -> None:
    """
    Full ingestion pipeline for a company:
    download → clean → section split → chunk → embed → store
    """
    ingested_filings = ingestion.ingest_recent_filings(
        cik_padded=cik_padded,
        years=n_filings,
        filing_type=filing_type,
    )

    if not ingested_filings:
        print(f"Warning: no filings found for CIK {cik_padded}")
        return

    all_chunks = chunker.chunk_filings(ingested_filings)
    if not all_chunks:
        print(f"Warning: no chunks produced for CIK {cik_padded}")
        return

    stats = chunker.get_chunk_stats(all_chunks)
    print(f"Chunked {stats['total']} chunks across {stats['by_year']}")

    store.add_chunks(all_chunks)


def _clean_chunks(chunks: list) -> list:
    """
    Remove internal fields before returning to tools/.
    Never return raw embeddings — only text + metadata.
    """
    clean = []
    for chunk in chunks:
        clean.append({
            "text":         chunk.get("text", ""),
            "company":      chunk.get("company", ""),
            "cik":          chunk.get("cik", ""),
            "year":         chunk.get("year", ""),
            "filing_type":  chunk.get("filing_type", "10-K"),
            "section":      chunk.get("section", ""),
            "rerank_score": chunk.get("rerank_score", 0.0),
            "crag_trimmed": chunk.get("crag_trimmed", False),
        })
    return clean