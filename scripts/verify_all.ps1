#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Parallel single-command terminal verification floor for Crucible Domain Hub + registered spokes.
#>
$ErrorActionPreference = "Continue"
$HubRoot = Split-Path -Parent $PSScriptRoot
$SpokeRoot = "C:/crucible-spokes/story-lane"

$steps = @(
    @{ Name = "Hub Gate (--strict)"; Cwd = $HubRoot; Cmd = @("python", ".agents/scripts/crucible_gate.py", "check", "--strict") },
    @{ Name = "Hub Doctor";          Cwd = $HubRoot; Cmd = @("python", ".agents/scripts/crucible_gate.py", "doctor") },
    @{ Name = "Hub Pytest";          Cwd = $HubRoot; Cmd = @("pytest", ".agents/scripts/tests", "-q") },
    @{ Name = "Story-Lane Pytest";   Cwd = $SpokeRoot; Cmd = @("python", "-m", "pytest", "-q") }
)

$jobs = @()
foreach ($s in $steps) {
    $job = Start-Job -ScriptBlock {
        param($Name, $Cwd, $Cmd)
        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        Push-Location $Cwd
        $exe = $Cmd[0]
        $argsList = $Cmd[1..($Cmd.Length - 1)]
        $out = & $exe @argsList 2>&1
        $ec = $LASTEXITCODE
        Pop-Location
        $sw.Stop()
        [PSCustomObject]@{
            Name    = $Name
            Exit    = $ec
            Output  = $out
            Seconds = [math]::Round($sw.Elapsed.TotalSeconds, 2)
        }
    } -ArgumentList $s.Name, $s.Cwd, $s.Cmd
    $jobs += $job
}

$null = Wait-Job -Job $jobs
$results = @()
$failed = 0

foreach ($j in $jobs) {
    $res = Receive-Job -Job $j
    Remove-Job -Job $j -Force
    $status = if ($res.Exit -eq 0) { "PASS" } else { "FAIL" }
    if ($res.Exit -ne 0) {
        $failed++
        Write-Host "`n--- FAILED: $($res.Name) (exit $($res.Exit)) ---" -ForegroundColor Red
        $res.Output | ForEach-Object { Write-Host $_ }
    }
    $results += [PSCustomObject]@{
        Check   = $res.Name
        Status  = $status
        Seconds = $res.Seconds
    }
}

Write-Host "`n=== Crucible Terminal Verification Summary (Parallel) ===" -ForegroundColor Cyan
$results | Format-Table -AutoSize
if ($failed -gt 0) {
    Write-Host "RESULT: $failed check(s) FAILED" -ForegroundColor Red
    exit 1
}
Write-Host "RESULT: ALL $($results.Count) CHECKS PASSED" -ForegroundColor Green
exit 0
