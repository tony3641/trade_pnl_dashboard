# Trade PnL Dashboard

Streamlit dashboard for realized options-trading PnL from multiple broker statement formats.

## Quick Start

```powershell
pip install -r requirements.txt
streamlit run app.py
```

## Supported Data Sources

| Format | Broker | Notes |
|--------|--------|-------|
| `.csv` | Schwab | Transaction history export |
| `.qfx` | Interactive Brokers | OFX/QFX investment statement |
| `.pdf` | E*Trade (Morgan Stanley) | Monthly client statement |

Upload one or multiple files in the sidebar, or provide a local file path. All sources are merged into a single trade ledger.

### Multi-file Merge Rules
- Deduplication uses `(activity_date, account_id, symbol, quantity, net_amount)` as key.
- Rows within the same file are **never** deduplicated (preserves legitimate repeat fills).
- Only rows in a later file that duplicate a key from an earlier file are dropped.

### Initial Capital Auto-Inference
- **IBKR QFX**: `Final balance − sum(IBKR account net amounts)` using `<INVBAL>`.
- **E*Trade PDF**: `Beginning Total Value` from the earliest monthly statement for that account.
- When multiple accounts are loaded their capitals are summed and shown as "Combined initial capital".
- The inferred capital pre-fills the input but is always user-overridable.

## Core Features

### Cumulative PnL Tab
- Account equity curve (`initial capital + cumulative realized PnL`).
- Optional SPX overlay normalized to same starting capital.
- Left y-axis in `$`, right y-axis in `% return`.
- 0% reference line, green/red return zones, enriched hover (value, daily gain, cumulative return).
- Inferred-expiry markers with hover metadata.
- Window: `1M` `3M` `YTD` `1Y` `All` — shared globally with Risk tab.

### Daily Calendar Tab
- Monthly heatmap of daily realized PnL (Mon–Sun grid).
- Hover shows **exact date** (`YYYY-MM-DD`), PnL, and commission.
- Weekly summary column with date-range hover.

### Risk Measurement Tab
- Sharpe and Sortino computed on **all business days** in window (zero-return days filled in) — not just trading days.
- Period return, positive/negative cycles, max single-day gain/loss.
- Commission drag (% of gross gains).
- Max drawdown recovery time (resolved and ongoing).
- Net EV (day-level expectancy: P(win)×AvgWin − P(loss)×AvgLoss).
- SPX: correlation, alpha (annualized), beta, SPX period return, return delta vs SPX.
- Shared global controls: Initial Capital, Window, Risk-Free Rate.

## Sidebar Displays

**IBKR QFX Account Balance**
```
Cash:  $x,xxx.xx
Stock: $xx,xxx.xx
Total: $xx,xxx.xx
Est. initial capital: $xx,xxx.xx
```

**E*Trade PDF Account**
```
Cash:  $xx,xxx.xx
Stock: $xx,xxx.xx
Initial capital: $xx,xxx.xx
```

## Data Notes

- `Other Fee` transactions are excluded from realized PnL totals (included in initial capital back-calculation).
- Stock trades in E*Trade PDFs are intentionally ignored (options-focused account).
- SPX data uses Yahoo Finance (`^GSPC`) via `yfinance` — lazy load, 15 s timeout, cached for 6 h.
- Cross-month option positions (opened in one E*Trade statement, closed in another) are handled naturally by the merge layer.

## File Structure

```
app.py                        # Streamlit entry point
requirements.txt
src/
  domain/
    parse_option_symbol.py    # OCC symbol parse + build
    pnl_engine.py             # Realized PnL engine
  io/
    load_csv.py               # Schwab CSV parser
    load_qfx.py               # IBKR QFX/OFX parser
    load_etrade_pdf.py        # E*Trade PDF parser
    load_spx.py               # SPX daily data via yfinance
  ui/
    tab_curve.py              # Cumulative PnL tab
    tab_calendar.py           # Daily calendar tab
    tab_risk.py               # Risk measurement tab
```
