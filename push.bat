@echo off
echo Pushing to GitLab...
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command "$env:Path = [System.Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [System.Environment]::GetEnvironmentVariable('Path','User'); Set-Location (Split-Path -Parent '%~f0'); $msg = '%~1'; if ([string]::IsNullOrEmpty($msg)) { $msg = 'Update: ' + (Get-Date -Format 'yyyy-MM-dd HH:mm') }; git add .; git commit -m $msg 2>&1 | Out-Null; git push; Write-Host ''; Write-Host 'Done!'"
