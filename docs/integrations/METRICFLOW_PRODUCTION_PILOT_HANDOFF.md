# MetricFlow production pilot handoff — 19.10.2026

STATUS: IMPLEMENTED / VERIFIED LOCAL-MOCK. LIVE: BLOCKED.

## Результат этапа

Добавлен закрытый путь одноразового пилота в существующий ActionEngine и приватный
Credential Manager. Это исходный код для будущего согласованного запуска, а не
разрешение на рекламные действия. Рабочие образы не пересобирались и не заменялись;
новые маршруты не опубликованы через frontend/BFF. Новая кнопка запуска в UI не добавлена.

Безусловный WRITE_CONTRACT_UNVERIFIED в ActionSafetyGate и закрытый
ActionCapabilityRegistry сохранены. Одного изменения environment flags недостаточно.
Реального permit и записи о принятии внешних доказательств в рабочей БД нет.
Сохранённая SIMULATED-команда включения кампании не переводится в LIVE.

## Что реализовано

- Только одно объявление: PAUSE_AD или ENABLE_AD. Кампании, группы, бюджеты,
  ставки и команды правил в этот production pilot не принимаются.
- Авторизация отдельно от подтверждения локальной симуляции: точный Request ID,
  revision, кабинет, AD, операция, исходный статус, WRITE revision, оператор/workspace.
  Отдельное заявление AUTHORIZE_ONE_METRICFLOW_AD_STATUS_POST обязательно.
- Разрешение действует не дольше исходного черновика и 600 секунд. В workspace
  допускается один незавершённый LIVE-пилот; UNKNOWN и другие незавершённые рекламные команды также блокируют следующий.
- Durable claim и уникальный ActionExecution фиксируются до расшифровки ключа.
  Максимум один физический POST, без retry, async job GET или автоматического readback.
  POST ограничен 30 секундами и остатком исходного deadline.
- Приватный vault открывается только после серверных проверок. Нет fallback на READ-ключ.
  Перед HTTP повторно проверяются evidence, actor, привязки, срок и WRITE revision/digest.
- HTTP 429 фиксирует общий cooldown MetricFlow, не подменяя здоровье READ-подключения.
  Ошибки, timeout и поздний ACK не разрешают повторную отправку.
- Ручной результат сохраняется отдельно: MANUALLY_REVIEWED только после своевременного
  ACK и совпадения собственного configured status в пределах deadline. Effective status
  записывается отдельно. Это НЕ авторитетный API-readback, НЕ succeeded/verified
  и НЕ право правила автоматически включать объявление.
- Совпавший ручной статус после неизвестного POST либо после deadline сохраняет UNKNOWN.
  Такой исход требует отдельного расследования; второй POST автоматически не отправляется.

## Приватная процедура будущего запуска

Сейчас каждый запуск должен быть отклонён существующими gates. Эта последовательность
описывает будущую процедуру после принятия доказательств, отдельного разрешения пользователя
и проверенного развёртывания. Она не является командой на снятие ограничений.

1. Получить подтверждение namespace WRITE entity_id и права конкретного подключённого
   профиля управлять выбранным AD. Проверить свежий own/effective status и иерархию.
2. Через существующий Credential Manager выполнить безопасную проверку /me, когда
   потребуется свежий scope. Ключ не заменять; сохранить ревизии READ и WRITE.
3. Создать новый актуальный ручной черновик PAUSE_AD, выполнить preflight и подтверждение
   намерения. Старую терминальную SIMULATED-запись не использовать повторно.
4. Инженерная процедура принимает настоящие внешние evidence в аудит. Маршрута для
   создания pilot_external_evidence_accepted нет. Запись нельзя изготовлять ради снятия
   блокировки. Ожидаются точные actor/account/AD/operation, READ/WRITE revision,
   PROVIDER_AD_ID namespace с источником, own/effective status, profile_id и проверенное
   MANAGE_CAMPAIGNS/FULL_CONTROL с источником MANUAL_META_ACCESS_REVIEW.
5. После отдельного согласования точной карточки авторизованный admin с действующей
   сессией и CSRF вызывает приватный POST /controlled-pilot/{request_id}/authorize:

```json
{
  "revision": "<целое число актуальной ревизии; здесь показан placeholder>",
  "credential_revision": "<целое число WRITE revision>",
  "account_id": "act_1047962734516123",
  "entity_id": "120247747556780571",
  "operation": "PAUSE_AD",
  "expected_status": "ACTIVE",
  "statement": "AUTHORIZE_ONE_METRICFLOW_AD_STATUS_POST"
}
```

Это шаблон, не готовый JSON для отправки: числовые placeholder нужно заменить числами.
Authorization endpoint возвращает новую revision и expires_at. Execute принимает только
эту revision: POST /controlled-pilot/{request_id}/execute с {"revision": <integer>}.
Разрешающие клиентские поля вроде allow_write запрещены схемой. Публичного WRITE proxy нет.

