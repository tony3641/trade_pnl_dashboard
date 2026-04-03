from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

import pandas as pd
import streamlit as st

from src.domain.pnl_engine import build_realized_pnl
from src.io.load_csv import load_transactions_csv
from src.io.load_etrade_pdf import EtradeBalance, load_transactions_etrade_pdf
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
        "Upload CSV, QFX, or E*Trade PDF",
        type=["csv", "qfx", "pdf"],
        accept_multiple_files=True,
    )
    st.markdown("or")
    path_input = st.text_input("Load from local path (CSV, QFX, or PDF)")


# _DEDUP_KEY: columns used to identify duplicate rows when merging CSV + QFX
_DEDUP_KEY = ["activity_date", "account_id", "symbol", "quantity", "net_amount"]


# Typed union for balance info coming from different sources
_BalanceInfo = Union[InvBalance, EtradeBalance]


def _load_single_file(f) -> tuple[Optional[pd.DataFrame], Optional[_BalanceInfo]]:
    """Load one uploaded file (CSV, QFX, or PDF). Returns (df, balance_or_None)."""
    name = getattr(f, "name", "") or ""
    ext = Path(name).suffix.lower()
    # Streamlit UploadedFile keeps stream position between rerenders.
    # Seek to the beginning so .read() inside each loader always gets full bytes.
    if hasattr(f, "seek"):
        f.seek(0)
    try:
        if ext == ".qfx":
            df, invbal = load_transactions_qfx(f)
            return df, invbal
        elif ext == ".pdf":
            df, ebal = load_transactions_etrade_pdf(f)
            return df, ebal
        else:
            df = load_transactions_csv(f)
            return df, None
    except (ValueError, ImportError) as exc:
        st.error(f"{name}: {exc}")
        return None, None


def _load_single_path(p: Path) -> tuple[Optional[pd.DataFrame], Optional[_BalanceInfo]]:
    """Load a file from a local path (CSV, QFX, or PDF)."""
    ext = p.suffix.lower()
    try:
        if ext == ".qfx":
            df, invbal = load_transactions_qfx(p)
            return df, invbal
        elif ext == ".pdf":
            df, ebal = load_transactions_etrade_pdf(p)
            return df, ebal
        else:
            df = load_transactions_csv(p)
            return df, None
    except (ValueError, ImportError) as exc:
        st.error(f"{p.name}: {exc}")
        return None, None


