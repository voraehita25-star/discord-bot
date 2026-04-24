@echo off
:: Quick launcher for manager.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0manager.ps1" %*
