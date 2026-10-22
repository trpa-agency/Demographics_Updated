@echo off
echo Build append and retire files that fix known errors in the published tables.
echo This reads the services only. It does not change any data.
echo.
set /p DL=Also download the correct Census codes (needs an API key)? (Y/N): 
if /i "%DL%"=="Y" (
  call "%~dp0_python.bat" corrections --download
) else (
  call "%~dp0_python.bat" corrections
)
echo.
echo Read outputs\corrections\<date>\README.txt before loading anything.
pause
