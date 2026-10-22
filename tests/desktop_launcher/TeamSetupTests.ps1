# 固定本机配置/临时密钥fixture，不连接云端，不读取现有用户密钥。
$ErrorActionPreference = 'Stop'
$project = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$source = Join-Path $project 'scripts/desktop_launcher/setup_team.ps1'
$folder = Join-Path $project ('runs/team-setup-fixture-' + [Guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($folder) | Out-Null
$copy = Join-Path $folder 'setup.ps1'
[IO.File]::WriteAllText($copy, [IO.File]::ReadAllText($source, [Text.Encoding]::UTF8), (New-Object Text.UTF8Encoding($true)))
. $copy
$valid = [PSCustomObject]@{host='example.test';port=44075;user='root';host_key='ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFIXTURE'}
Test-TeamConnection $valid
$passed = 1
foreach ($bad in @(
    [PSCustomObject]@{host='bad;command';port=44075;user='root';host_key=''},
    [PSCustomObject]@{host='example.test';port=0;user='root';host_key=''},
    [PSCustomObject]@{host='example.test';port='44075';user='root';host_key=''},
    [PSCustomObject]@{host='example.test';port=44075;user='root';host_key="ssh-ed25519 AAA`nInjected yes"}
)) {
    $rejected = $false
    try { Test-TeamConnection $bad } catch { $rejected = $true }
    if (-not $rejected) { throw '非法连接配置未拒绝' }
    $passed++
}
$keyFolder = Join-Path $folder '用户 密钥'
$key = Join-Path $keyFolder 'fixture_ed25519'
Initialize-TeamKey $key (Get-Command ssh-keygen.exe).Source
$before = (Get-FileHash -LiteralPath $key -Algorithm SHA256).Hash
Initialize-TeamKey $key (Get-Command ssh-keygen.exe).Source
if ($before -ne (Get-FileHash -LiteralPath $key -Algorithm SHA256).Hash) { throw '重配覆盖了旧密钥' }
$passed++
$known = Join-Path $keyFolder 'known_hosts'
Write-TeamConfig $folder $key $known $valid
Write-TeamConfig $folder $key $known $valid
if (@(Get-Content -LiteralPath $known).Count -ne 1) { throw '重复追加服务器公钥' }
$passed++
$config = Get-Content -LiteralPath (Join-Path $folder 'runtime/ssh/p2a_config') -Raw -Encoding UTF8
if (-not $config.Contains($key.Replace('\','/')) -or -not $config.Contains('StrictHostKeyChecking yes')) { throw '本机路径或严格验证未保存' }
$passed++
$valid.host_key = 'ssh-ed25519 AAAACHANGED'
$rejected = $false
try { Write-TeamConfig $folder $key $known $valid } catch { $rejected = $true }
if (-not $rejected) { throw '不同服务器公钥未拒绝' }
$passed++
Remove-Item -LiteralPath $key, ($key + '.pub')
@{passed=$passed;cloud_called=$false;private_fixture_removed=$true} | ConvertTo-Json -Compress
