"""
Mobile-friendly web view for the options bot: run the universe screener and check
live portfolio P/L from a phone browser via Streamlit Community Cloud.

This file does NOT duplicate any scanning/scoring logic -- it imports and calls the
exact same functions from options_bot.py that the desktop CLI uses, so results are
always identical between the two.

Local run:  streamlit run streamlit_app.py
"""
import os
import streamlit as st

# On Streamlit Community Cloud, secrets come from st.secrets (set in the app dashboard),
# not from a .env file. We copy PORTFOLIO_JSON into the environment BEFORE importing
# options_bot, since that's the only secret this app still needs -- live market data now
# comes from yfinance (no key/account required at all, see options_bot.py). Locally
# there's no secrets.toml at all, and st.secrets raises if the file is completely missing
# -- not just if a key is absent -- so this is wrapped defensively for local runs.
try:
    if "PORTFOLIO_JSON" in st.secrets:
        os.environ["PORTFOLIO_JSON"] = st.secrets["PORTFOLIO_JSON"]
except Exception:
    pass  # no secrets.toml -- fine locally, .env covers it

import options_bot as bot

st.set_page_config(page_title="Options Intelligence Desk", page_icon="📊", layout="centered")

st.title("📊 Options Intelligence Desk")

# st.code() renders in a <pre> block that doesn't wrap long lines by default -- with
# this bot's long, detail-packed trade descriptions, that meant endless horizontal
# scrolling on a phone just to read one trade. This CSS forces wrapping. (Left in place
# even though the main results now render as cards below, in case st.code is ever used
# elsewhere.)
st.markdown("""
<style>
div[data-testid="stCodeBlock"] pre {
    white-space: pre-wrap !important;
    word-wrap: break-word !important;
    overflow-x: hidden !important;
}
</style>
""", unsafe_allow_html=True)

tab_screener, tab_portfolio = st.tabs(["🔍 Screener", "💼 Portfolio"])

with tab_screener:
    st.caption(f"Universe: {len(bot.UNIVERSE)} candidate tickers, filtered for liquidity, then scanned for positive-EV setups.")
    if st.button("Run Screener", type="primary", use_container_width=True):
        status_box = st.empty()
        log_lines = []

        def show_progress(msg):
            log_lines.append(msg)
            status_box.info("\n\n".join(log_lines))

        with st.spinner("Scanning universe..."):
            result_text, grouped = bot.run_bulk_screener(progress=show_progress, return_setups=True)

        status_box.empty()
        with st.expander("Scan log (tap to see ticker/liquidity/regime counts)"):
            st.write("\n\n".join(log_lines))
        st.markdown("#### Results")

        if not grouped:
            st.info(result_text)
        else:
            any_shown = False
            for category, setups in grouped.items():
                if not setups:
                    continue
                any_shown = True
                st.markdown(f"**{category}**")
                for s in setups:
                    with st.container(border=True):
                        st.markdown(f"**{s['ticker']}**  (Est. EV: ${s['ev']:+.2f}, Prob. of Profit: {s['prob_profit']*100:.0f}%)")
                        # desc is a single pipe-delimited line built for the CLI --
                        # splitting it here gives the same info without the wall-of-text
                        # that required horizontal scrolling to read on a phone.
                        fields = [f.strip() for f in s['desc'].split('|')]
                        for field in fields:
                            st.caption(field.replace("$", "\\$"))
            if not any_shown:
                st.info("No positive-expected-value setups identified across the universe today. That's a legitimate result, not an error -- it means nothing in today's liquid universe cleared the bar once probability of profit is factored in.")

        st.caption("EV estimates use a simplified Black-Scholes probability model. Not a guarantee -- verify in your broker before trading.")

with tab_portfolio:
    st.caption("Reads live positions from the PORTFOLIO_JSON secret. To update it, log a trade with log_trade.py on your desktop, then update the secret in this app's settings.")
    if st.button("Refresh Portfolio", type="primary", use_container_width=True):
        with st.spinner("Pulling live prices..."):
            status = bot.get_portfolio_status()

        if status.get("error"):
            st.error(status["error"])
        elif not status.get("positions"):
            st.info("No open positions found.")
        else:
            for pos in status["positions"]:
                with st.container(border=True):
                    st.markdown(f"**{pos['ticker']}** -- {pos['type']}")
                    if pos.get("error"):
                        st.warning(pos["error"])
                        continue

                    opt_letter = "P" if pos.get("option_type") == "put" else "C"
                    if pos["type"] == "Butterfly Pin":
                        structure = f"{pos['low_strike']:.0f} / {pos['pin_strike']:.0f} / {pos['high_strike']:.0f} C"
                    elif pos["type"] == "Debit Vertical":
                        structure = f"BUY {pos['long_strike']:.0f}{opt_letter} / SELL {pos['short_strike']:.0f}{opt_letter}"
                    elif pos["type"] == "Calendar Spread":
                        structure = f"SELL {pos['strike']:.0f}{opt_letter} {pos['expiration']} / BUY {pos['strike']:.0f}{opt_letter} {pos['far_expiration']}"
                    else:  # Long Call / Long Put -- single leg
                        structure = f"BUY {pos['strike']:.0f}{opt_letter}"
                    total_paid = pos['entry_debit'] * 100 * pos['contracts']
                    purchase_info = (
                        f"Strikes: {structure}  |  Exp: {pos['expiration']}  |  "
                        f"Contracts: {pos['contracts']}  |  "
                        f"Paid: ${pos['entry_debit']:.2f}/share (${total_paid:.2f} total)"
                    ).replace("$", "\\$")
                    st.caption(purchase_info)

                    col1, col2, col3 = st.columns(3)
                    col1.metric("Spot", f"${pos['spot']:.2f}")
                    col2.metric("P/L", f"${pos['pnl']:+.2f}")
                    col3.metric("Days to Exp", pos["days_to_exp"])
                    st.caption(bot.generate_narrative(pos).replace("$", "\\$"))
            st.caption("General educational context only, not personalized trading advice -- always verify against your own broker and judgment before acting.")
    else:
        st.info("Tap 'Refresh Portfolio' to pull current prices, P/L, and a plain-language summary of each position.")