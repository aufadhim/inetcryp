import unittest
import numpy as np
import pandas as pd
from engine.numpang_paus_crypto import score_layers


class PausScoreTests(unittest.TestCase):
    def test_score_is_bounded_and_explainable(self):
        n=181; close=np.linspace(100,120,n)
        frame=pd.DataFrame({"Open":close,"High":close+1,"Low":close-1,"Close":close,
            "Volume":1000,"QuoteVolume":2_000_000,"CVD_Delta":1000},
            index=pd.date_range("2026-01-01",periods=n,freq="4h"))
        result=score_layers("BTCUSDT",frame,{"bid_ask_ratio":1.5},
            {"funding_rate_pct":0.01},{"weighted_pressure_pct":20,"exchange_count":3})
        self.assertTrue(0 <= result["score"] <= 100)
        self.assertIn("spot_accumulation",result["layers"])
        self.assertEqual(result["action"],"watchlist_only")


if __name__ == "__main__": unittest.main()
