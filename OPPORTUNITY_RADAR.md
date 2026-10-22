# Independent public-data opportunity radar

No FluxScout code, Telegram content, private endpoints or authenticated accounts
are copied. Binance public and documented DEXScreener observations are used.

Collector: up to ten ranked Binance USDT spot momentum candidates (existing
liquidity/volume/trade-count and bounded momentum criteria), plus observed DEX
pairs. Rankings are heuristics, not whale attribution or buy recommendations.
First detection per identity/UTC day is immutable. DEX identity is chain + pair,
never symbol alone. Calls and outcomes are persisted in the existing registry.

The first collector observation within ten minutes AFTER 30m/2h/24h records a
reference price outcome. Earlier observations cannot settle it; missed windows
are explicitly marked and never reconstructed. Falling tokens remain recorded.
Binance estimated net subtracts an explicit 0.35 percentage-point cost assumption
from price change, NOT an executable fill. DEX net is unknown: gas, tax, routing,
liquidity, contract safety and sellability are not established. No trading allowed.
Up to four old DEX tokens due for measurement are refreshed each collector cycle;
coverage is bounded, incomplete and visible through missed-outcome counts.

Online radar learner: separate SQLite database/model from BTC/ETH/SOL control.
At each half-hour slot it freezes up to three non-anchor Binance symbols from a
snapshot no older than 15 minutes. Failed requests cannot cause selection to be
replaced with winners during that slot. It uses the existing prospective
closed-candle, ask/bid depth, net-cost and delayed-label loop. DEX tokens do NOT
enter the Binance learner and cannot be traded through a ticker-name match.

Collector cadence ~5 minutes; online polling ~30 seconds with actual prediction
slots at :00/:30. No extra Gemini calls. Output: opportunity-radar.json and
online-radar-learning.json via authenticated dashboard research status. Model
promotion, wallet connection, LP farming, contract transactions and Telegram
messages are not part of this implementation.
