import unittest
from datetime import datetime, timezone
import pandas as pd

from engine.intraday import market_regime
from engine.paper_trader import CryptoPaperTrader


class RiskRegimeTests(unittest.TestCase):
    def test_regime_requires_clear_uptrend(self):
        base = dict(Close=105.0, EMA21=103.0, EMA50=100.0, ATR_PCT=1.0, ADX14=25.0)
        frame = pd.DataFrame([base] * 100)
        self.assertEqual(market_regime(frame), "UPTREND")
        frame.loc[99, "ADX14"] = 12
        self.assertEqual(market_regime(frame), "RANGE")
        frame.loc[99, ["ADX14", "ATR_PCT"]] = [30, 5]
        self.assertEqual(market_regime(frame), "EXTREME_VOLATILITY")

    def test_daily_loss_gate(self):
        trader = CryptoPaperTrader(client=object(), persist=False,
            clock=lambda: datetime(2026, 10, 7, tzinfo=timezone.utc))
        trader.daily_loss_limit_pct = 1.0
        trader.state["history"] = [{"exit_time": "2026-10-07T01:00:00+00:00", "pnl_usd": -10}]
        self.assertTrue(trader._daily_loss_limit_hit())

    def test_nonpersistent_replay_ignores_runtime_control_file(self):
        trader = CryptoPaperTrader(client=object(), persist=False)
        self.assertTrue(trader._entries_allowed())


if __name__ == "__main__":
    unittest.main()
