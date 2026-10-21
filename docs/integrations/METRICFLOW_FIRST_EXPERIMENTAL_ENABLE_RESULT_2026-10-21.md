# MetricFlow — единственный LIVE ENABLE_AD, 21.10.2026

## Результат

ONE ENABLE POST SENT / HTTP 200 / ACKNOWLEDGED / MANUAL READBACK PENDING.
ACK не доказывает фактический статус Meta или доставку.

Пользователь отдельно разрешил один экспериментальный ENABLE_AD для
120247730105960571 с принятием риска неподтверждённого WRITE ID.
Ранее выданное PAUSE-разрешение не использовалось вместо нового согласия.

- AD: #71012012_EGR_Creo 03 / 120247730105960571.
- Account: Valya Sergeeva / act_1047962734516123.
- AdSet: 120247730105950571; Campaign: 120247730079240571.
- Новый Request: 48e04f4a-1991-4e8b-8a09-7876044fa20c.
- PostgreSQL status verifying, revision 9.
- Control SYNC_ACKNOWLEDGED_NEEDS_MANUAL_READBACK.
- ActionExecution live_acknowledged, error_code null.
- attempts=1, wire_spent=true. Нет повторной отправки.

## Свежая проверка перед исполнением

Baseline карточки 80836c7e-e9a9-41f8-a687-f88c0ce59997 уже истёк. Старый DRAFT
штатно отменён, без удаления истории. Первый GET /me через Credential Manager
дал PROVIDER_UNAVAILABLE; подготовка остановилась до каталогов и рекламного POST.
Выполнена одна повторная READ-проверка подключения, без повторения рекламы:
SCOPES_VERIFIED / active_paid, отдельный encrypted WRITE credential revision 1.
Каждый GET /me без retries; scopes не подставлялись из старого результата.

Свежие три READ каталога: source_updated_at 21.10.2026 13:24:28 UTC,
campaign PAUSED/PAUSED, adset PAUSED/PAUSED, AD PAUSED/PAUSED. Проверены точные ID,
иерархия и полнота одного snapshot. Новый DRAFT ссылается на pinned локальный review
первого PAUSE 79e47858-d850-4935-b2a3-e0d6c1b72b85; его неизвестный API-результат и
spent wire не переписаны. Принята отдельная фраза
AUTHORIZE_ONE_EXPERIMENTAL_ENABLE_WITH_UNVERIFIED_ID.

Исполнение: существующий ActionEngine/private PilotContract, подтверждение намерения,
explicit authorization, durable claim, quota/cooldown, credential revision/hash и
consume-before-HTTP. На время одного docker exec процесса переданы
ACTIONS_ENABLED=true / LOCAL_READ_ONLY=false. Environment работающих сервисов и .env
не изменялись; workers/scheduler не получали WRITE допуска. После завершения процесса
ничего дополнительно выключать или восстанавливать в глобальной конфигурации не нужно.

После durable claim выполнены ещё три GET campaigns/adsets/ads, все HTTP 200.
Родители повторно PAUSED, own/effective AD PAUSED. Ограниченный реальный transport
разрешал ровно три таких GET и один точный POST; redirects/retries запрещены.

```http
POST https://metricflowit.click/api/v1/entities/120247730105960571/enable
Content-Type: application/json

{"level":"ad"}
```

Physical POST started_at: 21.10.2026 13:27:59 UTC / 16:27:59 МСК.
Получен HTTP 200. Existing typed adapter принял success=true с нужным entity_id,
без async job. Completed_at 13:28:04 UTC. Тело ответа и секретные заголовки в отчёт
не копируются. Ровно один ENABLE POST, без PAUSE/ENABLE повторов, budgets/bids,
изменения родителей, Meta API или автоматического readback polling.

В стадии исполнения — 3 GET + 1 POST. В новой подготовке — 2 GET /me (первый
неуспешный, второй успешный) и 3 GET каталогов. Каждый этап учитывает общую квоту.

## Проверка после попытки

В backend и Credential Manager подтверждены:

- ACTIONS_ENABLED=false, LOCAL_READ_ONLY=true;
- AI_ENABLED=false, AI_AUTOPILOT_ALLOWED=false;
- WRITE_DISABLED и global capability BLOCKED;
- .env SHA не изменён;
- Meta disabled/disconnected revision 4;
- ActionExecution всего 2: исторический PAUSE и текущий ENABLE;
- Advertising WRITE всего 2: один PAUSE + один ENABLE;
- Рекламных retry/resend 0, дополнительных разрешённых операций нет.

Исходники не менялись, unit-тесты повторно не запускались. Это один реальный
ограниченный интеграционный тест реализации 565caf0; gates и mocked backend/PG
проверены на предыдущем этапе. Текущие проверки — физический trace, typed ACK,
локальные SELECT/runtime flags, source hashes и secret scan/diff check.
Sanitized evidence: ignored .tools/experimental-enable-live-20261021/.

## Следующий ручной шаг

Пользователю отправлен запрос: обновить Ads Manager, открыть точный AD внутри
указанных Campaign/AdSet, проверить собственный переключатель, статусы родителей,
effective/доставку и время сверки. Ожидается AD включён при выключенных родителях.
Сам переключатель не трогать. Не объявлять включение подтверждённым только по ACK.
Окно permit: до 21.10.2026 13:37:50 UTC / 16:37:50 МСК.
Позднее наблюдение не подделывает своевременный readback и не создаёт ownership правил.

FINAL: ENABLE ACKNOWLEDGED — MANUAL READBACK PENDING — NO RESEND.
ENABLE POST: 1. ADVERTISING WRITE REQUESTS TOTAL: 2.
