@echo off
chcp 65001 >nul
setlocal
set "RADAR_DIR=%~dp0"
set "RADAR_PAGE=%RADAR_DIR%output\index.html"

if exist "%RADAR_PAGE%" (
  start "" "%RADAR_PAGE%"
  set "PAGE_ALREADY_OPEN=1"
  echo 雷达页面已打开，正在检查最新内容……
) else (
  echo 首次生成雷达页面，请稍候……
)

python "%RADAR_DIR%radar.py" --notify
if errorlevel 1 goto :failed

if not exist "%RADAR_PAGE%" goto :failed
if not defined PAGE_ALREADY_OPEN start "" "%RADAR_PAGE%"
echo.
echo 更新完成。若页面已经打开，请刷新浏览器查看最新内容。
echo 按任意键关闭此窗口。
pause >nul
exit /b 0

:failed
echo.
echo 更新没有完全成功，窗口将保留以便查看原因。
if exist "%RADAR_DIR%logs\latest.log" type "%RADAR_DIR%logs\latest.log"
echo.
echo 按任意键关闭此窗口。
pause >nul
exit /b 1
