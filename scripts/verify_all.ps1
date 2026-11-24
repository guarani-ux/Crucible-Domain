#!/usr/bin/env pwsh
$HubRoot = Split-Path -Parent $PSScriptRoot
python "$HubRoot/.agents/scripts/verify_all.py" --root "$HubRoot" @args
exit $LASTEXITCODE
