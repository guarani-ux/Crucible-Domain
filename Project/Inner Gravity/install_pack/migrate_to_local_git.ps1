param(
    [string]$TargetRoot = "C:\crucible-domain",
    [switch]$Apply
)

$ErrorActionPreference = "Stop"

$InstallPack = Split-Path -Parent $MyInvocation.MyCommand.Path
$SourceRepo = (Resolve-Path (Join-Path $InstallPack "..\..\..")).Path

Write-Host "Source (OneDrive/Drive synced): $SourceRepo"
Write-Host "Target (single-writer local Git): $TargetRoot"

if (-not $Apply) {
    Write-Host "`n[DRY RUN] Pass -Apply between Antigravity sessions to clone to $TargetRoot."
    Write-Host "Actions that -Apply will run:"
    Write-Host "  1. Clone $SourceRepo -> $TargetRoot (preserving origin remote if configured)"
    Write-Host "  2. Copy working tree changes if any, then verify 'crucible_gate.py doctor' in $TargetRoot"
    Write-Host "  3. Use sync_to_drive_mirror.ps1 for one-way non-.git publishing back to OneDrive/Drive."
    exit 0
}

if (Test-Path $TargetRoot) {
    throw "TargetRoot already exists: $TargetRoot. Move or pick a fresh directory before applying."
}

git clone $SourceRepo $TargetRoot
$OrigRemote = git -C $SourceRepo remote get-url origin 2>$null
if ($LASTEXITCODE -eq 0 -and $OrigRemote) {
    git -C $TargetRoot remote set-url origin $OrigRemote
    Write-Host "Restored origin remote -> $OrigRemote"
}

Write-Host "`nVerifying new local repo with crucible_gate.py doctor..."
Push-Location $TargetRoot
try {
    python ".agents/scripts/crucible_gate.py" doctor
} finally {
    Pop-Location
}
