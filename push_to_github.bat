@echo off
setlocal
cd /d "%~dp0"
echo.
echo  Pushing panw-adoption-analytics to GitHub...
echo.
where git >nul 2>nul
if errorlevel 1 (
  echo  Git is not installed or not on PATH.
  pause
  exit /b 1
)
if exist .git\index.lock del /f .git\index.lock
if exist .git\HEAD.lock del /f .git\HEAD.lock
if exist .git\refs\heads\main.lock del /f .git\refs\heads\main.lock
git config --global core.longpaths true
subst Q: /d >nul 2>nul
subst Q: "%~dp0."
if errorlevel 1 (
  echo  Could not map drive Q: - is it already in use?
  pause
  exit /b 1
)
Q:
rem One-time fix: point main at the commit re-authored as erink777-bit
git update-ref refs/heads/main 2e9642ad5ed542d7e2244a2835ede1191eda6c28 35df1fce8d4e80632e80e744f906255d689c1b9b 2>nul
git remote get-url origin >nul 2>nul
if errorlevel 1 git remote add origin https://github.com/erink777-bit/panw-adoption-analytics.git
git add -A
git commit -m "update %date% %time%" 2>nul
git push --force-with-lease -u origin main
set RC=%errorlevel%
C:
subst Q: /d >nul 2>nul
if %RC% neq 0 (
  echo.
  echo  Push did not complete. If a browser sign-in window appeared, finish it and run this again.
) else (
  echo.
  echo  Pushed. View at: https://github.com/erink777-bit/panw-adoption-analytics
)
pause
