# Приёмка ограниченного наблюдателя MetricFlow job

Дата: 18.10.2026, Europe/Moscow. База исходного кода: 3609464.
JOB OBSERVER: READY MOCK. Phase 4B: PARTIAL. LIVE WRITE: BLOCKED.
Наблюдатель не развёрнут в работающие сервисы и не имеет публичного API route.

## Результат

В существующем ActionEngine добавлен observe_rehearsal_job: один вызов делает
не более одного GET /api/v1/jobs/{job_id}. Состояние живёт в существующем
ActionRequest.provenance.controlled.observation; новых таблиц, миграций,
очередей, scheduler entries и worker services нет.

Наблюдение допускается только для ранее подтверждённого single-AD MOCK_ONLY
rehearsal в SQLite fixture или mcc_integrations_* PostgreSQL с workspace
write-rehearsal-*. Обязателен явный httpx.MockTransport. Старый production hard
contract gate не изменён и блокирует и POST, и новый job GET до HTTP.

## Границы и жизненный цикл

- Максимум 6 durably reserved GET slots; физические HTTP attempts не превышают
  число этих slots. При отказе vault/guard слот может быть потрачен без HTTP.
- Интервал между шагами не менее 10 секунд, первый GET не ранее 10 секунд после ACK.
- Deadline не позже min(original permit expiry, consumed_at + 600 секунд).
  У самого GET общий timeout не более 30 секунд и остатка deadline.
- Это локальные консервативные ограничения, не гарантии/лимиты провайдера.
- Claim очередного GET фиксируется транзакцией до vault/HTTP. На этом шаге
  переиспользуются existing manual lock order и shared quota ledger.
- GET-only transport не повторяет запрос внутри себя, не отправляет POST,
  не следует redirects и проверяет typed job_id/entity_id/action_type/counts.
- pending/running сохраняют next_poll_at. Повторный вызов до этого времени,
  конкурентный вызов и restart не сбрасывают attempts или deadline.
- success сохраняется как JOB_SUCCESS_NEEDS_READBACK. Это не VERIFIED, не
  доказательство configured/effective статуса и не основание MCC pause ownership.
- partial/failed/expired, malformed/uncorrelated response, HTTP/transport error,
  исчерпание бюджета или deadline переводят результат в OUTCOME_UNKNOWN.
  Для этих неоднозначных состояний не придумывается факт неприменения команды.
- При crash посреди GET IN_FLIGHT сохраняется; повторного GET для него нет.
  Существующий verify_pending закрывает истёкшее наблюдение в UNKNOWN без HTTP.
- 429 останавливает observer и сохраняет cooldown в существующей api_quotas;
  используется консервативная политика до следующего UTC reset или более
  позднего Retry-After, с локальным верхним ограничением Retry-After 7 дней.
  Это не изменение действующего лимита 800 и не повышение provider quota.

## Binding и секреты

Повторно проверяются actor permission, workspace, request, account, AD,
provider, операция, оригинальный POST claim, job ID, READ credential revision,
routing/иерархия, fresh WRITE scope evidence и digest encrypted credential.
Проверки выполняются до claim и непосредственно перед GET; factory дополнительно
проверяет rotation/deletion после awaited guard.
Изменившийся после команды status/timestamp не считается изменением identity:
иначе успешный PAUSE сам делал бы наблюдение невозможным.
Уже полученный ответ сохраняется даже при отзыве прав во время запроса,
но не подтверждает рекламное изменение.

Используется отдельный purpose-bound encrypted WRITE slot, без READ fallback.
В рабочей среде этот путь по-прежнему недоступен: contract gate не даёт открыть
реальный vault. У тестов synthetic credentials; сырые ответы, provider messages,
error bodies и токены не записываются в provenance или audit. Сохраняются
нормализованные состояния/коды и корреляция.

## Измеренные проверки

