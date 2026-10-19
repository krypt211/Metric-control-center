# MetricFlow synchronous pilot — acceptance, 19.10.2026

STATUS: SYNC_200 PATH READY LOCAL/MOCK. LIVE: BLOCKED.

## Что приближено к первому реальному тесту

Существующий ActionEngine теперь поддерживает синхронный single-attempt путь для
PAUSE_AD / ENABLE_AD, PAUSE_ADSET / ENABLE_ADSET, PAUSE_CAMPAIGN / ENABLE_CAMPAIGN.
Он использует тот же durable claim, encrypted WRITE handoff, credential revision,
свежий preflight, привязку аккаунта/объекта/оператора и deadline. Второй механизм
исполнения не создан. Путь пока строго MOCK_ONLY: изолированная БД, специальный
workspace и обязательный httpx.MockTransport. Production permit/dispatcher этим
изменением не реализован и не объявляется готовым.

Синхронная стратегия уменьшает необходимые компоненты первого пилота: один POST
без async=true, без job GET, без переключения на async и без повторного POST при
неопределённом результате. После ACK требуется отдельная сверка результата.
ACK не подтверждает configured/effective status и не создаёт MCC pause ownership.
При истечении окна без подтверждения результат становится UNKNOWN.

## Подтверждённая официальная спецификация

