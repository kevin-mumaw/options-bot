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

- [x] **Probability-of-profit trustworthiness improvements (2026-07-17).** NOTE: this
      reverses the 2026-07-10 decision above to wait for backtest calibration data
      before touching the probability model. That plan was set aside, not followed --
      worth knowing if the earlier logic gets revisited. What actually shipped instead:
  - [x] Earnings-gap distortion fix in `detect_regime()`'s IV/RV ratio. Root cause: a
        single earnings-day return can dominate the 20-day realized-vol window (one
        5-6% day contributes ~as much variance as 50 normal 0.8% days for a low-beta
        name), making "cheap IV" post-earnings partly an artifact rather than real
        mispricing. Fixed via winsorizing (cap outlier returns at ~3 MADs from the
        median before computing realized vol) plus a best-effort `earnings_in_window`
        flag (yfinance earnings-date lookup, never blocks the scan if it fails).
        Surfaced in both the CSV log (`iv_rv_ratio`, `earnings_in_window` columns) and
        live output (`⚠ EARNINGS IN RV WINDOW` tag). `grade_backtest.py` now has a
        dedicated report splitting cheap-IV win rate by earnings-window status, so this
        can eventually be checked against real outcomes instead of just theory.
  - [x] Dividend yield adjustment. `prob_finish_above`/`bs_call_price`/`bs_put_price`
        all previously assumed div_yield=0, which systematically overstated call
        profitability and understated put profitability on dividend payers (PEP at
        ~4%+ yield was the case that surfaced this). New `get_dividend_yield()`
        (yfinance, cached, defaults to 0.0 on failure) feeds the real yield through.
  - [x] Skew-aware breakeven pricing. Every multi-leg strategy (verticals, straddles,
        strangles, butterflies) was blending IV across legs into one `avg_iv` for its
        probability calc, which washes out real skew (OTM puts routinely trade richer
        than OTM calls). Each breakeven now uses its own leg's actual IV instead.
        Verified the mechanism moves probability in the correct direction in isolation
        (put IV 20%->35% moved P(finish below breakeven) from 15%->29%); net effect on
        any given trade's total probability varies by ticker since both tails can move
        and partially offset.
  - [x] Trade analytics on every recommendation: breakeven, max loss (always shown, capped
        types labeled "capped", long calls/puts labeled "100% of premium"), max profit
        (labeled "capped" for verticals/butterflies vs. "target, not a true cap" for
        uncapped calls/puts), and an exit price to capture ~80% of that profit target
        (BS-repriced at today's IV/DTE -- an approximation, since real theta decay
        between now and exit usually means the actual required move is a bit smaller
        than this implies).
  - [x] Earnings jump-diffusion adjustment (same day, later session). Root problem:
        plain lognormal diffusion assumes smooth price evolution the whole way to
        expiration, but a real earnings date is a discrete jump, not smooth drift --
        understating true tail probability when one falls inside the trade window.
        Fixed for Long Call/Long Put specifically (the two types most directly
        comparable, and where the actual live trades are): when expiration spans a
        real upcoming earnings date, probability switches from plain lognormal to a
        Monte Carlo model (`prob_finish_above_jump_aware`) -- ordinary diffusion using
        winsorized realized vol for the quiet days, plus one bootstrapped draw from
        the ticker's own last ~8 actual historical earnings-day returns for the jump.
        Deliberately ignores current market IV for this calc to avoid double-counting
        the market's own earnings pricing. Verified before shipping: a synthetic test
        with one big historical miss in the mix correctly showed the jump-aware model
        assigning MORE downside tail probability (25.3% vs. 17.4% for plain diffusion)
        than the naive model. Tagged `[jump-adjusted]` in the live output whenever it
        fires, plus a `jump_adjusted` column in the backtest log, so it's always clear
        which probability model produced a given number. New `get_next_earnings_date`/
        `get_historical_earnings_returns` helpers, both best-effort (yfinance), fall
        back to the plain model on any failure. Verticals/straddles/strangles/
        butterflies still use plain lognormal for now -- extension point if this proves
        out.
  - [x] Realistic bid/ask exit pricing (same session). The entry-cost side was already
        correct (buying at ask, selling short legs at bid) -- the actual gap was in the
        "exit price for 80% of target" calculations, which solved for the Black-Scholes
        THEORETICAL value at some future spot price, not what you'd actually receive
        selling to close (the bid, after crossing the spread again on the way out). New
        `estimate_spread_haircut()` reads each leg's own currently-quoted bid/ask width
        as a fraction of net cost, and every exit-target solve (Long Call, Long Put,
        both Debit Verticals, Butterfly Pin) now targets a theoretical value high enough
        to still net the real target after that haircut. Sanity-tested: a tight ~3%
        spread (like the actual PEP put) barely moves the target ($7.05 -> $7.17);
        wider/illiquid spreads get a proportionally bigger, more honest haircut. Assumes
        today's quoted spread % holds at exit -- a real approximation, since spreads can
        widen in exactly the fast moves where you're most likely to want out.

