from __future__ import annotations

from datetime import timedelta
from typing import Callable

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st


def _filter_range(df: pd.DataFrame, label: str, custom_start=None, custom_end=None) -> pd.DataFrame:
    if df.empty or label == "All":
        filtered = df.copy().sort_values("activity_date").reset_index(drop=True)
        if filtered.empty:
            return filtered

        filtered["cumulative_pnl"] = filtered["realized_pnl"].cumsum()

        anchor_date = filtered.loc[0, "activity_date"] - timedelta(days=1)
        anchor_row = {col: 0 for col in filtered.columns if col != "activity_date"}
        anchor_row["activity_date"] = anchor_date
        anchor_row["cumulative_pnl"] = 0.0
        return pd.concat([pd.DataFrame([anchor_row]), filtered], ignore_index=True)

    last_date = df["activity_date"].max()
    if label == "Custom":
        c_start = custom_start if custom_start is not None else df["activity_date"].min()
        c_end = custom_end if custom_end is not None else last_date
        filtered = (
            df[(df["activity_date"] >= c_start) & (df["activity_date"] <= c_end)]
            .copy()
            .sort_values("activity_date")
            .reset_index(drop=True)
        )
    else:
        if label == "1M":
            start = last_date - timedelta(days=29)
        elif label == "3M":
            start = last_date - timedelta(days=89)
        elif label == "1Y":
            start = last_date - timedelta(days=364)
        else:
            start = pd.Timestamp(last_date.year, 1, 1).date()
        filtered = df[df["activity_date"] >= start].copy().sort_values("activity_date").reset_index(drop=True)
    if filtered.empty:
        return filtered

    filtered["cumulative_pnl"] = filtered["realized_pnl"].cumsum()

    anchor_date = filtered.loc[0, "activity_date"] - timedelta(days=1)
    anchor_row = {col: 0 for col in filtered.columns if col != "activity_date"}
    anchor_row["activity_date"] = anchor_date
    anchor_row["cumulative_pnl"] = 0.0

    return pd.concat([pd.DataFrame([anchor_row]), filtered], ignore_index=True)


def _build_spx_equity_curve(view: pd.DataFrame, spx_df: pd.DataFrame, initial_capital: float) -> pd.DataFrame:
    if view.empty or spx_df.empty:
        return pd.DataFrame(columns=["activity_date", "spx_equity", "spx_close", "spx_day_change", "spx_cum_return"])

    curve_dates = pd.DataFrame({"activity_date": pd.to_datetime(view["activity_date"])})
    benchmark = spx_df[["activity_date", "spx_close", "spx_return"]].copy()
    benchmark["activity_date"] = pd.to_datetime(benchmark["activity_date"])
    benchmark["spx_close"] = pd.to_numeric(benchmark["spx_close"], errors="coerce")
    benchmark["spx_return"] = pd.to_numeric(benchmark["spx_return"], errors="coerce")
    benchmark = benchmark.dropna(subset=["spx_close"]).sort_values("activity_date")
    if benchmark.empty:
        return pd.DataFrame(columns=["activity_date", "spx_equity", "spx_close", "spx_day_change", "spx_cum_return"])

    aligned = pd.merge_asof(
        curve_dates.sort_values("activity_date"),
        benchmark,
        on="activity_date",
        direction="backward",
    )
    aligned = aligned.dropna(subset=["spx_close"]).copy()
    if aligned.empty:
        return pd.DataFrame(columns=["activity_date", "spx_equity", "spx_close", "spx_day_change", "spx_cum_return"])

    base_close = float(aligned.iloc[0]["spx_close"])
    if base_close <= 0:
        return pd.DataFrame(columns=["activity_date", "spx_equity", "spx_close", "spx_day_change", "spx_cum_return"])

    aligned["spx_equity"] = float(initial_capital) * (aligned["spx_close"] / base_close)
    aligned["spx_day_change"] = aligned["spx_return"].fillna(0.0)
    aligned["spx_cum_return"] = (aligned["spx_close"] / base_close) - 1.0
    aligned["activity_date"] = aligned["activity_date"].dt.date
    return aligned[["activity_date", "spx_equity", "spx_close", "spx_day_change", "spx_cum_return"]]


