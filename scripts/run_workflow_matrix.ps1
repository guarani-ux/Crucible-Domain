#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Launches every Crucible document-workflow permutation (solo docs, partial task packs, and full 8-stage pipelines)
    one at a time across project scopes, resuming cleanly from `.agents/bench_matrix_state.json`.
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
Push-Location $RepoRoot
try {
    $argsList = @(".agents/scripts/crucible_gate.py", "bench", "matrix")
    if ($Reset) { $argsList += "reset" }
    $argsList += @("--mode", $Mode, "--rounds", "$Rounds")
    if ($NoJudge) { $argsList += "--no-judge" }

    Write-Host "Launching Crucible Workflow Permutation Matrix (mode=$Mode, rounds=$Rounds, judge=$(-not $NoJudge))..." -ForegroundColor Cyan
    & python @argsList
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
