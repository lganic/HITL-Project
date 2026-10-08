@echo off
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel% equ 0 (
  py -3 launch_gui.pyw
) else (
  python launch_gui.pyw
)
pause
