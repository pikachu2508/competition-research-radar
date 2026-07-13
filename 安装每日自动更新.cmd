@echo off
chcp 65001 >nul
pwsh.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0安装每日自动更新.ps1"
