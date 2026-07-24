import yfinance as yf
import pandas as pd
import requests
import json
import os
import math
import random
import logging
logging.getLogger("yfinance").setLevel(logging.CRITICAL)  # ETFs have no earnings dates --
# yfinance logs a misleading "may be delisted" warning for every one of them on every
# scan. This isn't an error condition (handled fine by the try/except in the earnings
# helpers below), just noisy console output for something totally expected.
import time
import csv
import base64
import io
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from dotenv import load_dotenv

# Automatically finds your .env file and loads your keys into local memory
load_dotenv()

PORTFOLIO_FILE = "portfolio.json"
TRADIER_BASE_URL = "https://api.tradier.com/v1"

# Liquid universe: top ~200 S&P 500 companies by market cap (covers nearly all Nasdaq 100
# names too, since those are dominated by the same mega-caps) + the standard heavily-traded
# ETF universe. This is the RAW candidate pool -- filter_liquid_universe() below cuts it
# down to genuinely tradable names by real volume/price before any options data is pulled.
STOP_LOSS_PCT = 0.50  # Cut a losing long-premium position once it's lost this fraction
# of what you paid, rather than riding it toward a full loss. Long options/debit spreads
# can never lose more than the premium -- this isn't about avoiding catastrophic loss,
# it's capital discipline: a position that's already lost half its value before
# expiration usually keeps bleeding, and that capital is generally better redeployed into
# the next signal than held hoping for a reversal. 50% is a reasonable, common default --
# not derived from this bot's own backtest data yet, so treat it as a starting point to
# validate once enough graded trades exist to check whether cutting at 50% actually beats
# holding to expiration for this strategy mix.
#
# IMPORTANT KNOWN BIAS: the displayed stop-loss PRICE (see exit_price_for_target calls
# below) is computed assuming today's full time-to-expiration holds constant -- same
# simplification as the profit-target exit price. For a profit target that makes the
# number too CONSERVATIVE (needs a bigger move than reality). For a stop-loss it's the
# opposite and more dangerous: it makes the number too OPTIMISTIC. Theta decay alone
# erodes value over time even with zero adverse price movement, so the real STOP_LOSS_PCT
# loss can arrive with a smaller price move than this number implies, especially later in
# the trade's life. Treat the displayed stop price as a rough outer bound, not a precise
# trigger -- and don't wait for price alone to hit it if the position's actual current
# value has already crossed the loss threshold.

UNIVERSE = [
    "AAL", "AAPL", "ABBV", "ABNB", "ABT", "ACN", "ADBE", "ADI", "ADP",
    "AEP", "AFL", "AJG", "ALL", "AMAT", "AMD", "AMGN", "AMT",
    "AMZN", "ANET", "AON", "APD", "APH", "APO", "APP", "ARKK",
    "AVGO", "AXP", "BA", "BAC", "BKNG", "BLK", "BMY", "BNY",
    "BRK.B", "BSX", "BX", "C", "CAT", "CB", "CDNS", "CEG",
    "CI", "CL", "CMCSA", "CME", "CMI", "COF", "COHR", "COIN", "COP",
    "COST", "CRH", "CRM", "CRWD", "CSCO", "CSX", "CTAS", "CVS",
    "CVX", "D", "DAL", "DASH", "DDOG", "DE", "DELL", "DHR", "DIA",
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
    "PM", "PNC", "PSX", "PWR", "PYPL", "QCOM", "QQQ", "RCL", "REGN",
    "ROST", "RSG", "RTX", "SBUX", "SCHW", "SHW", "SLB", "SLV",
    "SMH", "SNDK", "SNPS", "SO", "SOXL", "SOXS", "SOXX", "SPG",
    "SPGI", "SPY", "SQ", "SQQQ", "STX", "SYK", "T", "TDG", "TFC",
    "TJX", "TLT", "TMO", "TMUS", "TQQQ", "TRV", "TSLA", "TSM", "TT",
    "TXN", "UAL", "UBER", "UNG", "UNH", "UNP", "UPS", "URI", "USB",
    "USO", "UVXY", "V", "VLO", "VNQ", "VRT", "VRTX", "VXX",
    "VZ", "WBD", "WDC", "WELL", "WFC", "WM", "WMB", "WMT",
    "XBI", "XHB", "XLB", "XLC", "XLE", "XLF", "XLI", "XLK",
    "XLP", "XLRE", "XLU", "XLV", "XLY", "XOM", "XOP",
]

MIN_AVG_VOLUME = 1_000_000   # avg daily shares traded -- proxy for tight bid/ask spreads
MIN_PRICE = 10.0             # skip penny-priced noise

BACKTEST_LOG_FILE = "backtest_log.csv"
BACKTEST_LOG_COLUMNS = [
    "run_date", "ticker", "type", "option_type", "direction", "expiration", "near_expiration", "spot_at_scan",
    "long_strike", "short_strike", "low_strike", "mid_strike", "high_strike",
    "strike", "call_strike", "put_strike",
    "net_cost", "max_profit", "prob_profit", "ev", "iv_rv_ratio", "earnings_in_window", "jump_adjusted",
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

def get_near_term_expiration(expirations, back_date_str):
    """Picks a near-term expiration (15-35 days out) for the short leg of a calendar
    spread -- distinct from and earlier than the macro (back-month) expiration. Returns
    None if nothing suitable exists, since a calendar spread needs two genuinely
    different dates to make sense."""
    current_date = datetime.now()
    min_date = current_date + timedelta(days=15)
    max_date = current_date + timedelta(days=35)
    try:
        back_date = datetime.strptime(back_date_str, "%Y-%m-%d")
    except (ValueError, TypeError):
        return None
    candidates = []
    for date_str in expirations:
        try:
            exp_date = datetime.strptime(date_str, "%Y-%m-%d")
            if min_date <= exp_date <= max_date and exp_date < back_date:
                candidates.append((date_str, exp_date))
        except:
            continue
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[1])
    return candidates[0][0]  # earliest suitable near-term date

def filter_contract_liquidity(df, min_open_interest=500, max_spread_pct=0.15):
    """Drops contracts that fail EITHER liquidity check: open interest under
    `min_open_interest`, OR a bid/ask spread wider than `max_spread_pct` of the mid
    price. OI alone isn't sufficient -- a strike can carry decent open interest from past
    activity while still showing a stale, wide quote today if it simply hasn't traded.
    15% is a reasonably generous cap: tight enough to catch genuinely bad quotes (the
    kind that showed up on PEP's deep OTM/ITM strikes in the Tradier/Schwab comparison),
    loose enough not to kill legitimate but less-active near-the-money candidates that
    are core to this bot's cheap-IV strategy. Contracts with bid or ask of exactly 0
    (no market at all) are dropped regardless of OI."""
    if df.empty: return df
    if 'openInterest' not in df.columns or 'bid' not in df.columns or 'ask' not in df.columns:
        return pd.DataFrame()
    df = df.copy()
    df['openInterest'] = df['openInterest'].fillna(0)
    df['bid'] = df['bid'].fillna(0)
    df['ask'] = df['ask'].fillna(0)
    has_market = (df['bid'] > 0) & (df['ask'] > 0)
    mid = (df['bid'] + df['ask']) / 2
    spread_pct = (df['ask'] - df['bid']) / mid.replace(0, pd.NA)
    passes_oi = df['openInterest'] >= min_open_interest
    passes_spread = spread_pct <= max_spread_pct
    return df[has_market & passes_oi & passes_spread].copy()

def check_volatility_environment(atm_calls):
    if atm_calls.empty: return False
    avg_iv = atm_calls['impliedVolatility'].mean() if 'impliedVolatility' in atm_calls.columns else 0
    return avg_iv >= 0.20

def prob_finish_above(spot, strike, iv, days_to_exp, div_yield=0.0):
    """Risk-neutral probability the stock finishes above `strike` at expiration, assuming
    lognormal returns (standard Black-Scholes N(d2), risk-free rate treated as 0 for
    simplicity). This is an approximation -- it ignores skew beyond the IV you feed it and
    early assignment -- but it's a meaningful upgrade over a raw payout ratio that ignores
    likelihood entirely.

    div_yield: continuous dividend yield (decimal, e.g. 0.03 for 3%). Matters most for
    higher-yield names -- dividends lower the forward price, so a stock with a real
    dividend yield is systematically MORE likely to finish below a given strike (and less
    likely to finish above) than a div_yield=0 assumption implies. Defaults to 0.0 so
    existing call sites that don't pass it keep behaving exactly as before."""
    if iv <= 0 or days_to_exp <= 0 or spot <= 0 or strike <= 0:
        return 0.5  # neutral fallback if inputs are unusable
    T = days_to_exp / 365.0
    d2 = (math.log(spot / strike) + (-div_yield - 0.5 * iv * iv) * T) / (iv * math.sqrt(T))
    return 0.5 * (1 + math.erf(d2 / math.sqrt(2)))

