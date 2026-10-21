# Turns a clean Windows 11, x64 or ARM64, into the rig. Run it elevated, from
# this folder's copy in the guest, with tests/fixtures/rig/ copied to
# C:\rig\fixtures (or RIG_FIXTURES pointing at it). Each step reads the
# environment its header names.
#
# Packer runs it in the base image; so can a Windows VM made by hand.

$ErrorActionPreference = "Stop"

# -Filter takes no character ranges, so the step pattern is a regex here.
$steps = Get-ChildItem -Path $PSScriptRoot -Filter "*.ps1" | Where-Object Name -Match "^\d\d-" | Sort-Object Name
if (-not $steps) { throw "no provisioning steps in $PSScriptRoot" }
foreach ($step in $steps) {
    Write-Host "=== $($step.BaseName)"
    $started = Get-Date
    & $step.FullName
    Write-Host ("=== {0} done in {1:N0}s" -f $step.BaseName, ((Get-Date) - $started).TotalSeconds)
}
# Packer exits with $LASTEXITCODE, which the last native command left behind.
exit 0
