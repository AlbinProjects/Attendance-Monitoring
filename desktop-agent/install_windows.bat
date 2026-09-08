@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>&1
if %errorlevel%==0 (set PY=py) else (set PY=python)
%PY% --version || (echo Python 3.11+ is required. Install it from python.org and rerun this file.& exit /b 1)
%PY% -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
schtasks /Create /TN "Attendance Desktop Activity Agent" /TR "\"%CD%\.venv\Scripts\pythonw.exe\" \"%CD%\activity_agent.py\"" /SC ONLOGON /RL LIMITED /F
start "" "%CD%\.venv\Scripts\pythonw.exe" "%CD%\activity_agent.py"
echo.
echo Attendance Desktop Activity Agent installed and started.
endlocal
