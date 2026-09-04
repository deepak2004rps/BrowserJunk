@echo off
setlocal EnableDelayedExpansion
title BrowserVault Demo Data Populator
color 0B

echo.
echo  ========================================
echo   BrowserVault Demo Data Populator
echo  ========================================
echo.

:: ── Locate a real Python 3.10+ ───────────────────────────────────────────
:: Note: Windows ships a stub python.exe in WindowsApps that only opens the
:: Microsoft Store, so `where python` succeeding is not proof Python exists.
set "PYEXE="

:: 1) Prefer the official py launcher (never the Store stub).
where py >nul 2>&1
if not errorlevel 1 (
    for /f "delims=" %%p in ('py -3 -c "import sys;print(sys.executable)" 2^>nul') do set "PYEXE=%%p"
)

:: 2) Fall back to python.exe on PATH, but reject the WindowsApps stub.
if not defined PYEXE (
    for /f "delims=" %%p in ('where python 2^>nul') do (
        echo %%p | find /i "\WindowsApps\" >nul
        if errorlevel 1 if not defined PYEXE set "PYEXE=%%p"
    )
)

:: 3) Validate version >= 3.10.
if defined PYEXE (
    "%PYEXE%" -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3,10) else 1)" >nul 2>&1
    if errorlevel 1 (
        echo [WARN] Found Python at "%PYEXE%" but it is older than 3.10.
        set "PYEXE="
    )
)

:: ── Auto-install Python if none found ────────────────────────────────────
if not defined PYEXE (
    echo [..] No suitable Python found. Installing the latest stable Python...

    where winget >nul 2>&1
    if not errorlevel 1 (
        echo [..] Installing via winget ^(official Python.org package^)...
        winget install --id Python.Python.3.12 -e --source winget ^
            --accept-package-agreements --accept-source-agreements ^
            --scope user --disable-interactivity
    ) else (
        echo [..] winget not available, downloading installer from python.org...
        set "PY_URL=https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe"
        set "PY_TMP=%TEMP%\python-3.12.7-amd64.exe"
        powershell -NoProfile -ExecutionPolicy Bypass -Command ^
            "[Net.ServicePointManager]::SecurityProtocol='Tls12'; Invoke-WebRequest -Uri '!PY_URL!' -OutFile '!PY_TMP!'"
        if errorlevel 1 (
            echo [ERROR] Failed to download the Python installer.
            echo         Install Python 3.10+ manually from https://python.org and re-run.
            pause
            exit /b 1
        )
        echo [..] Running the Python installer ^(per-user, silent^)...
        "!PY_TMP!" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_pip=1
        del /q "!PY_TMP!" >nul 2>&1
    )

    :: Re-detect after install. winget/py.exe land on PATH only in new shells,
    :: so check the py launcher and the standard per-user install path too.
    where py >nul 2>&1
    if not errorlevel 1 (
        for /f "delims=" %%p in ('py -3 -c "import sys;print(sys.executable)" 2^>nul') do set "PYEXE=%%p"
    )
    if not defined PYEXE (
        for /f "delims=" %%p in ('dir /b /s "%LOCALAPPDATA%\Programs\Python\Python3*\python.exe" 2^>nul') do (
            if not defined PYEXE set "PYEXE=%%p"
        )
    )

    if not defined PYEXE (
        echo [ERROR] Python was installed but could not be located automatically.
        echo         Close this window, open a NEW terminal, and run run.bat again.
        pause
        exit /b 1
    )
)

for /f "delims=" %%v in ('"%PYEXE%" --version 2^>^&1') do set "PYVER=%%v"
echo [OK] Using %PYVER% at "%PYEXE%"

:: ── Create virtual environment if needed ─────────────────────────────────
if not exist ".venv\Scripts\activate.bat" (
    echo [..] Creating virtual environment...
    "%PYEXE%" -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo [OK] Virtual environment created.
)

:: ── Activate venv ────────────────────────────────────────────────────────
call .venv\Scripts\activate.bat

:: ── Install / upgrade dependencies ───────────────────────────────────────
echo [..] Checking dependencies...
pip install -q -r requirements.txt >nul 2>&1
if errorlevel 1 (
    echo [WARN] pip install had issues, retrying with --upgrade...
    pip install --upgrade -r requirements.txt
)
echo [OK] Dependencies ready.

:: ── Create output directories ────────────────────────────────────────────
if not exist "logs" mkdir logs
if not exist "output" mkdir output

:: ── Run the populator ────────────────────────────────────────────────────
echo.
echo  ─── Starting population ───
echo.
python main.py %*

:: ── Done ─────────────────────────────────────────────────────────────────
echo.
echo  ========================================
echo   Complete. Check output\ for reports.
echo  ========================================
echo.
pause
