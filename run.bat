@echo off
REM ===================================================================
REM  SEO Backlink Audit - Windows launcher
REM
REM    run.bat                        audit everything in input\
REM    run.bat input\sites.csv        audit one specific file
REM    run.bat --no-content           status + tier only (faster)
REM    run.bat --resume               continue an interrupted run
REM    run.bat --limit 20             first 20 links only
REM ===================================================================
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo ERROR: Python was not found on your PATH.
  echo Install Python 3.10+ from https://www.python.org/downloads/
  echo and tick "Add python.exe to PATH" during setup.
  pause
  exit /b 1
)

python -c "import requests, bs4, openpyxl, yaml" >nul 2>nul
if errorlevel 1 (
  echo Installing dependencies from requirements.txt ...
  python -m pip install -r requirements.txt
  if errorlevel 1 (
    echo ERROR: dependency install failed.
    pause
    exit /b 1
  )
)

if "%~1"=="" (
  python -m seo_audit
) else (
  echo %~1 | findstr /b "-" >nul
  if errorlevel 1 (
    python -m seo_audit --input "%~1" %2 %3 %4 %5 %6
  ) else (
    python -m seo_audit %*
  )
)

echo.
echo Done. Reports are in the output folder.
pause
endlocal
