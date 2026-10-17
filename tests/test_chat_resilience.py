import unittest
from unittest.mock import Mock, patch
from engine.telegram_worker import TelegramWorker
from engine.ai_chat import chat_with_gemini
from engine.gemini_config import generate


class ChatResilienceTests(unittest.TestCase):
    def worker(self):
        w = TelegramWorker.__new__(TelegramWorker)
        w.allowed_chat = "123"
        w.send = Mock()
        w.send_portfolio = Mock()
        w.market_context = Mock(return_value={})
        return w

    def test_natural_portfolio_uses_ai_primary(self):
        w = self.worker()
        with patch("engine.telegram_worker.chat_with_gemini", return_value="AI answer") as ai:
            w.handle({"chat": {"id": 123}, "text": "gimana portoku?"})
            w.send_portfolio.assert_not_called()
            ai.assert_called_once()

    def test_natural_text_not_used_as_symbol_and_context_retained(self):
        w = self.worker()
        with patch("engine.telegram_worker.chat_with_gemini", return_value="test") as ai:
            w.handle({"chat": {"id": 123}, "text": "kenapa portoku rugi?"})
            w.market_context.assert_called_with("BTCUSDT")
            w.handle({"chat": {"id": 123}, "text": "jelaskan lagi"})
            self.assertEqual(len(ai.call_args.args[1]["recent_conversation"]), 1)

    def test_503_retried_then_success(self):
        with patch("engine.gemini_config.requests.post", side_effect=[Mock(status_code=503), Mock(status_code=200)]) as post, patch("engine.gemini_config.time.sleep"):
            self.assertEqual(generate({}, "fake", record_diagnostics=False).status_code, 200)
            self.assertEqual(post.call_count, 2)

    def test_404_not_retried(self):
        with patch("engine.gemini_config.requests.post", return_value=Mock(status_code=404)) as post:
            self.assertEqual(generate({}, "fake", record_diagnostics=False).status_code, 404)
            self.assertEqual(post.call_count, 1)

    def test_persistent_503_returns_labeled_paper_fallback(self):
        with patch.dict("os.environ", {"GEMINI_API_KEY": "fake"}), patch("engine.gemini_config.requests.post", return_value=Mock(status_code=503)) as post, patch("engine.gemini_config.time.sleep"), patch("engine.gemini_config._record"):
            answer = chat_with_gemini("kenapa rugi", {"portfolio": {"equity": 998, "net_pnl_usd": -2, "open_positions_count": 1}})
            self.assertIn("998.00", answer)
            self.assertIn("bukan analisis AI", answer)
            self.assertEqual(post.call_count, 4)

    def test_failure_is_not_added_to_conversation(self):
        w = self.worker()
        with patch("engine.telegram_worker.chat_with_gemini", return_value="Gemini sedang terganggu setelah percobaan ulang."):
            w.handle({"chat": {"id": 123}, "text": "bahas portoku"})
        self.assertEqual(getattr(w, "conversation", []), [])
