import tempfile
import unittest
from unittest.mock import Mock, patch
import pandas as pd
from engine.historical_data import historical


class HistoryTests(unittest.TestCase):
    def test_download_cache_and_no_unfinished_bar(self):
        start = pd.Timestamp("2025-01-01T00:00:00Z")
        rows = [[int((start+pd.Timedelta(minutes=15*i)).timestamp()*1000), "100", "102", "99", "101", "10"] for i in range(3)]
        session = Mock()
        session.get.return_value.json.return_value = rows
        with tempfile.TemporaryDirectory(dir="C:/inetcryp", prefix="history-test-") as folder:
            with patch("engine.historical_data.requests.Session", return_value=session):
                a, metadata = historical("BTCUSDT", start, start+pd.Timedelta(minutes=45), folder)
                b, again = historical("BTCUSDT", start, start+pd.Timedelta(minutes=45), folder)
            pd.testing.assert_frame_equal(a, b, check_freq=False, check_dtype=False)
            self.assertEqual(metadata["sha256"], again["sha256"])
            self.assertEqual(session.get.call_count, 1)
            self.assertEqual(session.get.call_args.kwargs["params"]["endTime"], int((start+pd.Timedelta(minutes=45)).timestamp()*1000)-1)

    def test_empty_page_fails_closed(self):
        session = Mock()
        session.get.return_value.json.return_value = []
        with tempfile.TemporaryDirectory(dir="C:/inetcryp", prefix="history-test-") as folder:
            with patch("engine.historical_data.requests.Session", return_value=session):
                with self.assertRaises(ValueError):
                    historical("BTCUSDT", "2025-01-01", "2025-01-02", folder)

    def test_invalid_symbol_rejected(self):
        with self.assertRaises(ValueError):
            historical("../secret", "2025-01-01", "2025-01-02")

    def test_pagination_advances_and_preserves_all_bars(self):
        start = pd.Timestamp("2025-01-01T00:00:00Z")
        rows = [[int((start+pd.Timedelta(minutes=15*i)).timestamp()*1000), "100", "102", "99", "101", "10"] for i in range(1001)]
        session = Mock()
        session.get.return_value.json.side_effect = [rows[:1000], rows[1000:]]
        with tempfile.TemporaryDirectory(dir="C:/inetcryp", prefix="history-test-") as folder:
            with patch("engine.historical_data.requests.Session", return_value=session):
                frame, _ = historical("BTCUSDT", start, start+pd.Timedelta(minutes=15*1001), folder)
        self.assertEqual(len(frame), 1001)
        self.assertEqual(session.get.call_count, 2)
        self.assertEqual(session.get.call_args_list[1].kwargs["params"]["startTime"], rows[1000][0])

    def test_missing_bar_rejected(self):
        start = pd.Timestamp("2025-01-01T00:00:00Z")
        session = Mock()
        session.get.return_value.json.return_value = [[int((start+pd.Timedelta(minutes=15*i)).timestamp()*1000), "100", "102", "99", "101", "10"] for i in (0, 2)]
        with tempfile.TemporaryDirectory(dir="C:/inetcryp", prefix="history-test-") as folder:
            with patch("engine.historical_data.requests.Session", return_value=session):
                with self.assertRaises(ValueError):
                    historical("BTCUSDT", start, start+pd.Timedelta(minutes=45), folder)
