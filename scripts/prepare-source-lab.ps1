$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
$envPath = Join-Path $repo '.env.sources'
if (!(Test-Path -LiteralPath $envPath)) {
    $reader = [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(24))
    $admin = [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(24))
    [IO.File]::WriteAllText($envPath, "SOURCE_LAB_ADMIN_PASSWORD=$admin`nSOURCE_LAB_READER_PASSWORD=$reader`n")
}
New-Item -ItemType Directory -Force -Path (Join-Path $repo 'config/local-inventory') | Out-Null
Write-Output 'Учебные секреты подготовлены в .env.sources. Существующие данные и пароли сохранены.'
