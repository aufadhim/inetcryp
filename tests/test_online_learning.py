import tempfile
import unittest
import json
from pathlib import Path
from engine.online_learning import connect,issue,settle,get_model,summary,probability,DIM,cycle


class OnlineLearningTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.db=connect(Path(self.folder.name)/"online.sqlite")
        self.x=[1.0]+[0.0]*(DIM-1)

    def tearDown(self):
        self.db.close();self.folder.cleanup()

    def book(self,at,bid=100,ask=100.01):
        return {"bids":[[bid,100]],"asks":[[ask,100]],"received_at":at,"latency_ms":10}

    def issue(self):
        return issue(self.db,"BTCUSDT","2026-01-01T00:00Z",self.x,self.book("2026-01-01T00:00:10Z"),"2026-01-01T00:00:10Z")

    def pending(self):return self.db.execute("SELECT * FROM predictions").fetchone()

    def test_predict_before_learn_and_duplicate_issue_is_ignored(self):
        self.assertTrue(self.issue());self.assertFalse(self.issue())
        self.assertEqual(get_model(self.db)["labels"],0)
        self.assertEqual(json.loads(self.pending()["payload"])["probability"],.5)

    def test_early_result_cannot_train_model(self):
        self.issue()
        self.assertFalse(settle(self.db,self.pending(),self.book("2026-01-01T00:10Z",101,101.01),"2026-01-01T00:10Z"))
        self.assertEqual(get_model(self.db)["labels"],0)

    def test_exactly_once_learning_persists_and_scores_original_prediction(self):
        self.issue();row=self.pending()
        book=self.book("2026-01-01T00:30:20Z",101,101.01)
        self.assertTrue(settle(self.db,row,book,"2026-01-01T00:30:20Z"))
        self.assertFalse(settle(self.db,row,book,"2026-01-01T00:30:20Z"))
        model=get_model(self.db)
        self.assertEqual(model["labels"],1)
        self.assertGreater(probability(model["weights"],self.x),.5)
        payload=json.loads(self.pending()["payload"])
        self.assertEqual(payload["brier"],.25)
        self.assertEqual(payload["probability"],.5)
        self.assertEqual(payload["label"],1)
        self.db.close();self.db=connect(Path(self.folder.name)/"online.sqlite")
        self.assertEqual(get_model(self.db)["labels"],1)

    def test_price_rise_smaller_than_fees_is_negative_label(self):
        self.issue()
        settle(self.db,self.pending(),self.book("2026-01-01T00:30:20Z",100.05,100.06),"2026-01-01T00:30:20Z")
        payload=json.loads(self.pending()["payload"])
        self.assertEqual(payload["label"],0)
        self.assertLess(payload["net_pnl_50"],0)

    def test_stale_quote_and_late_outcome_never_train(self):
        self.issue();row=self.pending()
        self.assertFalse(settle(self.db,row,self.book("2026-01-01T00:20Z",101,101.01),"2026-01-01T00:30:20Z"))
        self.assertTrue(settle(self.db,row,self.book("2026-01-01T00:40Z",101,101.01),"2026-01-01T00:40Z"))
        self.assertEqual(get_model(self.db)["labels"],0)
        self.assertEqual(self.pending()["status"],"late_discarded")

    def test_no_retrospective_entry_and_no_promotion_during_warmup(self):
        self.assertFalse(issue(self.db,"BTCUSDT","2026-01-01T00:00Z",self.x,self.book("2026-01-01T00:10Z"),"2026-01-01T00:10Z"))
        result=summary(self.db,"2026-01-01T00:10Z")
        self.assertFalse(result["review_ready"])
        self.assertFalse(result["paper_admission"])
        self.assertFalse(result["live_trading"])

    def test_invalid_vector_and_fees_cannot_poison_model(self):
        with self.assertRaises(ValueError):issue(self.db,"X","2026-01-01T00:00Z",[float("nan")]*DIM,self.book("2026-01-01T00:00Z"),"2026-01-01T00:00Z")

    def test_restart_discards_missed_deadlines_without_fetching_backlog(self):
        self.db.close();self.db=connect(Path(self.folder.name)/"online-learning.sqlite")
        self.issue()
        def no_network(*args,**kwargs):raise AssertionError("No historical settlement fetch allowed")
        result=cycle(no_network,self.folder.name,now="2026-01-01T00:40Z")
        self.assertEqual(result["counts"].get("late_discarded"),1)
        self.assertEqual(result["trained_labels"],0)
        self.assertEqual(result["errors"],[])