Источник: [OpenAPI MetricFlow](https://metricflowit.click/api/v1/openapi.json?lang=en),
[официальная документация](https://metricflowit.click/api/v1/docs).
Повторно получено 19.10.2026 в 14:16:42 UTC; version 1.0.0;
SHA256 `f52bc8ca0691fa0e2f2b5a5de06aa74a897546b88705ee16851859138a2f3327`.
Контракт совпадает с ранее проверенным. Context7 не нашёл этот продукт; результаты
для других Business API не использовались как подтверждение MetricFlow.

Подтверждены POST /api/v1/entities/{entity_id}/pause и /enable,
обязательное тело {"level":"campaign"|"adset"|"ad"}, async по умолчанию false,
ответ 200 EntityActionResponse: success, entity_id, message, необязательный job_id.
Для SYNC_200 адаптер требует success=true, совпадение entity_id и отсутствие job_id.
202, несовпадение ID, ошибочный/malformed ответ, 403/429/503 и timeout закрывают
попытку без resend. Полные error bodies и upstream message в audit не сохраняются.

entity_id в спецификации имеет тип string без подтверждённого namespace.
Связь provider ID из READ с WRITE entity_id остаётся неподтверждённой.
Общая инструкция [MetricFlow](https://metricflowit.click/docs) о правах при
подключении Facebook не подтверждает право текущего профиля на конкретный объект.

## Фактические проверки

- 22 новых targeted backend tests: PASS.
- Связанные backend regression tests: 266 PASS за 205.18 секунды (включая 22 новых).
- PostgreSQL: PASS на восстановленной БД
  mcc_integrations_controlled_20261016_211626, отдельная схема
  controlled_rehearsal_e2d492083e9b450cbda63df967fe7924.
- Восемь процессов: один claim / один mock POST; abrupt exit 17 -> UNKNOWN без resend.
- Три POST deadline/recovery сценария: PASS.
- Шесть SYNC_200 сценариев: по одному mock POST, ноль job GET,
  ACK не превращается в подтверждённое изменение; повторного POST нет.
- Итого 11 физических mock attempts; LIVE provider requests = 0.
- Сравнивается SHA реально импортированного engine.py и /app/services до создания
  тестовой схемы; запуск с PYTHONPATH=/app, без устаревшего site-packages.
- Ruff новых tests и PostgreSQL harness: PASS. В legacy engine остаются пять
  прежних lint findings, не относящихся к изменённым блокам.
- Frontend/API/UI не изменены; build/Playwright в этом этапе не запускались.
- Рабочие контейнеры на этом этапе не обновлялись; новый mock-only путь в UI не
  доступен и не является скрытой кнопкой боевого запуска.

Локальные исходные evidence сохранены в игнорируемом .tools/sync-pilot/.
Тестовые credentials синтетические; рабочий WRITE-ключ не расшифровывался.

## Рабочая система: измерено локально 19.10.2026, 14:18:31 UTC

PostgreSQL 0016_smart_control. MetricFlow READ enabled / healthy, revision 1,
last_success_at 14:10:07 UTC. WRITE encrypted_present=true, revision 1;
последняя проверка /me 18.10.2026 14:30:26 UTC: entities:write / active_paid.
Эта проверка устарела для будущего исполнения; её нельзя считать свежей.
Meta disabled / disconnected, revision 4. ActionExecution = 0.
Локальная квота MetricFlow: 244/800, blocked_until отсутствует; штатный READ может
изменять этот счётчик после снимка. Новых authenticated GET в этом этапе не было.

| Объект | Provider ID | Сохранённый статус | observed_at UTC |
| --- | --- | --- | --- |
| AD | 120247747556780571 | ACTIVE | 14:10:00 |
| Adset | 120247747556830571 | ACTIVE | 14:10:00 |
| Campaign | 120247747556760571 | PAUSED | 13:40:00 |

Кабинет Valya Sergeeva / act_1047962734516123. effective_status для этих объектов
в локальном снимке отсутствует. Статус кампании старше 15 минут; он не используется
для разрешения команды. Историческая симуляция ENABLE_CAMPAIGN / SIMULATED принята,
повторять её не требуется и превращать её в LIVE-разрешение нельзя.

## Первый кандидат и следующий ручной шаг

Кандидат первого отдельного теста: PAUSE_AD для выбранного пользователем
#70495691_EGR_Creo 06 / 120247747556780571. Текущий сохранённый статус AD ACTIVE;
родительская кампания PAUSED. Этот выбор не даёт разрешения на POST и не предполагает
включения кампании. Перед будущим запуском необходим новый актуальный снимок.

Следующий ручной шаг — установить, какой Facebook-профиль в MetricFlow подключил
act_1047962734516123, и проверить право этого профиля управлять рекламой кабинета
в настройках доступа Meta. Нужны имя профиля, вид права, точный account ID и время
сверки; ключи/токены не передавать, рекламные переключатели пока не нажимать.
Пользователь ответил: «Не знаю, где посмотреть». Следующий шаг: MetricFlow → FB Accounts / FB-аккаунты → раскрыть списки рекламных кабинетов у профилей → найти 1047962734516123. Сообщить все имена профилей, где он отображается. Эта связь ещё не подтверждает управляющее право; никакого разрешения на рекламные изменения не получено.

До первого контролируемого POST остаются:

1. Подтвердить WRITE entity_id namespace по официальному материалу/реализации или
   точному ответу провайдера. Письмо — один из источников, не обязательная форма.
2. Подтвердить identity/profile/account и право управления. entities:write и
   видимость аккаунта по READ не доказывают это право.
3. Зафиксировать исходные собственный и effective статусы. Для первого ручного
   пилота возможна отдельная сверка в Ads Manager до/после; она не заменяет
   авторитетный API readback для будущих автоматических правил.
4. Реализовать и проверить production single-use permit/dispatcher с приватным
   Credential Manager и привязкой точного объекта/операции/ревизий/окна.
   Существующий mock-only permit не снимает production gate.
5. Обновить scope проверкой Credential Manager и READ перед запуском; проверить
   квоту/отсутствие конфликтующих незавершённых команд.
6. Получить отдельное явное разрешение на одну точную операцию после готовности
   карточки; не разрешать ENABLE, parent actions или правила этой же карточкой.

План будущего запуска: один разрешённый synchronous POST; не более 30 секунд
на POST в пределах окна максимум 600 секунд, concurrency=1. При 401/402/403/429,
timeout, неожиданном ответе, несовпадении ID или неизвестном результате остановка
без resend и без автоматического восстановления. Сверка в Ads Manager с временем
и собственным/effective статусом, затем bounded READ diagnostic при отдельном
утверждённом бюджете. ENABLE после PAUSE — отдельная операция с новым разрешением.

ACTIONS_ENABLED=false
LOCAL_READ_ONLY=true
AI_ENABLED=false
AI_AUTOPILOT_ALLOWED=false

META LIVE REQUESTS THIS STAGE: 0
ADVERTISING WRITE REQUESTS THIS STAGE: 0

## Уточнение профиля — 19.10.2026, 17:31:58 МСК

После сообщения пользователя `739978 / Valya Sergeeva / act_1047962734516123`
выполнен ровно один документированный GET /api/v1/ad-accounts через действующее
READ-подключение revision 1. Использован существующий READ Credential Manager /
ProviderManager quota reserve, read_retries=0. WRITE vault не использовался.

Для exact account ID API подтвердил:

- internal_id: 739978 — внутренний ID строки кабинета MetricFlow;
- profile_id: 16192 — ID профиля в ответе MetricFlow, не доказательство Meta user ID;
- profile_name: Jacquelin Guadalupe Trejo Tovilla;
- is_active: true — признак аккаунта, не подтверждение управляющего права профиля.

Поиск имени профиля вручную больше не требуется. Следующий ручной шаг — посмотреть
доступ именно этого профиля к act_1047962734516123 в Meta. Нужны отображаемое право
управления/роль и время сверки, без изменения настроек доступа или рекламы.
Этот READ не подтверждает asset management permission, WRITE entity_id namespace
или авторитетность status readback; существующие LIVE blockers остаются.
Санитизированный результат: .tools/sync-pilot/account-profile-check.json (ignored).
За этот шаг: authenticated READ attempts = 1; advertising WRITE requests = 0.
