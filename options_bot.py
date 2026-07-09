import yfinance as yf
import pandas as pd
import requests
import json
import os
import math
import time
import csv
import base64
import io
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv

# Automatically finds your .env file and loads your keys into local memory
load_dotenv()

PORTFOLIO_FILE = "portfolio.json"
TRADIER_BASE_URL = "https://api.tradier.com/v1"

# Liquid universe: top ~200 S&P 500 companies by market cap (covers nearly all Nasdaq 100
# names too, since those are dominated by the same mega-caps) + the standard heavily-traded
# ETF universe. This is the RAW candidate pool -- filter_liquid_universe() below cuts it
# down to genuinely tradable names by real volume/price before any options data is pulled.
UNIVERSE = [
    "AAPL", "ABBV", "ABNB", "ABT", "ACN", "ADBE", "ADI", "ADP",
    "AEP", "AFL", "AJG", "ALL", "AMAT", "AMD", "AMGN", "AMT",
    "AMZN", "ANET", "AON", "APD", "APH", "APO", "APP", "ARKK",
    "AVGO", "AXP", "BA", "BAC", "BKNG", "BLK", "BMY", "BNY",
    "BRK.B", "BSX", "BX", "C", "CAT", "CB", "CDNS", "CEG",
    "CI", "CL", "CMCSA", "CME", "CMI", "COF", "COHR", "COP",
    "COST", "CRH", "CRM", "CRWD", "CSCO", "CSX", "CTAS", "CVS",
    "CVX", "D", "DASH", "DDOG", "DE", "DELL", "DHR", "DIA",
    "DIS", "DLR", "DUK", "ECL", "EEM", "ELV", "EMR", "EOG",
    "EQIX", "ETN", "EWJ", "EWZ", "FCX", "FDX", "FIX", "FTNT",
    "FXI", "GD", "GDX", "GDXJ", "GE", "GEV", "GILD", "GLD",
    "GLW", "GM", "GOOG", "GOOGL", "GS", "GWW", "HCA", "HD",
    "HLT", "HON", "HONA", "HOOD", "HWM", "HYG", "IBB", "IBM",
    "ICE", "INTC", "INTU", "ISRG", "ITB", "ITW", "IWM", "IYR",
    "JCI", "JETS", "JNJ", "JPM", "KKR", "KLAC", "KMI", "KO",
    "KRE", "KWEB", "LIN", "LLY", "LMT", "LOW", "LQD", "LRCX",
    "MA", "MAR", "MCD", "MCK", "MCO", "MDLZ", "MDT", "META",
    "MMM", "MNST", "MO", "MPC", "MPWR", "MRK", "MRSH", "MRVL",
    "MS", "MSFT", "MSI", "MU", "NEE", "NEM", "NFLX", "NKE",
    "NOC", "NOW", "NSC", "NVDA", "NXPI", "ORCL", "ORLY", "PANW",
    "PCAR", "PEP", "PFE", "PG", "PGR", "PH", "PLD", "PLTR",
    "PM", "PNC", "PSX", "PWR", "QCOM", "QQQ", "RCL", "REGN",
    "ROST", "RSG", "RTX", "SBUX", "SCHW", "SHW", "SLB", "SLV",
    "SMH", "SNDK", "SNPS", "SO", "SOXL", "SOXS", "SOXX", "SPG",
    "SPGI", "SPY", "SQQQ", "STX", "SYK", "T", "TDG", "TFC",
    "TJX", "TLT", "TMO", "TMUS", "TQQQ", "TRV", "TSLA", "TT",
    "TXN", "UBER", "UNG", "UNH", "UNP", "UPS", "URI", "USB",
    "USO", "UVXY", "V", "VLO", "VNQ", "VRT", "VRTX", "VXX",
    "VZ", "WBD", "WDC", "WELL", "WFC", "WM", "WMB", "WMT",
    "XBI", "XHB", "XLB", "XLC", "XLE", "XLF", "XLI", "XLK",
    "XLP", "XLRE", "XLU", "XLV", "XLY", "XOM", "XOP",
]

MIN_AVG_VOLUME = 1_000_000   # avg daily shares traded -- proxy for tight bid/ask spreads
MIN_PRICE = 10.0             # skip penny-priced noise

BACKTEST_LOG_FILE = "backtest_log.csv"
BACKTEST_LOG_COLUMNS = [
    "run_date", "ticker", "type", "expiration", "spot_at_scan",
    "long_strike", "short_strike", "low_strike", "mid_strike", "high_strike",
    "net_cost", "max_profit", "prob_profit", "ev",
    "graded", "actual_spot_at_exp", "actual_payoff", "actual_pnl", "win"
]

