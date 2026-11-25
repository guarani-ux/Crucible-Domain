#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Hot-reloadable sequential launcher for the Crucible Workflow Permutation Matrix.
    Spawns a fresh Python process per permutation (--rounds 1) so any live code, rubric,
    lever, or charter upgrade takes effect immediately on the very next run with zero restart.
#>
param(
    [ValidateSet("agy_live", "offline")]
    [string]$Mode = "agy_live",
    [int]$Rounds = 15,
    [switch]$NoJudge,
    [switch]$Reset
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$StopFile = Join-Path $RepoRoot ".agents\bench.stop"
$StateFile = Join-Path $RepoRoot ".agents\bench_matrix_state.json"

Push-Location $RepoRoot
try {
    if ($Reset -and (Test-Path $StateFile)) {
        Remove-Item $StateFile -Force
        Write-Host "Reset matrix cursor (.agents/bench_matrix_state.json removed)." -ForegroundColor Yellow
    }

    Write-Host "Launching Hot-Reloadable Crucible Workflow Matrix (mode=$Mode, rounds=$Rounds, judge=$(-not $NoJudge))..." -ForegroundColor Cyan
    Write-Host "Live code/YAML edits will automatically load on the next run." -ForegroundColor DarkGray

    for ($i = 1; $i -le $Rounds; $i++) {
        if (Test-Path $StopFile) {
            Remove-Item $StopFile -Force -ErrorAction SilentlyContinue
            Write-Host "Stop file detected (.agents/bench.stop). Exiting cleanly before run $i/$Rounds." -ForegroundColor Yellow
            break
        }

        Write-Host "`n>>> [Hot-Reload Step $i/$Rounds] spawning fresh Python process..." -ForegroundColor Cyan
        $argsList = @(".agents/scripts/crucible_gate.py", "bench", "matrix", "--mode", $Mode, "--rounds", "1")
        if ($NoJudge) { $argsList += "--no-judge" }

        & python @argsList
        $code = $LASTEXITCODE
        if ($code -eq 2) {
            Write-Host "Matrix CLI usage/config error (exit 2). Stopping." -ForegroundColor Red
            exit $code
        }
    }
    exit 0
} finally {
    Pop-Location
}
