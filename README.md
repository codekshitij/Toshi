# Tōshi 🗡️

> Ask questions about any public company. Get answers grounded in real SEC filings.

```
"What risks did Apple disclose about China in their last 3 annual reports?"
"Are there any red flags in Tesla's financials?"
"What is Microsoft's financial risk score?"
```

---

## What is Tōshi?

Tōshi is an MCP server that gives Claude access to SEC EDGAR — the US government's public database of every financial filing from every public company.

Most AI tools answer financial questions from training data. Tōshi answers from the actual source documents — annual reports, risk disclosures, financial statements — pulled live from SEC EDGAR.

**Three things it can do:**

**1. Financial data** — Pull real numbers directly from SEC filings
- Revenue, net income, cash flow, debt, EPS, and more
- Up to 10 years of history
- Side-by-side comparisons across companies

**2. Financial intelligence** — Analyze what the numbers mean
- Anomaly detection — flags unusual year-over-year changes
- Risk scoring — proprietary 0–10 score across 5 financial dimensions

**3. Filing Q&A** — Search and read actual filing text
- Ask questions in plain English
- Answers pulled from the Risk Factors, MD&A, and Business sections of 10-K filings
- Every answer is cited with company, year, and section

---

## Requirements

- [Claude Desktop](https://claude.ai/download)
- Python 3.11
- macOS, Linux, or Windows

---

## Setup

**1. Clone the repo**
```bash
git clone https://github.com/yourusername/toshi.git
cd toshi
```

**2. Create a virtual environment**
```bash
python3.11 -m venv venv
source venv/bin/activate        # macOS / Linux
venv\Scripts\activate           # Windows
```

**3. Install dependencies**
```bash
pip install -r requirements.txt
```

**4. Configure your email**

SEC EDGAR requires a contact email in the User-Agent header. Create a `.env` file:
```bash
cp .env.example .env
```

Edit `.env` and set:
```
SEC_USER_AGENT="Toshi your-email@example.com"
```

**5. Connect to Claude Desktop**

Edit your Claude Desktop config file:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

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

Replace `/absolute/path/to/toshi` with the actual path on your machine.

**6. Restart Claude Desktop**

Look for the 🔨 hammer icon — that confirms Tōshi is connected.

---

## Usage

Just ask Claude naturally. No special commands needed.

**Examples:**

```
"What was Apple's revenue over the last 5 years?"

"Compare Tesla and Ford's net income since 2021"

"Are there any red flags in Amazon's financials?"

"What is Microsoft's financial risk score?"

"What does Apple say about China risks in their 10-K filings?"

"How has Tesla's competition disclosure changed over the last 3 years?"

"What risks did Nvidia disclose about AI regulation?"
```

The first time you ask about a company's filings, Tōshi will download and index them. Subsequent queries are instant.

---

## Data Source

All data is pulled directly from the [SEC EDGAR REST API](https://www.sec.gov/developer):

- `www.sec.gov/files/company_tickers.json` — company search
- `data.sec.gov/submissions/` — filing history
- `data.sec.gov/api/xbrl/companyfacts/` — financial data
- `www.sec.gov/Archives/edgar/` — actual filing documents

No third-party APIs. No paid services. No API keys beyond your email address.

---

## Notes

- First query for a new company downloads and indexes their filings — this takes 15–30 seconds
- Subsequent queries are fast — data is cached locally
- Filing text (10-K documents) is indexed in a local vector database and not sent anywhere
- Only supports US public companies listed on SEC EDGAR