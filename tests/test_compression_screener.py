import unittest
import numpy as np
import pandas as pd
from engine.compression_screener import analyze_compression


def setup_frame(breakout=False):
    n = 121
    pre = np.linspace(120, 100, 49)
    base = np.linspace(100, 98, 48) + np.sin(np.arange(48))*1.0
    tail = np.linspace(98.0, 99.0, 24) + np.sin(np.arange(24))*np.linspace(1.0, .12, 24)
    close = np.concatenate([pre, base, tail])[:n]
    high = close + np.concatenate([np.full(97, 1.0), np.linspace(1.0, .2, 24)])[:n]
    low = close - np.concatenate([np.full(97, 1.0), np.linspace(1.0, .2, 24)])[:n]
    volume = np.concatenate([np.full(97, 200.0), np.full(24, 100.0)])[:n]
    if breakout:
        close[-2] = high[-13:-2].max()+0.5
        high[-2] = close[-2]+0.1
        low[-2] = close[-2]-0.2
        volume[-2] = 400
    return pd.DataFrame({"Open": close, "High": high, "Low": low, "Close": close,
        "Volume": volume, "CVD_Delta": np.ones(n)*10},
        index=pd.date_range("2026-01-01", periods=n, freq="4h"))


class CompressionTests(unittest.TestCase):
    def test_finds_post_downtrend_compression(self):
        result = analyze_compression("ASTERUSDT", setup_frame())
        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "WATCH_COMPRESSION")
        self.assertTrue(result["cvd_accumulation"])

    def test_rejects_no_downtrend(self):
        frame = setup_frame()
        frame.loc[frame.index[:49], ["Open", "High", "Low", "Close"]] = 100
        self.assertIsNone(analyze_compression("FLATUSDT", frame))


if __name__ == "__main__":
    unittest.main()
