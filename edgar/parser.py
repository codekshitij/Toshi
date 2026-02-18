"""
EDGAR Data Parser
Extracts clean, readable financial data from raw EDGAR API responses.
EDGAR returns raw XBRL data which needs to be processed into something useful.
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


def extract_metric(facts: dict, metric_name: str, last_n_years: int = 5) -> list[dict]:
    """
    Extract a specific financial metric from EDGAR company facts.
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

        # Filter to annual 10-K filings only (form = "10-K", not quarterly)
        annual = [
            v for v in values
            if v.get("form") == "10-K" and v.get("fp") == "FY"
        ]

        # Deduplicate by fiscal year end date - keep most recent filing per year
        by_year = {}
        for v in annual:
            year = v.get("end", "")[:4]  # Extract year from date string
            if year not in by_year or v.get("filed", "") > by_year[year].get("filed", ""):
                by_year[year] = v

        # Sort by year descending and take last N years
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

    return []  # Metric not found


def parse_filings_list(submissions: dict, filing_type: str = "10-K", limit: int = 5) -> list[dict]:
    """
    Extract a clean list of filings from company submissions.
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


def parse_company_info(submissions: dict) -> dict:
    """Extract clean company metadata from submissions response."""
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