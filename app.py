from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from src.domain.pnl_engine import build_realized_pnl
from src.io.load_csv import load_transactions_csv
from src.io.load_spx import load_spx_daily
from src.ui.tab_calendar import render_calendar_tab
from src.ui.tab_curve import render_curve_tab
from src.ui.tab_risk import render_risk_tab


st.set_page_config(page_title="Trade PnL Dashboard", layout="wide")
st.title("Trade PnL Dashboard")
st.caption("Realized PnL uses broker Net Amount. Other Fee is excluded from PnL totals.")


with st.sidebar:
    st.header("Data Source")
    uploaded = st.file_uploader("Upload YTD CSV", type=["csv"])
    st.markdown("or")
    path_input = st.text_input("Load from local path")


def _load_input():
    if uploaded is not None:
        try:
            return load_transactions_csv(uploaded)
        except ValueError as exc:
            st.error(str(exc))
            return None
    if path_input.strip():
        csv_path = Path(path_input.strip())
        if not csv_path.exists():
            st.error("Path does not exist.")
            return None
        try:
            return load_transactions_csv(csv_path)
        except ValueError as exc:
            st.error(str(exc))
            return None
    return None


@st.cache_data(ttl=21600, show_spinner=False)
def _load_spx_cached(start_date, end_date) -> pd.DataFrame:
    return load_spx_daily(start_date, end_date)


def _load_spx_for_period(daily_df: pd.DataFrame) -> pd.DataFrame:
    if daily_df.empty:
        return pd.DataFrame(columns=["activity_date", "spx_close", "spx_return"])

    with st.spinner("Loading SPX historical data..."):
        try:
            return _load_spx_cached(
                daily_df["activity_date"].min(),
                daily_df["activity_date"].max(),
            )
        except Exception:
            st.warning("SPX data could not be loaded within 15 seconds or encountered an error.")
            return pd.DataFrame(columns=["activity_date", "spx_close", "spx_return"])


raw_df = _load_input()
if raw_df is None:
    st.info("Upload your YTD CSV in the sidebar to start.")
    st.stop()

if "shared_initial_capital" not in st.session_state:
    st.session_state["shared_initial_capital"] = 100000.0
if "curve_spx_mode" not in st.session_state:
    st.session_state["curve_spx_mode"] = "Off"
if "curve_range" not in st.session_state:
    st.session_state["curve_range"] = "1M"
if "risk_window" not in st.session_state:
    st.session_state["risk_window"] = "1M"
if "risk_annual_rf" not in st.session_state:
    st.session_state["risk_annual_rf"] = 0.0
if "shared_window" not in st.session_state:
    st.session_state["shared_window"] = "1M"
if "ctx_shared_initial_capital" not in st.session_state:
    st.session_state["ctx_shared_initial_capital"] = float(st.session_state["shared_initial_capital"])
if "ctx_curve_spx_mode" not in st.session_state:
    st.session_state["ctx_curve_spx_mode"] = str(st.session_state["curve_spx_mode"])
if "ctx_curve_range" not in st.session_state:
    st.session_state["ctx_curve_range"] = str(st.session_state["curve_range"])
if "ctx_risk_window" not in st.session_state:
    st.session_state["ctx_risk_window"] = str(st.session_state["risk_window"])
if "ctx_risk_annual_rf" not in st.session_state:
    st.session_state["ctx_risk_annual_rf"] = float(st.session_state["risk_annual_rf"])
if "ctx_shared_window" not in st.session_state:
    st.session_state["ctx_shared_window"] = str(
        st.session_state.get("shared_window", st.session_state.get("ctx_risk_window", "1M"))
    )

result = build_realized_pnl(raw_df)
rows = result.enriched_rows
daily = result.daily

accounts = sorted(rows["account_id"].dropna().unique().tolist())
selected_account = st.selectbox("Account", ["All Accounts"] + accounts, key="selected_account")
if selected_account != "All Accounts":
    daily = (
        rows[rows["account_id"] == selected_account]
        .pipe(build_realized_pnl)
        .daily
    )

view_options = ["Cumulative PnL", "Daily Calendar", "Risk Measurement"]
if "active_view" not in st.session_state:
    st.session_state["active_view"] = view_options[0]

if hasattr(st, "segmented_control"):
    view_label = st.segmented_control(
        "View",
        view_options,
        key="active_view",
    )
else:
    view_label = st.radio(
        "View",
        view_options,
        horizontal=True,
        key="active_view",
    )

if view_label is None:
    view_label = st.session_state.get("active_view", view_options[0])

if view_label == "Cumulative PnL":
    render_curve_tab(daily, spx_loader=lambda: _load_spx_for_period(daily))
elif view_label == "Daily Calendar":
    render_calendar_tab(daily)
else:
    spx_daily = _load_spx_for_period(daily)
    render_risk_tab(daily, spx_daily)
