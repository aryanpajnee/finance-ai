import math
import pandas as pd

THRESHOLDS = { #(safe,risky)
    "current_ratio": (2.0, 1.0),
    "debt_to_equity": (0.5, 2.0),
    "interest_coverage": (8.0, 1.5),
    "operating_margin": (0.20, 0.0),
    "revenue_growth": (0.15, 0.0)
}
DEADBAND = 0.175
TREND_DELTA = 8
MIN_TREND_POINTS = 3
TREND_GATE = 40

WEIGHTS = { #(finding weighted sum)
    "current_ratio": 0.20,
    "debt_to_equity": 0.25,
    "interest_coverage": 0.30,
    "operating_margin": 0.15,
    "revenue_growth": 0.10
}

def current_ratio(latest):
    numerator = latest["Current Assets"]
    denominator = latest["Current Liabilities"]
    if pd.isna(numerator):
        return None
    if pd.isna(denominator) or abs(denominator) < 1:
        return None
    else:
        return numerator/denominator

def ratio_series(df):
    rows = []
    for i in range(len(df)):
        prior = df.iloc[i + 1] if i + 1 < len(df) else None
        rows.append((df.index[i], compute_ratios_for(df.iloc[i], prior)))
    rows.reverse()                            # oldest -> newest
    periods = [p for p, _ in rows]
    series = {name: [r[name] for _, r in rows] for name in THRESHOLDS}
    return periods, series

def _higher_is_better(name):
    safe, risky = THRESHOLDS[name]
    return safe > risky                       # D/E -> False, the rest -> True

def trend_delta(name, series, latest_score):   # series oldest->newest
    # v1 limitation: trend = endpoints only (first vs last of the None/inf-filtered points)
    pts = [v for v in series if v is not None and not math.isinf(v)]
    if len(pts) < MIN_TREND_POINTS:
        return 0                              # not enough history -> no score change
    base = abs(pts[0]) if abs(pts[0]) > 1e-9 else 1.0
    rel = (pts[-1] - pts[0]) / base
    if abs(rel) < DEADBAND:
        return 0                              # move too small -> noise, not a trend
    improving = (rel > 0) == _higher_is_better(name)
    delta = -TREND_DELTA if improving else TREND_DELTA
    if delta < 0 and latest_score is not None and latest_score < TREND_GATE:
        return 0                              # already deep in safe zone -> improving trend can't lower it;
                                              # deteriorating trends still pass through (early warning)
    return delta

def adjust_scores(level_scores, series):
    deltas, adjusted = {}, {}
    for name, level in level_scores.items():
        if level is None:
            deltas[name], adjusted[name] = 0, None
            continue
        d = trend_delta(name, series[name], level)
        deltas[name] = d
        adjusted[name] = max(0, min(100, level + d))
    return deltas, adjusted

def debt_to_equity(latest):
    numerator = latest["Total Debt"]
    denominator = latest["Stockholders Equity"]
    if pd.isna(numerator):
        return None
    if pd.isna(denominator) or abs(denominator) < 1:
        return None
    if denominator < 0:
        return float('inf')
    else:
        return numerator/denominator

def interest_coverage(latest):
    numerator = latest["EBIT"]
    denominator = latest["Interest Expense"]
    debt = latest["Total Debt"]
    if pd.isna(numerator):
        return None
    debt_free = not pd.isna(debt) and abs(debt) < 1
    if pd.isna(denominator) or abs(denominator) < 1:
        # no usable interest figure: only claim debt-free (inf -> safest)
        # if the balance sheet actually shows ~zero debt
        return float('inf') if debt_free else None
    # yfinance sometimes reports Interest Expense as a negative number;
    # coverage is conventionally EBIT over the *magnitude* of interest
    return numerator / abs(denominator)

def operating_margin(latest):
    numerator = latest["Operating Income"]
    denominator = latest["Total Revenue"]
    if pd.isna(numerator):
        return None
    if pd.isna(denominator) or abs(denominator) < 1:
        return None
    else:
        return numerator/denominator

