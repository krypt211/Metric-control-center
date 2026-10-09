# MULTI-PROVIDER LOCAL ACTIVATION REPORT

Дата завершения: 2026-10-09, Europe/Moscow. Проект: `E:/Creative_Factory/metric-control-center`.
**MULTI-PROVIDER LOCAL ACTIVATION: READY**. Активация и финальная браузерная приёмка выполнены. Meta LIVE остаётся BLOCKED без настоящих credentials.

## Backup

До миграции остановлены backend/frontend/worker/scheduler. PostgreSQL и Redis сохранены. Исходная Alembic revision: `0008_column_preferences`.

Backup: `backups/activation-20261008T194058Z.dump`, 1 734 409 байт.
SHA256: `45fde8890a0558873283da7931249eea58dd79f2d115f7a5ff764b2d26165da2`.

Checksum PASS. Восстановление в отдельную БД `mcc_activation_restore_20261008_194058` совпало по всем 42 таблицам: строки и SHA256. Рабочая БД не заменялась. Тестовая БД сохранена; впоследствии в ней отдельно проверено обновление до 0009. Существующие backups не удалялись.

Копии прежних Compose и идентификаторы предыдущих образов: `.tools/activation-20261008T194058Z/`. Основные сведения: `.tools/activation-state.json`.

## Encryption Key

`.secrets/provider_encryption_key` создан подготовленным `scripts/setup_provider_key.py`; криптографическая генерация, существующий корректный ключ не перезаписывается. Значение не выводилось. Runtime backend смог прочитать ключ и создать cipher; ADMIN ввод credentials доступен.

Ключ исключён Git ignore, не входит в SQL dump и frontend. Проверено отсутствие байтов реального ключа и MetricFlow READ key в 232 локальных frontend build-файлах. Ключ хранится отдельно от PostgreSQL.

## Windows ACL

PASS. Inheritance отключён. Доступ только у текущего Windows-пользователя, SYSTEM, Administrators. Изменялись права нового файла, существующие секреты не затронуты. Docker mount read-only только для backend и ingestion worker; frontend/scheduler/migrate/backup не получают ключ.

Добавлен `scripts/provider_key_check.ps1`. `start.bat`, `backup.bat` и maintenance restore-test проверяют наличие, формат и ACL без печати значения. Перед recovery восстановите **исходный** ключ отдельно; новый случайный ключ не расшифрует прежние credentials. См. `BACKUP_RESTORE.md`.

## Database Migration 0009

PASS. Рабочая БД обновлена с 0008 до Alembic head `0009_providers`. Добавлены восемь таблиц: connections, credentials, account mappings, routing settings, windows, catalog, switch events, jobs.

Сразу после миграции SHA256 и количество строк всех 41 существовавшей таблицы (кроме служебного изменения Alembic revision) совпали. Сохранены пользователи, сессии, column presets, table preferences, accounts, metrics, tracker observations, sync/action history.

Отдельно настоящий PostgreSQL integration testcase прошёл на изолированной восстановленной БД. Проверены все 49 application tables и их columns. Нет downgrade, удаления рабочей БД или сброса volumes.

## Docker

Подготовленные Compose сравнивались семантически, интегрированы только разрешённые env/secrets backend и worker. Volumes, networks, ports, service commands и health checks сохранены. Изменён и production Compose-файл проекта; production-развёртывание не выполнялось.

Пересобраны backend/frontend/migrate/worker/scheduler. Запущены один ingestion worker и один scheduler. Backend readiness подтверждает database/schema/migrations/Redis OK; frontend отвечает. PostgreSQL и Redis сохранили прежние container IDs и volumes.

При заключительной проверке 9 октября Docker Desktop был остановлен. Он запущен в фоне; существующие контейнеры автоматически восстановились. Повторно подтверждены readiness, frontend HTTP 200 и worker/scheduler heartbeats; PostgreSQL/Redis сохранили прежние IDs. Финальный снимок: `.tools/activation-docker-final.json` и `.tools/activation-runtime-final.json`.

Rollback не потребовался. Копии конфигураций и прежние image IDs сохранены. Проблемы пользовательских данных не маскировались восстановлением или destructive downgrade.

