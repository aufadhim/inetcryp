import unittest
from datetime import datetime, timezone, timedelta
from engine.anomaly_paper import initial, step


class AnomalyPaperTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 22, tzinfo=timezone.utc)
        self.call = {"id": "one", "detected_at": self.now.isoformat(),
                     "entry": {"signal": "LONG", "binance_symbol": "XUSDT", "binance_spot_listing_verified": True}}
        self.state = initial()

    def book(self, price=100, now=None):
        return {"XUSDT": {"bids": [[price, 1000]], "asks": [[price*1.0001, 1000]],
                          "received_at": (now or self.now).isoformat(), "latency_ms": 10}}

    def test_fee_loss_on_flat_price_and_no_repeated_entry(self):
        step(self.state, [self.call], self.book(), self.now)
        self.assertEqual(self.state["cash"], 950)
        self.assertLess(self.state["equity_last_observed"], 1000)
        later = self.now+timedelta(hours=2)
        step(self.state, [self.call], self.book(now=later), later)
        self.assertLess(self.state["realized_pnl"], 0)
        self.assertEqual(len(self.state["trades"]), 1)
        self.assertEqual(self.state["positions"], {})

    def test_short_stale_or_unverified_never_enters(self):
        for entry in ({**self.call["entry"], "signal": "SHORT"},
                      {**self.call["entry"], "binance_spot_listing_verified": False}):
            state = initial()
            step(state, [{**self.call, "entry": entry}], self.book(), self.now)
            self.assertEqual(state["positions"], {})
        step(self.state, [self.call], self.book(), self.now+timedelta(minutes=2))
        self.assertEqual(self.state["positions"], {})

    def test_missing_exit_does_not_fabricate_profit(self):
        step(self.state, [self.call], self.book(), self.now)
        step(self.state, [], {}, self.now+timedelta(hours=3))
        self.assertEqual(len(self.state["positions"]), 1)
        self.assertEqual(self.state["stale_marks"], 1)
        self.assertEqual(self.state["realized_pnl"], 0)

    def test_sl_plus_can_gap_into_loss(self):
        step(self.state, [self.call], self.book(), self.now)
        later = self.now+timedelta(minutes=1)
        step(self.state, [], self.book(102, later), later)
        self.assertTrue(self.state["positions"]["XUSDT"]["protected"])
        later += timedelta(minutes=1)
        step(self.state, [], self.book(95, later), later)
        self.assertLess(self.state["realized_pnl"], 0)
        self.assertFalse(self.state["live_trading"])
