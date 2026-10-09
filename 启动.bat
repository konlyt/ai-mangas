@echo off
chcp 65001 >nul
title AI Manga Studio - Start
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
echo.
pause