## MetricFlow Live Read

PASS через **новый ProviderManager**. Health выполнил GET me/usage/accounts; малый sync импортировал 20 строк за 2026-10-08, два GET. Всего инструментировано пять GET, WRITE = 0. Существующий READ key используется server-side.

Проверенный LIVE snapshot от 8 октября (цифры не выдаются за текущий Today 9 октября): каталог — три прежних аккаунта. Today: 14 Campaigns, 17 AdSets, 20 Ads. Проверены уникальные IDs и работа всех четырёх уровней.

| Период | Аккаунты с фактами | Campaigns | AdSets | Ads |
| --- | ---: | ---: | ---: | ---: |
| Today | 3 | 14 | 17 | 20 |
| Yesterday | 2 | 14 | 24 | 27 |
| 7d | 3 | 36 | 73 | 81 |
| 30d | 3 | 48 | 105 | 120 |

Yesterday показывает два аккаунта с фактами этого дня; каталог по-прежнему содержит три. Пустые факты не подменяются вымышленными нулями. Таблицы используют реальные сохранённые данные; дубликатов IDs нет. Dashboard и server-side sorting/pagination PASS. Financial formulas и MetricFlow API contract не изменены.

## Meta Connector

Meta **Не подключён / Disabled**. Настоящий Meta token не вводился, фиктивные credentials в рабочую БД не записывались. Provider credentials rows = 0. MetricFlow не зависит от Meta token.

GET-only Meta connector проверен изолированными MockTransport/SQLite fixtures: pagination, limits/retries, scopes, expiry, accounts/hierarchy, attribution, independent sync, current state и secret protection. **Meta LIVE BLOCKED / UNVERIFIED**. Graph version default v26.0. OAuth redirect/refresh не настроены. Нормализация Meta budget/bid currency units остаётся unverified; исходные значения отмечаются в diagnostics, WRITE не разрешается.

## Connections UI

http://127.0.0.1:3000/settings/connections

Проверены ADMIN login, карточки MetricFlow/Meta, READ/WRITE, quota/last sync, masked empty inputs, queued connection health, diagnostics и сохранение настроек. Viewer не получает ссылку; настоящий ADMIN API возвращает viewer 403. Токены через GET не возвращаются.

Сохранение workspace routing, account override, reload и удаление override проверены в браузере. Workspace остался MetricFlow primary / fallback disabled / action disabled. Секреты в live форму не вводились. Очистка полей после сохранения credentials реализована; реальное подключение Meta и сохранение его токена будут проверены при вводе владельцем своих данных.

Кириллица интерфейса проверена, placeholder `????`/replacement characters в новых исходниках отсутствуют. Исправлена повреждённая строка Windows provisioning в прежнем `REPORT.md`.

## Provider Routing

PRIMARY = MetricFlow. META = Disabled. FALLBACK = Disabled. ACTION PROVIDER = Disabled. Account overrides после тестов удалены; исходные пользовательские настройки сохранены.

Усилена проверка выбора primary: нужны enabled healthy connection и успешное complete sync window **текущей credential revision**. Для account override проверяется окно соответствующего canonical account. После замены credentials старая синхронизация не даёт права выбрать источник; сначала требуется новая. API и UI сообщают необходимость синхронизации.

Автоматический Meta ↔ MetricFlow fallback не включён: MetricFlow attribution contract не подтверждён. При несовместимости/неполноте/устаревании данных показывается STALE. Нет смешивания валют, аккаунтов и двух копий spend.

## Sync / Scheduler

PASS. Существующие `sync.insights` today/yesterday/last7 переключены на wrapper нового ProviderManager. Второй независимый периодический MetricFlow scheduler не добавлен. Новые provider health/manual jobs используют ту же очередь; полный sync использует общий lease `default:metricflow:insights` и общую PostgreSQL quota.

LIVE overlap probe вернул `skipped_overlap` до HTTP, без расходования quota. Meta имеет отдельный lease/quota и остаётся отключённой. Рабочие heartbeats worker/scheduler подтверждены; queues actions/ai пусты. Локальный MetricFlow лимит **800 GET/day** сохранён; при первой LIVE проверке использовано 532. Дальнейшие штатные READ/health jobs также учитываются в том же лимите.

