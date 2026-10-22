@echo off
echo Check config\groupings.csv for double counting and missing variables
call "%~dp0_python.bat" qaqc --config --label groupings
pause
