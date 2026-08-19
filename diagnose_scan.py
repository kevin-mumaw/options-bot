"""
Run this from the SAME folder as options_bot.py and your .env file.

Usage:  python diagnose_scan.py SPY
        python diagnose_scan.py        (defaults to SPY)
"""
import sys
import os
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

ticker = sys.argv[1].upper() if len(sys.argv) > 1 else "SPY"
print(f"--- Diagnosing {ticker} ---")
print("Data source: yfinance (no key/account required).")

# 1. Spot price
spot_hist = yf.Ticker(ticker).history(period="5d")
if spot_hist.empty:
    print("STOP: yfinance returned no price history for this ticker.")
    sys.exit(1)
spot = spot_hist['Close'].iloc[-1]
print(f"Spot price: ${spot:.2f}")

# 2. Expirations
try:
    expirations = sorted(yf.Ticker(ticker).options)
except Exception as e:
    print(f"STOP: yfinance raised an error fetching expirations: {e}")
    sys.exit(1)
print(f"Expirations returned: {len(expirations)}")
print(f"First few: {expirations[:8]}")

if not expirations:
    print("STOP: yfinance returned no expirations at all for this ticker.")
    sys.exit(1)

current_date = datetime.now()
min_date = current_date + timedelta(days=30)
max_date = current_date + timedelta(days=75)
print(f"Looking for expiration between {min_date.date()} and {max_date.date()}")

candidates = []
for date_str in expirations:
    try:
        exp_date = datetime.strptime(date_str, "%Y-%m-%d")
        if min_date <= exp_date <= max_date:
            candidates.append((date_str, exp_date))
    except Exception:
        continue

target_date = None
for date_str, exp_date in candidates:
    if exp_date.weekday() == 4 and 15 <= exp_date.day <= 21:
        target_date = date_str
        print(f"Found monthly (3rd Friday) expiration: {target_date}")
        break
if not target_date and candidates:
    target_date = candidates[0][0]
    print(f"No monthly found in window, falling back to first available: {target_date}")

print(f"Target expiration selected: {target_date}")
if not target_date:
    print("STOP: no expiration falls in the 30-75 day window.")
    print(f"All available expirations: {expirations}")
    sys.exit(1)

# 3. Option chain
try:
    chain = yf.Ticker(ticker).option_chain(target_date)
except Exception as e:
    print(f"STOP: yfinance raised an error fetching the chain: {e}")
    sys.exit(1)
print(f"Total contracts (calls+puts) returned: {len(chain.calls) + len(chain.puts)}")

if chain.calls.empty and chain.puts.empty:
    print("STOP: yfinance returned no contracts for this expiration.")
    sys.exit(1)

print(f"Calls only: {len(chain.calls)}")

contracts_list = []
for _, opt in chain.calls.iterrows():
    contracts_list.append({
        'strike': opt.get('strike'),
        'bid': opt.get('bid') or 0,
        'ask': opt.get('ask') or 0,
        'openInterest': opt.get('openInterest') or 0,
        'impliedVolatility': opt.get('impliedVolatility') or 0.35
    })

calls = pd.DataFrame(contracts_list)
print(f"\nSample of parsed calls (first 5 rows):")
print(calls.head(5).to_string())

liquid = calls[calls['openInterest'].fillna(0) >= 500].copy()
print(f"\nCalls with openInterest >= 500: {len(liquid)}")
if liquid.empty:
    print("STOP: liquidity filter (OI >= 500) rejected everything.")
    print(f"Open interest values seen: {sorted(calls['openInterest'].tolist())}")
    sys.exit(1)

liquid = liquid.sort_values('strike').reset_index(drop=True)
step_size = 5.0 if spot > 250 else (2.5 if spot > 100 else 1.0)
atm_calls = liquid[(liquid['strike'] >= spot * 0.90) & (liquid['strike'] <= spot * 1.10)].copy()
print(f"ATM calls (within 10% of spot ${spot:.2f}): {len(atm_calls)}")
print(f"ATM strikes: {sorted(atm_calls['strike'].tolist())}")

avg_iv = atm_calls['impliedVolatility'].mean() if not atm_calls.empty else 0
print(f"Average IV of ATM calls: {avg_iv:.3f} (need >= 0.20)")
if avg_iv < 0.20:
    print("STOP: volatility filter rejected this ticker.")
    sys.exit(1)

print("\nPassed all filters through volatility check.")
print(f"Step size for spread math: {step_size}")
print(atm_calls.to_string())