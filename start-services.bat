@echo off
setlocal

:: Path variables
set SERVICE_DIR=C:\Program Files\GlobalServer
set TARGET_EXE=%SERVICE_DIR%\global-server.exe
set SRC_EXE=%~dp0dist\global-server.exe
set SRC_CFG=%~dp0Code\config_global.txt

:: Check Administrator rights
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] Requesting Administrator privileges...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)


:: Create C:\Program Files\GlobalServer directory
if not exist "%SERVICE_DIR%" (
    echo [+] Creating installation directory: %SERVICE_DIR%
    mkdir "%SERVICE_DIR%" >nul 2>&1
)

echo [+] Terminating any running server instance to release file locks...
taskkill /f /im global-server.exe >nul 2>&1

:: Copy global-server.exe
if exist "%SRC_EXE%" (
    echo [+] Copying global-server.exe to Program Files...
    copy /Y "%SRC_EXE%" "%TARGET_EXE%" >nul
) else (
    :: Fallback: Check if user copied global-server.exe directly in current directory
    if exist "%~dp0global-server.exe" (
        if /I "%~dp0global-server.exe" NEQ "%TARGET_EXE%" (
            echo [+] Copying global-server.exe to Program Files...
            copy /Y "%~dp0global-server.exe" "%TARGET_EXE%" >nul
        )
    ) else (
        echo [ERROR] global-server.exe not found in dist\ or current folder!
        echo Please build the executable first using build_server.bat.
        pause
        exit /b 1
    )
)

:: Copy config_global.txt
if exist "%SRC_CFG%" (
    echo [+] Copying URL config file...
    copy /Y "%SRC_CFG%" "%SERVICE_DIR%\config_global.txt" >nul
) else (
    if exist "%~dp0config_global.txt" (
        if /I "%~dp0config_global.txt" NEQ "%SERVICE_DIR%\config_global.txt" (
            echo [+] Copying URL config file...
            copy /Y "%~dp0config_global.txt" "%SERVICE_DIR%\config_global.txt" >nul
        )
    ) else (
        echo [+] Creating default config_global.txt...
        echo wss://stremer-production.up.railway.app > "%SERVICE_DIR%\config_global.txt"
    )
)

:: Firewall Rule Setup
echo [+] Configuring Windows Firewall rules...
:: Allow port 9999 for local LAN streaming
netsh advfirewall firewall show rule name="GlobalServerLAN" >nul 2>&1
if %errorlevel% neq 0 (
    netsh advfirewall firewall add rule name="GlobalServerLAN" dir=in action=allow protocol=TCP localport=9999 >nul 2>&1
    echo     - Port 9999 local LAN rule added.
) else (
    echo     - Port 9999 rule already exists.
)

:: Allow the app binary itself
netsh advfirewall firewall show rule name="GlobalServerApp" >nul 2>&1
if %errorlevel% neq 0 (
    netsh advfirewall firewall add rule name="GlobalServerApp" dir=in action=allow program="%TARGET_EXE%" enable=yes >nul 2>&1
    echo     - Binary application rule added.
) else (
    :: Update rules in case it changed path
    netsh advfirewall firewall delete rule name="GlobalServerApp" >nul 2>&1
    netsh advfirewall firewall add rule name="GlobalServerApp" dir=in action=allow program="%TARGET_EXE%" enable=yes >nul 2>&1
    echo     - Binary application rule updated.
)

:: Startup Registry Key Setup (Autostart on login)
echo [+] Registering startup entry in Registry...
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "GlobalServer" /t REG_SZ /d "\"%TARGET_EXE%\"" /f >nul

:: Launch the service silently
echo [+] Starting the service silently in background...
start "" /min "%TARGET_EXE%"

echo.
echo [SUCCESS] Setup complete! The server is now running silently.
echo Logs are being written to: %SERVICE_DIR%\global-server.log
echo.
pause
endlocal
