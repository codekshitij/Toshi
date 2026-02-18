"""
Search Tools
MCP tools for finding companies and listing their filings.

Correct flow:
tools/search.py → parser.py → client.py

Tools never talk to client directly — that's parser's job.
"""

from edgar import client, cache, parser


def search_company(name: str) -> str:
    """
    Search for a public company by name on SEC EDGAR.
    Returns the company's CIK number and basic info needed for other tools.
    Use this first before calling any other tool.
    """
    # Cache stores already-parsed results so we don't re-parse on repeat calls
    cached = cache.get_cached("company_search", "query", name.lower())
    if cached:
        results = cached
    else:
        raw = client.search_company(name)            # raw EDGAR response
        results = parser.parse_company_search(raw)   # parser cleans it
        cache.set_cached("company_search", "query", name.lower(), results)

    if not results:
        return f"No companies found matching '{name}'. Try a different name or the stock ticker."

    lines = [f"Found {len(results)} result(s) for '{name}':\n"]
    for i, company in enumerate(results[:5], 1):
        tickers = ", ".join(company["tickers"]) if company["tickers"] else "No ticker"
        exchanges = ", ".join(company["exchanges"]) if company["exchanges"] else ""
        lines.append(
            f"{i}. {company['name']}\n"
            f"   CIK: {company['cik_padded']}\n"
            f"   Ticker: {tickers} ({exchanges})\n"
        )

    lines.append("\nUse the CIK number (10-digit padded) in other tools.")
    return "\n".join(lines)


def get_filings(cik_padded: str, filing_type: str = "10-K", limit: int = 5) -> str:
    """
    List recent SEC filings for a company using their CIK number.
    filing_type options: '10-K' (annual report), '10-Q' (quarterly), '8-K' (current events)
    Use search_company first to get the CIK number.
    """
    cached = cache.get_cached("company_submissions", "cik_padded", cik_padded)
    if cached:
        submissions = cached
    else:
        raw = client.get_company_submissions(cik_padded)    # raw EDGAR response
        cache.set_cached("company_submissions", "cik_padded", cik_padded, raw)
        submissions = raw

    # parser cleans both company info and filings list
    company_info = parser.parse_company_info(submissions)
    filings = parser.parse_filings_list(submissions, filing_type, limit)

    if not filings:
        return f"No {filing_type} filings found for CIK {cik_padded}."

    lines = [
        f"Company: {company_info['name']}",
        f"Ticker: {', '.join(company_info['tickers'])}",
        f"Industry: {company_info['sic_description']}",
        f"\nRecent {filing_type} Filings:\n"
    ]

    for i, filing in enumerate(filings, 1):
        lines.append(
            f"{i}. Filed: {filing['date']}\n"
            f"   Accession #: {filing['accession_number']}\n"
            f"   Document: {filing['document']}\n"
        )

    return "\n".join(lines)