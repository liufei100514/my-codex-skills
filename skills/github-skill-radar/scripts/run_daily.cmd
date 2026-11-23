@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist logs mkdir logs
echo. >> logs\run.log
python radar.py --days 7 --top 8 >> logs\run.log 2>&1
