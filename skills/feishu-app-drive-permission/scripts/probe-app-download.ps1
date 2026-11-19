<#
.SYNOPSIS
    用飞书应用身份直测文件能否下载，判断是权限问题还是服务端问题。

.DESCRIPTION
    读取 app_id / app_secret，换一个全新的 tenant_access_token（不经过任何缓存），
    然后对指定文件调用下载接口。200 = 应用能读；403 = 应用确实无权限。

.PARAMETER EnvFile
    env 配置文件路径，需含 FEISHU_SOURCE_APP_ID 与 FEISHU_SOURCE_APP_SECRET

.PARAMETER FileToken
    要测试的文件 token，可传多个（逗号分隔）

.PARAMETER DocType
    文件类型，默认为 file

.EXAMPLE
    .\probe-app-download.ps1 -EnvFile "F:\proj\private\feishu-source.env" -FileToken "URHwbLNYIoyOgyx5rm2cm7UJnXb,EfGdbidSaoGPETxxYY5ceMiqnwb"
#>
param(
    [Parameter(Mandatory = $true)][string]$EnvFile,
    [Parameter(Mandatory = $true)][string[]]$FileToken,
    [string]$DocType = 'file'
)

# 清掉可能存在的死代理，避免 curl/Invoke 走空端口
Remove-Item Env:http_proxy, Env:https_proxy, Env:HTTP_PROXY, Env:HTTPS_PROXY -ErrorAction SilentlyContinue

if (-not (Test-Path $EnvFile)) { Write-Error "env 文件不存在: $EnvFile"; exit 1 }

$cfg = @{}
Get-Content $EnvFile -Encoding UTF8 | ForEach-Object {
    if ($_ -match '^\s*([A-Z_]+)\s*=\s*(.+)$') { $cfg[$matches[1]] = $matches[2].Trim() }
}
$appId = $cfg['FEISHU_SOURCE_APP_ID']
$appSecret = $cfg['FEISHU_SOURCE_APP_SECRET']
if (-not $appId -or -not $appSecret) { Write-Error "env 文件缺少 FEISHU_SOURCE_APP_ID / FEISHU_SOURCE_APP_SECRET"; exit 1 }

Write-Host "应用: $appId" -ForegroundColor Cyan
Write-Host "换取全新 tenant_access_token（不走缓存）..." -ForegroundColor DarkGray
$body = @{ app_id = $appId; app_secret = $appSecret } | ConvertTo-Json -Compress
try {
    $r = Invoke-RestMethod -Uri 'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal' `
        -Method Post -ContentType 'application/json' -Body $body -TimeoutSec 20
} catch {
    Write-Error "取 token 失败: $($_.Exception.Message)"; exit 1
}
if ($r.code -ne 0) { Write-Error "取 token 失败: code=$($r.code) $($r.msg)"; exit 1 }
$tk = $r.tenant_access_token
Write-Host "token 已获取" -ForegroundColor Green
Write-Host ""

$results = @()
foreach ($tok in $FileToken) {
    $tok = $tok.Trim()
    if (-not $tok) { continue }
    $url = "https://open.feishu.cn/open-apis/drive/v1/files/$tok/download?type=$DocType"
    try {
        $resp = Invoke-WebRequest -Uri $url -Headers @{ Authorization = "Bearer $tk" } `
            -TimeoutSec 30 -UseBasicParsing -ErrorAction Stop
        Write-Host ("  {0}  HTTP {1}  {2:N0} 字节  可读" -f $tok, $resp.StatusCode, $resp.RawContentLength) -ForegroundColor Green
        $results += [pscustomobject]@{ Token = $tok; Status = $resp.StatusCode; Bytes = $resp.RawContentLength; Readable = $true }
    } catch {
        $code = $_.Exception.Response.StatusCode.value__
        $detail = ''
        try {
            $sr = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
            $detail = $sr.ReadToEnd()
            if ($detail.Length -gt 200) { $detail = $detail.Substring(0, 200) }
        } catch { }
        Write-Host ("  {0}  HTTP {1}  读不了  {2}" -f $tok, $code, $detail) -ForegroundColor Red
        $results += [pscustomobject]@{ Token = $tok; Status = $code; Bytes = 0; Readable = $false }
    }
}

Write-Host ""
Write-Host "=== 结论 ===" -ForegroundColor Cyan
$ok = ($results | Where-Object { $_.Readable }).Count
$bad = ($results | Where-Object { -not $_.Readable }).Count
if ($bad -eq 0) {
    Write-Host "全部可读。若服务端仍报错，问题在服务端缓存或代码，不是权限。" -ForegroundColor Yellow
} elseif ($ok -gt 0) {
    Write-Host "同一个应用：$ok 个可读、$bad 个读不了 → 纯粹是文件级权限差异。" -ForegroundColor Yellow
    Write-Host "下一步：对比读不了那个文件的 security_entity（见 SKILL.md 第 3 层）。" -ForegroundColor Yellow
} else {
    Write-Host "全部读不了 → 检查应用权限范围（drive:drive:readonly 是否开通并发布）。" -ForegroundColor Yellow
}
$results | Format-Table -AutoSize
