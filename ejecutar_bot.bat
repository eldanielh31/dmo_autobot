@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>&1
if errorlevel 1 (
    echo [ERROR] No se encontro Python. Instala Python 3.10 o superior desde python.org.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [INFO] Creando entorno virtual...
    py -m venv .venv
    if errorlevel 1 (
        echo [ERROR] No se pudo crear el entorno virtual.
        pause
        exit /b 1
    )
)

echo [INFO] Instalando o actualizando dependencias...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Fallo la instalacion de dependencias.
    pause
    exit /b 1
)

echo [INFO] Iniciando bot...
".venv\Scripts\python.exe" bot.py
if errorlevel 1 (
    echo [ERROR] El bot finalizo con un error.
)
pause
