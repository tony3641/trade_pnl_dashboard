from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

import pandas as pd
import streamlit as st

from src.domain.merge import DEDUP_KEY, merge_transaction_frames
from src.domain.pnl_engine import build_realized_pnl
from src.domain.strategy_filter import filter_strategy_rows, is_etrade_account
from src.io.format_detect import load_csv_by_format
from src.io.load_etrade_pdf import EtradeBalance, load_transactions_etrade_pdf
from src.io.load_qfx import InvBalance, load_transactions_qfx, resolve_qfx_account_id
from src.io.load_spx import load_spx_daily
from src.io.load_vix import load_vix_daily
from src.ui.tab_calendar import render_calendar_tab
from src.ui.tab_curve import render_curve_tab
from src.ui.tab_return import render_return_tab
from src.ui.tab_risk import render_risk_tab


st.set_page_config(page_title="Trade PnL Dashboard", layout="wide")

# ---------------------------------------------------------------------------
# Responsive mobile CSS
# ---------------------------------------------------------------------------
st.markdown("""
<style>
@media (max-width: 768px) {
    /* ---------------------------------------------------------------
       Header bar: fixed at top, sits above everything
    --------------------------------------------------------------- */
    [data-testid="stHeader"] {
        position: fixed !important;
        top: 0 !important;
        left: 0 !important;
        right: 0 !important;
        z-index: 9999 !important;
        height: 3.5rem !important;
        background: var(--background-color, #0e1117) !important;
    }

    /* Sidebar toggle control is top-most and always visible */
    [data-testid="stSidebarCollapsedControl"] {
        position: fixed !important;
        top: 0.5rem !important;
        left: 0.5rem !important;
        z-index: 10001 !important;
        width: 34px !important;
        height: 34px !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        color: #fff !important;
        background: rgba(10, 10, 10, 0.5) !important;
        border-radius: 6px !important;
        box-shadow: 0 0 10px rgba(0,0,0,0.45) !important;
    }
    [data-testid="stSidebarCollapsedControl"] * {
        color: #fff !important;
        font-size: 1.1rem !important;
    }

    /* Push main content below the fixed header */
    .stMainBlockContainer,
    [data-testid="stMainBlockContainer"] {
        padding-top: 4rem !important;
        padding-left: 0.75rem !important;
        padding-right: 0.75rem !important;
    }

    /* ---------------------------------------------------------------
       Sidebar: proper overlay that fully collapses off-screen.
       Do NOT override width on the outer stSidebar element — that
       breaks Streamlit's translateX close animation. Instead, only
       style the inner content panel so it fills the overlay width.
    --------------------------------------------------------------- */
    [data-testid="stSidebar"] {
        z-index: 9998 !important;
    }
    [data-testid="stSidebar"] > div:first-child {
        width: min(80vw, 336px) !important;
        max-width: min(80vw, 336px) !important;
        overflow-x: hidden !important;
        box-sizing: border-box !important;
    }
    /* Ensure complete collapse: if the sidebar gets translated left, do not show a tiny edge */
    [data-testid="stSidebar"] {
        overflow-x: hidden !important;
    }
    /* Constrain all sidebar content to the panel width */
    [data-testid="stSidebar"] * {
        max-width: 100% !important;
        box-sizing: border-box !important;
    }
    /* File uploader box specifically */
    [data-testid="stFileUploader"],
    [data-testid="stFileUploader"] > div,
    [data-testid="stFileUploader"] section {
        width: 100% !important;
        max-width: 100% !important;
        min-width: 0 !important;
    }

    /* ---------------------------------------------------------------
       Stack columns vertically
    --------------------------------------------------------------- */
    [data-testid="stHorizontalBlock"] {
        flex-direction: column !important;
        gap: 0.25rem !important;
    }
    [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
        width: 100% !important;
        flex: 1 1 100% !important;
        min-width: 0 !important;
    }

    /* Touch-friendly radio buttons and segmented controls */
    [data-testid="stRadio"] label,
    [data-testid="stSegmentedControl"] button {
        min-height: 44px !important;
        padding: 0.3rem 0.4rem !important;
        font-size: 0.78rem !important;
        white-space: nowrap !important;
    }

    /* Force view select controls to fit into one row on mobile */
    [data-testid="stSegmentedControl"],
    [data-testid="stRadio"] > div {
        display: flex !important;
        flex-wrap: nowrap !important;
        width: 100% !important;
        justify-content: space-between !important;
    }
    [data-testid="stSegmentedControl"] button,
    [data-testid="stRadio"] label {
        flex: 1 1 0 !important;
        min-width: 0 !important;
        text-align: center !important;
        margin: 0 !important;
        max-width: 25% !important;
    }

    /* Tab set row should not wrap across two lines */
    [data-testid="stSegmentedControl"],
    [data-testid="stRadio"] > div {
        flex-wrap: nowrap !important;
        overflow-x: hidden !important;
    }

    /* Keep scrollbar style for overflow fallback */
    [data-testid="stRadio"] > div::-webkit-scrollbar,
    [data-testid="stSegmentedControl"]::-webkit-scrollbar {
        height: 6px !important;
    }
    [data-testid="stRadio"] > div::-webkit-scrollbar-thumb,
    [data-testid="stSegmentedControl"]::-webkit-scrollbar-thumb {
        background: rgba(140, 158, 210, 0.4) !important;
        border-radius: 4px !important;
    }

    /* Increase metric card readability */
    [data-testid="stMetric"] {
        padding: 0.4rem 0.3rem !important;
    }
    [data-testid="stMetricLabel"] {
        font-size: 0.78rem !important;
    }
    [data-testid="stMetricValue"] {
        font-size: 1.15rem !important;
    }

    /* Touch-friendly inputs */
    [data-testid="stNumberInput"] input,
    [data-testid="stTextInput"] input,
    [data-testid="stDateInput"] input,
    [data-testid="stSelectbox"] > div {
        min-height: 44px !important;
        font-size: 1rem !important;
    }

    /* Horizontal scroll for dataframes instead of squish */
    [data-testid="stDataFrame"] {
        overflow-x: auto !important;
        -webkit-overflow-scrolling: touch !important;
    }

    /* Plotly chart containers: allow horizontal scroll on mobile */
    .stPlotlyChart {
        overflow-x: auto !important;
        -webkit-overflow-scrolling: touch !important;
    }
    .stPlotlyChart > div {
        min-width: 600px !important;
    }

    /* Compact title */
    h1 { font-size: 1.4rem !important; }
    h2, h3 { font-size: 1.1rem !important; }
}
</style>
""", unsafe_allow_html=True)

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


