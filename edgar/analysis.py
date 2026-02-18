"""
Financial Analysis Engine
Pure calculation logic — no API calls, no MCP, just math.

Takes already-parsed financial data from parser.py and produces insights.
This is what makes Tōshi different from every other SEC EDGAR MCP server.

Flow: tools/analysis.py → analysis.py → (uses already cached parser data)
"""

from typing import Optional


# Thresholds for anomaly detection
# These are based on general financial analysis rules of thumb
ANOMALY_THRESHOLDS = {
    "revenue":              {"warning": 20, "critical": 40},   # % YoY change
    "net_income":           {"warning": 30, "critical": 60},
    "operating_income":     {"warning": 30, "critical": 60},
    "total_debt":           {"warning": 30, "critical": 60},
    "cash":                 {"warning": 30, "critical": 50},
    "operating_cash_flow":  {"warning": 30, "critical": 60},
    "total_assets":         {"warning": 20, "critical": 40},
    "capex":                {"warning": 40, "critical": 80},
}

# Risk scoring weights — how much each ratio contributes to overall risk
RISK_WEIGHTS = {
    "debt_to_equity":       0.25,   # high debt = high risk
    "cash_burn":            0.20,   # burning cash fast = risky
    "revenue_growth":       0.20,   # declining revenue = risky
    "profit_margin":        0.20,   # thin margins = risky
    "cash_coverage":        0.15,   # can they cover debt with cash?
}


# ─────────────────────────────────────────────
# YoY Change Calculations
# ─────────────────────────────────────────────

def calculate_yoy_changes(metric_data: list[dict]) -> list[dict]:
    """
    Calculate year-over-year % change for a list of metric data points.
    metric_data: list of {year, value} dicts sorted most recent first.
    Returns list of {year, value, yoy_change, direction} dicts.
    """
    if len(metric_data) < 2:
        return []

    results = []
    # Compare each year to the previous one
    for i in range(len(metric_data) - 1):
        current = metric_data[i]
        previous = metric_data[i + 1]

        current_val = current.get("value")
        previous_val = previous.get("value")

        if current_val is None or previous_val is None or previous_val == 0:
            continue

        pct_change = ((current_val - previous_val) / abs(previous_val)) * 100
        direction = "▲" if pct_change > 0 else "▼"

        results.append({
            "year": current["year"],
            "value": current_val,
            "previous_value": previous_val,
            "yoy_change": round(pct_change, 1),
            "direction": direction,
        })

    return results


def detect_anomalies_in_metric(metric_name: str, changes: list[dict]) -> list[dict]:
    """
    Flag anomalous YoY changes for a single metric.
    Returns list of flagged anomalies with severity and explanation.
    """
    thresholds = ANOMALY_THRESHOLDS.get(metric_name, {"warning": 25, "critical": 50})
    anomalies = []

    for change in changes:
        abs_change = abs(change["yoy_change"])
        direction = "increased" if change["yoy_change"] > 0 else "decreased"

        # Determine if this is concerning based on metric type
        is_bad = _is_bad_direction(metric_name, change["yoy_change"])

        if abs_change >= thresholds["critical"]:
            severity = "🔴 CRITICAL" if is_bad else "⚠️  NOTABLE"
            anomalies.append({
                "year": change["year"],
                "metric": metric_name,
                "severity": severity,
                "change": change["yoy_change"],
                "message": f"{metric_name.replace('_', ' ').title()} {direction} {abs_change:.1f}% in {change['year']}"
            })
        elif abs_change >= thresholds["warning"]:
            severity = "🟡 WARNING" if is_bad else "ℹ️  NOTE"
            anomalies.append({
                "year": change["year"],
                "metric": metric_name,
                "severity": severity,
                "change": change["yoy_change"],
                "message": f"{metric_name.replace('_', ' ').title()} {direction} {abs_change:.1f}% in {change['year']}"
            })

    return anomalies


def _is_bad_direction(metric_name: str, change: float) -> bool:
    """
    Determine if a change is financially concerning.
    Declining revenue is bad. Declining debt is good. Context matters.
    """
    # These going DOWN is bad
    bad_if_decreasing = {"revenue", "net_income", "operating_income",
                          "gross_profit", "cash", "operating_cash_flow",
                          "stockholders_equity"}
    # These going UP is bad
    bad_if_increasing = {"total_debt", "total_liabilities"}

    if metric_name in bad_if_decreasing:
        return change < 0
    elif metric_name in bad_if_increasing:
        return change > 0
    return False  # neutral metrics like total_assets


# ─────────────────────────────────────────────
# Risk Score Calculations
# ─────────────────────────────────────────────