6. Наблюдать за ActionExecution, controlled_live_* audit, ApiQuota requests/blocked_until.
   Считать ACK только подтверждением приёма. При 401/403/429, timeout, несовпадении ID,
   malformed response, остановке процесса или истечении срока прекратить пилот без resend.
7. После своевременного ACK вручную сверить точные кабинет/AD и own/effective status в Meta.
   Приватный /readback принимает revision, account_id, entity_id, configured_status,
   effective_status, observed_at с timezone и statement=RECORD_MANUAL_META_READBACK.
   Никаких provider GET этот endpoint не выполняет.
8. После единственной попытки вернуть/сохранить закрытые WRITE flags по утверждённой
   процедуре, записать результат. При UNKNOWN не создавать второе разрешение до расследования.
   Автоматического включения обратно или изменения родительской кампании нет.

## Измерено в рабочей системе

Снимок: 19.10.2026 19:51:16 UTC / 22:51:16 МСК. Значения READ могут меняться штатной синхронизацией.

- PostgreSQL: 0016_smart_control; Docker 29.8.2. После запуска Docker завершилось штатное
  PostgreSQL recovery; PostgreSQL/backend/Credential Manager/Redis healthy, frontend/worker/
  scheduler running. Migration container exited 0; миграции не запускались повторно.
- Meta: disabled / disconnected, credential revision 4, активных Meta provider jobs 0.
- MetricFlow READ: enabled / healthy, revision 1; последнее сохранённое успешное обновление
  19.10.2026 15:50:02 UTC / 18:50:02 МСК. Это наблюдение из БД, не новый LIVE probe.
- WRITE: encrypted_present=true, revision 1. Исторический /me от 18.10.2026 14:30:26 UTC
  подтверждал entities:write и active_paid. Для исполнения проверка уже устарела.
  Asset management permission этим scope не подтверждается.
- ActionExecution=0; LIVE_SINGLE_OPERATION permits=0; external pilot acceptance records=0.
- Общая квота MetricFlow 276/800 за UTC-день, blocked_until отсутствует.
- AD 120247747556780571: ACTIVE, observed_at 15:50:00 UTC.
  Adset 120247747556830571 и campaign 120247747556760571: ACTIVE, observed_at 15:03:00 UTC.
  Это устаревшие сохранённые статусы, не разрешение на команду. Ранее ручная сверка кампании
  показывала PAUSED; прежний снимок нельзя переносить на текущий момент.
  Effective status всех трёх объектов отсутствует.
- .env сохраняет ACTIONS_ENABLED=false, LOCAL_READ_ONLY=true, AI_ENABLED=false,
  AI_AUTOPILOT_ALLOWED=false. Runtime backend/Credential Manager подтверждают все четыре;
  worker/scheduler сохраняют отключённый WRITE. Их конфигурация не менялась.

Ранее, 19.10.2026 14:31:58 UTC, безопасный READ связал кабинет Valya Sergeeva /
act_1047962734516123 с MetricFlow internal_id=739978, profile_id=16192 и профилем
Jacquelin Guadalupe Trejo Tovilla. Это историческое подтверждение mapping, не проверка
текущих прав. 16192 — MetricFlow profile ID, не подтверждённый Meta user ID.

## Контракт и точные блокеры

