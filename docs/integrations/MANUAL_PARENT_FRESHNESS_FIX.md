# Manual parent freshness — исправление и повторная приёмка

Дата: 19.10.2026, Europe/Moscow.
Статус кода: DEPLOYED / LOCAL-MOCK + SCHEDULED READ VERIFIED.
Ручная симуляция кампании: ACCEPTED — ENABLE_CAMPAIGN / SIMULATED.
Ручная симуляция выбранной группы: BLOCKED BY EFFECTIVE STATUS.
LIVE ADVERTISING WRITE: BLOCKED. Advertising WRITE requests = 0.

## Что показали ручные проверки 18 октября

- Campaign request e51292f1-ebbd-4b1f-a865-96d7a1efa19c: сохранённый статус
  22:00 МСК, preflight 22:30:29, возраст около 30 минут.
- Adset request af3ae67d-34a1-4af0-a4b5-5016000ea8ad: статус 22:03 МСК,
  preflight 22:31:52, возраст около 29 минут.
- В PostgreSQL у обоих blocking_reasons = [STATUS_STALE], local_allowed=false,
  live_allowed=false. Остальные WRITE reason codes относятся к закрытому LIVE.
- Freshness gate (900 секунд) сработал правильно. SIMULATED не достигнут.

Причина: today-sync каждые 10 минут успешно обновлял insights, но parent catalogs
использовали cache_seconds=3600. Рекомендация ждать очередной обычный sync была
недостаточно точной: он мог использовать всё тот же часовой parent cache.
Эти ручные результаты принимаются как проверка блокировки устаревших данных,
а не как завершение ручной симуляции. Исторические команды и журнал сохранены.

## Минимальное исправление

В SyncEngine.parent_states добавлен адресный запрос обновления из существующих
ручных BLOCKED-команд. Новый scheduler, HTTP endpoint, очередь или исполнитель
не созданы. Каталоги и их READ-контракты не менялись.

Условия: MetricFlow, текущий workspace/account, campaign/adset, phase=4A,
source=manual, совпадение kind/operation/entity ID, STATUS_STALE в локальных
blocking_reasons, корректный timezone-aware expires_at, created_at <= now < expiry.
Подтверждённое наблюдение должно быть старше создания команды или отсутствовать.
Дополнительно точный parent ID должен присутствовать среди родителей текущего
insight window. Отсутствие target не вызывает чтение чужих parent-каталогов.

При ближайшем штатном sync обновление объединяется по account/kind с обычными
запросами каталогов. Несколько объектов одного кабинета и уровня используют
один каталог. После успешного сохранения наблюдения не старше команды старый
STATUS_STALE в provenance не вызывает повторного принудительного GET.
Cancel, SIMULATED, expiry и неподходящие команды не инициируют этот путь.

Все GET проходят прежние lease, durable per-attempt quota, cooldown, shared
page/row caps и atomic publish. Ошибка или неполный каталог не изменяет старое
observed_at. Действующие READ retries остаются ограниченными; после неудачи
следующий штатный sync может повторить READ в пределах срока команды и квоты.
Успешное обновление не меняет ActionRequest, ожидаемый статус, TTL или разрешение.
Preflight/confirm/simulate продолжают самостоятельно проверять текущее состояние.

Оценка добавочной нагрузки при успешных ответах: максимум один GET на выбранный
account/kind, если его каталог ещё не обновляется обычным sync. Для двух выбранных
уровней одного кабинета — до двух дополнительных GET. Повторы READ при transport
ошибках учитываются отдельно тем же счётчиком; жёсткая дневная квота остаётся 800.
Глобальный часовой cache и freshness 900 секунд не ослаблены. Ключи, API scopes,
системные флаги и рекламные данные не менялись.

## Автоматическая проверка

- Новый файл тестов: 13 PASS, 14 subtests PASS. Включены обычный часовой cache,
  оба уровня, объединение двух synthetic adsets одного кабинета, отсутствие
  повторного refresh после успеха, cancelled/expired/неподходящие команды,
  отсутствие target в insights, quota exhaustion, 429/cooldown, hierarchy error
  и shared page cap. Все HTTP — httpx.MockTransport.
