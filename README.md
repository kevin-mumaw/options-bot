# Options Intelligence Desk

A liquid-universe options screener and portfolio P/L tracker, with a desktop CLI and a
mobile-friendly Streamlit web view. All live market data (quotes, expirations, option
chains) comes from Tradier -- both the screener and the portfolio tracker use it, since
Streamlit Cloud's shared IPs get rate-limited/blocked by Yahoo Finance.

## What it does

- **Screener**: scans ~254 liquid S&P 500 names + major ETFs, filters by real trading
  volume/price via Tradier's batch quotes plus a per-contract liquidity check (open
  interest and bid/ask spread width), then pulls live option chains. Classifies each
  ticker's trend regime (bullish/bearish/neutral) and IV richness (rich/cheap/fair vs.
  realized volatility) from free data, and scans the strategy that regime calls for:
  bull call verticals / bear put verticals when IV is normally priced, long calls /
  long puts / straddles / strangles when IV looks cheap relative to how much the stock
  actually moves, butterflies when neutral with normally-priced IV, and calendar
  spreads when a near-term option is pricing in meaningfully more volatility than a
  farther-dated one. Ranks results by an estimated probability-weighted expected value
  (Black-Scholes based, with dividend yield, skew-aware per-leg IV, and -- for Long
  Call/Long Put -- an earnings jump-diffusion adjustment when expiration spans a real
  earnings date), not just raw payout ratio, and only surfaces genuinely positive-EV
  setups. Every recommendation shows breakeven, max profit/loss, a spread-aware exit
  price to capture ~80% of the profit target, and a stop-loss price. **Calendar spreads
  are a rougher estimate than everything else and can't be backtested with free data**
  -- see `USER_GUIDE.md` Section 12 before trading one.
- **Portfolio tracker**: reports live P/L on open positions using current Tradier quotes
  and option chain prices. The mobile view also shows a plain-language narrative per
  position -- days to expiration, distance from pin/breakeven, % of max profit captured,
  and general educational context (not personalized advice).
- **Trade logger**: `log_trade.py` is a guided CLI for adding/closing positions in
  `portfolio.json` without hand-editing raw JSON.

## Files

| File | Purpose |
|---|---|
| `options_bot.py` | Core logic + desktop CLI (`python options_bot.py`) |
| `streamlit_app.py` | Mobile/web view (`streamlit run streamlit_app.py`) |
| `log_trade.py` | Add/close positions in `portfolio.json` |
| `diagnose_scan.py` | Debug tool -- traces one ticker step by step through the pipeline |
| `grade_backtest.py` | Grades expired setups against real outcomes, reports calibration |
| `migrate_backtest_log.py` | One-time migration for `backtest_log.csv` schema changes |
| `Pre_Trade_Checklist.md` | Manual pre-trade checklist to run through before entering a position |
| `backtest_log.csv` | Every candidate setup the screener has ever found (auto-generated, safe to commit -- no real trades, just hypothetical candidates) |

Note: `portfolio.json` is **not** in this repo (gitignored) -- see Privacy note below.
It exists only on your local machine for the desktop CLI, and as a Streamlit secret for
the mobile view.

## Backtesting / calibration

Every screener run logs **every** candidate setup it finds (not just the top 3 you see)
to `backtest_log.csv` -- ticker, strikes, cost, predicted probability of profit, and
estimated EV. This is a forward paper-test, not a retroactive one: there's no cheap
source of historical option chains, so instead we let real time pass and grade setups
against what actually happened.

Once a setup's expiration date is in the past, run:
```
python grade_backtest.py
```
This pulls the underlying's actual closing price near that expiration date (free, via
yfinance) and computes the *exact* payoff analytically -- no historical options data
needed, since a vertical/butterfly's payoff at expiration is fully determined by where
the stock closed. It prints a calibration report: does the model's "70% probability of
profit" actually win about 70% of the time, or is it over/under-confident? It also
breaks out cheap-IV setups by whether their expiration spanned an earnings date, so the
earnings-gap-distortion fix in the IV/RV ratio can be checked against real outcomes
over time, not just theory.

Run the screener regularly and re-run `grade_backtest.py` periodically (e.g. weekly) --
the more setups that accumulate and expire, the more reliable the calibration report
becomes. Early on, with only a handful of graded setups, don't over-interpret the
numbers; wait for a meaningful sample size (dozens, ideally hundreds) before trusting
the calibration gap as a signal to change the model. In particular, the current
`STOP_LOSS_PCT` (50%) is a reasonable starting default, not yet validated against this
bot's own graded outcomes -- worth revisiting once there's enough data.

**Calendar spreads are excluded from this.** Their outcome depends on a historical
option price this tool doesn't have free access to, not just the stock's closing
price. `grade_backtest.py` marks them `not_gradable` once their near leg expires
instead of grading them with a formula that couldn't check them against anything real.
See `USER_GUIDE.md` Section 12 for the full explanation.

