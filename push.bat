@echo off
REM Method 1: Refresh PATH then run git
set "msg=%~1"
if "%msg%"=="" set "msg=Update: %date% %time%"

echo Pushing to GitLab...
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
"$env:Path = [System.Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [System.Environment]::GetEnvironmentVariable('Path','User'); ^
Set-Location '%~dp0'; ^
git add .; ^
git commit -m \"%msg%\" 2>&1 | Out-Null; ^
git push; ^
Write-Host ''; Write-Host 'Done!'"
