@echo off
rem Opens the Demographic Data Explorer through a small web server on this computer.
rem Browsers block a page opened from disk from reading the config folder, so the page
rem needs to be served. The server only answers this computer (127.0.0.1).
rem Close this window to stop the server.
set "REPO=%~dp0.."
set "PORT=8000"
if defined TRPA_PYTHON (
  set "PY="%TRPA_PYTHON%""
) else if exist "%PROGRAMFILES%\ArcGIS\Pro\bin\Python\Scripts\propy.bat" (
  set "PY=call "%PROGRAMFILES%\ArcGIS\Pro\bin\Python\Scripts\propy.bat""
) else (
  set "PY=python"
)
echo Opening http://127.0.0.1:%PORT%/explorer/index.html
echo Leave this window open while you use the Explorer. Close it to stop.
rem The browser opens after a few seconds, once the server has started.
start "" /min powershell -NoProfile -Command "Start-Sleep -Seconds 4; Start-Process 'http://127.0.0.1:%PORT%/explorer/index.html'"
%PY% -m http.server %PORT% --bind 127.0.0.1 --directory "%REPO%"
pause