| Проверка | Результат |
| --- | --- |
| Финальный observer + wire contract + rehearsal набор | 118 PASS, 78.95 секунды |
| В том числе расширенные тесты observer | 35 observer cases in the final combined run секунды |
| Actions/API/manual-control/Phase4B/foundation/connector/sync regressions | 114 PASS, 37 subtests PASS, 126.78 секунды |
| PostgreSQL 8 процессов | 1 observation claim, 1 physical mock GET |
| PostgreSQL crash/restart | os._exit(17), UNKNOWN, без повторных GET/POST |
| Финальный PostgreSQL прогон | 1 synthetic POST, 2 synthetic GET, verified events 0 |
| Ruff новых/чистых изменённых файлов | PASS |
| Legacy engine Ruff delta | 5 прежних findings, 0 новых |
| Docker check image | PASS: final source, no-network hard gate, HTTP attempts 0 |

PostgreSQL evidence: private schema
controlled_rehearsal_jobs_6d2431d934dc47a19ebd83b5bfafe882
в ранее восстановленной mcc_integrations_audit_20261014_165636.
Рабочая БД отказана guard до SQL. Реальная PostgreSQL проверяет row/advisory locks;
SQLite не используется как доказательство межпроцессной блокировки.

Первый mock-run выявил cooldown TypeError в legacy reserve_api_request и два
старых ожидания бесконечного verifying. Исправлен ранний отказ при active
cooldown; обновлены assertions на ожидаемый UNKNOWN после нового deadline,
при сохранении проверок отсутствия verified/MCC ownership.
Начальные Docker/PG прогоны использовали установленную старую копию пакета:
после явного PYTHONPATH=/app проверен новый mounted source. В script добавлен
CURRENT_SOURCE_REQUIRED guard до создания fixture. Неудачные прогоны не
засчитываются как PASS, существующие private fixture schemas не удалялись.

Для воспроизведения использовать scripts/check_action_job_observation_postgres.py
только в mcc_integrations_* restored DB с новым private schema. При запуске
через старый базовый image с source mounts обязателен PYTHONPATH=/app.
В работающие сервисы новый source не примонтирован.

## Объём изменений и оставшаяся работа

Изменены writer, существующий ActionEngine, helper job_observation,
mock tests и отдельный PG acceptance script. Дополнены документация/roadmap.
В двух ранее созданных русских документах исправлена повреждённая кодировка;
проверено фактическое наличие кириллицы, а не только валидный UTF-8.

Frontend и публичные API routes не изменены. Frontend build/Playwright и полный
backend suite на этом этапе не запускались; не заявляются. Проверены именно
зависимые backend пути, Docker packaging и изолированная PostgreSQL.

Остаются отдельно: авторитетный readback, production one-operation authorization
и dispatch, identity/asset permissions, 202/lost-job reconciliation contract,
область attribution policy и historical freshness scheduling. Ничего из этого
не объявляется готовым в LIVE. Положительный TRUE -> REVIEW из пользовательского
теста не повышен до WOULD_PAUSE. Правило и экономический профиль не изменены.

ACTIONS_ENABLED=false, LOCAL_READ_ONLY=true, AI_ENABLED=false,
AI_AUTOPILOT_ALLOWED=false сохраняются. Новые реальные рекламные WRITE и Meta
LIVE requests в этом этапе: 0. Все новые HTTP в acceptance используют mocks.
Тесты не являются разрешением на LIVE; runtime observer не активирован.

Следующий этап: проверка документированного READ-контракта для authoritative
readback и его локальная приёмка. Job success остаётся недостаточным доказательством.
## Финальное состояние работающей среды

Проверка 18.10.2026 в 00:18 МСК: PostgreSQL 0016_smart_control;
правило revision 4, enabled=false, maximum threshold, value=null;
ActionExecution для выбранного AD: 0. MetricFlow READ healthy revision 1,
последний обычный успех 00:10:04 МСК; Meta disabled/disconnected revision 4.
Backend /health/live и /health/ready: HTTP 200. Backend, Credential Manager,
PostgreSQL и Redis healthy; frontend/worker/scheduler running.

Финальный отдельный image metric-control-center-job-observer-check:local
собран. В нём без сети подтверждены финальный source и блокировка job GET
до HTTP. Сравнены IDs/image IDs четырёх работающих Python services и hash .env:
без изменений. Рабочие containers не пересоздавались, deploy не выполнялся.
Production hard gate, зависимости, Compose и frontend source не изменены.

Дополнительный финальный тест проверяет изменение job/POST binding во время GET:
ответ старого job не записывается как успех новой привязки; UNKNOWN сохраняет
исходный job ID в audit. Это не ослабляет запись позднего ACK после отзыва прав.