def bs_call_price(spot, strike, iv, days_to_exp, div_yield=0.0):
    """Black-Scholes theoretical price of a call option (r=0, dividend yield optional).
    Needed for calendar spreads: unlike every other strategy here, a calendar's value at
    the point that matters (the near-month expiration) depends on re-pricing the still-alive
    far-month option, not just looking up the stock's terminal price."""
    if spot <= 0 or strike <= 0 or iv <= 0 or days_to_exp <= 0:
        return max(0.0, spot - strike)  # degenerates to intrinsic value at/after expiration
    T = days_to_exp / 365.0
    fwd = spot * math.exp(-div_yield * T)
    d1 = (math.log(fwd / strike) + 0.5 * iv * iv * T) / (iv * math.sqrt(T))
    d2 = d1 - iv * math.sqrt(T)
    Nd1 = 0.5 * (1 + math.erf(d1 / math.sqrt(2)))
    Nd2 = 0.5 * (1 + math.erf(d2 / math.sqrt(2)))
    return fwd * Nd1 - strike * Nd2

def bs_put_price(spot, strike, iv, days_to_exp, div_yield=0.0):
    """Black-Scholes theoretical price of a put option (r=0, dividend yield optional)."""
    if spot <= 0 or strike <= 0 or iv <= 0 or days_to_exp <= 0:
        return max(0.0, strike - spot)
    T = days_to_exp / 365.0
    fwd = spot * math.exp(-div_yield * T)
    d1 = (math.log(fwd / strike) + 0.5 * iv * iv * T) / (iv * math.sqrt(T))
    d2 = d1 - iv * math.sqrt(T)
    Nd1 = 0.5 * (1 + math.erf(d1 / math.sqrt(2)))
    Nd2 = 0.5 * (1 + math.erf(d2 / math.sqrt(2)))
    return strike * (1 - Nd2) - fwd * (1 - Nd1)

def estimate_spread_haircut(net_cost, *legs):
    """Estimates round-trip bid/ask friction as a fraction of net cost, from each leg's
    OWN currently-quoted spread width (ask - bid). Used to make 'exit price for target
    profit' realistic: the Black-Scholes theoretical/fair value at some future spot price
    isn't what you'll actually receive when you sell to close -- you cross the spread
    again on the way out, same as you did getting in. This assumes today's quoted spread
    % is a reasonable proxy for the spread at exit -- a real approximation, since spreads
    can widen between now and then (often exactly when you most want to exit, in a fast
    move). Capped at 50% as a sanity guard against a bad/stale quote blowing this up."""
    total_leg_spread = sum(max(0.0, leg.get('ask', 0) - leg.get('bid', 0)) for leg in legs)
    if net_cost <= 0:
        return 0.0
    return min(0.5, total_leg_spread / net_cost)


def exit_price_caveat(exit_price, spot, threshold=0.12):
    """Exit-price targets are computed assuming TODAY's full time-to-expiration stays
    constant (repricing 'if this move happened right now'). With a lot of time still
    left on a trade, hitting a big fraction of max profit purely from intrinsic value
    can require an unrealistically large move -- time value hasn't decayed yet, so the
    position hasn't 'matured' toward its expiration payoff. In practice the same dollar
    target is usually reached with a smaller move as expiration approaches, since decay
    does part of the work. Flag it plainly rather than silently showing a number that
    implies you need a much bigger move than you probably actually will."""
    if spot <= 0:
        return ""
    move_pct = abs(exit_price - spot) / spot
    if move_pct >= threshold:
        return f" [NOTE: implies a {move_pct*100:.0f}% move assuming NO time decay between now and then -- actual required move is likely smaller as expiration approaches]"
    return ""


def exit_price_for_target(direction, valuation_fn, spot, target_value, search_mult=(0.3, 3.0)):
    """Finds the stock price at which a position's BS-repriced value (using TODAY's days-
    to-expiration and IV -- i.e. 'if this move happened right now') would equal
    target_value. Used to answer 'what price should I watch for to capture 80% of my
    target profit', not just the breakeven/max-profit endpoints. `direction` is 'up' if
    valuation_fn is increasing in stock price (long calls, bull verticals, straddle upside
    leg) or 'down' if decreasing (long puts, bear verticals). This is a simplification --
    real theta decay between now and exit means the actual required move is usually a bit
    smaller than this implies, since less time value survives at exit than a same-day
    re-pricing assumes."""
    lo, hi = spot * search_mult[0], spot * search_mult[1]
    for _ in range(60):
        mid = (lo + hi) / 2
        v = valuation_fn(mid)
        if direction == "up":
            if v < target_value:
                lo = mid
            else:
                hi = mid
        else:
            if v < target_value:
                hi = mid
            else:
                lo = mid
    return (lo + hi) / 2


def expected_move(spot, iv, days_to_exp):
    """Standard 1-standard-deviation expected price move by expiration, from IV. Used as
    a representative 'typical move' size for straddle/strangle payoff estimates, since
    those structures don't have a natural max-profit cap the way verticals/butterflies do."""
    if spot <= 0 or iv <= 0 or days_to_exp <= 0:
        return 0.0
    return spot * iv * math.sqrt(days_to_exp / 365.0)

def straddle_payoff_at_price(price, strike):
    """Payoff of a long straddle (long call + long put, same strike) at a given
    terminal price, before subtracting cost. Equivalent to |price - strike|."""
    return max(0.0, price - strike) + max(0.0, strike - price)

def strangle_payoff_at_price(price, call_strike, put_strike):
    """Payoff of a long strangle (long OTM call + long OTM put, different strikes) at a
    given terminal price, before subtracting cost."""
    return max(0.0, price - call_strike) + max(0.0, put_strike - price)

@lru_cache(maxsize=256)
def get_dividend_yield(ticker):
    """Best-effort continuous dividend yield lookup (decimal, e.g. 0.032 for 3.2%). Feeds
    the dividend adjustment in prob_finish_above/bs_call_price/bs_put_price -- without
    this, probability-of-profit was systematically overstating call profitability and
    understating put profitability on dividend payers like PEP, since dividends lower the
    forward price. Cached per-ticker per-run since it doesn't change intraday. Returns 0.0
    (i.e. falls back to old no-dividend behavior) if the lookup fails for any reason --
    never blocks a scan over this."""
    try:
        info = yf.Ticker(ticker).info
        y = info.get("dividendYield") or 0.0
        # yfinance has been inconsistent across versions about whether this field is
        # already a decimal (0.032) or a whole percentage (3.2) -- normalize defensively.
        return y / 100.0 if y > 1.0 else float(y)
    except Exception:
        return 0.0


@lru_cache(maxsize=256)
def get_next_earnings_date(ticker):
    """Best-effort: next earnings date for this ticker (or None). Used to decide whether
    a trade's expiration spans an earnings event, so the jump-aware probability model
    below kicks in. Returns None on any failure -- caller falls back to plain lognormal."""
    try:
        edates = yf.Ticker(ticker).get_earnings_dates(limit=8)
        if edates is None or edates.empty:
            return None
        now = pd.Timestamp.now()
        idx = edates.index
        idx_naive = idx.tz_localize(None) if getattr(idx, "tz", None) is not None else idx
        future = sorted([d for d in idx_naive if d >= now])
        return future[0] if future else None
    except Exception:
        return None


