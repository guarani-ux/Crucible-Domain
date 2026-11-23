param(
    [switch]$Force,
    [switch]$SkipGlobalClean
)

$ErrorActionPreference = "Stop"

$InstallPack = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path (Join-Path $InstallPack "..\..\..")).Path

$HooksSource = Join-Path $InstallPack "crucible_hooks.json.fixed"
$HooksTarget = Join-Path $RepoRoot ".agents\hooks.json"
$HooksBackup = Join-Path $RepoRoot ".agents\hooks.json.bak"

$AgentsSource = Join-Path $InstallPack "AGENTS.md.ready"
$AgentsTarget = Join-Path $RepoRoot "AGENTS.md"

$LockSource = Join-Path $InstallPack "acceptance.lock.json.ready"
$LockTarget = Join-Path $RepoRoot ".agents\acceptance.lock.json"

if (-not (Test-Path $HooksSource)) {
    throw "Missing staged hooks file: $HooksSource"
}

Copy-Item -Path $HooksSource -Destination $HooksTarget -Force
Write-Host "Installed fixed .agents/hooks.json (SessionStart, PreToolUse, Stop)"

if (Test-Path $HooksBackup) {
    Remove-Item -Path $HooksBackup -Force
    Write-Host "Removed temporary .agents/hooks.json.bak (tracked in Git)"
}

if (-not (Test-Path $AgentsTarget) -or $Force) {
    Copy-Item -Path $AgentsSource -Destination $AgentsTarget -Force
    Write-Host "Installed workspace AGENTS.md"
} else {
    Write-Host "Skipped AGENTS.md (already exists; pass -Force to overwrite)"
}

if (Test-Path $LockSource) {
    if (-not (Test-Path $LockTarget) -or $Force) {
        Copy-Item -Path $LockSource -Destination $LockTarget -Force
        Write-Host "Installed .agents/acceptance.lock.json"
    } else {
        Write-Host "Skipped .agents/acceptance.lock.json (already exists; pass -Force to overwrite)"
    }
}

if (-not $SkipGlobalClean) {
    $GlobalCfg = Join-Path $env:USERPROFILE ".gemini\config"
    if (Test-Path (Join-Path $GlobalCfg ".git")) {
        $ProtectedTargets = @(
            (Join-Path $GlobalCfg "scripts\pre_tool_guard.js"),
            (Join-Path $GlobalCfg "scripts\pre_tool_guard.js.bak"),
            (Join-Path $GlobalCfg "scripts\pre_tool_guard.js.bak2"),
            (Join-Path $GlobalCfg "scripts\test_guard.js"),
            (Join-Path $GlobalCfg "scripts\guard_audit.log"),
            (Join-Path $GlobalCfg "scripts\hook_v4.py.bak_20261026_145402"),
            (Join-Path $GlobalCfg "scripts\hook_v4.py.bak_20261027_224045"),
            (Join-Path $GlobalCfg "scripts\hook_v4.py.bak_20261027_224239"),
            (Join-Path $GlobalCfg "scripts\hook_v4.py.bak_pre_lean"),
            (Join-Path $GlobalCfg "hooks.json.bak"),
            (Join-Path $GlobalCfg "hooks.json.bak2"),
            (Join-Path $GlobalCfg "hooks.json.bak_20261115"),
            (Join-Path $GlobalCfg "hooks.json.pre_repair_bak"),
            (Join-Path $GlobalCfg "AGENTS.md.bak"),
            (Join-Path $GlobalCfg "AGENTS.md.bak_20261026_145402")
        )
        $RemovedAny = $false
        foreach ($item in $ProtectedTargets) {
            if (Test-Path $item) {
                Remove-Item -Path $item -Force
                Write-Host "Removed legacy protected global item: $item"
                $RemovedAny = $true
            }
        }
        if ($RemovedAny) {
            git -C $GlobalCfg add -A
            git -C $GlobalCfg commit -m "Remove legacy backups and dead JS guard" | Out-Null
            Write-Host "Committed protected global cleanup to local git in $GlobalCfg"
        }
    }
}

Write-Host "`nRunning closed-loop verification (crucible_gate.py doctor)..."
Push-Location $RepoRoot
try {
    python ".agents/scripts/crucible_gate.py" doctor
} finally {
    Pop-Location
}
