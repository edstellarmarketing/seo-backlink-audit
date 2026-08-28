@echo off
REM ===================================================================
REM  Push this project to a private GitHub repo.
REM
REM  Needs: git, and the GitHub CLI (gh) signed in.
REM     winget install --id GitHub.cli
REM     gh auth login
REM
REM  Edit REPO below if you want a different name or owner.
REM ===================================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

set REPO=edstellarmarketing/seo-backlink-audit

echo Target repo: %REPO%  (private)
echo.

where git >nul 2>nul
if errorlevel 1 (
  echo ERROR: git is not installed or not on PATH.
  echo   winget install --id Git.Git
  pause & exit /b 1
)

where gh >nul 2>nul
if errorlevel 1 (
  echo ERROR: the GitHub CLI is not installed.
  echo   winget install --id GitHub.cli
  echo   then:  gh auth login
  pause & exit /b 1
)

gh auth status >nul 2>nul
if errorlevel 1 (
  echo ERROR: the GitHub CLI is not signed in.
  echo   gh auth login
  pause & exit /b 1
)

REM ---- sanity check: never publish secrets ----
if exist ".env" (
  findstr /r /c:"^[A-Z_]*=." ".env" >nul 2>nul
  if not errorlevel 1 (
    echo .env contains values. It is listed in .gitignore and will NOT be
    echo committed - but check the output of "git status" below before pushing.
    echo.
  )
)

if not exist ".git" (
  echo Initialising the repository...
  git init -b main
  if errorlevel 1 ( echo ERROR: git init failed. & pause & exit /b 1 )
)

git add -A
if errorlevel 1 ( echo ERROR: git add failed. & pause & exit /b 1 )

echo.
echo These files will be committed:
git status --short
echo.
echo Excluded by .gitignore: .env, data\*.db, cache\, output\, history\,
echo __pycache__, input\metrics\ contents.
echo.
set /p OK="Look right? Type Y to commit and push: "
if /i not "%OK%"=="Y" (
  echo Cancelled. Nothing was pushed. Your local commit staging is left as-is.
  pause & exit /b 0
)

git diff --cached --quiet
if errorlevel 1 (
  if exist "COMMIT_MSG.txt" (
    git commit -F COMMIT_MSG.txt
  ) else (
    git commit -m "SEO backlink audit: staged pipeline, master-list database, dashboard"
  )
) else (
  echo Nothing new to commit; pushing the existing history.
)

REM ---- create the repo if it does not exist yet, then push ----
gh repo view %REPO% >nul 2>nul
if errorlevel 1 (
  echo Creating private repo %REPO% ...
  gh repo create %REPO% --private --source=. --remote=origin --push
  if errorlevel 1 (
    echo.
    echo Could not create %REPO%.
    echo   - If "edstellarmarketing" is your personal account, try:
    echo         set REPO=seo-backlink-audit
    echo     and run this again ^(gh will use your own account^).
    echo   - If it is an organisation, make sure you can create repos in it.
    pause & exit /b 1
  )
) else (
  echo Repo already exists. Pushing to it...
  git remote get-url origin >nul 2>nul || git remote add origin https://github.com/%REPO%.git
  git push -u origin main
  if errorlevel 1 ( echo ERROR: push failed. & pause & exit /b 1 )
)

echo.
echo Done. https://github.com/%REPO%
echo.
echo Note: data\audit.db is deliberately NOT in the repo - git cannot diff a
echo binary and it bloats history. data\master_disavow_sheet.csv IS committed,
echo so anyone cloning can rebuild the database with:
echo     python -m seo_audit --import-master data\master_disavow_sheet.csv
pause
endlocal
