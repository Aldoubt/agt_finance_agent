@echo off
chcp 65001 >nul
cd /d "%~dp0"
python tools\review_photos.py
if errorlevel 1 pause
