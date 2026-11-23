<#
.SYNOPSIS
Promotes the Judgment Floor hard layer (`judgment_gate.py`, `global_hooks.json.ready`, and `GEMINI.md.ready`)
into `~/.gemini/` with automatic timestamped backups and immediate `crucible_gate.py doctor` verification.
#>
param(
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$InstallPack = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path (Join-Path $InstallPack "..\..\..")).Path
$GeminiHome = Join-Path $HOME ".gemini"
$GlobalScripts = Join-Path $GeminiHome "config\scripts"
$GlobalHooks = Join-Path $GeminiHome "config\hooks.json"
$GlobalGeminiMd = Join-Path $GeminiHome "GEMINI.md"

$SrcGate = Join-Path $RepoRoot ".agents\scripts\judgment_gate.py"
$SrcHooks = Join-Path $InstallPack "global_hooks.json.ready"
$SrcGeminiMd = Join-Path $InstallPack "GEMINI.md.ready"

foreach ($f in @($SrcGate, $SrcHooks, $SrcGeminiMd)) {
    if (-not (Test-Path $f)) {
        throw "Missing required staged source: $f"
    }
}

if (-not $Force) {
    Write-Host "DRY-RUN (pass -Force to promote):"
    Write-Host "  1. $SrcGate -> $(Join-Path $GlobalScripts 'judgment_gate.py')"
    Write-Host "  2. $SrcHooks -> $GlobalHooks"
    Write-Host "  3. $SrcGeminiMd -> $GlobalGeminiMd"
    exit 0
}

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupDir = Join-Path $GeminiHome "config\backups\judgment-floor-$stamp"
New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
New-Item -ItemType Directory -Force -Path $GlobalScripts | Out-Null

if (Test-Path $GlobalHooks) { Copy-Item $GlobalHooks (Join-Path $backupDir "hooks.json.bak") -Force }
if (Test-Path $GlobalGeminiMd) { Copy-Item $GlobalGeminiMd (Join-Path $backupDir "GEMINI.md.bak") -Force }

Copy-Item $SrcGate (Join-Path $GlobalScripts "judgment_gate.py") -Force
Copy-Item $SrcHooks $GlobalHooks -Force
Copy-Item $SrcGeminiMd $GlobalGeminiMd -Force

Write-Host "Promoted Judgment Floor hard layer (backups in $backupDir)."
Write-Host "Running live Crucible Doctor + Judgment Floor pointer check..."
python (Join-Path $GlobalScripts "judgment_gate.py") session-start
python (Join-Path $RepoRoot ".agents\scripts\crucible_gate.py") doctor
