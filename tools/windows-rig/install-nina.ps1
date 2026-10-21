# Installs one channel's N.I.N.A. and plugins. `rig.py install` writes the
# channel file from channels.toml and runs this over SSH:
#
#   {"nina": {"url": ..., "sha256": ...}, "plugins": "3.0.0",
#    "plugin": [{"name": ..., "url": ..., "sha256": ...}, ...]}
#
# A sha256 may be null, for a nightly build that publishes none. Exits 3010
# when N.I.N.A.'s installer wants a restart.

param([Parameter(Mandatory)][string]$Channel)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$pins = Get-Content $Channel -Raw | ConvertFrom-Json
$downloads = "C:\rig\downloads"
New-Item -ItemType Directory -Force -Path $downloads | Out-Null

function Save-Pin($pin) {
    $path = Join-Path $downloads ([uri]$pin.url).Segments[-1]
    Write-Host "downloading $($pin.url)"
    & curl.exe --fail --location --silent --show-error --retry 5 --output $path $pin.url
    if ($LASTEXITCODE -ne 0) { throw "curl exited $LASTEXITCODE fetching $($pin.url)" }
    if ($pin.sha256) {
        $hash = (Get-FileHash $path -Algorithm SHA256).Hash
        if ($hash -ne $pin.sha256) { throw "$path has SHA256 $hash, expected $($pin.sha256)" }
    }
    $path
}

$bundle = Join-Path $downloads "nina"
Expand-Archive -Path (Save-Pin $pins.nina) -DestinationPath $bundle -Force
$setup = Get-ChildItem $bundle -Recurse -Filter "NINASetupBundle.exe" | Select-Object -First 1
if (-not $setup) { throw "no NINASetupBundle.exe in the N.I.N.A. archive" }
$log = Join-Path $downloads "nina-install.log"
$process = Start-Process $setup.FullName -ArgumentList "/quiet", "/norestart", "/log", "`"$log`"" -Wait -PassThru
if ($process.ExitCode -notin 0, 3010) { throw "NINASetupBundle.exe exited $($process.ExitCode); see $log" }

$plugins = Join-Path $env:LOCALAPPDATA "NINA\Plugins\$($pins.plugins)"
foreach ($plugin in $pins.plugin) {
    $target = Join-Path $plugins $plugin.name
    Remove-Item $target -Recurse -Force -ErrorAction SilentlyContinue
    Expand-Archive -Path (Save-Pin $plugin) -DestinationPath $target
    Write-Host "installed $($plugin.name) into $target"
}

Remove-Item $downloads -Recurse -Force
exit $process.ExitCode
