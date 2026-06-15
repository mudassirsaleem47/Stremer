@echo off
setlocal

:: Check Administrator rights
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] Requesting Administrator privileges...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

set "SERVICE_DIR=C:\Program Files\GlobalServer"
set "TARGET_EXE=%SERVICE_DIR%\global-server.exe"

echo [+] Terminating any running server instance to release file locks...
taskkill /f /im global-server.exe >nul 2>&1

echo [+] Creating installation directory if not exists...
if not exist "%SERVICE_DIR%" mkdir "%SERVICE_DIR%" >nul 2>&1

echo [+] Downloading latest target files from GitHub...
powershell -Command "$ProgressPreference = 'SilentlyContinue'; [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/mudassirsaleem47/Stremer/main/target/global-server.exe' -OutFile '%TARGET_EXE%'; Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/mudassirsaleem47/Stremer/main/target/config_global.txt' -OutFile '%SERVICE_DIR%\config_global.txt';"

if not exist "%TARGET_EXE%" (
    echo.
    echo [ERROR] Download failed! Please check your internet connection or repository path.
    pause
    exit /b 1
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
