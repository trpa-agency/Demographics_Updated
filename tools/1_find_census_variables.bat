@echo off
echo Find Census variables and add them to config\variables.csv
echo.
set /p TABLE=Census table code (for example B25003): 
set /p YEAR=Data year to look up (for example 2023): 
set /p CATEGORY=TRPA category name for these variables (for example Housing Units): 
set /p ADD=Add them to config\variables.csv now? (Y/N): 
if /i "%ADD%"=="Y" (
  call "%~dp0_python.bat" find --table %TABLE% --year %YEAR% --category "%CATEGORY%" --add
) else (
  call "%~dp0_python.bat" find --table %TABLE% --year %YEAR% --category "%CATEGORY%"
)
echo.
echo Open config\variables.csv in Excel to review names before downloading.
pause
