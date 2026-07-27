# 注册 Windows 任务计划：每个工作日 15:10 运行热点板块信号
# 以管理员身份运行此脚本：Right-click -> Run as Administrator
# 或在PowerShell中: ! powershell -ExecutionPolicy Bypass -File setup_task_scheduler.ps1

$TaskName   = "BiliStock_DailySignal"
$ScriptPath = "C:\jz_code\Bili_Stock\run_daily_signal.bat"

# 删除旧任务（如存在）
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

$Action  = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$ScriptPath`""
$Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "15:10"
$Settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
              -StartWhenAvailable -RunOnlyIfNetworkAvailable

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger `
    -Settings $Settings -RunLevel Highest -Description "A股热点板块信号每日推送" -Force

Write-Host "OK 任务已注册: $TaskName  (每个工作日 15:10)"
Write-Host "查看任务: Get-ScheduledTask -TaskName $TaskName"
Write-Host "立即测试: Start-ScheduledTask -TaskName $TaskName"
