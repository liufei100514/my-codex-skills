<#
  金蝶云星空（K3Cloud）只读探针
  —— 登录 → 查物料 → 查采购价，用来验证账套、权限、字段是否可用。

  凭据来源（按优先级）：
    1. 环境变量 ERP_KINGDEE_ACCT / ERP_KINGDEE_USER / ERP_KINGDEE_PASSWORD
    2. Windows 凭据管理器，目标名由 -CredentialTarget 指定（默认 EDP/Kingdee/InventoryRead）

  只做读操作：ValidateUser + ExecuteBillQuery。不碰任何写接口。

  用法：
    powershell -NoProfile -ExecutionPolicy Bypass -File kingdee-probe.ps1
    powershell -NoProfile -ExecutionPolicy Bypass -File kingdee-probe.ps1 -MaterialCode ZC1367
#>
param(
  [string]$BaseUrl = 'https://changlian.ik3cloud.com/K3Cloud',
  [string]$AcctId = $env:ERP_KINGDEE_ACCT,
  [string]$Username = $env:ERP_KINGDEE_USER,
  [string]$Password = $env:ERP_KINGDEE_PASSWORD,
  [string]$CredentialTarget = 'EDP/Kingdee/InventoryRead',
  [string]$MaterialCode = '',
  [int]$Limit = 5
)
$ErrorActionPreference = 'Stop'

Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class KingdeeCred
{
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    public struct CREDENTIAL
    {
        public int Flags; public int Type;
        public string TargetName; public string Comment;
        public System.Runtime.InteropServices.ComTypes.FILETIME LastWritten;
        public int CredentialBlobSize; public IntPtr CredentialBlob;
        public int Persist; public int AttributeCount; public IntPtr Attributes;
        public string TargetAlias; public string UserName;
    }
    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern bool CredReadW(string target, int type, int flags, out IntPtr credential);
    [DllImport("advapi32.dll")]
    static extern void CredFree(IntPtr cred);
    public static string[] Read(string target)
    {
        IntPtr p;
        if (!CredReadW(target, 1, 0, out p)) return null;
        try
        {
            CREDENTIAL c = (CREDENTIAL)Marshal.PtrToStructure(p, typeof(CREDENTIAL));
            if (c.CredentialBlob == IntPtr.Zero || c.CredentialBlobSize <= 0) return new string[] { c.UserName, "" };
            return new string[] { c.UserName, Marshal.PtrToStringUni(c.CredentialBlob, c.CredentialBlobSize / 2) };
        }
        finally { CredFree(p); }
    }
}
'@

if (-not $Username -or -not $Password) {
    $cred = [KingdeeCred]::Read($CredentialTarget)
    if (-not $cred) { Write-Host "未找到凭据：$CredentialTarget（也未见 ERP_KINGDEE_* 环境变量）" -ForegroundColor Red; exit 1 }
    $Username = $cred[0]; $Password = $cred[1]
}
if (-not $AcctId) { Write-Host '缺少账套 acctID（-AcctId 或 ERP_KINGDEE_ACCT）' -ForegroundColor Red; exit 1 }

Write-Host ("账套 {0} / 用户 {1} / 入口 {2}" -f $AcctId, $Username, $BaseUrl)

# ── 1. 登录 ────────────────────────────────────────────────
$session = $null
$loginRes = Invoke-WebRequest -Uri "$BaseUrl/Kingdee.BOS.WebApi.ServicesStub.AuthService.ValidateUser.common.kdsvc" `
    -Method Post -ContentType 'application/x-www-form-urlencoded' -SessionVariable session -TimeoutSec 60 -UseBasicParsing `
    -Body @{ acctID = $AcctId; username = $Username; password = $Password; lcid = '2052' }
$login = $loginRes.Content | ConvertFrom-Json
Write-Host ("登录：LoginResultType={0} IsSuccessByAPI={1} Cookie={2}" -f $login.LoginResultType, $login.IsSuccessByAPI, $session.Cookies.Count)
if ($login.LoginResultType -ne 1 -and $login.IsSuccessByAPI -ne $true) { exit 2 }

function Invoke-BillQuery {
    param([string]$FormId, [string]$FieldKeys, [string]$FilterString = '', [string]$OrderString = '', [int]$PageSize = 2000, [int]$StartRow = 0)
    $payload = @{
        FormId = $FormId; FieldKeys = $FieldKeys; FilterString = $FilterString
        OrderString = $OrderString; TopRowCount = 0; StartRow = $StartRow; Limit = $PageSize
    } | ConvertTo-Json -Depth 5 -Compress
    $r = Invoke-WebRequest -Uri "$BaseUrl/Kingdee.BOS.WebApi.ServicesStub.DynamicFormService.ExecuteBillQuery.common.kdsvc" `
        -Method Post -ContentType 'application/x-www-form-urlencoded' -WebSession $session -TimeoutSec 90 -UseBasicParsing `
        -Body @{ data = $payload }
    return $r.Content
}

# ── 2. 物料 ────────────────────────────────────────────────
Write-Host "`n=== BD_MATERIAL 前 $Limit 条 ==="
$raw = Invoke-BillQuery -FormId 'BD_MATERIAL' -FieldKeys 'FNumber,FName,FSpecification' -OrderString 'FNumber ASC' -PageSize $Limit
if ($raw -match 'ErrorCode') { Write-Host $raw -ForegroundColor Yellow } else {
    ($raw | ConvertFrom-Json) | ForEach-Object { [pscustomobject]@{ FNumber=$_[0]; FName=$_[1]; Spec=$_[2] } } | Format-Table -AutoSize
}

# ── 3. 采购价 ──────────────────────────────────────────────
if (-not $MaterialCode) {
    $first = ($raw | ConvertFrom-Json | Select-Object -First 1)
    if ($first) { $MaterialCode = [string]$first[0] }
}
if ($MaterialCode) {
    Write-Host "=== PUR_PurchaseOrder：物料 $MaterialCode 最近 5 笔已审核采购 ==="
    $filter = "FDocumentStatus='C' and FCancelStatus='A' and FMaterialId.FNumber='$MaterialCode'"
    $raw2 = Invoke-BillQuery -FormId 'PUR_PurchaseOrder' `
        -FieldKeys 'FBillNo,FDate,FMaterialId.FNumber,FTaxPrice,FBaseUnitQty,FBaseUnitId.FName' `
        -FilterString $filter -OrderString 'FDate DESC' -PageSize 5
    if ($raw2 -match 'ErrorCode') { Write-Host $raw2 -ForegroundColor Yellow } else {
        $rows = $raw2 | ConvertFrom-Json
        if (-not $rows -or $rows.Count -eq 0) { Write-Host '该物料没有采购记录' -ForegroundColor DarkGray }
        else {
            $rows | ForEach-Object {
                [pscustomobject]@{ 单号=$_[0]; 日期=$_[1]; 物料=$_[2]; 含税单价=$_[3]; 数量=$_[4]; 单位=$_[5] }
            } | Format-Table -AutoSize
        }
    }
}

Write-Host '完成。以上全部为只读查询。'
