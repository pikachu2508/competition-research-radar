$ErrorActionPreference = 'Stop'
$Script = Join-Path $PSScriptRoot 'run-daily.ps1'
$Action = New-ScheduledTaskAction -Execute 'pwsh.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Script`""
$Trigger = New-ScheduledTaskTrigger -Daily -At '08:00'
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 20)
Register-ScheduledTask -TaskName '竞赛研究雷达-每日更新' -Action $Action -Trigger $Trigger -Settings $Settings -Description '每日检查物理实验竞赛学术信源并更新本地页面' -Force
$EveningScript = Join-Path $PSScriptRoot 'run-evening.ps1'
$EveningAction = New-ScheduledTaskAction -Execute 'pwsh.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$EveningScript`""
$EveningTrigger = New-ScheduledTaskTrigger -Daily -At '20:00'
Register-ScheduledTask -TaskName '竞赛研究雷达-晚间精选' -Action $EveningAction -Trigger $EveningTrigger -Settings $Settings -Description '每天晚上筛选当天值得关注的新内容并发送飞书' -Force
$WeeklyScript = Join-Path $PSScriptRoot 'run-weekly.ps1'
$WeeklyAction = New-ScheduledTaskAction -Execute 'pwsh.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$WeeklyScript`""
$WeeklyTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At '20:10'
Register-ScheduledTask -TaskName '竞赛研究雷达-每周精选' -Action $WeeklyAction -Trigger $WeeklyTrigger -Settings $Settings -Description '每周生成竞赛研究雷达精选并发送飞书' -Force
Write-Host '自动更新已设置：每天 08:00 检查，20:00 发送晚间精选，每周日 20:10 生成周报。' -ForegroundColor Green
Read-Host '按 Enter 关闭'
