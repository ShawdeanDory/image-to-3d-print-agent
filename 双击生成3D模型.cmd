@echo off
setlocal
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
if not exist "%~dp0runtime\envs\reconstruction\Scripts\python.exe" (
  echo Local Python environment is missing. Please check the project setup.
  pause
  exit /b 1
)
"%~dp0runtime\envs\reconstruction\Scripts\python.exe" "%~dp0scripts\local_preview\launcher.py" %*
set "RUN_RESULT=%ERRORLEVEL%"
if not "%RUN_RESULT%"=="0" pause
exit /b %RUN_RESULT%
