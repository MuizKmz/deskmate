@echo off
rem ---------------------------------------------------------------
rem  DeskMate launcher. Double-click me.
rem  First time: makes a private Python environment (.venv) and
rem  installs PySide6 (~1-2 minutes). After that: starts instantly.
rem
rem  run_deskmate.bat --console   runs with a console window (to see errors)
rem  run_deskmate.bat --test      runs the self-tests
rem ---------------------------------------------------------------
setlocal
cd /d "%~dp0"
set "VENV=%~dp0.venv"
set "VPY=%VENV%\Scripts\python.exe"

if exist "%VPY%" goto :check_packages

echo [DeskMate] First run: setting things up...
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)
if not defined PY goto :no_python
%PY% -m venv "%VENV%"
if errorlevel 1 goto :no_python

:check_packages
"%VPY%" -c "import PySide6" >nul 2>nul
if not errorlevel 1 goto :run
echo [DeskMate] Installing PySide6 (one time only)...
"%VPY%" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 goto :pip_failed

:run
if /i "%~1"=="--test" (
    "%VPY%" -m unittest discover -s tests -t .
    pause
    exit /b
)
if /i "%~1"=="--console" (
    "%VPY%" "%~dp0run_deskmate.pyw" --debug
    pause
    exit /b
)
start "" "%VENV%\Scripts\pythonw.exe" "%~dp0run_deskmate.pyw" %*
exit /b 0

:no_python
echo.
echo Python 3.9 or newer was not found.
echo Install it from https://www.python.org/downloads/
echo (tick "Add python.exe to PATH" during setup), then run this file again.
echo.
pause
exit /b 1

:pip_failed
echo.
echo Installing PySide6 failed. Check your internet connection and run this file again.
echo If it keeps failing, delete the .venv folder and try once more.
echo.
pause
exit /b 1
