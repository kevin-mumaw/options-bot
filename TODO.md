# Options Intelligence Desk — To-Do List

Running list of planned work. Check items off as they're completed; add new ones as they
come up. Each item should get its own focused session when it's substantial -- avoid
rushing architecture changes late in a long session.

## In Progress / Next Up

- [ ] **Strategy selection by market regime** -- the big one. Currently the tool only
  scans two strategies (debit verticals, butterflies), both of which assume a specific
  market view. Need to figure out:
  - [ ] How to detect market regime per ticker: bullish / bearish / neutral / high-volatility
        / low-volatility. Candidates: realized vs. implied volatility comparison, price vs.
        moving averages, IV rank/percentile (needs historical IV, which is a data-source
        question -- see note below).
  - [ ] Straddles/strangles -- when they make sense (expecting a big move, direction
        unknown -- earnings, catalysts) and how to score them.
  - [ ] Calendar spreads -- when they make sense (expecting low near-term movement,
        benefiting from time decay differences between expirations).
  - [ ] Single-leg calls/puts -- when a defined-risk spread isn't actually the better
        trade vs. a naked directional bet (rare for this tool's EV-focused approach, but
        worth defining explicitly rather than defaulting to "always use a spread").
  - [ ] Decision logic: given a ticker's regime, which strategy type(s) should the
        screener even attempt for it? (E.g., don't scan for bearish put verticals on a
        ticker in a strong uptrend, don't scan calendars against a name with no
        near-term catalyst.)
  - [ ] Architecture: how new strategy types plug into `scan_single_ticker()` --
        probably needs to become a dispatcher that calls per-strategy scan functions
        based on detected regime, rather than one function doing everything.
  - [ ] Data question: some regime signals (IV rank/percentile specifically) need
        *historical* IV, which Tradier doesn't provide for free -- same constraint we
        hit with the backtest. May need to approximate with realized volatility instead,
        or scope a paid data source later.
  - [ ] Backtest log schema: `backtest_log.csv` columns are vertical/butterfly-specific
        right now (`long_strike`, `short_strike`, `low_strike`/`mid_strike`/`high_strike`).
        New strategy types need this schema extended without breaking existing grading.
  - [ ] Streamlit app: Screener tab currently shows two fixed sections (verticals,
        butterflies). Needs to accommodate however many strategy types end up
        implemented, cleanly.
  - [ ] `USER_GUIDE.md`: new section(s) explaining each new strategy -- when it's used,
        how to read its output, same style as the existing vertical/butterfly sections.
  - [ ] `README.md`: update "What it does" section once new strategies are live.

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