def revenue_growth(latest, prior):
    term_1 = latest["Total Revenue"]
    term_2 = prior["Total Revenue"]
    if pd.isna(term_1) or pd.isna(term_2):
        return None
    if term_2 <= 1:            
        return None
    return (term_1 - term_2) / term_2

def compute_ratios_for(latest, prior):
    return {
        "current_ratio":     current_ratio(latest),
        "debt_to_equity":    debt_to_equity(latest),
        "interest_coverage": interest_coverage(latest),
        "operating_margin":  operating_margin(latest),
        "revenue_growth":    revenue_growth(latest, prior) if prior is not None else None,
    }
def compute_ratios(df):                      # unchanged behavior: snapshot = latest year
    prior = df.iloc[1] if len(df) > 1 else None
    return compute_ratios_for(df.iloc[0], prior)

def normalise(safe, risky, value):
    if value is None:
        return None
    score = ((value-safe)/(risky-safe))*100
    return max(0, min(100, score))

def score_ratios(ratios):
    sub_scores = {}
    for name, value in ratios.items():
        sub_scores[name] = normalise(*THRESHOLDS[name], value=value)
    return sub_scores

def final_score(scores):
    total = 0
    weight_sum = 0
    for name, score in scores.items():
        if score is None:
            continue                      # skip missing metrics
        total += WEIGHTS[name] * score
        weight_sum += WEIGHTS[name]
    if weight_sum == 0:
        return None                       # nothing to score
    return total / weight_sum

def assess_risk(df):
    """Run the full risk assessment on a financials DataFrame (rows = periods, newest first).

    Returns a dict:
      "ratios"          latest-year ratio values (None where not computable)
      "scores"          0-100 sub-scores per ratio (None where ratio is None); 0 = safe, 100 = risky
      "final"           weighted point-in-time score, or None if nothing scorable
      "periods"         period labels oldest -> newest
      "series"          per-ratio value lists aligned with "periods"
      "trend_deltas"    per-ratio trend adjustment (+/-TREND_DELTA or 0)
      "scores_adjusted" sub-scores after trend adjustment (clamped 0-100)
      "final_adjusted"  weighted score over the adjusted sub-scores
      "missing"         count of ratios that came back None (inapplicability signal)
    """
    ratios = compute_ratios(df)
    scores = score_ratios(ratios)
    final  = final_score(scores)

    periods, series = ratio_series(df)
    trend_deltas, scores_adjusted = adjust_scores(scores, series)
    final_adjusted = final_score(scores_adjusted)

    return {
        "ratios": ratios, "scores": scores, "final": final,
        "periods": periods, "series": series,
        "trend_deltas": trend_deltas,
        "scores_adjusted": scores_adjusted,
        "final_adjusted": final_adjusted,
        "missing": sum(1 for v in ratios.values() if v is None),
    }

if __name__ == "__main__":
    from data import fetch_financials
    user_ticker = input("Enter ticker symbol:\n")
    df, metadata = fetch_financials(user_ticker)

    if df is None:
        print("No data found. Check the Ticker symbol.")
    else:
        print("Company Information:\n")
        for key, value in metadata.items():
            print(f"{key.replace('_', ' ').title():<14}: {value}")
        print("\n")
        assessment = assess_risk(df)

        print("Ratios:")
        for name, value in assessment["ratios"].items():
            label = name.replace('_', ' ').title()
            if value is None:
                print(f"{label}: N/A")
            elif name in ("operating_margin", "revenue_growth"):
                print(f"{label}: {value * 100:.2f}%")
            else:
                print(f"{label}: {value:.2f}")

        print("\nScores:")
        for name, value in assessment["scores"].items():
            label = name.replace('_', ' ').title()
            if value is None:
                print(f"{label}: N/A")
            else:
                print(f"{label}: {value:.2f}")

        final = assessment["final"]
        print(f"\nFinal Score: {'N/A' if final is None else f'{final:.2f}'}")
        final_adjusted = assessment["final_adjusted"]
        print(f"Final Score (trend-adjusted): {'N/A' if final_adjusted is None else f'{final_adjusted:.2f}'}")
        print(f"Missing ratios: {assessment['missing']}")
