import yfinance as yf

stock = yf.Ticker("SHAILY.NS")

print("=== INCOME STATEMENT ===")
print(stock.financials)

print("\n=== BALANCE SHEET ===")
print(stock.balance_sheet)

print("\n=== CASH FLOW ===")
print(stock.cashflow)
