@echo off
echo.
echo  Connect the VRS dashboard to BigQuery (one-time setup)
echo.
where gcloud >nul 2>nul
if errorlevel 1 (
  echo  The Google Cloud SDK is not installed.
  echo  1. Download it:  https://cloud.google.com/sdk/docs/install
  echo  2. Run the installer with default options ^(check "Run gcloud init"^ off is fine^)
  echo  3. Double-click this file again.
  start https://cloud.google.com/sdk/docs/install
  pause
  exit /b 1
)
echo  A browser window will open - sign in with the Google account that owns
echo  the BigQuery project ^(panw-502122^).
echo.
call gcloud auth application-default login
if errorlevel 1 (
  echo  Sign-in did not complete. Run this file again to retry.
  pause
  exit /b 1
)
echo.
echo  Connected. The dashboard will now use live BigQuery automatically.
echo  Launching it now - check the sidebar badge: "BigQuery (live)"
cd /d "%~dp0"
python -m pip install -r requirements.txt --quiet --disable-pip-version-check
python -m streamlit run app.py
pause
