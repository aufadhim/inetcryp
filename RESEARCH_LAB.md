# Autonomous Research Lab

The Windows supervisor runs `research_lab_worker.py` continuously. It uses public
market endpoints, a SQLite WAL registry in `data/lab`, and an exclusive process
lock. The API `/api/research/status` and dashboard display progress.

## Seven components

1. Bounded generator: 12 frozen candidates from EMA pullback, channel breakout,
   RSI reversion, VWAP reclaim, flow breakout, compression. Daily Gemini advice
   may supply at most two validated parameter proposals for the NEXT weekly epoch.
   Responses are parsed as JSON; model output is never executed as code.
2. Data/features: public 15-minute Binance history, checksums, daily exchange catalog
   including observed status changes, and liquid universe of up to eight symbols
   including nongainers. Timestamped CoinGecko metadata (hourly), funding and open
   interest observations are archived. Optional COINGECKO_DEMO_API_KEY is read only
   from the worker's process environment; this worker never loads dotenv.
   DEXScreener observations use chain/contract identity and conservative market
   risk filters. GoPlus Solana/EVM checks are collected for up to two new profiles
   per pass, cached for six hours; unknown, unavailable or clean vendor flags do
   not establish sellability. No API keys in datasets or registry.
3. Backtest v2 freezes candidates before the next weekly endpoint, using a
   180-day window: first 108 days development and following 36 days validation.
   Final holdout starts after candidate freeze and after every consumed holdout,
   including previous versions. Historical development/validation runs immediately;
   promotion waits for fresh holdout completion. Holdouts no longer overlap.
   Candidates failing validation, double costs or latency stress are rejected early
   without consuming holdout. Gemini evaluates that rejection for the next epoch.
   Three chronological validation folds, cross-coin holdout, doubled costs and
   one-bar latency stress are required. Hard cap of 12 trials per weekly epoch.
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
   candle coverage and drawdown <=5%. A challenger needs a positive 2.5th-percentile
   bound for excess daily returns in a five-day block bootstrap
   over at least 30 common observed days to replace an existing champion.
   Absolute lifetime equity is not used for replacement. No live order methods.

## Execution and limitations

Backtest and forward paper use the same `advance` function: prior closed candle
signal, next open execution, 0.1% fee, 0.05% base slippage and half of a modeled
0.05% spread per side, plus a participation-based impact proxy. Allocation cannot
exceed 0.1% of prior candle quote volume. Real execution can still be worse.
Stop takes priority
if both stop and target are touched; gap stops execute at observed opening price.
Paper results are recorded after candles complete, with assumed fills rather than
real orders. Repeated completed candles are ignored.

Drawdown uses observed candle-close net liquidation values; actual intrabar drawdown
may be worse. There is no queue simulation, calibrated market impact model, or real fill proof.
Current universe selection still has survivorship/selection bias; daily listing
archives reduce future gaps but do not reconstruct unavailable delisted history.
The 30-day prospective gate is mandatory. Nonoverlapping holdouts may have small
samples; a failed sample gate never lowers thresholds automatically.

Flow is an OHLCV proxy, not identified whale ownership. Fundamental, unlock, holder,
historical orderbook, funding and sentiment features require point-in-time archives
before historical testing. An as-of join rejects any observation received after
the decision, regardless of the provider's earlier event time. DEX discoveries
remain observation-only until historical
coverage, liquidity, sellability and cost models are available. FluxScout/Dawn data
APIs have not been verified; no scraper or undocumented API integration is claimed.

Run tests: `python -m unittest discover -s tests -q`.
Run a bounded operational pass: `python research_lab_worker.py --once`.
Runtime output is ignored by Git; do not publish `data/lab`.
