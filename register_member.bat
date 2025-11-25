@echo off
setlocal enabledelayedexpansion

set "SERVER_URL=http://127.0.0.1:8000/api/members"
if not "%~1"=="" (
  set "SERVER_URL=%~1"
)

echo === Wi-Fi Monitor Member Registration ===
set /p "STUDENT_ID=Enter student ID: "
if "%STUDENT_ID%"=="" (
  echo Student ID is required.
  goto :eof
)

set /p "NAME=Enter name: "
if "%NAME%"=="" (
  echo Name is required.
  goto :eof
)

for /f "usebackq tokens=* delims=" %%A in (`powershell -NoProfile -Command " $mac = (Get-NetAdapter | Where-Object {$_.Status -eq 'Up'} | Select-Object -First 1 -ExpandProperty MacAddress); if (-not $mac) { $mac = (Get-NetAdapter | Select-Object -First 1 -ExpandProperty MacAddress) } ; if ($mac) { $mac } "`) do (
  set "MAC=%%A"
)

if "%MAC%"=="" (
  echo Failed to detect a MAC address automatically.
  goto :eof
)

echo Using MAC address: %MAC%
echo Sending data to %SERVER_URL% ...

powershell -NoProfile -Command ^
  "$ErrorActionPreference = 'Stop';" ^
  "$payload = @{ student_id = $env:STUDENT_ID; name = $env:NAME; mac = $env:MAC } | ConvertTo-Json;" ^
  "$response = Invoke-RestMethod -Method Post -Uri '%SERVER_URL%' -ContentType 'application/json' -Body $payload;" ^
  "Write-Host 'Registration succeeded.';" ^
  "$response | ConvertTo-Json -Depth 2"

if errorlevel 1 (
  echo Request failed.
) else (
  echo Done.
)

endlocal
