"""
EDGAR API Client
Handles all HTTP communication with SEC's EDGAR REST API.
No API key required - EDGAR is a public API.
"""

import httpx
import time
import os
from typing import Optional
from pathlib import Path

def _load_env():
    """
    Simple .env loader — reads KEY=VALUE pairs from .env file.
    We avoid adding python-dotenv as a dependency to keep things minimal.
    """
    env_path = Path(__file__).parent.parent / ".env"
    if not env_path.exists():
        raise FileNotFoundError(
            f".env file not found at {env_path}\n"
            "Copy .env.example to .env and fill in your details."
        )
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip().strip('"'))


# Load .env on import
_load_env()

# SEC requires a User-Agent header with your contact info
# Set this in your .env file as: SEC_USER_AGENT="AppName your-email@example.com"
HEADERS = {
    "User-Agent": os.environ["SEC_USER_AGENT"],
    "Accept-Encoding": "gzip, deflate",
}

# SEC docs: https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data


BASE_URL = "https://data.sec.gov"
SEC_URL = "https://www.sec.gov"

# Be polite to EDGAR - max 10 req/sec per their policy
REQUEST_DELAY = 0.15


def _get(url: str, params: dict = None) -> dict:
    """Make a GET request to EDGAR. Handles rate limiting and errors."""
    time.sleep(REQUEST_DELAY)
    response = httpx.get(url, headers=HEADERS, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def search_company(name: str) -> dict:
    """
    Search for a company by name using SEC's official ticker/CIK lookup file.

    Per SEC docs, the correct endpoint for company name → CIK lookup is:
    https://www.sec.gov/files/company_tickers.json

    This is far more reliable than the efts.sec.gov search endpoint which
    searches document contents, not company names.

    Returns RAW response — parser.py is responsible for cleaning it.
    """
    # Official SEC company/ticker/CIK lookup file
    data = _get(f"{SEC_URL}/files/company_tickers.json")

    # Return both the raw lookup data and the search query
    # so parser can filter it
    return {
        "query": name,
        "companies": data  # dict of {index: {cik_str, ticker, title}}
    }


def get_company_submissions(cik_padded: str) -> dict:
    """
    Get all filings/submissions for a company using their padded CIK.
    Official endpoint: https://data.sec.gov/submissions/CIK{cik_padded}.json
    """
    url = f"{BASE_URL}/submissions/CIK{cik_padded}.json"
    return _get(url)


def get_company_facts(cik_padded: str) -> dict:
    """
    Get structured XBRL financial facts for a company.
    Official endpoint: https://data.sec.gov/api/xbrl/companyfacts/CIK{cik_padded}.json
    Contains revenue, profit, assets, etc. over time.
    """
    url = f"{BASE_URL}/api/xbrl/companyfacts/CIK{cik_padded}.json"
    return _get(url)


def get_filing_document(accession_number: str, cik_padded: str, filename: str) -> Optional[str]:
    """
    Download the actual text of a specific filing document.
    accession_number format: 0000320193-23-000077 (with dashes)
    """
    acc_no_clean = accession_number.replace("-", "")
    cik_int = int(cik_padded)
    url = f"{SEC_URL}/Archives/edgar/data/{cik_int}/{acc_no_clean}/{filename}"

    time.sleep(REQUEST_DELAY)
    response = httpx.get(url, headers=HEADERS, timeout=60)

    if response.status_code == 200:
        return response.text
    return None