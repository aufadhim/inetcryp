# Research v3 and observed forward paper

## Diagnosis and hypotheses

Backtest trades carry entry regime, volatility bucket, UTC entry hour, opening
gap, exit reason, gross price PnL and modeled net PnL. Summaries are grouped by
coin, regime, volatility, hour and exit reason. A cost-flipped winner is a trade
with positive price PnL and nonpositive net PnL. Missing legacy cost/regime fields
remain unknown. Segments under 20 trades are flagged as weak evidence. These
summaries describe associations rather than identify causes.

Regimes use only trailing candles: ATR percentage, directional efficiency and
EMA alignment. RSI reversion is limited to range conditions; trend strategies
require uptrend; compression accepts range/uptrend. Extreme volatility is filtered.
The v3 identifier separates these rules from v2. Twelve trials are frozen per
release/epoch. Existing unseen holdouts remain protected by the global watermark.

## Baselines

Validation and holdout each compare with cash, EMA9/21 crossover with the same
paper risk controls, and a capped passive buy-and-hold portfolio. All start with
$1,000, maximum $50 per position and $250 gross exposure. Passive exposure is
limited to five alphabetically selected available symbols; this convention is
frozen rather than selected on returns. It does not match realized risk exactly.

The candidate must beat cash and the simple EMA rule. If it trails passive return,
it needs at least 20% lower drawdown and better net-PnL/drawdown ratio. These
comparisons complement, rather than replace, sample-size, cost, regime and holdout
gates. Outcomes appear in the Research Lab dashboard and loss-diagnosis.json.

## Observed execution

Historical replay uses conservative OHLCV execution assumptions. Forward paper now
uses actually received public depth snapshots with receipt timestamps and request
latency. Entry consumes ask depth, exit consumes bid depth and both include fees.
Insufficient depth is rejected; no historical opening fill is reconstructed.

Quotes older than five seconds, requests slower than five seconds, spread above
0.2%, unsorted/invalid depth, entry depth impact above 0.1%, and signals more than
90 seconds after candle close are rejected. Monitoring runs every 30 seconds.
Stop/target/time exits use the executable bid depth observed at that polling time;
an unobserved intrabar touch never generates a hypothetical successful fill.
Missing quotes retain the last observed position valuation. Every open/close and
rejection is audited. Old candle-simulated accounts cannot pass the observed-paper
promotion gate. Public snapshots are still paper evidence: a real order might
receive a different fill, and polling can miss a stop or target.

## Process isolation

The Windows supervisor manages separate research, monitor and collector workers:

- `python research_lab_worker.py --role research`: historical work and diagnoses.
- `python research_lab_worker.py --role monitor`: sole writer of forward accounts.
- `python research_lab_worker.py --role collector`: metadata, derivative and DEX archives.

Research writes admission requests; the monitor consumes them. It cannot overwrite
live paper account state. Each role has its own process lock and heartbeat, shown
by `/api/research/status`. The existing portfolio/quarantine and exchange read-only
permissions are preserved. Runtime artifacts stay under ignored data/lab.
