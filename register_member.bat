@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

set "SERVER_URL=http://192.168.1.142:8000/api/members"
if not "%~1"=="" (
  set "SERVER_URL=%~1"
)

echo === Wi-Fi モニター メンバー登録 ===
set /p "STUDENT_ID=学籍番号を入力してください: "
if "%STUDENT_ID%"=="" (
  echo 学籍番号は必須です。
  goto :eof
)

set /p "NAME=名前を入力してください（日本語可）: "
if "%NAME%"=="" (
  echo 名前は必須です。
  goto :eof
)

for /f "usebackq tokens=* delims=" %%A in (
  `powershell -NoProfile -Command " $mac = (Get-NetAdapter | Where-Object {$_.Status -eq 'Up'} | Select-Object -First 1 -ExpandProperty MacAddress); if (-not $mac) { $mac = (Get-NetAdapter | Select-Object -First 1 -ExpandProperty MacAddress) }; $mac "`
) do (
  set "MAC=%%A"
)

if "%MAC%"=="" (
  echo MAC アドレスの取得に失敗しました。
  goto :eof
)

echo 使用する MAC アドレス: %MAC%
echo サーバーへ送信しています... (%SERVER_URL%)

powershell -NoProfile -Command ^
  "[Console]::OutputEncoding = [Text.Encoding]::UTF8;" ^
  "[Console]::InputEncoding  = [Text.Encoding]::UTF8;" ^
  "$sid  = [Text.Encoding]::UTF8.GetString([Text.Encoding]::Default.GetBytes($env:STUDENT_ID));" ^
  "$name = [Text.Encoding]::UTF8.GetString([Text.Encoding]::Default.GetBytes($env:NAME));" ^
  "$mac  = $env:MAC;" ^
  "$payload = @{ student_id = $sid; name = $name; mac = $mac } | ConvertTo-Json -Compress;" ^
  "Invoke-RestMethod -Method Post -Uri '%SERVER_URL%' -ContentType 'application/json; charset=utf-8' -Body ([System.Text.Encoding]::UTF8.GetBytes($payload)) | ConvertTo-Json -Depth 3 | Write-Host"

if errorlevel 1 (
  echo リクエスト失敗…
) else (
  echo 登録が完了しました。
)

endlocal
