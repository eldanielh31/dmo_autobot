import importlib
import importlib.util
import site
import subprocess
import sys
from pathlib import Path

REQUIRED_MODULES = ("cv2", "mss", "numpy", "win32gui", "requests", "winrt")


def ensure_runtime_dependencies() -> None:
    missing = [
        module
        for module in REQUIRED_MODULES
        if importlib.util.find_spec(module) is None
    ]
    if not missing:
        return

    requirements_path = Path(__file__).resolve().with_name("requirements.txt")
    print(
        "[DEPENDENCIAS] Faltan módulos: "
        f"{', '.join(missing)}. Instalando requirements.txt para este Python..."
    )
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "-r",
            str(requirements_path),
        ],
        check=True,
    )
    site.addsitedir(site.getusersitepackages())
    importlib.invalidate_caches()

    still_missing = [
        module
        for module in REQUIRED_MODULES
        if importlib.util.find_spec(module) is None
    ]
    if still_missing:
        raise ImportError(
            "No se pudieron cargar estos módulos después de instalar "
            f"requirements.txt: {', '.join(still_missing)}."
        )
