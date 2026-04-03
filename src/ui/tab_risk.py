from __future__ import annotations

from datetime import timedelta
import math

import numpy as np
import pandas as pd
import streamlit as st


WINDOW_OPTIONS = ["1M", "3M", "YTD", "1Y", "All", "Custom"]


def _filter_range(df: pd.DataFrame, label: str, custom_start=None, custom_end=None) -> pd.DataFrame:
    if df.empty or label == "All":
        return df.sort_values("activity_date").reset_index(drop=True)

    last_date = df["activity_date"].max()
    if label == "Custom":
        c_start = custom_start if custom_start is not None else df["activity_date"].min()
        c_end = custom_end if custom_end is not None else last_date
        return (
            df[(df["activity_date"] >= c_start) & (df["activity_date"] <= c_end)]
            .copy()
            .sort_values("activity_date")
            .reset_index(drop=True)
        )

    if label == "1M":
        start = last_date - timedelta(days=29)
    elif label == "3M":
        start = last_date - timedelta(days=89)
    elif label == "1Y":
        start = last_date - timedelta(days=364)
    else:
        start = pd.Timestamp(last_date.year, 1, 1).date()

    return (
        df[df["activity_date"] >= start]
        .copy()
        .sort_values("activity_date")
        .reset_index(drop=True)
    )