@lru_cache(maxsize=256)
def get_historical_earnings_returns(ticker, lookback=8):
    """Best-effort: this ticker's own actual single-day return on each of its last
    `lookback` PAST earnings dates (close-to-close across the reaction day), pulled from
    yfinance's earnings calendar + price history. This is the empirical distribution fed
    into the jump-aware probability model -- built from what THIS stock has actually done
    on earnings day historically, not a theoretical/generic assumption. Returns () (empty
    tuple, for lru_cache hashability) if the lookup fails for any reason."""
    try:
        edates = yf.Ticker(ticker).get_earnings_dates(limit=lookback + 6)
        if edates is None or edates.empty:
            return ()
        hist = yf.Ticker(ticker).history(period="3y")["Close"]
        if hist.empty:
            return ()
        hist_idx = hist.index.tz_localize(None) if getattr(hist.index, "tz", None) is not None else hist.index
        now = pd.Timestamp.now()
        e_idx = edates.index.tz_localize(None) if getattr(edates.index, "tz", None) is not None else edates.index
        past_dates = sorted([d for d in e_idx if d < now], reverse=True)[:lookback]
        returns = []
        for ed in past_dates:
            after = hist_idx[hist_idx >= ed]
            before = hist_idx[hist_idx < ed]
            if len(after) == 0 or len(before) == 0:
                continue
            price_after = float(hist.loc[after[0]])
            price_before = float(hist.loc[before[-1]])
            if price_before > 0:
                returns.append((price_after / price_before) - 1)
        return tuple(returns)
    except Exception:
        return ()


def prob_finish_above_jump_aware(spot, strike, quiet_vol, days_to_exp, earnings_returns, div_yield=0.0, n_sims=4000):
    """Monte Carlo probability of finishing above `strike`, modeling terminal price as
    ORDINARY lognormal diffusion over the non-earnings days (quiet_vol -- pass the
    winsorized realized vol here, i.e. the stock's normal-day behavior, NOT current
    option IV) PLUS one bootstrap draw from the ticker's own historical earnings-day
    returns for the single earnings-day jump. Deliberately avoids current market IV
    entirely for this calculation: IV blends the market's earnings expectation with
    everything else in a way that's hard to decompose cleanly without double-counting.
    Trade-off: this assumes the past distribution of this ticker's earnings surprises is
    a reasonable guide to the next one -- a real assumption with real limits (small
    sample, regime changes, etc.), not a guarantee. Returns None if earnings_returns is
    empty or inputs are unusable -- caller should fall back to prob_finish_above."""
    if not earnings_returns or quiet_vol <= 0 or days_to_exp <= 0 or spot <= 0 or strike <= 0:
        return None
    diffusion_days = max(days_to_exp - 1, 0)  # one day "spent" on the jump itself
    T_diff = diffusion_days / 365.0
    sd = quiet_vol * math.sqrt(T_diff) if T_diff > 0 else 0.0
    mu = (-div_yield - 0.5 * quiet_vol * quiet_vol) * T_diff
    count_above = 0
    for _ in range(n_sims):
        diffusion_log_ret = random.gauss(mu, sd) if sd > 0 else mu
        jump_ret = random.choice(earnings_returns)
        jump_log_ret = math.log(max(1e-6, 1 + jump_ret))
        terminal = spot * math.exp(diffusion_log_ret + jump_log_ret)
        if terminal > strike:
            count_above += 1
    return count_above / n_sims


