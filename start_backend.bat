@echo off
title GreenLife Organics - Website Server
cd /d "%~dp0"
echo GreenLife website launcher
echo Password text will not appear while you type. Enter at least 10 characters, then confirm it.
echo Keep this window open while using the website.
".venv\Scripts\python.exe" run_backend.py
echo.
echo The website server stopped. Check any error message above.
pause
