import unittest
import pandas as pd
from unittest.mock import Mock
from engine.dynamic_universe import shortlist, liquidity
from engine.paper_trader import CryptoPaperTrader


class UniverseTests(unittest.TestCase):
    def info(self, **changes):
        item = dict(symbol="PEPEUSDT", baseAsset="PEPE", quoteAsset="USDT", status="TRADING", isSpotTradingAllowed=True)
        item.update(changes)
        return {"symbols": [item]}

    def ticker(self, **changes):
        item = dict(symbol="PEPEUSDT", quoteVolume="10000000", priceChangePercent="8", count="10000", lastPrice="0.00001", closeTime=1000000)
        item.update(changes)
        return [item]

    def test_memecoin_eligible_without_whitelist(self):
        self.assertEqual(shortlist(self.info(), self.ticker(), 1000000)[0]["symbol"], "PEPEUSDT")

    def test_reject_risk_and_stale_data(self):
        for changes in ({"quoteVolume": "1000"}, {"priceChangePercent": "40"},
                        {"lastPrice": "nan"}, {"closeTime": 0}, {"count": "2"}, {"priceChangePercent": "-2"}):
            self.assertFalse(shortlist(self.info(), self.ticker(**changes), 1000000))

    def test_only_active_spot_nonstable(self):
        for changes in ({"status": "BREAK"}, {"isSpotTradingAllowed": False},
                        {"quoteAsset": "BTC"}, {"baseAsset": "USDC"}):
            self.assertFalse(shortlist(self.info(**changes), self.ticker(), 1000000))

    def test_spread_and_depth(self):
        self.assertIsNotNone(liquidity({"bids": [[100, 1000]], "asks": [[100.1, 1000]]}))
        self.assertIsNone(liquidity({"bids": [[100, 1]], "asks": [[100.1, 1]]}))
        self.assertIsNone(liquidity({"bids": [[100, 1000]], "asks": [[102, 1000]]}))
        self.assertIsNone(liquidity({"bids": [[102, 1000]], "asks": [[100, 1000]]}))

    def test_empty_selection_does_not_fall_back_to_fixed_symbols(self):
        client = Mock()
        trader = CryptoPaperTrader(client=client, persist=False)
        trader.run_eval_cycle([])
        client.get_klines.assert_not_called()

    def test_position_limit_blocks_new_scan(self):
        client = Mock()
        trader = CryptoPaperTrader(client=client, persist=False)
        trader.max_open_positions = 0
        trader.run_eval_cycle(["PEPEUSDT"])
        client.get_klines.assert_not_called()

    def test_empty_universe_still_manages_existing_position(self):
        client = Mock()
        client.get_klines.return_value = pd.DataFrame({"Close": [95.0, 95.0]})
        trader = CryptoPaperTrader(client=client, persist=False)
        trader.state["open_positions"]["OLDUSDT"] = dict(entry_price=100, size_usd=50,
            entry_time=trader.clock().isoformat(), stop_price=98)
        trader.run_eval_cycle([])
        self.assertFalse(trader.state["open_positions"])
        self.assertEqual(len(trader.state["history"]), 1)
