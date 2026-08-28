@echo off
REM ===================================================================
REM  Cleanup - removes folders that are no longer part of the project.
REM
REM  Deletes:
REM    src\            the old flat layout, replaced by seo_audit\
REM    sample_report\  the bundled example output
REM    __pycache__\    compiled Python caches
REM
REM  Leaves alone: output\, history\, cache\, input\ - your own data.
REM ===================================================================
setlocal
cd /d "%~dp0"

echo This will permanently delete:
if exist "src"           echo    src\           (old layout - superseded by seo_audit\)
if exist "sample_report" echo    sample_report\ (bundled example output)
echo    all __pycache__\ folders
echo.
echo Your own output\, history\, cache\ and input\ folders are NOT touched.
echo.
set /p CONFIRM="Type Y to continue: "
if /i not "%CONFIRM%"=="Y" (
  echo Cancelled. Nothing was deleted.
  pause
  exit /b 0
)

echo.
if exist "src" (
  rmdir /s /q "src"
  if exist "src" (echo   FAILED to remove src\ - close any editor using it) else (echo   removed src\)
)
if exist "sample_report" (
  rmdir /s /q "sample_report"
  if exist "sample_report" (echo   FAILED to remove sample_report\) else (echo   removed sample_report\)
)
for /d /r %%d in (__pycache__) do (
  if exist "%%d" rmdir /s /q "%%d"
)
echo   removed __pycache__ folders

echo.
echo Done. Verifying the project still works...
echo.
python tests\run_tests.py
pause
endlocal
