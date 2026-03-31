# Progress Summary

## Session Highlights - E*Trade PDF Support, Merge Fix, Metric Corrections

### New: E*Trade / Morgan Stanley PDF Statement Parser
- Created `src/io/load_etrade_pdf.py` (~410 lines).
- Parses Morgan Stanley-format E*Trade monthly PDF statements.
- Extracts option trades from the **"CASH FLOW ACTIVITY BY DATE"** section via regex (no table grid lines in PDF).
  - `_OPT_PATTERN`: captures action, put/call, underlying, expiry, strike, quantity, price, net amount.
  - `_INTEREST_PATTERN` / `_DIVIDEND_PATTERN`: income rows.
  - Stock trades intentionally excluded (options-focused account).
- Builds OCC symbol (`SPXW  260202P06940000` format) via `_build_occ_symbol()` (also added to `src/domain/parse_option_symbol.py`).
- `EtradeBalance` dataclass stores:
  - `account_id`, `period_start`, `beginning_value`, `ending_value` (page 1)
  - `cash`, `stock_value` (page-3 asset-allocation table: `Cash $x` / `Equities $x`)
- Return type: `tuple[pd.DataFrame, Optional[EtradeBalance]]` — same pattern as QFX loader.
- Multiple monthly PDFs upload naturally; cross-month positions resolve via existing dedup + PnL engine.
- Requires `pdfplumber>=0.10.0` (added to `requirements.txt`).

### Multi-Account Initial Capital Aggregation
- `_load_input()` now returns `(DataFrame, list[_BalanceInfo])` — collects balance objects from ALL loaded files.
- Per-account initial capital logic:
  - **QFX (`InvBalance`)**: `initial = final_balance − sum(QFX-account net amounts only)`. Previously subtracted all accounts' net amounts — fixed.
  - **E*Trade PDF (`EtradeBalance`)**: `initial = beginning_value` of the earliest statement for that account (min `period_start`). Later statements for the same account are ignored for capital purposes.
- Combined initial capital = sum of all per-account capitals — displayed as "Combined initial capital" in sidebar when multiple sources are loaded.
- Sidebar now displays per-source breakdowns matching QFX style:
  - QFX: `Cash / Stock / Total / Est. initial capital`
  - E*Trade: `Cash / Stock / Initial capital`
- Auto-capital **always overwrites** session state on each render (not gated by `not in st.session_state`) so uploading or removing a file immediately re-evaluates the estimate.

### Merge Logic Rewrite — Intra-File Dedup Bug Fixed
- **Root cause**: `drop_duplicates()` was applied globally after concatenation. IBKR QFX contains legitimate repeat fills (same symbol, same qty, same net on the same day at the same price) which were incorrectly removed — causing up to $204 PnL loss in testing.
- **Fix** (`_merge_frames` in `app.py`): each frame is tagged with a `_src` index. Dedup only removes a row when its dedup key already appears in a **different** source file. Rows within the same file are always kept.
- Validated: IBKR QFX ($2,494) + E*Trade PDFs ($1,554) merged = $4,048 (exact sum, zero loss).

### UploadedFile Stream-Position Fix
- Added `f.seek(0)` before passing each Streamlit `UploadedFile` to any loader.
- Root cause: Streamlit reuses the same file-like object across rerenders; `.read()` after the first render returns empty bytes (stream already at EOF).
- Fix ensures every render fully re-reads all uploaded files, so adding/removing a file immediately reflects in the output.

### Sharpe / Sortino: Business-Day Fill
- **Root cause**: `_calc_metrics` in `tab_risk.py` received only trading days (days with at least one trade). Non-trading business days (zero PnL) were absent, inflating the mean-to-std ratio.
- **Fix**: before computing any statistics, the `view` DataFrame is left-joined against a full `pd.bdate_range` grid, filling missing days with `realized_pnl=0`, `commission_spent=0`. Sharpe dropped from 3.61 → 3.48 (YTD, all three files).
- SPX correlation alignment also benefits — benchmark returns are now matched against all business days, not just trading days.

