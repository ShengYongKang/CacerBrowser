#requires -Version 5.1
<#
.SYNOPSIS
  Prepare the self-contained ShadowFox runtime for a Windows release build.

.EXAMPLE
  $env:PYTHON_RUNTIME = 'C:\build\shadowfox-python'
  $env:CAMOUFOX_RUNTIME = 'C:\build\camoufox'
  $env:ARTI_RUNTIME = 'C:\build\arti'
  .\tools\package_runtime.ps1 -Clean

The script intentionally does not download binaries. Runtime versions must be
provided by the release pipeline and verified there. This avoids silently
shipping an untrusted executable or an accidentally developer-only venv.
#>
param(
  [switch]$Clean,
  [switch]$Build
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$resourceRoot = Join-Path $repo 'manager\src-tauri\resources'
$coreTarget = Join-Path $resourceRoot 'core'
$runtimeTarget = Join-Path $resourceRoot 'runtime'

function Require-Directory([string]$path, [string]$label) {
  if (-not (Test-Path -LiteralPath $path -PathType Container)) {
    throw "$label not found: $path"
  }
}
function Copy-Directory([string]$source, [string]$target) {
  New-Item -ItemType Directory -Force -Path $target | Out-Null
  Get-ChildItem -LiteralPath $source -Force | Copy-Item -Destination $target -Recurse -Force
}

$pythonSource = $env:PYTHON_RUNTIME
$camoufoxSource = $env:CAMOUFOX_RUNTIME
$artiSource = $env:ARTI_RUNTIME

if ([string]::IsNullOrWhiteSpace($pythonSource)) {
  throw 'Set PYTHON_RUNTIME to a standalone/embedded Python runtime directory before packaging.'
}
if ([string]::IsNullOrWhiteSpace($camoufoxSource)) {
  throw 'Set CAMOUFOX_RUNTIME to the Camoufox runtime directory before packaging.'
}
Require-Directory $pythonSource 'Python runtime'
Require-Directory $camoufoxSource 'Camoufox runtime'
if ($artiSource) { Require-Directory $artiSource 'arti runtime' }
if (-not (Test-Path -LiteralPath (Join-Path $pythonSource 'python.exe') -PathType Leaf)) {
  throw 'Python runtime must contain python.exe at its root; a development venv cannot be used.'
}
if (-not (Test-Path -LiteralPath (Join-Path $camoufoxSource 'camoufox.exe') -PathType Leaf)) {
  throw 'Camoufox runtime must point to the active Windows engine directory containing camoufox.exe.'
}

if ($Clean -and (Test-Path $resourceRoot)) {
  Remove-Item -LiteralPath $resourceRoot -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $coreTarget, $runtimeTarget | Out-Null

# The packaged CLI is copied as a resource and is no longer read from the
# repository at runtime.
Copy-Directory (Join-Path $repo 'core') $coreTarget
Copy-Directory $pythonSource (Join-Path $runtimeTarget 'python')
Copy-Directory $camoufoxSource (Join-Path $runtimeTarget 'camoufox')
if ($artiSource) { Copy-Directory $artiSource (Join-Path $runtimeTarget 'arti') }

# Remove development artefacts from the packaged Python code.
Get-ChildItem -LiteralPath $resourceRoot -Recurse -Directory -Force |
  Where-Object { $_.Name -in @('__pycache__', '.pytest_cache') } |
  Remove-Item -Recurse -Force
Get-ChildItem -LiteralPath $resourceRoot -Recurse -File -Force |
  Where-Object { $_.Extension -in @('.pyc', '.pyo') } |
  Remove-Item -Force

Write-Host "Prepared packaged runtime at: $resourceRoot" -ForegroundColor Green
Write-Host 'Next: cd manager; $env:NSISCONFDIR = (Resolve-Path .\src-tauri\nsis).Path; npm run tauri build'
if ($Build) {
  Push-Location (Join-Path $repo 'manager')
  $previousNsisConfig = $env:NSISCONFDIR
  try {
    $env:NSISCONFDIR = Join-Path $repo 'manager\src-tauri\nsis'
    npm run tauri build
    if ($LASTEXITCODE -ne 0) { throw 'Tauri build failed.' }
  } finally {
    $env:NSISCONFDIR = $previousNsisConfig
    Pop-Location
  }
}
