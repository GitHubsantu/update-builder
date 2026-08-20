@echo off
setlocal

rem StreamForge Update Builder - Windows launcher
rem - Creates a local virtual environment on first run
rem - Installs/updates dependencies from requirements.txt
rem - Launches the app
rem
rem Just double-click this file to run.

cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo.
    echo [ERROR] Python was not found in PATH.
    echo Please install Python 3.11+ from https://www.python.org/downloads/
    echo and make sure "Add Python to PATH" is checked during install.
    echo.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Setting up StreamForge Update Builder for the first time...
    python -m venv .venv
    if errorlevel 1 (
        echo.
        echo [ERROR] Failed to create the virtual environment.
        pause
        exit /b 1
    )
)

echo Checking dependencies...
".venv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
    echo.
    echo [ERROR] Failed to install dependencies. Check your internet connection.
    pause
    exit /b 1
)

echo Starting StreamForge Update Builder...
".venv\Scripts\python.exe" main.py

if errorlevel 1 (
    echo.
    echo [ERROR] The application closed with an error. See above for details.
    pause
)

endlocal
