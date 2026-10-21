# Shared by every provisioning step; dot-source it.
#
# Environment:
#   RIG_FIXTURES  where tests/fixtures/rig/ was copied (default C:\rig\fixtures)
#   RIG_MIRROR    a base URL serving downloads.json's files by name; each file is
#                 fetched from its own URL when unset. Either way its SHA256 is checked.

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$RigRoot = "C:\rig"
$RigDownloads = Join-Path $RigRoot "downloads"
$RigFixtures = if ($env:RIG_FIXTURES) { $env:RIG_FIXTURES } else { Join-Path $RigRoot "fixtures" }
$RigProfile = Join-Path $RigFixtures "nina-simulator.profile"

# An entry is one pin, or a list of them with one per `arch`.
function Get-RigPin([string]$Name) {
    $pins = Get-Content (Join-Path $PSScriptRoot "downloads.json") -Raw | ConvertFrom-Json
    if (-not $pins.$Name) { throw "downloads.json has no entry '$Name'" }
    $pin = @($pins.$Name) | Where-Object { -not $_.arch -or $_.arch -eq $env:PROCESSOR_ARCHITECTURE }
    if (-not $pin) { throw "downloads.json pins '$Name' for no $env:PROCESSOR_ARCHITECTURE guest" }
    $pin
}

function Get-RigDownload([string]$Name) {
    $pin = Get-RigPin $Name
    $file = ([uri]$pin.url).Segments[-1]
    $path = Join-Path $RigDownloads $file
    New-Item -ItemType Directory -Force -Path $RigDownloads | Out-Null
    if (-not (Test-Path $path) -or (Get-FileHash $path -Algorithm SHA256).Hash -ne $pin.sha256) {
        $url = if ($env:RIG_MIRROR) { "$($env:RIG_MIRROR.TrimEnd('/'))/$file" } else { $pin.url }
        Write-Host "downloading $url"
        & curl.exe --fail --location --silent --show-error --retry 5 --output $path $url
        if ($LASTEXITCODE -ne 0) { throw "curl exited $LASTEXITCODE fetching $url" }
        $hash = (Get-FileHash $path -Algorithm SHA256).Hash
        if ($hash -ne $pin.sha256) { throw "$file has SHA256 $hash, expected $($pin.sha256)" }
    }
    $path
}

function Get-RigProfileId {
    ([xml](Get-Content $RigProfile -Raw -Encoding UTF8)).Profile.Id
}

# Runs a program in the current user's desktop session, for one that needs a
# window or a tray icon, and returns once $Until holds. The program is stopped
# then if it is still running.
function Invoke-RigInDesktop([string]$Path, [string]$Arguments, [scriptblock]$Until, [int]$TimeoutSeconds = 300) {
    $desktop = Get-Process explorer -IncludeUserName -ErrorAction SilentlyContinue |
        Where-Object { $_.UserName -like "*\$env:USERNAME" }
    if (-not $desktop) { throw "$env:USERNAME is not logged on at the console" }
    $leaf = Split-Path $Path -Leaf
    $name = "rig-desktop-" + [guid]::NewGuid().ToString("N").Substring(0, 8)
    $action = New-ScheduledTaskAction -Execute $Path -Argument $Arguments
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest
    Register-ScheduledTask -TaskName $name -Action $action -Principal $principal -Force | Out-Null
    try {
        Write-Host "running $leaf $Arguments in the desktop session"
        Start-ScheduledTask -TaskName $name
        $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
        while (-not (& $Until)) {
            if ((Get-Date) -gt $deadline) { throw "$leaf $Arguments did not finish in $TimeoutSeconds s" }
            Start-Sleep -Seconds 3
        }
    } finally {
        Stop-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $name -Confirm:$false
    }
}

# Runs an installer to completion; a nonzero exit outside $Allowed throws.
function Invoke-RigInstaller([string]$Path, [string[]]$Arguments, [int[]]$Allowed = @(0)) {
    $leaf = Split-Path $Path -Leaf
    Write-Host "running $leaf $Arguments"
    $process = Start-Process -FilePath $Path -ArgumentList $Arguments -Wait -PassThru
    if ($Allowed -notcontains $process.ExitCode) { throw "$leaf exited $($process.ExitCode)" }
}

# New-Item -Force on a registry key that exists empties it; this keeps its values.
function New-RigKey([string]$Key) {
    if (-not (Test-Path $Key)) { New-Item -Path $Key -Force | Out-Null }
}
