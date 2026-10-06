@echo off
rem Run from the folder that contains this script, wherever the project lives.
rem pushd also handles network (UNC) folders, which cd cannot enter.
pushd "%~dp0" || (echo Could not open the launcher folder "%~dp0". & pause & exit /b 1)

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
