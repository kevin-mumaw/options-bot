"""
Run this after you open or close any options position, instead of hand-editing
portfolio.json directly.

Usage: python log_trade.py

Covers every position type options_bot.py can currently track live P/L for: Butterfly,
Bullish/Bearish Debit Vertical, Calendar Spread, Long Call, Long Put. Credit Put/Call
Spreads and Iron Condors can be logged here for record-keeping, but get_portfolio_status()
doesn't yet compute live P/L for those two -- that's a real, separate gap, flagged
honestly rather than silently pretending it works.
"""
import json
import os
import shutil
from datetime import datetime

PORTFOLIO_FILE = "portfolio.json"
BACKUP_FILE = "portfolio_backup.json"
CANCEL_WORDS = ("q", "quit", "cancel", "exit")

ALL_OPEN_CATEGORIES = (
    "butterfly_spreads", "bullish_debit_spreads", "bearish_debit_spreads",
    "calendar_spreads", "long_calls", "long_puts",
    "credit_put_spreads", "credit_call_spreads", "iron_condors",
)


class EntryCancelled(Exception):
    pass


def check_cancel(raw):
    if raw.strip().lower() in CANCEL_WORDS:
        raise EntryCancelled


def load_portfolio():
    if not os.path.exists(PORTFOLIO_FILE):
        print(f"[!] {PORTFOLIO_FILE} not found. Creating a new one.")
        return {c: [] for c in ALL_OPEN_CATEGORIES}
    with open(PORTFOLIO_FILE, "r") as f:
        return json.load(f)


def save_portfolio(portfolio):
    if os.path.exists(PORTFOLIO_FILE):
        shutil.copy(PORTFOLIO_FILE, BACKUP_FILE)
    with open(PORTFOLIO_FILE, "w") as f:
        json.dump(portfolio, f, indent=2)
    print(f"\n[OK] {PORTFOLIO_FILE} updated. Previous version saved to {BACKUP_FILE}.")


def prompt_float(label):
    while True:
        raw = input(f"  {label} (or 'q' to cancel): ").strip()
        check_cancel(raw)
        try:
            return float(raw)
        except ValueError:
            print("  Please enter a number (e.g. 2.65).")


def prompt_int(label):
    while True:
        raw = input(f"  {label} (or 'q' to cancel): ").strip()
        check_cancel(raw)
        try:
            return int(raw)
        except ValueError:
            print("  Please enter a whole number (e.g. 2).")


def prompt_date(label, default_today=False):
    hint = "YYYY-MM-DD, blank for today, or 'q' to cancel" if default_today else "YYYY-MM-DD, or 'q' to cancel"
    while True:
        raw = input(f"  {label} ({hint}): ").strip()
        check_cancel(raw)
        if default_today and raw == "":
            return datetime.now().strftime("%Y-%m-%d")
        try:
            datetime.strptime(raw, "%Y-%m-%d")
            return raw
        except ValueError:
            print("  Please use YYYY-MM-DD format, e.g. 2026-08-21.")


def prompt_str(label):
    while True:
        raw = input(f"  {label} (or 'q' to cancel): ").strip()
        check_cancel(raw)
        if raw:
            return raw.upper()
        print("  This field can't be blank.")


def prompt_call_or_put(label="Call or Put"):
    while True:
        raw = input(f"  {label} (or 'q' to cancel): ").strip()
        check_cancel(raw)
        opt = raw.upper()
        if opt in ("CALL", "PUT"):
            return opt.lower()
        print("  Please enter Call or Put.")


def add_butterfly(portfolio):
    print("\n--- New Butterfly Spread ---")
    entry = {
        "ticker": prompt_str("Ticker"),
        "expiration": prompt_date("Expiration"),
        "long_low_strike": prompt_float("Long low strike"),
        "short_mid_strike": prompt_float("Short mid strike"),
        "long_high_strike": prompt_float("Long high strike"),
        "contracts": prompt_int("Number of contracts (butterflies)"),
        "entry_debit": prompt_float("Net entry debit per share (e.g. 2.65)"),
    }
    portfolio.setdefault("butterfly_spreads", []).append(entry)
    print("\nAdded:")
    print(json.dumps(entry, indent=2))


