@echo off
chcp 65001 >nul
setlocal

REM 确保能找到 Git（解决终端 PATH 未刷新的问题）
set "GIT_PATH=C:\Program Files\Git\cmd"
if exist "%GIT_PATH%\git.exe" (
    set "PATH=%GIT_PATH%;%PATH%"
)

if "%~1"=="" (
    set "msg=Update: %date% %time%"
) else (
    set "msg=%~1"
)

echo 正在推送到 GitLab...
echo.

where git >nul 2>&1
if errorlevel 1 (
    echo 错误: 未找到 Git，请确认已安装 Git 并重启 Cursor 终端。
    exit /b 1
)

git add .
if errorlevel 1 exit /b 1

git commit -m "%msg%" 2>nul
REM 无论是否有新提交，都尝试推送（可能有未推送的旧提交）
git push
if errorlevel 1 exit /b 1

echo.
echo 推送完成!
exit /b 0