**All four items from the 2026-07-10 probability-of-profit backlog entry are now done**:
dividend yield, skew-aware IV, earnings jump-diffusion, and spread-aware exit targets.
Next real open question is whether it's worth extending jump-diffusion and/or per-leg
spread-awareness to the multi-leg strategy types (verticals/straddles/strangles/
butterflies already got the skew and spread-haircut treatment; jump-diffusion is Long
Call/Put only for now) -- revisit once there's enough graded backtest data on the two
types that have it to see whether it's actually improving calibration in practice.

- [x] Stop-loss pricing (2026-07-23). "When to exit" only had an answer for winners (the
      80%-target exit price) -- nothing for cutting losers. New `STOP_LOSS_PCT` constant
      (default 50%) plus a stop-loss price on Long Call, Long Put, and both Debit
      Verticals: the stock price at which the position has lost that fraction of premium.
      Reuses the same `exit_price_for_target` machinery as the profit target, just solved
      against a lower value. Tested end-to-end on the PEP put case: profit target and
      stop-loss land on opposite sides of spot, as they should. IMPORTANT KNOWN BIAS,
      documented at the constant's definition: this price assumes today's full time-to-
      expiration holds constant, same as the profit target -- but for a stop-loss that
      assumption cuts the wrong way. It makes the number too OPTIMISTIC (theta decay
      alone can produce the loss with a smaller price move than shown), not too
      conservative. Every Stop-Loss line in the output says this explicitly. Not yet
      validated against this bot's own backtest data -- 50% is a reasonable starting
      point, not a proven number.
- [x] Universe expansion (2026-07-23). Added AAL, COIN, DAL, PYPL, SQ, TSM, UAL --
      247 -> 254 tickers, no duplicates. Real gaps closed: payments/fintech (PYPL/SQ/
      COIN) and airlines (AAL/DAL/UAL) had zero individual-name representation despite
      adjacent baskets (JETS) being in the universe; TSM was a notable miss given NVDA/
      AMD/AVGO/MU were already there. Universe is still 100% large/mega-cap by design --
      liquidity filter would kill most small caps anyway.
- [x] Streamlit app audit (2026-07-23). Screener tab confirmed clean: it calls the exact
      same `run_bulk_screener()` as the desktop CLI, so every fix above flows through
      automatically, no separate display logic to maintain. Portfolio tab had a real,
      narrower bug than initially suspected -- an incorrect first-pass claim was made
      that Long Call/Long Put/bearish verticals weren't trackable at all, which was
      WRONG (the backend already handled all of them correctly); the actual bug was
      `streamlit_app.py` hardcoding every non-butterfly position's display as calls
      regardless of whether it was actually a put spread. Fixed with an `opt_letter`
      branch. Also fixed: `st.secrets` access crashed local runs entirely (not just
      missing keys -- a fully absent `secrets.toml`, which is normal locally since
      `.env` covers it), now wrapped in try/except. Also fixed: dollar signs in the
      narrative text were getting interpreted as LaTeX math delimiters by Streamlit's
      markdown renderer when two `$` amounts appeared close together, garbling numbers
      into stray backticks -- same escaping the purchase-info line already had, now
      applied to the narrative text too. Verified end-to-end: Screener tab output
      matched the CLI exactly, Portfolio tab correctly showed all 5 live positions
      (EWZ, KMI, NVDA, PFE, VZ -- MSFT closed same session, realized +$12.81) with
      accurate direction-aware narratives.

## Backlog (not started)

- [ ] Decide: track `backtest_log.csv` in git — **decided: yes** (see completed)
- [ ] Extend jump-diffusion earnings adjustment beyond Long Call/Long Put to the
      multi-leg types (verticals, straddles, strangles, butterflies)
- [ ] Validate `STOP_LOSS_PCT` (currently 50%, unvalidated) against real graded backtest
      data once enough exists -- check whether cutting at 50% actually beats holding to
      expiration for this strategy mix, and whether the "assumes no time decay" optimism
      bias documented above is large enough in practice to matter
- [ ] IV rank/percentile against each stock's OWN historical IV range (not just RV-
      relative "cheap/rich" via `iv_rv_ratio`) -- the ORATS-style upgrade discussed
      2026-07-23; current fixes made the RV-relative signal more honest but it's still
      not the same thing as knowing where IV sits in a stock's own 1-year range
- [ ] Position sizing / portfolio-level risk view -- every trade is currently evaluated
      alone; no Kelly-style sizing by edge/confidence, no check for correlated bets
      across open positions (e.g. three bearish tech plays that are really one
      correlated bet wearing three costumes)
- [ ] Per-strike liquidity filter -- the 254-ticker universe gets a liquidity screen,
      but individual strikes within a chain don't; same failure mode that showed up in
      the Tradier/Schwab IV comparison on deep OTM/ITM PEP strikes could still surface
      a signal pointing at a strike with a terrible spread or near-zero open interest
- [ ] Decide on a backtest-grading cadence -- `grade_backtest.py` only tells you
      anything when it's actually run against enough graded data; nothing scheduled
      currently