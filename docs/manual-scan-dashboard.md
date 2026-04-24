# BuzzFlow System Guide (Quant Programmer Documentation)

## 1) Purpose and Operating Model

BuzzFlow is a rule-based discretionary-assist stack for Indian equities that combines:

- **pre-trade selection** (scanner),
- **position lifecycle supervision** (monitor),
- **capital reallocation hints** (replacement),
- **operator UI** (dashboard),
- **automation orchestration** (GitHub Actions).

The system is intentionally hybrid:

- **Scheduled batch mode** for daily repeatability.
- **Manual intraday mode** for event-driven rescans and operator control.

It is not designed as a fully autonomous order-execution engine. It generates ranked trade candidates, manages watchlist state, and emits actionable alerts; execution remains user-driven.

## 2) High-Level Architecture

### Core modules

- `scanner_v2.py`
  - Universe selection
  - Two-phase filtering and scoring
  - Scan result persistence
  - Optional watchlist seeding + Telegram summary
- `monitoring_engine.py` + `monitor.py`
  - Active position reassessment
  - Exit/opportunity score updates
  - State transitions (STRONG/NEUTRAL/WEAK)
  - Stop/target/exit alerts
- `replacement_engine.py`
  - Identifies WEAK positions and better alternatives from fresh scan set
- `database.py`
  - SQLite schema and all persistence primitives
  - Dedup safety for active symbols and latest scan views
- `dashboard/app.py`
  - Flask API layer + static frontend serving
- `dashboard/ui/*`
  - React dashboard (watchlist, scans, performance)
  - Manual scan controls and refresh actions
- `.github/workflows/buzzflow.yml`
  - Time-based scheduling and environment bootstrap for cloud automation

### Data stores

- `watchlist`: current and historical positions (status-based lifecycle)
- `scan_results`: scan snapshots over time
- `trades_log`: realized exits and PnL
- `replacement_log`: replacement suggestions and score deltas

## 3) Signal and Score Pipeline

## 3.1 Scanner mechanics (`ScannerV2`)

### Universe model

Universe can be either:

- broad (`all` / extended universe), or
- sector bucket (`banking`, `nifty_it`, `pharma`, etc.).

### Two-phase execution

1. **Phase-1 quick filter** (high throughput):
   - RSI band sanity
   - trend relative to MA
   - basic volume participation
   - discards structurally weak symbols early
2. **Phase-2 full analysis** (on top candidates):
   - technical feature extraction
   - news sentiment aggregation
   - delivery/accumulation proxy features
   - entry score + recommendation
   - SL/target/R:R constraints

This design controls latency while maintaining feature depth on likely candidates.

### Output semantics

For each retained symbol:

- entry zone (`entry_zone_low` / `entry_zone_high`)
- breakout and pullback levels
- stop loss and target
- entry score, opportunity score, confidence
- recommendation (`STRONG_BUY`, `BUY`, `WATCH`, `SKIP`)

These are persisted in `scan_results` and displayed in the dashboard.

## 3.2 Monitor mechanics (`MonitoringEngine`)

For each active watchlist symbol:

- pull fresh price/technical context
- compute `exit_score` and updated `opportunity_score`
- classify trade state and suggested action
- apply lifecycle logic:
  - stop-loss hit -> close and alert
  - target hit -> close and alert
  - weak state -> caution/exit alert path
  - strong state -> trailing stop progression

The monitor writes state back to `watchlist` and logs realized exits to `trades_log`.

## 3.3 Replacement mechanics (`ReplacementEngine`)

Replacement runs only when:

- an active position is tagged `WEAK`, and
- a non-active candidate materially dominates score thresholds.

It logs proposals in `replacement_log` and optionally sends Telegram recommendation messages.

## 4) User Workflow (Operator View)

## 4.1 Daily workflow (recommended)

1. Morning scheduled scan populates candidate set.
2. User reviews `Scan Results` tab and promotes selected setups to watchlist.
3. Midday monitor updates state and sends only action-worthy alerts.
4. Replacement run checks for superior alternatives if current holdings degrade.
5. Afternoon monitor reassesses final intraday state.

