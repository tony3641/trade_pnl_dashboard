from __future__ import annotations

import calendar
from datetime import timedelta

import numpy as np

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st


def _fmt_signed(value: float, decimals: int = 0) -> str:
    if pd.isna(value):
        return ""
    if decimals == 0:
        rounded = int(round(float(value)))
        return f"+{rounded}" if rounded > 0 else f"{rounded}"
    number = float(value)
    return f"+{number:.{decimals}f}" if number > 0 else f"{number:.{decimals}f}"


def _to_float_array(values: np.ndarray) -> np.ndarray:
    array = np.asarray(values)
    if np.issubdtype(array.dtype, np.number):
        return array.astype(float)

    flat = pd.to_numeric(array.reshape(-1), errors="coerce")
    return np.asarray(flat, dtype=float).reshape(array.shape)


def _normalize_diverging(values: np.ndarray) -> np.ndarray:
    matrix = _to_float_array(values)
    normalized = np.zeros_like(matrix, dtype=float)

    valid_mask = ~np.isnan(matrix)
    positive_mask = valid_mask & (matrix > 0)
    negative_mask = valid_mask & (matrix < 0)

    if positive_mask.any():
        max_positive = float(np.nanmax(matrix[positive_mask]))
        if max_positive > 0:
            normalized[positive_mask] = matrix[positive_mask] / max_positive

    if negative_mask.any():
        min_negative = float(np.nanmin(matrix[negative_mask]))
        if min_negative < 0:
            normalized[negative_mask] = matrix[negative_mask] / abs(min_negative)

    normalized[~valid_mask] = np.nan
    return normalized


def _colorbar_ticktext(values: np.ndarray) -> list[str]:
    matrix = _to_float_array(values)
    raw_min = float(np.nanmin(matrix)) if not np.isnan(matrix).all() else 0.0
    raw_max = float(np.nanmax(matrix)) if not np.isnan(matrix).all() else 0.0
    min_label = _fmt_signed(min(raw_min, 0.0), 1)
    max_label = _fmt_signed(max(raw_max, 0.0), 1)
    return [min_label, "0.0", max_label]


def _build_calendar_matrix(
    daily_df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[str], pd.DataFrame]:
    if daily_df.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), [], pd.DataFrame()

    start = pd.to_datetime(daily_df["activity_date"].min())
    end = pd.to_datetime(daily_df["activity_date"].max())

    start_week = start - timedelta(days=int(start.weekday()))
    end_week = end + timedelta(days=int(6 - end.weekday()))

    all_days = pd.date_range(start=start_week, end=end_week, freq="D")
    date_df = pd.DataFrame({"activity_date": all_days.date})
    merged = date_df.merge(daily_df, on="activity_date", how="left").fillna(0)

    merged["date_ts"] = pd.to_datetime(merged["activity_date"])
    merged["weekday"] = merged["date_ts"].dt.weekday
    merged["week_start"] = merged["date_ts"] - pd.to_timedelta(merged["weekday"], unit="D")

    unique_week_starts = sorted(merged["week_start"].unique())
    week_map = {week_start: idx + 1 for idx, week_start in enumerate(unique_week_starts)}
    merged["week_seq"] = merged["week_start"].map(week_map).astype(int)

    pivot_pnl = (
        merged.pivot(index="week_seq", columns="weekday", values="realized_pnl")
        .reindex(columns=range(7), fill_value=0.0)
        .sort_index()
    )
    pivot_commission = (
        merged.pivot(index="week_seq", columns="weekday", values="commission_spent")
        .reindex(columns=range(7), fill_value=0.0)
        .sort_index()
    )

    weekly_summary = (
        merged.groupby("week_seq", as_index=True)
        .agg(
            weekly_pnl=("realized_pnl", "sum"),
            weekly_commission=("commission_spent", "sum"),
            weekly_options=("option_contracts_traded", "sum"),
        )
        .sort_index()
    )

    weekday_pnl = pivot_pnl.copy()
    weekday_commission = pivot_commission.copy()

    for weekend_day in (5, 6):
        weekday_pnl[weekend_day] = np.nan
        weekday_commission[weekend_day] = np.nan

    text_cells = weekday_pnl.copy().astype(object)
    for week in text_cells.index:
        for weekday in range(7):
            value = weekday_pnl.at[week, weekday]
            text_cells.at[week, weekday] = _fmt_signed(value, 1)

    week_labels = [f"Week {week}" for week in weekday_pnl.index]

    weekly_text = weekly_summary.copy().astype(object)
    weekly_text["label"] = weekly_text.apply(
        lambda row: f"{_fmt_signed(row['weekly_pnl'], 1)} Total Option: {int(round(row['weekly_options']))}",
        axis=1,
    )

    return weekday_pnl, weekday_commission, text_cells, week_labels, weekly_text


