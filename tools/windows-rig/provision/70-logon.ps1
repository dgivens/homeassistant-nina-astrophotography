# Logs the current user on at every boot, and starts N.I.N.A. on the simulator
# profile when they do. N.I.N.A., OmniSim and PHD2 need that desktop session.
#
# Environment:
#   RIG_PASSWORD  the current user's password, stored for autologon

. (Join-Path $PSScriptRoot "common.ps1")

if (-not $env:RIG_PASSWORD) { throw "RIG_PASSWORD is not set" }

$winlogon = "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon"
Set-ItemProperty $winlogon -Name AutoAdminLogon -Value "1"
Set-ItemProperty $winlogon -Name DefaultUserName -Value $env:USERNAME
Set-ItemProperty $winlogon -Name DefaultDomainName -Value $env:COMPUTERNAME
Set-ItemProperty $winlogon -Name DefaultPassword -Value $env:RIG_PASSWORD
# Left by the answer file's autologon, which Windows turns off when it counts down to zero.
Remove-ItemProperty $winlogon -Name AutoLogonCount -ErrorAction SilentlyContinue

# Opens no sequence: `rig.py wait` connects the equipment through the API. The
# check lets the base image, which has no N.I.N.A. yet, log on quietly.
$nina = "C:\Program Files\N.I.N.A. - Nighttime Imaging 'N' Astronomy\NINA.exe"
$startup = Join-Path ([Environment]::GetFolderPath("Startup")) "start-nina.cmd"
Set-Content -Path $startup -Encoding ascii -Value @(
    "@echo off",
    "rem Starts N.I.N.A. on the simulator profile at logon.",
    "if exist `"$nina`" start `"`" `"$nina`" --profileid $(Get-RigProfileId)"
)
