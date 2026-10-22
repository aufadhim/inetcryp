import json
import tempfile
import unittest
from pathlib import Path
from datetime import datetime,timezone,timedelta
from engine.research_lab import Registry
from engine.opportunity_radar import record,evaluate,collect
from engine.online_learning import cycle,connect,get_model


class RadarTests(unittest.TestCase):
    def test_collection_uses_receipt_time_not_request_start(self):
        def public(path):
            if path=="exchangeInfo":return {"symbols":[{"symbol":s,"baseAsset":s[:-4],"quoteAsset":"USDT","status":"TRADING","isSpotTradingAllowed":True} for s in ("XUSDT","YUSDT")]}
            return [{"symbol":s,"lastPrice":"100","quoteVolume":"10000000","count":"6000","priceChangePercent":"4",
                     "closeTime":datetime.now(timezone.utc).timestamp()*1000} for s in ("XUSDT","YUSDT")]
        result=collect(self.reg,public,[])
        self.assertEqual(len(result["binance"]),2)

    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.reg=Registry(str(Path(self.folder.name)/"radar.sqlite"))
        self.now=datetime(2026,1,1,tzinfo=timezone.utc)

    def tearDown(self):
        self.reg.db.close();self.folder.cleanup()

    def test_first_detection_not_overwritten_and_losses_retained(self):
        self.assertTrue(record(self.reg,"binance","XUSDT",100,self.now,{}))
        self.assertFalse(record(self.reg,"binance","XUSDT",150,self.now+timedelta(minutes=10),{}))
        evaluate(self.reg,{"binance:XUSDT":90},self.now+timedelta(minutes=30))
        row=self.reg.get("radar_call","binance:XUSDT:2026-01-01")
        self.assertEqual(row["reference_price"],100)
        self.assertAlmostEqual(row["outcomes"]["30m"]["gross_change_pct"],-10)
        self.assertFalse(row["paper_admission"])

    def test_early_or_late_price_never_fabricates_horizon_result(self):
        record(self.reg,"binance","XUSDT",100,self.now,{})
        evaluate(self.reg,{"binance:XUSDT":200},self.now+timedelta(minutes=20))
        key="binance:XUSDT:2026-01-01"
        self.assertEqual(self.reg.get("radar_call",key)["outcomes"],{})
        evaluate(self.reg,{"binance:XUSDT":200},self.now+timedelta(minutes=41))
        self.assertEqual(self.reg.get("radar_call",key)["outcomes"]["30m"]["status"],"missed_no_reconstruction")

    def test_dex_is_chain_pair_identified_and_net_profit_unknown(self):
        for identity in ("solana:poolA","ethereum:poolA"):
            record(self.reg,"dex",identity,1,self.now,{})
        evaluate(self.reg,{"dex:solana:poolA":2},self.now+timedelta(minutes=30))
        row=self.reg.get("radar_call","dex:solana:poolA:2026-01-01")
        self.assertIsNone(row["outcomes"]["30m"]["estimated_net_pct"])
        self.assertEqual(self.reg.get("radar_call","dex:ethereum:poolA:2026-01-01")["outcomes"],{})

    def test_dynamic_selection_is_frozen_and_uses_separate_database(self):
        root=Path(self.folder.name)
        path=root/"opportunity-radar.json"
        def snapshot(symbol):
            path.write_text(json.dumps({"as_of":"2026-01-01T00:00Z","binance":[{"symbol":"BTCUSDT"},{"symbol":symbol}]}),encoding="utf-8")
        seen=[]
        def public(path,**params):
            seen.append(params["symbol"])
            raise ValueError("No live network in test")
        snapshot("XUSDT")
        cycle(public,root,now="2026-01-01T00:00:10Z",radar=True)
        snapshot("YUSDT")
        cycle(public,root,now="2026-01-01T00:00:20Z",radar=True)
        self.assertEqual(seen,["XUSDT","XUSDT"])
        self.assertTrue((root/"online-radar-learning.sqlite").exists())
        self.assertFalse((root/"online-learning.sqlite").exists())

    def test_stale_radar_cannot_issue_dynamic_predictions(self):
        root=Path(self.folder.name)
        (root/"opportunity-radar.json").write_text(json.dumps({"as_of":"2025-12-31T00:00Z","binance":[{"symbol":"XUSDT"}]}),encoding="utf-8")
        def public(*args,**kwargs):raise AssertionError("Must not call network")
        result=cycle(public,root,now="2026-01-01T00:00Z",radar=True)
        self.assertEqual(result["errors"],[])
        self.assertEqual(result["trained_labels"],0)
