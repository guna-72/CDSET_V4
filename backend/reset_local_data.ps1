# Remove local Chaos Tutor project data only.
# Firebase Authentication accounts and the frontend source are not affected.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$data = Join-Path $root 'data'

Write-Host 'This will remove local SQLite project history, uploaded workspaces, and generated experiment data.' -ForegroundColor Yellow
$answer = Read-Host 'Continue? (Y/N)'
if ($answer -notin @('Y','y')) { Write-Host 'Cancelled.'; exit 0 }

if (Test-Path $data) {
    Remove-Item $data -Recurse -Force
}
New-Item -ItemType Directory -Force (Join-Path $data 'storage') | Out-Null
New-Item -ItemType Directory -Force (Join-Path $data 'workspace') | Out-Null
New-Item -ItemType File -Force (Join-Path $data 'storage\.gitkeep') | Out-Null
New-Item -ItemType File -Force (Join-Path $data 'workspace\.gitkeep') | Out-Null

Write-Host 'Local project data cleared. Restart the backend.' -ForegroundColor Green
