"""
Daily Risk Check -- 21-DTE Gamma Alert + Closing-Price Stop-Loss Confirmation

Two checks, run together once a day:

1. 21-DTE alert: flags any open position at or inside 21 DTE, per the mechanical
   close/roll rule regardless of P/L (gamma risk accelerates sharply in this window).

2. Stop-loss check, closing-price-confirmed: flags any position whose CURRENT loss has
   reached the STOP_LOSS_PCT threshold (50% of premium paid, same constant options_bot.py
   already uses for scanner recommendations). Only covers Debit Vertical, Long Call, and
   Long Put -- the three types that already have an established stop-loss convention.
   Butterfly Pin, Calendar Spread, and any future credit-spread positions do NOT have a
   defined stop-loss rule yet -- that's a separate, still-open gap, not silently ignored,
   just not solved by this script.

WHY "CLOSING-PRICE CONFIRMED" MATTERS: this script doesn't watch prices continuously --
it only checks whenever it runs. That's actually the fix, not a limitation. If you
instead watched a live intraday price against a target level and reacted the instant it
crossed, you'd be vulnerable to a bot-engineered liquidity-hunt wick: a brief spike
through the level that triggers a manual exit, then reverses an hour later. Checking
ACTUAL POSITION VALUE once, after market close, sidesteps that entirely -- you're
reacting to where the position genuinely settled for the day, not a momentary print.
FOR THIS TO ACTUALLY WORK AS DESIGNED: schedule this task to run AFTER market close
(e.g. 4:30 PM ET), not intraday. Running it mid-session defeats the whole point --
Task Scheduler is already set up from the 21-DTE work, just confirm/adjust its trigger
time to after-hours if it isn't already.

IMPORTANT SCOPE NOTE, same as the DTE checker: this ALERTS ONLY. options-bot has no
order-execution capability -- nothing here places, closes, or modifies any order. You
still have to act on the alert manually.

Usage: identical to daily_dte_check.py -- run manually, or via the same Task Scheduler
task (see setup notes from the original DTE-check delivery).
"""
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import options_bot as bot

DTE_ALERT_THRESHOLD = 21
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dte_alerts.log")

# Position types with an established stop-loss convention in the scanner (STOP_LOSS_PCT-
# based, 50% of premium paid by default). Everything else is intentionally excluded --
# see module docstring.
STOP_LOSS_ELIGIBLE_TYPES = {"Debit Vertical", "Long Call", "Long Put"}


def log(msg):
    print(msg)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass  # logging to file is best-effort -- never let a log-write failure mask the actual alert


def main():
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log(f"\n--- Daily risk check run: {timestamp} ---")

    status = bot.get_portfolio_status()
    if status.get("error"):
        log(f"[ERROR] Could not check portfolio: {status['error']}")
        sys.exit(1)

    positions = status.get("positions", [])
    if not positions:
        log("No open positions found. Nothing to check.")
        sys.exit(0)

    dte_flagged = []
    stop_flagged = []
    stop_ineligible_types_seen = set()

    for pos in positions:
        if pos.get("error"):
            log(f"[WARN] {pos.get('ticker', '?')}: {pos['error']} (skipped -- couldn't get live data)")
            continue

        dte = pos.get("days_to_exp")
        if dte is not None and dte <= DTE_ALERT_THRESHOLD:
            dte_flagged.append(pos)

        pos_type = pos.get("type")
        if pos_type in STOP_LOSS_ELIGIBLE_TYPES:
            entry_debit = pos.get("entry_debit")
            contracts = pos.get("contracts")
            pnl = pos.get("pnl")
            if entry_debit is not None and contracts is not None and pnl is not None:
                max_dollar_loss_at_stop = -(bot.STOP_LOSS_PCT * entry_debit * 100 * contracts)
                # Round both sides to cents before comparing -- floating point
                # multiplication can land a fraction of a cent off zero (e.g.
                # -14.000000000000002 instead of exactly -14.00), which would silently
                # fail to flag a position that lost EXACTLY the stop threshold.
                if round(pnl, 2) <= round(max_dollar_loss_at_stop, 2):
                    stop_flagged.append(pos)
        elif pos_type and pos_type not in STOP_LOSS_ELIGIBLE_TYPES:
            stop_ineligible_types_seen.add(pos_type)

    if not dte_flagged and not stop_flagged:
        log(f"All {len(positions)} open position(s) are outside the {DTE_ALERT_THRESHOLD}-DTE boundary and above their stop-loss threshold. No action needed today.")
    else:
        if dte_flagged:
            log(f"\n*** {len(dte_flagged)} POSITION(S) AT OR INSIDE {DTE_ALERT_THRESHOLD} DTE -- REVIEW FOR CLOSE/ROLL ***\n")
            for pos in dte_flagged:
                log(f"  {pos['ticker']} -- {pos['type']} -- {pos['days_to_exp']} DTE (expires {pos['expiration']}) -- current P/L: ${pos.get('pnl', 0):+.2f}")
                log(f"    {bot.generate_narrative(pos)}")
            log(f"\nReminder: per the 21-DTE rule, close or roll these regardless of current P/L --")
            log(f"gamma risk accelerates sharply inside this window.")

        if stop_flagged:
            log(f"\n*** {len(stop_flagged)} POSITION(S) HAVE HIT THEIR {bot.STOP_LOSS_PCT*100:.0f}% STOP-LOSS THRESHOLD (closing-price confirmed) ***\n")
            for pos in stop_flagged:
                entry_total = pos["entry_debit"] * 100 * pos["contracts"]
                log(f"  {pos['ticker']} -- {pos['type']} -- Entry cost: ${entry_total:.2f} -- Current P/L: ${pos['pnl']:+.2f} ({abs(pos['pnl'])/entry_total*100:.0f}% of premium lost)")
                log(f"    {bot.generate_narrative(pos)}")
            log(f"\nThis is the CLOSING-price-confirmed check -- not a reaction to an intraday wick.")
            log(f"Per the 21-DTE/stop-loss discipline, cutting losers early generally beats riding")
            log(f"toward a full loss. This script only alerts -- you still need to place the")
            log(f"actual close/roll order yourself.")

    if stop_ineligible_types_seen:
        log(f"\n[NOTE] No stop-loss rule is defined yet for: {', '.join(sorted(stop_ineligible_types_seen))}.")
        log(f"        These position(s) are tracked for DTE but NOT checked against any stop-loss threshold.")

    sys.exit(0)


if __name__ == "__main__":
    main()