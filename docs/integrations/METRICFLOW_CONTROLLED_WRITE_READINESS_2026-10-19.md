# MetricFlow — первый controlled WRITE: timeout hardening и точные блокеры

Дата: 19.10.2026, Europe/Moscow. Baseline: 490b136.
PHASE 4B: PARTIAL. LIVE WRITE: BLOCKED.
POST timeout / late ACK kernel: READY MOCK + ISOLATED POSTGRESQL.
Advertising WRITE requests=0; Meta LIVE requests=0.
Документ не является разрешением на реальный рекламный запрос.

## Официальный контракт перепроверен

Публичный OpenAPI получен 19.10.2026 13:48:39 UTC / 16:48:39 МСК без credentials:
https://metricflowit.click/api/v1/openapi.json?lang=en
API 1.0.0, SHA256
f52bc8ca0691fa0e2f2b5a5de06aa74a897546b88705ee16851859138a2f3327.
Контракт совпадает с предыдущим сохранённым источником; новый контракт не найден.
Официальная общая документация также проверена: https://metricflowit.click/docs.
Context7 не нашёл нужный продукт; документация других advertising API не использована.
Python 3.12 asyncio.timeout/expired проверены через Context7 по официальному
https://docs.python.org/3.12/library/asyncio-task.html.

Проверены PAUSE/ENABLE, jobs, me, account-scoped ads/adsets/campaigns,
GET campaigns/{campaign_id} и связанные response models. READ CampaignMetrics.id
описан как provider campaign ID; AdAccountInfo.id — provider account ID.
WRITE path entity_id по-прежнему только string без точного namespace/READ binding.
EntityMetrics/InsightRow дают status и effective_status, но не определяют
configured semantics и авторитетность после WRITE. В опубликованной схеме
не найден документированный non-mutating способ проверки manage permission
на конкретный рекламный объект. Наличие READ-доступа и entities:write этого
не доказывает. Общая docs-страница всё ещё говорит campaigns:write;
специфичный OpenAPI задаёт entities:write и остаётся источником scope policy.
Новый ключ или изменение scopes не потребовались и не выполнялись.

## Что исправлено в существующем ActionEngine

До исправления два воспроизводимых mock-сценария ошибочно давали verifying:
ACK после expires_at и ACK после уже выполненного recovery в UNKNOWN.
Добавлена проверка временной и durable state границы перед принятием ACK.

- Асинхронный участок отправки ограничен min(30 seconds, remaining permit time)
  через asyncio.timeout. Это локальный предел, не гарантия latency провайдера.
- После резервирования quota повторно проверяется оставшееся окно. Если оно
  закончилось, vault не открывается и HTTP не начинается; claim уже израсходован.
- TimeoutError сохраняет unknown / OUTCOME_UNKNOWN без повторного POST.
- Проверяется Timeout.expired(), включая mock-coroutine, подавившую cancellation.
- ACK после expires_at не запускает job observation. ACK после recovery не
  возрождает закрытый UNKNOWN. Валидный поздний job_id сохраняется для дальнейшего
  выяснения результата, без присвоения успеха/ownership.
- Внешняя отмена задачи продолжает распространяться как CancelledError.
  Израсходованный durable claim остаётся для прежнего no-resend recovery.

UNKNOWN не означает, что рекламное изменение не применилось. Для будущего LIVE
это остановка до reconciliation, без повторного POST и автоматического ENABLE.
Никакие provider response/error поля, idempotency headers или status semantics
не придуманы. Методы остаются MOCK_ONLY: isolated DB/workspace, явный
httpx.MockTransport и неизменённый ActionSafetyGate обязательны. Production permit,
публичный LIVE route и production dispatcher этой доработкой не созданы.

## Проверки

- До изменения: 2 воспроизводимых late-ACK tests FAIL (verifying вместо unknown).
  После изменения: 7 новых tests PASS, включая короткое окно permit, монотонный
  timeout при неподвижных fixture UTC-часах, suppressed cancellation, recovery,
  caller cancellation и отсутствие повторной отправки.
- Итоговый связанный backend запуск: 169 PASS, 104.51 seconds. Файлы:
  test_controlled_post_deadline, test_controlled_rehearsal,
  test_action_job_observation, test_action_readback, test_metricflow_write_contract.
  Полный backend suite не запускался и не объявляется пройденным.
- PostgreSQL: восстановленная mcc_integrations_controlled_20261016_211626,
  private schema controlled_rehearsal_59fe33c3512e4357b1bd76a606657f09.
  8 процессов -> 1 claim / 1 physical mock POST. Crash exit 17 -> UNKNOWN;
  restart не отправил повтор. Ещё 3 сценария: expiry ACK, recovery ACK, timeout.
  Всего 5 physical mock attempts для пяти команд; LIVE provider requests=0.
