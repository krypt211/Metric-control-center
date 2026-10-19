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

Latest acceptance: [WRITE credential and Meta pacing review](docs/integrations/WRITE_KEY_ACCEPTANCE_AND_META_PACING_REPORT.md). Historical key acceptance is preserved there. The newer [OpenAPI adapter audit](docs/integrations/METRICFLOW_WRITE_ADAPTER_ACCEPTANCE.md) confirms entities:write as the documented action scope; object permissions and LIVE execution remain blocked.

Meta READ hardening: [durable TTL, deduplication, cancellation and recovery](docs/integrations/META_JOB_LIFECYCLE_REPORT.md). Meta LIVE remains disabled.

Meta controlled READ pilot preparation and the separate LIVE approval procedure: [pilot report](docs/integrations/META_CONTROLLED_READ_PILOT_REPORT.md).

## Core workflow audit

[Full audit](docs/audit/PROJECT_FULL_AUDIT.md), [simplification](docs/audit/PROJECT_SIMPLIFICATION_REPORT.md), [Meta cleanup](docs/audit/META_DATABASE_CLEANUP.md), [Rule Engine acceptance](docs/audit/RULE_ENGINE_END_TO_END.md), and [remaining roadmap](docs/roadmap/FINAL_MCC_ROADMAP.md). Direct Meta is disconnected; the optional physical-request limiter is global at 1800 seconds. LIVE advertising WRITE remains blocked.

Smart Rules core: [local acceptance](docs/audit/SMART_RULES_FINAL_ACCEPTANCE.md). PAUSE/ENABLE preparation, MCC notifications, profile timezone, conflict/cooldown guards and the PostgreSQL-only DRY RUN scheduler are locally tested. LIVE WRITE remains blocked.

WRITE preparation: [encrypted handoff and durable mock rehearsal](docs/integrations/CONTROLLED_WRITE_REHEARSAL_REPORT.md). Single-attempt claims, job correlation and crash recovery use the existing ActionEngine in isolated fixtures. LIVE dispatch, provider readback and per-object authorization remain blocked.

Bounded action-job observation: [mock and isolated PostgreSQL acceptance](docs/integrations/METRICFLOW_JOB_OBSERVER_ACCEPTANCE.md).
Durable GET budgets, spacing, deadline and UNKNOWN recovery are implemented only
for isolated MOCK_ONLY rehearsals. Production authorization, dispatch and
verified readback remain blocked; working containers have not been updated.

READ readback diagnostics: [acceptance and LIVE boundaries](docs/integrations/METRICFLOW_READBACK_ACCEPTANCE.md).
The isolated mock path now covers POST -> correlated job -> bounded account-filtered
READ, including process races and crash recovery. Reported status matches remain
non-authoritative; production WRITE and automatic re-enabling stay blocked.
Manual pilot review without provider correspondence: [read-only UI acceptance](docs/integrations/METRICFLOW_MANUAL_PILOT_REVIEW.md).
The selected-AD screen now provides a local review card with exact identity,
status freshness and credential revisions. It sends no provider requests and
cannot authorize execution. LIVE WRITE remains blocked pending required evidence.

Multilevel manual status preparation: [campaign / adset / ad local acceptance](docs/integrations/MULTILEVEL_STATUS_LOCAL_ACCEPTANCE.md).
All six PAUSE/ENABLE intentions support local preparation and simulation; backend/frontend
are deployed for manual LOCAL acceptance. LIVE dispatch and authoritative parent readback
remain blocked. No advertising WRITE was sent.

Manual parent freshness: [targeted READ-sync recovery and next local test](docs/integrations/MANUAL_PARENT_FRESHNESS_FIX.md).
A valid STATUS_STALE-blocked parent draft can refresh its referenced catalog through
the existing bounded READ sync. Freshness checks and LIVE gates remain unchanged.

Controlled WRITE safety: [POST deadline, late ACK acceptance and current LIVE blockers](docs/integrations/METRICFLOW_CONTROLLED_WRITE_READINESS_2026-10-19.md).
The existing mock-only executor holds timeout/late acknowledgements in UNKNOWN without
resend. Production dispatch remains blocked pending ID, asset rights and readback evidence.
