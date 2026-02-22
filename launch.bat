@echo off
set PYTHONPATH=%~dp0
start "" "%~dp0venv\Scripts\pythonw.exe" -m threecolref %*
