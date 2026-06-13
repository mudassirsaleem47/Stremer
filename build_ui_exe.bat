@echo off
setlocal

set ROOT=%~dp0
set APP=%ROOT%Code\app with UI.py
set DIST=%ROOT%dist
set BUILD=%ROOT%build

if not exist "%ROOT%.venv\Scripts\python.exe" (
    echo .venv not found. Activate or create the virtual environment first.
    exit /b 1
)

"%ROOT%.venv\Scripts\python.exe" -m pip install --upgrade pyinstaller
if errorlevel 1 exit /b 1

"%ROOT%.venv\Scripts\python.exe" -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onefile ^
    --windowed ^
    --name ScreenMirrorProUI ^
    --distpath "%DIST%" ^
    --workpath "%BUILD%" ^
    --specpath "%ROOT%" ^
    "%APP%"

if errorlevel 1 exit /b 1

echo.
echo Build complete.
echo EXE: %DIST%\ScreenMirrorProUI.exe
endlocal