def log_setups_to_csv(setups, log_file=BACKTEST_LOG_FILE):
    """Appends every candidate setup found (not just the top 3 shown to the user) to a CSV,
    so we can later check what actually happened at expiration and see whether this
    tool's probability/EV estimates are calibrated to reality. Ungraded fields are left
    blank until grade_backtest.py fills them in after expiration passes."""
    run_date = datetime.now().strftime("%Y-%m-%d")
    file_exists = os.path.exists(log_file)
    try:
        with open(log_file, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=BACKTEST_LOG_COLUMNS)
            if not file_exists:
                writer.writeheader()
            for s in setups:
                row = {col: s.get(col, "") for col in BACKTEST_LOG_COLUMNS}
                row["run_date"] = run_date
                row["graded"] = "no"
                writer.writerow(row)
    except Exception as e:
        print(f" [!] Couldn't write to {log_file}: {e}")


def log_setups_to_github(setups, repo, token, branch="main", path=BACKTEST_LOG_FILE):
    """Appends setups directly to backtest_log.csv in the GitHub repo via the Contents API.
    Used when running somewhere with no persistent local disk (Streamlit Cloud), so
    mobile-triggered screener runs still end up in the same history as desktop runs
    instead of vanishing on the next redeploy."""
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}
    api_url = f"https://api.github.com/repos/{repo}/contents/{path}"
    run_date = datetime.now().strftime("%Y-%m-%d")

    try:
        res = requests.get(api_url, headers=headers, params={"ref": branch}, timeout=15)
        if res.status_code == 200:
            data = res.json()
            sha = data["sha"]
            existing_content = base64.b64decode(data["content"]).decode("utf-8")
        elif res.status_code == 404:
            sha = None
            existing_content = ",".join(BACKTEST_LOG_COLUMNS) + "\n"
        else:
            print(f" [!] GitHub fetch failed ({res.status_code}): {res.text[:200]}")
            return
    except Exception as e:
        print(f" [!] GitHub fetch error: {e}")
        return

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=BACKTEST_LOG_COLUMNS)
    for s in setups:
        row = {col: s.get(col, "") for col in BACKTEST_LOG_COLUMNS}
        row["run_date"] = run_date
        row["graded"] = "no"
        writer.writerow(row)

    updated_content = existing_content
    if not updated_content.endswith("\n"):
        updated_content += "\n"
    updated_content += buf.getvalue()

    commit_payload = {
        "message": f"Log {len(setups)} candidate setups from mobile screener run ({run_date})",
        "content": base64.b64encode(updated_content.encode("utf-8")).decode("utf-8"),
        "branch": branch,
    }
    if sha:
        commit_payload["sha"] = sha

    try:
        put_res = requests.put(api_url, headers=headers, json=commit_payload, timeout=15)
        if put_res.status_code not in (200, 201):
            print(f" [!] GitHub commit failed ({put_res.status_code}): {put_res.text[:200]}")
    except Exception as e:
        print(f" [!] GitHub commit error: {e}")


def log_setups(setups):
    """Logs candidate setups to the backtest history -- straight to GitHub if a
    GITHUB_TOKEN/GITHUB_REPO secret is present (Streamlit Cloud, no persistent local
    disk), otherwise to the local CSV file (desktop CLI)."""
    github_token = os.getenv("GITHUB_TOKEN")
    github_repo = os.getenv("GITHUB_REPO")
    if github_token and github_repo:
        branch = os.getenv("GITHUB_BRANCH", "main")
        log_setups_to_github(setups, github_repo, github_token, branch=branch)
    else:
        log_setups_to_csv(setups)


def filter_liquid_universe(tickers, progress=print):
    """Cuts the raw universe down to genuinely liquid names using Tradier's batch quote
    endpoint (a handful of calls for the whole universe), BEFORE spending option-chain
    calls on names that wouldn't qualify anyway. Real options IV/liquidity is still checked
    per-ticker later in scan_single_ticker -- this stage only screens on price/volume."""
    token = os.getenv("TRADIER_API_KEY")
    if not token:
        return []
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    liquid = []
    batch_size = 100
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i + batch_size]
        try:
            res = requests.get(f"{TRADIER_BASE_URL}/markets/quotes",
                                params={"symbols": ",".join(batch)},
                                headers=headers, timeout=15).json()
            quotes = (res.get('quotes') or {}).get('quote', [])
            if isinstance(quotes, dict):
                quotes = [quotes]
            for q in quotes:
                price = q.get('last') or 0
                avg_vol = q.get('average_volume') or 0
                if price >= MIN_PRICE and avg_vol >= MIN_AVG_VOLUME:
                    liquid.append(q.get('symbol'))
        except Exception as e:
            progress(f" [!] Liquidity batch {i}-{i+batch_size}: {e}")
    return liquid