def _fmt_pct(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    return f"{value * 100:.2f}%"


def _fmt_float(value: float | None, digits: int = 4) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    return f"{value:.{digits}f}"


def _fmt_currency(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    return f"${value:,.2f}"


def _fmt_recovery(max_days: int | None, ongoing_days: int | None) -> str:
    if ongoing_days is not None:
        return f"Ongoing: {ongoing_days}d"
    if max_days is None:
        return "N/A"
    return f"{max_days}d"


def _calc_metrics(
    view: pd.DataFrame,
    initial_capital: float,
    annual_rf: float,
    spx_df: pd.DataFrame | None = None,
) -> dict[str, float | int | None]:
    if view.empty:
        return {}

    # Fill ALL business days between first and last date so that non-trading
    # days (zero PnL, zero return) are properly included in Sharpe / Sortino
    # and SPX alignment.  Without this, metrics are inflated because the
    # series only contains days with trades.
    all_bdays = pd.bdate_range(
        start=view["activity_date"].min(),
        end=view["activity_date"].max(),
    )
    full_cal = pd.DataFrame({"activity_date": all_bdays.date})
    view = (
        full_cal
        .merge(view, on="activity_date", how="left")
        .fillna({"realized_pnl": 0.0, "commission_spent": 0.0,
                 "option_contracts_traded": 0, "trade_count": 0})
        .sort_values("activity_date")
        .reset_index(drop=True)
    )

    rf_daily = annual_rf / 252.0
    pnl = view["realized_pnl"].astype(float)
    daily_returns = pnl / initial_capital
    valid_returns = daily_returns.replace([np.inf, -np.inf], np.nan).dropna()

    period_return = pnl.sum() / initial_capital

    std_daily = valid_returns.std(ddof=1) if len(valid_returns) > 1 else np.nan
    excess_returns = valid_returns - rf_daily
    sharpe = np.nan
    if len(valid_returns) > 1 and std_daily and not np.isclose(std_daily, 0.0):
        sharpe = (excess_returns.mean() / std_daily) * math.sqrt(252)

    downside = np.minimum(excess_returns, 0.0)
    downside_std = downside.std(ddof=1) if len(downside) > 1 else np.nan
    sortino = np.nan
    if len(downside) > 1 and downside_std and not np.isclose(downside_std, 0.0):
        sortino = (excess_returns.mean() / downside_std) * math.sqrt(252)

    positive_cycles = int((pnl > 0).sum())
    negative_cycles = int((pnl < 0).sum())
    max_gain = float(pnl.max()) if not pnl.empty else np.nan
    max_loss = float(pnl.min()) if not pnl.empty else np.nan
    gross_gains = float(pnl[pnl > 0].sum())
    total_commission = float(view["commission_spent"].astype(float).sum())
    commission_drag = np.nan
    if gross_gains > 0:
        commission_drag = total_commission / gross_gains

    equity = pnl.cumsum().reset_index(drop=True)
    dates = pd.to_datetime(view["activity_date"]).reset_index(drop=True)

    peak_equity = float(equity.iloc[0])
    peak_date = dates.iloc[0]
    drawdown_peak_date = None
    max_recovery_days = 0

    for idx in range(1, len(equity)):
        current_equity = float(equity.iloc[idx])
        current_date = dates.iloc[idx]

        if current_equity >= peak_equity:
            if drawdown_peak_date is not None:
                recovery_days = int((current_date - drawdown_peak_date).days)
                max_recovery_days = max(max_recovery_days, recovery_days)
                drawdown_peak_date = None
            peak_equity = current_equity
            peak_date = current_date
        elif drawdown_peak_date is None:
            drawdown_peak_date = peak_date

    ongoing_recovery_days = None
    if drawdown_peak_date is not None:
        ongoing_recovery_days = int((dates.iloc[-1] - drawdown_peak_date).days)

    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    net_ev = np.nan
    cycle_total = len(wins) + len(losses)
    if cycle_total > 0 and len(wins) > 0 and len(losses) > 0:
        p_win = len(wins) / cycle_total
        p_loss = len(losses) / cycle_total
        avg_win = float(wins.mean())
        avg_loss = abs(float(losses.mean()))
        net_ev = p_win * avg_win - p_loss * avg_loss
    elif cycle_total > 0 and len(wins) > 0:
        net_ev = float(wins.mean())
    elif cycle_total > 0 and len(losses) > 0:
        net_ev = float(losses.mean())

    spx_corr = np.nan
    spx_beta = np.nan
    spx_alpha = np.nan
    spx_period_return = np.nan
    return_delta_vs_spx = np.nan
    spx_overlap_days = 0
    if spx_df is not None and not spx_df.empty:
        strategy = view[["activity_date"]].copy()
        strategy["strategy_return"] = daily_returns.values

        benchmark = spx_df[["activity_date", "spx_return"]].copy()
        aligned = strategy.merge(benchmark, on="activity_date", how="inner").dropna()
        spx_overlap_days = int(len(aligned))

        period_start = pd.to_datetime(view["activity_date"].min())
        period_end = pd.to_datetime(view["activity_date"].max())
        benchmark_close = spx_df[["activity_date", "spx_close"]].copy()
        benchmark_close["activity_date"] = pd.to_datetime(benchmark_close["activity_date"])
        benchmark_close["spx_close"] = pd.to_numeric(benchmark_close["spx_close"], errors="coerce")
        benchmark_close = benchmark_close.dropna(subset=["spx_close"]).sort_values("activity_date")

        in_window = benchmark_close[
            (benchmark_close["activity_date"] >= period_start)
            & (benchmark_close["activity_date"] <= period_end)
        ]
        if len(in_window) >= 2:
            start_close = float(in_window.iloc[0]["spx_close"])
            end_close = float(in_window.iloc[-1]["spx_close"])
            if start_close > 0:
                spx_period_return = (end_close / start_close) - 1.0
                return_delta_vs_spx = period_return - spx_period_return

        if spx_overlap_days >= 2:
            strategy_series = aligned["strategy_return"].astype(float)
            benchmark_series = aligned["spx_return"].astype(float)
            benchmark_var = benchmark_series.var(ddof=1)

            spx_corr = strategy_series.corr(benchmark_series)

            if not pd.isna(benchmark_var) and not np.isclose(benchmark_var, 0.0):
                covariance = strategy_series.cov(benchmark_series)
                spx_beta = covariance / benchmark_var
                alpha_daily = ((strategy_series - rf_daily) - spx_beta * (benchmark_series - rf_daily)).mean()
                spx_alpha = alpha_daily * 252.0

    return {
        "period_return": float(period_return),
        "sharpe": float(sharpe) if not pd.isna(sharpe) else np.nan,
        "sortino": float(sortino) if not pd.isna(sortino) else np.nan,
        "std_daily": float(std_daily) if not pd.isna(std_daily) else np.nan,
        "positive_cycles": positive_cycles,
        "negative_cycles": negative_cycles,
        "max_gain": float(max_gain) if not pd.isna(max_gain) else np.nan,
        "max_loss": float(max_loss) if not pd.isna(max_loss) else np.nan,
        "commission_drag": float(commission_drag) if not pd.isna(commission_drag) else np.nan,
        "max_recovery_days": max_recovery_days,
        "ongoing_recovery_days": ongoing_recovery_days,
        "net_ev": float(net_ev) if not pd.isna(net_ev) else np.nan,
        "spx_corr": float(spx_corr) if not pd.isna(spx_corr) else np.nan,
        "spx_beta": float(spx_beta) if not pd.isna(spx_beta) else np.nan,
        "spx_alpha": float(spx_alpha) if not pd.isna(spx_alpha) else np.nan,
        "spx_period_return": float(spx_period_return) if not pd.isna(spx_period_return) else np.nan,
        "return_delta_vs_spx": float(return_delta_vs_spx) if not pd.isna(return_delta_vs_spx) else np.nan,
        "spx_overlap_days": spx_overlap_days,
    }


def render_risk_tab(daily_df: pd.DataFrame, spx_df: pd.DataFrame | None = None) -> None:
    st.subheader("Risk Measurement")

    if daily_df.empty:
        st.info("No data available.")
        return

    saved_capital = float(st.session_state.get("ctx_shared_initial_capital", 100000.0))
    saved_rf = float(st.session_state.get("ctx_risk_annual_rf", 0.0))
    # Ensure the shared key holds a valid option before the widget renders.
    if st.session_state.get("ctx_shared_window") not in WINDOW_OPTIONS:
        st.session_state["ctx_shared_window"] = "1M"

    control_col1, control_col2, control_col3 = st.columns([1, 1, 1])
    with control_col1:
        initial_capital = st.number_input(
            "Initial Capital (USD)",
            min_value=0.01,
            value=saved_capital,
            step=1000.0,
            format="%.2f",
        )
    with control_col2:
        annual_rf_pct = st.number_input(
            "Risk-Free Rate (Annual, %)",
            min_value=0.0,
            value=saved_rf,
            step=0.1,
            format="%.2f",
        )
    with control_col3:
        range_label = st.radio("Window", WINDOW_OPTIONS, horizontal=True, key="ctx_shared_window")

    st.session_state["ctx_shared_initial_capital"] = float(initial_capital)
    st.session_state["ctx_risk_annual_rf"] = float(annual_rf_pct)
    st.session_state["ctx_risk_window"] = range_label
    # ctx_shared_window is already updated automatically via key= on the radio.
    st.session_state["shared_initial_capital"] = float(initial_capital)
    st.session_state["risk_annual_rf"] = float(annual_rf_pct)
    st.session_state["risk_window"] = range_label
    st.session_state["shared_window"] = range_label
    st.session_state["curve_range"] = range_label

    custom_start = None
    custom_end = None
    if range_label == "Custom":
        data_min = daily_df["activity_date"].min()
        data_max = daily_df["activity_date"].max()
        saved_custom_start = st.session_state.get("ctx_custom_start_date", data_min)
        saved_custom_end = st.session_state.get("ctx_custom_end_date", data_max)
        date_col1, date_col2, _ = st.columns([1, 1, 1])
        with date_col1:
            custom_start = st.date_input("Start Date", value=saved_custom_start, min_value=data_min, max_value=data_max)
        with date_col2:
            custom_end = st.date_input("End Date", value=saved_custom_end, min_value=data_min, max_value=data_max)
        st.session_state["ctx_custom_start_date"] = custom_start
        st.session_state["ctx_custom_end_date"] = custom_end

    view = _filter_range(daily_df, range_label, custom_start=custom_start, custom_end=custom_end)
    if view.empty:
        st.info("No data available for selected window.")
        return

    metrics = _calc_metrics(
        view=view,
        initial_capital=float(initial_capital),
        annual_rf=float(annual_rf_pct) / 100.0,
        spx_df=spx_df,
    )

    st.markdown(
        "<div style='font-size:0.95rem; font-weight:600; text-align:left;'>Period Overview</div>",
        unsafe_allow_html=True,
    )
    row1 = st.columns(4)
    row1[0].metric("% Return in Period", _fmt_pct(metrics.get("period_return")))
    row1[1].metric("Positive Cycles", str(metrics.get("positive_cycles", 0)))
    row1[2].metric("Negative Cycles", str(metrics.get("negative_cycles", 0)))
    row1[3].metric(
        "Recovery Time",
        _fmt_recovery(
            int(metrics.get("max_recovery_days", 0)),
            metrics.get("ongoing_recovery_days"),
        ),
    )

    st.markdown(
        "<div style='font-size:0.95rem; font-weight:600; text-align:left;'>Daily Extremes & Cost Drag</div>",
        unsafe_allow_html=True,
    )
    row2 = st.columns(3)
    row2[0].metric("Max Gain (Single Day)", _fmt_currency(metrics.get("max_gain")))
    row2[1].metric("Max Loss (Single Day)", _fmt_currency(metrics.get("max_loss")))
    row2[2].metric("Commission Drag (% Gross Gains)", _fmt_pct(metrics.get("commission_drag")))

    st.markdown(
        "<div style='font-size:0.95rem; font-weight:600; text-align:left;'>Risk-Adjusted Performance</div>",
        unsafe_allow_html=True,
    )
    row3 = st.columns(3)
    row3[0].metric("Sharpe Ratio", _fmt_float(metrics.get("sharpe"), 3))
    row3[1].metric("Sortino Ratio", _fmt_float(metrics.get("sortino"), 3))
    row3[2].metric(
        "Net EV (Expectation)",
        _fmt_currency(metrics.get("net_ev")),
        help=(
            "Day-level expectancy based on realized PnL cycles: "
            "Net EV = P(win) × AvgWin - P(loss) × AvgLoss, where "
            "P(win) = winning days / (winning + losing days), and "
            "AvgLoss uses absolute loss size."
        ),
    )

    st.markdown(
        "<div style='font-size:0.95rem; font-weight:600; text-align:left;'>Benchmark Relationship (SPX)</div>",
        unsafe_allow_html=True,
    )
    row4 = st.columns(5)
    row4[0].metric("SPX Correlation", _fmt_float(metrics.get("spx_corr"), 3))
    row4[1].metric("SPX Alpha (Annualized)", _fmt_pct(metrics.get("spx_alpha")))
    row4[2].metric("SPX Beta", _fmt_float(metrics.get("spx_beta"), 3))
    row4[3].metric("SPX Return in Period", _fmt_pct(metrics.get("spx_period_return")))
    row4[4].metric("Return Delta vs SPX", _fmt_pct(metrics.get("return_delta_vs_spx")))

    st.caption(
        "Returns use realized daily PnL scaled by initial capital. "
        "Sharpe/Sortino are annualized with 252 trading days. "
        "SPX metrics use aligned daily returns versus ^GSPC close."
    )

    if int(metrics.get("spx_overlap_days", 0)) < 2:
        st.info("SPX metrics require at least 2 overlapping dates with benchmark data.")
