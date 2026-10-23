import tempfile
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from telegram_logs import TelegramCommandListener, TelegramEventLog


class TelegramEventLogTests(unittest.TestCase):
    def test_get_events_returns_global_history_in_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            event_log = TelegramEventLog(Path(temporary_directory) / "events.sqlite3")
            event_log.record("iniciado", "Macro iniciado.")
            event_log.record("anti-macro", "Reto detectado.")

            events = event_log.get_events()

        self.assertEqual(len(events), 2)
        self.assertEqual(events[0][1:], ("iniciado", "Macro iniciado."))
        self.assertEqual(events[1][1:], ("anti-macro", "Reto detectado."))

    def test_migrates_previous_username_based_history(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database = Path(temporary_directory) / "events.sqlite3"
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.execute(
                    """
                    CREATE TABLE telegram_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        username TEXT NOT NULL COLLATE NOCASE,
                        created_at TEXT NOT NULL,
                        event TEXT NOT NULL,
                        details TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    INSERT INTO telegram_events (username, created_at, event, details)
                    VALUES (?, ?, ?, ?)
                    """,
                    ("previous-player", "2026-10-22T12:00:00", "iniciado", "old event"),
                )

            event_log = TelegramEventLog(database)
            events = event_log.get_events()

        self.assertEqual(events, [("2026-10-22T12:00:00", "iniciado", "old event")])


class TelegramCommandListenerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.event_log = TelegramEventLog(
            Path(self.temporary_directory.name) / "events.sqlite3"
        )
        self.listener = TelegramCommandListener(
            "test-token",
            "-100123",
            self.event_log,
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_logs_command_returns_global_event_history(self) -> None:
        self.event_log.record("iniciado", "Started.")
        self.event_log.record("cerrado", "Stopped.")

        with patch.object(self.listener, "_send_message") as send_message:
            self.listener._handle_update(
                {
                    "message": {
                        "chat": {"id": -100123},
                        "text": "/logs",
                    }
                }
            )

        self.assertEqual(send_message.call_count, 1)
        sent_chat_id, sent_text = send_message.call_args.args
        self.assertEqual(sent_chat_id, "-100123")
        self.assertIn("Historial global (2 eventos)", sent_text)
        self.assertIn("Started.", sent_text)
        self.assertIn("Stopped.", sent_text)

    def test_commands_from_private_chat_are_ignored(self) -> None:
        with patch.object(self.listener, "_send_message") as send_message:
            self.listener._handle_update(
                {
                    "message": {
                        "chat": {"id": 456},
                        "text": "/logs",
                    }
                }
            )

        send_message.assert_not_called()

    def test_chatid_command_reports_group_id(self) -> None:
        with patch.object(self.listener, "_send_message") as send_message:
            self.listener._handle_update(
                {
                    "message": {
                        "chat": {"id": -100123},
                        "text": "/chatid",
                    }
                }
            )

        send_message.assert_called_once()
        self.assertEqual(send_message.call_args.args[0], "-100123")
        self.assertIn("-100123", send_message.call_args.args[1])

    def test_logs_rejects_username_argument(self) -> None:
        with patch.object(self.listener, "_send_message") as send_message:
            self.listener._handle_update(
                {
                    "message": {
                        "chat": {"id": -100123},
                        "text": "/logs player",
                    }
                }
            )

        self.assertIn("Uso: /logs", send_message.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
