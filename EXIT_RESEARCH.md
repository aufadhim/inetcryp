# Paired exit experiment

The research worker evaluates the first two frozen daily candidates with fixed
stop, net-cost-aware SL+ and trailing exit. Parameters are predeclared: activation
at a completed close at least 0.8% above entry; net lock 0.1%; trailing distance
0.6%. A raised stop applies only to the next candle. Gaps execute at observed
opening price, not an ideal stop. Intrabar ambiguities choose stop before target.

The same entry cohorts are reserved for the full maximum holding window,
regardless of each exit's early close. Up to 60 chronological cohorts per symbol
are evaluated using normal costs and doubled costs plus one-candle delayed entry.
Each scenario is paired across exit policies, but delayed and normal scenarios
need not have identical entries. Results include regime breakdowns and entry times.

These are independent $50 trade diagnostics, NOT a portfolio return. They do not
simulate cross-symbol exposure limits or the portfolio daily-loss cap. No variant
is admitted into paper or promoted from these results. Final validation and paper
must test a separately frozen strategy with the desired exit policy. No original
Candidate ID or existing live/forward account is modified.

Daily JSON output: data/lab/exit-research.json; authenticated dashboard status
includes the result. Existing frozen data cutoff is respected, no new holdout
is read. Runtime is bounded and completed results are cached in the registry.
