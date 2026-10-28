@echo off
cd /d "%~dp0backend"
if not exist .venv (
  py -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
if not exist .env copy .env.example .env
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
pause
