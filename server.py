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
def get_filings(cik_padded: str, filing_type: str = "10-K", limit: int = 5) -> str:
    """
    List recent SEC filings for a company.
    cik_padded: 10-digit CIK from search_company (e.g. '0000320193' for Apple)
    filing_type: '10-K' = annual report, '10-Q' = quarterly, '8-K' = major events
    limit: how many filings to return (default 5)
    Use search_company first to get the CIK.
    """
    return _get_filings(cik_padded, filing_type, limit)


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


if __name__ == "__main__":
    print("Starting SEC EDGAR MCP Server...", file=sys.stderr)
    mcp.run()