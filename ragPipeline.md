# Tōshi RAG Pipeline — Implementation Plan

> This document is the source of truth for Phase 3 RAG implementation.
> Before writing any code, check here first. Do not deviate from this plan without updating this doc.

---

## Overview

We are building a RAG pipeline that allows Claude to answer questions grounded in actual 10-K filing text from SEC EDGAR. The pipeline is self-correcting, diverse in retrieval, and precise in ranking.

**The one new MCP tool this produces:**
```
search_filing(cik, query, filing_type="10-K", years=3)
```

---

## File Structure

```
toshi/
├── rag/
│   ├── PIPELINE.md       ← you are here
│   ├── ingestion.py      ← Step 1: download + clean 10-K text
│   ├── chunker.py        ← Step 2: split into chunks with metadata
│   ├── embedder.py       ← Step 3: sentence-transformers embeddings
│   ├── store.py          ← Step 4: ChromaDB operations
│   ├── retriever.py      ← Step 5: MMR + CRAG + reranking
│   └── pipeline.py       ← Step 6: orchestrates everything
├── tools/
│   └── filings_qa.py     ← MCP tool that calls pipeline.py
```

---

## Dependencies

```
sentence-transformers    # local embeddings, no API key needed
chromadb                 # vector store, persists to disk
beautifulsoup4           # HTML parsing for 10-K cleanup
torch                    # required by sentence-transformers
```

Add to requirements.txt. Do NOT use OpenAI embeddings — keep everything local and free.

---

## Step 1 — ingestion.py

**Job:** Download a 10-K filing from EDGAR, strip HTML, split into named sections.

**Input:** `cik_padded`, `accession_number`

**Output:**
```python
{
    "company": "Apple Inc.",
    "cik": "0000320193",
    "year": "2024",
    "filing_type": "10-K",
    "sections": {
        "risk_factors": "full text of risk factors section...",
        "mda": "full text of MD&A section...",
        "business": "full text of business overview...",
        "financials": "full text of financial statements..."
    }
}
```

**Rules:**
- Use `client.get_filing_document()` to download — never call EDGAR directly here
- Use BeautifulSoup to strip HTML tags
- Split sections by their standard 10-K headings
- If a section is not found, return empty string for that key — never crash
- Cache downloaded filings in SQLite using `cache.py`

**Section headings to detect:**
```python
SECTION_MARKERS = {
    "risk_factors":  ["item 1a", "risk factors"],
    "mda":           ["item 7", "management's discussion", "management&#8217;s discussion"],
    "business":      ["item 1", "business"],
    "financials":    ["item 8", "financial statements"],
}
```

---

## Step 2 — chunker.py

**Job:** Split each section into overlapping chunks with full metadata.

**Input:** Output from ingestion.py

**Output:** List of chunk dicts:
```python
{
    "text": "the actual chunk text...",
    "company": "Apple Inc.",
    "cik": "0000320193",
    "year": "2024",
    "filing_type": "10-K",
    "section": "risk_factors",
    "chunk_id": "0000320193_2024_risk_factors_0",
    "parent_section": "full parent section text..."  # for parent doc retrieval
}
```

**Rules:**
- Chunk size: 500 tokens (~400 words)
- Overlap: 50 tokens between chunks so context is not lost at boundaries
- Each chunk must carry full metadata — company, year, section, cik
- Store parent section text in each chunk for parent document retrieval
- Use simple word-count splitting — do NOT add a tokenizer dependency

---

## Step 3 — embedder.py

**Job:** Convert text to vectors using a local sentence-transformers model.

**Model:** `all-MiniLM-L6-v2`
- 384 dimensions
- Fast, lightweight, runs on CPU
- No API key, no cost, downloads once and caches locally

**Input:** Single string or list of strings

**Output:** numpy array of embeddings

**Rules:**
- Load model once at module level — do not reload on every call
- Expose two functions only: `embed_text(text)` and `embed_batch(texts)`
- Never call any external API here — local model only

---

## Step 4 — store.py

**Job:** All ChromaDB operations — store chunks, query, MMR search.

**Collection name:** `toshi_filings`

**ChromaDB storage path:** `./chroma_db` in project root (add to .gitignore)

**Functions to expose:**
```python
add_chunks(chunks: list[dict]) -> None
    # embed and store chunks in ChromaDB

search_mmr(query: str, cik: str = None, year: str = None, 
           n_results: int = 20, mmr_lambda: float = 0.7) -> list[dict]
    # MMR search with optional filters by company/year

chunk_exists(chunk_id: str) -> bool
    # check before re-embedding to avoid duplicates

clear_company(cik: str) -> None
    # delete all chunks for a company (for re-ingestion)
```

**MMR implementation:**
```
1. get top 50 candidates by similarity to query
2. initialize selected = []
3. for each remaining candidate:
   score = λ × similarity_to_query - (1-λ) × max_similarity_to_selected
   pick highest score, add to selected
4. return top n_results from selected
```

**Rules:**
- Filter by `cik` and/or `year` when provided — never mix companies
- `mmr_lambda = 0.7` default — 70% relevance, 30% diversity
- Always return chunks with their full metadata

---

## Step 5 — retriever.py

**Job:** Full retrieval pipeline — HyDE → MMR → CRAG → reranking.

**Input:** `query`, `cik`, `years` (list of years to search across)

