# ASTAP's command-line solver and its D05 star database, for N.I.N.A.'s plate solving.

. (Join-Path $PSScriptRoot "common.ps1")

$astap = Join-Path $RigRoot "ASTAP"
foreach ($name in "astap", "astap-d05") {
    Expand-Archive -Path (Get-RigDownload $name) -DestinationPath $astap -Force
}
if (-not (Test-Path (Join-Path $astap "astap_cli.exe"))) { throw "astap_cli.exe is not in $astap" }
