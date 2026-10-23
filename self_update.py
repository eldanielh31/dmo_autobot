from __future__ import annotations

import io
import json
import os
import subprocess
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

REPOSITORY = "eldanielh31/dmo_autobot"
BRANCH = "main"
API_URL = f"https://api.github.com/repos/{REPOSITORY}/commits/{BRANCH}"
ARCHIVE_URL = f"https://api.github.com/repos/{REPOSITORY}/zipball"
UPDATE_STATE = ".dmo_bot_update.json"
BACKUP_DIRECTORY = ".dmo_bot_update_backups"
PRESERVED_DIRECTORIES = {
    ".git",
    ".venv",
    "__pycache__",
    "debug",
    BACKUP_DIRECTORY,
}
PRESERVED_FILES = {
    ".env",
    UPDATE_STATE,
    ".dmo_bot_telegram_logs.sqlite3",
}
REQUEST_TIMEOUT = 20


def _download(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "dmo-autobot-updater"},
    )
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        return response.read()


def _extract_archive(archive_data: bytes) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    with zipfile.ZipFile(io.BytesIO(archive_data)) as archive:
        for entry in archive.infolist():
            if entry.is_dir():
                continue
            parts = PurePosixPath(entry.filename).parts
            if (
                len(parts) < 2
                or parts[0] in {".", ".."}
                or "\\" in entry.filename
            ):
                raise ValueError("El archivo de actualización tiene rutas inválidas.")

            relative_path = PurePosixPath(*parts[1:])
            if (
                relative_path.is_absolute()
                or any(part in {"", ".", ".."} for part in relative_path.parts)
                or ":" in relative_path.parts[0]
            ):
                raise ValueError("El archivo de actualización tiene rutas inválidas.")
            if relative_path.parts[0] in PRESERVED_DIRECTORIES:
                continue
            if len(relative_path.parts) == 1 and relative_path.name in PRESERVED_FILES:
                continue
            files[relative_path.as_posix()] = archive.read(entry)

    if "bot.py" not in files or "self_update.py" not in files:
        raise ValueError("El archivo de actualización no contiene los archivos del bot.")
    return files


def _safe_target(root: Path, relative_path: str) -> Path:
    target = root.joinpath(*PurePosixPath(relative_path).parts)
    try:
        target.resolve().relative_to(root.resolve())
    except ValueError as error:
        raise ValueError("La ruta de actualización sale de la carpeta del bot.") from error
    return target


def _write_atomically(target: Path, content: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=target.parent,
            prefix=f".{target.name}.",
            delete=False,
        ) as temporary_file:
            temporary_file.write(content)
            temporary_path = Path(temporary_file.name)
        os.replace(temporary_path, target)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _apply_files(root: Path, commit: str, files: dict[str, bytes]) -> int:
    changed_files = [
        (relative_path, content)
        for relative_path, content in files.items()
        if not (target := _safe_target(root, relative_path)).is_file()
        or target.read_bytes() != content
    ]
    backup_root = root / BACKUP_DIRECTORY / commit

    for relative_path, content in changed_files:
        target = _safe_target(root, relative_path)
        if target.is_file():
            backup = _safe_target(backup_root, relative_path)
            if not backup.exists():
                _write_atomically(backup, target.read_bytes())
        _write_atomically(target, content)

    return len(changed_files)


def _read_saved_commit(root: Path) -> str | None:
    state_path = root / UPDATE_STATE
    if not state_path.exists():
        return None
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if not isinstance(state, dict):
        raise ValueError(f"El archivo {UPDATE_STATE} no contiene un objeto válido.")
    commit = state.get("commit")
    if not isinstance(commit, str):
        raise ValueError(f"El archivo {UPDATE_STATE} no contiene un commit válido.")
    return commit


def _save_commit(root: Path, commit: str) -> None:
    content = json.dumps({"commit": commit}, indent=2).encode("utf-8")
    _write_atomically(root / UPDATE_STATE, content)


def _update_zip_installation(root: Path) -> None:
    commit_data = json.loads(_download(API_URL))
    commit = commit_data.get("sha")
    if not isinstance(commit, str) or not commit:
        raise ValueError("GitHub no devolvió un identificador de commit válido.")
    if _read_saved_commit(root) == commit:
        print("[ACTUALIZACIÓN] El bot ya está actualizado.")
        return

    files = _extract_archive(_download(f"{ARCHIVE_URL}/{commit}"))
    changed_count = _apply_files(root, commit, files)
    _save_commit(root, commit)
    if changed_count:
        print(
            f"[ACTUALIZACIÓN] Se actualizaron {changed_count} archivos. "
            f"Las copias reemplazadas están en {BACKUP_DIRECTORY}\\{commit}."
        )
    else:
        print("[ACTUALIZACIÓN] El bot ya está actualizado.")


def _update_git_installation(root: Path) -> None:
    try:
        status = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=REQUEST_TIMEOUT,
            check=False,
        )
    except FileNotFoundError:
        print("[ACTUALIZACIÓN] No se encontró Git; se iniciará la versión instalada.")
        return
    except subprocess.TimeoutExpired:
        print("[ACTUALIZACIÓN] Git tardó demasiado; se iniciará la versión instalada.")
        return

    if status.returncode != 0:
        detail = status.stderr.strip() or "git status falló."
        print(f"[ACTUALIZACIÓN] No se pudo revisar el repositorio: {detail}")
        return
    if status.stdout.strip():
        print(
            "[ACTUALIZACIÓN] Hay cambios locales pendientes; se omite la "
            "actualización para conservarlos."
        )
        return

    environment = os.environ.copy()
    environment["GIT_TERMINAL_PROMPT"] = "0"
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "pull", "--ff-only", "--quiet"],
            capture_output=True,
            text=True,
            timeout=REQUEST_TIMEOUT,
            check=False,
            env=environment,
        )
    except FileNotFoundError:
        print("[ACTUALIZACIÓN] No se encontró Git; se iniciará la versión instalada.")
        return
    except subprocess.TimeoutExpired:
        print("[ACTUALIZACIÓN] Git tardó demasiado; se iniciará la versión instalada.")
        return

    if result.returncode != 0:
        detail = result.stderr.strip() or "git pull falló."
        print(f"[ACTUALIZACIÓN] No se pudo actualizar: {detail}")
    else:
        print("[ACTUALIZACIÓN] Git terminó correctamente.")


def update_on_start() -> None:
    root = Path(__file__).resolve().parent
    if (root / ".git").exists():
        _update_git_installation(root)
        return

    try:
        _update_zip_installation(root)
    except (
        OSError,
        urllib.error.URLError,
        zipfile.BadZipFile,
        ValueError,
    ) as error:
        print(
            "[ACTUALIZACIÓN] Falló la actualización; se iniciará la versión "
            f"instalada: {error}"
        )
