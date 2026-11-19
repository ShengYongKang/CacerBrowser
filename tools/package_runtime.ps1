#requires -Version 5.1
<#
.SYNOPSIS
  Prepare the browser core plus separate Python/font Release assets.
.EXAMPLE
  $env:CAMOUFOX_RUNTIME = 'C:\build\camoufox'
  ./tools/package_runtime.ps1 -PythonEmbed build/python-embed.zip -ReleaseBase 'https://github.com/baseless1119/CacerBrowser/releases/download/v0.1.3'
Run with a clean dependency interpreter; use -Python to select it.
Install the build-only dependency first: python -m pip install fonttools==4.60.1
#>
param(
  [Parameter(Mandatory=$true)][string]$PythonEmbed,
  [Parameter(Mandatory=$true)][string]$ReleaseBase,
  [string]$Python = 'python',
  [switch]$Build
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
if (-not $env:CAMOUFOX_RUNTIME) { throw 'Set CAMOUFOX_RUNTIME to the active engine directory.' }
Push-Location $repo
try {
  & $Python tools/prepare_release.py --engine $env:CAMOUFOX_RUNTIME --python-embed $PythonEmbed --release-base $ReleaseBase
  if ($LASTEXITCODE -ne 0) { throw 'Runtime preparation failed.' }
  if ($Build) {
    Push-Location manager
    try {
      npm run tauri build
      if ($LASTEXITCODE -ne 0) { throw 'Tauri build failed.' }
    } finally { Pop-Location }
  }
} finally { Pop-Location }
