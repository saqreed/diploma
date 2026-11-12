param([switch]$Watch, [string]$Project = 'diploma-project')
$ErrorActionPreference = 'Stop'
if ($Project -notmatch '^[a-z0-9][a-z0-9_-]+$') { throw 'Неверное имя Compose-проекта' }
$directory = Join-Path (Split-Path $PSScriptRoot -Parent) 'config/local-inventory'
New-Item -ItemType Directory -Force -Path $directory | Out-Null
do {
    $sources = @()
    $warnings = @()
    $ids = @(docker ps --filter "label=com.docker.compose.project=$Project" --filter 'label=diploma.source.kind' --format '{{.ID}}')
    if ($LASTEXITCODE -ne 0) { $warnings += 'Не удалось обновить инвентарь Docker' }
    foreach ($id in $ids) {
        # Inspect labels only, never environment variables or secrets.
        $labels = docker inspect --format '{{json .Config.Labels}}' $id | ConvertFrom-Json
        if ($LASTEXITCODE -ne 0) { $warnings += 'Один сервис исчез во время обновления'; continue }
        $kind = $labels.'diploma.source.kind'
        if ($kind -notin @('postgresql','mysql','mongodb')) { $kind = 'unknown' }
        $sources += @{id=$labels.'com.docker.compose.service';kind=$kind;host=$labels.'diploma.source.host';port=[int]$labels.'diploma.source.port';origin="Compose $Project / $($labels.'com.docker.compose.service')"}
    }
    $data = @{updated_at=[DateTime]::UtcNow.ToString('o');sources=@($sources);warnings=@($warnings)} | ConvertTo-Json -Depth 8
    $temporary = Join-Path $directory 'inventory.tmp'
    [IO.File]::WriteAllText($temporary, $data)
    Move-Item -LiteralPath $temporary -Destination (Join-Path $directory 'inventory.json') -Force
    if ($Watch) { Start-Sleep -Seconds 10 }
} while ($Watch)
