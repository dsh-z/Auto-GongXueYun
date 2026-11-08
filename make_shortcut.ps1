# 为面板创建桌面快捷方式（带图标、可直接双击）
$ErrorActionPreference = 'Stop'

$Dir      = $PSScriptRoot
$Bat      = Join-Path $Dir '启动面板.bat'
$Desktop  = [Environment]::GetFolderPath('Desktop')
$LnkPath  = Join-Path $Desktop '工学云打卡面板.lnk'

if (-not (Test-Path $Bat)) { throw "找不到 $Bat" }

# 用 python.exe 的图标，比默认 bat 图标好看且一眼能认出
$PyIcon = $null
try {
    $py = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
    if ($py) { $PyIcon = $py }
} catch {}

$Wsh = New-Object -ComObject WScript.Shell
$Lnk = $Wsh.CreateShortcut($LnkPath)
$Lnk.TargetPath       = $Bat
$Lnk.WorkingDirectory = $Dir
$Lnk.Description      = '工学云打卡面板 —— 查看今日打卡状态、日历与云端运行记录'
$Lnk.WindowStyle      = 7          # 最小化启动，避免弹黑框
if ($PyIcon) { $Lnk.IconLocation = "$PyIcon,0" }
$Lnk.Save()

[System.Runtime.InteropServices.Marshal]::ReleaseComObject($Wsh) | Out-Null

if (Test-Path $LnkPath) {
    Write-Host "✓ 桌面快捷方式已创建：$LnkPath"
} else {
    Write-Host "✗ 快捷方式创建失败"
    exit 1
}
