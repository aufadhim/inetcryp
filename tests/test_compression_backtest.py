import unittest
from tests.test_compression_screener import setup_frame
from engine.compression_backtest import backtest_compression, walk_forward


class CompressionBacktestTests(unittest.TestCase):
    def test_backtest_is_cost_aware_and_bounded(self):
        frame = setup_frame(True)
        result = backtest_compression(frame, "ASTERUSDT")
        self.assertEqual(result["strategy"], "post_downtrend_compression_v1")
        self.assertEqual(result["fee_pct_per_side"], 0.1)
        self.assertGreaterEqual(result["max_drawdown_pct"], 0)

    def test_short_history_rejected(self):
        result = backtest_compression(setup_frame().iloc[:100], "ASTERUSDT")
        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
