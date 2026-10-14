@echo off
setlocal
cd /d "%~dp0"
if exist "backend\.venv\Scripts\python.exe" (
    "backend\.venv\Scripts\python.exe" "scripts\local_stack.py" %*
) else (
    uv run --project backend --frozen python "scripts\local_stack.py" %*
)
exit /b %errorlevel%
