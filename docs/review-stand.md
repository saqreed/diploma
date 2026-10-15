# Проверка на отдельном учебном стенде

Основной запуск и учебные роли описаны в корневом README. Этот стенд предназначен для воспроизведения проверок на накопленных данных и отрицательных сценариев. Он использует отдельный PostgreSQL-том и API на `127.0.0.1:28000`. Существующие заявки основного проекта `diploma-project` не сбрасываются.

Команды PowerShell выполняются из корня репозитория после подготовки локального `.env` по README. Нужны Docker Desktop, Node.js и Python с тестовыми зависимостями backend. Не выводите `.env` и приватный fixture в терминал или Git.

```powershell
docker compose -p diploma-review-20261008 -f docker-compose.yml -f docker-compose.review.yml build backend
docker compose -p diploma-review-20261008 -f docker-compose.yml -f docker-compose.review.yml up -d --wait postgres
docker compose -p diploma-review-20261008 -f docker-compose.yml -f docker-compose.review.yml --profile tools run --rm bootstrap
docker compose -p diploma-review-20261008 -f docker-compose.yml -f docker-compose.review.yml up -d --wait backend

./scripts/prepare-review-scale.ps1
New-Item -ItemType Directory -Path diploma-docs/07_reports -Force | Out-Null
python scripts/review-http.py --phase after --output diploma-docs/07_reports/review-http.json
```

Seeder создаёт 10 000 синтетических заявок, не фактических событий. Его повтор не меняет существующие строки. `review-http.py` проверяет страницы/поиск/очереди, ограничение владельца, явные действия, повтор согласования, конкурентную выплату, REVIEW+CONFIRM, запрет, изменение версии и фильтр текущей операции.

Для обычных интеграционных проверок укажите API этого стенда:

```powershell
$env:DIPLOMA_TEST_URL = 'http://127.0.0.1:28000'
Push-Location backend
python -m pytest -q
python tests/http_scenario.py
python tests/http_mechanisms.py
python tests/http_settings.py
python tests/http_source.py
python tests/http_demo_source.py
python tests/http_states.py
Pop-Location
```

`http_restart.py`, `check_logs.py` и `http_registry_reset.py` требуют отдельного внимания: сначала задайте `COMPOSE_PROJECT_NAME=diploma-review-20261008` и абсолютный `COMPOSE_FILE` из двух Compose-файлов. Reset архивирует весь текущий набор заявок и восстанавливает пять исходных, поэтому его запускают только здесь. После reset масштабный набор можно восстановить seeder. Не запускайте reset, перезапуск или изменение правил одновременно с браузерным сценарием.

Нагрузочный fixture содержит ключ приложения и остаётся в локальной папке пользователя. Это другой набор: 10 000 фактических событий, 20 правил, 5 проверок/с на протяжении 300 секунд. Задержка подключённой БД измеряется отдельно, согласно README.

```powershell
$qaDirectory = Join-Path $env:LOCALAPPDATA 'DiplomaValidation/review'
New-Item -ItemType Directory -Path $qaDirectory -Force | Out-Null
Push-Location backend
python tests/performance.py --duration 300 --output "$qaDirectory/performance.json" --fixture-cache "$qaDirectory/fixture.json"
Pop-Location
npm --prefix frontend ci
npm --prefix frontend run check

./scripts/test-browser-container.ps1 -Browser chromium -Scenario flow -SkipDemoReset -ReviewProject diploma-review-20261008 -FixtureCache "$qaDirectory/fixture.json" -Build
./scripts/test-browser-container.ps1 -Browser chromium -Scenario editor -SkipDemoReset -ReviewProject diploma-review-20261008 -FixtureCache "$qaDirectory/fixture.json"
./scripts/test-browser-container.ps1 -Browser chromium -Scenario review -SkipDemoReset -ReviewProject diploma-review-20261008 -FixtureCache "$qaDirectory/fixture.json"
./scripts/test-browser-container.ps1 -Browser firefox -Scenario flow -SkipDemoReset -ReviewProject diploma-review-20261008 -FixtureCache "$qaDirectory/fixture.json"
./scripts/test-browser-container.ps1 -Browser firefox -Scenario editor -SkipDemoReset -ReviewProject diploma-review-20261008 -FixtureCache "$qaDirectory/fixture.json"
./scripts/test-browser-container.ps1 -Browser firefox -Scenario review -SkipDemoReset -ReviewProject diploma-review-20261008 -FixtureCache "$qaDirectory/fixture.json"
```

Браузерные сценарии используют production-сборку, настоящий API и сохранённую PostgreSQL. Они выполняются последовательно. Отчёты/снимки попадают в игнорируемую папку `diploma-docs/07_reports`, временные файлы credentials удаляются после запуска. Сценарий review временно меняет TTL/источник demo и восстанавливает их в finally. После аварийного прекращения всего процесса следует проверить восстановление конфигурации на этом отдельном стенде.

Для осмотра 10 000 заявок во втором интерфейсе:

```powershell
$env:DIPLOMA_UI_API_URL = 'http://127.0.0.1:28000'
npm --prefix frontend run dev -- --host 127.0.0.1 --port 25173
```

Завершив проверки, удалите тестовые переменные из своей shell-сессии. Основной интерфейс по-прежнему использует API на `127.0.0.1:8000`.
