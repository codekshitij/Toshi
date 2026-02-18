"""
EDGAR API Client
Handles all HTTP communication with SEC's EDGAR REST API.
No API key required - EDGAR is a public API.
"""

import httpx
import time
from typing import Optional

# EDGAR requires a user-agent header identifying your app
HEADERS = {
    "User-Agent": "SEC-MCP-Server contact@example.com",  # Change email to yours
    "Accept-Encoding": "gzip, deflate",
}

BASE_URL = "https://data.sec.gov"
SEARCH_URL = "https://efts.sec.gov"

# Be polite to EDGAR - they ask for max 10 req/sec
REQUEST_DELAY = 0.1  


def _get(url: str, params: dict = None) -> dict:
    """
    Make a GET request to EDGAR. Handles rate limiting and errors cleanly.
    """
    time.sleep(REQUEST_DELAY)
    response = httpx.get(url, headers=HEADERS, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def search_company(name: str) -> dict:
    """
    Search for a company by name on EDGAR.
    Returns RAW response from EDGAR — parser.py is responsible for cleaning it.
    CIK = Central Index Key, EDGAR's unique ID for every company.
    """
    data = _get(f"{SEARCH_URL}/LATEST/search-index", params={"q": f'"{name}"', "dateRange": "custom"})

    # Try a broader search if exact match returns nothing
    if not data.get("hits", {}).get("hits"):
        data = _get(f"{SEARCH_URL}/LATEST/search-index", params={"q": name})

    return data  # raw — let parser.py handle cleaning


def get_company_submissions(cik_padded: str) -> dict:
    """
    Get all filings/submissions for a company using their padded CIK.
    Returns metadata about the company + list of all their filings.
    """
    url = f"{BASE_URL}/submissions/CIK{cik_padded}.json"
    return _get(url)


def get_company_facts(cik_padded: str) -> dict:
    """
    Get structured financial facts for a company (XBRL data).
    This is the gold mine - contains revenue, profit, assets, etc. over time.
    """
    url = f"{BASE_URL}/api/xbrl/companyfacts/CIK{cik_padded}.json"
    return _get(url)


def get_filing_document(accession_number: str, cik_padded: str, filename: str) -> Optional[str]:
    """
    Download the actual text of a specific filing document.
    accession_number format: 0000320193-23-000077 (with dashes)
    """
    # EDGAR stores files with dashes removed in the path
    acc_no_clean = accession_number.replace("-", "")
    url = f"https://www.sec.gov/Archives/edgar/full-index/{cik_padded}/{acc_no_clean}/{filename}"
    
    time.sleep(REQUEST_DELAY)
    response = httpx.get(url, headers=HEADERS, timeout=60)
    
    if response.status_code == 200:
        return response.text
    return None