### Calendar Hover: Exact Date Display
- `_build_calendar_matrix` in `tab_calendar.py` now returns a `pivot_date` matrix (6th return value) containing `YYYY-MM-DD` strings for every cell.
- Daily `customdata` has a 3rd layer: `[pnl, commission, date_str]`.
- Daily `hovertemplate` shows `%{customdata[2]}` as the first line (e.g. `2026-01-15`).
- Weekly `customdata` has 4 layers: `[weekly_pnl, weekly_commission, week_start_date, week_end_date]`.
- Weekly `hovertemplate` shows `%{customdata[2]} ~ %{customdata[3]}` date range.

### QFX Initial Capital Scoping Fix
- When IBKR QFX and E*Trade PDFs are loaded together the QFX formula was subtracting **all accounts'** net amounts rather than just the IBKR account's.
- Fixed: QFX-owned rows are identified by `account_id` starting with `"U"` (IBKR account ID prefix). Only those rows contribute to `acct_net`.

## Session Highlights - QFX Parser Implementation

### New: QFX/OFX File Format Support
- Created `src/io/load_qfx.py`: regex-based SGML parser for Interactive Brokers QFX investment statements.
- Parses all transaction types:
  - `<BUYOPT>` / `<SELLOPT>` → `"Buy"` / `"Sell"` with full option fields (underlying, expiry, strike, right).
  - `<INCOME>` (dividends) → `"Dividend"` (included in daily PnL).
  - `<INVBANKTRAN>` (fees/refunds) → `"Other Fee"` (excluded from daily PnL but counted in initial capital).
- Security lookup (`<SECLIST>`) maps CONID → OCC option symbol for seamless parsing into existing option-parsing pipeline.
- `<INVBAL>` extraction: final cash + equity for auto-calculating starting capital.

### Multi-File Upload & Deduplication
- Updated `app.py` file uploader to accept `.csv`, `.qfx`, and `.pdf` with `accept_multiple_files=True`.
- Merged frames are deduplicated on `(activity_date, account_id, symbol, quantity, net_amount)` — cross-file only.
- `source_row` is re-numbered after merge for clean enriched output.

### Initial Capital Auto-Inference
- Formula: `Initial Capital = Final Balance − Total Period P&L` (includes all cash flows: trades, dividends, fees, refunds).
- When a QFX file is loaded, sidebar displays:
  - Detected cash balance, stock value, total account value.
  - Estimated starting capital (computed from INVBAL − period sum of all net amounts).
- Initial capital pre-fills from this estimate but remains user-overridable.
- Fee/refund pairs cancel naturally in the sum; any net unrefunded fees are correctly deducted.

### Validation
- Full QFX test: 817 transactions parsed (401 Buy, 396 Sell, 18 Fees, 2 Dividends).
- 0DTE spread verification: Jan 2 day shows short legs (+$0.50 premium) + stop-loss buybacks (−$2–$4 fill) = **−$1,861.16 net loss** ✓
- Dividends: 2 entries (BIL: $117.79, $104.54) included in PnL ✓
- INVBAL: $5,601.49 cash + $39,379.40 stock = $44,980.89 ✓
- Auto-calculated initial capital: $42,486.38 ✓
- Three-file merge: IBKR $2,494 + E*Trade PDFs $1,554 = **$4,048 combined** ✓

## Previous Session Highlights (Cumulative PnL & Risk Tabs)
- Implemented account-vs-benchmark enhancements across curve and risk pages, plus lazy benchmark loading for better startup responsiveness.
- Added richer chart hover payloads for both account and SPX curves.
- Added SPX period performance delta in Risk metrics.
- Added tab-like view navigation with persistent page context and control state.
- Added dual-axis return visualization on the curve chart with 0% baseline and performance zones.
- Unified **global** window selection across Cumulative and Risk tabs.
- Unified **global** initial capital across Cumulative and Risk tabs.
- Fixed context recovery when switching tabs by using explicit `ctx_*` state as source-of-truth.

## App Flow
- `app.py` keeps sidebar upload (multi-file, accepts CSV / QFX / PDF) and local-path loading with validation and non-crashing error handling.
- Account filtering remains supported and now uses explicit widget key state (`selected_account`) to preserve context.
- Page navigation is tab-looking (`segmented_control` when available, fallback to horizontal radio), keyed as `active_view`.
- Only the selected view is rendered (branch rendering), preserving lazy-loading behavior.
- Session state is initialized for stable cross-tab recovery (`ctx_shared_initial_capital`, `ctx_shared_window`, page-specific context values).

