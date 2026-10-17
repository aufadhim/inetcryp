import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd

from engine.intraday import STRATEGY, entry_signal
from engine.metrics import calculate_crypto_metrics
from engine.paper_trader import CryptoPaperTrader


def signal_frame():
    frame = pd.DataFrame([dict(Close=102, Low=100, EMA9=101,
        EMA21=100, EMA50=99, ATR14=2, RSI14=58, RelativeVolume=1.3)] * 100, dtype=float)
    frame.loc[98, "EMA50"] = 98.9
    frame.loc[98, "Close"] = 101.5
    return frame


class IntradayTests(unittest.TestCase):
    def test_valid_pullback(self):
        self.assertEqual(entry_signal(signal_frame()), STRATEGY)

    def test_reject_bad_conditions(self):
        for field, value in [("EMA50", 102), ("RSI14", 80),
                             ("RelativeVolume", 1), ("Close", 110),
                             ("ATR14", 0), ("Close", float("nan"))]:
            with self.subTest(field=field, value=value):
                frame = signal_frame()
                frame.loc[99, field] = value
                self.assertIsNone(entry_signal(frame))
        self.assertIsNone(entry_signal(signal_frame().iloc[:99]))

    def test_requires_pullback_and_rising_trend(self):
        frame = signal_frame()
        frame.loc[98, "Low"] = 102
        self.assertIsNone(entry_signal(frame))
        frame = signal_frame()
        frame.loc[98, "EMA50"] = 99
        self.assertIsNone(entry_signal(frame))

    def test_metrics_do_not_see_future(self):
        close = pd.Series(range(100, 230), dtype=float)
        raw = pd.DataFrame(dict(Open=close, High=close+1, Low=close-1,
                                Close=close, Volume=100.0))
        full = calculate_crypto_metrics(raw)
        prefix = calculate_crypto_metrics(raw.iloc[:110])
        cols = ["EMA9", "EMA21", "EMA50", "ATR14", "RSI14", "RelativeVolume"]
        pd.testing.assert_frame_equal(full.loc[:109, cols], prefix[cols])
        self.assertEqual(full.iloc[-1].RSI14, 100)

    def test_paper_uses_closed_candle_and_prevents_duplicate_entry(self):
        frame = signal_frame()
        raw = pd.DataFrame({"Close": [102.0] * 101})
        client = Mock()
        client.get_klines.return_value = raw
        with tempfile.TemporaryDirectory(dir="C:/inetcryp", prefix="intraday-test-") as temp:
            trader = CryptoPaperTrader(str(Path(temp) / "journal.json"), client)
            trader.max_alloc = 50
            with patch("engine.paper_trader.calculate_crypto_metrics", return_value=frame) as metrics:
                trader.run_eval_cycle(["BTCUSDT"])
                self.assertEqual(len(metrics.call_args.args[0]), 100)
                self.assertEqual(trader.state["open_positions"]["BTCUSDT"]["strategy"], STRATEGY)
                trader.state["open_positions"].clear()
                trader.state["cash_usdt"] = 1000
                trader.run_eval_cycle(["BTCUSDT"])
                self.assertFalse(trader.state["open_positions"])

    def test_paper_rejects_execution_price_chase(self):
        client = Mock()
        client.get_klines.return_value = pd.DataFrame({"Close": [110.0] * 101})
        with tempfile.TemporaryDirectory(dir="C:/inetcryp", prefix="intraday-test-") as temp:
            trader = CryptoPaperTrader(str(Path(temp) / "journal.json"), client)
            with patch("engine.paper_trader.calculate_crypto_metrics", return_value=signal_frame()):
                trader.run_eval_cycle(["BTCUSDT"])
            self.assertFalse(trader.state["open_positions"])


if __name__ == "__main__":
    unittest.main()
