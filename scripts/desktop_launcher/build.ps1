# 复用Windows自带.NET Framework编译器，不下载工具链。
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$compilerPath = Join-Path $env:WINDIR 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
if (-not (Test-Path -LiteralPath $compilerPath)) { throw '未找到Windows自带.NET Framework编译器，未自动安装。' }
$references = @('/r:System.Core.dll','/r:System.Drawing.dll','/r:System.Windows.Forms.dll','/r:System.Web.Extensions.dll')
$outputPath = Join-Path $projectRoot '启动造物工坊.exe'
& $compilerPath /nologo /codepage:65001 /target:winexe /platform:x64 "/out:$outputPath" @references (Join-Path $PSScriptRoot 'Launcher.cs')
if ($LASTEXITCODE -ne 0) { throw '启动器编译失败。' }
$testFolder = Join-Path $projectRoot 'runs/desktop-launcher-20261021-01'
New-Item -ItemType Directory -Path $testFolder -Force | Out-Null
$testPath = Join-Path $testFolder 'launcher-tests.exe'
& $compilerPath /nologo /codepage:65001 /target:exe /platform:x64 /main:DesktopLauncherTests "/out:$testPath" @references (Join-Path $PSScriptRoot 'Launcher.cs') (Join-Path $projectRoot 'tests/desktop_launcher/DesktopLauncherTests.cs')
if ($LASTEXITCODE -ne 0) { throw '启动器固定回归程序编译失败。' }
Write-Output $outputPath
