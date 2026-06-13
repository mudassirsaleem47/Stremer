@echo off
setlocal

set SRC_DIR=%~dp0dist
set SRC_EXE=%SRC_DIR%\ScreenMirrorProUI.exe
set TARGET_DIR=C:\Program Files\ScreenMirrorPro
set TARGET_EXE=%TARGET_DIR%\ScreenMirrorProUI.exe

net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

if not exist "%SRC_EXE%" (
    echo Missing EXE: %SRC_EXE%
    echo First run build_ui_exe.bat.
    exit /b 1
)

mkdir "%TARGET_DIR%" >nul 2>&1
copy /Y "%SRC_EXE%" "%TARGET_EXE%" >nul
copy /Y "%~dp0StartwindowsService.bat" "%TARGET_DIR%\StartwindowsService.bat" >nul
copy /Y "%~dp0requirements-desktop.txt" "%TARGET_DIR%\requirements-desktop.txt" >nul

echo Installed to %TARGET_EXE%
echo Launch the app from Start menu or by running the EXE directly.
endlocal