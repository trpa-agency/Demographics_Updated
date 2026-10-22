@echo off
echo Download, group, summarize, and check Census data for one or more years
echo.
set /p YEAR=First year (for example 2024): 
set /p YEAREND=Last year (press Enter for one year only): 
if "%YEAREND%"=="" set "YEAREND=%YEAR%"
call "%~dp0_python.bat" run --year %YEAR% --year-end %YEAREND% --compare-service
echo.
echo Results are in the outputs folder. Open outputs\qaqc\...\qaqc_report.html first.
pause
