import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
from engine.exit_research import paired_exits
from engine.research_lab import account,advance,Candidate


class ExitPolicyTests(unittest.TestCase):
    def test_paired_cohorts_reserve_identical_entry_windows(self):
        frame=pd.DataFrame({"Open":100.,"High":100.1,"Low":99.9,"Close":100.,"Volume":100000.,"regime":"range"},
            index=pd.date_range("2026-01-01",periods=180,freq="15min",tz="UTC"))
        with patch("engine.exit_research.signals",return_value=np.ones(len(frame),dtype=bool)):
            result=paired_exits({"X":frame},Candidate("vwap_reclaim",hold_bars=8),frame.index[0],frame.index[-1])
        self.assertGreater(len(result["pairs"]),0)
        for row in result["pairs"]:
            self.assertEqual(set(row["pnl"]),{"fixed","sl_plus","trailing"})
            self.assertAlmostEqual(row["pnl"]["fixed"],row["pnl"]["sl_plus"])
        stamps=[pd.Timestamp(r["entry_time"]) for r in result["pairs"]]
        self.assertTrue(all(b-a>=pd.Timedelta(minutes=120) for a,b in zip(stamps,stamps[1:])))
        self.assertFalse(result["paper_admission"])

    def step(self,state,t,op,high,low,close,policy="sl_plus"):
        advance(state,Candidate("vwap_reclaim",target_pct=8),{"X":{"Open":op,"High":high,"Low":low,"Close":close}},
                {"X":not state["positions"] and not state["trades"]},t,exit_policy=policy)

    def test_stop_activated_only_for_next_candle_and_covers_costs(self):
        s=account()
        self.step(s,"2026-01-01T00:00Z",100,101.2,99.8,101)
        self.assertFalse(s["trades"])
        stop=s["positions"]["X"]["protective_stop"]
        self.assertGreater(stop,100.1)
        self.step(s,"2026-01-01T00:15Z",101,101.1,100,100.5)
        self.assertGreater(s["trades"][0]["pnl_usd"],0)

    def test_intrabar_high_alone_does_not_activate_stop(self):
        s=account()
        self.step(s,"2026-01-01T00:00Z",100,102,99.8,100)
        self.assertNotIn("protective_stop",s["positions"]["X"])

    def test_gap_can_lose_even_after_sl_plus_armed(self):
        s=account()
        self.step(s,"2026-01-01T00:00Z",100,101.2,99.8,101)
        self.step(s,"2026-01-01T00:15Z",99,99.1,98,98.5)
        self.assertEqual(s["trades"][0]["reason"],"gap_stop")
        self.assertLess(s["trades"][0]["pnl_usd"],0)

    def test_fixed_never_raises_stop(self):
        s=account()
        self.step(s,"2026-01-01T00:00Z",100,102,99.8,101.5,"fixed")
        self.assertNotIn("protective_stop",s["positions"]["X"])

    def test_trailing_stop_never_moves_backwards(self):
        s=account()
        self.step(s,"2026-01-01T00:00Z",100,103,99.8,102,"trailing")
        stop=s["positions"]["X"]["protective_stop"]
        self.step(s,"2026-01-01T00:15Z",102,102.2,101.6,101.8,"trailing")
        self.assertGreaterEqual(s["positions"]["X"]["protective_stop"],stop)
