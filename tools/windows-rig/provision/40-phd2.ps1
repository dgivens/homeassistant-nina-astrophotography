# PHD2, with the fixture's settings loaded before it first starts.

. (Join-Path $PSScriptRoot "common.ps1")

$phd2 = Join-Path $RigRoot "PHD2\phd2.exe"
$installer = Get-RigDownload "phd2"
Invoke-RigInstaller $installer "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", "/DIR=$(Split-Path $phd2)"

# `-l` replaces every setting with the file's and exits. Loaded before the first
# start, it also keeps PHD2's first-light wizard from opening.
$settings = Join-Path $RigFixtures "phd2-simulator.phdcfg"
Invoke-RigInstaller $phd2 "-l", "`"$settings`""
$profiles = Get-ChildItem "HKCU:\Software\StarkLabs\PHDGuidingV2\profile" -ErrorAction SilentlyContinue
if (-not $profiles) { throw "phd2 -l loaded no profile from $settings" }
