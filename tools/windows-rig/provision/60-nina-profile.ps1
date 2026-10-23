# The simulator profile and the rig's sequences, in place before N.I.N.A. is
# installed or first starts.

. (Join-Path $PSScriptRoot "common.ps1")

# N.I.N.A. silently swaps a folder that does not exist for its default under
# the user's profile, and saves that the next time it saves the profile.
foreach ($folder in "images", "sequences\Targets", "sequences\Templates", "FramingAssistantCache") {
    New-Item -ItemType Directory -Force -Path (Join-Path $RigRoot $folder) | Out-Null
}

$profiles = Join-Path $env:LOCALAPPDATA "NINA\Profiles"
New-Item -ItemType Directory -Force -Path $profiles | Out-Null
Copy-Item $RigProfile (Join-Path $profiles "$(Get-RigProfileId).profile") -Force

$sequences = Join-Path $RigRoot "sequences"
Copy-Item (Join-Path $RigFixtures "test-sequence.json") (Join-Path $sequences "Test Sequence.json") -Force
Copy-Item (Join-Path $RigFixtures "simulated-night.json") (Join-Path $sequences "Simulated Night.json") -Force