# Aliases from extracted domain modules
_DEDUP_KEY = DEDUP_KEY
_merge_frames = merge_transaction_frames


# Typed union for balance info coming from different sources
_BalanceInfo = Union[InvBalance, EtradeBalance]


def _load_single_file(
    f, csv_account_id: str = "E*Trade",
) -> tuple[Optional[pd.DataFrame], Optional[_BalanceInfo]]:
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
            df = load_csv_by_format(f, account_id=csv_account_id)
            return df, None
    except (ValueError, ImportError) as exc:
        st.error(f"{name}: {exc}")
        return None, None


def _load_single_path(
    p: Path, csv_account_id: str = "E*Trade",
) -> tuple[Optional[pd.DataFrame], Optional[_BalanceInfo]]:
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
            df = load_csv_by_format(p, account_id=csv_account_id)
            return df, None
    except (ValueError, ImportError) as exc:
        st.error(f"{p.name}: {exc}")
        return None, None


def _load_input() -> tuple[Optional[pd.DataFrame], list[_BalanceInfo]]:
    """Load all uploaded files and/or local path, merge, return (df, balances).

    Two-pass loading so an E*Trade trades CSV aligns its account id to a
    loaded E*Trade PDF statement (their option trades overlap and must dedup):
    pass 1 loads balance-bearing formats (QFX / PDF) and discovers E*Trade
    PDF account ids; pass 2 loads CSVs using the resolved account id.
    """
    frames: list[pd.DataFrame] = []
    balances: list[_BalanceInfo] = []
    etrade_pdf_accounts: list[str] = []

    # Local path, if provided and exists
    path_obj: Optional[Path] = None
    if path_input.strip():
        p = Path(path_input.strip())
        if not p.exists():
            st.error("Path does not exist.")
        else:
            path_obj = p

    sources = list(uploaded_files or []) + ([path_obj] if path_obj else [])

    # ---- Pass 1: QFX + PDF (balance-bearing) -------------------------------
    for src in sources:
        ext = (
            src.suffix.lower()
            if isinstance(src, Path)
            else Path(getattr(src, "name", "") or "").suffix.lower()
        )
        if ext not in (".qfx", ".pdf"):
            continue
        df, bal = _load_single_path(src) if isinstance(src, Path) else _load_single_file(src)
        if df is not None and not df.empty:
            frames.append(df)
        if bal is not None:
            balances.append(bal)
            if isinstance(bal, EtradeBalance):
                etrade_pdf_accounts.append(bal.account_id)

    # CSV rows take the E*Trade PDF account id when present so overlapping
    # option trades dedup; otherwise they form the virtual "E*Trade" account.
    csv_account_id = etrade_pdf_accounts[0] if etrade_pdf_accounts else "E*Trade"

    # ---- Pass 2: CSVs (format-detected) ------------------------------------
    for src in sources:
        ext = (
            src.suffix.lower()
            if isinstance(src, Path)
            else Path(getattr(src, "name", "") or "").suffix.lower()
        )
        if ext != ".csv":
            continue
        try:
            if isinstance(src, Path):
                df, _ = _load_single_path(src, csv_account_id=csv_account_id)
            else:
                df, _ = _load_single_file(src, csv_account_id=csv_account_id)
            if df is not None and not df.empty:
                frames.append(df)
        except (ValueError, ImportError) as exc:
            name = getattr(src, "name", "") or str(src)
            st.error(f"{name}: {exc}")

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


