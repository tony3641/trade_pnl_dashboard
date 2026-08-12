"""Account Return (TWR / MWR) tab.

Measures the **SPX/SPXW strategy** for each account against the account's
actual capital:

* When **monthly statements** are loaded, the monthly capital base is the
  account's actual value (statement beginning/ending), which includes
  deposits, stock holdings and every other non-SPX/SPXW movement.  The monthly
  return is ``SPX/SPXW PnL ÷ value at month start``; the implied external flow
  (deposits/withdrawals, stock trades, dividends, mark-to-market) is
  ``ending − start − SPX/SPXW PnL``.
* Without statements, the value is built from the ledger alone
  (``initial + Σ SPX/SPXW PnL + Σ non-SPX flows``), which understates the
  account when deposits are not in the transaction file.

A **reconciliation table** splits the account's full ledger into SPX/SPXW PnL
vs. external flows to explain initial → ending.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from src.domain.return_metrics import (
    compute_mwr,
    compute_portfolio_mwr,
    compute_portfolio_twr,
    compute_strategy_twr,
    statement_external_flows,
)
from src.domain.strategy_filter import is_strategy_symbol

_METHODS = ["Both", "TWR", "MWR"]


def _fmt_pct(value) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    return f"{value * 100:.2f}%"


def _fmt_usd(value) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    return f"${value:,.2f}"


def _split_ledger(acct_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split an account's ledger into (SPX/SPXW strategy rows, external-flow rows)."""
    if acct_df.empty:
        return acct_df, acct_df
    strategy_mask = acct_df["symbol"].map(is_strategy_symbol).fillna(False)
    return acct_df[strategy_mask], acct_df[~strategy_mask]


def _reconcile_rows(
    strategy_df: pd.DataFrame,
    external_flows: float,
    initial: float,
    ending: float,
) -> list[dict]:
    """Initial → SPX/SPXW PnL → external flows → ending reconciliation.

    ``external_flows`` is derived from statements (incl. deposits/withdrawals
    and mark-to-market) when statements are loaded, else from the non-SPX/SPXW
    ledger rows.  The residual is a check that the pieces sum to the ending.
    """
    strategy_pnl = float(strategy_df["net_amount"].sum()) if not strategy_df.empty else 0.0
    strategy_value = initial + strategy_pnl + external_flows
    residual = ending - strategy_value
    return [
        {"Item": "Initial Capital", "Value": _fmt_usd(initial)},
        {"Item": "SPX/SPXW Strategy PnL", "Value": _fmt_usd(strategy_pnl)},
        {"Item": "External Flows (incl. deposits / other)", "Value": _fmt_usd(external_flows)},
        {"Item": "Account / Strategy Value (initial + PnL + flows)", "Value": _fmt_usd(strategy_value)},
        {"Item": "Ending / Current Value", "Value": _fmt_usd(ending)},
        {"Item": "Reconciliation Residual (should be ~0)", "Value": _fmt_usd(residual)},
    ]


def _account_date_range(
    acct_df: pd.DataFrame,
    periods: list | None = None,
) -> tuple[date, date]:
    """Analysis window: merge statement-period bounds with the ledger activity range."""
    lo = acct_df["activity_date"].min() if not acct_df.empty else None
    hi = acct_df["activity_date"].max() if not acct_df.empty else None
    for p in (periods or []):
        ps = getattr(p, "period_start", None)
        pe = getattr(p, "period_end", None)
        if ps is not None:
            lo = ps if lo is None else min(lo, ps)
        end = pe or (ps + timedelta(days=30) if ps is not None else None)
        if end is not None:
            hi = end if hi is None else max(hi, end)
    if lo is not None and hi is not None:
        return lo, hi
    today = date.today()
    return today - timedelta(days=30), today


