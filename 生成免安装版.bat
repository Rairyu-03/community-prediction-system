@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Build Portable Community Prediction System

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\build-portable.ps1"
if errorlevel 1 (
    echo.
    echo Portable build failed. Please check the message above.
    pause
    exit /b 1
)

echo.
echo Portable build completed successfully.
pause
endlocal
