import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
import research_lab_worker as worker
from engine.research_lab import Registry


class DailyResearchTests(unittest.TestCase):
    def test_review_separates_cost_from_latency_and_caches_results(self):
        with tempfile.TemporaryDirectory() as folder:
            reg=Registry(str(Path(folder)/"registry.sqlite"))
            score={"net_pnl":-2,"profit_factor":.8,"trades":40,"max_drawdown_pct":1}
            plan={"id":"daily-test","status":"completed","data_start":"2026-06-22T00:00:00Z",
                  "data_end":"2026-09-20T00:00:00Z","universe":["A","B","C"],
                  "results":[{"candidate":worker.asdict_candidate(worker.Candidate("vwap_reclaim")),"cost_latency_stress":score}]}
            with patch.object(worker,"ROOT",Path(folder)),patch.object(worker,"historical",return_value=(pd.DataFrame(),{})),patch.object(worker,"features",side_effect=lambda f:f),patch.object(worker,"simulate",return_value=score) as sim:
                result=worker.evaluate_daily(reg,plan)
                self.assertEqual(sim.call_count,6)
                self.assertEqual(sim.call_args_list[1].kwargs["cost"],2)
                self.assertNotIn("delay_bars",sim.call_args_list[1].kwargs)
                self.assertEqual(len(result["candidates"][0]["folds"]),3)
                self.assertEqual(result["worth_fresh_validation"],0)
                self.assertIn("negative_after_normal_costs",result["candidates"][0]["rejection_reasons"])
                self.assertFalse(result["paper_admission"])
                worker.evaluate_daily(reg,plan)
                self.assertEqual(sim.call_count,6)
            reg.db.close()

    def test_daily_budget_resume_and_holdout_isolation(self):
        with tempfile.TemporaryDirectory() as folder:
            reg=Registry(str(Path(folder)/"registry.sqlite"))
            frozen={"start":"2026-04-29T00:00:00Z","holdout_start":"2026-10-21T00:00:00Z"}
            reg.put("state","active_experiment","frozen")
            reg.put("experiment","frozen",frozen)
            reg.put("state","proposals",[{"family":"vwap_reclaim","target_pct":3.5}])
            score={"net_pnl":5,"profit_factor":1.5,"trades":40,"max_drawdown_pct":1}
            boundaries=[]
            def history(symbol,start,end,**kwargs):
                boundaries.append(end)
                return pd.DataFrame(),{}
            with patch.object(worker,"ROOT",Path(folder)),patch.object(worker,"historical",side_effect=history),patch.object(worker,"features",side_effect=lambda f:f),patch.object(worker,"simulate",return_value=score) as sim:
                first=worker.daily_research(reg,["A","B","C"],now="2026-10-21T05:00:00Z")
                self.assertEqual(first["status"],"completed")
                self.assertEqual(len(first["results"]),6)
                self.assertEqual(sim.call_count,12)
                self.assertTrue(all(t<=pd.Timestamp(frozen["start"])+pd.Timedelta(days=144) for t in boundaries))
                worker.daily_research(reg,["D"],now="2026-10-21T15:00:00Z")
                self.assertEqual(sim.call_count,12)
                worker.daily_research(reg,["A","B","C"],now="2026-10-21T17:01:00Z")
                self.assertEqual(sim.call_count,24)  # Midnight Jakarta starts a new daily budget.
            self.assertEqual(reg.get("experiment","frozen"),frozen)
            self.assertIsNone(reg.get("admission",first["best"]["candidate"]["id"]))
            reg.db.close()

    def test_insufficient_data_is_not_retried_every_five_minutes(self):
        with tempfile.TemporaryDirectory() as folder:
            reg=Registry(str(Path(folder)/"registry.sqlite"))
            reg.put("state","active_experiment","frozen")
            reg.put("experiment","frozen",{"start":"2026-04-29T00:00:00Z","holdout_start":"2026-10-21T00:00:00Z"})
            with patch.object(worker,"ROOT",Path(folder)),patch.object(worker,"historical",side_effect=RuntimeError) as history:
                result=worker.daily_research(reg,["A","B","C"],now="2026-10-21T05:00:00Z")
                self.assertEqual(result["status"],"insufficient_data")
                worker.daily_research(reg,["A","B","C"],now="2026-10-21T06:00:00Z")
                self.assertEqual(history.call_count,3)
            reg.db.close()
