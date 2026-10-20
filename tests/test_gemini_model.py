import unittest
from unittest.mock import patch, Mock
from engine.ai_chat import chat_with_gemini
from engine.ai_analyst import analyze_with_gemini


class GeminiModelTests(unittest.TestCase):
    def setUp(self):
        recorder = patch("engine.gemini_config._record")
        recorder.start()
        self.addCleanup(recorder.stop)

    def test_both_paths_use_requested_model_and_header(self):
        response = Mock(status_code=200)
        response.json.return_value = {"candidates": [{"content": {"parts": [{"text": "internal", "thought": True}, {"text": "OK"}]}}]}
        with patch.dict("os.environ", {"GEMINI_API_KEY": "fake-test-key"}):
            with patch("requests.post", return_value=response) as post:
                self.assertEqual(chat_with_gemini("test", {}), "OK")
                self.assertEqual(analyze_with_gemini("BTCUSDT", {}), "OK")
                for call in post.call_args_list:
                    self.assertTrue(call.args[0].endswith("gemini-3.6-flash:generateContent"))
                    self.assertNotIn("fake-test-key", call.args[0])
                    self.assertEqual(call.kwargs["headers"]["x-goog-api-key"], "fake-test-key")

    def test_exception_does_not_expose_request(self):
        with patch.dict("os.environ", {"GEMINI_API_KEY": "fake-test-key"}):
            with patch("requests.post", side_effect=RuntimeError("fake-test-key")):
                self.assertNotIn("fake-test-key", analyze_with_gemini("BTCUSDT", {}))
                self.assertNotIn("fake-test-key", chat_with_gemini("test", {}))
