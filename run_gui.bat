@echo off
cd /d "%~dp0"
title BoomBeach Sonar Auto
echo Starting GUI with conda environment boom-beach-sonar...
conda run --no-capture-output -n boom-beach-sonar python gui_app.py
if errorlevel 1 (
  echo.
  echo Failed to start. Verify environment: conda info --envs
  pause
)
