# Tōshi 🗡️

> *"The truth behind the numbers"*

A financial intelligence MCP server that connects Claude to SEC's EDGAR database. Ask questions about any public company in plain English and get answers grounded in real SEC filings — not hallucinations.

```
You: "What risks did Tesla disclose about China in their last 3 annual reports?"
Claude: *searches actual 10-K filings* → gives you a cited, grounded answer
```

---

## What You Can Ask

**Financial Data (Phase 1)**
- *"What was Apple's revenue over the last 5 years?"*
- *"Compare Tesla and Ford's net income since 2020"*
- *"Show me Microsoft's latest 10-K filings"*

**Financial Intelligence (Phase 2)**
- *"Are there any red flags in Tesla's financials?"*
- *"What is Apple's financial risk score?"*
- *"Has Amazon's debt grown unusually fast?"*

**Filing Q&A with RAG (Phase 3 — In Progress)**
- *"What does Apple say about AI competition risk?"*
- *"How has Tesla's China revenue discussion changed over 3 years?"*
- *"What risks did Microsoft disclose about AI regulation?"*
- *"Summarize the MD&A section from Amazon's latest 10-K"*

---

## Architecture

### Data Layer — Clean 3-layer separation
```
tools/          →   parser.py   →   client.py
formats for         cleans raw       fetches from
Claude              EDGAR data       SEC EDGAR API
```

### Intelligence Layer
```
tools/analysis.py   →   edgar/analysis.py
passes clean data       pure math, no API calls
                        YoY changes, risk scoring
```

### RAG Layer (Phase 3)
```
tools/filings_qa.py
        ↓
rag/pipeline.py        orchestrates the full flow
        ↓
┌───────────────────────────────────────┐
│  1. ingestion.py                      │
│     download 10-K → strip HTML        │
│     → split into sections             │
│                                       │
│  2. chunker.py                        │
│     sections → 500 token chunks       │
│     with metadata (company, year,     │
│     section, cik)                     │
│                                       │
│  3. embedder.py                       │
│     sentence-transformers (local)     │
│     text → 384-dim vectors            │
│                                       │
│  4. store.py                          │
│     ChromaDB vector store             │
│     persist to disk                   │
│                                       │
│  5. retriever.py                      │
│     HyDE query expansion              │
│     MMR diverse retrieval             │
│     CRAG self-critique                │
│     Cross-encoder reranking           │
└───────────────────────────────────────┘
        ↓
Claude answers with citations
```

### Full Project Structure
```
toshi/
├── server.py                  # MCP entry point
├── edgar/
│   ├── client.py              # EDGAR API HTTP calls (raw data only)
│   ├── parser.py              # Cleans raw responses + fetch orchestration
│   ├── cache.py               # SQLite caching
│   └── analysis.py            # Financial calculations (YoY, risk scoring)
├── tools/
│   ├── search.py              # search_company, get_filings
│   ├── financials.py          # get_financials, compare_companies
│   ├── analysis.py            # detect_anomalies, get_risk_score
│   └── filings_qa.py          # search_filing (Phase 3)
├── rag/
│   ├── ingestion.py           # Download + clean 10-K filing text
│   ├── chunker.py             # Split into chunks with metadata
│   ├── embedder.py            # sentence-transformers embeddings
│   ├── store.py               # ChromaDB vector store operations
│   ├── retriever.py           # MMR + CRAG + reranking
│   └── pipeline.py            # Orchestrates full RAG flow
├── .env.example
├── .env                       # Never pushed to GitHub
├── requirements.txt
└── README.md
```

---

## RAG Pipeline — Technical Deep Dive

### Why RAG?
10-K filings are 200+ page documents. Passing the full text to an LLM is inefficient and hits context limits. RAG retrieves only the most relevant passages, making answers faster, cheaper, and more accurate.

### Techniques Used

**HyDE (Hypothetical Document Embeddings)**
Solves the query-document mismatch problem. SEC filings use formal legal language — a conversational query won't match well against it. Instead, Claude first generates a hypothetical 10-K paragraph that would answer the question, then we embed that. The hypothetical answer looks like a real filing chunk, so similarity search works much better.

```
"what are Apple's China risks?"
        ↓ HyDE
"Apple's operations in the People's Republic of China are subject to..."
        ↓ embed
much better vector match against actual filing text
```

**MMR (Maximal Marginal Relevance)**
Solves the redundancy problem. Without MMR, similarity search returns 5 nearly identical chunks from the same paragraph. MMR balances relevance against diversity:

```
Score = λ × relevance_to_query - (1-λ) × similarity_to_already_selected
```