Официальный [MetricFlow OpenAPI](https://metricflowit.click/api/v1/openapi.json?lang=en)
проверен предыдущим этапом 19.10.2026 14:16:42 UTC, version 1.0.0,
SHA256 f52bc8ca0691fa0e2f2b5a5de06aa74a897546b88705ee16851859138a2f3327.
Подтверждены POST entities/{entity_id}/pause и /enable, body level=ad, sync default false
для async-параметра, EntityActionResponse. Здесь использован уже проверенный контракт;
проверочный код этапа не отправлял запросов к MetricFlow или Meta. Штатный MetricFlow READ сохраняет своё расписание после запуска Docker.

Блокеры на момент снимка 19.10.2026 (обновление о правах от 20.10.2026 — ниже):

1. Подтверждение, что WRITE entity_id принимает именно provider AD ID из READ.
   Тип string в OpenAPI сам по себе namespace не доказывает.
2. Право профиля Jacquelin Guadalupe Trejo Tovilla управлять рекламой кабинета
   act_1047962734516123 / выбранным AD. Нужны отображаемая роль/право и время сверки.
   Номер кабинета из адресной строки и is_active=true не подтверждают это право.
3. Свежие baseline/own/effective status и scope-check WRITE; существующие данные устарели.
4. Принятие подтверждённого набора операций серверными gates. Они намеренно остаются
   закрытыми; клиентский body или смена environment не должны их обходить.
5. Отдельное разрешение пользователя на конкретный новый PAUSE_AD request, после карточки
   с точными IDs, ревизиями и сроком; затем проверенное развёртывание закрытого пути.
6. Для автоматических правил и расширения на кампании/группы отдельно нужен подтверждённый
   авторитетный readback own/effective status. Ручной пилот такого доказательства не создаёт.

Письмо провайдеру не является обязательным каналом: подходят опубликованная официальная
спецификация или иное проверяемое подтверждение нужного namespace. Пробный POST ради
угадывания ID без принятого контракта не выполняется.

## Проверки

Основной связанный backend прогон: 435 PASS за 524.36 секунды. Проверены manual actions,
multilevel preparation, pilot review, synchronous/deadline/rehearsal execution, job observation,
readback, WRITE contract, integration settings и private API/auth.
После финальных усилений proof typing и проверки конфликтующих команд повторный targeted
прогон: 38 PASS за 52.80 секунды (37 pilot tests + private ASGI/admin/CSRF test).
Эти наборы пересекаются; их количества не складываются как уникальные тесты.
Ruff check и format --check пяти новых/изменённых файлов: PASS. В legacy engine ровно
пять прежних замечаний (I001 x2, FURB157 x2, BLE001), сверено с HEAD; новых нет.
Синтаксис всех шести Python-модулей: PASS. Локальные backend /health/ready и frontend
/manual-control: HTTP 200. Это smoke-check, не Playwright acceptance новой функции.
PostgreSQL: PASS, restored DB mcc_integrations_controlled_20261016_211626,
schema controlled_rehearsal_0ea28ed179a84f06be14a1a58895c1aa. Два отдельных набора по 8
процессов дают по одному claim/POST; crash exit 17 -> UNKNOWN, restart -> NO_RESEND.
Итого 13 физических mock HTTP attempts, включая прежние deadline и six-level sync cases.
Ручная запись результата не создаёт API authority/verified ownership.

Сырые локальные результаты: ignored .tools/production-pilot/ (backend.txt, postgres.txt,
runtime.json, baseline/current Ruff JSON). Секреты в отчёт не включены; реальный WRITE-ключ
не расшифровывался. Frontend не менялся; build/Playwright этим этапом не запускались.

META LIVE REQUESTS INITIATED BY THIS STAGE: 0.
ADVERTISING WRITE REQUESTS: 0.
LIVE STATUS: BLOCKED — separate authorization not requested until evidence is accepted.

## Обновление 20.10.2026: подтверждение прав пользователем

Источник: прямое сообщение пользователя в текущей рабочей сессии:
«Jacquelin Guadalupe Trejo Tovilla это основной соц с которого управляются все рекламные кабинеты. права есть».

Принято как USER_ATTESTED: пользователь подтверждает, что этот профиль основной,
управляет рекламными кабинетами и имеет право управления, включая уже выбранный
act_1047962734516123 / Valya Sergeeva. Общий вопрос «есть ли права у этого профиля»
повторять не требуется. Не требуется повторная локальная симуляция.

Это подтверждение пользователя, не результат независимой проверки Meta API.
Название роли MANAGE_CAMPAIGNS/FULL_CONTROL, Meta user ID и новая инструментальная
проверка доступа этим сообщением не установлены. Предыдущий READ mapping profile_id=16192
остаётся историческим MetricFlow mapping. Реальные scope/revision/status в этом шаге
запросами к провайдеру не обновлялись.

Подтверждение сохранено в документации. Оно не превращено в
pilot_external_evidence_accepted: такой комбинированный объект также требует namespace
WRITE ID, актуальных привязок/revisions, операции и свежих own/effective status.
MANUAL_META_ACCESS_REVIEW в серверном аудите не подставляется вместо USER_ATTESTED.
Пользователь не предоставил разрешение на рекламный POST или изменение флагов.

Актуальные следующие условия:

1. Технически подтвердить namespace WRITE entity_id для AD 120247747556780571.
2. Перед конкретным пилотом получить свежие READ/WRITE checks и own/effective status,
   оформить объектную карточку и корректно принять доступные evidence серверной процедурой.
3. Проверить и развернуть закрытый single-use путь; серверные gates не обходить.
4. Получить отдельное разрешение пользователя на один конкретный PAUSE_AD после карточки.

Права профиля: USER_ATTESTED. Контракт ID: UNVERIFIED. LIVE: BLOCKED.
ACTIONS_ENABLED=false; LOCAL_READ_ONLY=true; AI_ENABLED=false; AI_AUTOPILOT_ALLOWED=false
подтверждены чтением .env; код и конфигурация не менялись. Новые тесты не запускались:
изменение только документационное, прежние результаты выше относятся к этапу 19.10.2026.
Provider API requests в этом шаге: 0. Advertising WRITE requests в этом шаге: 0.

## Обновление 20.10.2026: окончание проверки опубликованного WRITE ID контракта

[WRITE ID decision](METRICFLOW_WRITE_ID_DECISION_2026-10-20.md): свежий OpenAPI имеет тот же
SHA; проверены связанные READ/WRITE schemas и официальное руководство. Явное равенство
Facebook Ad ID и WRITE entity_id не установлено; документированного неизменяющего
validate/dry-run для этого ID не найдено. Осталось внешнее уточнение, сформулированное
одним вопросом в отчёте. Провайдеру ничего не отправлялось. До ответа не нужно повторять
симуляцию или общий вопрос о правах. Неподтверждённый контракт не реализован и gates
не изменены; authenticated API requests=0, Advertising WRITE requests=0 за этот шаг.
