@echo off
rem Run from the folder that contains this script, wherever the project lives.
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo No virtual environment found at "%CD%\.venv".
    echo Create it once from this folder, then run this launcher again:
    echo     py -3.14 -m venv .venv
    echo     .venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m streamlit run app.py
pause
