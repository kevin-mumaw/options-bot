# Pre-Trade 60-Second Gate

Manual checklist for options-bot / weekly-options-signal-engine trades. Run before every entry.

- [ ] **Regime confirmed** — detected regime matches the strategy being dispatched; no gut-feel override.
- [ ] **IV/RV sanity check** — IV/RV ratio not inflated by a recent post-earnings gap. *(Manual until earnings guard + MAD-based vol estimator ship — see IV logic fix backlog.)*
- [ ] **POP/EV threshold** — Black-Scholes POP clears minimum; EV still positive after estimated slippage.
- [ ] **Liquidity** — OI and bid/ask spread within tolerance for the 247-ticker universe.
- [ ] **Earnings/event window** — no earnings, ex-div, or macro print inside the DTE window (unless strategy is explicitly event-driven).
- [ ] **Data source cross-check** — Tradier IV sanity-checked against a second source pending full Schwab migration.
- [ ] **Position sizing / correlation** — new trade doesn't stack unwanted correlation onto existing positions (e.g., rate-sensitive names, current bull put spreads).
- [ ] **Exit defined** — profit target and stop logged *before* order entry, not after.

---

**Retire item 2** once the earnings guard and winsorizing/MAD-based vol estimator fixes ship in options-bot — at that point the IV/RV check is enforced in code and redundant here.