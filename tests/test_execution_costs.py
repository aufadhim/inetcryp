import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from engine.execution_costs import break_even_exit,target_cost_budget
from engine.commission_audit import commission_rates,audit_commissions
from engine.research_lab import account,advance,Candidate
from engine.observed_paper import observed_step


class ExecutionCostTests(unittest.TestCase):
    def test_production_commission_does_not_change_trading_mode(self):
        from engine.binance_client import BinanceClient
        client=object.__new__(BinanceClient)
        client.mode="testnet"
        with patch.object(BinanceClient,"_request",autospec=True,return_value={}) as request:
            client.get_account_commission("BTCUSDT",production_read_only=True)
            self.assertEqual(request.call_args.args[0].mode,"live")
            self.assertEqual(request.call_args.args[1:3],("GET","/api/v3/account/commission"))
        self.assertEqual(client.mode,"testnet")

    def test_commission_client_only_calls_signed_get_user_data(self):
        from engine.binance_client import BinanceClient
        client=object.__new__(BinanceClient)
        client._request=Mock(return_value={})
        client.get_account_commission("BTCUSDT")
        client._request.assert_called_once_with("GET","/api/v3/account/commission",{"symbol":"BTCUSDT","recvWindow":5000},signed=True)
        with self.assertRaises(ValueError):client.get_account_commission("../orders")

    def test_net_break_even_includes_both_fees_and_sell_slippage(self):
        quantity=50/1.001/(100*1.0005)
        price=break_even_exit(50,quantity,.001,.0005,net_buffer_pct=.1)
        self.assertGreater(price,100.1)
        self.assertAlmostEqual(quantity*price*(1-.001)*(1-.0005),50.05)

    def test_commission_includes_side_and_tax_without_assuming_bnb_balance(self):
        payload={"standardCommission":{"maker":".001","taker":".002","buyer":".0001","seller":".0002"},
                 "taxCommission":{"taker":".0003"},"specialCommission":{"seller":".0004"},
                 "discount":{"enabledForAccount":True,"enabledForSymbol":True}}
        r=commission_rates(payload)
        self.assertAlmostEqual(r["undiscounted_rates"]["taker_sell"],.0029)
        self.assertAlmostEqual(r["undiscounted_rates"]["maker_buy"],.0011)
        self.assertTrue(r["bnb_discount_enabled"])

    def test_fee_audit_unavailable_and_testnet_never_claims_live_verified(self):
        client=SimpleNamespace(mode="testnet",get_account_commission=Mock(return_value=None))
        result=audit_commissions(client,["BTCUSDT"])
        self.assertEqual(result["status"],"incomplete")
        self.assertEqual(result["configured_trading_mode"],"testnet")
        self.assertEqual(result["mode"],"production_read_only")
        self.assertEqual(result["symbols"]["BTCUSDT"]["status"],"unavailable")

    def test_historical_and_observed_reject_insufficient_target_cost_budget(self):
        c=Candidate("channel_breakout",target_pct=1)
        s=account()
        advance(s,c,{"X":{"Open":100,"High":100,"Low":100,"Close":100}},
                {"X":True},"2026-01-01T00:00Z",cost_guard=True)
        self.assertFalse(s["positions"])
        o=account()
        observed_step(o,c,{"X":{"signal":True,"candle_at":"2026-01-01T00:00Z",
            "book":{"bids":[[99.85,100]],"asks":[[100,100]],"received_at":"2026-01-01T00:15:20Z","latency_ms":10}}},now="2026-01-01T00:15:20Z")
        self.assertFalse(o["positions"])

    def test_equal_flat_quotes_and_fees_have_equal_marked_equity(self):
        c=Candidate("channel_breakout")
        s=account()
        advance(s,c,{"X":{"Open":100,"High":100,"Low":100,"Close":100}},
                {"X":True},"2026-01-01T00:00Z",slip=0,spread=0,cost_guard=True)
        o=account()
        observed_step(o,c,{"X":{"signal":True,"candle_at":"2026-01-01T00:00Z",
            "book":{"bids":[[100,100]],"asks":[[100,100]],"received_at":"2026-01-01T00:15:20Z","latency_ms":10}}},now="2026-01-01T00:15:20Z")
        self.assertAlmostEqual(s["equity"],o["equity"])
        self.assertAlmostEqual(s["positions"]["X"]["quantity"],o["positions"]["X"]["quantity"])
