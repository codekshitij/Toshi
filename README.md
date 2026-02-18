# Tōshi 🗡️

> *"The truth behind the numbers"*

A natural language interface to SEC's EDGAR financial database, built as an MCP server for Claude. Ask questions about any public company in plain English and get real data pulled directly from official SEC filings.

```
You: "Compare Apple and Microsoft's net income over the last 5 years"
Claude: *calls your tools* → fetches real SEC data → gives you a clean answer
```

---

## What You Can Ask

- *"What was Apple's revenue over the last 5 years?"*
- *"Compare Tesla and Ford's net income since 2020"*
- *"Show me Microsoft's latest 10-K filings"*
- *"What's Amazon's operating cash flow trend?"*
- *"How much cash does Google have on its balance sheet?"*
- *"Compare FAANG companies on total assets"*

---

## Architecture

Clean 3-layer design — each layer has one job:

```
tools/          →   parser.py   →   client.py
formats for         cleans raw       fetches from
Claude              EDGAR data       SEC EDGAR API
```

```
toshi/
├── server.py              # MCP entry point — @mcp.tool() decorators
├── edgar/
│   ├── client.py          # All EDGAR API HTTP calls (raw data only)
│   ├── parser.py          # Cleans raw EDGAR responses into structured data
│   └── cache.py           # SQLite caching — don't re-download what we have
├── tools/
│   ├── search.py          # search_company, get_filings
│   └── financials.py      # get_financials, compare_companies
├── .env.example           # Copy to .env and fill in your email
├── .env                   # Your config — never pushed to GitHub
├── requirements.txt
└── README.md
```

---

## Setup

**1. Clone and install dependencies**
```bash
git clone https://github.com/yourusername/toshi.git
cd toshi
python3 -m venv venv
source venv/bin/activate
python3 -m pip install mcp httpx
```

**2. Configure your environment**
```bash
cp .env.example .env
```

Edit `.env` and add your contact email — SEC EDGAR requires this to identify automated requests:
```
SEC_USER_AGENT="Toshi SEC-MCP-Server your-email@example.com"
```

**3. Connect to Claude Desktop**

Edit your Claude Desktop config:
- **Mac:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

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

> **Tip:** Use your venv's python path (e.g. `/Users/yourname/toshi/venv/bin/python3`) not the system python. This ensures the right dependencies are always used.

**4. Restart Claude Desktop**

Fully quit (`Cmd+Q` on Mac) and reopen. You should see a 🔨 hammer icon in the chat — your tools are connected.

---

## Available Tools

| Tool | Description |
|---|---|
| `search_company(name)` | Find any public company and get their CIK number |
| `get_filings(cik, type, limit)` | List 10-K / 10-Q / 8-K filings |
| `get_financials(cik, metrics, years)` | Pull financial metrics from SEC XBRL data |
| `compare_companies(cik_list, metric, years)` | Side-by-side metric comparison |

## Available Financial Metrics

`revenue`, `net_income`, `operating_income`, `gross_profit`, `total_assets`,
`total_liabilities`, `stockholders_equity`, `cash`, `total_debt`,
`operating_cash_flow`, `capex`, `eps_basic`, `eps_diluted`, `shares_outstanding`

---

## How It Works

1. You ask Claude a question in plain English
2. Claude calls `search_company` → gets the company's CIK from SEC's official ticker file
3. Claude calls `get_financials` or `compare_companies` with that CIK
4. Your server fetches structured XBRL data from [data.sec.gov](https://data.sec.gov) — free, no API key needed
5. Results are cached locally in SQLite — repeat queries are instant
6. Claude formats everything into a clean, readable answer

---

## Data Source

All data is pulled directly from the [SEC EDGAR REST API](https://www.sec.gov/search-filings/edgar-application-programming-interfaces):

- `https://www.sec.gov/files/company_tickers.json` — company/ticker/CIK lookup
- `https://data.sec.gov/submissions/CIK{cik}.json` — filing history
- `https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json` — structured financial data

No third-party APIs, no paid services, no API keys.

---

## Roadmap

**Phase 1 — Done ✓**
- Company search by name or ticker
- Filing history (10-K, 10-Q, 8-K)
- Financial metrics over time
- Multi-company comparison
- SQLite caching

**Phase 2 — Coming Next**
- `detect_anomalies` — flag unusual YoY changes in financials
- `extract_risk_factors` — pull risk section text from 10-K filings
- `get_executive_compensation` — CEO and exec pay data
- `benchmark_vs_peers` — compare against industry averages
- `analyze_sentiment` — tone analysis of MD&A section over time

---

## Requirements

- Python 3.10+
- [Claude Desktop](https://claude.ai/download)
- `mcp`, `httpx`

---

*Built with the [MCP SDK](https://modelcontextprotocol.io) and [SEC EDGAR API](https://www.sec.gov/developer)*