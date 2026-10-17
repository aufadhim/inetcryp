import unittest
from unittest.mock import Mock
from engine.signal_engine import score_signal
from engine.multi_exchange import CrossExchangeMarket
from engine.telegram_worker import TelegramWorker


class CoreTests(unittest.TestCase):
    def test_signal_score_is_bounded_and_explainable(self):
        result = score_signal({"lpm_score": 70, "intensity": 2.0, "dist_bandar_pct": 0, "phase": "MARK_UP", "divergence": "BULLISH_DIVERGENCE"}, {"weighted_pressure_pct": 20, "exchange_count": 3})
        self.assertGreaterEqual(result["score"], 0)
        self.assertLessEqual(result["score"], 100)
        self.assertTrue(result["reasons"])

    def test_pressure_normalization(self):
        row = CrossExchangeMarket._normalize("test", "BTCUSDT", [[100, 2]], [[101, 1]])
        self.assertAlmostEqual(row["bid_volume_usdt"], 200)
        self.assertGreater(row["pressure_pct"], 0)

    def test_telegram_rejects_unconfigured_or_wrong_chat(self):
        worker = TelegramWorker.__new__(TelegramWorker)
        worker.allowed_chat = "123"
        worker.send = Mock()
        worker.handle({"chat": {"id": 999}, "text": "/start"})
        worker.send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
