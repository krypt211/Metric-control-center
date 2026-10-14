# Metric Control Center

Панель статистики MetricFlow с собственной PostgreSQL БД. Текущий режим — **READ ONLY**: получение данных, аналитика и пользовательский доступ. Рекламные изменения выключены.

## Запуск

Windows: [RUN_LOCAL.md](RUN_LOCAL.md). После setup.bat → start.bat создайте первого администратора через create_admin.bat и войдите на http://127.0.0.1:3000/login.

Сервер Ubuntu + Docker + Caddy: [SERVER_DEPLOYMENT.md](SERVER_DEPLOYMENT.md). Production доступ проходит через HTTPS; backend, PostgreSQL и Redis не публикуются наружу.

## Пользователи и безопасность

Login/logout используют PostgreSQL server sessions, HttpOnly cookie, SameSite=Strict, CSRF и Redis rate limiting. Production cookie также Secure, с префиксом __Host-. Пароли хранятся как Argon2id hash; default password отсутствует.

VIEWER/OPERATOR смотрят статистику. ADMIN дополнительно управляет пользователями и видит /admin с operational status. FastAPI проверяет session/role/workspace самостоятельно. Общий operator token не определяет пользователя; credentials MetricFlow отсутствуют во frontend.

## Статистика

Core READ API и cursor pagination проверены на живом MetricFlow. Today/Yesterday/7d/30d, дерево Account → Campaign → AdSet → Ad, tracker и creative statistics читаются из БД. Quota, leases, атомарная публикация и duplicate protection сохраняются. Unknown money/creative identity не угадываются; ограничения — [READ report](docs/metricflow-full-read/REPORT.md).

Production Compose включает frontend/backend/PostgreSQL/Redis/ingestion worker/scheduler/Caddy/backup-job. ACTIONS_ENABLED=false, квота 800 запросов/сутки. Существующие Action/Rules/AI/Telegram модули сохранены в коде и исключены из production управления.

## Backup и проверки

[Центр рекомендаций](docs/recommendation-center/REPORT.md) доступен после входа
на `/recommendations`: последние результаты DRY RUN, приоритеты проверки,
причины, фильтры и переход к истории правила. План развития —
[roadmap](docs/roadmap.md).

[BACKUP_RESTORE.md](BACKUP_RESTORE.md): custom pg_dump, SHA256, retention, restore в отдельную БД и явный destructive restore. Windows: backup.bat.

[Production READ-only report](docs/production-read-only/REPORT.md): изменения, локальные HTTP/TLS проверки, реальное восстановление и оставшиеся условия запуска на публичном VPS. Публичный домен/сертификат ещё не проверены.

```powershell
.\.venv\Scripts\python -m unittest discover -s tests
.\.venv\Scripts\python scripts/security_scan.py
```

Frontend: Node.js 24, npm ci, npm run build, npm run typecheck. GitHub Actions проверяет backend, PostgreSQL migrations, frontend и basic secret scan; автоматического deploy нет.

## Документы существующей архитектуры

- [Архитектура](docs/architecture.md)
- [Контракт MetricFlow](docs/metricflow-contract.md)
- [Sync и Action Engine](docs/sync-and-actions.md)
- [Bulk actions и правила](docs/automation.md)
- [Детекторы](docs/recommendations.md)
- [AI Copilot](docs/ai-copilot.md)
- [AI Agent](docs/ai-agent.md)

Эти документы описывают также сохранённые будущие возможности управления; текущая production конфигурация остаётся READ ONLY.

Phase 3.1: [Multi-select and searchable rule targets](docs/rules/MULTI_SELECT_AND_SEARCH_REPORT.md).

Phase 4B: [Business WRITE readiness and migration repair](docs/phase4/BUSINESS_WRITE_READINESS_2026-10-12.md). LIVE WRITE remains blocked.

## Integration readiness

[Meta rate-limit audit and independent MetricFlow WRITE settings](docs/integrations/META_RATE_LIMIT_AND_METRICFLOW_WRITE_SETTINGS_REPORT.md).
LIVE advertising writes remain blocked; the private credential service does not dispatch actions.

Latest acceptance: [WRITE credential and Meta pacing review](docs/integrations/WRITE_KEY_ACCEPTANCE_AND_META_PACING_REPORT.md). The configured key reports entities:write, while exact campaigns:write and object permissions remain unconfirmed.

Meta READ hardening: [durable TTL, deduplication, cancellation and recovery](docs/integrations/META_JOB_LIFECYCLE_REPORT.md). Meta LIVE remains disabled.

Meta controlled READ pilot preparation and the separate LIVE approval procedure: [pilot report](docs/integrations/META_CONTROLLED_READ_PILOT_REPORT.md).

## Core workflow audit

[Full audit](docs/audit/PROJECT_FULL_AUDIT.md), [simplification](docs/audit/PROJECT_SIMPLIFICATION_REPORT.md), [Meta cleanup](docs/audit/META_DATABASE_CLEANUP.md), [Rule Engine acceptance](docs/audit/RULE_ENGINE_END_TO_END.md), and [remaining roadmap](docs/roadmap/FINAL_MCC_ROADMAP.md). Direct Meta is disconnected; the optional physical-request limiter is global at 1800 seconds. LIVE advertising WRITE remains blocked.
