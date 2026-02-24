"""
SEC EDGAR MCP Server
Natural language interface to SEC's EDGAR financial database.

Phase 1 Tools:
- search_company: Find a company and get their CIK
- get_filings: List a company's SEC filings
- get_financials: Pull key financial metrics over time
- compare_companies: Side-by-side metric comparison
"""

import sys
import os

# Add project root to path so imports work cleanly
sys.path.insert(0, os.path.dirname(__file__))

from mcp.server.fastmcp import FastMCP
from tools.search import search_company as _search_company, get_filings as _get_filings
from tools.financials import get_financials as _get_financials, compare_companies as _compare_companies
from tools.analysis import detect_anomalies as _detect_anomalies, get_risk_score as _get_risk_score
from tools.filings_qa import search_filing as _search_filing


mcp = FastMCP("sec-edgar-server")


# ─────────────────────────────────────────────
# Tool registrations
# Each function below is a thin wrapper that
# connects the MCP decorator to our tool logic.
# Keeping business logic in tools/ makes it
# easy to test outside of MCP context.
# ─────────────────────────────────────────────

@mcp.tool()
def search_company(name: str) -> str:
    """
    Search for a public company by name on SEC EDGAR.
    Returns the company's CIK number (their unique EDGAR ID) and basic info.
    Always use this first before calling any other tool — you need the CIK.
    Example: search_company("Apple") or search_company("Tesla")
    """
    return _search_company(name)


@mcp.tool()
def get_filings(cik_padded: str, filing_types: list[str] = ["10-K", "10-Q"], years: int = 3) -> str:
    """
    List recent SEC filings for a company.
    cik_padded: 10-digit CIK from search_company (e.g. '0000320193' for Apple)
    filing_type: '10-K' = annual report, '10-Q' = quarterly, '8-K' = major events
    limit: how many filings to return (default 5)
    Use search_company first to get the CIK.
    """
    return _get_filings(cik_padded, filing_types, years)


@mcp.tool()
def get_financials(cik_padded: str, metrics: list[str] = None, years: int = 5) -> str:
    """
    Get key financial metrics for a company pulled directly from their SEC filings.
    cik_padded: 10-digit CIK from search_company
    metrics: list of metrics to fetch. Options: revenue, net_income, operating_income,
             gross_profit, total_assets, total_liabilities, stockholders_equity,
             cash, total_debt, operating_cash_flow, capex, eps_basic, eps_diluted,
             shares_outstanding. Defaults to the most important ones if not specified.
    years: how many years of history to return (default 5)
    Use search_company first to get the CIK.
    """
    return _get_financials(cik_padded, metrics, years)


@mcp.tool()
def compare_companies(cik_list: list[str], metric: str = "revenue", years: int = 3) -> str:
    """
    Compare a financial metric across multiple companies side by side.
    cik_list: list of 10-digit CIK numbers (max 5 companies)
    metric: the metric to compare — revenue, net_income, operating_cash_flow, etc.
    years: years of history (default 3)
    Use search_company to get CIK numbers for each company first.
    Example: compare Apple, Microsoft, Google on revenue over 3 years.
    """
    return _compare_companies(cik_list, metric, years)


@mcp.tool()
def detect_anomalies(cik_padded: str) -> str:
    """
    Detect unusual year-over-year changes in a company's financials.
    Flags red flags like sudden debt spikes, revenue drops, or cash burn.
    Severity levels: CRITICAL, WARNING, NOTABLE, NOTE.
    Use search_company first to get the CIK number.
    Example: detect_anomalies("0000320193") for Apple
    """
    return _detect_anomalies(cik_padded)


@mcp.tool()
def get_risk_score(cik_padded: str) -> str:
    """
    Calculate a proprietary financial risk score (0-10) for a company.
    Analyzes debt levels, cash burn, revenue trends, profit margins, and more.
    0-2 = Low Risk | 3-4 = Moderate | 5-6 = Elevated | 7-8 = High | 9-10 = Very High
    Use search_company first to get the CIK number.
    Example: get_risk_score("0000320193") for Apple
    """
    return _get_risk_score(cik_padded)


@mcp.tool()
def search_filing(cik_padded: str, query: str,
                  filing_types: list[str], years: int = 3, quarters: list[str] = None) -> str:
    """
    Answer questions using actual text from SEC 10-K filings.
    Returns relevant passages with citations (company, year, section).
    Use search_company first to get the CIK number.

    IMPORTANT — before calling this tool, rewrite the user's question
    into formal SEC 10-K filing language. Examples:

    User: "What are Apple's China risks?"
    Rewrite: "The Company's operations in the People's Republic of China
    are subject to political, regulatory, and economic risks including
    potential restrictions on technology and trade."

    User: "How does Tesla talk about competition?"
    Rewrite: "The Company faces intense competition from established and
    new market participants in the electric vehicle industry which may
    adversely affect market share and financial results."

    Pass the rewritten formal query as the query parameter.
    """
    return _search_filing(cik_padded, query, filing_type, years)

if __name__ == "__main__":
    print("Starting SEC EDGAR MCP Server...", file=sys.stderr)
    mcp.run()