@echo off
chcp 65001 >nul
title AI Manga Studio - Stop
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop.ps1"
echo.
pause