def detect_regime(ticker, current_iv, price_history=None):
    """Classifies a ticker's regime using only free data:
    - trend: 'bullish' / 'bearish' / 'neutral', from price vs. 20/50-day SMAs and whether
      the 20-day SMA is rising or falling
    - iv_regime: 'rich' / 'cheap' / 'fair' / 'unknown', from current IV vs. realized
      volatility computed from recent price history. This sidesteps the need for paid
      historical IV/IV-rank data entirely -- it only needs the CURRENT option IV (which
      we already pull from Tradier) and historical STOCK prices (free via yfinance).
    Returns None if there isn't enough price history to classify confidently.
    `price_history` can be injected for testing; otherwise pulled live via yfinance."""
    if price_history is None:
        price_history = yf.Ticker(ticker).history(period="4mo")
    if price_history is None or len(price_history) < 55:
        return None

    closes = price_history['Close']
    current_price = closes.iloc[-1]
    sma20_series = closes.rolling(20).mean()
    sma20 = sma20_series.iloc[-1]
    sma20_prior = sma20_series.iloc[-6]  # ~1 trading week earlier, for slope direction
    sma50 = closes.rolling(50).mean().iloc[-1]
    sma20_rising = sma20 > sma20_prior

    if current_price > sma20 > sma50 and sma20_rising:
        trend = "bullish"
    elif current_price < sma20 < sma50 and not sma20_rising:
        trend = "bearish"
    else:
        trend = "neutral"

    daily_returns = closes.pct_change().dropna().iloc[-21:]  # ~last 20 trading days
    realized_vol_raw = daily_returns.std() * math.sqrt(252) if len(daily_returns) >= 5 else None

    # WINSORIZE before computing the realized-vol used for classification. A single
    # earnings-gap day (or any other one-off shock) can dominate a 20-day std-dev
    # calculation -- one 5-6% day contributes roughly as much variance as ~50 normal
    # 0.8% days for a low-beta name. Cap any return more than ~3 MADs from the median
    # at that boundary (don't drop it -- just stop it from dominating), then compute
    # realized vol on the capped series. 1.4826x scales MAD to be comparable to a
    # standard deviation for normally-distributed data.
    realized_vol = realized_vol_raw
    capped_returns_count = 0
    if realized_vol_raw is not None and len(daily_returns) >= 5:
        median_ret = daily_returns.median()
        mad = (daily_returns - median_ret).abs().median()
        if mad > 0:
            cap = 3 * mad * 1.4826
            lower, upper = median_ret - cap, median_ret + cap
            winsorized_returns = daily_returns.clip(lower=lower, upper=upper)
            capped_returns_count = int((daily_returns != winsorized_returns).sum())
            realized_vol = winsorized_returns.std() * math.sqrt(252)

    # Best-effort: does the ~20-trading-day realized-vol lookback window span a recent
    # earnings date? Even after winsorizing, this is worth surfacing/logging so a
    # "cheap" classification right after earnings can be reviewed with that context.
    # yfinance's earnings-date lookup can be flaky/rate-limited, so this must never
    # break the scan if it fails -- earnings_in_window just stays None (unknown).
    earnings_in_window = None
    try:
        edates = yf.Ticker(ticker).get_earnings_dates(limit=8)
        if edates is not None and len(edates) > 0 and len(daily_returns) > 0:
            window_start = daily_returns.index.min()
            window_end = closes.index.max()
            edates_idx = edates.index
            if getattr(edates_idx, "tz", None) is not None:
                edates_idx = edates_idx.tz_localize(None)
            ws = window_start.tz_localize(None) if getattr(window_start, "tz", None) is not None else window_start
            we = window_end.tz_localize(None) if getattr(window_end, "tz", None) is not None else window_end
            earnings_in_window = bool(((edates_idx >= ws) & (edates_idx <= we)).any())
    except Exception:
        earnings_in_window = None  # best-effort only -- never fail the scan over this

    iv_rv_ratio = None
    if realized_vol and realized_vol > 0 and current_iv and current_iv > 0:
        iv_rv_ratio = current_iv / realized_vol
        if iv_rv_ratio >= 1.3:
            iv_regime = "rich"    # options pricier than recent actual movement justifies
        elif iv_rv_ratio <= 0.8:
            iv_regime = "cheap"   # options cheaper than recent actual movement -- premium looks underpriced
        else:
            iv_regime = "fair"
    else:
        iv_regime = "unknown"

    return {
        "trend": trend, "iv_regime": iv_regime, "iv_rv_ratio": iv_rv_ratio,
        "realized_vol": realized_vol, "realized_vol_raw": realized_vol_raw,
        "capped_returns_count": capped_returns_count, "earnings_in_window": earnings_in_window,
        "current_price": current_price, "sma20": sma20, "sma50": sma50,
    }

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

    for spread in portfolio.get("bearish_debit_spreads", []):
        tk = spread.get("ticker", "?")
        try:
            quote = get_tradier_quote(tk, headers)
            if not quote:
                positions.append({"ticker": tk, "type": "Debit Vertical", "error": "no quote returned"})
                continue
            spot = quote.get('last') or 0
            puts = [o for o in get_tradier_chain(tk, spread["expiration"], headers) if o.get('option_type') == 'put']
            long_rows = [o for o in puts if o.get('strike') == spread['long_strike']]
            short_rows = [o for o in puts if o.get('strike') == spread['short_strike']]
            if not (long_rows and short_rows):
                positions.append({"ticker": tk, "type": "Debit Vertical", "error": f"couldn't find one or more strikes in the {spread['expiration']} chain"})
                continue
            p_long = ((long_rows[0].get('bid') or 0) + (long_rows[0].get('ask') or 0)) / 2
            p_short = ((short_rows[0].get('bid') or 0) + (short_rows[0].get('ask') or 0)) / 2
            current_value = p_long - p_short
            pnl = (current_value - spread["entry_debit"]) * 100 * spread["contracts"]
            days_to_exp = (datetime.strptime(spread["expiration"], "%Y-%m-%d") - datetime.now()).days
            breakeven = spread["long_strike"] - spread["entry_debit"]
            max_value = spread["long_strike"] - spread["short_strike"]
            max_profit_per_share = max_value - spread["entry_debit"]
            max_profit_total = max_profit_per_share * 100 * spread["contracts"]
            profit_captured_pct = (pnl / max_profit_total * 100) if max_profit_total > 0 else None
            positions.append({
                "ticker": tk, "type": "Debit Vertical", "option_type": "put", "direction": "bearish",
                "spot": spot, "expiration": spread["expiration"],
                "days_to_exp": days_to_exp, "entry_debit": spread["entry_debit"], "current_value": current_value,
                "pnl": pnl, "contracts": spread["contracts"], "breakeven": breakeven,
                "long_strike": spread["long_strike"], "short_strike": spread["short_strike"],
                "max_profit_total": max_profit_total, "profit_captured_pct": profit_captured_pct,
            })
        except Exception as e:
            positions.append({"ticker": tk, "type": "Debit Vertical", "error": str(e)})

    for leg in portfolio.get("long_calls", []):
        tk = leg.get("ticker", "?")
        try:
            quote = get_tradier_quote(tk, headers)
            if not quote:
                positions.append({"ticker": tk, "type": "Long Call", "error": "no quote returned"})
                continue
            spot = quote.get('last') or 0
            calls = [o for o in get_tradier_chain(tk, leg["expiration"], headers) if o.get('option_type') == 'call']
            rows = [o for o in calls if o.get('strike') == leg['strike']]
            if not rows:
                positions.append({"ticker": tk, "type": "Long Call", "error": f"couldn't find strike {leg['strike']} in the {leg['expiration']} chain"})
                continue
            current_value = ((rows[0].get('bid') or 0) + (rows[0].get('ask') or 0)) / 2
            pnl = (current_value - leg["entry_cost"]) * 100 * leg["contracts"]
            days_to_exp = (datetime.strptime(leg["expiration"], "%Y-%m-%d") - datetime.now()).days
            breakeven = leg["strike"] + leg["entry_cost"]
            positions.append({
                "ticker": tk, "type": "Long Call", "option_type": "call", "direction": "bullish",
                "spot": spot, "expiration": leg["expiration"], "days_to_exp": days_to_exp,
                "entry_debit": leg["entry_cost"], "current_value": current_value, "pnl": pnl,
                "contracts": leg["contracts"], "breakeven": breakeven, "strike": leg["strike"],
                # No capped max_profit_total for a long call (unlimited upside) -- profit_captured_pct
                # deliberately left out here rather than showing a fake percentage against a fake cap.
                "max_profit_total": None, "profit_captured_pct": None,
            })
        except Exception as e:
            positions.append({"ticker": tk, "type": "Long Call", "error": str(e)})

    for leg in portfolio.get("long_puts", []):
        tk = leg.get("ticker", "?")
        try:
            quote = get_tradier_quote(tk, headers)
            if not quote:
                positions.append({"ticker": tk, "type": "Long Put", "error": "no quote returned"})
                continue
            spot = quote.get('last') or 0
            puts = [o for o in get_tradier_chain(tk, leg["expiration"], headers) if o.get('option_type') == 'put']
            rows = [o for o in puts if o.get('strike') == leg['strike']]
            if not rows:
                positions.append({"ticker": tk, "type": "Long Put", "error": f"couldn't find strike {leg['strike']} in the {leg['expiration']} chain"})
                continue
            current_value = ((rows[0].get('bid') or 0) + (rows[0].get('ask') or 0)) / 2
            pnl = (current_value - leg["entry_cost"]) * 100 * leg["contracts"]
            days_to_exp = (datetime.strptime(leg["expiration"], "%Y-%m-%d") - datetime.now()).days
            breakeven = leg["strike"] - leg["entry_cost"]
            # True hard cap for a long put is if the stock goes to literally $0 -- used only
            # to give a rough profit_captured_pct context, not treated as a realistic target.
            true_max_profit_total = (leg["strike"] - leg["entry_cost"]) * 100 * leg["contracts"]
            profit_captured_pct = (pnl / true_max_profit_total * 100) if true_max_profit_total > 0 else None
            positions.append({
                "ticker": tk, "type": "Long Put", "option_type": "put", "direction": "bearish",
                "spot": spot, "expiration": leg["expiration"], "days_to_exp": days_to_exp,
                "entry_debit": leg["entry_cost"], "current_value": current_value, "pnl": pnl,
                "contracts": leg["contracts"], "breakeven": breakeven, "strike": leg["strike"],
                "max_profit_total": true_max_profit_total, "profit_captured_pct": profit_captured_pct,
            })
        except Exception as e:
            positions.append({"ticker": tk, "type": "Long Put", "error": str(e)})

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
    elif pos["type"] == "Debit Vertical":
        breakeven = pos["breakeven"]
        short_strike = pos["short_strike"]
        bearish = pos.get("direction") == "bearish"
        lines.append(f"Breakeven is ${breakeven:.2f}; short strike (max profit point) is ${short_strike:.2f}.")
        if bearish:
            if pos["spot"] <= short_strike:
                lines.append("Stock is already at or below the short strike -- this spread is at or near max profit.")
            elif pos["spot"] > breakeven:
                lines.append("Stock is still above breakeven -- needs to move down for this to be profitable by expiration.")
        else:
            if pos["spot"] >= short_strike:
                lines.append("Stock is already at or above the short strike -- this spread is at or near max profit.")
            elif pos["spot"] < breakeven:
                lines.append("Stock is still below breakeven -- needs to move up for this to be profitable by expiration.")
    elif pos["type"] in ("Long Call", "Long Put"):
        breakeven = pos["breakeven"]
        bearish = pos["type"] == "Long Put"
        lines.append(f"Breakeven is ${breakeven:.2f}; strike is ${pos['strike']:.2f}.")
        if bearish:
            if pos["spot"] < breakeven:
                lines.append("Stock is below breakeven -- currently profitable, though further downside still adds to gains since there's no cap until $0.")
            else:
                lines.append("Stock is still above breakeven -- needs to move down for this to be profitable by expiration.")
        else:
            if pos["spot"] > breakeven:
                lines.append("Stock is above breakeven -- currently profitable, with uncapped further upside.")
            else:
                lines.append("Stock is still below breakeven -- needs to move up for this to be profitable by expiration.")

    if pnl > 0 and pct is not None:
        lines.append(f"Currently up ${pnl:+.2f}, roughly {pct:.0f}% of max theoretical profit captured.")
        if pct >= 50:
            lines.append("Many options traders take profits in the 50-75% range on debit spreads rather than holding for full max, since time decay cuts both ways as expiration nears.")
    elif pnl < 0:
        lines.append(f"Currently down ${pnl:+.2f}. Worth revisiting whether the original thesis for this trade still holds given the time remaining.")

    return " ".join(lines)

