# Phase 2: Windows browser acceptance

Локальная установка: frontend <http://127.0.0.1:3000>, backend
<http://127.0.0.1:8000/health/ready>, revision `0010_economics`.
Используются существующие Playwright config и Windows Chromium.

## Preconditions

- Docker Desktop запущен, postgres/backend healthy, frontend/worker/scheduler работают.
- `.env`: `LOCAL_READ_ONLY=true`, `ACTIONS_ENABLED=false`, `AI_ENABLED=false`,
  `AI_AUTOPILOT_ALLOWED=false`; `APP_ENV` не production; Meta отключена.
- Перед миграцией создан и проверен backup. Для повторения E2E новую миграцию,
  downgrade, очистку volumes и изменение рекламных фактов выполнять не нужно.
- Зависимости frontend уже установлены. Используется установленный Node 24.
- После предыдущих попыток входа дождаться обычного окончания окна login rate limit
  (10 попыток / 900 секунд). Не отключать лимит, не очищать Redis keys, не менять IP.

## Run

```powershell
Set-Location E:\Creative_Factory\metric-control-center
$env:PATH = (Join-Path $PWD '.tools/node-v24.21.0-win-x64') + ';' + $env:PATH
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $PWD '.tools/playwright-browsers'
Push-Location frontend
npm.cmd run typecheck
if ($LASTEXITCODE -ne 0) { throw 'TypeScript failed' }
npm.cmd run test:unit
if ($LASTEXITCODE -ne 0) { throw 'Frontend unit tests failed' }
npm.cmd run test:e2e
if ($LASTEXITCODE -ne 0) { throw 'Browser acceptance failed' }
Pop-Location
```

Если Chromium отсутствует, из `frontend` выполнить `npx.cmd playwright install chromium`.
Если Docker установлен не в `%LOCALAPPDATA%\Programs\DockerDesktop`, перед тестами
задать `$env:DOCKER_EXE` абсолютным путём к своему `docker.exe`.

Только экономика: из `frontend` выполнить
`npx.cmd playwright test e2e/economics.spec.mjs`. Четыре сценария последовательные;
их общие данные создаются первым сценарием. Не запускать отдельно зависимый
сценарий колонок без профиля предыдущих сценариев.

`economics.spec.mjs` перед началом ждёт одну минуту, чтобы прежние suites не
исчерпали общий API minute budget. Timeout hook включает эту паузу. Это ожидание
не сбрасывает rate limits. Приёмка не должна маскировать 429 как PASS.

## Coverage

12 уникальных сценариев всего: 6 UI-1, 1 dashboard regression, 1 provider READ smoke,
4 economics. Экономика проверяет:

1. Decimal preview, недопустимый ROI, CRUD/copy/delete/restore версий, reload,
   account assignment и семь завершённых дат.
2. Approved/Rejected/Pending, исправление той же когорты без удвоения,
   сохранение и запрет выдуманного Actual ROI дочерним объявлениям.
3. Финансовые колонки, перенос видимых колонок мышью, resize/autofit, private preset,
   sorting/width/order после logout/login, 1440/768/390 px, собственную горизонтальную
   прокрутку и sticky name, удаление набора.
4. VIEWER read only, OPERATOR без grant, выдачу и отзыв grant администратором.

Контексты OPERATOR/VIEWER явно используют `storageState: { cookies: [], origins: [] }`:
Playwright наследует `use` options при `browser.newContext()`, поэтому иначе вход
другой ролью может отозвать унаследованную ADMIN session. Checkbox grants меняется
после ответа сервера: тест кликает и ожидает подтверждённое состояние, затем проверяет
права в отдельном контексте оператора.

Все economics pages проверяются на console errors, page exceptions и запросы
к рекламным mutation endpoints. Ожидается ноль.

Dashboard regression сверяет account rows с текущим каталогом из `/api/stats/filters`:
новые реальные аккаунты не должны ломать тест фиксированного количества.
Будущая дата определяется относительно `America/Los_Angeles`, без фиксированной
даты, которая со временем становится сегодняшней.

## Fixtures and evidence

`economics_accounts.py` допускает только локальный non-production READ mode и
revision `0010_economics`. Создаёт ADMIN/OPERATOR/VIEWER со случайным nonce и паролем
в памяти. В `finally` удаляет только их IDs, связанные private preferences/sessions,
их экономические профили, оценки, назначения, наблюдения, audit и grants.
Оригинальные пользователи и presets не изменяются. Рекламные facts не меняются.

При принудительном завершении процесса `finally` может не выполниться. Для такого
конкретного прогона использовать nonce из его временных email и cleanup mode той же
fixture. Не удалять пользователей/профили по широкому шаблону. Пример адресной очистки:

```powershell
$fixtureNonce = '<32 hex символа конкретного прерванного прогона>'
Get-Content frontend/e2e/economics_accounts.py -Raw -Encoding UTF8 |
  & $env:DOCKER_EXE compose --project-directory . --env-file .env `
    -f docker-compose.yml -p metric-control-center exec -T `
    -e UI_FIXTURE_MODE=cleanup -e "UI_FIXTURE_NONCE=$fixtureNonce" backend python -
```

JSON reporter: `frontend/test-results/browser-acceptance.json`. Он перезаписывается
следующим прогоном; при целевом повторе сначала сохранить предыдущий JSON в `.tools`.
Console/request audits прикрепляются внутри JSON. Trace/video отключены, screenshots
только при ошибке. Артефакты содержат реальные account names и остаются локальными.
`--list` проверяет discovery, но не является browser PASS.

Отдельная PostgreSQL concurrency проверка: `scripts/check_economics_postgres.py`.
Она предназначена только для восстановленной тестовой БД с префиксом
`mcc_economics_`, собственным случайным workspace и отключёнными advertising actions.
Проверяет один успех / один 409 для CAS и пересекающихся когорт. Live DB запрещена
guard; для запуска использовать изолированное окружение, а не production credentials.

Итоговая приёмка и backup checksum находятся в [REPORT.md](REPORT.md).

## Verified acceptance

2026-10-09: 12 уникальных сценариев PASS по последним результатам целевых прогонов; console errors = 0, advertising mutations = 0. Экономика: profiles, cohorts, columns/responsive/persistence и permissions — 4/4 PASS. Подробности и данные сверки в REPORT.md.