def load_portfolio():
    # On Streamlit Cloud, real position data comes from a secret (never committed to the
    # public repo). Locally, the CLI keeps reading portfolio.json as before.
    inline_json = os.getenv("PORTFOLIO_JSON")
    if inline_json:
        try:
            return json.loads(inline_json)
        except Exception:
            return None
    if not os.path.exists(PORTFOLIO_FILE): return None
    try:
        with open(PORTFOLIO_FILE, "r") as f: return json.load(f)
    except: return None

def get_macro_expiration(expirations):
    """Prefers the standard monthly expiration (3rd Friday) inside the 30-75 day window,
    since monthly contracts carry far deeper open interest than nearby weeklies. Falls back
    to the first available date in the window if no monthly expiration is found."""
    current_date = datetime.now()
    min_date = current_date + timedelta(days=30)
    max_date = current_date + timedelta(days=75)
    candidates = []
    for date_str in expirations:
        try:
            exp_date = datetime.strptime(date_str, "%Y-%m-%d")
            if min_date <= exp_date <= max_date:
                candidates.append((date_str, exp_date))
        except:
            continue
    if not candidates:
        return None
    for date_str, exp_date in candidates:
        if exp_date.weekday() == 4 and 15 <= exp_date.day <= 21:  # 3rd Friday of the month
            return date_str
    return candidates[0][0]  # no monthly in range, fall back to first available

def filter_contract_liquidity(df):
    if df.empty: return df
    if 'openInterest' in df.columns:
        df['openInterest'] = df['openInterest'].fillna(0)
        return df[df['openInterest'] >= 500].copy()
    return pd.DataFrame()

def check_volatility_environment(atm_calls):
    if atm_calls.empty: return False
    avg_iv = atm_calls['impliedVolatility'].mean() if 'impliedVolatility' in atm_calls.columns else 0
    return avg_iv >= 0.20

def prob_finish_above(spot, strike, iv, days_to_exp):
    """Risk-neutral probability the stock finishes above `strike` at expiration, assuming
    lognormal returns (standard Black-Scholes N(d2), risk-free rate treated as 0 for
    simplicity). This is an approximation -- it ignores dividends, skew beyond the IV you
    feed it, and early assignment -- but it's a meaningful upgrade over a raw payout ratio
    that ignores likelihood entirely."""
    if iv <= 0 or days_to_exp <= 0 or spot <= 0 or strike <= 0:
        return 0.5  # neutral fallback if inputs are unusable
    T = days_to_exp / 365.0
    d2 = (math.log(spot / strike) - 0.5 * iv * iv * T) / (iv * math.sqrt(T))
    return 0.5 * (1 + math.erf(d2 / math.sqrt(2)))
def get_tradier_quote(symbol, headers):
    res = requests.get(f"{TRADIER_BASE_URL}/markets/quotes",
                        params={"symbols": symbol}, headers=headers, timeout=10).json()
    q = (res.get('quotes') or {}).get('quote')
    if isinstance(q, list):
        q = q[0] if q else None
    return q

def get_tradier_chain(symbol, expiration, headers):
    res = requests.get(f"{TRADIER_BASE_URL}/markets/options/chains",
                        params={"symbol": symbol, "expiration": expiration},
                        headers=headers, timeout=10).json()
    options = (res.get('options') or {}).get('option', [])
    if isinstance(options, dict):
        options = [options]
    return options