def scan_single_ticker(ticker):
    """Pulls option chains via Tradier, detects the ticker's regime (trend + IV
    richness), and dispatches to the strategy that regime calls for: bull call
    verticals in an uptrend, bear put verticals in a downtrend, butterflies when
    neutral."""
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

        calls_list, puts_list = [], []
        for opt in options:
            greeks = opt.get('greeks') or {}
            iv = greeks.get('mid_iv') or greeks.get('smv_vol') or 0.35
            row = {
                'strike': opt.get('strike'), 'expiration': target_date,
                'bid': opt.get('bid') or 0, 'ask': opt.get('ask') or 0,
                'openInterest': opt.get('open_interest') or 0, 'impliedVolatility': iv
            }
            if opt.get('option_type') == 'call':
                calls_list.append(row)
            elif opt.get('option_type') == 'put':
                puts_list.append(row)

        calls = filter_contract_liquidity(pd.DataFrame(calls_list))
        puts = filter_contract_liquidity(pd.DataFrame(puts_list))
        if calls.empty and puts.empty: return setups

        step_size = 5.0 if spot > 250 else (2.5 if spot > 100 else 1.0)
        atm_calls = pd.DataFrame()
        if not calls.empty:
            calls = calls.sort_values('strike').reset_index(drop=True)
            atm_calls = calls[(calls['strike'] >= spot * 0.90) & (calls['strike'] <= spot * 1.10)].copy()
        atm_puts = pd.DataFrame()
        if not puts.empty:
            puts = puts.sort_values('strike').reset_index(drop=True)
            atm_puts = puts[(puts['strike'] >= spot * 0.90) & (puts['strike'] <= spot * 1.10)].copy()

        if not check_volatility_environment(atm_calls): return setups

        days_to_exp = (datetime.strptime(target_date, "%Y-%m-%d") - datetime.now()).days
        avg_iv_for_regime = atm_calls['impliedVolatility'].mean() if not atm_calls.empty else 0
        regime = detect_regime(ticker, current_iv=avg_iv_for_regime)
        if regime is None: return setups
        trend = regime["trend"]
        div_yield = get_dividend_yield(ticker)

        if trend == "bullish" and regime["iv_regime"] == "cheap" and not atm_calls.empty:
            # IV cheap -- the premium we'd sell to build a vertical isn't attractively
            # priced, so we give up the cost discount and just buy the call outright to
            # keep the uncapped upside instead.
            leg_row = atm_calls.iloc[(atm_calls['strike'] - spot).abs().argsort().iloc[0]].to_dict()
            strike = leg_row['strike']
            cost = leg_row['ask']
            breakeven = strike + cost
            avg_iv = leg_row['impliedVolatility']
            prob_profit = prob_finish_above(spot, breakeven, avg_iv, days_to_exp, div_yield)
            jump_adjusted = False
            next_earnings = get_next_earnings_date(ticker)
            if next_earnings is not None:
                exp_dt = pd.Timestamp(target_date)
                if pd.Timestamp.now() <= next_earnings <= exp_dt:
                    hist_returns = get_historical_earnings_returns(ticker)
                    if hist_returns:
                        p_above_jump = prob_finish_above_jump_aware(
                            spot, breakeven, regime["realized_vol"], days_to_exp, hist_returns, div_yield
                        )
                        if p_above_jump is not None:
                            prob_profit = p_above_jump
                            jump_adjusted = True
            em = expected_move(spot, regime["realized_vol"], days_to_exp)
            assumed_payoff = max(0.0, max(0.0, (spot + em) - strike) - cost)
            if 0.15 < cost <= 4.00 and assumed_payoff >= (cost * 2.0):
                ev = prob_profit * assumed_payoff - (1 - prob_profit) * cost
                target_value = cost + 0.8 * assumed_payoff
                spread_haircut = estimate_spread_haircut(cost, leg_row)
                target_value_for_exit = target_value / (1 - spread_haircut / 2)
                exit_price = exit_price_for_target(
                    "up", lambda S: bs_call_price(S, strike, avg_iv, days_to_exp, div_yield),
                    spot, target_value_for_exit
                )
                stop_target = cost * (1 - STOP_LOSS_PCT)
                stop_price = exit_price_for_target(
                    "up", lambda S: bs_call_price(S, strike, avg_iv, days_to_exp, div_yield),
                    spot, stop_target
                )
                setups.append({
                    "ticker": ticker, "type": "Long Call", "option_type": "call", "direction": "bullish",
                    "score": assumed_payoff / cost, "prob_profit": prob_profit, "ev": ev,
                    "expiration": target_date, "spot_at_scan": spot, "strike": strike,
                    "net_cost": cost, "max_profit": assumed_payoff, "jump_adjusted": jump_adjusted,
                    "iv_rv_ratio": regime.get("iv_rv_ratio"), "earnings_in_window": regime.get("earnings_in_window"),
                    "desc": f"[BULLISH/CHEAP IV] BUY ${strike} C (Cost: ${cost:.2f}) | Breakeven: ${breakeven:.2f} | Max Loss: ${cost:.2f} (100% of premium) | Target Profit @ ~1SD move: ${assumed_payoff:.2f} (NOTE: calls have theoretically unlimited upside -- this is a realistic target, not a hard cap) | Exit near ${exit_price:.2f}{exit_price_caveat(exit_price, spot)} to capture ~80% of target | Stop-Loss near ${stop_price:.2f} if stock drops that far (cuts the loss at {STOP_LOSS_PCT*100:.0f}% of premium rather than riding to zero -- NOTE: assumes no further time decay, so a {STOP_LOSS_PCT*100:.0f}% loss may actually arrive SOONER/with a smaller move than this, as theta erodes value passively while you wait) | Exp: {target_date} | Est. Prob. of Profit: {prob_profit*100:.0f}%{' [jump-adjusted -- uses historical earnings-day moves, not IV]' if jump_adjusted else ''} | EV: ${ev:+.2f}{(' | \u26a0 EARNINGS IN RV WINDOW' if regime.get('earnings_in_window') else '')}"
                })

        elif trend == "bullish" and len(atm_calls) >= 2:
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
                    # Skew-aware: breakeven sits near the LONG strike, so use that leg's own
                    # IV for the probability calc rather than a blended average -- OTM/ITM
                    # strikes routinely trade at meaningfully different IV than each other
                    # (skew), and averaging them washes that out right where it matters most.
                    prob_profit = prob_finish_above(spot, breakeven, long_leg['impliedVolatility'], days_to_exp, div_yield)
                    ev = prob_profit * max_profit - (1 - prob_profit) * net_debit
                    target_value = net_debit + 0.8 * max_profit
                    spread_haircut = estimate_spread_haircut(net_debit, long_leg, short_leg)
                    target_value_for_exit = target_value / (1 - spread_haircut / 2)
                    exit_price = exit_price_for_target(
                        "up",
                        lambda S: bs_call_price(S, long_leg['strike'], avg_iv, days_to_exp, div_yield)
                                  - bs_call_price(S, short_leg['strike'], avg_iv, days_to_exp, div_yield),
                        spot, target_value_for_exit
                    )
                    stop_target = net_debit * (1 - STOP_LOSS_PCT)
                    stop_price = exit_price_for_target(
                        "up",
                        lambda S: bs_call_price(S, long_leg['strike'], avg_iv, days_to_exp, div_yield)
                                  - bs_call_price(S, short_leg['strike'], avg_iv, days_to_exp, div_yield),
                        spot, stop_target
                    )
                    setups.append({
                        "ticker": ticker, "type": "Debit Vertical", "option_type": "call", "direction": "bullish",
                        "score": max_profit / net_debit, "prob_profit": prob_profit, "ev": ev,
                        "expiration": target_date, "spot_at_scan": spot,
                        "long_strike": long_leg['strike'], "short_strike": short_leg['strike'],
                        "net_cost": net_debit, "max_profit": max_profit,
                        "desc": f"[BULLISH] BUY ${long_leg['strike']} C / SELL ${short_leg['strike']} C (Cost: ${net_debit:.2f}) | Breakeven: ${breakeven:.2f} | Max Loss: ${net_debit:.2f} (capped) | Max Gain: ${max_profit:.2f} (capped, hit if stock >= ${short_leg['strike']:.2f} at exp) | Exit near ${exit_price:.2f}{exit_price_caveat(exit_price, spot)} to capture ~80% of max gain | Stop-Loss near ${stop_price:.2f} if stock drops that far (cuts the loss at {STOP_LOSS_PCT*100:.0f}% of premium rather than riding to zero -- NOTE: assumes no further time decay, so a {STOP_LOSS_PCT*100:.0f}% loss may actually arrive SOONER/with a smaller move than this, as theta erodes value passively while you wait) | Exp: {target_date} | Est. Prob. of Profit: {prob_profit*100:.0f}% | EV: ${ev:+.2f}"
                    })

        elif trend == "bearish" and regime["iv_regime"] == "cheap" and not atm_puts.empty:
            leg_row = atm_puts.iloc[(atm_puts['strike'] - spot).abs().argsort().iloc[0]].to_dict()
            strike = leg_row['strike']
            cost = leg_row['ask']
            breakeven = strike - cost
            avg_iv = leg_row['impliedVolatility']
            prob_profit = 1 - prob_finish_above(spot, breakeven, avg_iv, days_to_exp, div_yield)
            jump_adjusted = False
            next_earnings = get_next_earnings_date(ticker)
            if next_earnings is not None:
                exp_dt = pd.Timestamp(target_date)
                if pd.Timestamp.now() <= next_earnings <= exp_dt:
                    hist_returns = get_historical_earnings_returns(ticker)
                    if hist_returns:
                        p_above_jump = prob_finish_above_jump_aware(
                            spot, breakeven, regime["realized_vol"], days_to_exp, hist_returns, div_yield
                        )
                        if p_above_jump is not None:
                            prob_profit = 1 - p_above_jump
                            jump_adjusted = True
            em = expected_move(spot, regime["realized_vol"], days_to_exp)
            assumed_payoff = max(0.0, max(0.0, strike - (spot - em)) - cost)
            if 0.15 < cost <= 4.00 and assumed_payoff >= (cost * 2.0):
                ev = prob_profit * assumed_payoff - (1 - prob_profit) * cost
                true_max_profit = strike - cost  # if the stock went to literally $0 -- not realistic, but the actual hard cap
                target_value = cost + 0.8 * assumed_payoff
                spread_haircut = estimate_spread_haircut(cost, leg_row)
                target_value_for_exit = target_value / (1 - spread_haircut / 2)
                exit_price = exit_price_for_target(
                    "down", lambda S: bs_put_price(S, strike, avg_iv, days_to_exp, div_yield),
                    spot, target_value_for_exit
                )
                stop_target = cost * (1 - STOP_LOSS_PCT)
                stop_price = exit_price_for_target(
                    "down", lambda S: bs_put_price(S, strike, avg_iv, days_to_exp, div_yield),
                    spot, stop_target
                )
                setups.append({
                    "ticker": ticker, "type": "Long Put", "option_type": "put", "direction": "bearish",
                    "score": assumed_payoff / cost, "prob_profit": prob_profit, "ev": ev,
                    "expiration": target_date, "spot_at_scan": spot, "strike": strike,
                    "net_cost": cost, "max_profit": assumed_payoff, "jump_adjusted": jump_adjusted,
                    "iv_rv_ratio": regime.get("iv_rv_ratio"), "earnings_in_window": regime.get("earnings_in_window"),
                    "desc": f"[BEARISH/CHEAP IV] BUY ${strike} P (Cost: ${cost:.2f}) | Breakeven: ${breakeven:.2f} | Max Loss: ${cost:.2f} (100% of premium) | Max Theoretical Profit: ${true_max_profit:.2f} (only if stock->$0 -- unrealistic) | Realistic Target Profit @ ~1SD move: ${assumed_payoff:.2f} | Exit near ${exit_price:.2f}{exit_price_caveat(exit_price, spot)} to capture ~80% of target | Stop-Loss near ${stop_price:.2f} if stock rises that far (cuts the loss at {STOP_LOSS_PCT*100:.0f}% of premium rather than riding to zero -- NOTE: assumes no further time decay, so a {STOP_LOSS_PCT*100:.0f}% loss may actually arrive SOONER/with a smaller move than this, as theta erodes value passively while you wait) | Exp: {target_date} | Est. Prob. of Profit: {prob_profit*100:.0f}%{' [jump-adjusted -- uses historical earnings-day moves, not IV]' if jump_adjusted else ''} | EV: ${ev:+.2f}{(' | \u26a0 EARNINGS IN RV WINDOW' if regime.get('earnings_in_window') else '')}"
                })

        elif trend == "bearish" and len(atm_puts) >= 2:
            for idx in range(len(atm_puts) - 1):
                # Bear put vertical: BUY the higher strike, SELL the lower strike --
                # mirror image of the bull call vertical above.
                short_leg = atm_puts.iloc[idx].to_dict()      # lower strike, sold
                long_leg = atm_puts.iloc[idx + 1].to_dict()   # higher strike, bought
                strike_width = long_leg['strike'] - short_leg['strike']
                if abs(strike_width - step_size) > 0.1: continue
                net_debit = long_leg['ask'] - short_leg['bid']
                max_profit = strike_width - net_debit
                if 0.15 < net_debit <= 4.00 and max_profit >= (net_debit * 2.0):
                    breakeven = long_leg['strike'] - net_debit
                    avg_iv = (long_leg['impliedVolatility'] + short_leg['impliedVolatility']) / 2
                    # Skew-aware -- same reasoning as the bull vertical fix: use the LONG
                    # leg's own IV for the breakeven probability instead of a blend.
                    prob_profit = 1 - prob_finish_above(spot, breakeven, long_leg['impliedVolatility'], days_to_exp, div_yield)  # profit if stock finishes BELOW breakeven
                    ev = prob_profit * max_profit - (1 - prob_profit) * net_debit
                    target_value = net_debit + 0.8 * max_profit
                    spread_haircut = estimate_spread_haircut(net_debit, long_leg, short_leg)
                    target_value_for_exit = target_value / (1 - spread_haircut / 2)
                    exit_price = exit_price_for_target(
                        "down",
                        lambda S: bs_put_price(S, long_leg['strike'], avg_iv, days_to_exp, div_yield)
                                  - bs_put_price(S, short_leg['strike'], avg_iv, days_to_exp, div_yield),
                        spot, target_value_for_exit
                    )
                    stop_target = net_debit * (1 - STOP_LOSS_PCT)
                    stop_price = exit_price_for_target(
                        "down",
                        lambda S: bs_put_price(S, long_leg['strike'], avg_iv, days_to_exp, div_yield)
                                  - bs_put_price(S, short_leg['strike'], avg_iv, days_to_exp, div_yield),
                        spot, stop_target
                    )
                    setups.append({
                        "ticker": ticker, "type": "Debit Vertical", "option_type": "put", "direction": "bearish",
                        "score": max_profit / net_debit, "prob_profit": prob_profit, "ev": ev,
                        "expiration": target_date, "spot_at_scan": spot,
                        "long_strike": long_leg['strike'], "short_strike": short_leg['strike'],
                        "net_cost": net_debit, "max_profit": max_profit,
                        "desc": f"[BEARISH] BUY ${long_leg['strike']} P / SELL ${short_leg['strike']} P (Cost: ${net_debit:.2f}) | Breakeven: ${breakeven:.2f} | Max Loss: ${net_debit:.2f} (capped) | Max Gain: ${max_profit:.2f} (capped, hit if stock <= ${short_leg['strike']:.2f} at exp) | Exit near ${exit_price:.2f}{exit_price_caveat(exit_price, spot)} to capture ~80% of max gain | Stop-Loss near ${stop_price:.2f} if stock rises that far (cuts the loss at {STOP_LOSS_PCT*100:.0f}% of premium rather than riding to zero -- NOTE: assumes no further time decay, so a {STOP_LOSS_PCT*100:.0f}% loss may actually arrive SOONER/with a smaller move than this, as theta erodes value passively while you wait) | Exp: {target_date} | Est. Prob. of Profit: {prob_profit*100:.0f}% | EV: ${ev:+.2f}"
                    })

        elif trend == "neutral" and regime["iv_regime"] == "cheap" and not atm_calls.empty and not atm_puts.empty:
            # IV cheap relative to actual recent movement -- premium looks underpriced for
            # the moves this stock has actually been making, so buying it (straddle/strangle)
            # is more attractive here than selling it via a butterfly.
            # Use REALIZED volatility (not the option's own cheap IV) to estimate the
            # expected move. The whole thesis here is "IV is underpricing how much this
            # stock actually moves" -- so the payoff estimate should reflect that real
            # movement, not the same cheap IV that's mispricing the options in the first
            # place (which would be circular and understate the opportunity).
            em = expected_move(spot, regime["realized_vol"], days_to_exp)

            # Long straddle: same strike, nearest to spot, present in both calls and puts
            common_strikes = sorted(set(atm_calls['strike']) & set(atm_puts['strike']))
            if common_strikes:
                straddle_strike = min(common_strikes, key=lambda k: abs(k - spot))
                call_leg = atm_calls[atm_calls['strike'] == straddle_strike].iloc[0].to_dict()
                put_leg = atm_puts[atm_puts['strike'] == straddle_strike].iloc[0].to_dict()
                net_cost = call_leg['ask'] + put_leg['ask']
                breakeven_up = straddle_strike + net_cost
                breakeven_down = straddle_strike - net_cost
                avg_iv = (call_leg['impliedVolatility'] + put_leg['impliedVolatility']) / 2
                # Skew-aware: even at the SAME strike, calls and puts often carry slightly
                # different IV (skew/put-call parity noise in the quotes). Price the upside
                # breakeven with the call's own IV and the downside breakeven with the put's.
                prob_profit = prob_finish_above(spot, breakeven_up, call_leg['impliedVolatility'], days_to_exp, div_yield) + (1 - prob_finish_above(spot, breakeven_down, put_leg['impliedVolatility'], days_to_exp, div_yield))
                prob_profit = min(1.0, prob_profit)
                assumed_payoff = max(0.0,
                    straddle_payoff_at_price(spot + em, straddle_strike) - net_cost,
                    straddle_payoff_at_price(spot - em, straddle_strike) - net_cost)
                if 0.15 < net_cost <= 4.00 and assumed_payoff >= (net_cost * 2.0):
                    ev = prob_profit * assumed_payoff - (1 - prob_profit) * net_cost
                    setups.append({
                        "ticker": ticker, "type": "Long Straddle", "option_type": "both", "direction": "neutral",
                        "score": assumed_payoff / net_cost, "prob_profit": prob_profit, "ev": ev,
                        "expiration": target_date, "spot_at_scan": spot, "strike": straddle_strike,
                        "net_cost": net_cost, "max_profit": assumed_payoff,
                        "iv_rv_ratio": regime.get("iv_rv_ratio"), "earnings_in_window": regime.get("earnings_in_window"),
                        "desc": f"[NEUTRAL/CHEAP IV] BUY ${straddle_strike} C + BUY ${straddle_strike} P (Cost: ${net_cost:.2f}) | Breakevens: ${breakeven_down:.2f} / ${breakeven_up:.2f} | Max Loss: ${net_cost:.2f} (capped, if stock pins exactly at ${straddle_strike}) | Target Profit @ ~1SD move: ${assumed_payoff:.2f} (uncapped upside, no clean 80%-exit price since both legs move together) | Exp: {target_date} | Est. Prob. of Profit: {prob_profit*100:.0f}% | EV: ${ev:+.2f}{(' | \u26a0 EARNINGS IN RV WINDOW' if regime.get('earnings_in_window') else '')}"
                    })

            # Long strangle: nearest OTM call above spot, nearest OTM put below spot
            otm_calls = atm_calls[atm_calls['strike'] > spot]
            otm_puts = atm_puts[atm_puts['strike'] < spot]
            if not otm_calls.empty and not otm_puts.empty:
                call_leg = otm_calls.loc[otm_calls['strike'].idxmin()].to_dict()
                put_leg = otm_puts.loc[otm_puts['strike'].idxmax()].to_dict()
                net_cost = call_leg['ask'] + put_leg['ask']
                breakeven_up = call_leg['strike'] + net_cost
                breakeven_down = put_leg['strike'] - net_cost
                avg_iv = (call_leg['impliedVolatility'] + put_leg['impliedVolatility']) / 2
                # Skew-aware: call and put strikes are DIFFERENT here, so this is the
                # clearest case for it -- OTM puts routinely trade richer than OTM calls
                # (crash-risk premium). Blending would understate downside tail probability
                # and overstate upside tail probability. Each breakeven uses its own leg's IV.
                prob_profit = prob_finish_above(spot, breakeven_up, call_leg['impliedVolatility'], days_to_exp, div_yield) + (1 - prob_finish_above(spot, breakeven_down, put_leg['impliedVolatility'], days_to_exp, div_yield))
                prob_profit = min(1.0, prob_profit)
                assumed_payoff = max(0.0,
                    strangle_payoff_at_price(spot + em, call_leg['strike'], put_leg['strike']) - net_cost,
                    strangle_payoff_at_price(spot - em, call_leg['strike'], put_leg['strike']) - net_cost)
                if 0.15 < net_cost <= 4.00 and assumed_payoff >= (net_cost * 2.0):
                    ev = prob_profit * assumed_payoff - (1 - prob_profit) * net_cost
                    setups.append({
                        "ticker": ticker, "type": "Long Strangle", "option_type": "both", "direction": "neutral",
                        "score": assumed_payoff / net_cost, "prob_profit": prob_profit, "ev": ev,
                        "expiration": target_date, "spot_at_scan": spot,
                        "call_strike": call_leg['strike'], "put_strike": put_leg['strike'],
                        "net_cost": net_cost, "max_profit": assumed_payoff,
                        "iv_rv_ratio": regime.get("iv_rv_ratio"), "earnings_in_window": regime.get("earnings_in_window"),
                        "desc": f"[NEUTRAL/CHEAP IV] BUY ${call_leg['strike']} C + BUY ${put_leg['strike']} P (Cost: ${net_cost:.2f}) | Breakevens: ${breakeven_down:.2f} / ${breakeven_up:.2f} | Max Loss: ${net_cost:.2f} (capped, if stock finishes between the two strikes) | Target Profit @ ~1SD move: ${assumed_payoff:.2f} (uncapped upside, no clean 80%-exit price since both legs move together) | Exp: {target_date} | Est. Prob. of Profit: {prob_profit*100:.0f}% | EV: ${ev:+.2f}{(' | \u26a0 EARNINGS IN RV WINDOW' if regime.get('earnings_in_window') else '')}"
                    })

        elif trend == "neutral" and len(atm_calls) >= 3:
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
                        # Skew-aware: breakeven_low sits near the low (put-side-equivalent)
                        # wing and breakeven_high near the high wing -- use each wing's own
                        # IV rather than a 3-way blend that washes out the skew between them.
                        prob_profit = prob_finish_above(spot, breakeven_low, low_leg['impliedVolatility'], days_to_exp, div_yield) - prob_finish_above(spot, breakeven_high, high_leg['impliedVolatility'], days_to_exp, div_yield)
                        prob_profit = max(0.0, prob_profit)
                        ev = prob_profit * max_bfly_profit - (1 - prob_profit) * net_cost
                        target_value = net_cost + 0.8 * max_bfly_profit
                        spread_haircut = estimate_spread_haircut(net_cost, low_leg, mid_leg, mid_leg, high_leg)
                        target_value_for_search = target_value / (1 - spread_haircut / 2)

                        def _bfly_value(S, _low=low_leg['strike'], _mid=mid_leg['strike'], _high=high_leg['strike'], _iv=avg_iv, _dte=days_to_exp, _dy=div_yield):
                            return (bs_call_price(S, _low, _iv, _dte, _dy) + bs_call_price(S, _high, _iv, _dte, _dy)
                                    - 2 * bs_call_price(S, _mid, _iv, _dte, _dy))

                        # Payoff peaks AT the pin (mid_strike) and falls off both directions --
                        # not monotonic across the whole price axis, so bound the search to the
                        # segment between current spot and the pin itself, where it IS monotonic.
                        _lo, _hi = sorted([spot, mid_leg['strike']])
                        for _ in range(60):
                            _test = (_lo + _hi) / 2
                            _v = _bfly_value(_test)
                            moving_toward_pin_increases_value = spot < mid_leg['strike']
                            if (_v < target_value_for_search) == moving_toward_pin_increases_value:
                                _lo = _test
                            else:
                                _hi = _test
                        exit_price = (_lo + _hi) / 2

                        setups.append({
                            "ticker": ticker, "type": "Butterfly Pin", "option_type": "call", "direction": "neutral",
                            "score": max_bfly_profit / net_cost, "prob_profit": prob_profit, "ev": ev,
                            "expiration": target_date, "spot_at_scan": spot,
                            "low_strike": low_leg['strike'], "mid_strike": mid_leg['strike'], "high_strike": high_leg['strike'],
                            "net_cost": net_cost, "max_profit": max_bfly_profit,
                            "desc": f"[NEUTRAL] Pin Target ${mid_leg['strike']} (${low_leg['strike']}/{mid_leg['strike']}/{high_leg['strike']}) (Cost: ${net_cost:.2f}) | Breakevens: ${breakeven_low:.2f} / ${breakeven_high:.2f} | Max Loss: ${net_cost:.2f} (capped) | Max Gain: ${max_bfly_profit:.2f} (capped, only at exact pin ${mid_leg['strike']:.2f} at exp) | Stock needs to reach ~${exit_price:.2f}{exit_price_caveat(exit_price, spot)} to capture ~80% of max gain | Exp: {target_date} | Est. Prob. in Profit Zone: {prob_profit*100:.0f}% | EV: ${ev:+.2f}"
                        })

            # Calendar spread candidate: only when the near-term option is pricing in
            # meaningfully MORE volatility than the far-term one (term structure
            # inversion) -- classic setup around an upcoming near-term catalyst. Added
            # alongside butterflies, not instead of them; the EV ranking decides which
            # surfaces higher.
            near_date = get_near_term_expiration(expirations, target_date)
            if near_date and not atm_calls.empty:
                try:
                    near_chain_res = requests.get(f"{TRADIER_BASE_URL}/markets/options/chains",
                                                   params={"symbol": ticker, "expiration": near_date, "greeks": "true"},
                                                   headers=headers, timeout=10).json()
                    near_options = (near_chain_res.get('options') or {}).get('option', [])
                    if isinstance(near_options, dict): near_options = [near_options]
                    near_calls_list = []
                    for opt in near_options:
                        if opt.get('option_type') != 'call': continue
                        g = opt.get('greeks') or {}
                        near_calls_list.append({
                            'strike': opt.get('strike'), 'bid': opt.get('bid') or 0, 'ask': opt.get('ask') or 0,
                            'openInterest': opt.get('open_interest') or 0,
                            'impliedVolatility': g.get('mid_iv') or g.get('smv_vol') or 0.35
                        })
                    near_calls = filter_contract_liquidity(pd.DataFrame(near_calls_list))
                    if not near_calls.empty:
                        near_atm = near_calls[(near_calls['strike'] >= spot * 0.90) & (near_calls['strike'] <= spot * 1.10)]
                        back_atm_iv = atm_calls['impliedVolatility'].mean()
                        near_atm_iv = near_atm['impliedVolatility'].mean() if not near_atm.empty else 0
                        if near_atm_iv > 0 and back_atm_iv > 0 and (near_atm_iv / back_atm_iv) >= 1.15:
                            common = sorted(set(atm_calls['strike']) & set(near_atm['strike']))
                            if common:
                                cal_strike = min(common, key=lambda k: abs(k - spot))
                                back_leg = atm_calls[atm_calls['strike'] == cal_strike].iloc[0].to_dict()
                                near_leg = near_atm[near_atm['strike'] == cal_strike].iloc[0].to_dict()
                                net_cost = back_leg['ask'] - near_leg['bid']
                                near_days = (datetime.strptime(near_date, "%Y-%m-%d") - datetime.now()).days
                                remaining_days = days_to_exp - near_days
                                if 0.15 < net_cost <= 4.00 and remaining_days > 0:
                                    # ROUGH estimate only -- assumes the stock stays exactly
                                    # at today's spot AND back-month IV is unchanged by the
                                    # time the near leg expires. Real calendar spreads often
                                    # profit mainly from an IV CRUSH after a catalyst passes,
                                    # which this does not model at all. Treat this as a
                                    # coarse ranking signal, not a price target.
                                    assumed_back_value = bs_call_price(spot, cal_strike, back_leg['impliedVolatility'], remaining_days, div_yield)
                                    near_intrinsic_at_exp = max(0.0, spot - cal_strike)
                                    assumed_value_at_near_exp = assumed_back_value - near_intrinsic_at_exp
                                    assumed_profit = assumed_value_at_near_exp - net_cost
                                    near_em = expected_move(spot, near_leg['impliedVolatility'], near_days)
                                    prob_profit = prob_finish_above(spot, cal_strike - near_em, near_leg['impliedVolatility'], near_days, div_yield) - prob_finish_above(spot, cal_strike + near_em, near_leg['impliedVolatility'], near_days, div_yield)
                                    prob_profit = max(0.0, min(1.0, prob_profit))
                                    if assumed_profit >= (net_cost * 1.0):  # lower bar than other strategies -- this estimate is coarser
                                        ev = prob_profit * assumed_profit - (1 - prob_profit) * net_cost
                                        setups.append({
                                            "ticker": ticker, "type": "Calendar Spread", "option_type": "call", "direction": "neutral",
                                            "score": assumed_profit / net_cost if net_cost > 0 else 0, "prob_profit": prob_profit, "ev": ev,
                                            "expiration": target_date, "near_expiration": near_date, "spot_at_scan": spot, "strike": cal_strike,
                                            "net_cost": net_cost, "max_profit": assumed_profit,
                                            "desc": f"[NEUTRAL/TERM STRUCTURE] SELL ${cal_strike} C {near_date} / BUY ${cal_strike} C {target_date} (Cost: ${net_cost:.2f} | Est. Value @ near exp (flat stock, unchanged IV): ${assumed_value_at_near_exp:.2f}) | Est. Prob. Stock Stays Near Strike: {prob_profit*100:.0f}% | EV: ${ev:+.2f} -- ROUGH ESTIMATE, cannot be backtested with free data"
                                        })
                except Exception:
                    pass  # calendar candidate is a bonus signal -- don't let it break the rest of the scan
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
    straddles = [s for s in all_setups if s['type'] == 'Long Straddle' and s['ev'] > 0]
    strangles = [s for s in all_setups if s['type'] == 'Long Strangle' and s['ev'] > 0]
    long_calls = [s for s in all_setups if s['type'] == 'Long Call' and s['ev'] > 0]
    long_puts = [s for s in all_setups if s['type'] == 'Long Put' and s['ev'] > 0]
    calendars = [s for s in all_setups if s['type'] == 'Calendar Spread' and s['ev'] > 0]

    top_verticals = sorted(dedupe_best_per_ticker(verticals), key=lambda x: x['ev'], reverse=True)[:3]
    top_butterflies = sorted(dedupe_best_per_ticker(butterflies), key=lambda x: x['ev'], reverse=True)[:3]
    top_straddles = sorted(dedupe_best_per_ticker(straddles), key=lambda x: x['ev'], reverse=True)[:3]
    top_strangles = sorted(dedupe_best_per_ticker(strangles), key=lambda x: x['ev'], reverse=True)[:3]
    top_long_calls = sorted(dedupe_best_per_ticker(long_calls), key=lambda x: x['ev'], reverse=True)[:3]
    top_long_puts = sorted(dedupe_best_per_ticker(long_puts), key=lambda x: x['ev'], reverse=True)[:3]
    top_calendars = sorted(dedupe_best_per_ticker(calendars), key=lambda x: x['ev'], reverse=True)[:3]

    if not any([top_verticals, top_butterflies, top_straddles, top_strangles, top_long_calls, top_long_puts, top_calendars]):
        return "No positive-expected-value setups identified across the universe today. That's a legitimate result, not an error -- it means nothing in today's liquid universe cleared the bar once probability of profit is factored in."

    summary = format_setup_list(top_verticals, "=== TOP DEBIT VERTICALS (1 per ticker, positive EV only) ===")
    if not top_verticals:
        summary += "=== TOP DEBIT VERTICALS ===\nNone found with positive estimated EV today.\n\n"
    summary += format_setup_list(top_butterflies, "=== TOP BUTTERFLY PINS (1 per ticker, positive EV only) ===")
    if not top_butterflies:
        summary += "=== TOP BUTTERFLY PINS ===\nNone found with positive estimated EV today.\n\n"
    summary += format_setup_list(top_straddles, "=== TOP LONG STRADDLES (1 per ticker, positive EV only) ===")
    if not top_straddles:
        summary += "=== TOP LONG STRADDLES ===\nNone found with positive estimated EV today.\n\n"
    summary += format_setup_list(top_strangles, "=== TOP LONG STRANGLES (1 per ticker, positive EV only) ===")
    if not top_strangles:
        summary += "=== TOP LONG STRANGLES ===\nNone found with positive estimated EV today.\n\n"
    summary += format_setup_list(top_long_calls, "=== TOP LONG CALLS (1 per ticker, positive EV only) ===")
    if not top_long_calls:
        summary += "=== TOP LONG CALLS ===\nNone found with positive estimated EV today.\n\n"
    summary += format_setup_list(top_long_puts, "=== TOP LONG PUTS (1 per ticker, positive EV only) ===")
    if not top_long_puts:
        summary += "=== TOP LONG PUTS ===\nNone found with positive estimated EV today.\n\n"
    summary += format_setup_list(top_calendars, "=== TOP CALENDAR SPREADS (1 per ticker, positive EV only -- UNGRADABLE ESTIMATE, see USER_GUIDE.md) ===")
    if not top_calendars:
        summary += "=== TOP CALENDAR SPREADS ===\nNone found with positive estimated EV today.\n\n"
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