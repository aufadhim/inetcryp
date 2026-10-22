import unittest
import tempfile
import json
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from engine.observed_paper import depth_fill,observed_step
from engine.research_lab import account,Candidate,features,signals
from engine.research_analysis import diagnose,benchmark_gate,baselines


class ObservedTests(unittest.TestCase):
    def observation(self,now="2025-01-01T00:15:20Z",bid=99.99,ask=100):
        return {"X":{"signal":True,"candle_at":"2025-01-01T00:00:00Z","regime":"uptrend","volatility":"low",
            "book":{"received_at":now,"latency_ms":50,"bids":[[bid,100]],"asks":[[ask,100]]}}}

    def test_fill_uses_observed_ask_not_historical_open(self):
        s=account();obs=self.observation(bid=109.99,ask=110)
        events=observed_step(s,Candidate("channel_breakout"),obs,now="2025-01-01T00:15:20Z")
        self.assertEqual(s["positions"]["X"]["entry"],110)
        self.assertEqual(events[0]["decision_at"],"2025-01-01T00:15:20+00:00")
        self.assertLess(s["equity"],1000)

    def test_stale_quote_and_late_signal_do_not_create_fills(self):
        s=account()
        events=observed_step(s,Candidate("channel_breakout"),self.observation(),now="2025-01-01T00:20:00Z")
        self.assertFalse(s["positions"]);self.assertEqual(events[0]["reason"],"stale_or_invalid_quote")
        events=observed_step(s,Candidate("channel_breakout"),self.observation(now="2025-01-01T00:20:00Z"),now="2025-01-01T00:20:00Z")
        self.assertEqual(events[0]["reason"],"late_signal")

    def test_observed_stop_executes_at_current_bid(self):
        s=account();c=Candidate("channel_breakout")
        observed_step(s,c,self.observation(),now="2025-01-01T00:15:20Z")
        observed_step(s,c,self.observation(now="2025-01-01T00:16:00Z",bid=80,ask=80.01),now="2025-01-01T00:16:00Z")
        self.assertFalse(s["positions"])
        self.assertEqual(s["trades"][0]["exit_price"],80)
        self.assertLess(s["trades"][0]["pnl_usd"],-10)

    def test_cost_budget_blocks_expensive_small_target(self):
        s=account()
        events=observed_step(s,Candidate("channel_breakout",target_pct=1),self.observation(bid=99.85),now="2025-01-01T00:15:20Z")
        self.assertFalse(s["positions"])
        self.assertEqual(events[0]["reason"],"insufficient_target_cost_budget")

    def test_insufficient_depth_cannot_fabricate_fill(self):
        self.assertIsNone(depth_fill([[100,.01]],quote=50))
        fill=depth_fill([[100,.1],[101,1]],quote=50)
        self.assertGreater(fill["price"],100)

    def test_missing_position_quote_blocks_complete_valuation(self):
        s=account();c=Candidate("channel_breakout")
        observed_step(s,c,self.observation(),now="2025-01-01T00:15:20Z")
        observed_step(s,c,{},now="2025-01-01T00:15:50Z")
        self.assertFalse(s["valuation_complete"])

    def test_diagnosis_distinguishes_cost_flip_and_unknown_legacy_cost(self):
        report=diagnose([{"symbol":"X","pnl_usd":-.2,"gross_pnl_usd":.1,"reason":"stop","entry_regime":"range"},
                         {"symbol":"Y","pnl_usd":-1,"reason":"time_stop"}])
        self.assertEqual(report["cost_flipped_winners"],1)
        self.assertIsNone(report["groups"]["symbol"]["Y"]["estimated_cost_drag"])
        self.assertFalse(report["groups"]["symbol"]["X"]["sample_sufficient"])

    def test_profitable_strategy_can_fail_baseline_gate(self):
        result={"net_pnl":10,"max_drawdown_pct":5}
        baseline={"cash":{"net_pnl":0},"ema_cross":{"net_pnl":20},"buy_hold_capped":{"net_pnl":30,"max_drawdown_pct":3}}
        self.assertFalse(benchmark_gate(result,baseline)["eligible"])

    def test_adaptive_mean_reversion_cannot_enter_downtrend(self):
        close=pd.Series([150-i*.1 for i in range(150)],index=pd.date_range("2025-01-01",periods=150,freq="15min",tz="UTC"))
        frame=features(pd.DataFrame({"Open":close,"High":close+.1,"Low":close-.1,"Close":close,"Volume":100000}))
        frame.loc[frame.index[-2],"rsi"]=20;frame.loc[frame.index[-1],"rsi"]=35
        frame.loc[frame.index[-1],"rvol"]=2;frame.loc[frame.index[-1],"Close"]=frame.iloc[-2].Close+.01
        self.assertEqual(frame.iloc[-1].regime,"downtrend")
        self.assertFalse(signals(frame,Candidate("rsi_reversion"))[-1])
        self.assertTrue(signals(frame,Candidate("rsi_reversion",regime_filter="off"))[-1])

    def test_monitor_does_not_call_research_or_collector(self):
        import research_lab_worker as worker
        from engine.research_lab import Registry
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            def registry():return Registry(str(root/"registry.sqlite"))
            with patch.object(worker,"ROOT",root),patch.object(worker,"Registry",side_effect=registry),patch.object(worker,"universe",return_value=["BTCUSDT"]),patch.object(worker,"tournament_cycle",return_value={"accounts":[]}),patch.object(worker,"research") as heavy,patch("engine.research_data.collect_sources") as collect:
                worker.main(once=True,role="monitor")
            heavy.assert_not_called();collect.assert_not_called()
            self.assertEqual(json.loads((root/"monitor_status.json").read_text())["status"],"sleeping")


if __name__=="__main__":unittest.main()