## SPX Data Loading Behavior
- SPX data retrieval is lazy and no longer happens during startup.
- SPX fetch is triggered only when needed:
  - Risk page is active.
  - SPX comparison is enabled on the curve page.
- Front-screen loading feedback is shown via spinner while SPX data is loading.
- SPX download timeout is set to 15 seconds in `src/io/load_spx.py`.
- SPX fetch remains cached (`st.cache_data`) to reduce repeated API calls.

## UI: Return Curve (`src/ui/tab_curve.py`)
- Curve controls include:
  - Window (`1M`, `3M`, `YTD`, `1Y`, `All`) shared globally with Risk tab.
  - Initial capital input shared globally with Risk tab.
  - SPX comparison square-style toggle (`Off` / `On`) with persistent context.
- Account curve uses equity value (`initial capital + cumulative realized PnL`) with hover showing:
  - Cumulative return from period start to hovered day.
  - Account value on hovered day.
  - Daily gain on hovered day.
- SPX overlay (optional) is normalized to the same starting capital.
- Visual upgrades: right-side y-axis for return % scale, 0% reference line, green/red return zones.

## UI: Calendar (`src/ui/tab_calendar.py`)
- Daily heatmap hover shows exact date (`YYYY-MM-DD`) as the first line.
- Weekly summary hover shows date range (`start ~ end`).

## UI: Risk Measurement (`src/ui/tab_risk.py`)
- Sharpe/Sortino computed on full business-day series (zero-PnL days included).
- Existing risk metrics retained: Sharpe, Sortino, cycles, max gain/loss, commission drag, recovery, expectancy, SPX correlation/alpha/beta, SPX period return, return delta vs SPX.
- Risk controls recover from explicit context state; window and initial capital are shared globally.

## Data + Domain Notes
- `src/domain/pnl_engine.py` and existing ingest/parsing logic remain intact.
- `src/domain/parse_option_symbol.py` gained `build_occ_symbol()` for constructing OCC symbols from components.
- Realized PnL and inferred-expiry logic continue to drive all UI pages.

## Validation
- Sanity checks run during session with Python compile validation for modified modules (no syntax errors detected).

## Documentation
- `README.md` and `progress.md` updated to reflect all three sessions.


### New: QFX/OFX File Format Support
- Created `src/io/load_qfx.py`: regex-based SGML parser for Interactive Brokers QFX investment statements.
- Parses all transaction types:
  - `<BUYOPT>` / `<SELLOPT>` → `"Buy"` / `"Sell"` with full option fields (underlying, expiry, strike, right).
  - `<INCOME>` (dividends) → `"Dividend"` (included in daily PnL).
  - `<INVBANKTRAN>` (fees/refunds) → `"Other Fee"` (excluded from daily PnL but counted in initial capital).
- Security lookup (`<SECLIST>`) maps CONID → OCC option symbol for seamless parsing into existing option-parsing pipeline.
- `<INVBAL>` extraction: final cash + equity for auto-calculating starting capital.

### Multi-File Upload & Deduplication
- Updated `app.py` file uploader to accept both `.csv` and `.qfx` with `accept_multiple_files=True`.
- Merged frames are deduplicated on `(activity_date, account_id, symbol, quantity, net_amount)` to handle cross-format overlap.
- `source_row` is re-numbered after merge for clean enriched output.

### Initial Capital Auto-Inference
- Formula: `Initial Capital = Final Balance − Total Period P&L` (includes all cash flows: trades, dividends, fees, refunds).
- When a QFX file is loaded, sidebar displays:
  - Detected cash balance, stock value, total account value.
  - Estimated starting capital (computed from INVBAL − period sum of all net amounts).
- Initial capital pre-fills from this estimate but remains user-overridable.
- Fee/refund pairs cancel naturally in the sum; any net unrefunded fees are correctly deducted.