- В совместном запуске manual/multilevel regression прошли 90 cases; один новый
  parent-refresh case выявил ошибку fixture (в исходном примере один adset на
  кабинет). Добавлен второй synthetic adset того же кабинета; после исправления
  весь новый файл прошёл отдельно. Чистый единый полный backend suite не заявлен.
- PostgreSQL: точный новый запрос и два уровня проверены на изолированной
  восстановленной БД. Fresh cache и expiry не дают refresh; fixture-транзакция
  полностью ROLLED BACK. Provider HTTP = 0.
- Новый test file: Ruff check и format --check PASS. Для старого sync engine
  осталось 8 прежних Ruff diagnostics; сравнение с HEAD: новых diagnostics = 0.
  Полное форматирование старого engine не выполнялось.
- UI и внутренний API-контракт не менялись; frontend/Playwright в этом
  исправлении повторно не запускались. Предыдущая браузерная приёмка сохранена
  в MULTILEVEL_STATUS_LOCAL_ACCEPTANCE.md.

## Установка и сохранность

Source-only Docker images собраны поверх отдельных текущих backend/worker base
images без сети и изменения dependencies. Совпадение candidate source SHA256
с host source проверено. Обновлены только backend и idle READ-worker.
Frontend, scheduler, Credential Manager, PostgreSQL и Redis имеют прежние
container IDs. READ scheduler не включался заново, Meta не подключался.

Перед установкой проверены отсутствие активных worker tasks и живого sync lease.
Две старые running-записи (Meta 09.10 и MetricFlow 19.10 03:10 UTC) не имели
действующей задачи/lease. Их история не удалялась и не переписывалась.

Свежий pg_dump: 11 036 905 bytes, SHA256
9adb2ffdeacc97f7f9abf458568159e66f8f3ff3ca51e77f9ba42d726589adea.
Checksum и pg_restore --list PASS; ACL owner+SYSTEM. Новое полное восстановление
этого backup не выполнялось. Бизнес/credential таблицы проверены отдельно:
14 count/digest до и после совпадают. .env SHA256 сохранён. БД и volumes
не удалялись; миграции не запускались; revision 0016_smart_control.
Health live/ready и /login: HTTP 200. Rollback images сохранены.

После установки наблюдён уже существующий scheduled today-sync:
19.10.2026 07:30:00–07:30:11 UTC / 10:30:00–10:30:11 МСК, succeeded,
10 физических READ attempts. Агент не запускал отдельный provider probe или
внеочередной sync. В 10:31 МСК: READ healthy, revision 1, quota 94/800,
cooldown нет; очередь пуста, активных tasks/leases нет. Эти значения — снимок,
не обещание постоянной свежести. Старые выбранные requests уже истекли и не
инициировали адресный refresh; новый путь подтверждён mock/PostgreSQL тестами,
а наблюдённый штатный READ также обновил просроченные обычные каталоги.

Свежие локальные значения выбранных объектов на 10:30 МСК:

| Уровень | ID | READ status |
| --- | --- | --- |
| Campaign | 120247747556760571 | PAUSED |
| Adset | 120247747556830571 | CAMPAIGN_PAUSED |

CAMPAIGN_PAUSED — effective status при выключенной кампании. Он не доказывает
собственный configured status группы. Подмена на ACTIVE/PAUSED и реальное
включение кампании ради прохождения теста не разрешены.

## Следующий ручной тест

1. Открыть /manual-control, кабинет Valya Sergeeva / act_1047962734516123,
   уровень «Кампании», выбрать 120247747556760571 и открыть объект.
2. Старые requests не продолжать: срок истёк, исходный статус изменился.
   При новом DRAFT прежняя истёкшая команда обрабатывается существующим lifecycle.
3. Если текущий READ status всё ещё PAUSED, причина:
   «Локальная симуляция включения кампании, без рекламных изменений».
   Нажать «Подготовить включение», затем «Проверить команду».
4. При STATUS_STALE дождаться ближайшего штатного sync (обычно до 10 минут)
   и повторить «Проверить команду» до истечения 15 минут. Нажатие проверки само
   по себе не делает HTTP. При изменении статуса/expiry/другом блокере остановиться.
5. Когда local_allowed=true, подтвердить намерение и выполнить только локальную
   симуляцию. Ожидается SIMULATED, LIVE остаётся заблокирован, реклама не меняется.
