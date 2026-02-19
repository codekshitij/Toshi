"""
RAG Step 2 — Chunker
Split ingested filing sections into overlapping chunks with full metadata.

Flow: pipeline.py → chunker.py (receives output from ingestion.py)

Rules from PIPELINE.md:
- Chunk size: 500 tokens (~400 words)
- Overlap: 50 tokens between chunks so context is not lost at boundaries
- Each chunk must carry full metadata — company, year, section, cik
- Store parent section text in each chunk for parent document retrieval
- Use simple word-count splitting — do NOT add a tokenizer dependency
"""

# Chunk size in words (~400 words ≈ 500 tokens for English text)
CHUNK_SIZE_WORDS = 400

# Overlap in words — shared between consecutive chunks to preserve context
OVERLAP_WORDS = 50

# Minimum words for a chunk to be worth keeping
MIN_CHUNK_WORDS = 50


def chunk_filing(ingested: dict) -> list[dict]:
    """
    Main entry point for Step 2.
    Takes output from ingestion.py, returns list of chunk dicts.

    Input: ingested filing dict from ingestion.py:
        {
            "company": str,
            "cik": str,
            "year": str,
            "filing_type": str,
            "sections": {"risk_factors": str, "mda": str, ...}
        }

    Output: list of chunk dicts matching PIPELINE.md spec:
        {
            "text": str,
            "company": str,
            "cik": str,
            "year": str,
            "filing_type": str,
            "section": str,
            "chunk_id": str,
            "parent_section": str,
        }
    """
    company = ingested.get("company", "")
    cik = ingested.get("cik", "")
    year = ingested.get("year", "")
    filing_type = ingested.get("filing_type", "10-K")
    sections = ingested.get("sections", {})

    all_chunks = []

    for section_name, section_text in sections.items():
        if not section_text or len(section_text.split()) < MIN_CHUNK_WORDS:
            continue  # skip empty or too-short sections

        section_chunks = _chunk_section(
            text=section_text,
            section_name=section_name,
            company=company,
            cik=cik,
            year=year,
            filing_type=filing_type,
        )
        all_chunks.extend(section_chunks)

    return all_chunks


def chunk_filings(ingested_list: list[dict]) -> list[dict]:
    """
    Chunk multiple filings at once.
    Called by pipeline.py when ingesting multiple years.
    """
    all_chunks = []
    for ingested in ingested_list:
        chunks = chunk_filing(ingested)
        all_chunks.extend(chunks)
    return all_chunks


# ─────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────

def _chunk_section(text: str, section_name: str, company: str,
                   cik: str, year: str, filing_type: str) -> list[dict]:
    """
    Split a single section into overlapping word-based chunks.
    Each chunk gets full metadata + parent section text.
    """
    words = text.split()
    chunks = []
    chunk_index = 0
    start = 0

    while start < len(words):
        end = start + CHUNK_SIZE_WORDS
        chunk_words = words[start:end]

        if len(chunk_words) < MIN_CHUNK_WORDS:
            break  # remaining text too short to be useful

        chunk_text = " ".join(chunk_words)
        chunk_id = f"{cik}_{year}_{section_name}_{chunk_index}"

        chunks.append({
            "text": chunk_text,
            "company": company,
            "cik": cik,
            "year": year,
            "filing_type": filing_type,
            "section": section_name,
            "chunk_id": chunk_id,
            "parent_section": text,  # full section for parent doc retrieval
        })

        chunk_index += 1
        # Move forward by chunk size minus overlap
        start += CHUNK_SIZE_WORDS - OVERLAP_WORDS

    return chunks


def get_chunk_stats(chunks: list[dict]) -> dict:
    """
    Return stats about a set of chunks — useful for debugging.
    """
    if not chunks:
        return {"total": 0}

    by_section = {}
    by_year = {}

    for chunk in chunks:
        section = chunk.get("section", "unknown")
        year = chunk.get("year", "unknown")
        by_section[section] = by_section.get(section, 0) + 1
        by_year[year] = by_year.get(year, 0) + 1

    return {
        "total": len(chunks),
        "by_section": by_section,
        "by_year": by_year,
        "avg_words": sum(len(c["text"].split()) for c in chunks) // len(chunks),
    }