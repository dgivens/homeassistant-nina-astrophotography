# Windows settings the rig needs: an always-on desktop, no update or telemetry
# noise, scripts allowed, RDP, and no firewall.

. (Join-Path $PSScriptRoot "common.ps1")

function Set-Policy([string]$Key, [string]$Name, [int]$Value) {
    New-RigKey $Key
    Set-ItemProperty -Path $Key -Name $Name -Value $Value -Type DWord
}

# The desktop session hosts N.I.N.A.; nothing may sleep, lock or blank it.
foreach ($arguments in @("/hibernate", "off"), @("/change", "monitor-timeout-ac", "0"),
    @("/change", "standby-timeout-ac", "0"), @("/change", "disk-timeout-ac", "0")) {
    & powercfg @arguments
    if ($LASTEXITCODE -ne 0) { throw "powercfg $arguments exited $LASTEXITCODE" }
}
Set-Policy "HKLM:\SOFTWARE\Policies\Microsoft\Windows\Personalization" "NoLockScreen" 1
Set-Policy "HKLM:\SOFTWARE\Policies\Microsoft\Windows\Control Panel\Desktop" "ScreenSaveActive" 0

# A rig never updates itself: every session starts from the same layer. The
# service stays startable, because enabling .NET 3.5 fetches it through Windows Update.
Set-Policy "HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU" "NoAutoUpdate" 1
Set-Policy "HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU" "AUOptions" 1
Set-Service -Name wuauserv -StartupType Manual

Set-Policy "HKLM:\SOFTWARE\Policies\Microsoft\Windows\DataCollection" "AllowTelemetry" 0
Set-Policy "HKLM:\SOFTWARE\Policies\Microsoft\Dsh" "AllowNewsAndInterests" 0
Set-Policy "HKLM:\SOFTWARE\Policies\Microsoft\Windows\Windows Search" "DisableWebSearch" 1
Set-Policy "HKLM:\SOFTWARE\Policies\Microsoft\Edge" "HideFirstRunExperience" 1

# What `Set-ExecutionPolicy -Scope LocalMachine` writes. The cmdlet itself
# throws when a narrower scope overrides it, as Packer's Bypass does.
Set-ItemProperty "HKLM:\SOFTWARE\Microsoft\PowerShell\1\ShellIds\Microsoft.PowerShell" -Name ExecutionPolicy -Value RemoteSigned

Set-ItemProperty -Path "HKLM:\System\CurrentControlSet\Control\Terminal Server" -Name "fDenyTSConnections" -Value 0 -Type DWord
Set-ItemProperty -Path "HKLM:\System\CurrentControlSet\Control\Terminal Server\WinStations\RDP-Tcp" -Name "UserAuthentication" -Value 1 -Type DWord

# PHD2 and OmniSim each raise a firewall prompt the first time they listen.
Set-NetFirewallProfile -Profile Domain, Private, Public -Enabled False
