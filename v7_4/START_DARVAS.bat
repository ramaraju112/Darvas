@echo off
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (set PY=py -3) else (set PY=python)
if not exist .venv ( %PY% -m venv .venv || (echo Python 3.11+ is required & pause & exit /b 1) )
call .venv\Scripts\activate.bat
python -m pip install -r requirements.txt || (echo Dependency installation failed & pause & exit /b 1)
start "" http://127.0.0.1:8000
python -m uvicorn app:app --host 127.0.0.1 --port 8000
pause