## 4.2 Intraday manual workflow

Use dashboard manual scan controls when regime/sector dynamics change:

- choose category (`all`, `banking`, `metals`, etc.),
- set `min_score` and `max_results`,
- optionally enable:
  - auto-add to watchlist
  - Telegram summary push,
- run scan and inspect refreshed table immediately.

This avoids waiting for the next scheduler slot while preserving identical strategy logic.

## 5) Dashboard API and UI Contracts

### Core read APIs

- `GET /api/market`
- `GET /api/watchlist`
- `GET /api/scans?limit=...`
- `GET /api/performance`
- `GET /api/trades`

### Action APIs

- `POST /api/watchlist`
- `PATCH /api/watchlist/<symbol>/status`
- `POST /api/watchlist/<symbol>/close`
- `POST /api/monitor`
- `POST /api/replacement`

### Manual scan APIs

- `GET /api/scans/categories`
  - returns UI dropdown options aligned with scanner universes
- `POST /api/scans/run`
  - synchronous manual scan trigger
  - request:

```json
{
  "index": "all",
  "min_score": 65,
  "max_results": 20,
  "auto_watchlist": false,
  "alert": false
}
```

  - response includes run metadata and top symbols:

```json
{
  "status": "ok",
  "index": "all",
  "min_score": 65.0,
  "max_results": 20,
  "signals_found": 5,
  "top_symbols": ["SBIN.NS", "ICICIBANK.NS"]
}
```

## 6) Scheduling and Automation

Automation is orchestrated in `.github/workflows/buzzflow.yml` with weekday schedules:

- Morning scan
- Midday monitor
- Replacement scan
- Afternoon monitor

This automation remains authoritative for daily consistency. Manual dashboard scans are an additive override path.

## 7) Data Integrity and Dedup Guarantees

Implemented safeguards:

- active watchlist insertion is idempotent by symbol (update-in-place for active rows),
- watchlist reads suppress duplicate active symbols,
- scan retrieval returns latest row per symbol for UI consumption.

Net effect: repeated scans/refreshes do not pollute active state with symbol duplicates.

## 8) Alerting and Logging Behavior

- Telegram alerts are sent via `AlertEngine` when enabled and configured.
- Console logging is Windows-safe (ASCII-safe logging path for problematic characters).
- Alerting policy is selective in monitor path to reduce notification noise.

## 9) Failure Modes and Interpretation

### “Manual scan succeeded but 0 signals”

This is usually model-state outcome, not runtime failure. Common causes:

- threshold too strict for current regime (`min_score` high),
- selected category currently weak,
- risk/reward constraints rejecting candidates.

Action: lower `min_score`, widen universe, inspect market regime banner.

### “Dashboard loads but no data”

Verify backend process and API health:

- `GET /api/market`
- `GET /api/scans`
- `GET /api/watchlist`

If these return `200`, issue is typically browser cache/UI state, not backend compute.

## 10) Local Runbook

### Start backend + dashboard API

```bash
python dashboard/app.py
```

Open `http://127.0.0.1:5000`.

### Run scanner manually (CLI)

```bash
python scanner_v2.py --index all --min-score 65 --max-results 10 --auto-watchlist --alert
```

### Run monitor manually (CLI)

```bash
python monitor.py
```

### Run replacement only (CLI)

```bash
python monitor.py --replacement
```

## 11) Practical Quant Usage Patterns

- Use `all` with moderate threshold to detect broad leadership rotation.
- Use sector-specific rescans after macro/event catalysts.
- Keep watchlist compact and score-ranked; avoid over-allocation from marginal signals.
- Treat replacement suggestions as opportunity-cost optimization, not forced turnover.
- Track realized `trades_log` and recalibrate threshold policy empirically.

## 12) Current Scope and Next Enhancements

Current system is production-usable for assisted swing workflow. Natural next upgrades:

- asynchronous job queue for manual scans (non-blocking UI),
- richer scan diagnostics (phase pass/fail counters by reason),
- portfolio-level risk constraints (sector caps, correlation caps),
- experiment ledger for threshold/regime policy backtesting.

