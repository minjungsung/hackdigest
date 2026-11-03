from contextlib import redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from building_monitor.deployment import main, prepare_config, status_email, waiting_report


class DeploymentTests(unittest.TestCase):
    def prepare(self, base):
        (base / "examples").mkdir()
        (base / "examples/reviews.csv").write_text("source,listing_id,property_id\n")
        (base / "config.example.json").write_text(json.dumps({"feeds": [], "email": {}}))

    def test_existing_mail_secrets_are_used_without_extracting_or_saving_them(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"EMAIL_FROM": "sender@example.test", "EMAIL_APP_PASSWORD": "example-only"}, clear=True):
            base = Path(directory)
            self.prepare(base)
            config = prepare_config(base)
            self.assertEqual(config["email"]["password_env"], "EMAIL_APP_PASSWORD")
            self.assertEqual(os.environ["SMTP_USERNAME"], "sender@example.test")
            self.assertNotIn("example-only", json.dumps(config))

    def test_missing_key_is_explicitly_reported_as_not_monitoring(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True), redirect_stdout(StringIO()):
            base = Path(directory)
            self.prepare(base)
            with patch("sys.argv", ["deployment", "--base", directory]):
                self.assertEqual(main(), 0)
            report = json.loads((base / "data/cloud/health.json").read_text())
            self.assertEqual(report["collection_status"], "awaiting_onbid_credentials")
            email = status_email(report, {"feeds": []})
            self.assertIn("Listing monitoring has NOT started", email.get_content())

    def test_private_supplier_and_review_inputs_are_configured_from_environment(self):
        env = {"BUILDING_FEED_URL": "https://supplier.example/feed", "BUILDING_FEED_TOKEN": "example-token",
               "BUILDING_REVIEWS_CSV": "source,listing_id,property_id\nbroker-feed,demo,property-demo\n"}
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, env, clear=True):
            base = Path(directory)
            self.prepare(base)
            config = prepare_config(base)
            self.assertEqual(config["feeds"][0]["token_env"], "BUILDING_FEED_TOKEN")
            self.assertEqual((base / "data/cloud/reviews.csv").read_text(), env["BUILDING_REVIEWS_CSV"])


if __name__ == "__main__":
    unittest.main()
