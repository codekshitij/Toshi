"""
Financials Tools
MCP tools for extracting and comparing financial data from EDGAR.

Correct flow:
tools/financials.py → parser.py → client.py

Tools never talk to client directly — that's parser's job.
"""

from edgar import client, cache, parser


AVAILABLE_METRICS = list(parser.FINANCIAL_CONCEPTS.keys())


def get_financials(cik_padded: str, metrics: list[str] = None, years: int = 5) -> str:
    """
    Get key financial metrics for a company from their SEC filings.

    Available metrics: revenue, net_income, operating_income, gross_profit,
    total_assets, total_liabilities, stockholders_equity, cash, total_debt,
    operating_cash_flow, capex, eps_basic, eps_diluted, shares_outstanding.

    If metrics not specified, returns the most important ones by default.
    Use search_company first to get the CIK number.
    """
    if metrics is None:
        metrics = ["revenue", "net_income", "operating_cash_flow", "total_assets", "cash"]

    # Validate metrics before making any API calls
    invalid = [m for m in metrics if m not in parser.FINANCIAL_CONCEPTS]
    if invalid:
        return (
            f"Invalid metrics: {invalid}.\n"
            f"Available metrics: {', '.join(AVAILABLE_METRICS)}"
        )

    # Fetch raw facts (with cache)
    cached = cache.get_cached("company_facts", "cik_padded", cik_padded, max_age_hours=48)
    if cached:
        raw_facts = cached
    else:
        raw_facts = client.get_company_facts(cik_padded)   # raw EDGAR response
        cache.set_cached("company_facts", "cik_padded", cik_padded, raw_facts)

    # Parser cleans everything — tool never touches raw_facts directly
    data = parser.parse_company_facts(cik_padded, raw_facts, metrics, years)

    lines = [f"Financial Data: {data['company_name']}\n", "=" * 50]

    for metric, rows in data["metrics"].items():
        lines.append(f"\n{metric.replace('_', ' ').title()}:")
        if not rows:
            lines.append("  No data available")
            continue
        for row in rows:
            formatted = parser.format_number(row["value"], metric)
            lines.append(f"  {row['year']}: {formatted}")

    return "\n".join(lines)


def compare_companies(cik_list: list[str], metric: str = "revenue", years: int = 3) -> str:
    """
    Compare a financial metric across multiple companies side by side.
    cik_list: list of 10-digit padded CIK numbers (max 5 companies)
    metric: one financial metric to compare (e.g. 'revenue', 'net_income')
    Use search_company to get CIK numbers for each company first.
    """
    if metric not in parser.FINANCIAL_CONCEPTS:
        return f"Invalid metric '{metric}'. Available: {', '.join(AVAILABLE_METRICS)}"

    if len(cik_list) > 5:
        return "Please compare at most 5 companies at a time."

    # Fetch and parse each company through parser — never touch raw facts in tool
    companies = {}
    for cik in cik_list:
        cached = cache.get_cached("company_facts", "cik_padded", cik, max_age_hours=48)
        if cached:
            raw_facts = cached
        else:
            raw_facts = client.get_company_facts(cik)      # raw EDGAR response
            cache.set_cached("company_facts", "cik_padded", cik, raw_facts)

        # Parser cleans it — one metric at a time for comparison
        data = parser.parse_company_facts(cik, raw_facts, [metric], years)
        company_name = data["company_name"]
        companies[company_name] = {
            row["year"]: row["value"]
            for row in data["metrics"].get(metric, [])
        }

    # Get all years present across all companies
    all_years = sorted(
        set(year for year_data in companies.values() for year in year_data),
        reverse=True
    )

    metric_label = metric.replace("_", " ").title()
    lines = [f"Comparison: {metric_label}\n", "=" * 60]

    company_names = list(companies.keys())
    header = f"{'Year':<8}" + "".join(f"{name[:20]:<22}" for name in company_names)
    lines.append(header)
    lines.append("-" * 60)

    for year in all_years:
        row = f"{year:<8}"
        for name in company_names:
            val = companies[name].get(year)
            formatted = parser.format_number(val, metric) if val is not None else "N/A"
            row += f"{formatted:<22}"
        lines.append(row)

    return "\n".join(lines)