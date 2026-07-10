# Options Intelligence Desk — User's Guide

This explains what the tool's numbers actually mean and how the mechanics work --
assuming you already know what a call option and a debit spread are, but not
necessarily the specific terms or math this tool uses to score and describe them.

---

## 1. Reading a Debit Vertical setup

Example output:
```
BUY $210.0 C / SELL $225.0 C (Cost: $4.00 | Max Gain: $11.00) | Exp: 2026-09-18
Est. Prob. of Profit: 45% | EV: $+0.60
```

- **BUY/SELL strikes**: you buy the lower-strike call, sell the higher-strike call.
  This caps both your cost and your max gain.
- **Cost**: what you pay per share (multiply by 100 for the per-contract dollar cost).
- **Max Gain**: the most you can make per share -- happens if the stock closes at or
  above the *short* (sold) strike on expiration day. Between the strikes, gain is
  partial and scales linearly.
- **Breakeven**: long strike + cost. Below this at expiration, you lose money;
  above it, you're in profit (up to the max gain cap).
- **Est. Prob. of Profit**: the tool's estimate of the odds the stock closes above
  breakeven by expiration (see Section 4 for how this is calculated and its limits).
- **EV (Expected Value)**: probability-weighted estimate of average outcome per
  contract. Positive EV means the math favors the trade *on average across many
  similar bets* -- it does not mean this specific trade will win.

## 2. Reading a Butterfly Pin setup

Example output:
```
Pin Target $115.0 ($100.0/115.0/130.0) (Cost: $2.65 | Max Gain: $12.35) | Exp: 2026-08-21
Est. Prob. in Profit Zone: 17% | EV: $+0.18
```

**What "pin" means**: the butterfly makes its *maximum* profit only if the stock
closes **exactly** at the middle strike ($115 here) on the expiration date -- nothing
that happens before expiration matters for a butterfly held to expiration. The stock
needs to be "pinned" to that price when time runs out.

**The payoff is a tent shape, not all-or-nothing:**
- Closes exactly at the middle strike -> max profit
- Closes between the breakevens (roughly the outer strikes adjusted for what you
  paid) -> partial profit, shrinking the further from the middle strike
- Closes at or beyond either outer strike ($100 or $130 here) -> you lose your
  full entry cost, nothing more

**Important**: if the stock touches $115 three weeks before expiration and then
drifts to $130 by the actual expiration date, that touch meant nothing. Only the
closing price *on expiration day* determines the payoff.

**Est. Prob. in Profit Zone**: probability the stock finishes anywhere between the
two breakevens -- not the (much smaller) probability of hitting the exact pin for
max profit. Hitting the exact center strike is a single point in a continuous price
distribution, so its standalone probability is near zero; "in the zone" is the
meaningful number.

## 3. Reading the Portfolio tracker (mobile view)

Each position card shows:
- **Spot**: current stock price
- **P/L**: your live profit/loss on the position (per your actual contract count)
- **Days to Exp**: calendar days until expiration
- **Narrative**: plain-language summary -- distance from pin/breakeven, roughly what
  % of max theoretical profit you've captured so far, and general educational context
  (not a personal recommendation)

**"% of max profit captured"** compares your current paper P/L to the max possible
profit if the trade played out perfectly. 17% means you've captured about a sixth of
the total possible gain -- there's no fixed rule for when to take profits early vs.
hold for more, that's a judgment call based on your own read of the setup.

## 4. How "Probability of Profit" is actually calculated

The tool uses a standard Black-Scholes formula: given the stock's current price, a
strike, the option's implied volatility, and days to expiration, it estimates the
probability the stock finishes above that strike, assuming lognormal returns.

**Real limitations, stated plainly:**
- **Uses 0% risk-free rate** and ignores dividends -- a simplification, not a precise
  fair-value model.
- **Implied volatility (IV) tends to run higher than what actually happens** on
  average, because IV includes a "volatility risk premium" -- options are often
  slightly overpriced relative to realized outcomes as compensation for sellers
  bearing risk. This means the tool's probability estimates may be *slightly
  pessimistic* about your odds of profit (since higher assumed IV widens the range
  of "not profitable" outcomes) -- something the backtest calibration report will
  reveal directly over time (see `grade_backtest.py`).
- **Binary EV approximation**: EV math treats the payoff as all-or-nothing at
  breakeven, when the real payoff ramps up gradually. This overstates EV somewhat --
  useful for ranking setups against each other, not as a precise dollar prediction.

## 5. "Auto-close" and order types -- what actually works

Two different things get conflated under "auto-close," and only one of them actually
protects the position:

- **A price alert on the stock** (e.g., "notify me if NOW hits $115"): this tells you
  *nothing* about whether the spread is actually near max value, since butterfly/
  vertical value depends on both price *and* time remaining. Touching the target
  early with weeks left doesn't mean the position is worth much yet.
