"""
Schema migration for backtest_log.csv. Ensures every row has every column the current
version of options_bot.py expects (BACKTEST_LOG_COLUMNS), backfilling sensible values
for columns that didn't exist when older rows were logged.

Rows logged before 'option_type'/'direction' existed were always:
  - "Debit Vertical" -> bull call vertical (option_type=call, direction=bullish)
  - "Butterfly Pin"  -> calls-based, neutral (option_type=call, direction=neutral)
Any other missing column (e.g. new strategy-specific fields added later) is just backfilled
with an empty string, since older rows genuinely don't have that data.

Run this any time options_bot.py's BACKTEST_LOG_COLUMNS changes (new strategy added, new
field needed):
    python migrate_backtest_log.py

Rewrites backtest_log.csv in place. A backup is saved first as backtest_log_backup.csv.
Safe to run multiple times -- if the file already matches the current schema, it does
nothing.
"""
import csv
import os
import shutil

LOG_FILE = "backtest_log.csv"
BACKUP_FILE = "backtest_log_backup.csv"

# Keep this in sync with BACKTEST_LOG_COLUMNS in options_bot.py
CURRENT_COLUMNS = [
    "run_date", "ticker", "type", "option_type", "direction", "expiration", "spot_at_scan",
    "long_strike", "short_strike", "low_strike", "mid_strike", "high_strike",
    "strike", "call_strike", "put_strike",
    "net_cost", "max_profit", "prob_profit", "ev",
    "graded", "actual_spot_at_exp", "actual_payoff", "actual_pnl", "win"
]


def migrate(log_file=LOG_FILE):
    if not os.path.exists(log_file):
        print(f"No {log_file} found -- nothing to migrate.")
        return

    with open(log_file, "r", newline="") as f:
        reader = csv.DictReader(f)
        existing_columns = reader.fieldnames or []
        rows = list(reader)

    if not rows:
        print(f"{log_file} is empty -- nothing to migrate.")
        return

    missing_columns = [c for c in CURRENT_COLUMNS if c not in existing_columns]
    if not missing_columns:
        print("File already matches the current schema. No changes made.")
        return

    print(f"Missing columns found: {missing_columns}")
    shutil.copy(log_file, BACKUP_FILE)
    print(f"Backed up existing file to {BACKUP_FILE}")

    migrated = 0
    for row in rows:
        changed = False
        if "option_type" in missing_columns and not row.get("option_type"):
            if row.get("type") == "Debit Vertical":
                row["option_type"] = "call"
                row["direction"] = "bullish"
            elif row.get("type") == "Butterfly Pin":
                row["option_type"] = "call"
                row["direction"] = "neutral"
            else:
                row["option_type"] = "call"
                row["direction"] = "unknown"
            changed = True
        for col in missing_columns:
            if col not in row:
                row[col] = row.get(col, "")
                changed = True
        if changed:
            migrated += 1

    with open(log_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CURRENT_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in CURRENT_COLUMNS})

    print(f"Migrated {migrated} row(s) to the current schema. {log_file} updated.")


if __name__ == "__main__":
    migrate()