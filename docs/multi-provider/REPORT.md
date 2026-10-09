# MULTI-PROVIDER IMPLEMENTATION REPORT

> Архивный отчёт о подготовке кода от 8 октября, до разрешённой локальной активации. Статусы PARTIAL/PENDING и сведения о migration 0008 ниже относятся к тому этапу.
> **Текущее состояние на 9 октября: MULTI-PROVIDER LOCAL ACTIVATION: READY**, migration 0009, browser 7/7 PASS. Meta LIVE остаётся BLOCKED без credentials.
> Актуальные результаты, изменения и инструкция подключения Meta: [LOCAL_ACTIVATION_REPORT.md](LOCAL_ACTIVATION_REPORT.md).

Дата: 2026-10-08. Проект: `E:/Creative_Factory/metric-control-center`.
Статус: **MULTI-PROVIDER READ: PARTIAL**. Код подготовлен; обновление работающей установки требует отдельного операционного подтверждения. Meta LIVE BLOCKED: реального токена нет.

## Existing Architecture

Сохранены FastAPI, PostgreSQL, Celery/Redis, Next.js, MetricFlowConnector и проверенный `/insights` schema contract. Финансовые формулы и UI-1 templates/presets не переписаны. Старый локальный стек продолжает работать на миграции 0008; новая сборка ещё не развёрнута. Creative Factory не изменялся.

## Provider Manager

Добавлены общий READ contract, MetricFlowProvider, MetaMarketingProvider, ProviderManager, DataSourceRouter. Manager разделяет credentials, health, quotas и ревизии подключения. Capabilities различают доступную реализацию, подтверждённые права и запрет WRITE. Ошибки сохраняются символическими кодами.

ActionProviderRouter и WRITE contract подготовлены как отключённые границы: pause/enable/budget/bid всегда возвращают WRITE_DISABLED до HTTP. Это не готовая интеграция маршрутизации WRITE с существующим Action Engine. Перед отдельной WRITE-фазой понадобятся подтверждённые capabilities/permissions, идентификаторы и иерархия, свежий state, проверенные денежные единицы, policy, idempotency и проверка результата. Автоматический WRITE failover запрещён.

## Settings UI

ADMIN-страница `/settings/connections` — «API и подключения»: карточки двух API, permissions, last check/sync, quota, expiry, capabilities, зашифрованная замена credentials, локальное отключение/удаление, проверка и синхронизация через durable READ jobs, primary/fallback, account overrides, matching, diagnostics и история. Парольные поля очищаются после успешного сохранения; GET не возвращает токены. CSRF и ADMIN обязательны.

Рабочий URL сейчас: http://127.0.0.1:3000 — прежняя версия панели. Новая страница появится после согласованной активации.

## Meta Authentication

Первое подключение: собственные Meta App ID, App Secret и токен с `ads_read`. Проверяются debug_token, принадлежность App ID, валидность, expiry/data-access expiry, scopes и `/me/permissions`; затем доступные accounts. Версия Graph явно закреплена в настройках (по умолчанию v26.0). OAuth **NOT CONFIGURED**; нет redirect/login flow и автоматического refresh. Долговечность токена зависит от его типа и Meta. System-user token LIVE также не проверен.

## MetricFlow Authentication

Существующий READ key из server-side `.secrets` остаётся совместимым. ADMIN может заменить его зашифрованным значением в БД. Формат ключа проверяется существующим validator. WRITE key не нужен и не передаётся новым READ провайдерам. Проверка scopes использует существующий контракт MetricFlow.

## Meta READ Connector

Только GET к фиксированному https://graph.facebook.com/{version}/. Реализованы accounts, campaigns, adsets, ads, creatives, insights и current state. Явные fields/time_range/time_increment/level/attribution. Cursor pagination не следует upstream URL с токенами; проверяет origin, endpoint, loops, caps и полную загрузку. Retry ограничен, 429 сохраняет блокировку, quota headers редактируются до числовых метаданных. Неверная pagination не публикует частичные данные.

Расход/показы/клики и явно выбранные `lead`/`purchase` переносятся в общую модель; пересекающиеся action aliases не складываются. Неизвестные показатели остаются NULL. Дробные modeled conversions сохраняются в raw, без округления в integer count. Нормализованные Meta budget/bid пока NULL: исходные minor units доступны в diagnostics с пометкой unverified. Для исторической строки нужна подтверждённая текущим каталогом иерархия; отсутствующие исторические/архивные объекты могут блокировать окно до доработки проверенного READ-восстановления иерархии.

