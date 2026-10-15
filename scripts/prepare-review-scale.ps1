# Synthetic REQUESTS only. Factual event history is prepared by performance.py separately.
$ErrorActionPreference = 'Stop'
$reviewProject = 'diploma-review-20261008'
$repositoryPath = Split-Path -Parent $PSScriptRoot
Push-Location $repositoryPath
try {
    $databaseId = docker compose -p $reviewProject -f docker-compose.yml -f docker-compose.review.yml ps -q postgres
    if (!$databaseId) {throw 'Start the isolated review PostgreSQL first.'}
    $actualProject = docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' $databaseId
    if ($actualProject -ne $reviewProject) {throw 'Refusing to seed a different project.'}
    $sql = @'
INSERT INTO demo.requests (id,author,amount,recipient,receipt,vendor,purchase_date,title,version,status,history,category,created_at)
SELECT 'review-scale-' || lpad(i::text,5,'0'),
       CASE WHEN i%2=0 THEN 'employee' ELSE 'employee2' END,
       500, 'Учебный получатель', 'REVIEW-SCALE-' || i, 'Учебный магазин', CURRENT_DATE,
       'Масштабная заявка ' || i, 1,
       CASE WHEN i%3=0 THEN 'SUBMITTED' ELSE 'DRAFT' END,
       '[]'::json, 'other', CURRENT_DATE + i * interval '1 second'
FROM generate_series(1,10000) AS series(i)
ON CONFLICT (id) DO NOTHING;
SELECT count(*) AS synthetic_requests FROM demo.requests WHERE id LIKE 'review-scale-%';
'@
    $sql | docker exec -i $databaseId sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
    if ($LASTEXITCODE -ne 0) {throw 'Review seeding failed.'}
} finally {Pop-Location}
