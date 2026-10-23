@echo off
REM Start FastAPI backend on 127.0.0.1:8000
cd /d "%~dp0backend"
call .venv\Scripts\activate.bat
echo Starting backend at http://127.0.0.1:8000 ...
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