def track_live_portfolio():
    portfolio = load_portfolio()
    if not portfolio: return f"\n[!] Configuration file '{PORTFOLIO_FILE}' not found or is empty."
    token = os.getenv("TRADIER_API_KEY")
    if not token: return "\n[!] TRADIER_API_KEY not set -- can't pull live prices."
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    report = "\n" + "═"*60 + "\n          LIVE OPTIONS PORTFOLIO RISK TRACKER\n" + "═"*60 + "\n"
    if portfolio.get("butterfly_spreads"):
        report += "─── ACTIVE BUTTERFLY SPREADS ───\n"
        for bfly in portfolio["butterfly_spreads"]:
            try:
                tk = bfly["ticker"]
                quote = get_tradier_quote(tk, headers)
                if not quote:
                    report += f" [!] {tk}: no quote returned\n\n"
                    continue
                spot = quote.get('last') or 0
                calls = [o for o in get_tradier_chain(tk, bfly["expiration"], headers) if o.get('option_type') == 'call']
                low_rows = [o for o in calls if o.get('strike') == bfly['long_low_strike']]
                mid_rows = [o for o in calls if o.get('strike') == bfly['short_mid_strike']]
                high_rows = [o for o in calls if o.get('strike') == bfly['long_high_strike']]
                if not (low_rows and mid_rows and high_rows):
                    report += f" [!] {tk}: couldn't find one or more strikes in the {bfly['expiration']} chain\n\n"
                    continue
                p_low = ((low_rows[0].get('bid') or 0) + (low_rows[0].get('ask') or 0)) / 2
                p_mid = ((mid_rows[0].get('bid') or 0) + (mid_rows[0].get('ask') or 0)) / 2
                p_high = ((high_rows[0].get('bid') or 0) + (high_rows[0].get('ask') or 0)) / 2
                current_value = p_low + p_high - (2 * p_mid)
                pnl = (current_value - bfly["entry_debit"]) * 100 * bfly["contracts"]
                dist_from_pin = abs(spot - bfly["short_mid_strike"])
                report += f" [{tk.upper()}] Spot: ${spot:.2f} | Exp: {bfly['expiration']}\n   * Net Premium: Entry: ${bfly['entry_debit']:.2f} | Current Mid: ${current_value:.2f}\n   * Position PnL: ${pnl:+.2f} | Distance to Pin: ${dist_from_pin:.2f}\n\n"
            except Exception as e:
                report += f" [!] {bfly.get('ticker', '?')}: {e}\n\n"
    if portfolio.get("bullish_debit_spreads"):
        report += "─── ACTIVE BULLISH DEBIT SPREADS ───\n"
        for spread in portfolio["bullish_debit_spreads"]:
            try:
                tk = spread["ticker"]
                quote = get_tradier_quote(tk, headers)
                if not quote:
                    report += f" [!] {tk}: no quote returned\n\n"
                    continue
                spot = quote.get('last') or 0
                calls = [o for o in get_tradier_chain(tk, spread["expiration"], headers) if o.get('option_type') == 'call']
                long_rows = [o for o in calls if o.get('strike') == spread['long_strike']]
                short_rows = [o for o in calls if o.get('strike') == spread['short_strike']]
                if not (long_rows and short_rows):
                    report += f" [!] {tk}: couldn't find one or more strikes in the {spread['expiration']} chain\n\n"
                    continue
                p_long = ((long_rows[0].get('bid') or 0) + (long_rows[0].get('ask') or 0)) / 2
                p_short = ((short_rows[0].get('bid') or 0) + (short_rows[0].get('ask') or 0)) / 2
                current_value = p_long - p_short
                pnl = (current_value - spread["entry_debit"]) * 100 * spread["contracts"]
                report += f" [{tk.upper()}] Spot: ${spot:.2f} | Exp: {spread['expiration']}\n   * Structure: +${spread['long_strike']}C / -${spread['short_strike']}C\n   * Net Premium: Entry: ${spread['entry_debit']:.2f} | Current Mid: ${current_value:.2f}\n   * Position PnL: ${pnl:+.2f}\n\n"
            except Exception as e:
                report += f" [!] {spread.get('ticker', '?')}: {e}\n\n"
    return report

