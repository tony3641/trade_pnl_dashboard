# Progress Summary

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
