# Forward dynamic spot universe — liquid_momentum_v1

The worker refreshes public Binance spot selection every 15 minutes (subject to
worker polling). It ranks active USDT pairs, not a BTC/ETH/SOL whitelist. Memecoins
can qualify; no unreliable automatic meme or whale classification is claimed.

Filters: explicit spot trading allowed; exclude known stable/pegged assets and
leveraged-token suffixes; >=$5m quote volume and >=5,000 trades over 24h; positive
24h change <=25%; finite values and ticker timestamp <=120s old. Up to 30 ranked
pairs receive orderbook checks. Require spread <=0.2% and at least $25k visible
depth on EACH side within 0.5% of midpoint, using up to 100 levels. Rank by bounded
24h momentum plus liquidity; keep at most 10. This is not acceleration/relative
strength/on-chain whale detection, and visible orderbooks can change or be spoofed.

Selection alone never buys: existing completed-candle EMA entry rules remain.
New entries capped at five concurrent positions and at most $50 each, including
all existing positions when checking the cap. Existing positions continue to be
managed if they leave the universe or selection is empty/unavailable. No forced
liquidation from ranking changes. Screener budget ~45s plus final request timeout;
failures stop new entries and retry no sooner than 60s. Successful results cached
15m; these screening checks are not execution-time liquidity guarantees.

Public data session has no API credentials. Snapshots are timestamped under
data/universe; latest.json is replaced atomically. Positions record selection
version and timestamp. Telegram /screener and GET /api/universe expose the current
watchlist, not investment recommendations. A stale flag warns after 20 minutes.

This is a forward paper experiment, NOT a historically validated dynamic strategy.
Do not backtest today's winners backwards. Historical universe membership,
delistings, orderbook snapshots and multi-asset capital constraints are not yet
replayed. Existing single-symbol historical results do not validate this selector.
No automatic live trading or API permission changes.
