"""
One-time migration: adds the new 'option_type' and 'direction' columns to an existing
backtest_log.csv, backfilling correct values for rows logged before those columns existed.

All setups logged before this migration were either:
  - "Debit Vertical" -> always a bull call vertical (option_type=call, direction=bullish)
  - "Butterfly Pin"  -> always calls-based, neutral (option_type=call, direction=neutral)

Run this ONCE:
    python migrate_backtest_log.py

It rewrites backtest_log.csv in place. A backup is saved first as backtest_log_backup.csv.
Safe to run multiple times -- rows that already have option_type/direction filled in are
left untouched.
"""
import csv
import os
import shutil

LOG_FILE = "backtest_log.csv"
BACKUP_FILE = "backtest_log_backup.csv"

NEW_COLUMNS = [
    "run_date", "ticker", "type", "option_type", "direction", "expiration", "spot_at_scan",
    "long_strike", "short_strike", "low_strike", "mid_strike", "high_strike",
    "net_cost", "max_profit", "prob_profit", "ev",
    "graded", "actual_spot_at_exp", "actual_payoff", "actual_pnl", "win"
]


def migrate(log_file=LOG_FILE):
    if not os.path.exists(log_file):
        print(f"No {log_file} found -- nothing to migrate.")
        return

    with open(log_file, "r", newline="") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        print(f"{log_file} is empty -- nothing to migrate.")
        return

    if "option_type" in rows[0] and rows[0].get("option_type"):
        print("File already has option_type filled in on the first row -- migration likely already ran. No changes made.")
        return

    shutil.copy(log_file, BACKUP_FILE)
    print(f"Backed up existing file to {BACKUP_FILE}")

    migrated = 0
    for row in rows:
        if not row.get("option_type"):
            if row.get("type") == "Debit Vertical":
                row["option_type"] = "call"
                row["direction"] = "bullish"
            elif row.get("type") == "Butterfly Pin":
                row["option_type"] = "call"
                row["direction"] = "neutral"
            else:
                row["option_type"] = "call"
                row["direction"] = "unknown"
            migrated += 1

    with open(log_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=NEW_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in NEW_COLUMNS})

    print(f"Migrated {migrated} row(s) to the new schema. {log_file} updated.")


if __name__ == "__main__":
    migrate()