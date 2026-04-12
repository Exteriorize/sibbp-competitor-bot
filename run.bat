@echo off
cd /d %~dp0
echo Installing dependencies...
pip install -r requirements.txt
echo Starting bot...
python main.py
pause
