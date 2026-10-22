# Prospective online learning (online_v1)

Runs in the existing isolated monitor every ~30 seconds. It issues at most one
forecast per BTCUSDT, ETHUSDT and SOLUSDT per UTC half-hour slot, only within
90 seconds of the slot. This is NOT one new training example per polling tick.
No retrospective predictions or historical bootstrap are counted as learning.

Inputs are nine fixed, clipped features from complete closed 15-minute candles:
intercept, 30-minute return, EMA9/21 and EMA21/50 separation, RSI, relative volume,
ATR and two regime indicators. A bounded regularized logistic SGD model predicts
whether a $50 long diagnostic will have positive proceeds after costs 30 minutes
after actual issuance. Model weights are persisted separately from trading.

The entry is a fresh observed ask-depth VWAP; settlement uses fresh observed bid
depth, fees on entry and exit. Current verified undiscounted taker rates are used
when the production read-only audit is no older than six hours, otherwise an
explicit 0.1% per-side assumption is recorded. Every prediction freezes its fees,
features, probability, model training count, baseline probability, receipt time
and deadline. Sufficient full depth and quote freshness/latency are required.

Pending predictions are not training examples. A fresh quote at/after the
deadline and within 90 seconds gives the label. Later observations are recorded
as late_discarded and never update the model or quality scores. Scoring always
uses the original forecast, never a re-prediction after training. SQLite commits
the outcome and one model update atomically; duplicate callbacks cannot retrain.

The comparison baseline is the smoothed positive-label frequency available at
forecast issuance. Brier score evaluates probabilistic quality. A rolling recent
warning detects deterioration relative to this baseline. Quality statistics use
up to 2,000 recent scored forecasts; observed UTC-day count spans all outcomes.

Warmup: 200 prospective labels. Review readiness additionally requires 30 observed
UTC days, better Brier score than the baseline, 50 confident forecasts made after
warmup, positive sum of cost-adjusted outcomes and no recent deterioration. These
are screening checks, NOT proof of profitability, independence or robustness.
Cross-coin forecasts are correlated. Independent forward portfolio evaluation,
drawdown/risk testing and adverse execution tests are still needed before any
admission. No self-promotion into trading is implemented by this module.

Output is a hypothetical signal diagnostic, not portfolio return: it does not
simulate allocation limits, stops, rebalancing or PnL on actual holdings.
paper_admission and live_trading are always false. No exchange order endpoint,
Gemini calls or credential access exists in this module.

Persistence: data/lab/online-learning.sqlite. Snapshot: online-learning.json,
authenticated research API and dashboard. Polling continues while no forecasts
are due. After a restart between slots, it waits for the next :00/:30 boundary
instead of inventing missed predictions.