Result: chunks from different years, different sections, different angles on the same topic.

**CRAG (Corrective RAG)**
Makes the pipeline self-correcting. After retrieval, each chunk is scored for relevance:

```
CORRECT   (score > 0.7)  → keep as is
AMBIGUOUS (score 0.3-0.7) → extract only the relevant sentences
INCORRECT (score < 0.3)  → discard entirely, search again
```

This means the LLM only ever sees high-quality, relevant context.

**Cross-Encoder Reranking**
Two-stage retrieval for speed + precision. First stage: fast MMR retrieval of top 20 chunks (approximate). Second stage: slow cross-encoder re-scores all 20 precisely, returns top 5. Best of both worlds.

**Parent Document Retrieval**
Index small chunks for precise matching, but return the full parent section for rich context. Solves the "chunk too small = loses meaning" problem.

---

## Setup

**1. Clone and install**
```bash
git clone https://github.com/yourusername/toshi.git
cd toshi
python3 -m venv venv
source venv/bin/activate
python3 -m pip install -r requirements.txt
```

**2. Configure environment**
```bash
cp .env.example .env
# Edit .env and add your email
```

**3. Connect to Claude Desktop**

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "toshi": {
      "command": "/absolute/path/to/toshi/venv/bin/python3",
      "args": ["/absolute/path/to/toshi/server.py"]
    }
  }
}
```

Quit and reopen Claude Desktop. Look for the 🔨 hammer icon.

---

## Available Tools

### Phase 1 — Data
| Tool | Description |
|---|---|
| `search_company(name)` | Find any public company, get their CIK |
| `get_filings(cik, type, limit)` | List 10-K / 10-Q / 8-K filings |
| `get_financials(cik, metrics, years)` | Pull financial metrics from XBRL data |
| `compare_companies(cik_list, metric, years)` | Side-by-side comparison |

### Phase 2 — Intelligence
| Tool | Description |
|---|---|
| `detect_anomalies(cik)` | Flag unusual YoY changes with severity levels |
| `get_risk_score(cik)` | Proprietary 0-10 risk score across 5 dimensions |

### Phase 3 — RAG (In Progress)
| Tool | Description |
|---|---|
| `search_filing(cik, query, years)` | Natural language Q&A over actual 10-K text |

---

## Financial Metrics Available

`revenue`, `net_income`, `operating_income`, `gross_profit`, `total_assets`,
`total_liabilities`, `stockholders_equity`, `cash`, `total_debt`,
`operating_cash_flow`, `capex`, `eps_basic`, `eps_diluted`, `shares_outstanding`

---

## Data Source

All data pulled directly from the official [SEC EDGAR REST API](https://www.sec.gov/developer):
- `https://www.sec.gov/files/company_tickers.json` — company lookup
- `https://data.sec.gov/submissions/CIK{cik}.json` — filing history
- `https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json` — financial data
- `https://www.sec.gov/Archives/edgar/` — actual filing documents

No third-party APIs. No paid services. No API keys.

---

## Roadmap

**Phase 1 — Data ✓**
- Company search, filing history, financial metrics, multi-company comparison, SQLite caching

**Phase 2 — Intelligence ✓**
- Anomaly detection with severity levels
- Proprietary risk scoring across 5 financial dimensions

**Phase 3 — RAG 🔨 In Progress**
- 10-K ingestion and section extraction
- Local embeddings with sentence-transformers
- ChromaDB vector store
- HyDE + MMR + CRAG + reranking pipeline
- Natural language Q&A over actual filing text with citations

**Phase 4 — Planned**
- Graph RAG — connect companies, subsidiaries, markets across filings
- Multi-filing reasoning — answer questions that span multiple years
- Peer benchmarking — compare risk scores across an industry

---

## Requirements

- Python 3.10+
- [Claude Desktop](https://claude.ai/download)
- Dependencies: `mcp`, `httpx`, `sentence-transformers`, `chromadb`, `beautifulsoup4`

---

## Why Tōshi is Different

Every other SEC EDGAR MCP server fetches data and returns it raw. Tōshi goes further:

- **Proprietary risk scoring** — no other SEC MCP server does this
- **Anomaly detection** — flags what a financial analyst would actually notice  
- **RAG over filings** — answers grounded in actual document text, not hallucinations
- **Self-correcting pipeline** — CRAG ensures only relevant context reaches the LLM
- **Pure Python, no heavy dependencies** — just clone and run

---

*Built with the [MCP SDK](https://modelcontextprotocol.io) and [SEC EDGAR API](https://www.sec.gov/developer)*