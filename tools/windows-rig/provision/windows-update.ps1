# Installs downloads.json's pinned cumulative update. Packer runs it before
# provision.ps1 and restarts the guest after it; a Windows VM made by hand takes
# its updates from Windows Update instead.

. (Join-Path $PSScriptRoot "common.ps1")

$msu = Get-RigDownload "windows-update"
& dism.exe /Online /Add-Package "/PackagePath:$msu" /NoRestart /Quiet
# 3010: installed, restart required. 0x800F081E: already installed or superseded.
if ($LASTEXITCODE -notin 0, 3010, -2146498530) { throw "DISM exited $LASTEXITCODE" }
Remove-Item $msu
exit 0