def render_return_tab(
    raw_df: pd.DataFrame,
    account_capital: dict,
    accounts: list[str],
    selected_account: str,
) -> None:
    st.subheader("Account Return")
    st.caption(
        "TWR and MWR measure the **SPX/SPXW strategy only**; everything else "
        "(stocks, dividends, deposits) is treated as an external cash flow."
    )

    method = st.radio("Return Method", _METHODS, horizontal=True, key="ret_method")

    targets = accounts if selected_account == "All Accounts" else [selected_account]
    if not targets:
        st.info("No accounts loaded.")
        return

    portfolio_accounts: list[dict] = []

    for acct in targets:
        cap = account_capital.setdefault(
            acct, {"initial": 100000.0, "ending": None, "flows": [], "periods": []}
        )
        st.markdown(f"### {acct}")

        acct_df_all = (
            raw_df[raw_df["account_id"] == acct] if "account_id" in raw_df else pd.DataFrame()
        )
        periods = list(cap.get("periods") or [])
        start, end = _account_date_range(acct_df_all, periods)

        c1, c2 = st.columns(2)
        saved_initial = float(cap.get("initial") or 100000.0)
        saved_ending = cap.get("ending")
        initial = c1.number_input(
            "Initial Capital (USD)",
            min_value=0.01, value=saved_initial, step=1000.0, format="%.2f",
            key=f"ret_init_{acct}",
        )
        ending = c2.number_input(
            "Ending / Current Value (USD)",
            min_value=0.01, value=float(saved_ending if saved_ending else saved_initial),
            step=1000.0, format="%.2f",
            key=f"ret_end_{acct}",
        )
        cap["initial"] = float(initial)
        cap["ending"] = float(ending)

        # Analysis window (defaults from statements / ledger; user-adjustable).
        dc1, dc2 = st.columns(2)
        start = dc1.date_input("Period Start", value=start, key=f"ret_pstart_{acct}")
        end = dc2.date_input("Period End", value=end, key=f"ret_pend_{acct}")

        # Only rows inside the window contribute to TWR/MWR.
        if not acct_df_all.empty:
            acct_df = acct_df_all[
                (acct_df_all["activity_date"] >= start) & (acct_df_all["activity_date"] <= end)
            ]
        else:
            acct_df = acct_df_all
        strategy_df, flow_df = _split_ledger(acct_df)

        show_twr = method in ("Both", "TWR")
        show_mwr = method in ("Both", "MWR")

        # ---- external cash flows (deposits / withdrawals) ------------------
        user_flows: list[tuple[date, float]] = []
        with st.expander("Additional Deposits / Withdrawals — optional"):
            st.caption(
                "Amount: positive = money added to the account, negative = withdrawn. "
                "Stock trades and dividends are already counted automatically."
            )
            saved_flows = cap.get("flows") or []
            if saved_flows:
                flow_df_ui = pd.DataFrame(saved_flows, columns=["date", "amount"])
            else:
                flow_df_ui = pd.DataFrame({"date": pd.to_datetime([start]), "amount": [0.0]})
            edited = st.data_editor(
                flow_df_ui, num_rows="dynamic", key=f"ret_flows_{acct}",
                column_config={
                    "date": st.column_config.DateColumn("Date"),
                    "amount": st.column_config.NumberColumn("Amount (USD)"),
                },
                use_container_width=True,
            )
            for _, r in edited.dropna(subset=["date"]).iterrows():
                amt = r.get("amount")
                if pd.notna(amt) and amt != 0:
                    user_flows.append((pd.Timestamp(r["date"]).date(), float(amt)))
            cap["flows"] = user_flows

        # ---- TWR -----------------------------------------------------------
        twr_result = None
        mwr_result = None
        spx_pnl = [
            (row["activity_date"], row["net_amount"])
            for _, row in strategy_df.iterrows()
        ]
        ledger_flows = [
            (row["activity_date"], row["net_amount"])
            for _, row in flow_df.iterrows()
        ]
        # Statement-derived external flows (incl. deposits) when statements are
        # loaded — this is what makes the strategy value track the account.
        derived_flows = (
            statement_external_flows(initial, spx_pnl, periods) if periods else []
        )
        ext_flows_total = (
            sum(a for _, a in derived_flows)
            if periods
            else (float(flow_df["net_amount"].sum()) if not flow_df.empty else 0.0)
        )
        strategy_pnl = float(strategy_df["net_amount"].sum()) if not strategy_df.empty else 0.0
        strategy_ending = initial + strategy_pnl + ext_flows_total

        if show_twr:
            twr_result = compute_strategy_twr(
                initial, spx_pnl, ledger_flows, statement_periods=periods or None
            )
            if twr_result.get("warnings"):
                for w in twr_result["warnings"]:
                    st.info(w)

        # ---- MWR -----------------------------------------------------------
        if show_mwr:
            if periods:
                # Account endpoints + statement-derived external flows (incl.
                # deposits), so MWR measures the strategy on the actual account.
                mwr_result = compute_mwr(
                    initial, ending, start, end,
                    cash_flows=derived_flows + user_flows,
                )
            else:
                # No statements: use the strategy's own derived ending value.
                strategy_ending = initial + strategy_pnl + ext_flows_total
                mwr_result = compute_mwr(
                    initial, strategy_ending, start, end,
                    cash_flows=ledger_flows + user_flows,
                )
            if mwr_result.get("warning"):
                st.warning(mwr_result["warning"])

        # Collect inputs for the combined (portfolio) view below.
        portfolio_accounts.append({
            "initial": initial,
            "ending": ending if periods else strategy_ending,
            "spx_pnl_by_date": spx_pnl,
            "external_flows_by_date": ledger_flows,
            "statement_periods": periods or None,
            "mwr_flows": (derived_flows + user_flows) if periods else (ledger_flows + user_flows),
        })

        # ---- result cards --------------------------------------------------
        if show_twr and twr_result:
            m1, m2, m3 = st.columns(3)
            m1.metric("TWR (period)", _fmt_pct(twr_result.get("twr")))
            m2.metric("TWR (annualized)", _fmt_pct(twr_result.get("annualized")))
            m3.metric("Months", str(twr_result.get("period_count", 0)))
        if show_mwr and mwr_result:
            m1, m2, m3 = st.columns(3)
            m1.metric("MWR (period)", _fmt_pct(mwr_result.get("mwr")))
            m2.metric("MWR (annualized)", _fmt_pct(mwr_result.get("annualized")))
            m3.metric("Days", str(mwr_result.get("total_days", 0)))
            if mwr_result.get("converged") and mwr_result.get("mwr") is not None:
                if periods:
                    st.caption(
                        "MWR uses the account's value (from monthly statements) "
                        "as the capital base; deposits/withdrawals and other "
                        "non-SPX/SPXW movements are treated as external cash flows."
                    )
                else:
                    st.caption(
                        "No statements loaded — MWR uses the strategy's derived "
                        f"ending value ({_fmt_usd(strategy_ending)} = initial + "
                        "SPX/SPXW PnL + external flows)."
                    )

        # ---- monthly TWR breakdown -----------------------------------------
        if show_twr and periods:
            spanning = [
                p for p in periods
                if getattr(p, "period_end", None)
                and (p.period_start.year, p.period_start.month)
                != (p.period_end.year, p.period_end.month)
            ]
            if spanning:
                st.caption(
                    "Some statement periods span more than one calendar month "
                    "(e.g. a single QFX export covering Jan–Jul).  Months without "
                    "a real balance snapshot are estimated from the ledger — load "
                    "one QFX file per month to anchor every month."
                )
        if show_twr and twr_result and twr_result.get("periods"):
            with st.expander("Monthly TWR Breakdown", expanded=True):
                ptable = pd.DataFrame(twr_result["periods"])
                ptable["period_start"] = pd.to_datetime(ptable["period_start"]).dt.date
                ptable["period_end"] = pd.to_datetime(ptable["period_end"]).dt.date
                display = ptable.rename(columns={
                    "period_start": "Month", "period_end": "Month End",
                    "beginning_value": "Account Value (start)",
                    "ending_value": "Account Value (end)",
                    "spx_pnl": "SPX/SPXW PnL",
                    "external_flows": "External Flows (incl. deposits)",
                    "monthly_return": "Monthly Return",
                    "cumulative_return": "Cumulative",
                })[["Month", "Month End", "Account Value (start)",
                    "SPX/SPXW PnL", "External Flows (incl. deposits)",
                    "Monthly Return", "Cumulative"]]
                for col in ["Account Value (start)", "SPX/SPXW PnL",
                            "External Flows (incl. deposits)"]:
                    display[col] = display[col].map(lambda v: _fmt_usd(v) if pd.notna(v) else "N/A")
                for col in ["Monthly Return", "Cumulative"]:
                    display[col] = display[col].map(_fmt_pct)
                st.dataframe(display, use_container_width=True, hide_index=True)

        # ---- reconciliation -------------------------------------------------
        with st.expander("Reconciliation (full ledger)", expanded=False):
            st.dataframe(
                pd.DataFrame(_reconcile_rows(
                    strategy_df, ext_flows_total, initial, ending
                )),
                use_container_width=True, hide_index=True,
            )
            st.caption(
                "External flows are derived from the statements when loaded "
                "(they include deposits/withdrawals and mark-to-market); "
                "otherwise from the non-SPX/SPXW trades file rows.  Residual = "
                "Ending/Current Value − (Initial + SPX/SPXW PnL + External "
                "Flows) and should be ~0 when statements and initial capital "
                "align."
            )

    if len(targets) > 1 and portfolio_accounts:
        st.markdown("---")
        st.markdown(
            "<div style='font-size:0.95rem; font-weight:600;'>Combined (All Accounts)</div>",
            unsafe_allow_html=True,
        )
        agg_initial = sum(float(account_capital.get(a, {}).get("initial") or 0.0) for a in targets)
        agg_ending = sum(float(account_capital.get(a, {}).get("ending") or 0.0) for a in targets)

        agg_twr: dict = {}
        agg_mwr: dict = {}
        if show_twr:
            agg_twr = compute_portfolio_twr(portfolio_accounts)
            t1, t2, t3 = st.columns(3)
            t1.metric("TWR (period)", _fmt_pct(agg_twr.get("twr")))
            t2.metric("TWR (annualized)", _fmt_pct(agg_twr.get("annualized")))
            t3.metric("Months", str(agg_twr.get("period_count", 0)))
            if agg_twr.get("warnings"):
                for w in agg_twr["warnings"]:
                    st.info(w)
        if show_mwr:
            all_periods = [p for a in portfolio_accounts for p in (a.get("statement_periods") or [])]
            c_start, c_end = _account_date_range(
                raw_df[raw_df["account_id"].isin(targets)] if "account_id" in raw_df else pd.DataFrame(),
                all_periods,
            )
            agg_mwr = compute_portfolio_mwr(portfolio_accounts, c_start, c_end)
            m1, m2, m3 = st.columns(3)
            m1.metric("MWR (period)", _fmt_pct(agg_mwr.get("mwr")))
            m2.metric("MWR (annualized)", _fmt_pct(agg_mwr.get("annualized")))
            m3.metric("Days", str(agg_mwr.get("total_days", 0)))
            if agg_mwr.get("warning"):
                st.warning(agg_mwr["warning"])

        # Combined monthly TWR breakdown — per-account values summed per month.
        if show_twr and agg_twr.get("periods"):
            with st.expander("Combined Monthly TWR Breakdown", expanded=False):
                ptable = pd.DataFrame(agg_twr["periods"])
                ptable["period_start"] = pd.to_datetime(ptable["period_start"]).dt.date
                ptable["period_end"] = pd.to_datetime(ptable["period_end"]).dt.date
                display = ptable.rename(columns={
                    "period_start": "Month", "period_end": "Month End",
                    "beginning_value": "Portfolio Value (start)",
                    "ending_value": "Portfolio Value (end)",
                    "spx_pnl": "SPX/SPXW PnL",
                    "external_flows": "External Flows",
                    "monthly_return": "Monthly Return",
                    "cumulative_return": "Cumulative",
                })[["Month", "Month End", "Portfolio Value (start)",
                    "SPX/SPXW PnL", "External Flows", "Monthly Return", "Cumulative"]]
                for col in ["Portfolio Value (start)", "SPX/SPXW PnL", "External Flows"]:
                    display[col] = display[col].map(lambda v: _fmt_usd(v) if pd.notna(v) else "N/A")
                for col in ["Monthly Return", "Cumulative"]:
                    display[col] = display[col].map(_fmt_pct)
                st.dataframe(display, use_container_width=True, hide_index=True)

        with st.expander("Combined Reconciliation", expanded=False):
            agg_df = (
                raw_df[raw_df["account_id"].isin(targets)] if "account_id" in raw_df else pd.DataFrame()
            )
            all_periods = [p for a in portfolio_accounts for p in (a.get("statement_periods") or [])]
            a_start, a_end = _account_date_range(agg_df, all_periods)
            if not agg_df.empty:
                agg_df = agg_df[
                    (agg_df["activity_date"] >= a_start) & (agg_df["activity_date"] <= a_end)
                ]
            a_strategy, a_flow = _split_ledger(agg_df)
            agg_flows_total = float(a_flow["net_amount"].sum()) if not a_flow.empty else 0.0
            st.dataframe(
                pd.DataFrame(_reconcile_rows(
                    a_strategy, agg_flows_total, agg_initial, agg_ending
                )),
                use_container_width=True, hide_index=True,
            )