def get_portfolio_status():
    """Structured version of the portfolio data (same Tradier calls as track_live_portfolio,
    kept separate so that function stays untouched and proven-working). Returns a list of
    position dicts, each either containing full computed stats or an 'error' key."""
    portfolio = load_portfolio()
    if not portfolio:
        return {"error": f"Configuration file '{PORTFOLIO_FILE}' not found or is empty."}
    token = os.getenv("TRADIER_API_KEY")
    if not token:
        return {"error": "TRADIER_API_KEY not set -- can't pull live prices."}
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    positions = []

    for bfly in portfolio.get("butterfly_spreads", []):
        tk = bfly.get("ticker", "?")
        try:
            quote = get_tradier_quote(tk, headers)
            if not quote:
                positions.append({"ticker": tk, "type": "Butterfly Pin", "error": "no quote returned"})
                continue
            spot = quote.get('last') or 0
            calls = [o for o in get_tradier_chain(tk, bfly["expiration"], headers) if o.get('option_type') == 'call']
            low_rows = [o for o in calls if o.get('strike') == bfly['long_low_strike']]
            mid_rows = [o for o in calls if o.get('strike') == bfly['short_mid_strike']]
            high_rows = [o for o in calls if o.get('strike') == bfly['long_high_strike']]
            if not (low_rows and mid_rows and high_rows):
                positions.append({"ticker": tk, "type": "Butterfly Pin", "error": f"couldn't find one or more strikes in the {bfly['expiration']} chain"})
                continue
            p_low = ((low_rows[0].get('bid') or 0) + (low_rows[0].get('ask') or 0)) / 2
            p_mid = ((mid_rows[0].get('bid') or 0) + (mid_rows[0].get('ask') or 0)) / 2
            p_high = ((high_rows[0].get('bid') or 0) + (high_rows[0].get('ask') or 0)) / 2
            current_value = p_low + p_high - (2 * p_mid)
            pnl = (current_value - bfly["entry_debit"]) * 100 * bfly["contracts"]
            dist_from_pin = abs(spot - bfly["short_mid_strike"])
            days_to_exp = (datetime.strptime(bfly["expiration"], "%Y-%m-%d") - datetime.now()).days
            wing_width = bfly["short_mid_strike"] - bfly["long_low_strike"]
            max_profit_per_share = wing_width - bfly["entry_debit"]
            max_profit_total = max_profit_per_share * 100 * bfly["contracts"]
            profit_captured_pct = (pnl / max_profit_total * 100) if max_profit_total > 0 else None
            positions.append({
                "ticker": tk, "type": "Butterfly Pin", "spot": spot, "expiration": bfly["expiration"],
                "days_to_exp": days_to_exp, "entry_debit": bfly["entry_debit"], "current_value": current_value,
                "pnl": pnl, "contracts": bfly["contracts"], "dist_from_pin": dist_from_pin,
                "pin_strike": bfly["short_mid_strike"], "wing_width": wing_width,
                "low_strike": bfly["long_low_strike"], "high_strike": bfly["long_high_strike"],
                "max_profit_total": max_profit_total, "profit_captured_pct": profit_captured_pct,
            })
        except Exception as e:
            positions.append({"ticker": tk, "type": "Butterfly Pin", "error": str(e)})

    for spread in portfolio.get("bullish_debit_spreads", []):
        tk = spread.get("ticker", "?")
        try:
            quote = get_tradier_quote(tk, headers)
            if not quote:
                positions.append({"ticker": tk, "type": "Debit Vertical", "error": "no quote returned"})
                continue
            spot = quote.get('last') or 0
            calls = [o for o in get_tradier_chain(tk, spread["expiration"], headers) if o.get('option_type') == 'call']
            long_rows = [o for o in calls if o.get('strike') == spread['long_strike']]
            short_rows = [o for o in calls if o.get('strike') == spread['short_strike']]
            if not (long_rows and short_rows):
                positions.append({"ticker": tk, "type": "Debit Vertical", "error": f"couldn't find one or more strikes in the {spread['expiration']} chain"})
                continue
            p_long = ((long_rows[0].get('bid') or 0) + (long_rows[0].get('ask') or 0)) / 2
            p_short = ((short_rows[0].get('bid') or 0) + (short_rows[0].get('ask') or 0)) / 2
            current_value = p_long - p_short
            pnl = (current_value - spread["entry_debit"]) * 100 * spread["contracts"]
            days_to_exp = (datetime.strptime(spread["expiration"], "%Y-%m-%d") - datetime.now()).days
            breakeven = spread["long_strike"] + spread["entry_debit"]
            max_value = spread["short_strike"] - spread["long_strike"]
            max_profit_per_share = max_value - spread["entry_debit"]
            max_profit_total = max_profit_per_share * 100 * spread["contracts"]
            profit_captured_pct = (pnl / max_profit_total * 100) if max_profit_total > 0 else None
            positions.append({
                "ticker": tk, "type": "Debit Vertical", "spot": spot, "expiration": spread["expiration"],
                "days_to_exp": days_to_exp, "entry_debit": spread["entry_debit"], "current_value": current_value,
                "pnl": pnl, "contracts": spread["contracts"], "breakeven": breakeven,
                "long_strike": spread["long_strike"], "short_strike": spread["short_strike"],
                "max_profit_total": max_profit_total, "profit_captured_pct": profit_captured_pct,
            })
        except Exception as e:
            positions.append({"ticker": tk, "type": "Debit Vertical", "error": str(e)})

    return {"positions": positions}

