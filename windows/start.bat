@echo off
setlocal enabledelayedexpansion
title ComfyUI MixMedia
rem Запуск ComfyUI + окно приложения (Chrome в режиме --app).
rem Лежит рядом с папкой ComfyUI и venv, которые создал install.ps1.

set "APP=%~dp0"
set "COMFY=%APP%ComfyUI"
set "PY=%APP%venv\Scripts\python.exe"
set "URL=http://127.0.0.1:8188"
set "PROFILE=%LOCALAPPDATA%\ComfyUI MixMedia\Chrome"
set "LOG=%LOCALAPPDATA%\ComfyUI Mix Media\server.log"

if not exist "%PY%" (
  echo Не найден python: "%PY%"
  echo Сначала запусти install.ps1
  pause
  exit /b 1
)
if not exist "%PROFILE%" mkdir "%PROFILE%"
if not exist "%LOCALAPPDATA%\ComfyUI Mix Media" mkdir "%LOCALAPPDATA%\ComfyUI Mix Media"

rem сервер уже поднят?
curl -s -o NUL --max-time 2 "%URL%" >NUL 2>&1
if not errorlevel 1 goto open

echo Запускаю ComfyUI...
start "" /min "%PY%" "%COMFY%\main.py" --listen 127.0.0.1 --port 8188 >>"%LOG%" 2>&1

set /a tries=0
:wait
curl -s -o NUL --max-time 2 "%URL%" >NUL 2>&1
if not errorlevel 1 goto open
set /a tries+=1
if !tries! geq 90 goto failed
timeout /t 1 /nobreak >NUL
goto wait

:failed
echo ComfyUI не поднялся за 90 секунд. Смотри лог: "%LOG%"
pause
exit /b 1

:open
set "CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"

if exist "%CHROME%" (
  start "" "%CHROME%" --app="%URL%" --user-data-dir="%PROFILE%" --no-first-run --no-default-browser-check
) else (
  start "" "%URL%"
)
exit /b 0
