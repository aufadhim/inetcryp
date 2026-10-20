# Autonomous Research Lab

The Windows supervisor runs `research_lab_worker.py` continuously. It uses public
market endpoints, a SQLite WAL registry in `data/lab`, and an exclusive process
lock. The API `/api/research/status` and dashboard display progress.

## Seven components

1. Bounded generator: 12 frozen candidates from EMA pullback, channel breakout,
   RSI reversion, VWAP reclaim, flow breakout, compression. Daily Gemini advice
   may supply at most two validated parameter proposals for the NEXT weekly epoch.
   Responses are parsed as JSON; model output is never executed as code.
2. Data/features: 180 days of public 15-minute Binance history, checksums,
   current dynamic liquid universe (up to eight symbols). DEXScreener observations
   are archived with chain/contract identity. No API keys in datasets or registry.
3. Backtest: 108 days development, 36 days validation, 36 days final holdout.
   Select once on development. Validate the winner on three chronological folds,
   cross-coin holdout, and doubled costs. Hard cap of 12 trials per weekly epoch.
4. Gate: validation/stress/holdout each positive expectancy, PF >=1.3, >=30 trades,
   drawdown <=5%; two positive folds and three positive individual symbols.
5. Tournament: up to three isolated $1,000 paper accounts, $50 maximum per position,
   five positions, daily realized loss gate, drawdown pause. Existing portfolio and
   quarantine are not overwritten. Enrollment starts with observation, never a
   backdated paper fill. Missing data beyond catch-up window pauses that account.
6. Gemini researcher: the normal main worker supplies its existing Gemini environment.
   One cached advice per UTC day, bounded JSON parameters, audit records. If unavailable,
   deterministic research continues and status reports the missing adviser.
7. Champion/challenger: automatic PAPER champion only after >=30 days, >=200 trades,
   PF >=1.3, positive expectancy/return, three profitable symbols, >=95% observed
   candle coverage and drawdown <=5%. A challenger needs $5
   higher cumulative net PnL to replace an existing champion. No live order methods.

## Execution and limitations

Backtest and forward paper use the same `advance` function: prior closed candle
signal, next open execution, 0.1% fee and 0.05% slippage per side. Stop takes priority
if both stop and target are touched; gap stops execute at observed opening price.
Paper results are recorded after candles complete, with assumed fills rather than
real orders. Repeated completed candles are ignored.

Drawdown uses observed candle-close net liquidation values; actual intrabar drawdown
may be worse. There is no queue simulation, market impact model, or real fill proof.
Current universe selection has survivorship/selection bias. Weekly holdouts overlap;
they are not independent evidence. The 30-day prospective gate is mandatory.

Flow is an OHLCV proxy, not identified whale ownership. Fundamental, unlock, holder,
historical orderbook, funding and sentiment features require point-in-time archives
before historical testing. DEX discoveries remain observation-only until historical
coverage, liquidity, sellability and cost models are available. FluxScout/Dawn data
APIs have not been verified; no scraper or undocumented API integration is claimed.

Run tests: `python -m unittest discover -s tests -q`.
Run a bounded operational pass: `python research_lab_worker.py --once`.
Runtime output is ignored by Git; do not publish `data/lab`.
