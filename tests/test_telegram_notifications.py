import logging
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from antimacro import load_telegram_credentials, send_telegram_photo


class TelegramNotificationTests(unittest.TestCase):
    def test_load_credentials_reads_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            env_path = Path(temporary_directory) / ".env"
            env_path.write_text(
                "TELEGRAM_BOT_TOKEN=file-token\nTELEGRAM_CHAT_ID=12345\n",
                encoding="utf-8-sig",
            )
            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(
                    load_telegram_credentials(env_path),
                    ("file-token", "12345"),
                )

    def test_send_photo_posts_multipart_to_telegram(self) -> None:
        response = Mock()
        response.json.return_value = {"ok": True}
        with tempfile.TemporaryDirectory() as temporary_directory:
            screenshot = Path(temporary_directory) / "capture.png"
            screenshot.write_bytes(b"png-data")

            with patch("antimacro.requests.post", return_value=response) as post:
                send_telegram_photo(screenshot, "test-token", "12345")

        args, kwargs = post.call_args
        self.assertEqual(
            args[0],
            "https://api.telegram.org/bottest-token/sendPhoto",
        )
        self.assertEqual(kwargs["data"]["chat_id"], "12345")
        self.assertEqual(kwargs["files"]["photo"][0], "capture.png")
        self.assertEqual(kwargs["files"]["photo"][2], "image/png")
        self.assertEqual(kwargs["timeout"], 15.0)
        response.raise_for_status.assert_called_once_with()

    def test_send_photo_logs_api_failure_without_raising(self) -> None:
        response = Mock()
        response.raise_for_status.side_effect = requests.HTTPError("rejected")
        with tempfile.TemporaryDirectory() as temporary_directory:
            screenshot = Path(temporary_directory) / "capture.png"
            screenshot.write_bytes(b"png-data")

            with self.assertLogs(level=logging.ERROR) as captured:
                send_telegram_photo(screenshot, "test-token", "12345")

        self.assertIn("Falló el envío", captured.output[0])
        self.assertNotIn("test-token", captured.output[0])


if __name__ == "__main__":
    unittest.main()