Schedules actions/rules/ai исключены в LOCAL READ ONLY. Наличие реализаций в репозитории не означает активного управления.

## Browser E2E

**Playwright PASS: 7/7**, 33.6 s, Windows Chromium, существующий Playwright config. Skip = 0, flaky = 0. Browser console errors = 0; page errors = 0; advertising mutations = 0. Все семь audit attachments проверены.

| Проверка | Результат |
| --- | --- |
| Drag-and-drop | PASS |
| Resize мышью / double click | PASS |
| Добавление / скрытие метрик | PASS |
| Presets | PASS |
| Persistence: width/order/sort, reload/logout/login | PASS |
| Responsive / sticky / horizontal scroll / русский текст | PASS |
| ADMIN / viewer / routing settings | PASS |

Evidence: `frontend/test-results/browser-acceptance.json`, `.tools/activation-browser-accepted.log`, `.tools/activation-browser-final.json`. **UI-1 BROWSER ACCEPTANCE: PASS**.

Ранее в этой активации отдельно выполнены шесть UI-1 сценариев PASS и исправленный providers smoke PASS. Первый provider smoke имел ошибочный locator nested label; заменён на accessible combobox locator. Последующий общий повтор попал в штатный login rate limit после серии проверок. Rate limits не менялись и не очищались; дождались естественного expiry.

Проверены drag/drop, pointer resize и double click, add/hide metrics, presets CRUD/default/switch, logout/login/reload, six scopes, long Russian names, horizontal scroll/sticky name, responsive 1440/768/390, ADMIN/viewer и routing persistence. Отдельный HTTP тест подтвердил сохранность сессий и всех шести scopes после перезапуска **только backend/frontend**; PostgreSQL/Redis ради этого не перезапускались.

## Backend Tests

Полный прогон после активации: 265 tests, 264 PASS, 1 SKIP (отдельная PostgreSQL DSN отсутствует в Windows suite). Сам пропущенный PostgreSQL testcase отдельно выполнен на реальной изолированной БД: **1 PASS**. Таким образом все 265 testcase получили успешное выполнение в соответствующих окружениях.

После усиления primary routing targeted provider/API/jobs: 34 PASS. Финальный полный прогон этой версии: **265 tests за 186.246 s, OK (skipped=1)**; PostgreSQL testcase — отдельный PASS. Evidence: `.tools/activation-backend-final.log`, `.tools/activation-postgresql-test.log`.

## Frontend Tests

13 unit/SSR PASS, TypeScript PASS. Финальный Docker frontend build после усиления primary guard PASS; финальная TypeScript проверка PASS. App/auth/CSRF security checks не отключались.

## Data Integrity

До/после миграции все существовавшие данные совпали. После READ-синхронизации и очистки временных E2E пользователей сохранены исходный пользователь, один собственный набор колонок и два table views. Users/sessions/preferences/action/rule/AI history совпадают с backup по SHA256.

Итоговая проверка после всех E2E: исходный пользователь, один собственный набор и два views сохранены; 10 таблиц users/sessions/preferences/action/rule/AI совпадают с backup. Изменения daily metrics за 6–8 октября входят в реально выполненные today/yesterday/manual READ windows. Восемь остальных исторических дней совпадают с backup; потери строк нет. Tracker metrics не изменились. Последующие штатные reconciliation могут обновлять другие разрешённые окна — это READ collection, а не изменение рекламы.

Evidence: `.tools/activation-state.json`, `activation-integrity-final.json`, `activation-live-read-utf8.json`, `activation-http-persistence.json`, `activation-scheduler.json`, `activation-docker-state.json`, `activation-docker-final.json`, `activation-runtime-final.json`, `activation-browser-final.json`, `provider-key-acl.json`.

## Safety

`ACTIONS_ENABLED=false`, `LOCAL_READ_ONLY=true`, `AI_ENABLED=false`, `AI_AUTOPILOT_ALLOWED=false`. Rule Engine/Telegram control не активированы. Advertising action records сохранены.

