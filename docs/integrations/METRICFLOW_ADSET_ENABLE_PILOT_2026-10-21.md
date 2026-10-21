# Single-group ENABLE pilot — 21.10.2026

## Scope and authorization

User requested: «можешь попробовать еще включить группу обьявлений» after the
single-AD PAUSE/ENABLE acceptance in the same hierarchy. This authorizes one
experimental ENABLE_ADSET for group 120247730105950571 (name 3), account
act_1047962734516123. Campaign 120247730079240571 must stay PAUSED.
No campaign enable, child AD write, budget/bid, retries or automation is authorized.

Official OpenAPI anonymous GET was rechecked: enable endpoint and EntityActionRequest
unchanged, SHA256 f52bc8ca0691fa0e2f2b5a5de06aa74a897546b88705ee16851859138a2f3327.
[Official source](https://metricflowit.click/api/v1/openapi.json?lang=en).
Body level=adset is documented. WRITE ID namespace still explicitly unverified:
UNVERIFIED_CANDIDATE_FACEBOOK_ADSET_ID. AD acceptance does not prove every group ID.

Existing ActionEngine, durable claim, quota/cooldown, encrypted WRITE credential,
shared POST timeout and UNKNOWN/no-resend are reused. No second executor was added.
The additional private contract is limited to ENABLE_ADSET, exact group/account,
level=adset and distinct AUTHORIZE_ONE_EXPERIMENTAL_ENABLE_ADSET_WITH_UNVERIFIED_ID.
Normal and verified AD-only contracts do not gain general group/campaign admission.

## Guards

- Fresh, complete campaigns/adsets/ads catalogs with identical source timestamp.
- Campaign configured/effective PAUSED/PAUSED; group PAUSED/PAUSED.
- Correct account/hierarchy and sorted pinned child inventory (ID + own status).
- After durable claim: three GETs repeat all guards; child changes stop POST.
- Single synchronous POST /api/v1/entities/120247730105950571/enable,
  JSON {"level":"adset"}; no async job, redirect or retry.
- Concurrency 1, maximum 3 pre-POST GET + 1 POST; window <=600s,
  shared POST-stage timeout <=30s. Any uncertainty stops without resend.
- API scope alone is not asset permission; management remains USER_ATTESTED.
- Cached MetricFlow READ is not an atomic Meta lock; it cannot exclude outside
  operators changing the campaign after the snapshot.

Previous child ENABLE request 48e04f4a-1991-4e8b-8a09-7876044fa20c was locally reviewed
only after spent wire, expired window, original live_unknown/MANUAL_READBACK_DEADLINE,
three actual manual observations and fresh ACTIVE child inside this exact group.
ActionRequest is MANUALLY_REVIEWED; original execution outcome/error, wire_spent,
OUTCOME_UNKNOWN and historical logs are retained. No Rule Engine ownership is created.

## Preparation measured

Request 39836b5b-296f-4896-917c-3ae2b48eb536, revision 1, DRAFT.
Baseline 21.10.2026 15:25:04 UTC / 18:25:04 MSK:
campaign PAUSED, group PAUSED, only child AD 120247730105960571 ACTIVE.
Baseline expires 15:40:04 UTC; draft expires 15:44:07 UTC.
First credential GET /me returned PROVIDER_UNAVAILABLE; one bounded READ recheck
succeeded (SCOPES_VERIFIED/active_paid), then three catalog GETs succeeded.
No advertising POST was sent during preparation. No keys/revisions changed.

Backend and Credential Manager updated with image
metric-control-center-experimental-adset-20261021:prepared, based on the existing
working image, unchanged dependencies. Source hashes of 13 modules match locally
in both services. Before preparation all 14 protected tables matched exactly.
Other five service containers and .env were not changed. No migrations/role grants.

Tests: new group 10 PASS; prior experimental/enable/contract regressions 75 PASS;
private API/admin/CSRF and production pilot 93 PASS. Isolated restored PostgreSQL
PASS: AD PAUSE -> AD ENABLE -> local review -> group mock ENABLE, no resend,
UNKNOWN preserved, facts unchanged, private schema removed in finally.
Group tests include wrong level/ID/method, parent/children change and timeout.
All test HTTP is MockTransport. Ruff check/format and secret/diff scans PASS.

ACTIONS_ENABLED=false, LOCAL_READ_ONLY=true, AI_ENABLED=false,
AI_AUTOPILOT_ALLOWED=false in running services. Meta LIVE remains disconnected.
The future authorized attempt uses enabled flags only in one bounded exec process.
Rule TEST - Creo 03 - PAUSE - IT remains disabled DRY_RUN; existing profiles/rules
are not modified. Before group execution advertising POST total remains 2.

Evidence (ignored): .tools/adset-enable-pilot-20261021/.
STATUS AT THIS CHECKPOINT: GROUP PILOT PREPARED; ONE USER-AUTHORIZED ATTEMPT PENDING.

## Единственная разрешённая LIVE попытка

21.10.2026 15:30:44 UTC / 18:30:44 MSK отправлен ровно один:

```http
POST https://metricflowit.click/api/v1/entities/120247730105950571/enable
Content-Type: application/json

{"level":"adset"}
```

После durable claim перед ним выполнены три GET catalogs, все 200; кампания и группа
повторно PAUSED, состав из одного ACTIVE AD не изменился. Получен HTTP 200,
existing typed adapter принял success=true с точным entity_id группы, без job.
Completed_at 15:30:46 UTC. Новых AD или Campaign POST нет; ничего не повторялось.

Request 39836b5b-296f-4896-917c-3ae2b48eb536: verifying, revision 9,
control SYNC_ACKNOWLEDGED_NEEDS_MANUAL_READBACK, attempts=1, wire_spent=true,
execution live_acknowledged, error_code=null. Окно до 15:40:04 UTC / 18:40:04 MSK.
ACK не равен подтверждённому изменению переключателя.

Пользователю запрошена сверка именно вкладки «Группы объявлений», группы «3» / ID
120247730105950571: группа включена, кампания всё ещё выключена, effective статус
«Кампания выключена». Никаких переключений вручную. Ожидается ручной ответ.
Новые API GET для наблюдения/опроса не запускались; только локальные SELECT/runtime.

После одноразового процесса backend и CM снова проверены: ACTIONS_ENABLED=false,
LOCAL_READ_ONLY=true, AI_ENABLED=false, AI_AUTOPILOT_ALLOWED=false, WRITE_DISABLED,
global capability BLOCKED. .env SHA неизменён, Meta disconnected/disabled revision 4.
Rule/profile настройки не менялись. Из 14 защищённых таблиц 9 совпали полностью;
изменились только requests/logs/executions и результат/audit проверки WRITE ключа.
Две попытки GET /me не являются рекламными retry. Новый ActionExecution ровно 1.
Сохранены 3 исторических исполнения: AD PAUSE, AD ENABLE, ADSET ENABLE; ни одного resend.
Playwright Edge smoke 3 PASS (login/auth redirect/page errors), provider HTTP=0.
Source implementation commit be48ec4; дополнительных source изменений после тестов нет.

CURRENT STATUS: GROUP ENABLE ACKNOWLEDGED; MANUAL READBACK PENDING.
ADSET ENABLE POST: 1. ADVERTISING WRITE REQUESTS TOTAL: 3.

## Исправленная ручная сверка после обновления Ads Manager

21.10.2026 в 18:38:41 МСК записан ответ пользователя: группа включилась;
предыдущий ответ «остаётся выключенной» был ошибочным из-за необновлённой страницы.
Для группы 120247730105950571 сохранено отдельное локальное audit-событие
pilot_manual_adset_target_confirmed_after_refresh, configured_status=ACTIVE,
matches_target=true, source=USER_REPLY_CORRECTION_AFTER_REFRESH.

Это пользовательская сверка переключателя, а не authoritative API readback.
Точное время наблюдения, актуальное состояние кампании и effective статус группы
в исправлении не указаны; эти поля не выдумывались. Запрошено дополнение.
Формальный статус на момент записи: verifying, revision 9,
SYNC_ACKNOWLEDGED_NEEDS_MANUAL_READBACK; execution live_acknowledged.
Окно первоначальной проверки не продлевалось, server-side gates не обходились.
Никаких новых provider GET/POST для этой сверки не выполнено. Глобальные четыре
защитных флага проверены и сохранены. Рекламных исполнений по-прежнему всего 3.

CURRENT MANUAL RESULT: USER CONFIRMED GROUP TOGGLE ACTIVE AFTER REFRESH.
FORMAL READBACK: INCOMPLETE (campaign/effective status and observation time missing).
NEW ADVERTISING WRITE REQUESTS: 0. TOTAL: 3.

## Полная ручная сверка пользователя

В 18:48:35 МСК 21.10.2026 сохранено дополнение пользователя: кампания выключена,
показ кампании прекращён; проверено «только что». Вместе с предыдущим исправлением
это подтверждает вручную: группа 120247730105950571 ACTIVE, кампания
120247730079240571 PAUSED, effective статус группы нормализован как CAMPAIGN_PAUSED.
Время observed_at — серверное время записи ответа «только что», а не независимая
метка времени Meta; происхождение этой оценки отдельно зафиксировано в audit.

Применён существующий record_manual_readback, без provider HTTP. Полная сверка
записана позже исходного deadline 18:40:04 МСК: request unknown, revision 10,
control MANUAL_OBSERVATION_OUTCOME_UNKNOWN, execution live_unknown, error_code null.
Никакой ошибки провайдера этим не установлено: формальная неопределённость связана
с поздней полной сверкой, при наличии HTTP ACK и пользовательского подтверждения.
Deadline, прежние события и число попыток не изменялись; API authority и владение
паузой для Rule Engine не создавались. Историческое незавершённое описание выше
относится к предыдущим контрольным точкам, а актуальный результат приведён здесь.

FINAL MANUAL RESULT: ADSET ACTIVE; CAMPAIGN PAUSED; DELIVERY BLOCKED BY CAMPAIGN.
FORMAL PILOT RESULT: UNKNOWN (complete manual readback recorded after deadline).
GLOBAL ACTIONS: DISABLED; LOCAL_READ_ONLY=true; AI flags=false.
NEW PROVIDER HTTP REQUESTS: 0. ADVERTISING WRITE REQUESTS TOTAL: 3.
Evidence: .tools/adset-enable-pilot-20261021/manual-complete-readback.json (ignored).
