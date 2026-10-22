# 首次配置只在本机生成队友自己的专用密钥，不连接云端或读取组长凭据。
$ErrorActionPreference = 'Stop'

function Test-TeamConnection($Info) {
    if ($Info.host -notmatch '\A[A-Za-z0-9][A-Za-z0-9.-]*\z') { throw '服务器地址格式不合法' }
    if ($Info.port -isnot [int] -and $Info.port -isnot [long]) { throw '端口必须是整数' }
    if ($Info.port -lt 1 -or $Info.port -gt 65535) { throw 'SSH端口必须在1～65535之间' }
    if ($Info.user -notmatch '\A[a-zA-Z_][a-zA-Z0-9_-]*\z') { throw 'SSH用户名不合法' }
    if ($Info.host_key -and $Info.host_key -notmatch '\A(ssh-ed25519|ecdsa-sha2-nistp256|ssh-rsa) [A-Za-z0-9+/=]+\z') { throw '服务器公钥格式不合法，请向组长索取正确配置' }
}

function Initialize-TeamKey([string]$KeyPath, [string]$Keygen) {
    if (Test-Path -LiteralPath $KeyPath) {
        if (-not (Test-Path -LiteralPath ($KeyPath + '.pub'))) { throw '已有同名密钥但缺少公钥；请人工核对，不会覆盖旧私钥' }
        return
    }
    if (Test-Path -LiteralPath ($KeyPath + '.pub')) { throw '已有同名公钥但缺少私钥；请人工核对，不会覆盖' }
    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($KeyPath)) | Out-Null
    $info = New-Object Diagnostics.ProcessStartInfo
    $info.FileName = $Keygen
    # 显式原生参数保留空口令，兼容Windows PowerShell5的空参数问题。
    $info.Arguments = '-q -t ed25519 -N "" -f "' + $KeyPath + '" -C "image3d-team"'
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $process = [Diagnostics.Process]::Start($info)
    if (-not $process.WaitForExit(30000)) { $process.Kill(); throw '密钥生成超时' }
    if ($process.ExitCode -ne 0) { throw ('密钥生成失败：' + $process.StandardError.ReadToEnd()) }
    $process.Dispose()
}

function Write-TeamConfig([string]$Root, [string]$KeyPath, [string]$KnownHosts, $Info) {
    Test-TeamConnection $Info
    $sshFolder = Join-Path $Root 'runtime/ssh'
    [IO.Directory]::CreateDirectory($sshFolder) | Out-Null
    $key = $KeyPath.Replace('\','/')
    $known = $KnownHosts.Replace('\','/')
    $config = @"
Host p2a-autodl
  HostName $($Info.host)
  Port $($Info.port)
  User $($Info.user)
  IdentityFile "$key"
  IdentitiesOnly yes
  UserKnownHostsFile "$known"
  StrictHostKeyChecking yes
"@
    [IO.File]::WriteAllText((Join-Path $sshFolder 'p2a_config'), $config, (New-Object Text.UTF8Encoding($false)))
    if ($Info.host_key) {
        $hostRecord = '[' + $Info.host + ']:' + $Info.port + ' ' + $Info.host_key
        $existing = if (Test-Path -LiteralPath $KnownHosts) { @(Get-Content -LiteralPath $KnownHosts -Encoding UTF8) } else { @() }
        $sameHost = @($existing | Where-Object { $_.StartsWith('[' + $Info.host + ']:' + $Info.port + ' ') })
        if ($sameHost.Count -gt 0 -and $sameHost -notcontains $hostRecord) { throw '已有服务器公钥与包内记录不同，请向组长核对，不会自动覆盖' }
        if ($existing -notcontains $hostRecord) { [IO.File]::AppendAllText($KnownHosts, $hostRecord + "`n", (New-Object Text.UTF8Encoding($false))) }
    }
}

function Start-TeamSetup {
    $root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
    $ssh = Get-Command ssh.exe -ErrorAction SilentlyContinue
    $keygen = Get-Command ssh-keygen.exe -ErrorAction SilentlyContinue
    if (-not $ssh -or -not $keygen) { throw '请先按使用说明安装Windows“OpenSSH客户端”，重新打开本窗口；不需要安装OpenSSH服务器' }
    $connection = Get-Content -LiteralPath (Join-Path $root 'config/team-connection.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    Test-TeamConnection $connection
    $keyFolder = Join-Path $env:USERPROFILE '.ssh'
    $keyPath = Join-Path $keyFolder 'image3d_team_ed25519'
    $known = Join-Path $keyFolder 'image3d_team_known_hosts'
    Write-Host '将生成你自己的专用无口令SSH密钥，用于双击启动。已有同名密钥会保留。'
    Initialize-TeamKey $keyPath $keygen.Source
    Write-TeamConfig $root $keyPath $known $connection
    $public = [IO.File]::ReadAllText($keyPath + '.pub').Trim()
    [IO.File]::WriteAllText((Join-Path $root '发给组长的公钥.txt'), $public + "`n", (New-Object Text.UTF8Encoding($true)))
    Write-Host "`n配置完成。请把包内“发给组长的公钥.txt”发给组长；不要发送私钥。"
    Write-Host ('私钥保留在你的用户目录：' + $keyPath)
    Write-Host '组长将公钥加入云端授权并开机后，再双击“启动造物工坊.exe”。'
    if (-not $connection.host_key) { Write-Host '此包未内置服务器公钥。请按使用说明先人工核对服务器指纹并进行首次SSH连接。' }
    Write-Host '本次没有连接云端、安装模型或提交重建任务。'
}

if ($MyInvocation.InvocationName -ne '.') {
    try { Start-TeamSetup } catch { Write-Host ('配置未完成：' + $_.Exception.Message) -ForegroundColor Red; exit 1 }
}
