from __future__ import annotations

import logging
import sqlite3
import threading
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from config import (
    TELEGRAM_API_TIMEOUT,
    TELEGRAM_COMMAND_POLL_TIMEOUT,
    TELEGRAM_LOG_DATABASE_PATH,
)

LONG_POLL_TIMEOUT = int(TELEGRAM_COMMAND_POLL_TIMEOUT)
MAX_TELEGRAM_MESSAGE_LENGTH = 3900


class TelegramEventLog:
    def __init__(self, database_path: Path = TELEGRAM_LOG_DATABASE_PATH) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS telegram_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    event TEXT NOT NULL,
                    details TEXT NOT NULL
                )
                """
            )
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(telegram_events)")
            }
            if "username" in columns:
                connection.execute(
                    "ALTER TABLE telegram_events RENAME TO telegram_events_with_username"
                )
                connection.execute(
                    """
                    CREATE TABLE telegram_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        created_at TEXT NOT NULL,
                        event TEXT NOT NULL,
                        details TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    INSERT INTO telegram_events (id, created_at, event, details)
                    SELECT id, created_at, event, details
                    FROM telegram_events_with_username
                    ORDER BY id
                    """
                )
                connection.execute("DROP TABLE telegram_events_with_username")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS telegram_events_created_id "
                "ON telegram_events(created_at, id)"
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.database_path, timeout=10)

    def record(self, event: str, details: str = "") -> None:
        try:
            with closing(self._connect()) as connection, connection:
                connection.execute(
                    """
                    INSERT INTO telegram_events (created_at, event, details)
                    VALUES (?, ?, ?)
                    """,
                    (
                        datetime.now().astimezone().isoformat(timespec="seconds"),
                        event,
                        details,
                    ),
                )
        except sqlite3.Error as exc:
            logging.error("[TELEGRAM] No se pudo guardar el evento local (%s).", exc)

    def get_events(self) -> list[tuple[str, str, str]]:
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                """
                SELECT created_at, event, details
                FROM telegram_events
                ORDER BY id
                """
            ).fetchall()
        return [
            (str(created_at), str(event), str(details))
            for created_at, event, details in rows
        ]


class TelegramCommandListener:
    def __init__(
        self,
        token: str,
        logs_chat_id: str,
        event_log: TelegramEventLog,
    ) -> None:
        self.token = token
        self.logs_chat_id = str(logs_chat_id)
        self.event_log = event_log
        self.api_url = f"https://api.telegram.org/bot{token}"

    def run(self, shutdown: threading.Event) -> None:
        offset: int | None = None
        while not shutdown.is_set():
            params: dict[str, int] = {"timeout": LONG_POLL_TIMEOUT}
            if offset is not None:
                params["offset"] = offset
            try:
                response = requests.get(
                    f"{self.api_url}/getUpdates",
                    params=params,
                    timeout=LONG_POLL_TIMEOUT + 5,
                )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict) or not payload.get("ok", False):
                    logging.error("[TELEGRAM] No se pudieron consultar comandos.")
                    shutdown.wait(5)
                    continue

                updates = payload.get("result", [])
                if not isinstance(updates, list):
                    logging.error(
                        "[TELEGRAM] La respuesta de comandos tiene formato inválido."
                    )
                    shutdown.wait(5)
                    continue
                for update in updates:
                    if not isinstance(update, dict):
                        continue
                    update_id = update.get("update_id")
                    if isinstance(update_id, int):
                        offset = update_id + 1
                    self._handle_update(update)
            except (requests.RequestException, ValueError) as exc:
                logging.error(
                    "[TELEGRAM] Falló la recepción de comandos (%s).",
                    type(exc).__name__,
                )
                shutdown.wait(5)

    def _handle_update(self, update: dict[str, Any]) -> None:
        message = update.get("message")
        if not isinstance(message, dict):
            return
        chat = message.get("chat")
        if not isinstance(chat, dict) or "id" not in chat:
            return

        chat_id = str(chat["id"])
        if chat_id != self.logs_chat_id:
            return

        text = message.get("text")
        if not isinstance(text, str):
            return
        parts = text.strip().split()
        if not parts:
            return

        command = parts[0].split("@", 1)[0].lower()
        if command == "/chatid":
            self._send_message(
                chat_id,
                f"ID de este chat: {chat_id}\n"
                "Configúralo como TELEGRAM_CHAT_ID en .env y reinicia el bot.",
            )
            return

        if command != "/logs":
            return
        if len(parts) != 1:
            self._send_message(
                chat_id,
                "Uso: /logs",
            )
            return

        try:
            events = self.event_log.get_events()
        except sqlite3.Error as exc:
            logging.error("[TELEGRAM] No se pudo consultar el historial (%s).", exc)
            self._send_message(chat_id, "No se pudo consultar el historial local.")
            return
        if not events:
            self._send_message(chat_id, "Todavía no hay eventos guardados.")
            return
        self._send_chunks(chat_id, events)

    def _send_chunks(
        self,
        chat_id: str,
        events: list[tuple[str, str, str]],
    ) -> None:
        heading = f"Historial global ({len(events)} eventos):\n"
        lines = [
            f"{created_at} | {event}: {details}".rstrip()
            for created_at, event, details in events
        ]
        chunks: list[str] = []
        current = heading
        for line in lines:
            candidate = f"{current}\n{line}" if current else line
            if len(candidate) > MAX_TELEGRAM_MESSAGE_LENGTH and current:
                chunks.append(current)
                current = line
            else:
                current = candidate
        if current:
            chunks.append(current)

        for chunk in chunks:
            self._send_message(chat_id, chunk)

    def _send_message(self, chat_id: str, text: str) -> None:
        try:
            response = requests.post(
                f"{self.api_url}/sendMessage",
                data={"chat_id": chat_id, "text": text},
                timeout=TELEGRAM_API_TIMEOUT,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or not payload.get("ok", False):
                logging.error("[TELEGRAM] No se pudo responder al comando.")
        except (requests.RequestException, ValueError) as exc:
            logging.error(
                "[TELEGRAM] Falló la respuesta al comando (%s).",
                type(exc).__name__,
            )