## MetricFlow READ Connector

Новый wrapper использует прежний MetricFlowConnector и schema. Существующая ingest-логика сохраняется; добавлены revision fence и публикация provider window. Дополнительные frequency/breakdowns продолжают использовать существующие проверенные schemas и общую квоту MetricFlow. Публичный API MetricFlow не изменён.

## Account Matching

Сопоставление по подтверждённому числовому Meta account ID (`act_...`), без совпадения названий. Общий canonical ID сохраняет прежние MetricFlow identity/filter IDs, когда совпадают внешние entity IDs и родители. Ручное ADMIN-сопоставление требует явного подтверждения; конфликт Meta IDs/дубли одного провайдера отклоняются. Ручная привязка сама по себе не доказывает совместимость атрибуции.

## Unified Data Model

Существующие accounts/entities/daily metrics/current state/raw snapshots остаются source-aware. Добавлены encrypted credentials, connections, account mappings, routing settings, windows, catalogs, switch events и jobs. Window хранит период, complete, импорт/доступное source timestamp, атрибуцию, hierarchy hash и credential revision. Source timestamp Meta отсутствует, если API его не сообщает: observed/import time не выдаётся за время изменения на стороне Meta.

Таблица выбирает один источник на весь период каждого canonical account. Суммы не складывают две копии одного аккаунта. Overview разделяет валюты, timezone, провайдер и атрибуцию. Метрики трекера не придумываются для Meta. Фильтры, optional statistics и AI snapshot читают выбранный source; AI остаётся отключён.

## Provider Routing

Workspace: primary, optional READ fallback, action=disabled. Account override может заменить общую настройку и удаляться для возврата к наследованию. Смена primary разрешена после health verification. Primary одного аккаунта не меняет другие аккаунты. Diagnostics показывает два источника рядом и разницу spend при одинаковых currency/timezone, без автокоррекции.

## Failover

READ fallback допустим только при доказанном общем account ID, полном свежем окне (30 минут), той же ревизии credentials, валюте, timezone, известной одинаковой атрибуции и совпадающей иерархии. При несовместимости остаётся доступный снимок STALE. Смена источника записывается в audit с причиной/периодом.

Реальная атрибуция MetricFlow сейчас не подтверждена schema: NULL. Поэтому автоматический MetricFlow ↔ Meta fallback **BLOCKED BY COMPATIBILITY**. Тестирование совместимых synthetic windows не означает готовность реального автоматического переключения. Ручной выбор основного источника после проверки доступен.

## Independent Sync

Раздельные quotas, leases, sync runs и HTTP clients. Meta: today каждые 10 минут, yesterday раз в час, reconciliation за 7 дней ежедневно; ручной backfill до 91 дня делится на окна по 3 дня. Durable jobs сохраняются в БД, dispatch не дублирует уже claimed job; истёкший running claim восстанавливается после 30 минут. Credential revision проверяется перед READ и публикацией. Полное account window публикуется атомарно; при сбое снимок сохраняется. Сбой Meta не блокирует MetricFlow job, и наоборот.

Новые задания ещё не запущены в рабочем Docker. Meta первоначально отключена. Частично выполненный READ не даёт права выполнять WRITE.

## Credentials Security

Fernet authenticated encryption; key отдельно от PostgreSQL: `.secrets/provider_encryption_key`, Docker read-only secret mount. В БД encrypted payload привязан к workspace/provider. Ошибочный/отсутствующий key блокирует ввод/расшифровку, без plaintext fallback. Ключ не перегенерируется поверх существующего.

Обычный SQL backup содержит ciphertext, но не key. Ключ нужно отдельно хранить в защищённом backup; потеря ключа делает сохранённые credentials недоступными. Новый реальный ключ пока **не создан**, Windows ACL нового файла пока **не проверен**. HTTP logging скрывает credential-bearing URL/body. Source secret scan PASS, это ограниченная статическая проверка, не полноценный security audit. Локальное отключение не отзывает токен у Meta/MetricFlow; remote revocation выполняется владельцем через настройки провайдера.

## Database Migrations

0009_providers добавляет восемь таблиц, не удаляет старые таблицы/строки. SQLite upgrade, repeatability, сохранение исторических записей и соответствие metadata проверены; PostgreSQL SQL компилируется. Реальная PostgreSQL-миграция 0009 **PENDING**. Изолированный LIVE PostgreSQL migration test пропущен при отсутствии отдельной test DSN.

