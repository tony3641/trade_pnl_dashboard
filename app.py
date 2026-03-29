from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd
import streamlit as st

from src.domain.pnl_engine import build_realized_pnl
from src.io.load_csv import load_transactions_csv
from src.io.load_qfx import InvBalance, load_transactions_qfx
from src.io.load_spx import load_spx_daily
from src.ui.tab_calendar import render_calendar_tab
from src.ui.tab_curve import render_curve_tab
from src.ui.tab_risk import render_risk_tab


st.set_page_config(page_title="Trade PnL Dashboard", layout="wide")
st.title("Trade PnL Dashboard")
st.caption("Realized PnL uses broker Net Amount. Other Fee is excluded from PnL totals.")


with st.sidebar:
    st.header("Data Source")
    uploaded_files = st.file_uploader(
        "Upload CSV or QFX (one or both)",
        type=["csv", "qfx"],
        accept_multiple_files=True,
    )
    st.markdown("or")
    path_input = st.text_input("Load from local path (CSV or QFX)")


# _DEDUP_KEY: columns used to identify duplicate rows when merging CSV + QFX
_DEDUP_KEY = ["activity_date", "account_id", "symbol", "quantity", "net_amount"]


def _load_single_file(f) -> tuple[Optional[pd.DataFrame], Optional[InvBalance]]:
    """Load one uploaded file (CSV or QFX). Returns (df, invbal_or_None)."""
    name = getattr(f, "name", "") or ""
    ext = Path(name).suffix.lower()
    try:
        if ext == ".qfx":
            df, invbal = load_transactions_qfx(f)
            return df, invbal
        else:
            df = load_transactions_csv(f)
            return df, None
    except ValueError as exc:
        st.error(f"{name}: {exc}")
        return None, None


def _load_single_path(p: Path) -> tuple[Optional[pd.DataFrame], Optional[InvBalance]]:
    """Load a file from a local path (CSV or QFX)."""
    ext = p.suffix.lower()
    try:
        if ext == ".qfx":
            df, invbal = load_transactions_qfx(p)
            return df, invbal
        else:
            df = load_transactions_csv(p)
            return df, None
    except ValueError as exc:
        st.error(f"{p.name}: {exc}")
        return None, None


def _merge_frames(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """Concatenate DataFrames and drop obvious duplicates."""
    merged = pd.concat(frames, ignore_index=True)
    # Keep first occurrence of any (date, account, symbol, qty, net_amount) tuple
    dup_cols = [c for c in _DEDUP_KEY if c in merged.columns]
    if dup_cols:
        merged = merged.drop_duplicates(subset=dup_cols, keep="first")
    merged = merged.sort_values("activity_date").reset_index(drop=True)
    # Re-number source_row after merge
    merged["source_row"] = range(1, len(merged) + 1)
    return merged


def _load_input() -> tuple[Optional[pd.DataFrame], Optional[InvBalance]]:
    """Load all uploaded files and/or local path, merge, return (df, invbal)."""
    frames: list[pd.DataFrame] = []
    invbal: Optional[InvBalance] = None

    # Uploaded files (may be multiple)
    for f in (uploaded_files or []):
        df, ib = _load_single_file(f)
        if df is not None and not df.empty:
            frames.append(df)
        if ib is not None:
            invbal = ib  # last QFX wins (typically there's only one)

    # Local path
    if path_input.strip():
        p = Path(path_input.strip())
        if not p.exists():
            st.error("Path does not exist.")
        else:
            df, ib = _load_single_path(p)
            if df is not None and not df.empty:
                frames.append(df)
            if ib is not None:
                invbal = ib

    if not frames:
        return None, None

    merged = _merge_frames(frames)
    return merged, invbal


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


raw_df, qfx_invbal = _load_input()
if raw_df is None:
    st.info("Upload your CSV or QFX file(s) in the sidebar to start.")
    st.stop()

# Auto-compute initial capital from QFX INVBAL when a QFX file is loaded.
# Formula: Initial Capital = Final Balance - Total Realized P&L over the period.
# The user can always override this in the session state widget.
_qfx_auto_capital: Optional[float] = None
if qfx_invbal is not None:
    # Sum ALL net_amounts (trades, dividends, fees, refunds) so that
    # fee/refund pairs cancel out and any net unrefunded fees are included.
    total_net_in_period = float(raw_df["net_amount"].fillna(0.0).sum())
    _qfx_auto_capital = qfx_invbal.total - total_net_in_period
    with st.sidebar:
        st.divider()
        st.markdown("**Account Balance (from QFX)**")
        st.markdown(
            f"Cash: `${qfx_invbal.cash:,.2f}`  \n"
            f"Stock: `${qfx_invbal.stock_value:,.2f}`  \n"
            f"Total: `${qfx_invbal.total:,.2f}`"
        )
        st.caption(
            f"Estimated initial capital: **${_qfx_auto_capital:,.2f}**  \n"
            "(Final balance − period P&L)"
        )

if "shared_initial_capital" not in st.session_state:
    st.session_state["shared_initial_capital"] = (
        _qfx_auto_capital if _qfx_auto_capital is not None else 100000.0
    )
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
