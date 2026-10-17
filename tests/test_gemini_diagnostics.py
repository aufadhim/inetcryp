import unittest
from unittest.mock import Mock, patch
from engine.gemini_config import generate


class GeminiDiagnosticsTests(unittest.TestCase):
    def test_safe_diagnostics_have_no_key_or_prompt(self):
        captured = []
        response = Mock(status_code=503)
        response.json.return_value = {"error": {"status": "UNAVAILABLE", "message": "secret upstream text"}}
        with patch("engine.gemini_config.requests.post", return_value=response), \
             patch("engine.gemini_config.time.sleep"), patch("engine.gemini_config._record", side_effect=captured.append):
            generate({"contents": [{"parts": [{"text": "private portfolio"}]}]}, "secret-key")
        self.assertEqual(len(captured), 1)
        rendered = str(captured[0])
        self.assertNotIn("secret-key", rendered)
        self.assertNotIn("private portfolio", rendered)
        self.assertNotIn("secret upstream text", rendered)
        self.assertEqual(captured[0]["api_error_status"], "UNAVAILABLE")
        self.assertEqual(captured[0]["attempts"], 4)