def add_debit_spread(portfolio, bearish=False):
    label = "Bearish" if bearish else "Bullish"
    category = "bearish_debit_spreads" if bearish else "bullish_debit_spreads"
    print(f"\n--- New {label} Debit Spread ---")
    if bearish:
        print("  (Buy the HIGHER put, sell the LOWER put)")
    else:
        print("  (Buy the LOWER call, sell the HIGHER call)")
    entry = {
        "ticker": prompt_str("Ticker"),
        "expiration": prompt_date("Expiration"),
        "long_strike": prompt_float("Long strike (the one you bought)"),
        "short_strike": prompt_float("Short strike (the one you sold)"),
        "contracts": prompt_int("Number of contracts"),
        "entry_debit": prompt_float("Net entry debit per share (e.g. 1.95)"),
    }
    portfolio.setdefault(category, []).append(entry)
    print("\nAdded:")
    print(json.dumps(entry, indent=2))


def add_calendar_spread(portfolio):
    print("\n--- New Calendar Spread ---")
    print("  (Sell the NEAR-term option, buy the FAR-term option, same strike)")
    entry = {
        "ticker": prompt_str("Ticker"),
        "option_type": prompt_call_or_put(),
        "strike": prompt_float("Strike (same for both legs)"),
        "near_expiration": prompt_date("Near (sold) expiration"),
        "far_expiration": prompt_date("Far (bought) expiration"),
        "contracts": prompt_int("Number of contracts"),
        "entry_debit": prompt_float("Net entry debit per share (e.g. 1.23)"),
    }
    portfolio.setdefault("calendar_spreads", []).append(entry)
    print("\nAdded:")
    print(json.dumps(entry, indent=2))


def add_long_option(portfolio, is_put):
    label = "Long Put" if is_put else "Long Call"
    category = "long_puts" if is_put else "long_calls"
    print(f"\n--- New {label} ---")
    entry = {
        "ticker": prompt_str("Ticker"),
        "expiration": prompt_date("Expiration"),
        "strike": prompt_float("Strike"),
        "contracts": prompt_int("Number of contracts"),
        "entry_cost": prompt_float("Price paid per share (e.g. 3.05)"),
    }
    portfolio.setdefault(category, []).append(entry)
    print("\nAdded:")
    print(json.dumps(entry, indent=2))


def add_credit_spread(portfolio, is_call):
    label = "Credit Call Spread" if is_call else "Credit Put Spread"
    category = "credit_call_spreads" if is_call else "credit_put_spreads"
    print(f"\n--- New {label} ---")
    print("  [!] NOTE: live P/L tracking for this type isn't built yet -- this just")
    print("      records the trade for your own reference and backtest history.")
    entry = {
        "ticker": prompt_str("Ticker"),
        "expiration": prompt_date("Expiration"),
        "short_strike": prompt_float("Short strike (the one you sold)"),
        "long_strike": prompt_float("Long strike (the one you bought for protection)"),
        "contracts": prompt_int("Number of contracts"),
        "entry_credit": prompt_float("Net credit received per share (e.g. 0.75)"),
    }
    portfolio.setdefault(category, []).append(entry)
    print("\nAdded:")
    print(json.dumps(entry, indent=2))