6. Сообщить Request ID и SIMULATED либо точные blocking reasons.

Группу пока не тестировать повторными кликами: CAMPAIGN_PAUSED не проходит
допустимые исходные ACTIVE/PAUSED. Её локальный тест остаётся BLOCKED до
подтверждённого пригодного READ состояния/контракта собственного статуса.
Реальные PAUSE/ENABLE кампании ради этого не выполнять.

ACTIONS_ENABLED=false, LOCAL_READ_ONLY=true, AI_ENABLED=false,
AI_AUTOPILOT_ALLOWED=false. Meta disabled/disconnected revision 4.
ActionExecution=0; Advertising WRITE requests=0; Meta LIVE requests=0.
WRITE ID namespace, per-object permissions, ACK/UNKNOWN/authoritative readback
и одноразовый production dispatcher по-прежнему блокируют LIVE.

## Checkpoint 19.10.2026 16:41 МСК — адресный refresh подтверждён

Пользователь создал ENABLE_CAMPAIGN request
c3f77c65-f40e-47d9-a7ef-8df2a8d851b1 в 16:36:18, expiry 16:51:18 МСК.
Первый preflight в 16:36:25 корректно вернул STATUS_STALE: наблюдение 16:03.
Установленный worker read-only проверкой подтвердил refresh demand именно
для act_1047962734516123 / campaign / 120247747556760571.

Агент дождался существующего scheduled today-sync в 16:40; внеочередной
provider GET не запускался. Sync 779d9d07-8b5c-4616-ae83-a5395cb1c2ff:
16:40:00–16:40:08 МСК, succeeded, 3 физических READ attempts вместо прежних
двух. Campaign PAUSED, observed_at 16:40:00; quota 226 -> 229/800, cooldown нет.
Это подтверждает адресную ветку на реальном штатном READ; рекламных WRITE нет.

В 16:41:03 чистая read-only функция preflight дала local_allowed=true,
blocking_reasons=[], live_allowed=false. Остались только WRITE_DISABLED,
WRITE_CONTRACT_UNVERIFIED и WRITE_PERMISSION_UNVERIFIED для LIVE.
Request revision=4 и сохранённый прежний preflight не изменялись; переход,
подтверждение и симуляция агентом не выполнялись, provider HTTP этой проверки=0.
ActionExecution=0. Пользователю нужно повторно нажать «Проверить команду» для
сохранения новой проверки и затем подтвердить/выполнить только локальную симуляцию
до expiry. Ручной результат SIMULATED пока не подтверждён.

## Ручная приёмка 19.10.2026 16:42 МСК — ENABLE_CAMPAIGN ACCEPTED

Пользователь повторил preflight в 16:42:02, подтвердил локальное намерение в
16:42:19 и выполнил симуляцию в 16:42:20. PostgreSQL проверена агентом в 16:43:27:

- Request c3f77c65-f40e-47d9-a7ef-8df2a8d851b1, operation ENABLE_CAMPAIGN,
  terminal status SIMULATED, revision=10, result=LOCAL_SIMULATION_ONLY.
- Final preflight checked_at 16:42:20: local_allowed=true,
  blocking_reasons=[], live_allowed=false.
- Сохранённый READ-статус кампании 120247747556760571 остался PAUSED,
  observed_at 16:40:00. В audit есть CONFIRMED и SIMULATED; всего 10 событий.
- ActionExecution=0. Проверка агентом использовала только локальную БД;
  provider GET/WRITE для приёмки не запускались.

Сценарий пользовательской подготовки ENABLE_CAMPAIGN, восстановления freshness,
повторного preflight, подтверждения и локальной симуляции принят. Повторять этот
ручной сценарий не требуется. Это не ручная приёмка реального ENABLE или всех
остальных операций. Исходное 16:03 в captured card является историческим снимком
черновика; актуальная freshness проверялась по EntityCurrentState в 16:42.

Группа с CAMPAIGN_PAUSED остаётся BLOCKED по пригодности исходного состояния.
LIVE остаётся BLOCKED: точный WRITE ID binding, права на конкретный объект,
подтверждённая семантика ACK/UNKNOWN/authoritative readback и одноразовый
production dispatcher ещё не приняты. Подтверждение симуляции не разрешает
рекламный WRITE. Advertising WRITE requests=0.
