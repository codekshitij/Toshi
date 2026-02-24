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


# Section heading patterns to detect in raw HTML
# Apple and most large filers use iXBRL with inline CSS spans
# We match the Item number in raw HTML before stripping tags
SECTION_PATTERNS = {
    "business":     [r'item\s+1\.(?!a)', r'item\s+1\b(?!\s*a)'],
    "risk_factors": [r'item\s+1a\.', r'item\s+1a\b'],
    "mda":          [r'item\s+7\.(?!a)', r'item\s+7\b(?!\s*a)'],
    "financials":   [r'item\s+8\.', r'item\s+8\b'],
}

MIN_SECTION_LENGTH = 500


def ingest_filing(cik_padded: str, accession_number: str,
                  company_name: str, year: str,
                  filing_type: str = "10-K") -> dict:
    """
    Main entry point for Step 1.
    Downloads, cleans, and sections a single 10-K filing.
    """
    cache_key = f"{cik_padded}_{accession_number}"

    cached = cache.get_cached("filing_text", "accession", cache_key, max_age_hours=720)
    if cached:
        return cached

    filename = _get_main_document(cik_padded, accession_number)
    if not filename:
        print(f"Warning: could not find main document for {accession_number}")
        return _empty_result(company_name, cik_padded, year, filing_type)

    print(f"Downloading: {filename}")
    raw_html = client.get_filing_document(accession_number, cik_padded, filename)
    if not raw_html:
        print(f"Warning: download returned empty for {filename}")
        return _empty_result(company_name, cik_padded, year, filing_type)

    print(f"Downloaded {len(raw_html):,} chars — extracting sections...")

    # Extract sections from raw HTML before stripping tags
    sections = _extract_sections_from_html(raw_html)

    # Strip HTML from each section's text
    for key in sections:
        if sections[key]:
            sections[key] = _strip_html(sections[key])

    result = {
        "company": company_name,
        "cik": cik_padded,
        "year": year,
        "filing_type": filing_type,
        "sections": sections,
    }

    cache.set_cached("filing_text", "accession", cache_key, result)
    return result


def ingest_recent_filings(cik_padded: str, years: int = 3,
                           filing_types: list[str] = ["10-K", "10-Q"]) -> list:
    """
    Ingest the last N annual and quarterly filings for a company.
    Called by pipeline.py when a company hasn't been ingested yet.
    """
    raw_submissions = client.get_company_submissions(cik_padded)
    company_name = raw_submissions.get("name", f"CIK {cik_padded}")

    results = []
    for filing_type in filing_types:
        filings = parser.parse_filings_list(raw_submissions, filing_type, limit=years)

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
    EDGAR returns an HTML index page — parse with regex to find filenames.
    Modern 10-K filings use iXBRL wrapped in /ix?doc= viewer links.
    """
    import httpx, time

    acc_clean = accession_number.replace("-", "")
    cik_int = int(cik_padded)
    index_url = (
        f"https://www.sec.gov/Archives/edgar/data/"
        f"{cik_int}/{acc_clean}/{accession_number}-index.htm"
    )

    try:
        time.sleep(0.15)
        response = httpx.get(index_url, headers=client.HEADERS, timeout=30)
        if response.status_code != 200:
            return ""

        html = response.text

        # Modern filings: main doc linked via /ix?doc=...htm (iXBRL viewer)
        ix_matches = re.findall(
            r'/ix\?doc=/Archives/edgar/data/\d+/\d+/([^"\'>\s]+\.htm)',
            html
        )
        if ix_matches:
            return ix_matches[0]

        # Fallback: direct .htm links — skip exhibits
        direct_matches = re.findall(
            rf'/Archives/edgar/data/{cik_int}/{acc_clean}/([^"\'>\s]+\.htm)',
            html
        )
        for filename in direct_matches:
            if "exhibit" not in filename.lower() and not re.match(r'ex\d', filename.lower()):
                return filename

        if direct_matches:
            return direct_matches[0]

    except Exception as e:
        print(f"Warning: could not get filing index: {e}")

    return ""


def _extract_sections_from_html(html: str) -> dict:
    """
    Find section positions in raw HTML using regex on Item headings.
    Apple's iXBRL filings embed headings inside spans with inline CSS.
    We find positions in raw HTML, then slice HTML chunks per section,
    then strip tags from each chunk separately.
    """
    html_lower = html.lower()
    sections = {key: "" for key in SECTION_PATTERNS}
    positions = {}

    for section_name, patterns in SECTION_PATTERNS.items():
        for pattern in patterns:
            matches = list(re.finditer(pattern, html_lower))
            if matches:
                # Use the LAST match of "item 1" to skip table of contents
                # The actual section appears after the TOC
                if section_name == "business":
                    # business (item 1) appears multiple times — skip TOC entries
                    # real section is usually the largest gap match
                    pos = matches[-1].start() if len(matches) > 1 else matches[0].start()
                else:
                    # For others, use last occurrence too (skip TOC)
                    pos = matches[-1].start()
                positions[section_name] = pos
                break

    if not positions:
        return sections

    sorted_sections = sorted(positions.items(), key=lambda x: x[1])

    for i, (section_name, start_pos) in enumerate(sorted_sections):
        if i + 1 < len(sorted_sections):
            end_pos = sorted_sections[i + 1][1]
        else:
            end_pos = len(html)

        html_chunk = html[start_pos:end_pos]
        if len(html_chunk) >= MIN_SECTION_LENGTH:
            sections[section_name] = html_chunk

    return sections


def _strip_html(html: str) -> str:
    """Strip HTML tags, preserve text structure."""
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "head"]):
        tag.decompose()

    for tag in soup.find_all(["p", "div", "tr", "h1", "h2", "h3", "h4", "h5"]):
        tag.insert_before("\n")
        tag.insert_after("\n")

    text = soup.get_text()
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Clean up HTML entities
    text = re.sub(r'&#\d+;', ' ', text)
    text = re.sub(r'&[a-z]+;', ' ', text)
    text = re.sub(r'\s+', ' ', text)

    return text.strip()


def _empty_result(company_name: str, cik_padded: str,
                  year: str, filing_type: str) -> dict:
    """Return empty result structure when ingestion fails — never crash."""
    return {
        "company": company_name,
        "cik": cik_padded,
        "year": year,
        "filing_type": filing_type,
        "sections": {key: "" for key in SECTION_PATTERNS},
    }