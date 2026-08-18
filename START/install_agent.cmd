@echo off
cd /d "%~dp0.."
title Paychain Agent Installer
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\install_agent.ps1"
echo.
pause
