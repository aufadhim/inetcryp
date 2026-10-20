import tempfile
import json
import unittest
from unittest.mock import patch, Mock
from pathlib import Path
import numpy as np
import pandas as pd
from engine.research_lab import Candidate, Registry, account, advance, candidates, features, signals, simulate, research_gate, forward_gate


class LabTests(unittest.TestCase):
    def frame(self):
        close = 100 + np.sin(np.arange(300)/5)*2 + np.arange(300)*.02
        return pd.DataFrame({"Open":close,"Close":close,"High":close+1,"Low":close-1,"Volume":100000},
            index=pd.date_range("2025-01-01",periods=300,freq="15min",tz="UTC"))

    def test_future_cannot_change_previous_signals(self):
        raw = self.frame()
        changed = raw.copy()
        changed.iloc[200:,changed.columns.get_loc("Close")] *= 2
        changed.iloc[200:,changed.columns.get_loc("High")] *= 3
        for c in candidates():
            np.testing.assert_array_equal(signals(features(raw),c)[:200],signals(features(changed),c)[:200])

    def test_stop_wins_and_duplicate_bar_is_ignored(self):
        c=Candidate("channel_breakout")
        s=account()
        bar={"Open":100,"High":110,"Low":90,"Close":100}
        advance(s,c,{"BTCUSDT":bar},{"BTCUSDT":True},"2025-01-01T00:00Z")
        self.assertEqual(s["trades"][0]["reason"],"stop")
        self.assertLess(s["equity"],999.25)  # $50 x 1.5% stop plus round-trip costs.
        advance(s,c,{"BTCUSDT":bar},{"BTCUSDT":True},"2025-01-01T00:00Z")
        self.assertEqual(len(s["trades"]),1)

    def test_gap_uses_observed_open(self):
        c=Candidate("channel_breakout")
        s=account()
        advance(s,c,{"X":{"Open":100,"High":100,"Low":100,"Close":100}},{"X":True},"2025-01-01T00:00Z")
        advance(s,c,{"X":{"Open":80,"High":81,"Low":79,"Close":80}},{},"2025-01-01T00:15Z")
        self.assertEqual(s["trades"][0]["reason"],"gap_stop")
        self.assertLess(s["trades"][0]["pnl_usd"],-10)

    def test_gate_rejects_thin_or_losing_samples(self):
        weak={"net_pnl":1,"expectancy":.1,"profit_factor":2,"trades":2,"max_drawdown_pct":1}
        self.assertFalse(research_gate(weak,weak,weak,[weak]*3,[weak]*3)["eligible"])
        self.assertFalse(forward_gate(account())["eligible"])

    def test_forward_gate_requires_actual_observation_coverage(self):
        s=account()
        s.update(first_at="2025-01-01T00:00:00Z",last_at="2025-02-02T00:00:00Z",equity=1100,execution_model="observed_depth_v1",valuation_complete=True)
        s["trades"]=[{"symbol":str(i%3),"pnl_usd":.5} for i in range(210)]
        self.assertFalse(forward_gate(s)["eligible"])
        s["observed_steps"]=32*96+1
        self.assertTrue(forward_gate(s)["eligible"])

    def test_registry_persists_and_rejects_unknown_strategy(self):
        with tempfile.TemporaryDirectory() as folder:
            r=Registry(str(Path(folder)/"registry.sqlite"))
            r.put("x","id",{"ok":True})
            self.assertEqual(r.get("x","id"),{"ok":True})
            r.db.close()
        with self.assertRaises(ValueError):
            Candidate("arbitrary_python").validate()

    def test_gemini_proposal_is_bounded_and_does_not_promote(self):
        import research_lab_worker as worker
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/"research-latest.json").write_text(json.dumps({"id":"experiment"}),encoding="utf-8")
            r=Registry(str(root/"registry.sqlite"))
            text=json.dumps({"analysis":"test","hypotheses":[{"family":"channel_breakout","stop_pct":1.5,"target_pct":3,"hold_bars":16,"volume_ratio":1.5}]})
            response=Mock(status_code=200)
            response.json.return_value={"candidates":[{"content":{"parts":[{"text":text}]}}]}
            with patch.object(worker,"ROOT",root),patch.dict("os.environ",{"GEMINI_API_KEY":"fake"}),patch("engine.gemini_config.generate",return_value=response):
                result=worker.adviser(r)
            self.assertEqual(result["status"],"bounded_proposals_for_next_epoch")
            self.assertIsNone(r.get("state","champion"))
            self.assertEqual(len(r.get("state","proposals")),1)
            r.db.close()

    def test_historical_matches_paper_step(self):
        f=features(self.frame())
        c=Candidate("channel_breakout")
        mask=np.zeros(len(f),dtype=bool)
        mask[[110,140,170]]=True
        with patch("engine.research_lab.signals",return_value=mask):
            result=simulate({"X":f},c,f.index[100],f.index[-1]+pd.Timedelta(minutes=15))
        s=account()
        for i in range(100,len(f)):
            bar=f.iloc[i].to_dict()
            bar["decision_quote_volume"]=float(f.iloc[i-1].Close*f.iloc[i-1].Volume)
            advance(s,c,{"X":bar},{"X":bool(mask[i-1])},f.index[i])
        self.assertGreater(len(s["trades"]),0)
        self.assertAlmostEqual(result["equity"],s["equity"],places=3)


if __name__=="__main__":
    unittest.main()