def _merge_frames(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """Concatenate DataFrames and drop cross-file duplicates.

    Each frame is tagged with a ``_src`` index so that we only dedup rows that
    appear in *different* source files.  Rows within the same file are always
    kept — they represent distinct broker executions that may happen to share
    the same (date, account, symbol, qty, net_amount) tuple (e.g. multiple
    partial fills at the same price from IBKR).
    """
    tagged: list[pd.DataFrame] = []
    for idx, df in enumerate(frames):
        tmp = df.copy()
        tmp["_src"] = idx
        tagged.append(tmp)

    merged = pd.concat(tagged, ignore_index=True)

    dup_cols = [c for c in _DEDUP_KEY if c in merged.columns]
    if dup_cols and len(frames) > 1:
        # For each dedup-key group, keep ALL rows from the first source that
        # has them, and drop rows from later sources whose key already appeared
        # in an earlier source.
        keep_mask = pd.Series(True, index=merged.index)
        seen: set[tuple] = {}  # type: ignore[assignment]
        seen = {}  # dedup_key_tuple → set of _src values that contributed it

        for i, row in merged.iterrows():
            key = tuple(row[c] for c in dup_cols)
            src = row["_src"]
            if key not in seen:
                seen[key] = src
            elif seen[key] != src:
                # This key already contributed by a different source file —
                # mark this row for removal.
                keep_mask.at[i] = False

        merged = merged[keep_mask]

    merged = merged.drop(columns=["_src"], errors="ignore")
    merged = merged.sort_values("activity_date").reset_index(drop=True)
    # Re-number source_row after merge
    merged["source_row"] = range(1, len(merged) + 1)
    return merged


def _load_input() -> tuple[Optional[pd.DataFrame], list[_BalanceInfo]]:
    """Load all uploaded files and/or local path, merge, return (df, balances)."""
    frames: list[pd.DataFrame] = []
    balances: list[_BalanceInfo] = []

    # Uploaded files (may be multiple)
    for f in (uploaded_files or []):
        df, bal = _load_single_file(f)
        if df is not None and not df.empty:
            frames.append(df)
        if bal is not None:
            balances.append(bal)

    # Local path
    if path_input.strip():
        p = Path(path_input.strip())
        if not p.exists():
            st.error("Path does not exist.")
        else:
            df, bal = _load_single_path(p)
            if df is not None and not df.empty:
                frames.append(df)
            if bal is not None:
                balances.append(bal)

    if not frames:
        return None, []

    merged = _merge_frames(frames)
    return merged, balances


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
        except Exception as exc:
            st.warning(f"SPX data could not be loaded: {exc}")
            return pd.DataFrame(columns=["activity_date", "spx_close", "spx_return"])


raw_df, all_balances = _load_input()
if raw_df is None:
    st.info("Upload your CSV or QFX file(s) in the sidebar to start.")
    st.stop()

# ---------------------------------------------------------------------------
# Auto-compute initial capital from all balance sources
# ---------------------------------------------------------------------------
# For each account we determine an initial-capital estimate:
#   • QFX  (InvBalance): Initial = final_balance − sum(net_amounts for that acct)
#   • E*Trade PDF (EtradeBalance): Initial = beginning_value of the *earliest*
#     statement for that account.
# When multiple accounts are loaded the totals are summed.
_auto_capital: Optional[float] = None
_capital_parts: dict[str, float] = {}   # account_id → estimated initial capital
_sidebar_lines: list[str] = []

for bal in all_balances:
    if isinstance(bal, InvBalance):
        # Only subtract the QFX account's net amounts, not all accounts'.
        # The QFX file doesn't carry an account_id on the balance object,
        # so we look up which account_id the QFX rows belong to.  When
        # multiple QFX files are loaded (rare), each InvBalance still
        # corresponds to the rows from its own file.
        qfx_accounts = set(
            raw_df[raw_df["account_id"].str.startswith("U", na=False)]["account_id"].unique()
        )
        if qfx_accounts:
            acct_net = float(
                raw_df[raw_df["account_id"].isin(qfx_accounts)]["net_amount"]
                .fillna(0.0).sum()
            )
        else:
            acct_net = float(raw_df["net_amount"].fillna(0.0).sum())
        cap = bal.total - acct_net
        key = "__qfx__"
        _capital_parts[key] = cap
        _sidebar_lines.append(
            f"**QFX Account Balance**  \n"
            f"Cash: `${bal.cash:,.2f}`  \n"
            f"Stock: `${bal.stock_value:,.2f}`  \n"
            f"Total: `${bal.total:,.2f}`  \n"
            f"Est. initial capital: **${cap:,.2f}**"
        )

# E*Trade PDFs: pick earliest period_start per account
_etrade_by_acct: dict[str, list[EtradeBalance]] = {}
for bal in all_balances:
    if isinstance(bal, EtradeBalance):
        _etrade_by_acct.setdefault(bal.account_id, []).append(bal)

for acct_id, ebal_list in _etrade_by_acct.items():
    earliest = min(ebal_list, key=lambda b: b.period_start)
    _capital_parts[acct_id] = earliest.beginning_value
    _sidebar_lines.append(
        f"**E*Trade {acct_id}**  \n"
        f"Cash: `${earliest.cash:,.2f}`  \n"
        f"Stock: `${earliest.stock_value:,.2f}`  \n"
        f"Initial capital: **${earliest.beginning_value:,.2f}**"
    )

if _capital_parts:
    _auto_capital = sum(_capital_parts.values())
    with st.sidebar:
        st.divider()
        for line in _sidebar_lines:
            st.markdown(line)
        if len(_capital_parts) > 1:
            st.caption(f"Combined initial capital: **${_auto_capital:,.2f}**")
        else:
            st.caption(f"Estimated initial capital: **${_auto_capital:,.2f}**")

# Always refresh the initial capital when balance info was derived from the
# currently loaded file(s). Only fall back to the existing session value (or
# 100 000 as a last resort) when no file supplies balance information.
if _auto_capital is not None:
    st.session_state["shared_initial_capital"] = _auto_capital
    st.session_state["ctx_shared_initial_capital"] = _auto_capital
elif "shared_initial_capital" not in st.session_state:
    st.session_state["shared_initial_capital"] = 100000.0
    st.session_state["ctx_shared_initial_capital"] = 100000.0
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
