@echo off
cd /d "%~dp0"
if not exist logs mkdir logs
.venv\Scripts\python.exe collect.py >> logs\collect.log 2>&1
