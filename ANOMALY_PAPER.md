# Prospective anomaly experiment

The 30-second monitor runs `engine/anomaly_paper.py` separately from the main
paper account. Output: `data/lab/anomaly-paper.json`. It never sends orders.

Frozen v1 protocol: verified Binance spot LONG anomaly calls only, first seen
within 90 seconds, $50 including fees per entry, max five positions, $1,000
isolated starting capital. Stop at -1.5% net liquidation, target +3%, 2h time
exit. After +1% net liquidation, SL+ triggers at +0.2%; actual observed bids
determine the fill, so gaps can still lose money. Pause new entries after $10
realized daily loss. Fresh depth required; missing quotes retain open risk.
Assumed fee 0.1% per side, not the user's verified account fee. No queue/latency
guarantee. No automatic promotion. Restart resumes the persisted state.

This is NOT a backtest of FluxScout's proprietary engine. Current JSON signals
cannot reconstruct historical orderbooks, holders, or the tokens never called.
Historical OHLCV strategies continue in the separate frozen research worker;
on-chain and orderbook hypotheses require prospective archived observations.
DEX and SHORT remain observation-only. Results must include losses, rejected
entries, gaps, missing quotes and costs; do not market best-call peaks as PnL.

Increasing polling cannot defeat API rate limits or create independent samples.
Keep public source backoff and existing validation gates. The machine must remain
powered and connected for the Windows scheduled supervisor to operate 24/7.
