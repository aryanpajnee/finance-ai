import pandas as pd

def current_ratio(latest):
    numerator = latest["Current Assets"]
    denominator = latest["Current Liabilities"]
    if pd.isna(numerator):
        return None
    if pd.isna(denominator) or abs(denominator)<1:
        return None
    else:
        return numerator/denominator

def debt_to_equity(latest):
    numerator = latest["Total Debt"]
    denominator = latest["Stockholders Equity"]
    if pd.isna(numerator):
        return None
    if pd.isna(denominator) or abs(denominator)<1:
        return None
    if denominator < 0:
        return float('inf')
    else:
        return numerator/denominator

def interest_coverage(latest):
    numerator = latest["EBIT"]
    denominator = latest["Interest Expense"]
    if pd.isna(numerator):
        return None                 
    if pd.isna(denominator) or abs(denominator) < 1:
        return float('inf')
    return numerator / denominator

def operating_margin(latest):
    numerator = latest["Operating Income"]
    denominator =latest["Total Revenue"]
    if pd.isna(numerator):
        return None
    if pd.isna(denominator) or abs(denominator)<1:
        return None
    else:
        return numerator/denominator

def revenue_growth(latest,prior):
    term_1 = latest["Total Revenue"]
    term_2 = prior["Total Revenue"]
    if pd.isna(term_1):
        return None
    if pd.isna(term_2) or abs(term_2)<1:
        return None
    else:
        return (term_1-term_2)/term_2

def compute_ratios(df):
    latest = df.iloc[0]
    prior = df.iloc[1] if len(df) > 1 else None
    return {
        "current_ratio":     current_ratio(latest),
        "debt_to_equity":    debt_to_equity(latest),
        "interest_coverage": interest_coverage(latest),
        "operating_margin":  operating_margin(latest),
        "revenue_growth":    revenue_growth(latest, prior) if prior is not None else None,
    }
    
THRESHOLDS = { #(safe,risky)
    "current_ratio": (2.0,1.0),
    "debt_to_equity": (0.5 , 2.0),
    "interest_coverage": (8.0 , 1.5),
    "operating_margin": (0.20, 0.0),
    "revenue_growth": (0.15 , 0.0)
}
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

WEIGHTS ={#(finding weighted sum)
         "current_ratio": 0.20,
        "debt_to_equity":0.25 ,
        "interest_coverage":0.30,
        "operating_margin": 0.15,
        "revenue_growth":0.10 
    }

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
    ratios = compute_ratios(df)
    scores = score_ratios(ratios)
    final = final_score(scores)

    return {
        "ratios": ratios,
        "scores": scores,
        "final" : final
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
        ratios = compute_ratios(df)
        for name, value in ratios.items():
            label = name.replace('_', ' ').title()
            if value is None:
                print(f"{label}: N/A")
            elif name in ("operating_margin", "revenue_growth"):
                print(f"{label}: {value * 100:.2f}%")
            else:
                print(f"{label}: {value:.2f}")

        scores = score_ratios(ratios)
        print("\n")
        print("Risk Scores:")
        for name, score in scores.items():
            print(f"{name.replace('_',' ').title()}:{score:.2f}")
        weighted_sum = final_score(scores)
        print(f"\nWeighted Sum:{weighted_sum:.2f}")
        assessment = assess_risk(df)

        print("\nRatios:")
        for name, value in assessment["ratios"].items():
            label = name.replace('_', ' ').title()
            if value is None:
                print(f"{label}: N/A")
            else:
                print(f"{label}: {value:.2f}")

        print("\nScores:")
        for name, value in assessment["scores"].items():
            label = name.replace('_', ' ').title()
            print(f"{label}:{value:.2f}")

        print(f"\nFinal Score:{assessment['final']:.2f}")
                   
                

        
        
        