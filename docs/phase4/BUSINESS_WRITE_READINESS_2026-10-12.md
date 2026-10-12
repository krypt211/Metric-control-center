# Phase 4B — Business WRITE preparation — 2026-10-12

## Status

**PHASE 4B: PARTIAL — LIVE WRITE BLOCKED.**
Phase 3.1 READY не перерабатывалась. Реальных рекламных WRITE: **0**.
ACTIONS_ENABLED=false, LOCAL_READ_ONLY=true, AI_ENABLED=false,
AI_AUTOPILOT_ALLOWED=false сохранены. Общая action queue не активировалась.

## Official contract and prior audit

Проверены прежние WRITE_API_AUDIT.md, METRICFLOW_WRITE_AUDIT.md и PHASE4B_PLAN.md.
Context7 не содержит подходящей библиотеки MetricFlow; нерелевантные SDK не использованы.
Первичный источник: [официальная документация](https://metricflowit.click/docs),
раздел Settings / API Keys, проверен 2026-10-12.

Документированы Bearer auth, scope campaigns:write и общие POST маршруты
/api/v1/entities/{entity_id}/pause и /enable. GET /me сообщает scopes/access_state;
GET /usage — тариф и лимиты. Для account READ используется act_ ID.
Общие subscription/rate errors — 402/429. Эти сведения не задают полный WRITE contract.

| Проверяемая часть | PAUSE_AD | ENABLE_AD |
| --- | --- | --- |
| Общий маршрут POST | /api/v1/entities/{entity_id}/pause | /api/v1/entities/{entity_id}/enable |
| Scope | campaigns:write | campaigns:write |
| Точный namespace WRITE entity_id и привязка к AD/account | UNVERIFIED | UNVERIFIED |
| Тело, обязательные поля/headers и bodyless semantics | UNVERIFIED | UNVERIFIED |
| Типизированный success/error response, sync/async execution | UNVERIFIED | UNVERIFIED |
| Asset permissions / acting-as ограничения | UNVERIFIED | UNVERIFIED |
| Idempotency / no-op / timeout / partial-apply semantics | UNVERIFIED | UNVERIFIED |
| Correlated result / authoritative readback / consistency deadline | UNVERIFIED | UNVERIFIED |
| Production typed wire adapter | BLOCKED | BLOCKED |

Числовой external AD ID, отсутствие тела в legacy connector и HTTP 200 не приняты
как контракт. READ mapping effective_status не подтверждает configured AD status
и причинную связь с WRITE. Бюджеты, ставки и дополнительные операции заблокированы.

## Current connection: documented READ probe

Выполнены ровно два рекламно-безопасных GET: /me и /usage.
Использован текущий READ credential через существующий encrypted credential loader;
каждый запрос зарезервирован через ProviderManager.reserve, retries=0.
Credentials, owner identity, email и необработанные ответы не выводились.
Никаких недокументированных probes, WRITE, новых ключей и изменений READ connection.

Результат: plan=business; access_state=active_paid; team role=member.
Key scopes: analytics:read, ad_accounts:read, campaigns:read, rules:read,
bundles:read, pages:read, launches:read, seeding:read, team:read, insights:read.
campaigns:write и wildcard отсутствуют. Это подтверждает READ-only scopes данного ключа,
но не определяет все права пользователя/команды на рекламные активы.
Provider daily_limit=20000; daily_used=122 в ответе /usage.
Локально до probe: 125/800, blocked_until=null. Два probes учтены локально;
автоматическая READ синхронизация также продолжает расходовать квоту.
Локальный cap **800** не повышен. Статус Business не снимает WRITE блокеры.

## Independent WRITE credential storage

Добавлен services/actions/write_credentials.py: отдельный Fernet encrypted envelope.
Binding: workspace, provider=metricflow, purpose=ADVERTISING_WRITE, revision и
verification=UNVERIFIED. Token исключён из repr. Проверяются tampering, чужие
workspace/revision/purpose и попытки overwrite; создание исключительно O_EXCL.
Нет fallback на READ credentials и нет записи в ProviderCredential READ slot.

Новые настройки: METRICFLOW_WRITE_VAULT_FILE и METRICFLOW_WRITE_ENCRYPTION_KEY_FILE.
Docker mounts подготовлены только в отключённом actions profile:
.secrets/metricflow_write_credentials.enc и отдельный .secrets/metricflow_write_encryption_key.
Backend/READ worker этих secrets не получают. Secret values и encryption key
не созданы в рабочем проекте; тесты используют синтетические keys во временных каталогах.
Vault не подключён к LIVE dispatcher и не является permission grant.
Legacy plaintext WRITE path не активирован и не является принятым provisioning flow.

Будущее provisioning: приватный host parent, mode 0700 / файлы 0600 на Linux,
эквивалентный ограниченный Windows ACL; encryption key хранить отдельно от envelope.
Не включать secrets в Git, отчёты, backup артефакты с публичным доступом или UI.
Создание настоящего WRITE key и выдача прав требуют отдельного будущего решения пользователя.

## Action Engine and mock transport

Сохранён fail-closed ActionSafetyGate: даже изменение двух environment flags
не отменяет WRITE_CONTRACT_UNVERIFIED. READ provider router не делает fallback WRITE.
Local prepare/preflight/confirm/simulation/history остаются доступными и безопасными.

Новый production typed HTTP serializer/result decoder не реализован:
подтверждённой спецификации для него нет. Это намеренный BLOCKED по условию этапа,
а не утверждение о готовности legacy connector. Существующий transport и Action Engine
проверяются только httpx.MockTransport: четыре сочетания flags, zero HTTP при gates,
zero execution до принятого contract, unknown outcome, READ reconciliation без resend.
Синтетический contract bypass допустим только в уже существующих изолированных mock tests;
runtime hard gate остаётся. MOCK PASS не означает LIVE VERIFIED.

## Migration incident and deployment fix

Старый metric-control-center-migrate-1: exit 255, ошибка
Can't locate revision identified by '0010_economics'.
Image sha256:6a3bc9a5aeb36f4e199b61cf853798c863c563cbb879fca385c5a65a84e378ac
отличался от рабочего backend image и содержал устаревшую migration history.

Добавлен services.storage.migrate. Один PostgreSQL transaction/advisory lock
сериализует runners; Alembic использует тот же connection через Config.attributes.
Неизвестная revision/несколько heads/неполная stamped schema блокируют запуск.
На актуальном head проверяется schema и возвращается ALREADY_CURRENT **без command.upgrade**.
Downgrade, stamp для исправления working DB, drop/reset и удаления volumes нет.

Оба Compose используют runner. deploy_server.sh/deploy_update.sh явно build migrate,
запускают новый service container с --force-recreate/--no-build/--no-deps и проверяют exit.
Приложение запускается отдельным --no-deps списком без повторного запуска migrate.
Shell scripts сохранены с LF, bash syntax проверен. Production server deployment не выполнялся.

Свежий pg_dump рабочей БД восстановлен в отдельную
mcc_write_rehearsal_20261012_112731. Два повторных и четыре конкурентных запуска
нового migration image: PASS, ALREADY_CURRENT, **62/62 count/hash unchanged**.
Изолированная БД и backup сохранены. Обновление с прежних revisions проверяется backend tests.

После rehearsal только migrate-контейнер рабочей среды пересоздан проверенным image:
ALREADY_CURRENT, exit 0, **62/62 unchanged**, action_execution_delta=0.
Рабочая schema остаётся 0012_manual_actions, worker/scheduler возобновлены.

## Validation

Backend: полный прогон **487 passed, 1 skipped, 77 subtests passed**.
После усиления revision/token binding: **30 passed** в write_preparation/phase4b_audit.
Пропущенный PostgreSQL auth/schema case отдельно выполнен на восстановленной БД: PASS.
Ruff check/format и scoped mypy двух новых компонентов: PASS.

Frontend: **35 unit passed**, TypeScript и production build: PASS.
Playwright: **15 разных сценариев passed** — Manual Control 5, navigation 7, Rule Engine 3.
Объединённый прогон достиг локального API cap 240/мин и получил 429 в Rule Engine;
три Rules scenarios затем прошли отдельно. Cap и assertions не изменены.
Использован существующий opt-in UI_SESSION_FIXTURES для адресных временных users;
feature tests проверяют настоящие server sessions/roles/CSRF/logout, не password form.
Синтетические AD facts в рабочую БД не добавлялись.

Во всех browser windows после точного fixture cleanup: 62/62 таблицы неизменны,
advertising execution delta=0. READ workers временно приостанавливались и возобновлены.
Рабочие volumes не удалены. Migration repair также сохранил 62/62 таблицы.
Обычная READ синхронизация между контрольными окнами продолжает обновлять реальные факты.

Docker Compose config (включая отключённый actions profile), bash syntax: PASS.
Рабочий migrate: exit 0; head 0012; backend/PostgreSQL/Redis healthy;
frontend/worker/scheduler работают, action-worker отсутствует.
GET /health/ready: database/migrations/schema/redis OK.
alembic check: No new upgrade operations detected.
Все четыре safe flags и SYNC_DAILY_BUDGET=800 проверены внутри backend.
Vault envelope/encryption key отсутствуют на рабочем host.
Полный production redeploy не выполнялся; production scripts проверены syntax/config,
migration behavior — на изолированной restored DB и текущем head working DB.
Пользовательские roadmap/Phase 4 report файлы сохранены вне текущего коммита.

Локальные evidence: .tools/phase4b-backend-full.txt,
phase4b-frontend-checks.txt, phase4b-migration-rehearsal.json,
phase4b-migrate-repair.json и navigation-phase4b-business-*-integrity.json.

Security source scan / staged diff check: PASS. Final local quota: 129/800, no block.

## First controlled LIVE test: blockers and user actions

1. Получить от MetricFlow provider-authored versioned specification или OpenAPI:
   точные AD ID semantics и account binding, request/response/error schemas,
   required scopes/asset permissions/acting-as, idempotency, timeout/partial apply,
   result correlation, configured/effective readback и consistency bounds.
   Связаться с провайдером должен пользователь; сообщений от его имени не отправляли.
2. После получения contract реализовать и принять typed adapter на mock transport;
   проверить malformed responses, definitive rejection, unknown outcome и отсутствие retries.
3. Отдельно согласовать provisioning WRITE credential с минимальным campaigns:write,
   ограниченным доступом к выбранному account/AD; READ key не менять и не использовать для WRITE.
   Наличие vault или Business plan не заменяет scopes и permission review.
4. Реализовать dedicated one-action executor, durable one-time permit и атомарное
   consume/attempt с PostgreSQL concurrency tests, exact actor/account/AD/action/revision binding.
   Общую legacy action queue для проверки не включать.
5. Непосредственно перед тестом получить свежие authoritative READ facts и подтверждённый
   configured status/parents, preflight и отсутствие unresolved outcome.
6. Получить отдельное явное разрешение пользователя на **один** WRITE attempt с конкретным AD,
   действием, временным окном и ожидаемым результатом. Любое восстановление исходного статуса —
   отдельное действие с новым разрешением. Timeout не даёт права повторить WRITE.

На данный момент ни PAUSE_AD, ни ENABLE_AD не готовы к LIVE исполнению.
Подготовлены безопасные локальные controls, independent storage и deployment/migration checks.
