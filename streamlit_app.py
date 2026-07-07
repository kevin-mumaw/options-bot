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
# not from a .env file. We copy it into the environment BEFORE importing options_bot,
# so os.getenv("TRADIER_API_KEY") works the same way locally and when deployed.
if "TRADIER_API_KEY" in st.secrets:
    os.environ["TRADIER_API_KEY"] = st.secrets["TRADIER_API_KEY"]
if "PORTFOLIO_JSON" in st.secrets:
    os.environ["PORTFOLIO_JSON"] = st.secrets["PORTFOLIO_JSON"]

import options_bot as bot

st.set_page_config(page_title="Options Intelligence Desk", page_icon="📊", layout="centered")

st.title("📊 Options Intelligence Desk")

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
            result_text = bot.run_bulk_screener(progress=show_progress)

        status_box.empty()
        st.markdown("#### Results")
        st.code(result_text, language=None)
        st.caption("EV estimates use a simplified Black-Scholes probability model. Not a guarantee -- verify in your broker before trading.")

with tab_portfolio:
    st.caption("Reads portfolio.json committed to this repo. To update it, log a trade with log_trade.py on your desktop, then push to GitHub.")
    if st.button("Refresh Portfolio", type="primary", use_container_width=True):
        with st.spinner("Pulling live prices..."):
            report_text = bot.track_live_portfolio()
        st.code(report_text, language=None)
    else:
        st.info("Tap 'Refresh Portfolio' to pull current prices and P/L.")