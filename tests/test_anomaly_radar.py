import unittest
from unittest.mock import patch
import requests
import tempfile
from pathlib import Path
from datetime import datetime,timezone,timedelta
from engine.anomaly_radar import classify,observe_calls,review,collect
from engine.research_lab import Registry


class AnomalyTests(unittest.TestCase):
    def test_rate_limit_backoff_does_not_invent_signals(self):
        with tempfile.TemporaryDirectory() as folder:
            reg=Registry(str(Path(folder)/"test.sqlite"))
            response=requests.Response();response.status_code=429
            error=requests.HTTPError(response=response)
            with patch("engine.anomaly_radar.fetch_json",side_effect=error) as fetch:
                first=collect(reg,lambda path:{"symbols":[]})
                second=collect(reg,lambda path:{"symbols":[]})
                self.assertEqual(fetch.call_count,1)
            self.assertEqual(first["source_http_status"],429)
            self.assertEqual(second["status"],"degraded")
            self.assertEqual(second["items"],[])
            self.assertEqual(second["total_calls"],0)
            reg.db.close()

    def test_review_includes_losses_and_missed_measurements(self):
        calls=[{"entry":{"signal":"LONG"},"outcomes":{"30m":{"status":"OBSERVED","directional_change_pct":-10,"estimated_long_net_pct":-10.35}}},
               {"entry":{"signal":"LONG"},"outcomes":{"30m":{"status":"MISSED"}}}]
        row=review(calls)["30m"]["LONG"]
        self.assertEqual(row["observed"],1)
        self.assertEqual(row["missed"],1)
        self.assertEqual(row["mean_directional_change_pct"],-10)
        self.assertEqual(row["positive_estimated_long_net"],0)
        self.assertFalse(row["sample_sufficient"])

    def setUp(self):
        self.now=datetime(2026,1,1,tzinfo=timezone.utc)
        self.coin={"id":"pha","symbol":"pha","market_cap":100000,"total_volume":200000,
            "current_price":100,"price_change_percentage_1h_in_currency":-3,"last_updated":self.now.isoformat()}

    def book(self):
        return {"bids":[[99.99,10000]],"asks":[[100.01,7000]],"received_at":self.now.isoformat(),"latency_ms":10}

    def test_dip_requires_fresh_deep_orderbook(self):
        self.assertEqual(classify(self.coin,self.now)["signal"],"WATCH")
        result=classify(self.coin,self.now,self.book())
        self.assertEqual(result["signal"],"LONG")
        self.assertEqual(result["score"],80)
        self.assertFalse(result["paper_admission"])

    def test_rising_high_turnover_is_only_short_hypothesis(self):
        result=classify({**self.coin,"price_change_percentage_1h_in_currency":3},self.now)
        self.assertEqual(result["signal"],"SHORT")
        self.assertFalse(result["live_trading"])

    def test_missing_and_stale_values_never_become_accumulation(self):
        for coin in ({**self.coin,"market_cap":None},{**self.coin,"last_updated":(self.now-timedelta(hours=1)).isoformat()},
                     {**self.coin,"total_volume":float("nan")}):
            self.assertEqual(classify(coin,self.now,self.book())["signal"],"WATCH")

    def test_falling_knife_and_stablecoin_excluded(self):
        for coin in ({**self.coin,"price_change_percentage_1h_in_currency":-6},
                     {**self.coin,"id":"tether","price_change_percentage_1h_in_currency":2}):
            self.assertEqual(classify(coin,self.now,self.book())["signal"],"WATCH")

    def test_thin_spoofable_or_disagreeing_book_cannot_confirm(self):
        thin={**self.book(),"bids":[[99.99,1]],"asks":[[100.01,1]]}
        self.assertEqual(classify(self.coin,self.now,thin)["signal"],"WATCH")
        self.assertEqual(classify({**self.coin,"current_price":110},self.now,self.book())["signal"],"WATCH")
        self.assertEqual(classify({**self.coin,"id":"unverified-token","symbol":"pha"},self.now,self.book())["signal"],"WATCH")

    def test_losses_are_recorded_without_flooring_and_entry_is_immutable(self):
        with tempfile.TemporaryDirectory() as folder:
            reg=Registry(str(Path(folder)/"test.sqlite"))
            item=classify(self.coin,self.now,self.book())
            calls=observe_calls(reg,[item],[],self.now)
            key=calls[0]["id"]
            later=self.now+timedelta(minutes=30)
            price={**self.coin,"current_price":90,"last_updated":later.isoformat()}
            calls=observe_calls(reg,[{**item,"price":150}],[price],later)
            call=reg.get("anomaly_call",key)
            self.assertEqual(call["entry"]["price"],100)
            self.assertAlmostEqual(call["outcomes"]["30m"]["price_change_pct"],-10)
            self.assertAlmostEqual(call["outcomes"]["30m"]["estimated_long_net_pct"],-10.35)
            self.assertEqual(len(calls),1)
            reg.db.close()

    def test_cached_price_before_deadline_cannot_settle(self):
        with tempfile.TemporaryDirectory() as folder:
            reg=Registry(str(Path(folder)/"test.sqlite"))
            item=classify(self.coin,self.now,self.book())
            calls=observe_calls(reg,[item],[],self.now)
            calls=observe_calls(reg,[],[self.coin],self.now+timedelta(minutes=30))
            self.assertNotIn("30m",calls[0]["outcomes"])
            calls=observe_calls(reg,[],[],self.now+timedelta(minutes=51))
            self.assertEqual(calls[0]["outcomes"]["30m"]["status"],"MISSED")
            reg.db.close()

    def test_short_outcome_is_directional_not_spot_profit(self):
        with tempfile.TemporaryDirectory() as folder:
            reg=Registry(str(Path(folder)/"test.sqlite"))
            item=classify({**self.coin,"price_change_percentage_1h_in_currency":3},self.now)
            observe_calls(reg,[item],[],self.now)
            later=self.now+timedelta(minutes=30)
            calls=observe_calls(reg,[],[{**self.coin,"current_price":90,"last_updated":later.isoformat()}],later)
            outcome=calls[0]["outcomes"]["30m"]
            self.assertAlmostEqual(outcome["directional_change_pct"],10)
            self.assertIsNone(outcome["estimated_long_net_pct"])
            reg.db.close()
