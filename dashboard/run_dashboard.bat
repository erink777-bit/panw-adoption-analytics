@echo off
cd /d "%~dp0.."
echo.
echo  VRS Adoption Dashboard - starting...
echo.
where python >nul 2>nul
if errorlevel 1 (
  echo  Python was not found. Install it from https://www.python.org/downloads/
  echo  and select "Add python.exe to PATH" during installation, then run this again.
  pause
  exit /b 1
)
echo  Installing requirements (first run only)...
python -m pip install -r requirements.txt --quiet --disable-pip-version-check
echo  Launching - your browser will open at http://localhost:8501
python -m streamlit run dashboard/app.py
pause
