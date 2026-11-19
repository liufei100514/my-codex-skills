<#
.SYNOPSIS
    把飞书云文档的 security_entity 从 only_full_access 改成 anyone_can_view，
    解决"应用能读 A 文件、读 B 文件 403"的问题。

.DESCRIPTION
    1. 读当前 permission.public，确认 security_entity 取值
    2. 写无 BOM 的 UTF-8 body 文件（关键：带 BOM 会导致 lark-cli 报 invalid JSON）
    3. 调 lark-cli drive permission.public patch 修改
    4. 回读验证

.PARAMETER FileToken
    文件 token，多个用逗号分隔

.PARAMETER DocType
    文件类型，默认 file

.PARAMETER DryRun
    只读不写，先看当前值

.EXAMPLE
    .\fix-file-security.ps1 -FileToken "URHwbLNYIoyOgyx5rm2cm7UJnXb" -DryRun
    .\fix-file-security.ps1 -FileToken "URHwbLNYIoyOgyx5rm2cm7UJnXb"
#>
param(
    [Parameter(Mandatory = $true)][string[]]$FileToken,
    [string]$DocType = 'file',
    [switch]$DryRun
)

Remove-Item Env:http_proxy, Env:https_proxy, Env:HTTP_PROXY, Env:HTTPS_PROXY -ErrorAction SilentlyContinue

$bodyJson = '{"security_entity":"anyone_can_view"}'
$bodyFile = Join-Path $env:TEMP ("feishu-secbody-{0}.json" -f [guid]::NewGuid().ToString('N').Substring(0, 8))
# 必须无 BOM，否则 lark-cli 报 --data invalid JSON format
[System.IO.File]::WriteAllText($bodyFile, $bodyJson, (New-Object System.Text.UTF8Encoding($false)))

try {
    foreach ($tok in $FileToken) {
        $tok = $tok.Trim()
        if (-not $tok) { continue }
        Write-Host ""
        Write-Host "=== $tok ===" -ForegroundColor Cyan

        # 1. 读当前值
        $cur = lark-cli drive +permission-get-setting --token $tok --type $DocType 2>&1 | Out-String
        $sec = [regex]::Match($cur, '"security_entity":\s*"([^"]+)"').Groups[1].Value
        if (-not $sec) {
            Write-Host "  读取失败，跳过。原始输出：" -ForegroundColor Red
            Write-Host ($cur.Substring(0, [Math]::Min(300, $cur.Length))) -ForegroundColor DarkGray
            continue
        }
        Write-Host "  当前 security_entity = $sec" -ForegroundColor Yellow

        if ($sec -eq 'anyone_can_view') {
            Write-Host "  已是目标值，无需修改" -ForegroundColor Green
            continue
        }
        if ($DryRun) {
            Write-Host "  [DryRun] 将改为 anyone_can_view" -ForegroundColor DarkGray
            continue
        }

        # 2. 修改
        $out = lark-cli drive permission.public patch --token $tok --type $DocType --data "@$bodyFile" --yes 2>&1 | Out-String
        if ($out -match '"ok":\s*true') {
            Write-Host "  修改成功" -ForegroundColor Green
        } else {
            Write-Host "  修改失败：" -ForegroundColor Red
            Write-Host ($out.Substring(0, [Math]::Min(400, $out.Length))) -ForegroundColor DarkGray
            continue
        }

        # 3. 回读验证
        $after = lark-cli drive +permission-get-setting --token $tok --type $DocType 2>&1 | Out-String
        $sec2 = [regex]::Match($after, '"security_entity":\s*"([^"]+)"').Groups[1].Value
        if ($sec2 -eq 'anyone_can_view') {
            Write-Host "  回读确认：$sec2" -ForegroundColor Green
        } else {
            Write-Host "  回读值异常：$sec2（可能被组织策略覆盖）" -ForegroundColor Yellow
        }
    }
} finally {
    Remove-Item $bodyFile -Force -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "改完请用 probe-app-download.ps1 复测下载，看到 200 才算真的好了。" -ForegroundColor Cyan
