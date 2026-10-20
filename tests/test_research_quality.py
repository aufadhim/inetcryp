import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from engine.research_data import asof_observation, dex_risk, coin_metadata, derivatives, token_security
from engine.research_lab import Registry, account, advance, Candidate, compare_forward, holdout_watermark, features


class ResearchQualityTests(unittest.TestCase):
    def test_receipt_timestamp_prevents_retroactive_fundamentals(self):
        row={"observed_at":"2025-01-02T00:00Z","source_updated_at":"2024-12-01T00:00Z"}
        self.assertIsNone(asof_observation([row],"2025-01-01T00:00Z"))
        self.assertEqual(asof_observation([row],"2025-01-03T00:00Z"),row)

    def test_unknown_liquidity_never_passes_dex_filters(self):
        risk=dex_risk({"volume":{"h24":1000000},"txns":{"h24":{"sells":100}}})
        self.assertFalse(risk["market_filters_pass"])
        self.assertFalse(risk["eligible_for_paper"])
        self.assertIn("missing_or_thin_liquidity",risk["reasons"])

    def test_market_filter_does_not_prove_contract_safety(self):
        risk=dex_risk({"liquidity":{"usd":100000},"volume":{"h24":1000000},"fdv":1000000,
            "pairCreatedAt":1600000000000,"txns":{"h24":{"sells":100}}})
        self.assertTrue(risk["market_filters_pass"])
        self.assertFalse(risk["eligible_for_paper"])

    def test_missing_coin_metadata_stays_missing(self):
        with patch("engine.research_data.fetch_json",return_value=[{"id":"coin","symbol":"x"}]):
            row=coin_metadata()["coins"][0]
        self.assertIsNone(row["market_cap"])

    def test_security_flags_cannot_approve_a_trade(self):
        payload={"code":1,"result":{"TOKEN":{"mintable":{"status":"1"},"holders":[{"percent":"0.7"}]}}}
        with patch("engine.research_data.fetch_json",return_value=payload):
            result=token_security("solana","TOKEN")
        self.assertIn("mintable",result["flags"])
        self.assertIn("top10_concentration_including_lp",result["flags"])
        self.assertFalse(result["eligible_for_paper"])

    def test_derivatives_failure_isolated(self):
        with patch("engine.research_data.fetch_json",side_effect=[ValueError(),[{"timestamp":1}]]):
            result=derivatives("BTCUSDT")
        self.assertEqual(result["sources"]["funding"]["status"],"unavailable")
        self.assertEqual(result["sources"]["open_interest"]["status"],"ok")

    def test_participation_limit_rejects_illiquid_entry(self):
        s=account()
        advance(s,Candidate("channel_breakout"),{"X":{"Open":100,"High":100,"Low":100,"Close":100,
            "decision_quote_volume":1000}},{"X":True},"2025-01-01T00:00Z")
        self.assertFalse(s["positions"])
        self.assertEqual(s["cash"],1000)

    def test_old_bar_cannot_rewind_account(self):
        s=account()
        c=Candidate("channel_breakout")
        bar={"Open":100,"High":100,"Low":100,"Close":100}
        advance(s,c,{"X":bar},{},"2025-01-02T00:00Z")
        advance(s,c,{"X":bar},{"X":True},"2025-01-01T00:00Z")
        self.assertFalse(s["positions"])
        self.assertEqual(s["last_at"],"2025-01-02T00:00:00+00:00")

    def test_holdout_watermark_includes_previous_versions(self):
        with tempfile.TemporaryDirectory() as folder:
            reg=Registry(str(Path(folder)/"registry.sqlite"))
            reg.put("experiment","legacy",{"status":"completed","end":"2025-01-10T00:00Z","holdout":{}})
            reg.put("experiment","pending",{"status":"awaiting_fresh_holdout","end":"2025-02-01T00:00Z"})
            self.assertEqual(holdout_watermark(reg),pd.Timestamp("2025-01-10T00:00Z"))
            reg.db.close()

    def test_time_series_deduplicates_without_rewriting_receipt_time(self):
        with tempfile.TemporaryDirectory() as folder:
            reg=Registry(str(Path(folder)/"registry.sqlite"))
            rows=[{"timestamp":1700000000000,"value":1}]
            self.assertEqual(reg.series("oi","BTC",rows,"timestamp"),1)
            receipt=reg.db.execute("SELECT received_at FROM observation_points").fetchone()[0]
            self.assertEqual(reg.series("oi","BTC",rows,"timestamp"),0)
            self.assertEqual(reg.db.execute("SELECT received_at FROM observation_points").fetchone()[0],receipt)
            reg.db.close()

    def test_champion_uses_common_days_not_lifetime_profit(self):
        challenger,incumbent=account(),account()
        dates=pd.date_range("2025-01-01",periods=50,tz="UTC")
        challenger["equity_curve"]=[{"at":str(t),"equity":1000*(1.002**i)} for i,t in enumerate(dates[10:])]
        incumbent["equity_curve"]=[{"at":str(t),"equity":2000*(1.001**i)} for i,t in enumerate(dates)]
        result=compare_forward(challenger,incumbent)
        self.assertTrue(result["replace"])
        self.assertEqual(result["common_days"],39)
        self.assertFalse(compare_forward(account(),incumbent)["replace"])

    def test_gapped_candles_are_rejected(self):
        frame=pd.DataFrame({"Open":[1,1],"High":[1,1],"Low":[1,1],"Close":[1,1],"Volume":[100,100]},
            index=pd.to_datetime(["2025-01-01T00:00Z","2025-01-01T00:30Z"]))
        with self.assertRaises(ValueError):features(frame)

    def test_prospective_holdout_is_frozen_and_not_read_early(self):
        import research_lab_worker as worker
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            reg=Registry(str(root/"registry.sqlite"))
            prior=pd.Timestamp.now(tz="UTC").floor("D")
            reg.put("experiment","legacy",{"status":"completed","end":prior.isoformat(),"holdout":{}})
            result={"net_pnl":1,"expectancy":.1,"profit_factor":2,"trades":50,"max_drawdown_pct":1}
            with patch.object(worker,"ROOT",root),patch.object(worker,"historical",return_value=(pd.DataFrame(),{})),patch.object(worker,"features",return_value=pd.DataFrame()),patch.object(worker,"simulate",return_value=result) as replay:
                worker.research(reg,["BTCUSDT","ETHUSDT","SOLUSDT"])
                key=reg.get("state","active_experiment")
                plan=reg.get("experiment",key)
                self.assertEqual(plan["status"],"awaiting_fresh_holdout")
                self.assertGreater(pd.Timestamp(plan["holdout_start"]),pd.Timestamp(plan["frozen_at"]))
                self.assertTrue(all(call.args[3]<pd.Timestamp(plan["holdout_start"]) for call in replay.call_args_list))
                count=replay.call_count
                worker.research(reg,["SOMETHINGELSE"])
                self.assertEqual(replay.call_count,count)
                self.assertEqual(reg.get("experiment",key)["universe"],plan["universe"])
                plan["validation"]["net_pnl"]=-1
                reg.put("experiment",key,plan)
                worker.research(reg,["BTCUSDT"])
                self.assertEqual(reg.get("experiment",key)["status"],"rejected_validation")
                self.assertEqual(holdout_watermark(reg),prior)
            reg.db.close()

    def test_wider_spread_worsens_paper_return(self):
        c=Candidate("channel_breakout",hold_bars=4)
        narrow,wide=account(),account()
        for i,stamp in enumerate(pd.date_range("2025-01-01",periods=4,freq="15min",tz="UTC")):
            bars={"X":{"Open":100,"High":100,"Low":100,"Close":100}}
            advance(narrow,c,bars,{"X":i==0},stamp,spread=0)
            advance(wide,c,bars,{"X":i==0},stamp,spread=.002)
        self.assertLess(wide["equity"],narrow["equity"])

    def test_daily_loss_cache_blocks_new_entries(self):
        state=account()
        c=Candidate("channel_breakout")
        for stamp in pd.date_range("2025-01-01",periods=30,freq="15min",tz="UTC"):
            advance(state,c,{"X":{"Open":100,"High":110,"Low":90,"Close":100}},{"X":True},stamp)
        self.assertLessEqual(state["realized_days"]["2025-01-01"],-10)
        self.assertLess(len(state["trades"]),30)
        self.assertAlmostEqual(sum(t["pnl_usd"] for t in state["trades"]),state["realized_days"]["2025-01-01"])

    def test_tournament_can_replace_older_higher_lifetime_profit(self):
        import research_lab_worker as worker
        with tempfile.TemporaryDirectory() as folder:
            reg=Registry(str(Path(folder)/"registry.sqlite"))
            incumbent,challenger=Candidate("channel_breakout"),Candidate("vwap_reclaim")
            dates=pd.date_range("2025-01-01",periods=301,freq="15min",tz="UTC")
            raw=[[int(t.timestamp()*1000),100,101,99,100,100000] for t in dates]
            pool={}
            for c,status in ((incumbent,"champion"),(challenger,"challenger")):
                s=account();s["seen"]["BTCUSDT"]=dates[-2].isoformat()
                pool[c.id]={"candidate":worker.asdict_candidate(c),"status":status,"account":s}
            reg.put("state","tournament",pool);reg.put("state","champion",incumbent.id)
            scores=[{"eligible":True,"net_pnl":1000,"max_drawdown_pct":1},{"eligible":True,"net_pnl":100,"max_drawdown_pct":1}]
            with patch.object(worker,"public",return_value=raw),patch.object(worker,"forward_gate",side_effect=scores),patch.object(worker,"compare_forward",return_value={"replace":True,"mean_daily_excess_return":.001}):
                result=worker.tournament_cycle(reg,["BTCUSDT"])
            self.assertEqual(result["champion"],challenger.id)
            reg.db.close()


if __name__=="__main__":unittest.main()
