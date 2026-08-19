"""
DEPRECATED (2026-08-19): options_bot.py no longer uses Schwab for anything -- live data
comes from yfinance now (no key/account/OAuth required). This script is dead code, kept
only for reference. Do NOT run it; there's nothing left in options_bot.py that reads
token.json/SCHWAB_TOKEN_PATH anymore. If a weekly Task Scheduler job still calls this
file, disable/delete that task -- it'll just prompt an unnecessary browser login for a
token nothing uses.

Original docstring below, for history:

Weekly Schwab Token Refresh -- run this once every 7 days, when Schwab's refresh token
expires and options_bot.py starts throwing "invalid_grant"/"Refresh token is invalid,
expired or revoked" errors.

THIS CANNOT BE FULLY AUTOMATED. Schwab's OAuth design requires a live human browser
login every 7 days -- no script can renew a refresh token on its own, for any app using
their API. That's a Schwab platform constraint, not a limitation of this script. What
this script DOES do: collapses everything else around that unavoidable step into one
run, in one project folder, instead of the previous multi-step routine (separate
weekly-options-signal-engine trip, manual file copy, manually reformatting the token for
Streamlit).

Usage:
    python weekly_schwab_refresh.py

You will still have to:
    1. Click/paste the printed URL into a browser and log in (unavoidable, Schwab-side).
    2. Copy the redirect URL back into this terminal (unavoidable, Schwab-side).
Everything else -- writing token.json directly into THIS folder, and printing the exact
block to paste into Streamlit's SCHWAB_TOKEN_JSON secret -- happens automatically.
"""
import os
import sys
from dotenv import load_dotenv

load_dotenv()

TOKEN_PATH = "./token.json"


def main():
    api_key = os.getenv("SCHWAB_APP_KEY")
    app_secret = os.getenv("SCHWAB_APP_SECRET")
    if not api_key or not app_secret:
        print("[!] SCHWAB_APP_KEY / SCHWAB_APP_SECRET not found in .env -- can't proceed.")
        print("    These should already be set from the original Schwab setup.")
        sys.exit(1)

    # Wipe any existing (expired) token first, so there's no ambiguity about old vs new.
    if os.path.exists(TOKEN_PATH):
        os.remove(TOKEN_PATH)
        print(f"[*] Removed old {TOKEN_PATH}.")

    try:
        from schwab.auth import client_from_manual_flow
    except ImportError:
        print("[!] schwab-py not installed in this environment. Run: pip install schwab-py")
        sys.exit(1)

    print("[*] Starting the Schwab login flow. Follow the prompts below exactly.\n")
    client_from_manual_flow(
        api_key=api_key,
        app_secret=app_secret,
        callback_url="https://127.0.0.1:8182",
        token_path=TOKEN_PATH,
        enforce_enums=False,
    )

    if not os.path.exists(TOKEN_PATH):
        print("\n[!] Something went wrong -- no token.json was written. Login likely failed or was cancelled.")
        sys.exit(1)

    print(f"\n[OK] {TOKEN_PATH} refreshed successfully, right here in this folder.")
    print("    No more copying between weekly-options-signal-engine and option-bot --")
    print("    this script writes the token directly where options_bot.py needs it.\n")

    with open(TOKEN_PATH, "r") as f:
        token_content = f.read().strip()

    print("=" * 70)
    print("If you also use the DEPLOYED Streamlit app, copy the ENTIRE block below")
    print("(including the triple quotes) and paste it over the existing")
    print("SCHWAB_TOKEN_JSON line in Streamlit Cloud -> Settings -> Secrets,")
    print("then reboot the app. If you only use the app locally, you're already done.")
    print("=" * 70)
    print(f"\nSCHWAB_TOKEN_JSON = '''{token_content}'''\n")
    print("=" * 70)


if __name__ == "__main__":
    main()