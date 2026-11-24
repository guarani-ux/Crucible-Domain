#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Single-command terminal verification floor for Crucible Domain Hub + registered spokes.
#>
$ErrorActionPreference = "Continue"
$HubRoot = Split-Path -Parent $PSScriptRoot
$SpokeRoot = "C:/crucible-spokes/story-lane"

$steps = @(
    @{ Name = "Hub Gate (--strict)"; Cwd = $HubRoot; Cmd = @("python", ".agents/scripts/crucible_gate.py", "check", "--strict") },
    @{ Name = "Hub Doctor";          Cwd = $HubRoot; Cmd = @("python", ".agents/scripts/crucible_gate.py", "doctor") },
    @{ Name = "Hub Pytest";          Cwd = $HubRoot; Cmd = @("pytest", ".agents/scripts/tests", "-q") },
    @{ Name = "Story-Lane Spoke Pytest"; Cwd = $SpokeRoot; Cmd = @("python", "-m", "pytest", "tests/test_storylane_spoke_mcp.py", "tests/test_storylane_fuzz_and_replay.py", "-q") }
)

$results = @()
$failed = 0

foreach ($s in $steps) {
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    Push-Location $s.Cwd
    $exe = $s.Cmd[0]
    $argsList = $s.Cmd[1..($s.Cmd.Length - 1)]
    $out = & $exe @argsList 2>&1
    $ec = $LASTEXITCODE
    Pop-Location
    $sw.Stop()

    $status = if ($ec -eq 0) { "PASS" } else { "FAIL" }
    if ($ec -ne 0) {
        $failed++
        Write-Host "`n--- FAILED: $($s.Name) (exit $ec) ---" -ForegroundColor Red
        $out | ForEach-Object { Write-Host $_ }
    }
    $results += [PSCustomObject]@{
        Check   = $s.Name
        Status  = $status
        Seconds = [math]::Round($sw.Elapsed.TotalSeconds, 2)
    }
}

Write-Host "`n=== Crucible Terminal Verification Summary ===" -ForegroundColor Cyan
$results | Format-Table -AutoSize
if ($failed -gt 0) {
    Write-Host "RESULT: $failed check(s) FAILED" -ForegroundColor Red
    exit 1
}
Write-Host "RESULT: ALL $($results.Count) CHECKS PASSED" -ForegroundColor Green
exit 0
