param(
    [switch]$Watch,
    [string]$Project = 'diploma-project',
    [ValidateSet('All', 'Compose', 'Windows')][string]$Scope = 'All',
    [string]$WindowsTargetHost = 'host.docker.internal'
)
$ErrorActionPreference = 'Stop'
if ($Project -notmatch '^[a-z0-9][a-z0-9_-]+$') { throw 'Неверное имя Compose-проекта' }
$directory = Join-Path (Split-Path $PSScriptRoot -Parent) 'config/local-inventory'
New-Item -ItemType Directory -Force -Path $directory | Out-Null
$engineByProcess = @{ postgres = 'postgresql'; mysqld = 'mysql'; mongod = 'mongodb' }
do {
    $sources = @()
    $warnings = @()
    if ($Scope -ne 'Windows') {
        try {
            $ids = @(docker ps --filter "label=com.docker.compose.project=$Project" --filter 'label=diploma.source.kind' --format '{{.ID}}' 2>$null)
            if ($LASTEXITCODE -ne 0) { throw 'Docker is unavailable' }
            foreach ($id in $ids) {
                $rawLabels = docker inspect --format '{{json .Config.Labels}}' $id 2>$null
                if ($LASTEXITCODE -ne 0) { $warnings += 'Один сервис исчез во время обновления'; continue }
                $labels = $rawLabels | ConvertFrom-Json
                $kind = $labels.'diploma.source.kind'
                if ($kind -notin @('postgresql','mysql','mongodb')) { $kind = 'unknown' }
                $sources += @{id=$labels.'com.docker.compose.service';kind=$kind;host=$labels.'diploma.source.host';port=[int]$labels.'diploma.source.port';origin="Compose $Project / $($labels.'com.docker.compose.service')"}
            }
        } catch {
            $warnings += 'Не удалось обновить инвентарь Docker'
        }
    }
    if ($Scope -ne 'Compose') {
        try {
            $engines = @{}
            foreach ($dbProcess in (Get-Process -Name @($engineByProcess.Keys) -ErrorAction SilentlyContinue)) {
                $engines[[int]$dbProcess.Id] = $engineByProcess[$dbProcess.ProcessName]
            }
            if ($engines.Count) {
                $windowsKeys = @{}
                foreach ($listener in (Get-NetTCPConnection -State Listen)) {
                    $kind = $engines[[int]$listener.OwningProcess]
                    if (!$kind) { continue }
                    $address = $listener.LocalAddress
                    $targetHost = if ($address -in @('0.0.0.0', '::', '127.0.0.1', '::1')) { $WindowsTargetHost } else { $address }
                    $entryKey = "windows-${kind}-${targetHost}-$($listener.LocalPort)"
                    if ($windowsKeys.ContainsKey($entryKey)) { continue }
                    $windowsKeys[$entryKey] = $true
                    $sources += @{id=$entryKey;kind=$kind;host=$targetHost;port=[int]$listener.LocalPort;origin="Windows / $kind"}
                }
            }
        } catch {
            $warnings += 'Не удалось прочитать локальные порты Windows'
        }
    }
    $scopeLabel = switch ($Scope) {
        'Compose' { "Compose $Project" }
        'Windows' { 'Локальные процессы Windows' }
        'All' { "Compose $Project и локальные процессы Windows" }
    }
    $data = @{updated_at=[DateTime]::UtcNow.ToString('o');scope=$scopeLabel;sources=@($sources);warnings=@($warnings)} | ConvertTo-Json -Depth 8
    $temporary = Join-Path $directory 'inventory.tmp'
    [IO.File]::WriteAllText($temporary, $data)
    Move-Item -LiteralPath $temporary -Destination (Join-Path $directory 'inventory.json') -Force
    if ($Watch) { Start-Sleep -Seconds 10 }
} while ($Watch)