def render_curve_tab(
    daily_df: pd.DataFrame,
    spx_df: pd.DataFrame | None = None,
    spx_loader: Callable[[], pd.DataFrame] | None = None,
) -> None:
    st.subheader("Return Curve")

    range_options = ["1M", "3M", "YTD", "1Y", "All", "Custom"]
    # Ensure the shared key holds a valid option before the widget renders.
    if st.session_state.get("ctx_shared_window") not in range_options:
        st.session_state["ctx_shared_window"] = "1M"

    saved_capital = float(st.session_state.get("ctx_shared_initial_capital", 100000.0))

    spx_modes = ["Off", "On"]
    saved_spx_mode = str(st.session_state.get("ctx_curve_spx_mode", "Off"))
    if saved_spx_mode not in spx_modes:
        saved_spx_mode = "Off"

    control_col1, control_col2, control_col3 = st.columns([1, 1, 1])
    with control_col1:
        range_label = st.radio("Window", range_options, horizontal=True, key="ctx_shared_window")
    with control_col2:
        initial_capital = st.number_input(
            "Initial Capital (USD)",
            min_value=0.01,
            value=saved_capital,
            step=1000.0,
            format="%.2f",
        )
    with control_col3:
        if hasattr(st, "segmented_control"):
            spx_mode = st.segmented_control(
                "SPX Curve",
                spx_modes,
                default=saved_spx_mode,
            )
        else:
            spx_mode = st.radio(
                "SPX Curve",
                spx_modes,
                horizontal=True,
                index=spx_modes.index(saved_spx_mode),
            )
        if spx_mode is None:
            spx_mode = saved_spx_mode
        show_spx_curve = spx_mode == "On"

    st.session_state["ctx_curve_range"] = range_label
    # ctx_shared_window is already updated automatically via key= on the radio.
    st.session_state["ctx_shared_initial_capital"] = float(initial_capital)
    st.session_state["ctx_curve_spx_mode"] = spx_mode
    st.session_state["shared_initial_capital"] = float(initial_capital)
    st.session_state["curve_range"] = range_label
    st.session_state["curve_spx_mode"] = spx_mode
    st.session_state["shared_window"] = range_label
    st.session_state["risk_window"] = range_label

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
        st.info("No data available for selected range.")
        return

    view = view.copy()
    view["daily_gain"] = view["realized_pnl"].astype(float)
    view["cumulative_return"] = view["cumulative_pnl"].astype(float) / float(initial_capital)
    view["equity_curve"] = float(initial_capital) + view["cumulative_pnl"].astype(float)

    account_color = "#1F77B4"
    spx_color = "#FF7F0E"

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Scatter(
            x=view["activity_date"],
            y=view["equity_curve"],
            mode="lines+markers",
            name="Account Equity Curve",
            line={"color": account_color, "width": 2.4},
            marker={"color": account_color, "size": 6},
            customdata=view[["cumulative_return", "equity_curve", "daily_gain"]].values,
            hovertemplate=(
                "Date=%{x}<br>"
                "Cumulative Return=%{customdata[0]:.2%}<br>"
                "Account Value=$%{customdata[1]:,.2f}<br>"
                "Daily Gain=$%{customdata[2]:,.2f}<extra></extra>"
            ),
        ),
        secondary_y=False,
    )

    spx_curve = pd.DataFrame()
    if show_spx_curve:
        if (spx_df is None or spx_df.empty) and spx_loader is not None:
            spx_df = spx_loader()

        if spx_df is not None and not spx_df.empty:
            spx_curve = _build_spx_equity_curve(view, spx_df, float(initial_capital))
            if not spx_curve.empty:
                fig.add_trace(
                    go.Scatter(
                        x=spx_curve["activity_date"],
                        y=spx_curve["spx_equity"],
                        mode="lines+markers",
                        name="SPX (Normalized)",
                        line={"color": spx_color, "width": 2.2, "dash": "solid"},
                        marker={"color": spx_color, "size": 5},
                        customdata=spx_curve[["spx_close", "spx_day_change", "spx_cum_return"]].values,
                        hovertemplate=(
                            "Date=%{x}<br>"
                            "SPX Close=%{customdata[0]:.1f}<br>"
                            "Day Change=%{customdata[1]:.2%}<br>"
                            "Cumulative Return=%{customdata[2]:.2%}<extra></extra>"
                        ),
                    ),
                    secondary_y=False,
                )
            else:
                st.caption("SPX comparison is unavailable for the selected range.")
        else:
            st.caption("SPX comparison is unavailable for the selected range.")

    expire_days = view[view["expire_inferred_count"] > 0]
    if not expire_days.empty:
        fig.add_trace(
            go.Scatter(
                x=expire_days["activity_date"],
                y=expire_days["equity_curve"],
                mode="markers",
                marker={"size": 11, "symbol": "diamond", "color": "#0B3D91"},
                name="Contains inferred expiry realization",
                customdata=expire_days[
                    ["expire_inferred_contract_count", "expire_inferred_count", "expire_inferred_pnl"]
                ].values,
                hovertemplate=(
                    "Date=%{x}<br>"
                    "Equity=%{y:.2f}<br>"
                    "Inferred expiry contracts=%{customdata[0]}<br>"
                    "Inferred expiry events=%{customdata[1]}<br>"
                    "Inferred expiry pnl=%{customdata[2]:.2f}<extra></extra>"
                ),
            ),
            secondary_y=False,
        )

    return_series = [view["cumulative_return"].astype(float)]
    if not spx_curve.empty:
        return_series.append(spx_curve["spx_cum_return"].astype(float))

    combined_returns = pd.concat(return_series, ignore_index=True)
    min_ret = float(combined_returns.min()) if not combined_returns.empty else 0.0
    max_ret = float(combined_returns.max()) if not combined_returns.empty else 0.0
    span = max(max_ret - min_ret, 0.02)
    pad = span * 0.08
    y2_lower = min(min_ret - pad, -0.001)
    y2_upper = max(max_ret + pad, 0.001)

    fig.add_shape(
        type="rect",
        xref="paper",
        yref="y2",
        x0=0,
        x1=1,
        y0=0,
        y1=y2_upper,
        fillcolor="rgba(34, 139, 34, 0.10)",
        line={"width": 0},
        layer="below",
    )
    fig.add_shape(
        type="rect",
        xref="paper",
        yref="y2",
        x0=0,
        x1=1,
        y0=y2_lower,
        y1=0,
        fillcolor="rgba(220, 20, 60, 0.10)",
        line={"width": 0},
        layer="below",
    )
    fig.add_shape(
        type="line",
        xref="paper",
        yref="y2",
        x0=0,
        x1=1,
        y0=0,
        y1=0,
        line={"color": "rgba(85, 85, 85, 0.85)", "width": 1.5},
        layer="below",
    )

    y_lower = float(initial_capital) * (1.0 + y2_lower)
    y_upper = float(initial_capital) * (1.0 + y2_upper)

    fig.update_layout(
        xaxis_title="Date",
        yaxis_title="Value (USD)",
        margin={"l": 20, "r": 20, "t": 20, "b": 20},
        height=420,
        legend={"orientation": "h", "y": 1.02, "x": 0.0},
    )
    fig.update_yaxes(range=[y_lower, y_upper], secondary_y=False)
    fig.update_yaxes(showgrid=True, secondary_y=False)
    fig.update_yaxes(
        title_text="Return (%)",
        tickformat=".0%",
        range=[y2_lower, y2_upper],
        showgrid=False,
        ticks="outside",
        ticklen=6,
        showline=True,
        side="right",
        secondary_y=True,
    )
    st.plotly_chart(fig, use_container_width=True)

    cols = st.columns(3)
    cols[0].metric("Realized PnL", f"${view['realized_pnl'].sum():,.2f}")
    cols[1].metric("Commission Spent", f"${view['commission_spent'].sum():,.2f}")
    cols[2].metric("Total Trades", int(view["trade_count"].sum()))