**Desktop vs. mobile logging**: the desktop CLI writes new setups straight to your local
`backtest_log.csv` (you `git add`/`commit`/`push` when you want, same as any other file
here). The mobile app has no persistent disk on Streamlit Cloud, so instead it commits
new rows directly to `backtest_log.csv` in this GitHub repo via the GitHub API, using a
`GITHUB_TOKEN` secret scoped to just this repo's contents. Both paths feed the same file
and history -- but because of that, **run `git pull` before running `grade_backtest.py`**
if you've triggered any screener runs from your phone recently, so your local copy
includes what the mobile app committed.

A true retroactive backtest (testing against years of past market conditions instead of
waiting for real time to pass) would need a paid historical options data source like
Polygon's Options plan, ORATS, or CBOE DataShop -- worth considering later if this
forward-test shows promise and you want to validate faster / further back.

## Setup

1. `pip install -r requirements.txt`
2. Create a `.env` file (not committed) with:
   ```
   TRADIER_API_KEY=your_key_here
   ```
3. Create `portfolio.json` locally (not committed) with your open positions -- see
   `log_trade.py` to add them interactively instead of hand-writing JSON. Supported
   sections: `butterfly_spreads`, `bullish_debit_spreads`, `bearish_debit_spreads`,
   `long_calls`, `long_puts`, and `closed_trades` (your own record of closed positions
   -- not read by the bot itself, purely for your reference).
4. Run the CLI: `python options_bot.py`
   Or the web view locally: `streamlit run streamlit_app.py`
5. **If you have an existing `backtest_log.csv` from before regime-based strategy
   selection was added**, run `python migrate_backtest_log.py` once -- it adds the new
   `option_type`/`direction` columns and correctly backfills old rows (all pre-existing
   rows were bull call verticals or neutral butterflies). Safe to run multiple times;
   it detects if migration already happened and does nothing.

## Deploying the mobile view (Streamlit Community Cloud)

Streamlit Community Cloud's free tier only reliably deploys from **public** repos --
there's no working private-repo path without a paid Snowflake-backed tier. So this repo
is public, but your real position data is NOT: `portfolio.json` is gitignored and never
committed. Instead, positions live in Streamlit's private Secrets.

1. Push this repo to GitHub as a **public** repo.
2. Go to [share.streamlit.io](https://share.streamlit.io), sign in with GitHub.
3. Click **Create app** -> **Deploy a public app from GitHub**.
4. Repository: this repo. Branch: `main`. Main file path: `streamlit_app.py`.
5. In the app's **Settings -> Secrets**, add:
   ```
   TRADIER_API_KEY = "your_key_here"
   PORTFOLIO_JSON = '{"butterfly_spreads": [...], "bullish_debit_spreads": [...], "bearish_debit_spreads": [...], "long_calls": [...], "long_puts": [...]}'
   ```
   (paste your real portfolio.json contents as a single-line JSON string for the second one)
6. Open the deployed URL from your phone.

Whenever you open/close a position with `log_trade.py` on your desktop, also update the
`PORTFOLIO_JSON` secret in the Streamlit dashboard to match -- the deployed app reads from
the secret, not from your local file. The two can drift out of sync if you forget this
step, so it's worth checking after every trade.

## Privacy note

`portfolio.json` is gitignored on purpose and must **never** be committed to this public
repo -- it contains real, live trading positions (strikes, contracts, entry prices).
It only exists in two places: your local machine (for the desktop CLI) and Streamlit's
private Secrets panel (for the mobile view, visible only to you). If `portfolio.json`
ever shows up in `git status` or `git add` output, do not commit it -- check `.gitignore`
first.

## Known limitations

- EV estimates use a simplified Black-Scholes model -- 0% risk-free rate, and probability
  is still a lognormal-diffusion approximation for every strategy type except Long
  Call/Long Put with an upcoming earnings date (those get a Monte Carlo jump-diffusion
  adjustment instead, using the ticker's own historical earnings-day moves). Dividend
  yield and per-leg skew-aware IV are now factored in. Useful for ranking setups against
  each other and giving a realistic entry/exit/stop plan, not a precise fair-value
  calculation.
- The per-contract liquidity filter checks both open interest (>= 500) and bid/ask
  spread width (<= 15% of mid), applied once to the whole chain before any strike is
  eligible for any strategy. It does not check trading volume separately from OI.
- Exit-price and stop-loss targets assume today's full time-to-expiration holds
  constant ("if this move happened right now"). For profit targets this makes the
  number too conservative (a real target is usually easier to reach as time decay
  helps close the gap); for stop-losses it's the opposite and more important to know --
  the displayed price can be too optimistic, since theta decay alone can produce the
  loss threshold with a smaller adverse move than shown. Large-move exit targets get an
  explicit on-screen warning; stop-loss lines always carry this caveat.
- `UNIVERSE` is a static list (currently 254 tickers) that will drift from actual S&P
  500 / Nasdaq 100 membership over time and needs periodic manual refreshing.
