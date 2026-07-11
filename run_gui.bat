@echo off
cd /d "%~dp0"
title BoomBeach Sonar Auto
echo Starting GUI...
python gui_app.py
if errorlevel 1 (
  echo.
  echo Failed to start. Try: pip install -r requirements.txt
  pause
)
