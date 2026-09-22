@echo off
chcp 65001 >nul
setlocal
rem 鲸鱼娘余额挂件启动器：自动定位脚本目录与系统 Python，不写死任何绝对路径

set "SCRIPT=%~dp0whale_widget.pyw"

if not exist "%SCRIPT%" (
  echo [错误] 未找到 whale_widget.pyw
  echo 请确保本 .bat 与 whale_widget.pyw 放在同一目录。
  pause
  exit /b 1
)

rem 1) 优先 pythonw（无控制台窗口）
where pythonw >nul 2>nul
if %errorlevel%==0 (
  start "" pythonw "%SCRIPT%"
  exit /b 0
)

rem 2) 其次 pyw（Python 官方启动器的无窗口版）
where pyw >nul 2>nul
if %errorlevel%==0 (
  start "" pyw "%SCRIPT%"
  exit /b 0
)

rem 3) 最后 python（会附带一个控制台窗口）
where python >nul 2>nul
if %errorlevel%==0 (
  start "" python "%SCRIPT%"
  exit /b 0
)

echo [错误] 未找到 Python。
echo 请先安装 Python 3，安装时勾选 "Add Python to PATH"。
echo 下载地址: https://www.python.org/downloads/
pause
exit /b 1