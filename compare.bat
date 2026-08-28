@echo off
REM Compare the two most recent runs in history\ and write output\changes.csv
setlocal enabledelayedexpansion
cd /d "%~dp0"
set OLD=
set NEW=
for /f "delims=" %%f in ('dir /b /o:n history\run_*.json 2^>nul') do (
  set OLD=!NEW!
  set NEW=%%f
)
if "!OLD!"=="" (
  echo Need at least two runs in history\ to compare. Run an audit twice first.
  pause
  exit /b 1
)
echo Comparing !OLD!  ->  !NEW!
python -m seo_audit --compare "history\!OLD!" "history\!NEW!"
pause
endlocal