- **A GTC limit order on the spread's own price**: this is the real mechanism --
  you set a target price for the *spread itself* (e.g., "sell this butterfly once
  it's worth $4.00"), and it closes automatically whenever the market gets there,
  regardless of exactly why. This is what you actually want for "auto-close."

**Robinhood-specific note**: multi-leg spread orders generally have to be placed
in-app manually, not through the automated trading connection -- worth confirming
current behavior before assuming it, since broker capabilities change.

## 6. Why the screener prefers monthly expirations

Options liquidity clusters heavily around the standard monthly expiration (3rd Friday
of the month) -- often 10-50x the open interest of a nearby weekly. The screener
specifically looks for that monthly date inside its 30-75 day window rather than just
grabbing the first available expiration, since thin weeklies produce unreliable
bid/ask spreads and can make a setup look better (or worse) than it really is.

## 7. Quick glossary

| Term | Meaning |
|---|---|
| ATM | At-the-money -- strike price close to the current stock price |
| OI | Open Interest -- number of outstanding contracts at that strike; a liquidity proxy |
| IV | Implied Volatility -- the market's expectation of future price swings, baked into an option's price |
| Breakeven | The stock price at expiration where you neither gain nor lose money |
| EV | Expected Value -- probability-weighted average outcome |
| Debit | What you pay to enter the trade (as opposed to credit, which you'd receive) |
| Pin / Pin risk | The uncertainty of whether a stock will close exactly at a target strike at expiration |
| GTC | Good-Till-Canceled -- an order that stays active until filled or manually canceled |

## 8. When to close a debit vertical for max profit (worked example: PFE)

Real trade: bought the $25 call / sold the $26 call on PFE for $0.20, 2 contracts,
expiring 2026-08-21. PFE was around $24 at entry.

**Max profit condition**: the stock needs to close at or above the *short* strike
($26) on expiration day. Here that's the full $1.00 width minus the $0.20 cost =
$0.80/share = $160 total across 2 contracts.

**You don't have to wait for expiration to capture close to max profit.** If the
stock rallies well above the short strike with weeks still left, the spread will
already be trading near its max value, since both legs are deep in-the-money with
little time value left to lose. Many traders close once the spread's value gets
close to the cap (e.g. $0.90+ of a $1.00 max) rather than holding to the literal
last day -- same economic result, without the extra risk of holding through the
final stretch.

**Early assignment / dividend risk on short calls**: if the underlying pays a
dividend, a short call that's in-the-money right before the ex-dividend date can get
assigned early -- the option holder on the other side may exercise to capture the
dividend. Check the stock's next ex-dividend date against your expiration; if it
falls before expiration and your short strike is ITM at that point, early assignment
is a real possibility, not just a theoretical one.

**Reality check on probability**: this PFE trade needed roughly an 8%+ rally in five
weeks to hit max profit -- the screener's own estimate put this around 27% probability
of profit. That's not a high-confidence setup; it's a small-cost, positive-EV longshot.
Worth remembering what kind of bet you're actually making, not just the payout ratio.

## 9. How the screener picks a strategy for each ticker (regime detection)

As of this update, the screener no longer treats every ticker the same way. For each
ticker, it classifies a **trend regime** using free price history, and dispatches to a
different strategy depending on what it finds:

| Trend | Signal | Strategy scanned |
|---|---|---|
| Bullish | Price > rising 20-day SMA > 50-day SMA | Bull call vertical (buy lower call, sell higher call) |
| Bearish | Price < falling 20-day SMA < 50-day SMA | Bear put vertical (buy higher put, sell lower put) |
| Neutral | Neither of the above cleanly | Butterfly (unchanged from before) |

**Bear put verticals** are the mirror image of the bull call verticals you've already
seen: you buy the higher-strike put and sell the lower-strike put, profiting as the
stock falls. Max profit happens if the stock closes at or below the *short* (lower)
strike at expiration -- same shape as a bull call vertical, just flipped and using puts.

**Why this matters**: before this update, the screener could *only* find bullish
trades -- it would suggest a bull call vertical even on a ticker in a clear downtrend,
which never made sense. Now a downtrending ticker gets scanned for bear put verticals
instead, and an uptrending ticker still gets bull call verticals. Neutral/choppy names
still go to butterflies, unchanged.

**The `[BULLISH]` / `[BEARISH]` / `[NEUTRAL]` tag** at the start of each setup's
description tells you which regime triggered that particular trade -- worth reading
before you act on it, since a bearish tag means the whole thesis is "this stock keeps
falling," not "this stock rises."

**A second signal is also computed but not yet used to pick strategies**: whether
current implied volatility is "rich," "cheap," or "fair" relative to the stock's own
recent realized volatility. This is the foundation for adding straddles/strangles
later (cheap IV + expecting a big move = attractive to buy premium) -- not wired into
strategy selection yet, just being calculated and logged for now.

---

*This guide will grow over time as new concepts come up -- treat it as a living
document, not a finished one.*