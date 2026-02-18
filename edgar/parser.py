"""
EDGAR Data Parser
Extracts clean, readable financial data from raw EDGAR API responses.
EDGAR returns raw XBRL data which needs to be processed into something useful.

This is the ONLY file that knows what raw EDGAR responses look like.
All other files (tools/) receive already-cleaned data from here.
"""

from typing import Optional


# Map of common financial metrics to their XBRL concept names
# XBRL is the tagging standard SEC uses for structured financial data
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
    Clean raw EDGAR search API response into a list of simple company dicts.
    This is the only place that knows what EDGAR's search response looks like.
    """
    hits = raw.get("hits", {}).get("hits", [])
    results = []
    seen_ciks = set()

    for hit in hits:
        source = hit.get("_source", {})
        cik = source.get("entity_id", "")

        if not cik or cik in seen_ciks:
            continue

        seen_ciks.add(cik)
        results.append({
            "name": source.get("display_names", ["Unknown"])[0] if source.get("display_names") else "Unknown",
            "cik": cik.lstrip("0"),           # clean version e.g. "320193"
            "cik_padded": cik.zfill(10),       # padded version e.g. "0000320193"
            "tickers": source.get("tickers", []),
            "exchanges": source.get("exchanges", []),
        })

    return results


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
    Returns a clean dict with company name and all requested metric data.
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

        # Get USD values (or shares for share-based metrics)
        values = units.get("USD") or units.get("shares") or units.get("USD/shares") or []

        # Filter to annual 10-K filings only (not quarterly)
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

    return []  # Metric not found in this company's filings


# ─────────────────────────────────────────────
# Formatting helpers
# ─────────────────────────────────────────────

def format_number(value: Optional[float], metric_name: str = "") -> str:
    """Format a raw number into a human-readable string."""
    if value is None:
        return "N/A"

    # EPS and per-share metrics don't need to be scaled
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