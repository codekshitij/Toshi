"""
EDGAR Data Parser
Extracts clean, readable financial data from raw EDGAR API responses.
EDGAR returns raw XBRL data which needs to be processed into something useful.

This is the ONLY file that knows what raw EDGAR responses look like.
All other files (tools/) receive already-cleaned data from here.
"""

from typing import Optional


# Map of common financial metrics to their XBRL concept names
FINANCIAL_CONCEPTS = {
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "operating_income": ["OperatingIncomeLoss"],
    "gross_profit": ["GrossProfit"],
    "total_assets": ["Assets"],
    "total_liabilities": ["Liabilities"],
    "stockholders_equity": ["StockholdersEquity", "StockholdersEquityAttributableToParent"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue", "Cash"],
    "total_debt": ["LongTermDebt", "LongTermDebtNoncurrent"],
    "operating_cash_flow": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment"],
    "eps_basic": ["EarningsPerShareBasic"],
    "eps_diluted": ["EarningsPerShareDiluted"],
    "shares_outstanding": ["CommonStockSharesOutstanding"],
}


# ─────────────────────────────────────────────
# Search parsing
# ─────────────────────────────────────────────

def parse_company_search(raw: dict) -> list[dict]:
    """
    Clean raw SEC company tickers response into a filtered list of companies.

    SEC's company_tickers.json format:
    { "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}, ... }

    We filter this by the search query and return clean company dicts.
    This is the only place that knows what SEC's ticker lookup response looks like.
    """
    query = raw.get("query", "").lower()
    companies = raw.get("companies", {})

    results = []
    for entry in companies.values():
        name = entry.get("title", "")
        ticker = entry.get("ticker", "")
        cik = str(entry.get("cik_str", ""))

        # Match against company name or ticker
        if query in name.lower() or query.upper() == ticker.upper():
            results.append({
                "name": name,
                "cik": cik,
                "cik_padded": cik.zfill(10),
                "tickers": [ticker] if ticker else [],
                "exchanges": [],  # not in this endpoint, populated later if needed
            })

    # Sort by exact name match first, then alphabetically
    results.sort(key=lambda x: (
        0 if query == x["name"].lower() else
        1 if x["name"].lower().startswith(query) else 2,
        x["name"]
    ))

    return results[:10]  # return top 10 matches


# ─────────────────────────────────────────────
# Submissions / filings parsing
# ─────────────────────────────────────────────

def parse_company_info(submissions: dict) -> dict:
    """Extract clean company metadata from raw submissions response."""
    return {
        "name": submissions.get("name", "Unknown"),
        "cik": submissions.get("cik", ""),
        "tickers": submissions.get("tickers", []),
        "exchanges": submissions.get("exchanges", []),
        "sic_description": submissions.get("sicDescription", ""),
        "state_of_incorporation": submissions.get("stateOfIncorporation", ""),
        "fiscal_year_end": submissions.get("fiscalYearEnd", ""),
        "business_address": submissions.get("addresses", {}).get("business", {}),
    }


def parse_filings_list(submissions: dict, filing_type: str = "10-K", limit: int = 5) -> list[dict]:
    """
    Extract a clean list of filings from raw company submissions.
    filing_type: "10-K" for annual, "10-Q" for quarterly, "8-K" for events
    """
    recent = submissions.get("filings", {}).get("recent", {})

    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accession_numbers = recent.get("accessionNumber", [])
    descriptions = recent.get("primaryDocument", [])

    results = []
    for i, form in enumerate(forms):
        if form == filing_type:
            results.append({
                "type": form,
                "date": dates[i] if i < len(dates) else "",
                "accession_number": accession_numbers[i] if i < len(accession_numbers) else "",
                "document": descriptions[i] if i < len(descriptions) else "",
            })
            if len(results) >= limit:
                break

    return results


# ─────────────────────────────────────────────
# Financial facts parsing
# ─────────────────────────────────────────────

def parse_company_facts(cik_padded: str, raw_facts: dict, metrics: list[str], years: int) -> dict:
    """
    Clean raw EDGAR company facts into structured financial data.
    This is the only place that knows what EDGAR's facts response looks like.
    """
    return {
        "company_name": raw_facts.get("entityName", f"CIK {cik_padded}"),
        "metrics": {
            metric: extract_metric(raw_facts, metric, last_n_years=years)
            for metric in metrics
        }
    }


def extract_metric(facts: dict, metric_name: str, last_n_years: int = 5) -> list[dict]:
    """
    Extract a specific financial metric from raw EDGAR company facts.
    Tries multiple XBRL concept names since companies use different tags.
    Returns last N years of annual data sorted by most recent first.
    """
    concepts = FINANCIAL_CONCEPTS.get(metric_name, [metric_name])
    us_gaap = facts.get("facts", {}).get("us-gaap", {})

    for concept in concepts:
        if concept not in us_gaap:
            continue

        units = us_gaap[concept].get("units", {})
        values = units.get("USD") or units.get("shares") or units.get("USD/shares") or []

        # Filter to annual 10-K filings only
        annual = [
            v for v in values
            if v.get("form") == "10-K" and v.get("fp") == "FY"
        ]

        # Deduplicate by fiscal year — keep most recently filed entry per year
        by_year = {}
        for v in annual:
            year = v.get("end", "")[:4]
            if year not in by_year or v.get("filed", "") > by_year[year].get("filed", ""):
                by_year[year] = v

        sorted_data = sorted(by_year.values(), key=lambda x: x.get("end", ""), reverse=True)
        result = sorted_data[:last_n_years]

        if result:
            return [
                {
                    "year": r.get("end", "")[:4],
                    "value": r.get("val"),
                    "period_end": r.get("end"),
                    "filed": r.get("filed"),
                }
                for r in result
            ]

    return []


# ─────────────────────────────────────────────
# Formatting helpers
# ─────────────────────────────────────────────

def format_number(value: Optional[float], metric_name: str = "") -> str:
    """Format a raw number into a human-readable string."""
    if value is None:
        return "N/A"

    if "eps" in metric_name or "per_share" in metric_name:
        return f"${value:.2f}"

    abs_val = abs(value)
    sign = "-" if value < 0 else ""

    if abs_val >= 1_000_000_000:
        return f"{sign}${abs_val / 1_000_000_000:.2f}B"
    elif abs_val >= 1_000_000:
        return f"{sign}${abs_val / 1_000_000:.2f}M"
    elif abs_val >= 1_000:
        return f"{sign}${abs_val / 1_000:.2f}K"
    else:
        return f"{sign}${abs_val:.2f}"

def get_parsed_company_facts(cik_padded: str, metrics: list, years: int) -> dict:
    """
    Fetch and parse company financial facts in one call.
    This is what tools/financials.py calls — handles fetch + clean.
    """
    from edgar import client
    raw_facts = client.get_company_facts(cik_padded)
    return parse_company_facts(cik_padded, raw_facts, metrics, years)
