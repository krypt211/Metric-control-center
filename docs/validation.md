# Проверка версии 0.6

6–7 октября 2026 года:

- 145 unittest: connectors, PostgreSQL-compatible persistence на SQLite,
  миграции, pagination, late conversion upsert, quotas/retries/429,
  lease fencing, отдельный current state, валюты/часовые пояса,
  hierarchy/creatives/filters/GEO, idempotency, state drift, permissions,
  неопределённый POST, recovery, API identity и audit.
- Дополнительно: bulk partial failures/savepoints, replay, лимит 200,
  dry-run без action requests, OFF, условия/точные ratios, unknown/stale,
  minimum events/schedule, валюты, cooldown после перезапуска и редактирования,
  конкурентная оценка/редактирование одного правила на SQLite, optimistic revisions,
  повторная проверка условий/OFF перед HTTP и аутентифицированный Rule API.
- Детекторы: все условия Winner, явный ноль лидов Loser, пять завершённых
  дней Fatigue, совместность/монотонность четырёх трендов, отсутствие
  frequency, missing/stale/zero/low-volume данные, смена источника трекера,
  shared creatives без суммирования reach, parent frequency без двойного
  расхода, weighted totals, freshness открытых/закрытых дней, settings revisions,
  read-only рекомендации без ActionRequest и optional reach/frequency sync.
- Parent-frequency worker: disabled/missing/invalid schema не создают
  connector; valid schema использует READ и общую квоту; extra parent sync
  даёт Fatigue нескольким ad без двойного расхода. Проверено на mock HTTP.
- Alembic upgrade исполнялся повторно на временной SQLite. Схема и
  колонки совпали с ORM. PostgreSQL SQL compiled offline: JSONB,
  NUMERIC(24,8), partial unique index pending action.
- Upgrade 0001 → 0002 сохраняет существующую action request и добавляет
  default provenance. Upgrade 0002 → 0003 сохраняет daily history,
  reach/frequency остаются NULL до загрузки. Upgrade 0003 → 0004 сохраняет
  существующие ai_decisions и связанные ai_actions. PostgreSQL DDL пяти миграций
  компилируется offline.
- Next.js production build, включая TypeScript, прошёл.
- HTTP preview: /, /api/dashboard, /api/stats/filters, /api/stats/table,
  /api/capabilities вернули 200. Dashboard вернул empty, без подставных цифр.
- Обновлённый preview: вкладки «Правила»/«Журнал» доступны в HTML,
  /api/automation/rules и /api/automation/audit вернули 200 с локальным
  preview operator. Celery task rules.evaluate зарегистрирована в worker.
- Вкладка «Рекомендации» есть в HTML; /api/recommendations вернул 200,
  все counts=0/rows=[] на пустой БД. Operator доступен, actions_enabled=false.
- AI: Python snapshots/trends, Copilot без commands, typed output, отказ +70%,
  budget ceiling, daily units, idempotent/concurrent approvals, expiry, drift,
  policy/mode changes, отсутствие durable approval, роли/workspace, дневные quotas.
  OpenAI Responses shape проверен через MockTransport, без внешних запросов.
- Telegram: sender/chat/message binding, callback replay, отсутствие повторной
  отправки при uncertain delivery, продолжение inbox после callback ack failure.
  AI/Telegram credentials проверены на изоляцию в Compose.
- AI API: authentication, revision conflicts, deployment Autopilot gate,
  disabled inference, idempotent analysis и запрет client actor/source.
- Обновлённый HTTP preview: AI Copilot есть в HTML, /api/ai/settings и
  /api/ai/decisions вернули 200. Mode OFF, ai_enabled/autopilot_allowed/
  actions_enabled=false, model=null и decisions=[]; внешних вызовов нет.
- Agent: 25 новых тестов проверяют уровни 0–3 и legacy COPILOT, READ_ONLY без
  proposals, GEO-условия из breakdowns, явный sales=0 и точный spend>30,
  отсутствие вывода страны из labels, запрет bid и enable по умолчанию,
  отказ при >30 совпадениях без частичного плана, chat idempotency,
  ручной CONFIRM даже в Autopilot и drift country facts перед HTTP.
- Emergency Stop: отмена AI/rule queued заявок при сохранении ручных,
  generation fence после resume, устаревшее возобновление, stop между claim
  и HTTP, конкурентные stop/queue на SQLite, Telegram /stop_auto без LLM.
- Профили: optimistic revision, Python GEO/CPL/ROI, потолок 250, шаг 15%,
  persistent scaling cooldown 8 часов, явный ноль leads и unknown metrics.
  Function calling: required/additionalProperties, строгий Responses shape,
  stateless call_id/encrypted reasoning replay, HTTP 429 без повторов.
- Agent API и Telegram chat: auth, workspace, revision conflict, запрет
  client actor, disabled inference, durable inbox и повторная доставка.
- Preview мигрирован до 0005_agent: 37 application tables; /api/ai/profiles,
  /api/ai/messages, /api/ai/automation/events вернули 200. Профили/чат пусты,
  AI и рекламные действия выключены. Production build с TypeScript прошёл.
- Зависимости проходят pip check; ключи/.env/tools исключены из Git,
  .secrets исключён из Docker build. Сборочные зависимости зафиксированы
  в requirements.lock и frontend/package-lock.json.

Не проверено: реальные MetricFlow JSON/права/полнота/команды, live OpenAI/Telegram, PostgreSQL
server/Redis/Celery в контейнерах, Docker build/up и визуальное отображение
в браузере. В этой среде Docker отсутствует, CUA не предоставляет браузеры.
Миграционные/SQLite тесты не доказывают поведение конкурентных транзакций
на реальном PostgreSQL; это обязательная проверка перед рабочим запуском.


## LOCAL READ ONLY — 7 октября 2026

- Полный unittest run: **165 tests, OK** (70.489 s).
- Windows PowerShell: синтаксис launcher проверен; три теста выполняют реальные setup-функции в изолированных временных папках. Проверены скрытый ввод, отказ неправильному ключу, сохранение существующих credentials и принудительные read-only flags.
- Production Next.js build и TypeScript: PASS.
- HTTP-проверка существующей SQLite preview-БД: backend /health/live, /health/ready, /api/system/status — 200; frontend /, /api/dashboard, /api/stats/filters и table для account/campaign/adset/ad/creative — 200.
- Read-only guard: POST /api/actions вернул 403. Реальный MetricFlow WRITE не вызывался.
- LOCAL_READ_ONLY расписание содержит только today/yesterday/last7/breakdowns/frequency; task rules.evaluate возвращает disabled_read_only.
- Проверочные frontend/backend процессы остановлены; порты 3000/8000 освобождены.
- .env: LOCAL_READ_ONLY=true, SYNC_ENABLED=true, ACTIONS_ENABLED=false, AI_ENABLED=false, AI_AUTOPILOT_ALLOWED=false, TELEGRAM_ENABLED=false.
- Docker Desktop/CLI не найдены. start.bat/launcher показывает понятную ошибку и exit code 1, а не успешный запуск.
- **Полный Docker/PostgreSQL/Redis/worker/scheduler runtime: BLOCKED / NOT VERIFIED.** Контейнеры и production migrations не запускались.
- **METRICFLOW LIVE: WAITING FOR READ KEY.** Файл READ key пустой. HTTP-импорт проверен только с MockTransport и временной БД, не с реальным сервисом.
- Автоматическое определение схемы допускается только для однозначных полей и подтверждаемой пагинации. Неизвестный формат не подменяется синтетическим example; команда прекращается без публикации частичных метрик.
