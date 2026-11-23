param(
    [string]$LocalGitRoot = "C:\crucible-domain",
    [string]$MirrorDest = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path,
    [switch]$Apply
)

$ErrorActionPreference = "Stop"

$CmdArgs = @(
    $LocalGitRoot,
    $MirrorDest,
    "/MIR",
    "/XD", ".git", ".pytest_cache", "__pycache__", ".tmp.drivedownload", ".tmp.driveupload",
    "/XF", "*.pyc", "Thumbs.db", ".DS_Store"
)

if (-not $Apply) {
    $CmdArgs += "/L"
    Write-Host "[DRY RUN] robocopy $($CmdArgs -join ' ')"
    Write-Host "Pass -Apply to execute one-way mirror (excluding .git)."
}

robocopy @CmdArgs
$rc = $LASTEXITCODE
# Robocopy exit codes 0-7 indicate success with varying copy/mismatch flags; >= 8 indicates failure.
if ($rc -ge 8) {
    throw "robocopy failed with exit code $rc"
}
exit 0
