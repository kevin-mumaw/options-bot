# Options Intelligence Desk — To-Do List

**Working preference (2026-07-10): always give the straight, unvarnished answer on
this project — no sugarcoating, especially on model accuracy/confidence questions.**

Running list of planned work. Check items off as they're completed; add new ones as they
come up. Each item should get its own focused session when it's substantial -- avoid
rushing architecture changes late in a long session.

## In Progress / Next Up

- [ ] **Strategy selection by market regime** -- the big one. Currently the tool only
  scans two strategies (debit verticals, butterflies), both of which assume a specific
  market view. Progress so far:
  - [x] How to detect market regime per ticker: bullish / bearish / neutral, from price
        vs. 20/50-day SMAs (trend direction and slope). Also computing IV-vs-realized-
        volatility richness (rich/cheap/fair) as a second signal -- calculated and
        logged, but not yet wired into strategy selection.
  - [x] Data question resolved: IV rank/percentile would need paid historical IV data,
        so instead we compare CURRENT IV (free, already pulled) against REALIZED
        volatility from free historical stock prices. Sidesteps the paid-data wall
        entirely for this purpose.
  - [x] Bear put verticals -- implemented and tested. Screener now finds bearish trades
        for the first time (previously it could only ever suggest bullish call
        verticals, even on tickers in a clear downtrend).
  - [x] Architecture: `scan_single_ticker()` now detects regime once per ticker and
        dispatches to bull call verticals / bear put verticals / butterflies
        accordingly, instead of always attempting all strategies on every ticker.
  - [x] Backtest log schema extended (`option_type`, `direction` columns) with a
        tested, idempotent one-time migration script (`migrate_backtest_log.py`) for
        existing log files.
  - [x] `grade_backtest.py` updated with correct put-vertical payoff math (verified
        against known payoff shapes) and a calibration report that breaks out bull
        call / bear put / butterfly separately.
  - [x] `USER_GUIDE.md` and `README.md` updated to explain regime-based dispatch.
  - [x] Straddles/strangles -- implemented and tested. Triggers on neutral trend +
        cheap IV (options underpriced relative to the stock's own realized volatility).
        Uses realized vol (not the cheap option IV itself) to estimate expected payoff,
        avoiding a circular "cheap IV makes it look cheap to buy AND cheap to profit"
        trap. Backtest schema, grading math, and calibration report all updated and
        tested for both new types.
  - [x] Single-leg calls/puts -- implemented and tested. Triggers on bullish/bearish
        trend + cheap IV, replacing the vertical entirely rather than running alongside
        it: when the premium you'd sell to build a spread is cheap, the discount isn't
        worth giving up uncapped upside for. No new backtest schema needed -- reused
        the `strike`/`option_type`/`direction` columns already added for straddles.
  - [x] Calendar spreads -- implemented and tested, but with an important honest
        caveat: this is the ONE strategy that can't be backtested with free data (its
        payoff depends on a historical option price at an interim date, not just the
        stock's price at expiration -- same paid-data wall as the original Polygon
        problem, just resurfacing here). `grade_backtest.py` marks these `not_gradable`
        rather than pretending to check them against reality. Uses Black-Scholes
        option pricing for the first time in this tool (previously only used for
        probability, never for pricing) -- verified against put-call parity and the
        standard textbook ATM approximation before shipping.
  - [x] Streamlit app: text-tag approach (`[BULLISH]` etc.) held up fine through all
        six strategy types -- no dedicated-sections rework needed after all.

**Phase 1 of strategy selection is essentially complete**: 6 strategy types, all
regime-aware, 5 of 6 fully backtestable. Remaining polish items live in Backlog below.

## Completed

- [x] Fix broken Polygon integration (malformed URLs, wrong plan tier) -- switched to Tradier
- [x] Universe scan (247 liquid tickers) with liquidity pre-filter
- [x] Probability-of-profit + expected value scoring (Black-Scholes based)
- [x] Positive-EV-only filtering, deduped/ranked separately by strategy type
- [x] Mobile deployment via Streamlit Community Cloud
- [x] Portfolio tracker (desktop CLI + mobile), moved off yfinance onto Tradier
- [x] `log_trade.py` -- guided CLI for adding/closing positions, with realized P/L tracking
- [x] Backtest logging (`backtest_log.csv`) + calibration grading (`grade_backtest.py`)
- [x] GitHub-backed logging so mobile-triggered runs feed the same backtest history as desktop
- [x] Portfolio narrative (plain-language position summaries) on mobile
- [x] Purchase details (strikes, expiration, contracts, entry cost) shown per position on mobile
- [x] `USER_GUIDE.md` started -- pin risk, GTC vs. price alerts, closing for max profit,
      early assignment risk
- [x] GitHub profile README updated with options-bot listed under Quantitative Trading

## Backlog (not started)

- [ ] Decide: track `backtest_log.csv` in git — **decided: yes** (see completed)
- [ ] Improve probability-of-profit trustworthiness. Discussed 2026-07-10: raw Black-
      Scholes probability estimates aren't necessarily well-calibrated (options IV
      tends to run a bit higher than realized volatility on average, which could bias
      probabilities in a predictable direction). Two candidate fixes:
      1. Add a minimum probability-of-profit threshold so longshots stop surfacing as
         "top picks" just because EV is technically positive -- straightforward, no
         data dependency, but only changes *what gets shown*, not the underlying
         accuracy of the estimate itself.
      2. Apply a documented volatility-risk-premium correction to the raw IV before
         estimating probabilities -- addresses the actual estimate, but is a real
         statistical claim that ideally needs backtest validation before/after
         applying it, or risks trading one unverified bias for another.
      **Decided to wait for real backtest calibration data before doing either** --
      once `grade_backtest.py` has enough graded setups (dozens per strategy type,
      ideally more), the calibration report will show whether there's a real,
      measurable gap between predicted and actual win rates, and by how much --
      turning this from a guess into an evidence-based fix.