def add_iron_condor(portfolio):
    print("\n--- New Iron Condor ---")
    print("  [!] NOTE: live P/L tracking for this type isn't built yet -- this just")
    print("      records the trade for your own reference and backtest history.")
    entry = {
        "ticker": prompt_str("Ticker"),
        "expiration": prompt_date("Expiration"),
        "put_short_strike": prompt_float("Put side -- short strike"),
        "put_long_strike": prompt_float("Put side -- long (protective) strike"),
        "call_short_strike": prompt_float("Call side -- short strike"),
        "call_long_strike": prompt_float("Call side -- long (protective) strike"),
        "contracts": prompt_int("Number of contracts"),
        "entry_credit": prompt_float("Total net credit received per share (both sides combined)"),
    }
    portfolio.setdefault("iron_condors", []).append(entry)
    print("\nAdded:")
    print(json.dumps(entry, indent=2))


def list_positions(portfolio):
    found_any = False
    for category in ALL_OPEN_CATEGORIES:
        items = portfolio.get(category, [])
        if not items:
            continue
        found_any = True
        print(f"\n{category}:")
        for i, item in enumerate(items):
            print(f"  [{i}] {json.dumps(item)}")
    if not found_any:
        print("\nNo open positions on file.")


def compute_realized_pnl(category, position, exit_price):
    contracts = position["contracts"]
    if category in ("long_calls", "long_puts"):
        entry_cost = position["entry_cost"]
        return (exit_price - entry_cost) * 100 * contracts
    if category in ("credit_put_spreads", "credit_call_spreads", "iron_condors"):
        entry_credit = position["entry_credit"]
        return (entry_credit - exit_price) * 100 * contracts
    entry_cost = position["entry_debit"]
    return (exit_price - entry_cost) * 100 * contracts


def remove_position_no_close(portfolio):
    """For correcting a mistaken entry (duplicate, wrong ticker, never actually a real
    position) -- removes it entirely with NO closed_trades record, unlike close_position
    which always logs a realized P/L. Use close_position instead for any position that
    was actually a real, live trade you're exiting."""
    print("\n--- Remove a Position (correction only -- NOT a real close, no P/L logged) ---")
    list_positions(portfolio)
    categories = [c for c in ALL_OPEN_CATEGORIES if portfolio.get(c)]
    if not categories:
        return
    print("\nWhich category?")
    for i, c in enumerate(categories):
        print(f"  {i}: {c}")
    cat_idx = prompt_int("Category number")
    if cat_idx < 0 or cat_idx >= len(categories):
        print("  Invalid category.")
        return
    category = categories[cat_idx]
    items = portfolio[category]
    for i, item in enumerate(items):
        print(f"  [{i}] {json.dumps(item)}")
    pos_idx = prompt_int("Position number to remove")
    if pos_idx < 0 or pos_idx >= len(items):
        print("  Invalid position number.")
        return
    removed = items.pop(pos_idx)
    print(f"\n[OK] Removed {removed.get('ticker', '?')} from {category}. No P/L was recorded -- if this")
    print("    was actually a real trade you exited, use option 10 (Close) instead next time.")


def close_position(portfolio):
    print("\n--- Close / Remove a Position ---")
    list_positions(portfolio)
    categories = [c for c in ALL_OPEN_CATEGORIES if portfolio.get(c)]
    if not categories:
        return
    print("\nWhich category?")
    for i, c in enumerate(categories):
        print(f"  {i}: {c}")
    cat_idx = prompt_int("Category number")
    if cat_idx < 0 or cat_idx >= len(categories):
        print("  Invalid category.")
        return
    category = categories[cat_idx]
    items = portfolio[category]
    for i, item in enumerate(items):
        print(f"  [{i}] {json.dumps(item)}")
    pos_idx = prompt_int("Position number to close")
    if pos_idx < 0 or pos_idx >= len(items):
        print("  Invalid position number.")
        return

    position = items[pos_idx]
    print("\nClosing:")
    print(json.dumps(position, indent=2))
    if category in ("credit_put_spreads", "credit_call_spreads", "iron_condors"):
        exit_price = prompt_float("Cost to close per share (what you paid to buy it back -- enter 0 if it expired worthless)")
    else:
        exit_price = prompt_float("Exit price per share (what you sold it for -- enter 0 if it expired worthless)")
    close_date = prompt_date("Close date", default_today=True)

    realized_pnl = compute_realized_pnl(category, position, exit_price)

    closed_record = dict(position)
    closed_record["category"] = category
    closed_record["exit_price"] = exit_price
    closed_record["close_date"] = close_date
    closed_record["realized_pnl"] = round(realized_pnl, 2)

    portfolio.setdefault("closed_trades", []).append(closed_record)
    removed = items.pop(pos_idx)

    print(f"\n[OK] Closed {removed.get('ticker', '?')} at ${exit_price:.2f}/share.")
    print(f"    Realized P/L: ${realized_pnl:+.2f}")
    print("    (Recorded in closed_trades -- see option 12 to review your realized P/L history.)")


