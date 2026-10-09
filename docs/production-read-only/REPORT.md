# PRODUCTION READ-ONLY REPORT

08.10.2026, 10:13 MSK. Проект: E:\Creative_Factory\metric-control-center. Реализована серверная READ-only конфигурация и проверены authentication, HTTPS в изолированном stack и настоящее восстановление БД. Доступ к публичному VPS/домену не предоставлен.

## Authentication

Login/logout работают через /login и /api/auth/*. Пароли — Argon2id (64 MiB, 3 iterations); default password отсутствует. Bootstrap запрашивает login и скрытый пароль дважды. Общий operator token удалён из frontend trust model.

## Authorization

FastAPI самостоятельно проверяет session, роль и WORKSPACE_ID. Незалогиненный приватный API — 401, недостаточная роль — 403. VIEWER/OPERATOR читают статистику; ADMIN управляет пользователями через admin API и видит operational status/settings. Подмена Authorization/X-User-ID не создаёт identity. Рекламные mutations запрещены даже ADMIN.

## Sessions

PostgreSQL user_sessions: HMAC token hash, CSRF hash, expiry и связь с users. Session cookie — HttpOnly, SameSite=Strict; production — Secure, __Host-mcc_session, Path=/, без Domain. Срок по умолчанию 8 часов. Logout, password reset, изменение роли и деактивация отзывают sessions. Session после restart backend/frontend проверена: PASS.

## Security

CSRF token и точный Origin обязательны для login и других state-changing запросов. Redis: 10 login attempts/15 минут по IP и login; 240 API requests/минуту по IP. Ошибка rate-limit storage закрывает доступ с 503. CSP использует nonce для Next.js scripts; nosniff, frame protection, Referrer-Policy и Permissions-Policy настроены. Secret scan PASS; secrets в Git/frontend не включены. WRITE secret не монтируется. В production startup отклоняет отключённый auth и включённое рекламное управление.

## Docker

Отдельный docker-compose.production.yml: frontend, backend, PostgreSQL, Redis, ingestion worker, scheduler, Caddy, daily backup-job; migrate и maintenance backup. Только Caddy публикует 80/443. Backend/PostgreSQL/Redis не имеют host ports. Action/Rules/AI/Telegram control services отсутствуют в production stack.

Compose validation, сборка backend/frontend/backup и изолированный production stack: PASS. Рабочий локальный READ stack оставлен запущенным; тестовый HTTPS stack остановлен без удаления volumes.

## Reverse Proxy

Caddy → Next.js → FastAPI внутри Docker networks. Входящие actor/workspace/Authorization headers не используются как identity; X-Real-IP заменяется доверенным адресом Caddy. Access logs с cookies не включены. Persistent Caddy data/config сохраняют сертификаты.

## HTTPS

Изолированный Caddy с собственной доверенной тестовой CA: TLS, HTTP redirect, Secure/HttpOnly/Strict cookie, CSRF, login/logout и security headers — PASS. Проверка выполнялась с доверенным CA, без отключения TLS verification.

Публичный ACME certificate на реальном домене: NOT VERIFIED. Caddy automatic HTTPS настроен; HSTS пока max-age=0. Включение после проверки описано в SERVER_DEPLOYMENT.md. [Caddy Automatic HTTPS](https://caddyserver.com/docs/automatic-https).

## Domain Configuration

APP_DOMAIN и ACME_EMAIL задаются в .env.production. Описаны DNS A/AAAA, входящие TCP 80/443, certificate issuance и проверка HTTPS. Реальный домен/VPS в текущей сессии не указан.

## Database

Migration 0007_auth расширяет существующую users и добавляет user_sessions. Upgrade на PostgreSQL 16, schema consistency и alembic check: PASS. Текущая БД сохранена; 371 daily metric, 1040 READ observations, 273 рекламные entities. Duplicate groups, orphan references и null external IDs: 0.

## Redis

Работает во внутренней сети: broker, API/login rate limits, expiring worker/scheduler heartbeat. AOF и persistent volume включены. Readiness Redis: PASS. Пользовательские sessions хранятся в PostgreSQL.

## MetricFlow READ

Живой core sync продолжает работать: последнее подтверждённое SUCCESS — 08.10.2026 10:10:01 MSK, today, 35 rows, 2 requests. Квота на 10:13 MSK: 405/800; это снимок, scheduler продолжает расходовать READ quota.

Core /insights schema/cursor pagination и существующая аналитика сохранены. Контракты tracker money, breakdowns и creative identity не пересматривались. Изолированный HTTPS stack не делал provider requests.

## Scheduler

Ingestion worker и scheduler запущены, heartbeat/worker ping: PASS. Core schedule: today каждые 10 минут, yesterday ежечасно :03, last7 ежедневно 04:07. READ quota 800 сохранена. Контрольные action/AI/rules/Telegram workers не запущены.

## Backups

Custom pg_dump, UTC timestamp + suffix, SHA256, atomic file publication, retention 14 дней, безопасные logs/exit codes. Windows backup.bat и серверный backup-job подготовлены. Последний дополнительный backup текущего образа успешно создан 08.10.2026 10:13 MSK.

## Restore Test

Реально выполнен pg_restore в отдельную тестовую PostgreSQL БД. SHA256, nine critical table counts/digests и migration revision совпали: PASS. На момент копии: 364 daily metrics, 3 accounts, 273 entities, 1040 READ observations, 136 sync runs; users/sessions/actions — 0. После теста отдельная БД удалена, ingestion снова запущен.

[Restore evidence](restore-test.json). Процедура и подтверждение destructive restore — ../../BACKUP_RESTORE.md. Более позднее увеличение daily metrics до 371 связано с продолжившейся синхронизацией.

## Logging

Backend request JSON содержит timestamp, service, level, request_id, status, method, elapsed_ms и safe error_code. Worker/scheduler output фильтруется до безопасных событий без task payload/traceback; backup пишет фиксированные error codes. Passwords, API keys и session tokens не логируются. Инфраструктурные PostgreSQL/Redis/Caddy logs остаются в нативном формате.

## Monitoring

/admin показывает последнюю успешную/неуспешную синхронизацию, следующее запланированное время, quota, expiring heartbeat и readiness PostgreSQL/schema/Redis. Настройки timezone/session TTL отображаются; deployment settings меняются через .env.production. Health live/ready доступны только внутри production stack. check_server.sh проверяет готовность, trusted HTTPS, redirect и heartbeat, возвращает ненулевой code при сбое.

## CI

GitHub Actions workflow: locked backend dependencies, весь unittest suite, PostgreSQL migration consistency, alembic check, basic secret scan, frontend TypeScript/build. Автоматического production deploy нет. Workflow подготовлен; remote GitHub run не выполнялся, repository connection не предоставлен.

## Tests

- Полный suite: 211 tests, 210 PASS и 1 host skip из-за отсутствия TEST_POSTGRES_URL.
- Этот PostgreSQL migration test отдельно выполнен с настоящим PostgreSQL 16: PASS. Alembic check: PASS.
- Final auth subset: 15 PASS; тот же PG test пропущен на хосте и подтверждён отдельно.
- HTTP authentication E2E: PASS — login failure/success, все роли, independent backend denial, CSRF, sessions после restart, logout/replayed cookie denial.
- HTTP statistics: Today/Yesterday/7d/30d × Account/Campaign/AdSet/Ad, Tracker, Creatives: PASS.
- Production TLS/cookie/header E2E, actual backup/restore, builds, Compose validation, Bash syntax, secret scan, local readiness/worker ping: PASS.

VISUAL CHECK NOT VERIFIED: computer-use не обнаружил доступных browsers/apps. HTTP E2E не заменяет визуальное подтверждение.

[HTTP evidence](auth-smoke.json), [TLS evidence](https-smoke.json), [final DB snapshot](db-final.json), [validation](validation.json).

## Files Changed

- Auth/backend: services/auth/{sessions,bootstrap}.py, services/storage/models.py, migrations/versions/0007_auth.py, backend/{auth,app,action_api,logging_config,operations}.py.
- Frontend: proxy.ts, lib/{proxy,operator}.ts, app/login/page.tsx, app/admin/page.tsx, components/SessionBar.tsx, app/layout.tsx, app/page.tsx, app/globals.css, dashboard/stats/recommendations/action proxies и новые auth/admin proxies; frontend/README.md.
- Runtime/deploy: workers/runtime.py, docker-compose.yml, docker-compose.production.yml, docker/Caddyfile, docker/backup.Dockerfile, .env.production.example, .gitignore, .dockerignore, .gitattributes, pyproject.toml, requirements.lock.
- Scripts: local.ps1, maintenance.ps1, database_backup.py, prepare_secrets.py, deploy_server.sh, check_server.sh, deploy_update.sh, rollback_images.sh, security_scan.py; create_admin.bat, backup.bat.
- Verification/docs: tests/test_auth.py, .github/workflows/ci.yml, README.md, RUN_LOCAL.md, SERVER_DEPLOYMENT.md, BACKUP_RESTORE.md, docs/production-read-only/*.json и REPORT.md.

## Server Deployment Instructions

Полные команды установки Docker и DNS: [SERVER_DEPLOYMENT.md](../../SERVER_DEPLOYMENT.md), с опорой на [официальный Docker apt repository](https://docs.docker.com/engine/install/ubuntu/). После установки Docker и копирования проекта/проверенной READ-схемы:

1. Перейдите в проект и подготовьте конфигурацию.

```bash
cd /opt/metric-control-center
cp .env.production.example .env.production
nano .env.production
```

2. Укажите реальные APP_DOMAIN/ACME_EMAIL, направьте DNS A на VPS, откройте TCP 80/443. Создайте secrets скрытым вводом.

```bash
python3 scripts/prepare_secrets.py
```

3. Соберите stack, выполните migrations, интерактивно создайте ADMIN и запустите HTTPS.

```bash
bash scripts/deploy_server.sh
```

4. Проверьте readiness, HTTPS и сервисы.

```bash
bash scripts/check_server.sh
docker compose --env-file .env.production -f docker-compose.production.yml ps
```

При переносе локальной истории сначала остановите локальный ingestion и восстановите финальную копию со счётчиком quota на сервере. Не запускайте два независимых scheduler с одним ключом. Инструкции backup/update/rollback включены в документы.

## First Admin Creation

Локально: create_admin.bat. Сервер после migrations:

```bash
docker compose --env-file .env.production -f docker-compose.production.yml run --rm backend python -m services.auth.bootstrap
```

Пароль выбирает владелец через скрытый interactive prompt; default password нет. Постоянный ADMIN в этой сессии не создавался. Временные случайные E2E users и sessions удалены. Повторный bootstrap при существующем credentialed ADMIN отклоняется.

## Login URL

Локально: http://127.0.0.1:3000/login. Production после deployment: https://YOUR_DOMAIN/login.

## Dashboard URL

Локально: http://127.0.0.1:3000/. Production после deployment: https://YOUR_DOMAIN/. Администратор: /admin.

## Remaining Risks

Публичный VPS/domain/DNS/ACME ещё не проверены. Первый постоянный ADMIN требуется создать владельцу. VISUAL CHECK NOT VERIFIED. Update/rollback прошли синтаксическую проверку, но не исполнялись на реальном release/VPS; DB compatibility нужно проверять перед image rollback. GitHub CI remote run не выполнен. Backup на диске VPS настроен, offsite encrypted copy ещё не выбрана/настроена. Эти ограничения явно документированы, автоматического rollback БД нет.

## Safety

ACTIONS_ENABLED=false  
WRITE key used: NO  
MetricFlow write requests: 0  
Advertising entities modified: 0

Action requests/executions в текущей БД: 0. Реальные provider вызовы на этой фазе только READ; backend mutations рекламы закрыты. Creative Factory не изменялся.

## FINAL RESULT

PRODUCTION READ-ONLY: NOT READY

Конкретные блокеры публичного запуска: не предоставлены выбранный VPS и реальный домен; поэтому не выполнены server deployment, public DNS/ACME/HTTPS verification и bootstrap постоянного владельца. Код и изолированный production stack прошли перечисленные локальные проверки. К ручному управлению рекламой перехода нет.
