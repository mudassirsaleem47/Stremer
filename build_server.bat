@echo off
setlocal
set ROOT=%~dp0
set APP=%ROOT%Code\global-server.py
set DIST=%ROOT%dist
set BUILD=%ROOT%build

if not exist "%ROOT%.venv\Scripts\python.exe" (
    echo .venv not found.
    exit /b 1
)

echo Compiling global-server.py to single silent executable...
"%ROOT%.venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --windowed --name global-server --distpath "%DIST%" --workpath "%BUILD%" --specpath "%ROOT%." "%ROOT%Code\global-server.py"

if errorlevel 1 (
    echo PyInstaller build failed!
    exit /b 1
)

echo.
echo Build complete!
echo EXE is ready at: %DIST%\global-server.exe
endlocal
