# .NET Framework 3.5, then ASCOM Platform, which brings OmniSim, and a check that
# every OmniSim device is registered with COM.

. (Join-Path $PSScriptRoot "common.ps1")

# ASCOM's installer enables .NET 3.5 itself, through a script that ends in
# `pause`; with it already on, the installer skips that script.
if ((Get-WindowsOptionalFeature -Online -FeatureName NetFx3).State -ne "Enabled") {
    Start-Service -Name wuauserv
    Enable-WindowsOptionalFeature -Online -FeatureName NetFx3 -All -NoRestart | Out-Null
}

$installer = Get-RigDownload "ascom"
Invoke-RigInstaller $installer "/s" -Allowed 0, 3010

# N.I.N.A. opens ASCOM.OmniSim.<Type>, served by an x86 proxy, which in turn
# opens OmniSim.<Type>, served by OmniSim itself. OmniSim registers both
# families, and the installer has it do so, but OmniSim exits at start without
# a desktop to put its tray icon on. Installed from anywhere else, every device
# then fails in N.I.N.A. with `MissingMethodException: .ctor`.
$types = "Camera", "CoverCalibrator", "Dome", "FilterWheel", "Focuser",
    "ObservingConditions", "Rotator", "SafetyMonitor", "Switch", "Telescope"

function Get-Unregistered {
    foreach ($type in $types) {
        foreach ($progId in "ASCOM.OmniSim.$type", "OmniSim.$type") {
            $clsid = (Get-ItemProperty "Registry::HKEY_CLASSES_ROOT\$progId\CLSID" -ErrorAction SilentlyContinue).'(default)'
            $served = $clsid -and (
                (Test-Path "Registry::HKEY_CLASSES_ROOT\CLSID\$clsid\LocalServer32") -or
                (Test-Path "Registry::HKEY_CLASSES_ROOT\WOW6432Node\CLSID\$clsid\LocalServer32"))
            if (-not $served) { $progId }
        }
    }
}

$missing = @(Get-Unregistered)
if ($missing) {
    Write-Host "$($missing.Count) OmniSim classes are not registered with COM"
    $omnisim = "${env:ProgramFiles}\ASCOM\OmniSimulator\ascom.alpaca.simulators.exe"
    Invoke-RigInDesktop $omnisim "/regserver" -Until { -not @(Get-Unregistered) }
}
Write-Host "all $($types.Count) OmniSim devices registered"

# The telescope's first start writes only some of its settings, and without
# CanLatLongElev it reports no site. N.I.N.A. then stops connecting it to ask
# whether to synchronise the site with the profile's.
$telescope = Join-Path $env:USERPROFILE ".ascom\Alpaca\ASCOM-Alpaca-Simulator\Telescope\v1"
New-Item -ItemType Directory -Force -Path $telescope | Out-Null
Copy-Item (Join-Path $RigFixtures "omnisim-telescope.xml") (Join-Path $telescope "Instance-0.xml") -Force
