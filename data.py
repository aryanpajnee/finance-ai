import time
import yfinance as yf
import pandas as pd

balance_items = ["Total Debt" ,
    "Total Assets" ,
    "Current Assets" ,
    "Current Liabilities" ,
    "Stockholders Equity" ,
    "Cash And Cash Equivalents" ]

income_items = ["Total Revenue" ,
    "Gross Profit" ,
    "Operating Income" ,
    "EBIT" ,
    "EBITDA" ,
    "Interest Expense" ,
    "Pretax Income" ,
    "Tax Provision",
    "Net Income"]

cashflow_items = ["Operating Cash Flow" ,
    "Free Cash Flow" ,
    "Capital Expenditure" ]


def safe_extract(df, items):
    return df.reindex(items)


def format_market_cap(value):
    if value is None:
        return "N/A"
    for threshold, suffix in [(1e12, "T"), (1e9, "B"), (1e6, "M")]:
        if abs(value) >= threshold:
            return f"{value / threshold:,.4f} {suffix}"
    return f"{value:,.0f}"

def fetch_financials(ticker):
    for attempt in range(3):
        try:
            stock = yf.Ticker(ticker)
            balance = stock.balance_sheet
            income = stock.income_stmt
            cashflow = stock.cash_flow
            info = stock.info
            if not balance.empty and not income.empty:
                break          # got the data -> stop retrying
        except Exception:
            pass               # network hiccup -> fall through to retry
        time.sleep(2)
    else:
        return None, None      # all 3 attempts failed

    balance_extracted = safe_extract(df=balance, items=balance_items)
    income_extracted = safe_extract(df=income, items=income_items)
    cashflow_extracted = safe_extract(df=cashflow, items=cashflow_items)

    combined = pd.concat(
        [balance_extracted, income_extracted, cashflow_extracted], axis=0, sort=False
    )
    combined = combined.dropna(axis=1, how="all")

    metadata = {
        "name": info.get("longName"),
        "sector": info.get("sector"),
        "market_cap": format_market_cap(info.get("marketCap")),
        "currency": info.get("currency"),
    }

    return combined.T, metadata

if __name__ == "__main__":
    user_ticker = input("Enter ticker symbol:\n")
    df, metadata = fetch_financials(user_ticker)

    if df is None:
        print("No data found. Check the Ticker symbol.")
    else:
        print("Company Information:\n")
        for key, value in metadata.items():
            print(f"{key.replace('_', ' ').title():<14}: {value}")
        print("\n")
        print("Financial Information:\n")
        print(df)



