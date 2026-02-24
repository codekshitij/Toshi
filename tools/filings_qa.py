"""
RAG MCP Tool — Filing Q&A
Formats RAG pipeline output for Claude.

Flow: server.py → tools/filings_qa.py → pipeline.py
                                       (never calls rag/* directly)

Architecture rule: this file calls pipeline.py ONLY.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from rag import pipeline

SECTION_LABELS = {
    "risk_factors": "Risk Factors",
    "mda":          "MD&A",
    "business":     "Business Overview",
    "financials":   "Financial Statements",
}


def search_filing(cik_padded: str, query: str,
                  filing_types: list[str], years: int = 3, quarters: list[str] = None) -> str:
    """
    Answer a question using actual text from SEC filings.
    Returns relevant passages with citations (company, year, filing type, section).
    Use search_company first to get the CIK number.

    IMPORTANT — before calling this tool, rewrite the user's question
    into formal SEC filing language. Examples:
    ...
    """
    try:
        chunks = pipeline.search_filing(
            cik_padded=cik_padded,
            query=query,
            filing_types=filing_types,
            years=years,
            quarters=quarters,
        )

        if not chunks:
            return (
                f"No relevant passages found in {', '.join(filing_types)} filings for CIK {cik_padded}.\n"
                f"The filings may not be available on EDGAR or the sections could not be extracted.\n"
                f"Try get_filings() to check what filings are available."
            )

        return _format_results(query, chunks)

    except Exception as e:
        return f"Error searching filings: {str(e)}"


# ─────────────────────────────────────────────
# Formatting
# ─────────────────────────────────────────────

def _format_results(query: str, chunks: list) -> str:
    """
    Format chunks into clean cited output for Claude.

    Output format per PIPELINE.md:
    Query: "..."
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    [1] Company — Year 10-K — Section
    "passage text..."
    """
    lines = []
    lines.append(f'Query: "{query}"')
    lines.append("━" * 50)
    lines.append("")

    for i, chunk in enumerate(chunks, 1):
        company     = chunk.get("company", "Unknown")
        year        = chunk.get("year", "Unknown")
        filing_type = chunk.get("filing_type", "10-K")
        section     = SECTION_LABELS.get(chunk.get("section", ""), chunk.get("section", ""))
        text        = chunk.get("text", "").strip()
        trimmed     = chunk.get("crag_trimmed", False)
        score       = chunk.get("rerank_score", 0.0)

        # Citation header
        lines.append(f"[{i}] {company} — {year} {filing_type} — {section}")
        if trimmed:
            lines.append("     ℹ️  (trimmed to most relevant sentences)")

        # Passage — truncate at 600 chars so Claude has room to reason
        if len(text) > 600:
            text = text[:600].rsplit(" ", 1)[0] + "..."
        lines.append(f'"{text}"')
        lines.append("")

    lines.append(f"━" * 50)
    lines.append(f"Found {len(chunks)} relevant passage(s) from SEC filings.")

    return "\n".join(lines)