На этапе подготовки кода before/after SHA-256 и количество строк совпали в 15 защищённых таблицах (`.tools/multi-provider-before.json`, `.tools/multi-provider-source-only-after.json`). После проверки прежний READ worker возобновлён; последующая штатная синхронизация может обновлять статистику. Это не доказательство сохранности после ещё не выполненной 0009.

## Tests

- Финальный backend: 265 tests, 264 PASS, 1 SKIP (PostgreSQL), 171.820 s; `.tools/provider-final-backend.log`.
- Отдельный финальный targeted прогон новых provider/API/jobs: 34 PASS.
- Прогон включает последние исправления pagination, source indicators, audit и durable jobs.
- Frontend unit/SSR: 13 PASS. Frontend build/type checking: PASS.
- Windows provisioning отдельного ключа проверен в изолированной тестовой папке: ACL применяется до записи ключа, повторный запуск сохраняет ключ. Рабочий ключ создан при подтверждённой активации; права существующих секретов не менялись.
- Проверены GET-only, отключённые WRITE, pagination/retry/rate/expiry/scopes, matching, currency/timezone/attribution/hierarchy mismatch, no double counting, stale/fallback, независимость API/jobs, ADMIN/operator/viewer, CSRF, encryption/secret omission, durable restart recovery и SQLite persistence.
- Новый browser smoke подготовлен в `frontend/e2e/providers.spec.mjs`; **NOT RUN** до развёртывания. Старые 6 UI-1 E2E раньше проходили (docs/ui-1/BROWSER_ACCEPTANCE.md); текущая multi-provider сборка в браузере ещё **UNVERIFIED**, прежний PASS не переносится автоматически.
- `ACTIONS_ENABLED=false`, `LOCAL_READ_ONLY=true`; тесты не отправляют рекламные WRITE. AI/Rules/Telegram control не включались.

## Live Meta API Verification

**BLOCKED / UNVERIFIED**: отсутствует реальный Meta access token. Все Meta HTTP проверки выполнены MockTransport; они подтверждают поведение кода, а не доступность реальных аккаунтов/permissions/Graph responses.

## Live MetricFlow Verification

Прежний локальный MetricFlow READ стек сохранён и работает. Новый ProviderManager/wrapper проверен тестами, но его свежая LIVE health/sync проверка **PENDING** активации. Ключи и контракт не менялись. Не заявляем LIVE PASS новой сборки.

## Files Changed

Новые: `services/providers/{__init__,models,credentials,contracts,metricflow,manager,matching,router,sync}.py`, `services/meta/{__init__,client,provider,mapper}.py`, `backend/provider_api.py`, `workers/providers.py`, `migrations/versions/0009_providers.py`, `scripts/setup_provider_key.py`, `tests/test_providers.py`, `tests/test_provider_api.py`, `tests/test_provider_jobs.py`, `frontend/app/settings/connections/page.tsx`, `frontend/components/DataSources.tsx`, `frontend/e2e/{provider_accounts.py,providers.spec.mjs}`, `docs/multi-provider/{REPORT.md,ACTIVATION_PLAN.json,docker-compose.yml.proposed,docker-compose.production.yml.proposed}`.

Изменены: `services/storage/models.py`, `services/sync/engine.py`, `services/analytics/{table,dashboard,optional,recommendations}.py`, `services/ai/snapshot.py`, `workers/ingestion.py`, `backend/app.py`, `tests/test_frequency_worker.py`, `frontend/{app/page.tsx,app/globals.css,components/Statistics.tsx,components/SessionBar.tsx,app/api/admin/[...path]/route.ts,app/api/stats/[kind]/route.ts,e2e/accounts.py}`, `requirements.lock`, `pyproject.toml`.

Рабочие `docker-compose*.yml`, существующие credentials, PostgreSQL и Creative Factory не заменены предложенными файлами.

## Remaining Blockers

1. Отдельное операционное подтверждение: новый encryption key, proposed Compose, backup, migration 0009, сборка/перезапуск локальных READ services и браузерная приёмка. План: [ACTIVATION_PLAN.json](ACTIVATION_PLAN.json).
2. Реальные Meta App/token/asset permissions — LIVE проверка невозможна без них.
3. Подтверждение реального Meta field contract, доступности `/me/permissions` для выбранного типа токена и атрибуции; бюджетные денежные единицы ещё не нормализованы.
4. Подтверждение атрибуции MetricFlow для автоматического fallback; сейчас он запрещён.
5. OAuth redirect/refresh flow и WRITE-фаза не реализованы и не включены.
6. Проверка PostgreSQL миграции, сохранности presets и restart/browser новой сборки после активации.

