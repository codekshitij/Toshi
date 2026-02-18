"""
Analysis Tools
MCP tools for financial anomaly detection and risk scoring.

Correct flow:
tools/analysis.py → parser.get_parsed_company_facts() → client.py

Tools never call client directly — parser handles fetch + clean.
"""

from edgar import parser
from edgar import analysis


ANOMALY_METRICS = [
    "revenue", "net_income", "operating_income",
    "total_debt", "cash", "operating_cash_flow", "capex"
]

RISK_METRICS = [
    "revenue", "net_income", "total_debt",
    "stockholders_equity", "cash", "operating_cash_flow"
]


def detect_anomalies(cik_padded: str) -> str:
    """
    Detect unusual year-over-year changes in a company's financials.
    Flags red flags like sudden debt spikes, revenue drops, or cash burn.
    Use search_company first to get the CIK number.
    """
    # parser handles fetch + cache + clean — tool never touches client
    data = parser.get_parsed_company_facts(cik_padded, ANOMALY_METRICS, years=5)
    company_name = data["company_name"]
    all_anomalies = []

    for metric_name, rows in data["metrics"].items():
        if len(rows) < 2:
            continue
        changes = analysis.calculate_yoy_changes(rows)
        anomalies = analysis.detect_anomalies_in_metric(metric_name, changes)
        all_anomalies.extend(anomalies)

    if not all_anomalies:
        return (
            f"Anomaly Detection: {company_name}\n"
            f"{'=' * 50}\n"
            f"✅ No significant anomalies detected in the last 5 years.\n"
            f"All major financial metrics are within normal ranges."
        )

    severity_order = {"🔴 CRITICAL": 0, "🟡 WARNING": 1, "⚠️  NOTABLE": 2, "ℹ️  NOTE": 3}
    all_anomalies.sort(key=lambda x: (severity_order.get(x["severity"], 9), x["year"]))

    lines = [
        f"Anomaly Detection: {company_name}",
        "=" * 50,
        f"Found {len(all_anomalies)} anomalies:\n",
    ]

    for a in all_anomalies:
        lines.append(f"{a['severity']}  {a['message']}")

    lines.append("\nNote: Anomalies are not necessarily bad — always investigate context.")
    return "\n".join(lines)


def get_risk_score(cik_padded: str) -> str:
    """
    Calculate a financial risk score (0-10) for a company based on SEC filings.
    Analyzes debt levels, cash burn, revenue trends, profit margins, and more.
    Use search_company first to get the CIK number.
    0-2 = Low Risk | 3-4 = Moderate | 5-6 = Elevated | 7-8 = High | 9-10 = Very High
    """
    # parser handles fetch + cache + clean — tool never touches client
    data = parser.get_parsed_company_facts(cik_padded, RISK_METRICS, years=5)
    company_name = data["company_name"]

    risk = analysis.calculate_risk_score(data["metrics"])

    if risk["score"] is None:
        return f"Risk Score: {company_name}\nInsufficient financial data to calculate risk score."

    lines = [
        f"Risk Score: {company_name}",
        "=" * 50,
        f"\nOverall Score: {risk['score']}/10  {risk['label']}\n",
    ]

    if risk["breakdown"]:
        lines.append("Score Breakdown:")
        label_map = {
            "debt_to_equity":   "Debt to Equity",
            "cash_burn":        "Cash Burn Rate",
            "revenue_growth":   "Revenue Growth",
            "profit_margin":    "Profit Margin",
            "cash_coverage":    "Cash Coverage",
        }
        for factor, score in risk["breakdown"].items():
            bar = "█" * int(score) + "░" * (10 - int(score))
            label = label_map.get(factor, factor.replace("_", " ").title())
            lines.append(f"  {label:<20} {bar} {score}/10")

    if risk["explanations"]:
        lines.append("\nKey Concerns:")
        for explanation in risk["explanations"]:
            lines.append(f"  • {explanation}")
    else:
        lines.append("\n✅ No major financial concerns identified.")

    lines.append("\nDisclaimer: Based on SEC filing data only. Not financial advice.")
    return "\n".join(lines)