"""
Run this after you open or close any options position, instead of hand-editing
portfolio.json directly.

Usage: python log_trade.py
"""
import json
import os
import shutil
from datetime import datetime

PORTFOLIO_FILE = "portfolio.json"
BACKUP_FILE = "portfolio_backup.json"
CANCEL_WORDS = ("q", "quit", "cancel", "exit")


class EntryCancelled(Exception):
    pass


def check_cancel(raw):
    if raw.strip().lower() in CANCEL_WORDS:
        raise EntryCancelled


def load_portfolio():
    if not os.path.exists(PORTFOLIO_FILE):
        print(f"[!] {PORTFOLIO_FILE} not found. Creating a new one.")
        return {"butterfly_spreads": [], "bullish_debit_spreads": [], "straight_positions": []}
    with open(PORTFOLIO_FILE, "r") as f:
        return json.load(f)


def save_portfolio(portfolio):
    # Always back up before writing, in case of a mistake
    if os.path.exists(PORTFOLIO_FILE):
        shutil.copy(PORTFOLIO_FILE, BACKUP_FILE)
    with open(PORTFOLIO_FILE, "w") as f:
        json.dump(portfolio, f, indent=2)
    print(f"\n[✓] {PORTFOLIO_FILE} updated. Previous version saved to {BACKUP_FILE}.")


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


def prompt_date(label):
    while True:
        raw = input(f"  {label} (YYYY-MM-DD, or 'q' to cancel): ").strip()
        check_cancel(raw)
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


def add_debit_spread(portfolio):
    print("\n--- New Bullish Debit Spread ---")
    entry = {
        "ticker": prompt_str("Ticker"),
        "expiration": prompt_date("Expiration"),
        "long_strike": prompt_float("Long strike"),
        "short_strike": prompt_float("Short strike"),
        "contracts": prompt_int("Number of contracts"),
        "entry_debit": prompt_float("Net entry debit per share (e.g. 1.95)"),
    }
    portfolio.setdefault("bullish_debit_spreads", []).append(entry)
    print("\nAdded:")
    print(json.dumps(entry, indent=2))


def add_straight_position(portfolio):
    print("\n--- New Straight Option Position ---")
    option_type = ""
    while option_type not in ("CALL", "PUT"):
        raw = input("  Call or Put (or 'q' to cancel): ").strip()
        check_cancel(raw)
        option_type = raw.upper()
    entry = {
        "ticker": prompt_str("Ticker"),
        "expiration": prompt_date("Expiration"),
        "strike": prompt_float("Strike"),
        "option_type": option_type.lower(),
        "contracts": prompt_int("Number of contracts"),
        "entry_price": prompt_float("Entry price per share"),
    }
    portfolio.setdefault("straight_positions", []).append(entry)
    print("\nAdded:")
    print(json.dumps(entry, indent=2))


def list_positions(portfolio):
    found_any = False
    for category in ("butterfly_spreads", "bullish_debit_spreads", "straight_positions"):
        items = portfolio.get(category, [])
        if not items:
            continue
        found_any = True
        print(f"\n{category}:")
        for i, item in enumerate(items):
            print(f"  [{i}] {json.dumps(item)}")
    if not found_any:
        print("\nNo open positions on file.")


def close_position(portfolio):
    print("\n--- Close / Remove a Position ---")
    list_positions(portfolio)
    categories = [c for c in ("butterfly_spreads", "bullish_debit_spreads", "straight_positions")
                  if portfolio.get(c)]
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
    print("\nRemoved:")
    print(json.dumps(removed, indent=2))


def main():
    portfolio = load_portfolio()
    print("=" * 46)
    print(" PORTFOLIO TRADE LOGGER")
    print("=" * 46)
    print(" 1: Add a new Butterfly Spread")
    print(" 2: Add a new Bullish Debit Spread")
    print(" 3: Add a new Straight (single-leg) Position")
    print(" 4: Close / remove an existing position")
    print(" 5: View current positions (no changes)")
    print(" 0: Cancel / exit without saving")
    print("-" * 46)
    choice = input(" -> Select an option: ").strip()

    try:
        if choice == "1":
            add_butterfly(portfolio)
            save_portfolio(portfolio)
        elif choice == "2":
            add_debit_spread(portfolio)
            save_portfolio(portfolio)
        elif choice == "3":
            add_straight_position(portfolio)
            save_portfolio(portfolio)
        elif choice == "4":
            close_position(portfolio)
            save_portfolio(portfolio)
        elif choice == "5":
            list_positions(portfolio)
        elif choice == "0":
            print("Cancelled, no changes made.")
        else:
            print("Invalid choice, no changes made.")
    except EntryCancelled:
        print("\n[!] Entry cancelled. Nothing was saved.")


if __name__ == "__main__":
    main()
    