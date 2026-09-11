@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" activity_agent.py
) else (
  echo Agent is not installed. Run install_windows.bat first.
  exit /b 1
)