def render_calendar_tab(daily_df: pd.DataFrame) -> None:
    st.subheader("Daily Realized PnL Calendar")

    pnl_matrix, commission_matrix, text_matrix, week_labels, weekly_text = _build_calendar_matrix(daily_df)
    if pnl_matrix.empty:
        st.info("No data available.")
        return

    week_numbers = pnl_matrix.index.tolist()
    x_labels = [calendar.day_abbr[i] for i in range(7)]
    normalized_pnl = _normalize_diverging(pnl_matrix.values)
    normalized_weekly_pnl = _normalize_diverging(weekly_text[["weekly_pnl"]].values)
    daily_customdata = np.dstack((pnl_matrix.values, commission_matrix.values))
    weekly_customdata = np.dstack((weekly_text[["weekly_pnl"]].values, weekly_text[["weekly_commission"]].values))

    fig = make_subplots(
        rows=1,
        cols=2,
        shared_yaxes=True,
        horizontal_spacing=0.01,
        column_widths=[0.88, 0.12],
    )

    fig.add_trace(
        go.Heatmap(
            z=normalized_pnl,
            x=x_labels,
            y=week_numbers,
            text=text_matrix.values,
            customdata=daily_customdata,
            texttemplate="%{text}",
            colorscale="RdYlGn",
            zmin=-1,
            zmax=1,
            zmid=0,
            colorbar={
                "title": "Daily PnL",
                "tickmode": "array",
                "tickvals": [-1, 0, 1],
                "ticktext": _colorbar_ticktext(pnl_matrix.values),
                "len": 0.6,
                "x": 1.02,
            },
            hovertemplate="PnL=%{customdata[0]:+.1f}<br>Commission=%{customdata[1]:.1f}<extra></extra>",
            hoverongaps=False,
            xgap=2,
            ygap=2,
        ),
        row=1,
        col=1,
    )

    fig.add_trace(
        go.Heatmap(
            z=normalized_weekly_pnl,
            x=["Weekly Summary"],
            y=week_numbers,
            text=weekly_text[["label"]].values,
            customdata=weekly_customdata,
            texttemplate="%{text}",
            colorscale="RdYlGn",
            zmin=-1,
            zmax=1,
            zmid=0,
            colorbar={
                "title": "Weekly PnL",
                "tickmode": "array",
                "tickvals": [-1, 0, 1],
                "ticktext": _colorbar_ticktext(weekly_text[["weekly_pnl"]].values),
                "len": 0.6,
                "x": 1.1,
            },
            hovertemplate="Weekly PnL=%{customdata[0]:+.1f}<br>Weekly Commission=%{customdata[1]:.1f}<extra></extra>",
            xgap=2,
            ygap=2,
        ),
        row=1,
        col=2,
    )

    fig.update_layout(height=480, margin={"l": 20, "r": 20, "t": 20, "b": 20})
    fig.update_yaxes(
        autorange="reversed",
        tickmode="array",
        tickvals=week_numbers,
        ticktext=week_labels,
        row=1,
        col=1,
    )
    fig.update_yaxes(matches="y", row=1, col=2)

    st.plotly_chart(fig, use_container_width=True)

    st.dataframe(
        daily_df.sort_values("activity_date", ascending=False)
        [["activity_date", "realized_pnl", "commission_spent", "trade_count"]]
        .assign(
            realized_pnl=lambda df: df["realized_pnl"].map(lambda value: _fmt_signed(value, 1)),
            commission_spent=lambda df: df["commission_spent"].map(lambda value: f"{float(value):.1f}"),
        )
        .rename(
            columns={
                "activity_date": "Date",
                "realized_pnl": "Daily PnL",
                "commission_spent": "Commision",
                "trade_count": "Number of Trade",
            }
        )
        .reset_index(drop=True),
        use_container_width=True,
        hide_index=True,
    )