def show_closed_positions(portfolio):
    closed = portfolio.get("closed_trades", [])
    if not closed:
        print("\nNo closed positions on file yet.")
        return
    print("\n--- Realized P/L History ---")
    total = 0.0
    for c in closed:
        total += c.get("realized_pnl", 0.0)
        print(f"  {c.get('close_date', '?')}  [{c.get('ticker', '?')}] {c.get('category', '?')}  "
              f"exit=${c.get('exit_price', 0):.2f}  P/L: ${c.get('realized_pnl', 0):+.2f}")
    print(f"\n  Total realized P/L: ${total:+.2f} across {len(closed)} closed position(s)")


def main():
    portfolio = load_portfolio()
    print("=" * 46)
    print(" PORTFOLIO TRADE LOGGER")
    print("=" * 46)
    print(" 1: Add a new Butterfly Spread")
    print(" 2: Add a new Bullish Debit Spread")
    print(" 3: Add a new Bearish Debit Spread")
    print(" 4: Add a new Calendar Spread")
    print(" 5: Add a new Long Call")
    print(" 6: Add a new Long Put")
    print(" 7: Add a new Credit Put Spread   [no live P/L tracking yet]")
    print(" 8: Add a new Credit Call Spread  [no live P/L tracking yet]")
    print(" 9: Add a new Iron Condor         [no live P/L tracking yet]")
    print("10: Close / remove an existing position")
    print("11: View current positions (no changes)")
    print("12: View realized P/L history (closed positions)")
    print("13: REMOVE a mistaken entry (correction only -- no P/L logged)")
    print(" 0: Cancel / exit without saving")
    print("-" * 46)
    choice = input(" -> Select an option: ").strip()

    try:
        if choice == "1":
            add_butterfly(portfolio); save_portfolio(portfolio)
        elif choice == "2":
            add_debit_spread(portfolio, bearish=False); save_portfolio(portfolio)
        elif choice == "3":
            add_debit_spread(portfolio, bearish=True); save_portfolio(portfolio)
        elif choice == "4":
            add_calendar_spread(portfolio); save_portfolio(portfolio)
        elif choice == "5":
            add_long_option(portfolio, is_put=False); save_portfolio(portfolio)
        elif choice == "6":
            add_long_option(portfolio, is_put=True); save_portfolio(portfolio)
        elif choice == "7":
            add_credit_spread(portfolio, is_call=False); save_portfolio(portfolio)
        elif choice == "8":
            add_credit_spread(portfolio, is_call=True); save_portfolio(portfolio)
        elif choice == "9":
            add_iron_condor(portfolio); save_portfolio(portfolio)
        elif choice == "10":
            close_position(portfolio); save_portfolio(portfolio)
        elif choice == "11":
            list_positions(portfolio)
        elif choice == "12":
            show_closed_positions(portfolio)
        elif choice == "13":
            remove_position_no_close(portfolio); save_portfolio(portfolio)
        elif choice == "0":
            print("Cancelled, no changes made.")
        else:
            print("Invalid choice, no changes made.")
    except EntryCancelled:
        print("\n[!] Entry cancelled. Nothing was saved.")


if __name__ == "__main__":
    main()