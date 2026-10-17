import unittest
from unittest.mock import patch
import pandas as pd
from engine.paper_replay import replay, ReplayClient
from engine.paper_trader import CryptoPaperTrader
from engine.intraday import STRATEGY


def candles(count=120):
    return pd.DataFrame({"Open": 100.0, "High": 101.0, "Low": 99.0,
                         "Close": 100.0, "Volume": 100.0},
                        index=pd.date_range("2025-01-01", periods=count, freq="15min"))


class ReplayTests(unittest.TestCase):
    def test_current_candle_future_is_hidden(self):
        frame = candles()
        frame.iloc[100, frame.columns.get_loc("Close")] = 900
        observed = ReplayClient(frame, 100).get_klines("BTCUSDT")
        self.assertEqual(len(observed), 101)
        self.assertEqual(observed.iloc[-1].Close, 100)
        self.assertEqual(observed.iloc[-1].Volume, 0)

    def test_round_trip_costs(self):
        trader = CryptoPaperTrader(client=object(), persist=False)
        entry = 100 * 1.0005
        pos = dict(quantity=50 / 1.001 / entry, fee_pct=0.1, slippage_pct=0.05)
        self.assertAlmostEqual(trader.liquidation_value(pos, 100), 50/1.001/1.0005*0.9995*0.999)
        self.assertLess(trader.liquidation_value(pos, 100), 50)

    def test_same_engine_time_stop_costs_and_cooldown(self):
        with patch("engine.paper_trader.technical_entry", return_value=STRATEGY):
            result = replay(candles(120))
        self.assertEqual(result["total_trades"], 1)
        self.assertIn("Time Stop", result["trades"][0]["reason"])
        self.assertLess(result["trades"][0]["pnl_usd"], 0)
        self.assertEqual(result["trades"][0]["accounting_version"], "net_costs_v1")
        self.assertGreater(result["max_drawdown_pct"], 0)

    def test_future_changes_do_not_change_prior_equity(self):
        a = candles(110)
        b = a.copy()
        b.iloc[108:, b.columns.get_loc("Open")] = 200
        with patch("engine.paper_trader.technical_entry", return_value=STRATEGY):
            left, right = replay(a), replay(b)
        self.assertEqual(left["equity_curve"][:8], right["equity_curve"][:8])

    def test_legacy_value_unchanged(self):
        self.assertEqual(CryptoPaperTrader.liquidation_value(dict(size_usd=50, entry_price=100), 110), 55)

    def test_stop_loss_uses_observed_gap_price_not_ideal_stop(self):
        frame = candles(103)
        frame.iloc[101:, frame.columns.get_loc("Open")] = 95
        with patch("engine.paper_trader.technical_entry", return_value=STRATEGY):
            result = replay(frame)
        self.assertEqual(result["total_trades"], 1)
        self.assertEqual(result["trades"][0]["exit_price"], 95)
        self.assertLess(result["trades"][0]["pnl_pct"], -5)

    def test_trailing_stop_locks_then_exits(self):
        frame = candles(104)
        frame.iloc[101, frame.columns.get_loc("Open")] = 101.5
        frame.iloc[102:, frame.columns.get_loc("Open")] = 100.5
        with patch("engine.paper_trader.technical_entry", return_value=STRATEGY):
            result = replay(frame)
        self.assertGreaterEqual(result["total_trades"], 1)
        self.assertIn("SL+", result["trades"][0]["reason"])
        self.assertGreater(result["trades"][0]["pnl_usd"], 0)

    def test_short_history_rejected(self):
        self.assertIn("error", replay(candles(100)))


if __name__ == "__main__":
    unittest.main()
