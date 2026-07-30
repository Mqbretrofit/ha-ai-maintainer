import sys
from pathlib import Path
import unittest

APP_PATH = Path(__file__).parents[1] / "ha_ai_maintainer" / "app"
sys.path.insert(0, str(APP_PATH))

from redaction import redact_text


class RedactionTests(unittest.TestCase):
    def test_redacts_credentials_and_addresses(self) -> None:
        value = (
            "api_key=sk-example0123456789 email=user@example.com "
            "host=192.168.1.25 latitude=47.12345"
        )
        redacted, count = redact_text(value)
        self.assertNotIn("sk-example0123456789", redacted)
        self.assertNotIn("user@example.com", redacted)
        self.assertNotIn("192.168.1.25", redacted)
        self.assertNotIn("47.12345", redacted)
        self.assertGreaterEqual(count, 4)

    def test_preserves_normal_log_text(self) -> None:
        value = "ERROR integration failed to load after restart"
        redacted, count = redact_text(value)
        self.assertEqual(value, redacted)
        self.assertEqual(0, count)


if __name__ == "__main__":
    unittest.main()