@st.cache_data(ttl=21600, show_spinner=False)
def _load_vix_cached(start_date, end_date) -> pd.DataFrame:
    return load_vix_daily(start_date, end_date)


def _load_vix_for_period(daily_df: pd.DataFrame) -> pd.DataFrame:
    if daily_df.empty:
        return pd.DataFrame(columns=[
            "activity_date", "vix_open", "vix_high",
            "vix_low", "vix_close", "vix_change",
        ])

    with st.spinner("Loading VIX historical data..."):
        try:
            return _load_vix_cached(
                daily_df["activity_date"].min(),
                daily_df["activity_date"].max(),
            )
        except Exception as exc:
            st.warning(f"VIX data could not be loaded: {exc}")
            return pd.DataFrame(columns=[
                "activity_date", "vix_open", "vix_high",
                "vix_low", "vix_close", "vix_change",
            ])


raw_df, all_balances = _load_input()
if raw_df is None:
    st.info("Upload your CSV or QFX file(s) in the sidebar to start.")
    st.stop()

# ---------------------------------------------------------------------------
# Per-account capital: balance-derived defaults + user-editable map
# ---------------------------------------------------------------------------
# The per-account capital map is the source of truth for the initial / ending
# capital used by the Account Return (TWR/MWR) tab.  Balance-bearing files
# seed it: QFX initial = final_balance − sum(net_amounts for that account);
# E*Trade PDF initial/ending = earliest beginning_value / latest ending_value.
# E*Trade CSV-only accounts (no balance) are seeded with a $100k default the
# user can override in the sidebar.  The shared initial capital used by the
# Curve / Risk tabs is the sum of the per-account initials.
_auto_capital_map: dict[str, dict] = {}   # account_id → {initial, ending}
_sidebar_lines: list[str] = []

# QFX balances: accumulate statement periods per IBKR account.  Each QFX file
# is one balance snapshot (period_end = <DTASOF>); the latest snapshot anchors
# the account's ending value and the initial is back-computed
# (total − Σ that account's net amounts).  Monthly QFX exports chain into a
# monthly TWR; a single spanning QFX anchors its final month only.
_qfx_by_acct: dict[str, list[InvBalance]] = {}
for bal in all_balances:
    if isinstance(bal, InvBalance):
        _qfx_by_acct.setdefault(resolve_qfx_account_id(bal, raw_df), []).append(bal)

for acct_id, qfx_list in _qfx_by_acct.items():
    # Deduplicate by snapshot date (duplicate files / overlapping ranges).
    unique_bals = {b.as_of: b for b in qfx_list if b.as_of is not None}
    qfx_list = sorted(unique_bals.values(), key=lambda b: b.as_of)
    latest = qfx_list[-1]
    acct_net = float(
        raw_df[raw_df["account_id"] == acct_id]["net_amount"].fillna(0.0).sum()
    )
    cap = latest.total - acct_net
    _auto_capital_map[acct_id] = {
        "initial": cap,
        "ending": latest.total,
        "periods": [b.to_statement_period() for b in qfx_list],
    }
    _sidebar_lines.append(
        f"**QFX {acct_id}**  \n"
        f"Cash: `${latest.cash:,.2f}`  \n"
        f"Stock: `${latest.stock_value:,.2f}`  \n"
        f"Total: `${latest.total:,.2f}`  \n"
        f"Est. initial capital: **${cap:,.2f}**"
    )

