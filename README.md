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
| `.csv` | IB | Perf & Reports -> Transaction History -> CSV |
| `.qfx` | IB | Perf & Reports -> 3rd Party Reports -> Quicken Web Connect |
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
- `generate_monthly_report` fetches fresh SPX/VIX from Yahoo Finance **by default** (`offline=False`) and merges it into `reports/data/spx_closes.csv` / `vix_closes.csv`, so the offline fallback always has current benchmark data. Pass `offline=True` to skip the network fetch.
- Cross-month option positions (opened in one E*Trade statement, closed in another) are handled naturally by the merge layer.

## MCP Server

An **MCP (Model Context Protocol) server** is included that exposes the same analytical engine as tools an AI agent can call. This lets an agent load trade files, compute PnL, calculate risk metrics, and analyze contracts — all through structured JSON responses.

### Quick Start

```powershell
pip install -r mcp_server/requirements.txt
python -m mcp_server.server
```

Or with the FastMCP CLI:

```powershell
fastmcp run mcp_server.server
```

### Available Tools

| Tool | Description |
|------|-------------|
| `get_transaction_summary` | Load files, return row counts, date range, accounts, balances |
| `compute_daily_pnl` | Full PnL pipeline — daily series, cumulative, top contracts |
| `compute_risk_metrics` | Sharpe, Sortino, drawdown, Net EV, SPX/VIX benchmarks, VIX regimes |
| `get_calendar_data` | Weekly calendar heatmap matrix (week × weekday PnL grid) |
| `get_market_data` | Fetch SPX or VIX daily OHLC/returns from Yahoo Finance |
| `parse_occ_symbol` | Decompose an OCC option symbol into components |
| `build_occ_symbol` | Assemble a padded OCC option symbol from components |
| `get_contract_details` | All trades and PnL for a specific option contract |
| `generate_monthly_report` | Full monthly report — performance + risk + strategy edge analysis (HTML + JSON) |

### File Input

All file-consuming tools accept two parameters:

- **`paths`** — list of local file paths (`["data/trades.csv", "data/ibkr.qfx"]`)
- **`file_contents`** — list of dicts with `name` (filename with extension), plus `data_text` (raw text for CSV/QFX) or `data_base64` (base64-encoded bytes for PDFs)

Since every tool call is **stateless**, switching files means just calling the tool again with different paths — no explicit cancel or reset needed.

### Example

```
# Agent calls:
get_transaction_summary(paths=["january.csv", "february.qfx"])

# Returns summary, then agent drills in:
compute_daily_pnl(paths=["january.csv", "february.qfx"], initial_capital=50000)

# Risk analysis with SPX benchmarking:
compute_risk_metrics(paths=["january.csv", "february.qfx"], window="1M", with_spx=True)
```

## Monthly Report (HTML)

Beyond the live dashboard, the repo ships a standalone report generator that produces a **self-contained HTML report** (inline SVG charts, light/dark themes) for any month. It combines the monthly performance report (daily PnL, weekly breakdown, risk-adjusted metrics at the risk-free rate, VIX regimes, SPX benchmark) with a strategy-level edge & risk analysis: bull-put-credit-spread structure, per-leg win rates, stops & re-entry, bootstrap significance, spread-capped tail stress, Monte Carlo, and Kelly. Takeaways adapt to whether the month was a gain or a loss.

### CLI

```powershell
python reports/generate_report.py --monthly <month.qfx> --label "July 2026"
```

Options: `--month 2026-06` (filter to one calendar month when the file spans several), `--ytd <ytd.qfx>` (prior-month / YTD file for cross-month context and pooled significance), `--rf 0.04` (annual risk-free rate, decimal), `--offline` (use cached market data, no network fetch), `--out <path>` (default `reports/output/report.html`).

### As an MCP tool

`generate_monthly_report` accepts the same `paths` / `file_contents` convention and returns the full report as structured JSON plus `html_path` (and the full HTML string when `include_html=True`). The generated report is written to `reports/output/`.

## File Structure

```
app.py                        # Streamlit entry point
requirements.txt
src/
  domain/
    parse_option_symbol.py    # OCC symbol parse + build
    pnl_engine.py             # Realized PnL engine
    risk_metrics.py           # Pure risk-metric computations (shared by UI + MCP)
    merge.py                  # Cross-file merge + dedup (shared by UI + MCP)
  io/
    load_csv.py               # IB CSV parser
    load_qfx.py               # IBKR QFX/OFX parser
    load_etrade_pdf.py        # E*Trade PDF parser
    load_spx.py               # SPX daily data via yfinance
    load_vix.py               # VIX daily OHLC via yfinance
  ui/
    tab_curve.py              # Cumulative PnL tab
    tab_calendar.py           # Daily calendar tab
    tab_risk.py               # Risk measurement tab
mcp_server/
    server.py                 # FastMCP app with 9 tools
    adapter.py                # DataFrame → JSON serializers
    requirements.txt
    tests/
        test_adapter.py       # Serializer unit tests
        test_server_tools.py  # Tool integration tests
reports/
    generate_report.py        # Monthly HTML report builder (CLI + MCP tool)
    strategy_analysis.py      # Spread reconstruction, edge/tail stats, market data
    data/
        spx_closes.csv        # SPX daily cache (auto-refreshed on report run)
        vix_closes.csv        # VIX daily cache (auto-refreshed on report run)
    output/                   # Generated HTML reports
```
