# Options Intelligence Desk — To-Do List

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
  - [ ] Straddles/strangles -- when they make sense (expecting a big move, direction
        unknown -- earnings, catalysts) and how to score them. Natural next use of the
        IV-richness signal (cheap IV = premium looks underpriced = good time to buy a
        straddle betting on movement).
  - [ ] Calendar spreads -- when they make sense (expecting low near-term movement,
        benefiting from time decay differences between expirations).
  - [ ] Single-leg calls/puts -- when a defined-risk spread isn't actually the better
        trade vs. a naked directional bet (rare for this tool's EV-focused approach, but
        worth defining explicitly rather than defaulting to "always use a spread").
  - [ ] Streamlit app: Screener tab currently shows two fixed sections (verticals,
        butterflies). The `[BULLISH]`/`[BEARISH]`/`[NEUTRAL]` tags in each setup's
        description cover this for now, but once straddles/calendars exist, may need
        dedicated sections rather than relying on tags alone.

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

## Backlog (not started)

- [ ] Update GitHub profile README (the profile-level one, not this project's)
- [ ] Decide: track `backtest_log.csv` in git — **decided: yes** (see completed)