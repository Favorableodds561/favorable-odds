@echo off
rem Local Windows x64 build of OddsTune.exe. The official, tested build is produced by GitHub Actions
rem (.github/workflows/build-odds-tune.yml). Run this only for local experiments.
setlocal
cd /d "%~dp0"

echo [1/6] Checking Python...
where py >nul 2>nul || (echo Python launcher not found. Install Python 3.12 x64 from python.org. & exit /b 1)
py -3.12 -c "import sys; assert sys.maxsize > 2**32, '64-bit Python required'" || exit /b 1

echo [2/6] Creating build environment...
if not exist .venv py -3.12 -m venv .venv || exit /b 1
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip || exit /b 1
python -m pip install -r requirements-build.txt || exit /b 1

echo [3/6] Syntax check...
python -m compileall -q odds_tune_core.py odds_tune.py || exit /b 1

echo [4/6] Running tests...
python -m unittest discover -s tests -v || exit /b 1

echo [5/6] Building OddsTune.exe...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
pyinstaller --noconfirm --clean --onefile --windowed --name OddsTune --version-file version_info.txt --icon odds_tune.ico --add-data "odds_tune.ico;." odds_tune.py || exit /b 1

echo [6/6] Smoke test and SHA-256...
dist\OddsTune.exe --self-test dist\selftest.json
powershell -NoProfile -Command "Start-Sleep 3; Get-Content dist\selftest.json"
certutil -hashfile dist\OddsTune.exe SHA256

echo.
echo Built: %CD%\dist\OddsTune.exe  (UNSIGNED - see docs\SIGNING.md before any public release)
endlocal