def generate_narrative(pos):
    """Plain-language summary of a single position: where it stands, what's driving P/L,
    and general rule-of-thumb context (not personalized advice) on what many options
    traders watch for. Informational only -- not a recommendation to act."""
    if pos.get("error"):
        return f"Couldn't pull live data for {pos['ticker']}: {pos['error']}"

    lines = []
    days = pos["days_to_exp"]
    pnl = pos["pnl"]
    pct = pos.get("profit_captured_pct")

    if days < 0:
        lines.append(f"Expired {abs(days)} day(s) ago ({pos['expiration']}) -- this position should already be closed or settled.")
    else:
        lines.append(f"{days} day(s) to expiration ({pos['expiration']}).")

    if pos["type"] == "Butterfly Pin":
        dist = pos["dist_from_pin"]
        pin = pos["pin_strike"]
        wing = pos["wing_width"]
        lines.append(f"Stock is ${dist:.2f} away from the ${pin:.0f} pin target.")
        if dist <= wing * 0.3:
            lines.append("Price is sitting close to the pin -- this is the sweet spot for a butterfly, worth checking daily as expiration nears.")
        elif dist >= wing * 0.8:
            lines.append("Price has drifted well outside the profit zone -- the original pin thesis looks unlikely to play out unless it reverses.")
    else:  # Debit Vertical
        breakeven = pos["breakeven"]
        short_strike = pos["short_strike"]
        lines.append(f"Breakeven is ${breakeven:.2f}; short strike (max profit point) is ${short_strike:.2f}.")
        if pos["spot"] >= short_strike:
            lines.append("Stock is already at or above the short strike -- this spread is at or near max profit.")
        elif pos["spot"] < breakeven:
            lines.append("Stock is still below breakeven -- needs to move up for this to be profitable by expiration.")

    if pnl > 0 and pct is not None:
        lines.append(f"Currently up ${pnl:+.2f}, roughly {pct:.0f}% of max theoretical profit captured.")
        if pct >= 50:
            lines.append("Many options traders take profits in the 50-75% range on debit spreads rather than holding for full max, since time decay cuts both ways as expiration nears.")
    elif pnl < 0:
        lines.append(f"Currently down ${pnl:+.2f}. Worth revisiting whether the original thesis for this trade still holds given the time remaining.")

    return " ".join(lines)