### Validation
- Full QFX test: 817 transactions parsed (401 Buy, 396 Sell, 18 Fees, 2 Dividends).
- 0DTE spread verification: Jan 2 day shows short legs (+$0.50 premium) + stop-loss buybacks (−$2–$4 fill) = **−$1,861.16 net loss** ✓
- Dividends: 2 entries (BIL: $117.79, $104.54) included in PnL ✓
- INVBAL: $5,601.49 cash + $39,379.40 stock = $44,980.89 ✓
- Auto-calculated initial capital: $42,486.38 ✓

## Previous Session Highlights (Cumulative PnL & Risk Tabs)
- Implemented account-vs-benchmark enhancements across curve and risk pages, plus lazy benchmark loading for better startup responsiveness.
- Added richer chart hover payloads for both account and SPX curves.
- Added SPX period performance delta in Risk metrics.
- Added tab-like view navigation with persistent page context and control state.
- Added dual-axis return visualization on the curve chart with 0% baseline and performance zones.
- Unified **global** window selection across Cumulative and Risk tabs.
- Unified **global** initial capital across Cumulative and Risk tabs.
- Fixed context recovery when switching tabs by using explicit `ctx_*` state as source-of-truth.

## App Flow
- `app.py` keeps sidebar CSV upload/local path loading with validation and non-crashing error handling.
- Account filtering remains supported and now uses explicit widget key state (`selected_account`) to preserve context.
- Page navigation is now tab-looking (`segmented_control` when available, fallback to horizontal radio), keyed as `active_view`.
- Only the selected view is rendered (branch rendering), preserving lazy-loading behavior.
- Session state is initialized for stable cross-tab recovery (`ctx_shared_initial_capital`, `ctx_shared_window`, page-specific context values).

## SPX Data Loading Behavior
- SPX data retrieval is lazy and no longer happens during startup.
- SPX fetch is triggered only when needed:
  - Risk page is active.
  - SPX comparison is enabled on the curve page.
- Front-screen loading feedback is shown via spinner while SPX data is loading.
- SPX download timeout is set to 15 seconds in `src/io/load_spx.py`.
- SPX fetch remains cached (`st.cache_data`) to reduce repeated API calls.

## UI: Return Curve (`src/ui/tab_curve.py`)
- Curve controls include:
  - Window (`1M`, `3M`, `YTD`, `1Y`, `All`) shared globally with Risk tab.
  - Initial capital input shared globally with Risk tab.
  - SPX comparison square-style toggle (`Off` / `On`) with persistent context.
- Account curve uses equity value (`initial capital + cumulative realized PnL`) with hover showing:
  - Cumulative return from period start to hovered day.
  - Account value on hovered day.
  - Daily gain on hovered day.
- SPX overlay (optional) is normalized to the same starting capital and hover shows:
  - SPX close (1 decimal).
  - Day change %.
  - Cumulative return since period start.
- Visual upgrades added:
  - Right-side y-axis for return % scale.
  - Horizontal 0% return reference line.
  - Light green zone above 0% and light red zone below 0%.
  - Explicit high-contrast colors between account and SPX curves.
- Inferred-expiry diamond markers use deep blue for better contrast against the account line.
- Inferred-expiry markers remain on the chart with detailed hover metadata.

## UI: Risk Measurement (`src/ui/tab_risk.py`)
- Existing risk metrics retained (Sharpe, Sortino, cycles, max gain/loss, commission drag, recovery, expectancy, SPX correlation/alpha/beta).
- Added benchmark period metrics:
  - SPX Return in Period.
  - Return Delta vs SPX (`account period return - SPX period return`).
- Risk controls now recover from explicit context state:
  - `Risk-Free Rate` remains tab-specific and persistent.
  - `Window` is shared globally with Cumulative tab.
  - `Initial Capital` is shared globally with Cumulative tab.

## Data + Domain Notes
- `src/domain/pnl_engine.py` and existing ingest/parsing logic remain intact.
- Realized PnL and inferred-expiry logic continue to drive all UI pages.

## Validation
- Sanity checks run during session with Python compile validation for modified modules (no syntax errors detected).

## Documentation
- `README.md` has been aligned and condensed to a concise quick-start + current behavior summary.
