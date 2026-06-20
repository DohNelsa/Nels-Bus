@echo off
title GARANTI EXPRESS - Dev Server
cd /d "%~dp0.."
echo.
echo  GARANTI EXPRESS - starting from:
echo  %CD%
echo.
echo  If port 8000 is busy, close other terminals running runserver first.
echo.
powershell -ExecutionPolicy Bypass -File "%~dp0run-dev.ps1"
pause
