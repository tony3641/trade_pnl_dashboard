# Trade PnL Dashboard

Streamlit dashboard for realized options-trading PnL from broker CSV exports.

## Quick Start

```powershell
pip install -r requirements.txt
streamlit run app.py
```

## Core Features

- Three views: **Cumulative PnL**, **Daily Calendar**, **Risk Measurement**.
- Shared global controls across pages:
  - **Initial Capital (USD)** (Cumulative + Risk)
  - **Window**: `1M`, `3M`, `YTD`, `1Y`, `All` (Cumulative + Risk)
- Cumulative curve:
  - Account equity curve + optional SPX comparison (`Off` / `On`)
  - Left y-axis in `$`, right y-axis in `% return`
  - 0% reference line, green/red return zones, enriched hover details
- Risk metrics include Sharpe, Sortino, cycle stats, recovery, commission drag, SPX alpha/beta/correlation, SPX period return, and return delta vs SPX.
- Context persistence on page switching (window, capital, SPX toggle, risk-free rate).

## Data Notes

- Input: upload CSV in sidebar or provide local file path.
- `Other Fee` is excluded from realized PnL totals.
- SPX data uses Yahoo Finance (`^GSPC`) via `yfinance`.
- SPX fetch is lazy (only when needed), shows a spinner, and uses a 15s timeout.
