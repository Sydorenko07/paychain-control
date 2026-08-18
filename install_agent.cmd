@echo off
cd /d "%~dp0"
title Paychain Agent Installer
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_agent.ps1"
echo.
pause
