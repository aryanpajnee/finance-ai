import math
from llm import get_llm_response


def _format_raw(name, raw):
    """Format a raw ratio value for the prompt (mirrors app.py's display logic)."""
    if raw is None:
        return "not available"
    if name == "debt_to_equity" and math.isinf(raw):
        return "negative equity (insolvent)"
    if name == "interest_coverage" and math.isinf(raw):
        return "no debt / fully covered"
    if name in ("operating_margin", "revenue_growth"):
        return f"{raw * 100:.2f}%"
    return f"{raw:.2f}"

def _trajectory(name, series, periods):
    """Build an oldest→newest path like '4.10 → 3.05 → 2.23', skipping missing years."""
    pairs = [(p, v) for p, v in zip(periods, series[name]) if v is not None]
    if len(pairs) < 2:
        return None
    return " → ".join(_format_raw(name, v) for _, v in pairs)


def build_facts(metadata, result):
    lines = [
        f"Company: {metadata['name']}",
        f"Sector: {metadata['sector'] or 'Unknown'}",
    ]
    final = result["final"]
    final_adj = result["final_adjusted"]
    if final_adj is None:
        lines.append("Overall risk score: could not be computed (insufficient data)")
    else:
        lines.append(
            f"Overall risk score (trend-adjusted): {final_adj:.1f}/100 "
            f"(point-in-time before trend: {final:.1f}/100; 0 = least risky, 100 = most risky)"
        )

    lines.append("")
    lines.append(
        "Metric breakdown — raw value, point-in-time risk sub-score (higher = riskier), "
        "trend adjustment, and the multi-year trajectory:"
    )
    for name in result["ratios"]:
        raw = result["ratios"][name]
        sub = result["scores"][name]
        label = name.replace("_", " ").title()
        if raw is None:
            lines.append(f"- {label}: not available")
            continue
        delta = result["trend_deltas"][name]
        traj = _trajectory(name, result["series"], result["periods"])
        trend_txt = f"trend {'+' if delta > 0 else ''}{delta} risk" if delta else "trend flat/short"
        traj_txt = f"; over time {traj}" if traj else ""
        lines.append(f"- {label}: {_format_raw(name, raw)}  (risk {sub:.0f}/100, {trend_txt}){traj_txt}")
    return "\n".join(lines)


def generate_risk_summary(metadata, result):
    facts = build_facts(metadata, result)

    SYSTEM_PROMPT = """You are a financial risk analyst explaining an assessment to someone with no finance background.
    All companies are Indian; use rupees (₹) or avoid currency units entirely — never dollars/cents.

A separate scoring SYSTEM has already computed everything below from the company's
financial statements. You do NOT recompute, re-judge, or second-guess the numbers.
Your only job is to explain what they mean in plain English.

You will receive:
- An overall risk score from 0 (least risky) to 100 (most risky)
- Individual metrics, each with its raw value and its risk sub-score

ASSESSMENT:
{facts}

Rules:
- Explain in plain language a non-expert understands. No jargon without a one-line definition.
- Ground every statement in the numbers given. Do not introduce outside facts, news, or figures.
- If a metric is marked unavailable, say so plainly and do not speculate why or guess a value.
- State the 2-3 metrics driving the score most, and say whether each pushes risk up or down.
- Be honest and balanced — do not soften a high-risk score or inflate a low one.
- If overall confidence is low (several metrics missing), say the assessment is limited.
- Keep it under 200 words. End with one plain-language sentence summarising the overall risk.
- The overall score is TREND-ADJUSTED: a metric worsening across the years adds risk, improving subtracts (within a small bound). When a trajectory is shown, state the direction and whether it pushed risk up or down — do not re-derive or dispute the score.
- A single year's value can look fine while the trajectory tells a different story (e.g. a current ratio of 2.23 that fell from 4.10 → 3.05 → 2.23). Call that out when it happens.

Do not give investment advice or tell the user to buy/sell/hold."""

    prompt = SYSTEM_PROMPT.replace("{facts}", facts)
    return get_llm_response(prompt)


if __name__ == "__main__":
    from data import fetch_financials
    from risk import assess_risk

    for tkr in ["TCS.NS", "IDEA.NS", "ICICIBANK.NS"]:
        df, metadata = fetch_financials(tkr)
        result = assess_risk(df)
        print(f"\n{'=' * 60}\n{tkr}\n{'=' * 60}")
        print(generate_risk_summary(metadata, result))