MetricFlow WRITE = 0. Meta WRITE = 0. Advertising entities modified = 0. Записи выполнялись только в локальную конфигурацию/audit/user preferences/sync jobs/statistics storage. Creative Factory не изменялся. Secret scan PASS.

## Files Changed

Активация: `docker-compose.yml`, `docker-compose.production.yml`, `.secrets/provider_encryption_key` (секрет, Git ignored), `scripts/local_activation_evidence.py`, `scripts/provider_key_check.ps1`, `scripts/maintenance.ps1`, `scripts/local.ps1`, `scripts/check_ui_preferences.py`, `frontend/e2e/{accounts.py,provider_accounts.py,providers.spec.mjs}`, `backend/provider_api.py`, `frontend/app/settings/connections/page.tsx`, `tests/test_provider_api.py`, `BACKUP_RESTORE.md`, `docs/multi-provider/{ACTIVATION_PLAN.json,REPORT.md,LOCAL_ACTIVATION_REPORT.md}`. Созданы новый backup/sha256 и локальные evidence logs.

Файлы ранее подготовленной архитектуры перечислены в [implementation report](REPORT.md).

## Remaining Issues

- Meta LIVE невозможно подтвердить без настоящих App/token/asset permissions. Это не блокирует локальную панель MetricFlow.
- OAuth login/refresh не реализован; первоначальное подключение токеном.
- Automatic fallback запрещён до подтверждения совместимой MetricFlow attribution.
- Meta minor budget/bid units и архивная иерархия требуют отдельной LIVE проверки/доработки; WRITE-фаза не выполнялась.
- Изолированная restore test DB оставлена для проверки; её не удаляли.

## HOW TO CONNECT META

1. В Meta for Developers → My Apps создайте/выберите собственное приложение с Marketing API use case. В App Dashboard → Settings → Basic получите App ID и App Secret.
2. Назначьте пользователю/Business system user доступ к нужным ad accounts в своём Business Portfolio. API scope сам по себе не предоставляет права на рекламный актив.
3. В App Dashboard проверьте доступ к **ads_read**. Для внешних пользователей/бизнесов выполните те требования Advanced Access/App Review/Business Verification, которые показывает ваш Dashboard. Для этой READ-фазы ads_management не нужен.
4. В Graph API Explorer выберите именно своё приложение и пользователя с доступом к аккаунтам; получите token с ads_read. Альтернативный system user token требует назначенных активов; его совместимость с текущим `/me/permissions` workflow пока LIVE не проверена.
5. В Access Token Debugger проверьте valid, App ID, ads_read, expiry и data-access expiry. Автоматический OAuth refresh здесь не настроен.
6. Войдите в локальную панель как ADMIN → «API и подключения» → Meta Marketing API → «Подключить или обновить credentials». Введите **App ID, App Secret, Access Token**, оставьте Graph version v26.0 или подтверждённую версию вашего приложения. Нажмите «Подключить / заменить credentials».
7. Дождитесь READ health; затем задайте небольшой период и нажмите «Синхронизировать выбранный период». Сравните spend/conversions/currency/timezone/attribution с Meta Ads Manager в diagnostics.
8. После успешной синхронизации станет доступен выбор Meta основным. До этого MetricFlow продолжает работать. Fallback оставьте отключённым, управление рекламой disabled.
9. Для отзыва token используйте настройки Meta. Локальное «Отключить»/«Удалить credentials» не отзывает его у провайдера.

Реальные ключи вводите только в ADMIN UI; **не отправляйте их в переписку**. [Graph API Explorer](https://developers.facebook.com/tools/explorer/), [Access Token Debugger](https://developers.facebook.com/tools/debug/accesstoken/). Версия/fields сверялись по [официальному SDK Meta](https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/apiconfig.py); фактические права приложения подтверждаются health/LIVE проверкой и вашим App Dashboard.

## FINAL STATUS

**MULTI-PROVIDER LOCAL ACTIVATION: READY**

Локальная панель работает на 0009; MetricFlow — primary READ, Meta — disconnected. URL: http://127.0.0.1:3000/ и http://127.0.0.1:3000/settings/connections. Все проверки завершены; рекламное управление выключено. К следующей фазе не переходили.