def scan_single_ticker(ticker):
    """Pulls option chains via Tradier."""
    setups = []
    token = os.getenv("TRADIER_API_KEY")
    if not token: return setups
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    try:
        # Spot price
        spot_hist = yf.Ticker(ticker).history(period="5d")
        if spot_hist.empty: return setups
        spot = spot_hist['Close'].iloc[-1]

        # 1. Get available expirations for this ticker, pick the one 30-75 days out
        exp_res = requests.get(f"{TRADIER_BASE_URL}/markets/options/expirations",
                                params={"symbol": ticker}, headers=headers, timeout=10).json()
        expirations = (exp_res.get('expirations') or {}).get('date', [])
        if isinstance(expirations, str): expirations = [expirations]
        if not expirations: return setups

        target_date = get_macro_expiration(expirations)
        if not target_date: return setups

        # 2. Pull the full option chain for that expiration (bid/ask/OI/IV all included)
        chain_res = requests.get(f"{TRADIER_BASE_URL}/markets/options/chains",
                                  params={"symbol": ticker, "expiration": target_date, "greeks": "true"},
                                  headers=headers, timeout=10).json()
        options = (chain_res.get('options') or {}).get('option', [])
        if isinstance(options, dict): options = [options]  # Tradier returns a dict instead of a list when there's only one contract
        if not options: return setups

        contracts_list = []
        for opt in options:
            if opt.get('option_type') != 'call': continue
            greeks = opt.get('greeks') or {}
            iv = greeks.get('mid_iv') or greeks.get('smv_vol') or 0.35
            contracts_list.append({
                'strike': opt.get('strike'),
                'expiration': target_date,
                'bid': opt.get('bid') or 0,
                'ask': opt.get('ask') or 0,
                'openInterest': opt.get('open_interest') or 0,
                'impliedVolatility': iv
            })

        calls = pd.DataFrame(contracts_list)
        if calls.empty: return setups

        calls = filter_contract_liquidity(calls)
        if calls.empty: return setups
        
        calls = calls.sort_values('strike').reset_index(drop=True)
        step_size = 5.0 if spot > 250 else (2.5 if spot > 100 else 1.0)
        atm_calls = calls[(calls['strike'] >= spot * 0.90) & (calls['strike'] <= spot * 1.10)].copy()
        
        if not check_volatility_environment(atm_calls): return setups
        
        days_to_exp = (datetime.strptime(target_date, "%Y-%m-%d") - datetime.now()).days

        if len(atm_calls) >= 2:
            for idx in range(len(atm_calls) - 1):
                long_leg = atm_calls.iloc[idx].to_dict()
                short_leg = atm_calls.iloc[idx + 1].to_dict()
                strike_width = short_leg['strike'] - long_leg['strike']
                if abs(strike_width - step_size) > 0.1: continue
                net_debit = long_leg['ask'] - short_leg['bid']
                max_profit = strike_width - net_debit
                if 0.15 < net_debit <= 4.00 and max_profit >= (net_debit * 2.0):
                    breakeven = long_leg['strike'] + net_debit
                    avg_iv = (long_leg['impliedVolatility'] + short_leg['impliedVolatility']) / 2
                    prob_profit = prob_finish_above(spot, breakeven, avg_iv, days_to_exp)
                    # Binary approximation: treats the payoff as all-or-nothing at breakeven,
                    # which overstates EV since real profit ramps linearly between breakeven
                    # and the short strike -- good enough for ranking, not a precise price.
                    ev = prob_profit * max_profit - (1 - prob_profit) * net_debit
                    setups.append({
                        "ticker": ticker, "type": "Debit Vertical", "score": max_profit / net_debit,
                        "prob_profit": prob_profit, "ev": ev,
                        "expiration": target_date, "spot_at_scan": spot,
                        "long_strike": long_leg['strike'], "short_strike": short_leg['strike'],
                        "net_cost": net_debit, "max_profit": max_profit,
                        "desc": f"BUY ${long_leg['strike']} C / SELL ${short_leg['strike']} C (Cost: ${net_debit:.2f} | Max Gain: ${max_profit:.2f}) | Exp: {target_date} | Est. Prob. of Profit: {prob_profit*100:.0f}% | EV: ${ev:+.2f}"
                    })
                    
        if len(atm_calls) >= 3:
            for idx in range(len(atm_calls) - 2):
                low_leg = atm_calls.iloc[idx].to_dict()
                mid_leg = atm_calls.iloc[idx + 1].to_dict()
                high_leg = atm_calls.iloc[idx + 2].to_dict()
                if (mid_leg['strike'] - low_leg['strike']) == (high_leg['strike'] - mid_leg['strike']) and abs((mid_leg['strike'] - low_leg['strike']) - step_size) < 0.1:
                    wing_width = mid_leg['strike'] - low_leg['strike']
                    net_cost = low_leg['ask'] + high_leg['ask'] - (2 * mid_leg['bid'])
                    max_bfly_profit = wing_width - net_cost
                    if 0.15 < net_cost <= 4.00 and max_bfly_profit >= (net_cost * 2.0):
                        breakeven_low = low_leg['strike'] + net_cost
                        breakeven_high = high_leg['strike'] - net_cost
                        avg_iv = (low_leg['impliedVolatility'] + mid_leg['impliedVolatility'] + high_leg['impliedVolatility']) / 3
                        # Probability the stock finishes anywhere in the profit zone (between
                        # the two breakevens), not just probability of hitting max profit at
                        # the exact center strike -- max profit is a single point, so its
                        # standalone probability is ~0 in a continuous model.
                        prob_profit = prob_finish_above(spot, breakeven_low, avg_iv, days_to_exp) - prob_finish_above(spot, breakeven_high, avg_iv, days_to_exp)
                        prob_profit = max(0.0, prob_profit)
                        # Binary approximation using max profit -- real payoff tapers linearly
                        # from the breakevens to a peak at the center strike, so this overstates
                        # EV. Useful for ranking/comparison, not a precise fair value.
                        ev = prob_profit * max_bfly_profit - (1 - prob_profit) * net_cost
                        setups.append({
                            "ticker": ticker, "type": "Butterfly Pin", "score": max_bfly_profit / net_cost,
                            "prob_profit": prob_profit, "ev": ev,
                            "expiration": target_date, "spot_at_scan": spot,
                            "low_strike": low_leg['strike'], "mid_strike": mid_leg['strike'], "high_strike": high_leg['strike'],
                            "net_cost": net_cost, "max_profit": max_bfly_profit,
                            "desc": f"Pin Target ${mid_leg['strike']} (${low_leg['strike']}/{mid_leg['strike']}/{high_leg['strike']}) (Cost: ${net_cost:.2f} | Max Gain: ${max_bfly_profit:.2f}) | Exp: {target_date} | Est. Prob. in Profit Zone: {prob_profit*100:.0f}% | EV: ${ev:+.2f}"
                        })
    except Exception as e:
        print(f" [!] {ticker}: {e}")
    return setups



