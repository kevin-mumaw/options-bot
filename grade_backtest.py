"""
Grades every logged setup whose expiration date has passed, using the actual closing
price of the underlying on (or near) that date. No historical options data is needed --
for a vertical or butterfly held to expiration, the payoff is fully determined by where
the stock closed, since these are cash-settled at expiration in terms of intrinsic value.

Run this periodically (e.g. weekly) once some of your logged setups' expirations have
passed:

    python grade_backtest.py

Then see the calibration summary at the end -- it tells you whether this tool's
probability/EV estimates are actually tracking reality, or need recalibrating.
"""
import csv
import os
from datetime import datetime, timedelta
import yfinance as yf

LOG_FILE = "backtest_log.csv"


def call_vertical_payoff(spot_at_exp, long_strike, short_strike):
    """Payoff of a long call debit vertical (bull call spread) at expiration (per share)."""
    long_value = max(0.0, spot_at_exp - long_strike)
    short_value = max(0.0, spot_at_exp - short_strike)
    return long_value - short_value


def put_vertical_payoff(spot_at_exp, long_strike, short_strike):
    """Payoff of a long put debit vertical (bear put spread) at expiration (per share).
    long_strike is the higher (bought) strike, short_strike is the lower (sold) strike --
    profit increases as the stock falls."""
    long_value = max(0.0, long_strike - spot_at_exp)
    short_value = max(0.0, short_strike - spot_at_exp)
    return long_value - short_value


def butterfly_payoff(spot_at_exp, low_strike, mid_strike, high_strike):
    """Payoff of a long call butterfly at expiration (per share), built from the exact
    sum of the three individual call legs (long low, short 2x mid, long high) -- this is
    the precise payoff formula, not a triangular approximation."""
    low_value = max(0.0, spot_at_exp - low_strike)
    mid_value = max(0.0, spot_at_exp - mid_strike)
    high_value = max(0.0, spot_at_exp - high_strike)
    return low_value - (2 * mid_value) + high_value


def get_closing_price_near(ticker, date_str):
    """Pulls the stock's closing price on the given date, falling back to the nearest
    prior trading day within a week if the exact date isn't a trading day (holiday, etc)."""
    target = datetime.strptime(date_str, "%Y-%m-%d")
    start = target - timedelta(days=7)
    end = target + timedelta(days=1)
    hist = yf.Ticker(ticker).history(start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"))
    if hist.empty:
        return None
    return float(hist['Close'].iloc[-1])


def grade_log(log_file=LOG_FILE):
    if not os.path.exists(log_file):
        print(f"No {log_file} found -- run the screener first to generate some setups.")
        return

    with open(log_file, "r", newline="") as f:
        rows = list(csv.DictReader(f))

    today = datetime.now()
    graded_count = 0

    for row in rows:
        if row.get("graded") == "yes":
            continue
        try:
            exp_date = datetime.strptime(row["expiration"], "%Y-%m-%d")
        except (ValueError, KeyError):
            continue
        if exp_date > today:
            continue  # not expired yet, nothing to grade

        ticker = row["ticker"]
        spot_at_exp = get_closing_price_near(ticker, row["expiration"])
        if spot_at_exp is None:
            print(f" [!] {ticker}: couldn't get a closing price near {row['expiration']}, skipping")
            continue

        net_cost = float(row["net_cost"])
        if row["type"] == "Debit Vertical":
            option_type = (row.get("option_type") or "call").strip().lower()  # old rows default to call
            if option_type == "put":
                payoff = put_vertical_payoff(spot_at_exp, float(row["long_strike"]), float(row["short_strike"]))
            else:
                payoff = call_vertical_payoff(spot_at_exp, float(row["long_strike"]), float(row["short_strike"]))
        elif row["type"] == "Butterfly Pin":
            payoff = butterfly_payoff(spot_at_exp, float(row["low_strike"]), float(row["mid_strike"]), float(row["high_strike"]))
        else:
            continue

        pnl = (payoff - net_cost) * 100  # per 1 contract
        row["actual_spot_at_exp"] = f"{spot_at_exp:.2f}"
        row["actual_payoff"] = f"{payoff:.2f}"
        row["actual_pnl"] = f"{pnl:.2f}"
        row["win"] = "yes" if pnl > 0 else "no"
        row["graded"] = "yes"
        graded_count += 1

    if graded_count:
        with open(log_file, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)

    print(f"\nGraded {graded_count} newly-expired setups this run.")
    print_calibration_report(rows)


def print_calibration_report(rows):
    graded = [r for r in rows if r.get("graded") == "yes" and r.get("actual_pnl")]
    if not graded:
        print("No graded setups yet -- nothing to report on. Check back once some expirations have passed.")
        return

    print("\n" + "=" * 60)
    print("CALIBRATION REPORT")
    print("=" * 60)

    buckets = [
        ("Bull Call Verticals", lambda r: r["type"] == "Debit Vertical" and (r.get("direction") or "bullish") == "bullish"),
        ("Bear Put Verticals", lambda r: r["type"] == "Debit Vertical" and r.get("direction") == "bearish"),
        ("Butterflies (Neutral)", lambda r: r["type"] == "Butterfly Pin"),
    ]

    for label, match_fn in buckets:
        subset = [r for r in graded if match_fn(r)]
        if not subset:
            continue
        wins = [r for r in subset if r["win"] == "yes"]
        avg_pnl = sum(float(r["actual_pnl"]) for r in subset) / len(subset)
        avg_predicted_prob = sum(float(r["prob_profit"]) for r in subset) / len(subset)
        actual_win_rate = len(wins) / len(subset)
        print(f"\n{label} (n={len(subset)}):")
        print(f"  Avg predicted probability of profit: {avg_predicted_prob*100:.1f}%")
        print(f"  Actual win rate:                      {actual_win_rate*100:.1f}%")
        print(f"  Average P/L per contract:              ${avg_pnl:+.2f}")
        gap = (actual_win_rate - avg_predicted_prob) * 100
        if abs(gap) > 15:
            calibration_direction = "overconfident" if gap < 0 else "underconfident"
            print(f"  --> Model looks {calibration_direction} by ~{abs(gap):.0f} points on this type.")
        else:
            print(f"  --> Reasonably well calibrated (within 15 points).")

    print(f"\nTotal graded: {len(graded)}. More data = more reliable calibration -- keep running the screener and re-grading over time.")


if __name__ == "__main__":
    grade_log()