**Output:** Top 5 high-quality, diverse, relevant chunks with metadata

**Sub-steps in order:**

### 5a. HyDE (Hypothetical Document Embeddings)
```python
def hyde_expand(query: str) -> str:
    """
    Ask Claude to generate a hypothetical 10-K paragraph that would 
    answer the query. Embed that instead of the raw query.
    
    Why: SEC filings use formal legal language. A conversational query
    won't match well. A hypothetical answer looks like real filing text.
    """
```
- Call Claude API with system prompt: "You are an SEC filing. Write one paragraph from a 10-K filing that would answer this question: {query}"
- Return the generated paragraph
- If Claude API fails, fall back to raw query — never crash

### 5b. MMR Retrieval
```python
def retrieve_mmr(expanded_query: str, cik: str, years: list) -> list[dict]:
    """Retrieve 20 diverse chunks using MMR across specified years."""
```
- Call `store.search_mmr()` for each year separately
- Combine results, re-run MMR across all years
- Returns 20 candidates

### 5c. CRAG Self-Critique
```python
def crag_filter(query: str, chunks: list[dict]) -> list[dict]:
    """
    Score each chunk for relevance. Keep correct, trim ambiguous, discard incorrect.
    
    Scoring is keyword + semantic — no extra API calls.
    """
```
- Score each chunk: keyword overlap + embedding similarity to query
- CORRECT (>0.7): keep full chunk
- AMBIGUOUS (0.3-0.7): extract sentences containing query keywords only
- INCORRECT (<0.3): discard
- If fewer than 3 chunks remain after filtering, relax thresholds

### 5d. Cross-Encoder Reranking
```python
def rerank(query: str, chunks: list[dict]) -> list[dict]:
    """Rerank remaining chunks with cross-encoder for precision."""
```
- Model: `cross-encoder/ms-marco-MiniLM-L-6-v2`
- Score each (query, chunk) pair
- Return top 5 sorted by score

**Rules:**
- HyDE failure must never crash the pipeline — fall back gracefully
- CRAG must never return fewer than 2 chunks — relax thresholds if needed
- Final output is always exactly 5 chunks (or fewer if not enough data)

---

## Step 6 — pipeline.py

**Job:** Orchestrate all steps. Single entry point for everything.

**The one function tools/ calls:**
```python
def search_filing(cik_padded: str, query: str, 
                  filing_type: str = "10-K", years: int = 3) -> list[dict]:
    """
    Full RAG pipeline:
    1. Check if filings are ingested for this company/years
    2. If not → ingest → chunk → embed → store
    3. HyDE expand query
    4. MMR retrieve
    5. CRAG filter
    6. Rerank
    7. Return top 5 chunks with metadata
    """
```

**Rules:**
- Check ChromaDB before downloading — never re-ingest what we already have
- Ingest on demand — only when a query comes in for a company
- Return chunks with full metadata so tools/ can format citations properly
- Never return raw embeddings to tools/ — only text + metadata

---

## tools/filings_qa.py

**Job:** MCP tool layer. Calls pipeline, formats output for Claude.

```python
def search_filing(cik_padded: str, query: str, 
                  filing_type: str = "10-K", years: int = 3) -> str:
    """
    Answer a question using actual text from SEC 10-K filings.
    Returns relevant passages with citations (company, year, section).
    Use search_company first to get the CIK number.
    """
```

**Output format:**
```
Query: "What are Tesla's China risks?"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[1] Tesla Inc. — 2024 10-K — Risk Factors
"Our business in China is subject to..."

[2] Tesla Inc. — 2023 10-K — MD&A
"Revenue from China decreased..."

[3] Tesla Inc. — 2022 10-K — Risk Factors
"The Chinese government may impose..."
```

---

## Architecture Rules — Do Not Break These

1. `tools/filings_qa.py` calls `pipeline.py` only — never calls rag/* directly
2. `pipeline.py` orchestrates all rag/* files — it is the only file that knows the full flow
3. `retriever.py` calls `store.py` for data — never touches ChromaDB directly
4. `ingestion.py` calls `client.py` for downloads — never calls EDGAR directly
5. `embedder.py` is stateless — only embeds, never stores
6. HyDE lives in `retriever.py` — not in `pipeline.py`
7. CRAG lives in `retriever.py` — not in `pipeline.py`

---

## What Goes in .gitignore

```
chroma_db/       # vector store — too large to push, rebuilt on demand
```

---

## Build Order

Build and test each step independently before moving to the next:

- [ ] Step 1: `ingestion.py` — test by printing cleaned section text
- [ ] Step 2: `chunker.py` — test by printing chunk count and metadata
- [ ] Step 3: `embedder.py` — test by checking embedding dimensions (should be 384)
- [ ] Step 4: `store.py` — test by storing 10 chunks and retrieving them
- [ ] Step 5: `retriever.py` — test full retrieval pipeline on one query
- [ ] Step 6: `pipeline.py` — end to end test
- [ ] `tools/filings_qa.py` — register in server.py, test in Claude Desktop

---

## Definition of Done

Phase 3 is complete when:
- [ ] Claude can answer "What are Apple's China risks?" using actual 10-K text
- [ ] Answer includes citations (company, year, section)
- [ ] Works across multiple years (not just the latest filing)
- [ ] No crashes on missing sections or unavailable filings
- [ ] ChromaDB persists between Claude Desktop sessions
EOF