## HOW TO CONNECT META

Выполняется после активации новой страницы. Секреты вводятся только в локальной ADMIN-форме; не вставляйте их в переписку, исходники или Git.

1. Откройте Meta for Developers → My Apps. Создайте или выберите собственное приложение с Marketing API use case. В App Dashboard → Settings → Basic найдите App ID и App Secret. Конкретные доступные use cases/настройки определяются вашим аккаунтом Meta.
2. Убедитесь, что пользователь (или business system user) имеет доступ к нужному Business Portfolio и назначенным ad accounts. Одного разрешения API без прав на рекламный актив недостаточно.
3. В App Dashboard проверьте доступ к `ads_read`. Для собственных назначенных тестовых активов используйте доступный режим разработки/App Roles. Для подключения внешних пользователей/бизнесов выполняйте требования Advanced Access, App Review и Business Verification, которые показывает ваш App Dashboard; необходимость этих шагов зависит от сценария. `ads_management` для этой READ-фазы не требуется.
4. В [Graph API Explorer](https://developers.facebook.com/tools/explorer/) выберите именно своё приложение, пользователя с правами на аккаунты, запросите `ads_read` и получите user token. Альтернативно создайте system user token в Business Settings с назначенными рекламными активами и разрешением `ads_read`; этот тип токена ещё требует LIVE проверки нашего `/me/permissions` workflow. Не обещаем универсальной совместимости всех типов токенов.
5. В [Access Token Debugger](https://developers.facebook.com/tools/debug/accesstoken/) проверьте valid, App ID, `ads_read`, expiry и data access expiry. Пользовательские токены имеют ограниченный срок; его продление зависит от Meta, OAuth refresh здесь не настроен. Не отправляйте токен другим людям.
6. В панели войдите как ADMIN → «API и подключения» → Meta Marketing API → «Подключить или обновить credentials». Введите App ID, App Secret, token; Graph version по умолчанию v26.0. Нажмите «Подключить / заменить credentials».
7. Дождитесь READ health job: карточка должна стать «Подключён», с подтверждённым read, accounts и scopes. При expiry/permissions error не выбирайте Meta основной: исправьте доступ и повторите проверку.
8. Выберите небольшой период в diagnostics и нажмите «Синхронизировать выбранный период». Дождитесь завершения всех окон; сравните accounts/валюту/timezone/spend/конверсии и атрибуцию с Meta Ads Manager. Никакие рекламные объекты не меняются.
9. Только после проверки выберите Meta основным источником. Для отзыва токена используйте настройки Meta; кнопка «Отключить» останавливает локальное использование, а «Удалить сохранённые credentials» удаляет только локальный ciphertext.

Первичные источники field contract/version: [официальный SDK Meta apiconfig](https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/apiconfig.py), [AdsInsights](https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/adobjects/adsinsights.py), [AdAccount](https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/adobjects/adaccount.py). v26.0 проверена по SDK в текущем сеансе. Документы developers.facebook.com возвращали 429/были недоступны для чтения: требования App Review и шаги в App Dashboard должны быть подтверждены владельцем приложения, SDK не подтверждает фактические права аккаунта.

## HOW TO SWITCH PROVIDERS

1. ADMIN → «API и подключения». Проверьте подключение и синхронизацию будущего primary за нужный период.
2. «Источники статистики» → «Настройка для: Все аккаунты» → выберите основной источник, резервный или «Отключён» → «Сохранить источники».
3. Для исключения выберите конкретный аккаунт в «Настройка для», задайте primary/fallback и сохраните. «Использовать общие настройки» удаляет только override.
4. Откройте статистику: indicator показывает фактический source, PRIMARY/FALLBACK/STALE и время snapshot. В diagnostics сравнивайте источники рядом; разницу не исправляет автоматически программа.
5. Наличие configured fallback не гарантирует его применение: неизвестная атрибуция/другие currency/timezone/неполное окно/непроверенная иерархия оставят STALE. Для реального MetricFlow ↔ Meta автоматический fallback сейчас заблокирован неизвестной атрибуцией MetricFlow.
6. Перед отключением последнего источника UI требует подтверждения; сохранённые данные остаются. Управление рекламой всегда disabled.

## FINAL STATUS

**MULTI-PROVIDER READ: PARTIAL**

Код и автоматические проверки готовы к согласованному локальному развёртыванию. LIVE Meta BLOCKED; миграция/новая сборка/браузерная приёмка PENDING. Рекламных WRITE-запросов и изменений рекламных объектов: 0. Перехода к WRITE-фазе нет.
