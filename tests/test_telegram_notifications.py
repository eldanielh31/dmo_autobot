import logging
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

import cv2
import numpy as np

from antimacro import (
    load_telegram_credentials,
    send_telegram_message,
    send_telegram_photo,
    send_telegram_status_photo,
)


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

    def test_env_file_chat_id_overrides_stale_terminal_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            env_path = Path(temporary_directory) / ".env"
            env_path.write_text(
                "TELEGRAM_BOT_TOKEN=file-token\nTELEGRAM_CHAT_ID=-5076045131\n",
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {
                    "TELEGRAM_BOT_TOKEN": "stale-token",
                    "TELEGRAM_CHAT_ID": "531200202",
                },
            ):
                self.assertEqual(
                    load_telegram_credentials(env_path),
                    ("file-token", "-5076045131"),
                )

    def test_send_photo_posts_multipart_to_telegram(self) -> None:
        response = Mock()
        response.json.return_value = {"ok": True}
        with tempfile.TemporaryDirectory() as temporary_directory:
            screenshot = Path(temporary_directory) / "capture.png"
            screenshot.write_bytes(b"png-data")

            with patch("antimacro.requests.post", return_value=response) as post:
                send_telegram_photo(screenshot, "test-token", "-5076045131")

        args, kwargs = post.call_args
        self.assertEqual(
            args[0],
            "https://api.telegram.org/bottest-token/sendPhoto",
        )
        self.assertEqual(kwargs["data"]["chat_id"], "-5076045131")
        self.assertEqual(kwargs["files"]["photo"][0], "capture.png")
        self.assertEqual(kwargs["files"]["photo"][2], "image/png")
        self.assertEqual(kwargs["timeout"], 15.0)
        response.raise_for_status.assert_called_once_with()

    def test_send_photo_crops_antimacro_dialog_and_encodes_jpeg(self) -> None:
        response = Mock()
        response.json.return_value = {"ok": True}
        frame = np.full((768, 1366, 3), (70, 80, 90), dtype=np.uint8)
        frame[170:485, 930:1180] = (20, 30, 40)
        frame[400:415, 950:1170] = (0, 255, 255)

        with patch("antimacro.requests.post", return_value=response) as post:
            send_telegram_photo(frame, "test-token", "-5076045131")

        _, kwargs = post.call_args
        filename, content, mime_type = kwargs["files"]["photo"]
        self.assertEqual(filename, "antimacro.jpg")
        self.assertEqual(mime_type, "image/jpeg")
        decoded = cv2.imdecode(np.frombuffer(content, dtype=np.uint8), cv2.IMREAD_COLOR)
        self.assertEqual(decoded.shape, (356, 286, 3))
        self.assertTrue(np.allclose(decoded[53, 83], (20, 30, 40), atol=5))
        response.raise_for_status.assert_called_once_with()

    def test_send_photo_keeps_full_frame_when_timer_bar_is_not_found(self) -> None:
        response = Mock()
        response.json.return_value = {"ok": True}
        frame = np.zeros((768, 1366, 3), dtype=np.uint8)

        with patch("antimacro.requests.post", return_value=response) as post:
            send_telegram_photo(frame, "test-token", "-5076045131")

        _, kwargs = post.call_args
        _, content, mime_type = kwargs["files"]["photo"]
        self.assertEqual(mime_type, "image/jpeg")
        decoded = cv2.imdecode(np.frombuffer(content, dtype=np.uint8), cv2.IMREAD_COLOR)
        self.assertEqual(decoded.shape, frame.shape)
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

    def test_status_notification_sends_top_left_game_crop_as_photo(self) -> None:
        response = Mock()
        response.json.return_value = {"ok": True}
        frame = np.zeros((768, 1366, 3), dtype=np.uint8)
        frame[30, 80] = (25, 100, 220)

        with patch("antimacro.requests.post", return_value=response) as post:
            send_telegram_status_photo(
                frame,
                "Macro iniciado\nHora: ahora",
                "test-token",
                "-5076045131",
            )

        args, kwargs = post.call_args
        self.assertEqual(
            args[0],
            "https://api.telegram.org/bottest-token/sendPhoto",
        )
        self.assertEqual(
            kwargs["data"],
            {"chat_id": "-5076045131", "caption": "Macro iniciado\nHora: ahora"},
        )
        filename, content, mime_type = kwargs["files"]["photo"]
        self.assertEqual(filename, "game_hud.png")
        self.assertEqual(mime_type, "image/png")
        decoded = cv2.imdecode(np.frombuffer(content, dtype=np.uint8), cv2.IMREAD_COLOR)
        self.assertEqual(decoded.shape, (177, 478, 3))
        self.assertTrue(np.array_equal(decoded[30, 80], frame[30, 80]))
        response.raise_for_status.assert_called_once_with()

    def test_status_photo_logs_api_error_without_token(self) -> None:
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "ok": False,
            "description": "Bad Request: chat not found",
        }

        with (
            patch("antimacro.requests.post", return_value=response),
            self.assertLogs(level=logging.ERROR) as captured,
        ):
            send_telegram_status_photo(
                np.zeros((768, 1366, 3), dtype=np.uint8),
                "Macro iniciado",
                "test-token",
                "-5076045131",
            )

        self.assertIn("-5076045131", captured.output[0])
        self.assertIn("chat not found", captured.output[0])
        self.assertNotIn("test-token", captured.output[0])

    def test_send_message_posts_status_to_telegram(self) -> None:
        response = Mock()
        response.json.return_value = {"ok": True}

        with patch("antimacro.requests.post", return_value=response) as post:
            send_telegram_message("Macro iniciado", "test-token", "-5076045131")

        args, kwargs = post.call_args
        self.assertEqual(
            args[0],
            "https://api.telegram.org/bottest-token/sendMessage",
        )
        self.assertEqual(
            kwargs["data"],
            {"chat_id": "-5076045131", "text": "Macro iniciado"},
        )
        response.raise_for_status.assert_called_once_with()

    def test_send_message_logs_telegram_api_rejection(self) -> None:
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "ok": False,
            "description": "Bad Request: chat not found",
        }

        with (
            patch("antimacro.requests.post", return_value=response),
            self.assertLogs(level=logging.ERROR) as captured,
        ):
            send_telegram_message("test", "test-token", "-100123")

        self.assertIn("-100123", captured.output[0])
        self.assertIn("chat not found", captured.output[0])
        self.assertNotIn("test-token", captured.output[0])


if __name__ == "__main__":
    unittest.main()
