# =============================================================================
#  工学云开机自动打卡 —— 触发 GitHub Actions
#
#  工作方式：
#    开机登录后由计划任务调用本脚本 -> 用 GitHub API 触发 workflow ->
#    云端跑 python index.py -> 补一条今日打卡（已有记录则跳过）
#
#  为什么用 API 触发而不是本地跑：
#    你的坐标靠 anydoor 注入，本地直连工学云会用真实 IP/真实定位，
#    反而暴露。云端跑是纯协议打卡，不依赖本机 mock 环境。
#
#  使用前：把下面的 GH_TOKEN 换成你自己的 token（只需 workflow 权限）。
#  生成：https://github.com/settings/tokens  选 Fine-grained，
#        仅授权 dsh-z/Auto-GongXueYun 仓库的 Actions: Read and write
# =============================================================================

param(
    [switch]$NoWait,      # 不等待结果（开机时用，快照退场）
    [switch]$DryRun       # 只检查环境，不真正触发
)

$ErrorActionPreference = 'Stop'

# ---- 配置区 -----------------------------------------------------------------
# token 不写进脚本！脚本会被提交到仓库，GitHub Push Protection 会拦截，
# 而且一旦进过历史就等于永久泄露。改从本机文件读取（同目录、已 gitignore）。
$TokenFile = Join-Path $PSScriptRoot 'gh_token.txt'
$OWNER    = 'dsh-z'
$REPO     = 'Auto-GongXueYun'
$LOG      = Join-Path $PSScriptRoot 'clockin.log'
# -----------------------------------------------------------------------------

function Write-Log($msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
    Write-Host $line
    try { Add-Content -Path $LOG -Value $line -Encoding UTF8 } catch {}
}

function Invoke-GH {
    param($Path, $Method = 'GET', $Body)
    $headers = @{
        'Authorization'        = "Bearer $GH_TOKEN"
        'Accept'               = 'application/vnd.github+json'
        'User-Agent'           = 'gxy-boot'
        'X-GitHub-Api-Version' = '2022-11-28'
    }
    $args = @{
        Uri                = "https://api.github.com$Path"
        Method             = $Method
        Headers            = $headers
        TimeoutSec         = 40
        UseBasicParsing    = $true
    }
    if ($Body) {
        $args['Body']        = ($Body | ConvertTo-Json -Compress)
        $args['ContentType'] = 'application/json'
    }
    return Invoke-RestMethod @args
}

# ---- 0. 前置检查 -------------------------------------------------------------
if (-not (Test-Path $TokenFile)) {
    Write-Log "找不到 token 文件：$TokenFile"
    Write-Log '请把 GitHub token（需要该仓库 Actions: Read and write 权限）单独写入该文件'
    exit 2
}
$GH_TOKEN = (Get-Content $TokenFile -Raw).Trim()
if ([string]::IsNullOrWhiteSpace($GH_TOKEN)) {
    Write-Log "token 文件为空：$TokenFile"
    exit 2
}

Write-Log '=== 开机打卡开始 ==='

# 网络就绪等待：开机后网络往往还没通，最多等 5 分钟
$ready = $false
for ($i = 1; $i -le 30; $i++) {
    try {
        $null = Invoke-GH "/repos/$OWNER/$REPO" 
        $ready = $true
        Write-Log "网络与凭据就绪（第 $i 次尝试）"
        break
    } catch {
        if ($i -eq 1) { Write-Log "等待网络/凭据... ($($_.Exception.Message))" }
        Start-Sleep -Seconds 10
    }
}
if (-not $ready) {
    Write-Log '网络或 token 不可用，放弃本次开机打卡'
    exit 1
}

if ($DryRun) {
    Write-Log 'DryRun：环境检查通过，未触发'
    exit 0
}

# ---- 1. 每天只触发一次（本机侧去重，省额度也避免重复） ---------------------
$stampFile = Join-Path $PSScriptRoot 'last-run.txt'
$today = Get-Date -Format 'yyyy-MM-dd'
if (Test-Path $stampFile) {
    $last = (Get-Content $stampFile -Raw).Trim()
    if ($last -eq $today) {
        Write-Log "今天($today)已触发过，跳过（如需重跑请删除 last-run.txt）"
        exit 0
    }
}

# ---- 2. 找到 workflow 并触发 -------------------------------------------------
try {
    $wfs = Invoke-GH "/repos/$OWNER/$REPO/actions/workflows"
    $wf = $wfs.workflows | Where-Object { $_.name -eq '打卡' } | Select-Object -First 1
    if (-not $wf) { $wf = $wfs.workflows | Select-Object -First 1 }
    if (-not $wf) { Write-Log '没有找到可用的 workflow'; exit 1 }

    Write-Log "触发 workflow: $($wf.name) (id=$($wf.id))"
    $null = Invoke-GH "/repos/$OWNER/$REPO/actions/workflows/$($wf.id)/dispatches" 'POST' @{ ref = 'main' }
    Set-Content -Path $stampFile -Value $today -Encoding ASCII
    Write-Log '已提交触发请求'
} catch {
    Write-Log "触发失败: $($_.Exception.Message)"
    exit 1
}

if ($NoWait) {
    Write-Log '不等待结果（NoWait）'
    exit 0
}

# ---- 3. 等结果（最多 5 分钟）------------------------------------------------
for ($i = 1; $i -le 30; $i++) {
    Start-Sleep -Seconds 10
    try {
        $runs = Invoke-GH "/repos/$OWNER/$REPO/actions/runs?per_page=1"
        $run = $runs.workflow_runs | Select-Object -First 1
        if ($run -and $run.status -eq 'completed') {
            Write-Log "完成：$($run.conclusion)  $($run.html_url)"
            if ($run.conclusion -ne 'success') { exit 1 }
            exit 0
        }
    } catch {
        Write-Log "轮询异常: $($_.Exception.Message)"
    }
}
Write-Log '等待超时，请稍后在 Actions 页查看'
exit 0