def calculate_risk_score(metrics: dict) -> dict:
    """
    Calculate an overall financial risk score (0-10) for a company.
    0 = very safe, 10 = very risky.

    metrics: dict of {metric_name: list of {year, value} dicts}
    Returns risk score with breakdown by category.
    """
    scores = {}
    explanations = []

    # 1. Debt to Equity Ratio
    debt_data = metrics.get("total_debt", [])
    equity_data = metrics.get("stockholders_equity", [])
    if debt_data and equity_data:
        debt = debt_data[0].get("value", 0) or 0
        equity = equity_data[0].get("value", 1) or 1
        if equity > 0:
            dte = debt / equity
            score = min(10, dte * 2)  # DTE of 5 = max risk score
            scores["debt_to_equity"] = score
            if dte > 3:
                explanations.append(f"High debt-to-equity ratio of {dte:.1f}x")
            elif dte > 1.5:
                explanations.append(f"Moderate debt-to-equity ratio of {dte:.1f}x")

    # 2. Cash Burn / Coverage
    cash_data = metrics.get("cash", [])
    ocf_data = metrics.get("operating_cash_flow", [])
    if cash_data and ocf_data:
        cash = cash_data[0].get("value", 0) or 0
        ocf = ocf_data[0].get("value", 1) or 1
        if ocf < 0:
            # Burning cash — how many years until empty?
            years_of_cash = cash / abs(ocf) if abs(ocf) > 0 else 10
            score = max(0, 10 - years_of_cash * 2)
            scores["cash_burn"] = score
            explanations.append(f"Negative operating cash flow — {years_of_cash:.1f} years of cash remaining")
        else:
            scores["cash_burn"] = 0  # positive OCF = no burn risk

    # 3. Revenue Growth (last 2 years)
    revenue_data = metrics.get("revenue", [])
    if len(revenue_data) >= 2:
        changes = calculate_yoy_changes(revenue_data[:3])
        if changes:
            avg_growth = sum(c["yoy_change"] for c in changes) / len(changes)
            if avg_growth < -10:
                score = min(10, abs(avg_growth) / 5)
                scores["revenue_growth"] = score
                explanations.append(f"Revenue declining at {abs(avg_growth):.1f}% average per year")
            elif avg_growth < 0:
                scores["revenue_growth"] = 3
                explanations.append(f"Slight revenue decline of {abs(avg_growth):.1f}% average")
            else:
                scores["revenue_growth"] = max(0, 5 - avg_growth / 10)

    # 4. Profit Margin
    revenue_data = metrics.get("revenue", [])
    net_income_data = metrics.get("net_income", [])
    if revenue_data and net_income_data:
        revenue = revenue_data[0].get("value", 1) or 1
        net_income = net_income_data[0].get("value", 0) or 0
        margin = (net_income / revenue) * 100
        if margin < 0:
            scores["profit_margin"] = 8
            explanations.append(f"Negative profit margin of {margin:.1f}%")
        elif margin < 5:
            scores["profit_margin"] = 5
            explanations.append(f"Thin profit margin of {margin:.1f}%")
        elif margin > 20:
            scores["profit_margin"] = 0
        else:
            scores["profit_margin"] = max(0, 5 - margin / 5)

    # 5. Cash Coverage of Debt
    if debt_data and cash_data:
        debt = debt_data[0].get("value", 0) or 0
        cash = cash_data[0].get("value", 0) or 0
        if debt > 0:
            coverage = cash / debt
            if coverage < 0.1:
                scores["cash_coverage"] = 7
                explanations.append(f"Low cash coverage — only {coverage:.1%} of debt covered by cash")
            elif coverage < 0.3:
                scores["cash_coverage"] = 4
            else:
                scores["cash_coverage"] = max(0, 3 - coverage * 2)

    # Calculate weighted final score
    if not scores:
        return {"score": None, "label": "Insufficient Data", "breakdown": {}, "explanations": []}

    total_weight = sum(RISK_WEIGHTS.get(k, 0.1) for k in scores)
    weighted_score = sum(
        scores[k] * RISK_WEIGHTS.get(k, 0.1)
        for k in scores
    ) / total_weight if total_weight > 0 else 0

    final_score = round(min(10, max(0, weighted_score)), 1)

    # Label
    if final_score <= 2:
        label = "🟢 Low Risk"
    elif final_score <= 4:
        label = "🟡 Moderate Risk"
    elif final_score <= 6:
        label = "🟠 Elevated Risk"
    elif final_score <= 8:
        label = "🔴 High Risk"
    else:
        label = "🚨 Very High Risk"

    return {
        "score": final_score,
        "label": label,
        "breakdown": {k: round(v, 1) for k, v in scores.items()},
        "explanations": explanations,
    }