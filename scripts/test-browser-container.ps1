param(
    [ValidateSet('chromium', 'firefox')][string]$Browser = 'chromium',
    [ValidateSet('flow', 'editor', 'review')][string]$Scenario = 'flow',
    [string]$FixtureCache = (Join-Path $env:LOCALAPPDATA 'DiplomaValidation/performance/fixture.json'),
    [switch]$Build,
    [switch]$SkipDemoReset,
    [ValidatePattern('^diploma-review-20261008$')][string]$ReviewProject,
    [string]$ReportPrefix = 'browser'
)
$ErrorActionPreference = 'Stop'
if ($Scenario -eq 'review' -and !$ReviewProject) {throw 'Negative review scenario requires the isolated review project.'}
$appDirectory = Split-Path -Parent $PSScriptRoot
$reportDirectory = Join-Path $appDirectory 'diploma-docs/07_reports'
$qaDirectory = Join-Path $reportDirectory '.browser-qa'
$qaInputDirectory = Join-Path $qaDirectory 'input'
$qaEnvironmentPath = Join-Path $qaInputDirectory '.env'
$qaFixturePath = Join-Path $qaInputDirectory 'fixture.json'
$qaScreenshots = Join-Path $qaDirectory "screenshots/$Browser/$Scenario"
if (!(Test-Path -LiteralPath $FixtureCache -PathType Leaf)) {throw 'Prepare the private performance fixture first; see README.'}
if (!(Test-Path -LiteralPath (Join-Path $appDirectory 'frontend/dist/index.html'))) {throw 'Build frontend production assets first.'}
New-Item -ItemType Directory -Path $qaInputDirectory,$qaScreenshots,$reportDirectory -Force | Out-Null
Push-Location $appDirectory
try {
    if ($Build) {
        docker build -t diploma-browser-qa -f frontend/tests/Dockerfile.browser frontend/tests
        if ($LASTEXITCODE -ne 0) {throw 'QA image build failed.'}
    }
    $backendId = if ($ReviewProject) { docker compose -p $ReviewProject -f docker-compose.yml -f docker-compose.review.yml ps -q backend } else { docker compose ps -q backend }
    if (!$backendId) {throw 'Start the existing backend and PostgreSQL first.'}
    $projectName = docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' $backendId
    if ($LASTEXITCODE -ne 0) {throw 'Cannot identify the local Compose network.'}
    $allowedNames = @('DIPLOMA_SEED_PASSWORD', 'DIPLOMA_READER_PASSWORD', 'POSTGRES_DB')
    $selectedEnvironment = @(Get-Content -LiteralPath .env | Where-Object {$allowedNames -contains ($_.Split('=',2)[0])})
    if (@($selectedEnvironment | Where-Object {$_ -like 'DIPLOMA_*'}).Count -ne 2) {throw 'Local QA account/source credentials are missing.'}
    Set-Content -LiteralPath $qaEnvironmentPath -Value $selectedEnvironment
    Copy-Item -LiteralPath $FixtureCache -Destination $qaFixturePath -Force
    $browserLabel = if ($Browser -eq 'chromium') {'chrome-linux'} else {'firefox-linux'}
    $browserExecutable = if ($Browser -eq 'chromium') {'/opt/qa-browsers/chrome-linux64/chrome'} else {'/opt/qa-browsers/firefox/firefox'}
    $dockerArguments = @('run','--rm','--init','--shm-size=1g','--network',"${projectName}_default",'--workdir','/qa/repository/frontend',
        '--mount',"type=bind,source=$($appDirectory.Replace('\','/'))/frontend/dist,target=/qa/repository/frontend/dist,readonly",
        '--mount',"type=bind,source=$($appDirectory.Replace('\','/'))/frontend/tests,target=/qa/repository/frontend/tests,readonly",
        '--mount',"type=bind,source=$($qaInputDirectory.Replace('\','/')),target=/qa/input,readonly",
        '--mount',"type=bind,source=$($qaScreenshots.Replace('\','/')),target=/qa/screenshots",
        '--mount',"type=bind,source=$($reportDirectory.Replace('\','/')),target=/qa/repository/diploma-docs/07_reports",
        '-e','QA_ENV_FILE=/qa/input/.env','-e','QA_FIXTURE_CACHE=/qa/input/fixture.json',
        '-e',"QA_REPORT_NAME=$ReportPrefix-$browserLabel-$Scenario.json")
    if ($SkipDemoReset) {$dockerArguments += @('-e','QA_SKIP_DEMO_RESET=1')}
    if ($ReviewProject) {$dockerArguments += @('-e','QA_ISOLATED_REVIEW=1')}
    if ($Browser -eq 'firefox') {$dockerArguments += @('-e','QA_BROWSER_CHANNEL=moz-firefox')}
    $dockerArguments += @('diploma-browser-qa','node','tests/local-qa-server.cjs',$Browser,$browserExecutable)
    if ($Scenario -ne 'flow') {$dockerArguments += $Scenario}
    & docker @dockerArguments
    if ($LASTEXITCODE -ne 0) {throw 'Browser acceptance failed; see its safe stage message.'}
} finally {
    # Delete only this runner's temporary credential file, never application data.
    foreach ($qaTemporaryFile in @($qaEnvironmentPath,$qaFixturePath)) {
        if (Test-Path -LiteralPath $qaTemporaryFile -PathType Leaf) {Remove-Item -LiteralPath $qaTemporaryFile}
    }
    Pop-Location
}
