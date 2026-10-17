import unittest
from engine.narrative_radar import terms, score_pair


class NarrativeRadarTests(unittest.TestCase):
    def test_terms_remove_generic_words(self):
        self.assertIn("anyps5", terms("AnyPS5 open source tool for Windows"))
        self.assertNotIn("source", terms("AnyPS5 open source tool"))

    def test_pair_scoring_flags_unverified_affiliation(self):
        pair = {"chainId":"solana", "dexId":"pumpfun", "pairAddress":"p",
            "baseToken":{"address":"mint", "name":"AnyPS5", "symbol":"ANYPS5"},
            "liquidity":{"usd":50000}, "volume":{"h24":120000},
            "txns":{"h24":{"buys":200,"sells":120}}, "pairCreatedAt":1_000_000,
            "fdv":500000}
        result = score_pair(pair, {"attention_score":80}, 1_000_000+24*3_600_000)
        self.assertGreater(result["score"], 50)
        self.assertFalse(result["official_affiliation"])
        self.assertIn("unverified_project_affiliation", result["risks"])


if __name__ == "__main__": unittest.main()
