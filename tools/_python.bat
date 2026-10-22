@echo off
rem Finds the ArcGIS Pro Python environment and runs the toolkit with it.
rem To use a different Python, set TRPA_PYTHON to its python.exe before running.
set "REPO=%~dp0.."
set "PYTHONPATH=%REPO%\src"
cd /d "%REPO%"
if defined TRPA_PYTHON (
  "%TRPA_PYTHON%" -m trpa_demographics %*
) else if exist "%PROGRAMFILES%\ArcGIS\Pro\bin\Python\Scripts\propy.bat" (
  call "%PROGRAMFILES%\ArcGIS\Pro\bin\Python\Scripts\propy.bat" -m trpa_demographics %*
) else (
  python -m trpa_demographics %*
)
