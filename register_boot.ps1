# =============================================================================
#  注册「开机自动打卡」计划任务
#
#  用法（本目录打开 PowerShell）：
#     Set-ExecutionPolicy -Scope Process Bypass -Force
#     .\register_boot.ps1              # 注册（登录后延迟 2 分钟执行）
#     .\register_boot.ps1 -Delay 5     # 登录后延迟 5 分钟（等网络更稳）
#     .\register_boot.ps1 -Status      # 查看状态
#     .\register_boot.ps1 -Remove      # 取消开机自启
#     .\register_boot.ps1 -RunNow      # 立刻试跑一次
#
#  为什么延迟：开机后网卡、DNS、代理往往要一会儿才就绪，
#  脚本自身也有 5 分钟重试，两层保险。
#  触发条件用「登录时」而不是「开机时」：开机时用户会话还没建好，
#  涉网请求容易失败；登录后执行更稳。
# =============================================================================

[CmdletBinding()]
param(
    [int]$Delay = 2,
    [switch]$Remove,
    [switch]$Status,
    [switch]$RunNow
)

$ErrorActionPreference = 'Stop'
$Dir      = $PSScriptRoot
$Script   = Join-Path $Dir 'boot_clockin.ps1'
$TaskName = 'GXY_BootClockIn'

if (-not (Test-Path $Script)) { throw "找不到 $Script" }

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "已取消开机自启（$TaskName）"
    return
}

if ($Status) {
    $t = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $t) { Write-Host "未注册"; return }
    $i = $t | Get-ScheduledTaskInfo
    Write-Host ("任务     : {0}" -f $t.TaskName)
    Write-Host ("状态     : {0}" -f $t.State)
    Write-Host ("上次运行 : {0}  结果={1}" -f $i.LastRunTime, $i.LastTaskResult)
    Write-Host ("下次运行 : {0}" -f $i.NextRunTime)
    Write-Host ("日志     : {0}" -f (Join-Path $Dir 'clockin.log'))
    return
}

if ($RunNow) {
    Write-Host "手动试跑..."
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Script
    return
}

# Windows PowerShell 5.1 默认按 ANSI 读脚本，含中文的 UTF-8 无 BOM 会乱码，
# 所以用 -File 调用时统一走 powershell.exe 并确保文件带 BOM。
$bytes = [System.IO.File]::ReadAllBytes($Script)
if (-not ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF)) {
    $txt = [System.IO.File]::ReadAllText($Script, [System.Text.Encoding]::UTF8)
    [System.IO.File]::WriteAllText($Script, $txt, (New-Object System.Text.UTF8Encoding $true))
    Write-Host "已为 boot_clockin.ps1 补写 UTF-8 BOM（避免中文乱码）"
}

$Action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument ('-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}" -NoWait' -f $Script) `
    -WorkingDirectory $Dir

# AtLogOn：用户登录后触发。延迟用 Delay 参数控制，避开开机网络未就绪。
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$Trigger.Delay = "PT${Delay}M"

$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 20) `
    -Priority 7

# 交互登录用户，无需保存密码，也不需要管理员权限
$Principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger `
    -Settings $Settings -Principal $Principal `
    -Description '开机登录后触发工学云自动打卡（每天一条，脚本内去重）' -Force | Out-Null

Write-Host @"
✓ 已注册开机自启：$TaskName
   触发时机：登录后延迟 $Delay 分钟
   执行内容：$Script -NoWait
   运行日志：$(Join-Path $Dir 'clockin.log')

说明：
  - 脚本内部按日期去重（last-run.txt），同一天多次登录只触发一次；
    云端也有去重（今日已有记录就跳过），双保险。
  - 想每天固定的其他时机补一次，可再加一条定时任务（可选）：
      .\register_boot.ps1 -Delay 0   然后手动把触发改为 Daily
  - 临时想重跑：删除 last-run.txt 后执行 .\register_boot.ps1 -RunNow
  - 取消：.\register_boot.ps1 -Remove
"@
