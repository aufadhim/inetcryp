# Independent anomaly hypotheses, anomaly_v1

Source: CoinGecko top 150 by 24h volume, refreshed at most every 15 minutes.
Provider last_updated must be no more than 15 minutes old; missing values do not
become zero risk or synthetic accumulation. Explicit stablecoin IDs are excluded.
This is a bounded subset, not an all-chain scanner. Fetch failures are visible.

Predeclared rules: positive/nonnegative 1h change and volume/MC >1 => SHORT
hypothesis score 70. A dip between -5% and -2% with volume/MC >0.15 requires a
fresh verified Binance spot orderbook, >=$25K observed depth on EACH side within
0.5% of mid, bid/ask notional ratio >=1.2, spread <=0.2%, and <=1% price divergence
from the provider reference. Score is 80 for ratio >0.5, otherwise 60. Deeper dips
are excluded. Identity matching uses an explicit six-coin CoinGecko-ID map and
active exchange listing verification, never ticker-only matching. Unknown maps
cannot confirm LONG. A single depth snapshot cannot prove absorption or exclude
spoofing. Scores are heuristic labels, not probabilities or manipulation proof.

Calls freeze original inputs and receipt times, once per coin/direction/UTC day.
Reference prices are actual provider price fields, NOT market-cap ratios. Results
at 30m, 2h, 24h use only provider prices timestamped AFTER the deadline and within
a bounded 20-minute observation window. Negative returns are never clamped. Late
or missing outcomes are MISSED, never reconstructed. Once all horizons resolve,
the call is CLOSED. Open, closed, losing and missed calls are retained.

LONG net is explicitly only a 0.35 percentage-point cost estimate, not realized
portfolio PnL. SHORT outcome is directional price movement only: borrowing,
funding and execution costs are unknown and no short order is ever submitted.
No live/paper admission, wallet actions, Telegram spam or external code execution.
No FluxScout private API, assets or sample history is copied into our results.

Authenticated API: /api/radar/anomalies. Snapshot: data/lab/anomaly-radar.json.
Collector role writes it; dashboard displays current signals and full outcomes
for the latest 50 calls. All calls remain in the local research registry.
