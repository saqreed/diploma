param([string]$Destination = (Join-Path $env:LOCALAPPDATA 'DiplomaValidation/tls/root.crt'))
$ErrorActionPreference = 'Stop'
$appDirectory = Split-Path -Parent $PSScriptRoot
New-Item -ItemType Directory -Path (Split-Path -Parent $Destination) -Force | Out-Null
Push-Location $appDirectory
try {
    $webContainerId = docker compose -f docker-compose.yml -f docker-compose.https.yml ps -q web
    if (!$webContainerId) {throw 'Start the local HTTPS service first.'}
    docker cp "${webContainerId}:/data/caddy/pki/authorities/local/root.crt" $Destination
    if ($LASTEXITCODE -ne 0) {throw 'Cannot export the public local CA certificate.'}
    Write-Output 'Public CA exported. No certificate trust store was changed.'
} finally {Pop-Location}