- Первый PostgreSQL запуск загрузил старый installed package из site-packages
  вместо mounted candidate и не прошёл новый timeout case. Исправлено окружение
  harness (PYTHONPATH=/app); добавлена fail-fast SHA-проверка загружаемого engine
  до DB setup и в child process. Успех относится к полному повторному запуску
  именно candidate source, не к тому неуспешному запуску.
- Ruff check и format --check для нового test и изменённого PostgreSQL script:
  PASS. В legacy engine 5 прежних diagnostics; новых diagnostics=0.
  Файл целиком не переформатирован. Basic secret scan и staged diff проверены
  перед коммитом. Dependencies/lock не менялись.
- UI/внутренний API-контракт не менялись; frontend build и Playwright повторно
  не запускались. Принятая пользователем campaign simulation остаётся принятой.

## Установка и сохранность

Обновлены только backend и READ-worker. Candidate images собраны source-only
поверх их собственных предыдущих images без сети/установки пакетов.
Проверен SHA реально импортируемого engine и в candidate, и в обоих running
контейнерах. Frontend, scheduler, Credential Manager, PostgreSQL и Redis имеют
прежние container IDs. Rollback images сохранены, canonical tags обновлены
только после проверок. Action worker и обычный Meta scheduler не запускались.

Контроль 19.10.2026 14:04:34 UTC / 17:04:34 МСК:
health/live, health/ready, /login HTTP 200; 14 бизнес/credential таблиц совпадают
по count/digest до/после; .env SHA256 неизменен. Изменения схемы отсутствуют,
миграции/restore рабочей БД не запускались, revision 0016_smart_control.
Рабочие volumes и данные не удалялись.

MetricFlow READ healthy, enabled, revision 1; последний штатный success
14:03:03 UTC. Это локальная проверка сохранённого результата нормального sync,
без отдельного provider probe. WRITE credential/ревизия/сохранённый scope check
не менялись и не объявлены свежепроверенными. Реальный WRITE-ключ не расшифровывался
для этой работы. Все POST тестировали только synthetic credentials.
Meta disconnected/disabled, revision 4. ActionExecution рабочей БД=0.

ACTIONS_ENABLED=false; LOCAL_READ_ONLY=true; AI_ENABLED=false;
AI_AUTOPILOT_ALLOWED=false. Hard contract gate остаётся безусловно закрытым
даже при попытке сделать env разрешающим. Рекламных WRITE=0.

## Что действительно требуется перед первым LIVE

Три внешних факта:

1. Точное равенство/преобразование READ provider ID -> WRITE entity_id для
   выбранного уровня и способ подтвердить account/owner/team binding.
2. Управляющее право текущего MetricFlow профиля на конкретный объект:
   документированный non-mutating GET либо другая официальная процедура.
   API scope и видимость объекта через READ не равны этому праву.
3. Авторитетный источник собственного/configured и effective статуса,
   identity и свежести после команды; поведение при delayed sync/UNKNOWN.

Источник может быть обновлённым OpenAPI, официальным SDK/описанием реализации
или точным ответом разработчика. Письмо не единственный способ; агент сообщений
никому не отправлял. Предыдущий ручной ответ «роль не видно» не заменяет факт 2.

После принятия этих фактов остаётся кодовая работа: production one-operation
permit/dispatcher в существующем ActionEngine и принятый readback. Он пока
не реализован; существующий изолированный rehearsal не объявлен production-ready.
Затем нужны свежие READ/WRITE scope checks, подходящий исходный статус одного AD,
ограниченное окно/attempt budget и отдельное явное разрешение на одну операцию.
SIMULATED request не повышается до LIVE; ENABLE restoration разрешается отдельно.

Что не нужно превращать в безусловный внешний блокер первого пилота:

- Схема 202/job visibility: обязательна при выборе async; первый пилот может
  быть спроектирован на документированном synchronous 200 EntityActionResponse.
  Это вариант проектирования, не включённый режим production executor.
  При его timeout результат остаётся UNKNOWN; он может не уложиться в local cap.
- Provider idempotency: при принятой стратегии ровно одной попытки и no-resend
  её отсутствие не требует выдуманного Idempotency-Key и не разрешает повтор.
- Полные error bodies: неизвестный ответ останавливает путь с UNKNOWN;
  неподтверждённое тело не интерпретируется как успех или безопасный retry.

Новых пользовательских кругов локальной симуляции не требуется. Ближайший
переход к LIVE блокируется перечисленными фактами и незавершённым production
dispatcher, а не повторением уже принятого manual UI теста.
