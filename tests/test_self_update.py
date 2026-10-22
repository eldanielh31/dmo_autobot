import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from self_update import (
    API_URL,
    ARCHIVE_URL,
    BACKUP_DIRECTORY,
    _apply_files,
    _extract_archive,
    _update_git_installation,
    _update_zip_installation,
)


class SelfUpdateTests(unittest.TestCase):
    def test_extract_archive_keeps_installation_data_out_of_update(self) -> None:
        archive_buffer = io.BytesIO()
        with zipfile.ZipFile(archive_buffer, "w") as archive:
            archive.writestr("repo-main/bot.py", "print('updated')")
            archive.writestr("repo-main/self_update.py", "update")
            archive.writestr("repo-main/.env", "TOKEN=secret")
            archive.writestr("repo-main/debug/capture.png", "image")

        files = _extract_archive(archive_buffer.getvalue())

        self.assertEqual(files["bot.py"], b"print('updated')")
        self.assertNotIn(".env", files)
        self.assertNotIn("debug/capture.png", files)

    def test_extract_archive_rejects_path_traversal(self) -> None:
        archive_buffer = io.BytesIO()
        with zipfile.ZipFile(archive_buffer, "w") as archive:
            archive.writestr("repo-main/../outside.txt", "unsafe")

        with self.assertRaises(ValueError):
            _extract_archive(archive_buffer.getvalue())

    def test_apply_files_backs_up_replaced_files_and_preserves_user_data(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "bot.py").write_bytes(b"local version")
            (root / ".env").write_bytes(b"TOKEN=local")
            (root / "debug").mkdir()
            (root / "debug" / "capture.png").write_bytes(b"capture")

            changed_count = _apply_files(
                root,
                "abc123",
                {
                    "bot.py": b"new version",
                    "new_module.py": b"new module",
                },
            )

            self.assertEqual(changed_count, 2)
            self.assertEqual((root / "bot.py").read_bytes(), b"new version")
            self.assertEqual(
                (root / BACKUP_DIRECTORY / "abc123" / "bot.py").read_bytes(),
                b"local version",
            )
            self.assertEqual((root / ".env").read_bytes(), b"TOKEN=local")
            self.assertEqual((root / "debug" / "capture.png").read_bytes(), b"capture")

    def test_git_update_skips_a_dirty_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / ".git").mkdir()
            status_result = type(
                "Result",
                (),
                {"returncode": 0, "stdout": " M bot.py\n", "stderr": ""},
            )()

            with patch("self_update.subprocess.run", return_value=status_result) as run:
                _update_git_installation(root)

            self.assertEqual(run.call_count, 1)

    def test_zip_update_fetches_archive_once_per_new_commit(self) -> None:
        archive_buffer = io.BytesIO()
        with zipfile.ZipFile(archive_buffer, "w") as archive:
            archive.writestr("repo-main/bot.py", "new bot")
            archive.writestr("repo-main/self_update.py", "new updater")
        archive_data = archive_buffer.getvalue()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "bot.py").write_text("old bot", encoding="utf-8")
            responses = [b'{"sha": "abc123"}', archive_data, b'{"sha": "abc123"}']

            with patch("self_update._download", side_effect=responses) as download:
                _update_zip_installation(root)
                _update_zip_installation(root)

            self.assertEqual(download.call_count, 3)
            self.assertEqual(download.call_args_list[0].args, (API_URL,))
            self.assertEqual(
                download.call_args_list[1].args,
                (f"{ARCHIVE_URL}/abc123",),
            )
            self.assertEqual((root / "bot.py").read_text(encoding="utf-8"), "new bot")
            self.assertEqual(
                (root / BACKUP_DIRECTORY / "abc123" / "bot.py").read_text(
                    encoding="utf-8"
                ),
                "old bot",
            )


if __name__ == "__main__":
    unittest.main()
