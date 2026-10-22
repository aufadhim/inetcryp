# Bounded daily exploration

The research service now runs a separate daily development queue (Asia/Jakarta
calendar day). Each frozen daily plan has at most six candidates and eight
symbols, two simulations per candidate: ordinary costs and double costs with a
one-candle entry delay. Results are persisted after each candidate for crash
recovery. Completed or insufficient-data jobs are not retried that day.

The queue includes up to two bounded adviser proposals and deterministic
technical-parameter rotations. It reads only the development/validation history
before the active frozen experiment's validation endpoint, never its final
holdout. Repeated exploration on this history is NOT independent validation.
Promising results can propose candidates for the next frozen weekly experiment;
they cannot modify an existing experiment, admit paper accounts or enable live
trading. The weekly final-holdout and observed-paper gates remain unchanged.

Daily output: data/lab/daily-research.json, authenticated research status API and
dashboard. No Gemini calls are added by this daily queue. Six trials is a search
budget, not a guarantee of finding an edge.

Completed daily batches also receive a cached cost review (daily-review.json):
normal execution with loss attribution, double costs at unchanged signal timing,
the existing delayed-execution stress, and three chronological development folds.
This costs six bounded simulations per candidate and does not add hypotheses.
All results remain exploratory. Negative net returns, insufficient samples, weak
profit factor, excessive drawdown or instability across periods are explicit
rejection reasons, never overridden by the adviser.

Historical simulations currently assume 0.1% commission per side, 0.05%
slippage per side, 0.05% total quoted spread (half applied per side), plus
volume impact. These are assumptions, not verified account-specific Binance
fees. Observed paper instead uses actual observed orderbook depth and the
0.1% assumed commission; it rejects entries whose target distance is less than
five times the estimated immediate round-trip cost. Targets are not forecasts.
