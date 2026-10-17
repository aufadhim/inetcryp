import unittest
import numpy as np
import pandas as pd
from engine.metrics import calculate_crypto_metrics
from engine.replay_features import ReplayFeatures
from engine.paper_replay import replay


def sample(n=520):
    rng = np.random.default_rng(41)
    close = 100 + np.cumsum(rng.normal(0.04, 0.4, n))
    return pd.DataFrame(dict(Open=close, High=close+0.5, Low=close-0.5,
                             Close=close, Volume=rng.uniform(80, 180, n)),
                        index=pd.date_range("2025-01-01", periods=n, freq="15min", tz="UTC"))


class FastReplayTests(unittest.TestCase):
    def test_last_rows_equal_reference_with_rolling_seed(self):
        frame = sample()
        features = ReplayFeatures(frame)
        for cursor in (100, 199, 200, 201, 400, 519):
            expected = calculate_crypto_metrics(frame.iloc[max(0,cursor-200):cursor])
            actual = features.at(cursor).iloc[-2:]
            np.testing.assert_allclose(actual.to_numpy(), expected[actual.columns].iloc[-2:].to_numpy(), rtol=1e-12, atol=1e-10)

    def test_future_does_not_change_features(self):
        frame = sample()
        changed = frame.copy()
        changed.iloc[300:] *= 2
        pd.testing.assert_frame_equal(ReplayFeatures(frame).at(300), ReplayFeatures(changed).at(300))

    def test_fast_and_reference_trades_equity_match(self):
        frame = sample(260)
        slow, fast = replay(frame), replay(frame, fast=True)
        self.assertEqual(slow["trades"], fast["trades"])
        self.assertEqual(slow["equity_curve"], fast["equity_curve"])
        self.assertGreater(slow["total_trades"] + slow["open_positions_count"], 0)
