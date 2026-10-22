@echo off
echo List and check what is published in the Census Data service (read only)
call "%~dp0_python.bat" inventory
call "%~dp0_python.bat" qaqc --service --label published_service
pause
