@echo off
title Stop LeadSweep

echo Stopping LeadSweep services...

powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 8000,5173 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }" >nul 2>&1

if exist ".ports.txt" del /f /q ".ports.txt" >nul 2>&1
if exist ".pids.txt" del /f /q ".pids.txt" >nul 2>&1

echo Application successfully stopped.
powershell -NoProfile -Command "Start-Sleep -Seconds 1"