# E*Trade PDFs: earliest period_start → initial; latest → ending
_etrade_by_acct: dict[str, list[EtradeBalance]] = {}
for bal in all_balances:
    if isinstance(bal, EtradeBalance):
        _etrade_by_acct.setdefault(bal.account_id, []).append(bal)

for acct_id, ebal_list in _etrade_by_acct.items():
    # Deduplicate by period (duplicate files for the same month may be uploaded).
    unique_bals = {b.period_start: b for b in ebal_list}
    ebal_list = sorted(unique_bals.values(), key=lambda b: b.period_start)
    earliest = ebal_list[0]
    latest = ebal_list[-1]
    _auto_capital_map[acct_id] = {
        "initial": earliest.beginning_value,
        "ending": latest.ending_value,
        "periods": list(ebal_list),  # statement periods → analysis window for TWR/MWR
    }
    _sidebar_lines.append(
        f"**E*Trade {acct_id}**  \n"
        f"Cash: `${earliest.cash:,.2f}`  \n"
        f"Stock: `${earliest.stock_value:,.2f}`  \n"
        f"Initial capital: **${earliest.beginning_value:,.2f}**"
    )

# Merge balance-derived defaults into the persisted per-account map without
# clobbering user edits already stored in session state.
account_capital: dict[str, dict] = dict(st.session_state.get("account_capital", {}))
for acct, vals in _auto_capital_map.items():
    entry = account_capital.setdefault(
        acct, {"initial": vals["initial"], "ending": vals["ending"],
               "flows": [], "periods": list(vals.get("periods") or [])}
    )
    entry.setdefault("initial", vals["initial"])
    if entry.get("ending") is None:
        entry["ending"] = vals["ending"]
    entry.setdefault("flows", [])
    entry.setdefault("periods", list(vals.get("periods") or []))

# E*Trade accounts present in the data without balance-derived capital
# (e.g. the CSV-only virtual account) get a user-editable default.
for acct in raw_df["account_id"].dropna().unique().tolist():
    if is_etrade_account(acct) and acct not in _auto_capital_map:
        account_capital.setdefault(
            acct, {"initial": 100000.0, "ending": None, "flows": [], "periods": []}
        )

st.session_state["account_capital"] = account_capital

with st.sidebar:
    st.divider()
    for line in _sidebar_lines:
        st.markdown(line)
    # E*Trade CSV-only accounts: user sets initial / ending capital here.
    for acct, vals in account_capital.items():
        if is_etrade_account(acct) and acct not in _auto_capital_map:
            init = st.number_input(
                f"{acct} Initial Capital (USD)",
                min_value=0.01,
                value=float(vals.get("initial") or 100000.0),
                step=1000.0, format="%.2f", key=f"side_init_{acct}",
            )
            endv = vals.get("ending")
            endin = st.number_input(
                f"{acct} Ending / Current Value (USD)",
                min_value=0.01,
                value=float(endv if endv else (vals.get("initial") or 100000.0)),
                step=1000.0, format="%.2f", key=f"side_end_{acct}",
            )
            vals["initial"] = init
            vals["ending"] = endin

# Shared initial capital = sum of per-account initials (recomputed each rerun).
_total_initial = sum(float(v.get("initial") or 0.0) for v in account_capital.values())
if _total_initial <= 0:
    _total_initial = 100000.0
st.session_state["shared_initial_capital"] = _total_initial
st.session_state["ctx_shared_initial_capital"] = _total_initial
with st.sidebar:
    st.caption(f"Estimated combined initial capital: **${_total_initial:,.2f}**")
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

# The strategy / PnL views are SPX/SPXW-focused for E*Trade accounts (their
# CSV also contains stock trades).  The full ledger (raw_df) is retained for
# the Account Return tab, which treats non-SPX/SPXW activity as external flows.
strategy_df = filter_strategy_rows(raw_df)
result = build_realized_pnl(strategy_df)
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

view_options = ["Cumulative PnL", "Daily Calendar", "Risk Measurement", "Account Return"]
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
elif view_label == "Account Return":
    render_return_tab(raw_df, account_capital, accounts, selected_account)
else:
    spx_daily = _load_spx_for_period(daily)
    vix_daily = _load_vix_for_period(daily)
    render_risk_tab(daily, spx_daily, vix_daily)
