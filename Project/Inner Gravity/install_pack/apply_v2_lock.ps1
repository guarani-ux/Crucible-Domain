param(
    [switch]$SkipDoctor
)

$ErrorActionPreference = "Stop"

$InstallPack = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path (Join-Path $InstallPack "..\..\..")).Path

$LockSource = Join-Path $InstallPack "acceptance.lock.json.v2"
$LockTarget = Join-Path $RepoRoot ".agents\acceptance.lock.json"

if (-not (Test-Path $LockSource)) {
    throw "Missing staged v2 lockfile: $LockSource"
}

Write-Host "Validating acceptance.lock.json.v2 via Python json.load..."
python -c "import json, sys; data = json.load(open(sys.argv[1], encoding='utf-8')); assert isinstance(data.get('required_files'), list) and isinstance(data.get('python_syntax'), list)" "$LockSource"
if ($LASTEXITCODE -ne 0) {
    throw "Failed JSON validation for $LockSource"
}

$NeedsCopy = $true
if (Test-Path $LockTarget) {
    $SrcHash = (Get-FileHash -Path $LockSource -Algorithm SHA256).Hash
    $DstHash = (Get-FileHash -Path $LockTarget -Algorithm SHA256).Hash
    if ($SrcHash -eq $DstHash) {
        $NeedsCopy = $false
        Write-Host ".agents/acceptance.lock.json already matches acceptance.lock.json.v2 (no-op)"
    }
}

if ($NeedsCopy) {
    Copy-Item -Path $LockSource -Destination $LockTarget -Force
    Write-Host "Installed acceptance.lock.json.v2 -> .agents/acceptance.lock.json"
}

if (-not $SkipDoctor) {
    Write-Host "`nRunning closed-loop verification (crucible_gate.py doctor)..."
    Push-Location $RepoRoot
    try {
        python ".agents/scripts/crucible_gate.py" doctor
        if ($LASTEXITCODE -ne 0) {
            throw "crucible_gate.py doctor failed with exit code $LASTEXITCODE"
        }
    } finally {
        Pop-Location
    }
}
