# Intraday paper candidate: ema_pullback_v1

Research candidate, not a validated profitable strategy. Long-only paper entries;
no Binance order placement. Default timeframe is 15m; PAPER_TIMEFRAME can override it.

- At least 100 completed candles; exclude the newest potentially open candle.
- EMA9 > EMA21 > EMA50, with EMA50 rising.
- Previous candle touches EMA9; signal closes above EMA9 and previous close.
- Simple rolling RSI14 between 45 and 68.
- Volume at least 1.15 times the preceding 20 candles' average.
- Close above EMA21 but no more than 1.5 ATR14 away (simple-average true range).
- Reject execution if current price differs from signal close by over 0.5 ATR14.
- One entry per symbol per signal candle. Existing allocation limits apply.
- Existing configured TP, stop, SL+, time stop and loss cooldown remain.
- New-strategy positions also exit on completed-candle EMA9 below EMA21.
- Legacy positions keep legacy signal exits. History records strategy version.

Stops are polling-based simulations, not exchange-resident orders. New positions
use net_costs_v1: 0.1% fee and 0.05% adverse slippage per side (assumptions, not
verified account fee rates). Allocation includes entry fee; open equity estimates
net liquidation proceeds. Legacy positions/history retain original accounting.

The EMA backtest replays the actual paper engine with an injected clock and a
public-data-only client; no journal reads/writes. It observes next candle OPEN,
never its future high/low/close. It shares stops, trailing, time stop and cooldown,
but samples once per candle, not the worker's faster polling. This is not tick
execution equivalence. Open positions remain marked, not synthetic closed wins.
Replay freezes the active default risk profile shown in its output; live env
overrides can differ. Default allocation is $50, not legacy 25% of capital.

run_intraday_validation.py runs a chronological 70/30 split with frozen rules and
a double-cost holdout. Initial maximum 1000 bars (~10 days at 15m) is only a smoke
test, not adequate validation. It does not optimize parameters. A holdout viewed
here must not be reused as untouched evidence after tuning.

Provisional research plan (not a statistical guarantee): 6-12 months historical
data across different regimes, then 8-12 weeks forward paper AND at least 200
closed net-cost trades. Extend if signals are sparse or highly correlated. Assess
net expectancy, drawdown, loss streaks, stability by period and cost stress, not
win rate alone. No automatic live promotion or Gemini changes to frozen rules.
Long-history pagination is now supported for 15m through historical_data.py,
using the public Binance market-data endpoint without application credentials.
Intervals are cached with SHA256 provenance; missing/duplicate/non-finite bars
are rejected. Portfolio-wide replay remains future work; separate-symbol results
must not be summed as a shared portfolio.

## Accelerated candidate research

`run_candidate_research.py --days 180` downloads BTC/ETH/SOL, freezes three exit
variants before execution, selects on the first 60% only, and evaluates the winner
on the next 20% (normal and doubled costs) and final 20%. A plan and per-symbol
results are saved under data/research/candidates-<timestamp>. Every segment starts
flat with prior candles available only for indicator warmup. No auto-promotion.
Recent history may have been inspected in earlier experiments: this chronological
holdout is not a substitute for untouched future paper data. Do not keep tuning
against the same reported holdout. Gates are heuristics, not statistical proof.

Fast replay skips unused whale calculations and precomputes technical features,
including an exact EMA seed correction for the original rolling 200-bar window.
The entry/exit/accounting state machine is still CryptoPaperTrader. The original
replay remains available with fast=False as a reference; feature and transaction
equivalence tests and a 300-bar per-dataset benchmark guard the optimization.
Dashboard EMA/15m now requests 17,280 bars; other modes remain short-history.

Offline verification (PowerShell, no .env loading):

```powershell
$env:PYTHON_DOTENV_DISABLED = '1'
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```
