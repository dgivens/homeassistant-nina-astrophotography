# OpenSSH Server, with PowerShell as its shell and the host's key authorised.
#
# Environment:
#   RIG_SSH_PUBLIC_KEY  an OpenSSH public key line, authorised for every administrator

. (Join-Path $PSScriptRoot "common.ps1")

$capability = Get-WindowsCapability -Online -Name "OpenSSH.Server*"
if ($capability.State -ne "Installed") {
    Add-WindowsCapability -Online -Name $capability.Name | Out-Null
}
Set-Service -Name sshd -StartupType Automatic
Start-Service -Name sshd

New-RigKey "HKLM:\SOFTWARE\OpenSSH"
New-ItemProperty -Path "HKLM:\SOFTWARE\OpenSSH" -Name DefaultShell -PropertyType String -Force `
    -Value "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" | Out-Null

if ($env:RIG_SSH_PUBLIC_KEY) {
    # sshd reads an administrator's keys from here, not ~\.ssh, and ignores the
    # file unless only Administrators and SYSTEM can write it.
    $keys = Join-Path $env:ProgramData "ssh\administrators_authorized_keys"
    Set-Content -Path $keys -Value $env:RIG_SSH_PUBLIC_KEY.Trim() -Encoding ascii
    & icacls.exe $keys /inheritance:r /grant "*S-1-5-32-544:F" /grant "*S-1-5-18:F" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "icacls exited $LASTEXITCODE on $keys" }
}
