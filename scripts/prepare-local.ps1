$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $projectRoot '.env'
$existing = if (Test-Path -LiteralPath $envPath) { [IO.File]::ReadAllText($envPath) } else { '' }
$names = @('POSTGRES_PASSWORD', 'DIPLOMA_AF_PASSWORD', 'DIPLOMA_DEMO_PASSWORD', 'DIPLOMA_READER_PASSWORD', 'DIPLOMA_SEED_PASSWORD', 'DIPLOMA_DEMO_API_KEY', 'DIPLOMA_SOURCE_ENCRYPTION_KEY')
$added = 0
foreach ($name in $names) {
    if ($existing -match "(?m)^$name=.+$") { continue }
    $bytes = New-Object byte[] 32
    [Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
    $value = if ($name -eq 'DIPLOMA_SOURCE_ENCRYPTION_KEY') { [Convert]::ToBase64String($bytes).Replace('+', '-').Replace('/', '_') } else { [Convert]::ToHexString($bytes).ToLowerInvariant() }
    $existing += "`n$name=$value`n"
    $added++
}
[IO.File]::WriteAllText($envPath, $existing, (New-Object Text.UTF8Encoding $false))
Write-Output "Local configuration ready; $added missing values generated. Existing values preserved; secrets are not displayed."
