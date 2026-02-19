"""
RAG Step 1 — Ingestion
Download 10-K filing from EDGAR, strip HTML, split into named sections.

Flow: pipeline.py → ingestion.py → client.py (for download)
                                 → cache.py  (for caching)

Rules from PIPELINE.md:
- Use client.get_filing_document() to download — never call EDGAR directly
- Use BeautifulSoup to strip HTML tags
- Split sections by standard 10-K headings
- If a section is not found, return empty string — never crash
- Cache downloaded filings in SQLite
"""

import re
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from bs4 import BeautifulSoup
from edgar import client, cache, parser


# Standard 10-K section headings to detect
# Each key maps to a list of possible heading strings (lowercase)
SECTION_MARKERS = {
    "business":      ["item 1.", "item 1 ", "business overview"],
    "risk_factors":  ["item 1a.", "item 1a ", "risk factors"],
    "mda":           ["item 7.", "item 7 ", "management's discussion",
                      "management&#8217;s discussion", "management\u2019s discussion"],
    "financials":    ["item 8.", "item 8 ", "financial statements"],
}

# Minimum section length — anything shorter is probably a header, not content
MIN_SECTION_LENGTH = 500


def ingest_filing(cik_padded: str, accession_number: str,
                  company_name: str, year: str,
                  filing_type: str = "10-K") -> dict:
    """
    Main entry point for Step 1.
    Downloads, cleans, and sections a single 10-K filing.

    Input:
        cik_padded:        10-digit CIK e.g. "0000320193"
        accession_number:  e.g. "0000320193-24-000081"
        company_name:      e.g. "Apple Inc."
        year:              e.g. "2024"
        filing_type:       "10-K" (default)

    Output: dict matching PIPELINE.md spec:
        {
            "company": str,
            "cik": str,
            "year": str,
            "filing_type": str,
            "sections": {
                "business": str,
                "risk_factors": str,
                "mda": str,
                "financials": str,
            }
        }
    """
    cache_key = f"{cik_padded}_{accession_number}"

    # Check cache first — never re-download what we have
    cached = cache.get_cached("filing_text", "accession", cache_key, max_age_hours=720)
    if cached:
        return cached

    # Find the main document filename from the filing index
    filename = _get_main_document(cik_padded, accession_number)
    if not filename:
        return _empty_result(company_name, cik_padded, year, filing_type)

    # Download raw HTML via client — ingestion never calls EDGAR directly
    raw_html = client.get_filing_document(accession_number, cik_padded, filename)
    if not raw_html:
        return _empty_result(company_name, cik_padded, year, filing_type)

    # Strip HTML, get clean text
    clean_text = _strip_html(raw_html)

    # Split into sections
    sections = _extract_sections(clean_text)

    result = {
        "company": company_name,
        "cik": cik_padded,
        "year": year,
        "filing_type": filing_type,
        "sections": sections,
    }

    # Cache the result
    cache.set_cached("filing_text", "accession", cache_key, result)

    return result


def ingest_recent_filings(cik_padded: str, years: int = 3,
                           filing_type: str = "10-K") -> list[dict]:
    """
    Ingest the last N annual filings for a company.
    Called by pipeline.py when a company hasn't been ingested yet.

    Returns list of ingested filing dicts.
    """
    # Get company submissions via parser (parser calls client)
    submissions = parser.get_parsed_company_facts.__module__  # just to confirm import works
    raw_submissions = client.get_company_submissions(cik_padded)

    company_name = raw_submissions.get("name", f"CIK {cik_padded}")
    filings = parser.parse_filings_list(raw_submissions, filing_type, limit=years)

    results = []
    for filing in filings:
        accession = filing.get("accession_number", "")
        date = filing.get("date", "")
        year = date[:4] if date else "unknown"

        if not accession:
            continue

        result = ingest_filing(
            cik_padded=cik_padded,
            accession_number=accession,
            company_name=company_name,
            year=year,
            filing_type=filing_type,
        )
        results.append(result)

    return results


# ─────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────

def _get_main_document(cik_padded: str, accession_number: str) -> str:
    """
    Find the main HTML document filename from the filing index.
    EDGAR filings contain multiple files — we want the primary 10-K document.
    """
    import httpx, time

    acc_clean = accession_number.replace("-", "")
    index_url = (
        f"https://www.sec.gov/Archives/edgar/data/"
        f"{int(cik_padded)}/{acc_clean}/{accession_number}-index.json"
    )

    try:
        time.sleep(0.15)
        response = httpx.get(index_url, headers=client.HEADERS, timeout=30)
        if response.status_code != 200:
            return ""

        index = response.json()
        documents = index.get("documents", [])

        # Look for the primary 10-K document — usually type "10-K" or "10-K405"
        for doc in documents:
            doc_type = doc.get("type", "").upper()
            filename = doc.get("filename", "")
            if doc_type in ("10-K", "10-K405", "10-KSB") and filename.endswith(".htm"):
                return filename

        # Fallback — return first .htm file
        for doc in documents:
            if doc.get("filename", "").endswith(".htm"):
                return doc["filename"]

    except Exception:
        pass

    return ""


def _strip_html(html: str) -> str:
    """
    Strip HTML tags from filing text using BeautifulSoup.
    Preserves text structure — adds newlines for block elements.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Remove script and style tags entirely
    for tag in soup(["script", "style", "head"]):
        tag.decompose()

    # Add newlines for block-level elements to preserve structure
    for tag in soup.find_all(["p", "div", "tr", "h1", "h2", "h3", "h4", "h5"]):
        tag.insert_before("\n")
        tag.insert_after("\n")

    text = soup.get_text()

    # Clean up excessive whitespace
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]  # remove empty lines
    text = "\n".join(lines)

    # Collapse multiple newlines
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text


def _extract_sections(text: str) -> dict:
    """
    Split clean text into named 10-K sections.
    Returns dict with section names as keys, text as values.
    If a section is not found, returns empty string — never crashes.
    """
    text_lower = text.lower()
    sections = {key: "" for key in SECTION_MARKERS}

    # Find position of each section marker in the text
    positions = {}
    for section_name, markers in SECTION_MARKERS.items():
        for marker in markers:
            pos = text_lower.find(marker)
            if pos != -1:
                positions[section_name] = pos
                break  # use first matching marker

    if not positions:
        return sections

    # Sort sections by their position in the document
    sorted_sections = sorted(positions.items(), key=lambda x: x[1])

    # Extract text between each section start and the next section start
    for i, (section_name, start_pos) in enumerate(sorted_sections):
        # Find end — either next section start or end of document
        if i + 1 < len(sorted_sections):
            end_pos = sorted_sections[i + 1][1]
        else:
            end_pos = len(text)

        section_text = text[start_pos:end_pos].strip()

        # Only keep if substantial content (not just a heading)
        if len(section_text) >= MIN_SECTION_LENGTH:
            sections[section_name] = section_text

    return sections


def _empty_result(company_name: str, cik_padded: str,
                  year: str, filing_type: str) -> dict:
    """Return empty result structure when ingestion fails — never crash."""
    return {
        "company": company_name,
        "cik": cik_padded,
        "year": year,
        "filing_type": filing_type,
        "sections": {key: "" for key in SECTION_MARKERS},
    }