def dedupe_best_per_ticker(setups):
    """Keeps only the single best-scoring setup per ticker, so one name with many
    near-identical strikes doesn't crowd out the rest of the universe."""
    best = {}
    for s in setups:
        t = s['ticker']
        if t not in best or s['ev'] > best[t]['ev']:
            best[t] = s
    return list(best.values())

def format_setup_list(setups, header):
    if not setups:
        return ""
    section = f"{header}\n"
    for i, setup in enumerate(setups, 1):
        section += f"{i}. [{setup['ticker'].upper()}] (Ratio: {setup['score']:.1f}:1, Est. EV: ${setup['ev']:+.2f})\n   {setup['desc']}\n\n"
    return section

def run_bulk_screener(progress=print):
    all_setups = []
    progress(f" [*] Universe: {len(UNIVERSE)} candidate tickers. Checking liquidity (price/volume)...")
    liquid_tickers = filter_liquid_universe(UNIVERSE, progress=progress)
    progress(f" [*] {len(liquid_tickers)} tickers passed the liquidity filter (avg volume >= {MIN_AVG_VOLUME:,}, price >= ${MIN_PRICE:.0f}).")
    if not liquid_tickers:
        return "No tickers passed the liquidity filter -- check your Tradier connection or thresholds."
    progress(f" [*] Scanning {len(liquid_tickers)} liquid tickers for options setups via parallel multithreading pools...")
    with ThreadPoolExecutor(max_workers=15) as executor:
        results = executor.map(scan_single_ticker, liquid_tickers)
    for res_list in results:
        if res_list: all_setups.extend(res_list)

    if all_setups:
        log_setups(all_setups)
        progress(f" [*] Logged {len(all_setups)} candidate setups for future grading.")

    verticals = [s for s in all_setups if s['type'] == 'Debit Vertical' and s['ev'] > 0]
    butterflies = [s for s in all_setups if s['type'] == 'Butterfly Pin' and s['ev'] > 0]

    top_verticals = sorted(dedupe_best_per_ticker(verticals), key=lambda x: x['ev'], reverse=True)[:3]
    top_butterflies = sorted(dedupe_best_per_ticker(butterflies), key=lambda x: x['ev'], reverse=True)[:3]

    if not top_verticals and not top_butterflies:
        return "No positive-expected-value setups identified across the universe today. That's a legitimate result, not an error -- it means nothing in today's liquid universe cleared the bar once probability of profit is factored in."

    summary = format_setup_list(top_verticals, "=== TOP DEBIT VERTICALS (1 per ticker, positive EV only) ===")
    if not top_verticals:
        summary += "=== TOP DEBIT VERTICALS ===\nNone found with positive estimated EV today.\n\n"
    summary += format_setup_list(top_butterflies, "=== TOP BUTTERFLY PINS (1 per ticker, positive EV only) ===")
    if not top_butterflies:
        summary += "=== TOP BUTTERFLY PINS ===\nNone found with positive estimated EV today.\n\n"
    return summary

if __name__ == "__main__":
    print("\n╔" + "═"*44 + "╗")
    print("║          OPTIONS INTELLIGENCE DESK         ║")
    print("╚" + "═"*44 + "╝")
    print(" 1: Stream Live Portfolio Status (Auto-Refresh Loop)")
    print(" 2: Run Watchlist Screener for Optimal Setups")
    print("─"*46)
    choice = input(" -> Select active track (1 or 2): ").strip()
    if choice == "1":
        try:
            while True:
                os.system('cls' if os.name == 'nt' else 'clear')
                print(track_live_portfolio())
                print(" [*] Streaming live... Press Ctrl + C to exit tracker deck loop.")
                time.sleep(30)
        except KeyboardInterrupt:
            print("\n [!] Exiting live stream tracker deck.")
    elif choice == "2":
        print(run_bulk_screener())
    else:
        print("Invalid choice selected.")