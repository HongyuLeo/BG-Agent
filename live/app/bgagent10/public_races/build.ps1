$ErrorActionPreference = 'Stop'
$compiler = 'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe'
& $compiler /nologo /target:exe /platform:x64 /optimize+ /reference:System.Web.Extensions.dll ('/out:' + (Join-Path $PSScriptRoot 'PublicRaces.exe')) (Join-Path $PSScriptRoot 'PublicRaces.cs') (Join-Path $PSScriptRoot 'Offsets.cs') (Join-Path $PSScriptRoot 'SelfTests.cs')
if ($LASTEXITCODE -ne 0) { throw 'Compilation failed' }
& (Join-Path $PSScriptRoot 'PublicRaces.exe') --self-test
if ($LASTEXITCODE -ne 0) { throw 'Fake tests failed' }
