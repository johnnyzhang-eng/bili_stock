@echo off
REM ============================================================
REM 每日收盘后自动运行热点板块选股信号并推送钉钉
REM 建议用 Windows 任务计划程序设置为每个工作日 15:10 运行
REM
REM 手动运行:         run_daily_signal.bat
REM 只打印不推送:     run_daily_signal.bat --no-push
REM ============================================================

cd /d C:\jz_code\Bili_Stock
if not exist logs mkdir logs

set PUSH_FLAG=--push
if "%1"=="--no-push" set PUSH_FLAG=

echo [%date% %time%] === 热点板块信号 ====================== >> logs\signal_daily.log
C:\Python314\python.exe research\factors_v2\run_hot_sector_signal.py %PUSH_FLAG% >> logs\signal_daily.log 2>&1
echo [%date% %time%] 完成 (exit %errorlevel%) >> logs\signal_daily.log

echo [%date% %time%] === 每日简报 ========================== >> logs\signal_daily.log
C:\Python314\python.exe research\data_prep\daily_briefing.py >> logs\signal_daily.log 2>&1
echo [%date% %time%] 简报完成 (exit %errorlevel%) >> logs\signal_daily.log
