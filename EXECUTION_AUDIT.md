# Execution audit, 21 October 2026

Fee verification uses only signed GET /api/v3/account/commission through the
existing runtime client. The six-hour snapshot contains mode, symbol-level
standard + tax + special maker/taker and buyer/seller rates, never credentials,
signatures, balances or raw errors. BNB enablement is not treated as proof of
sufficient BNB. A scoped client copy queries production commission using GET
only, even when the trading client is in testnet; the original client mode is
never changed and the snapshot exposes both configured mode and read-only scope.
Unavailable verification keeps simulation fees marked as assumptions.
Current account fees are not retroactively substituted into historical results.

Shared accounting: execution_costs.py defines the round-trip cost budget and
net break-even exit. New daily and weekly plans freeze cost_guard=true so both
backtest and observed paper reject targets below five times estimated immediate
round-trip cost. Frozen legacy experiments keep their prior policy and results.
Legacy paper SL+ now computes its lock from quantity, capital, exit fee and
slippage rather than simply entry price +0.1%. Gaps can still cause net losses.

Parity regression tests cover equal flat-market fills/fees and insufficient
target-cost rejection. Both models use $50 positions, five-position caps, daily
loss protection, closed-candle signals, all-or-none sizing and net liquidation.
The models are intentionally not identical: OHLC backtests approximate
spread/impact and intrabar stops conservatively, while forward paper uses actual
observed bid/ask depth and rejects stale/late signals. Candle data cannot prove
intrabar execution or guarantee stop fills. Observed forward tests remain required.

SL+ is present only in legacy paper, not a research Candidate parameter. Enabling
SL+ in the lab would change the tested strategy and requires a separately frozen
hypothesis and new out-of-sample evaluation; it is not silently retrofitted.
