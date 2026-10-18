# Кампании, группы и объявления — локальная подготовка PAUSE / ENABLE

Дата: 18.10.2026, Europe/Moscow.
LOCAL MULTILEVEL STATUS CONTROL: READY FOR MANUAL LOCAL ACCEPTANCE; backend/frontend установлены.
LIVE WRITE: BLOCKED. Этот документ не разрешает рекламные операции.

## Подтверждённый контракт

Официальный OpenAPI повторно получен без credentials, с обычным browser
User-Agent. API version 1.0.0; полный SHA256
f52bc8ca0691fa0e2f2b5a5de06aa74a897546b88705ee16851859138a2f3327.
Это тот же контракт, что в предыдущем аудите; невозможность получить страницу
через web tool не означала отсутствия API.

Сохранены неизменённые операции и рекурсивно связанные schemas:
[official excerpt](METRICFLOW_STATUS_LEVELS_OPENAPI_2026-10-18.json).
EntityActionRequest.level документирует campaign, adset и ad.
POST /api/v1/entities/{entity_id}/pause и /enable описаны для всех трёх уровней.
Точный namespace entity_id остаётся неизвестным; READ ID не объявлен WRITE ID.
Тело запроса не расширено неописанными полями. Formal 202 response schema
по-прежнему отсутствует, job success не считается подтверждённым изменением.

## Что реализовано

Расширен существующий путь ActionEngine, без второго исполнителя и без миграции:

- PAUSE_CAMPAIGN / ENABLE_CAMPAIGN;
- PAUSE_ADSET / ENABLE_ADSET;
- PAUSE_AD / ENABLE_AD.

Каждый проходит DRAFT -> preflight -> локальное подтверждение -> SIMULATED.
Предусмотрены cancel, idempotency, конфликт незавершённой команды, revision,
проверка пользователя/workspace, account/provider/ID, kind и иерархии,
свежесть и неизменность исходного статуса. Simulation не изменяет статусы,
не создаёт ActionExecution и не конструирует provider client.

Новые parent-команды принимают только MetricFlow, явный entity_level и
соответствующий суффикс операции. Нельзя приложить AD RuleSimulation к parent
команде. Старые AD payload и fingerprint сохранены; существующие черновики
и idempotency keys не мигрировались. Вход external_id доступен как понятный
alias старого meta_ad_id. В provenance сохранены generic external_id/entity_level;
legacy meta_ad_id остаётся совместимым полем и не является доказательством WRITE ID.

Каталог /api/manual-control/ads получил необязательный level=ad|adset|campaign,
default=ad. Неверный уровень отвергается. Статистика/экономика агрегируются на
выбранном уровне, а AD-рекомендации не присваиваются кампаниям и группам.
Этот внутренний app route не является придуманным endpoint MetricFlow.

В /manual-control добавлен «Уровень управления». Для всех уровней используется
тот же выбор чекбоксами, заголовок текущей страницы и счётчик, что в статистике.
Смена уровня снимает выбор, очищает выбранную панель/причину; старый ответ не
подменяет новый каталог. Формы и IDs относятся к выбранному виду объекта.
Общая настройка колонок manual_ad сохраняется, чужие presets не переписываются.

Typed status adapter принимает level для документированного тела на трёх уровнях;
default=ad сохраняет старых callers. Проверены только mock transport запросы.
Ни hard gate, ни глобальные флаги, ни routes выполнения не включены.

## Точная граница готовности

| Уровень | Локальный lifecycle | Mock POST wire | Production dispatcher / authoritative readback | LIVE |
| --- | --- | --- | --- | --- |
| AD | Реализован | Реализован | Доступен AD-only mock job/readback; LIVE не принят | BLOCKED |
| Adset | Реализован | Реализован | Production не реализован; AD-only observer не объявлен parent-ready | BLOCKED |
| Campaign | Реализован | Реализован | Production не реализован; AD-only observer не объявлен parent-ready | BLOCKED |

Глобальный контрактный gate остаётся безусловно закрытым, включая случай
изменённых ACTIONS_ENABLED/LOCAL_READ_ONLY. Encrypted credential factory не
открывает ключ до gate. Worker/scheduler не включаются, AD-правила не превращены
в автоматические команды родителей. Выбор нескольких строк не запускает bulk WRITE.

## Следующий ручной тест — только локальный

1. Ctrl+F5 на /manual-control, кабинет Valya Sergeeva / act_1047962734516123.
2. Уровень «Кампании», выбрать чекбоксом 120247747556760571 и открыть объект.
3. Заполнить причину «Проверка локальной подготовки кампании, без рекламного WRITE».
4. При ACTIVE подготовить отключение; при PAUSED — включение. Неподтверждённый
   или иной статус не заменять вручную и не обходить отключённую кнопку.
5. «Проверить команду»: LIVE должен быть заблокирован. Если локальная симуляция
   допустима, подтвердить намерение и выполнить симуляцию. Итог SIMULATED,
   фактический статус должен сохраниться. Если есть блокер — сообщить его;
   не менять expected status, часы, флаги или TTL ради продолжения.
6. Повторить для уровня «Группы объявлений», ID 120247747556830571.
7. AD-сценарий уже принят; повторные одинаковые клики для него не требуются.

У родительских статусов существующий ingestion cache может достигать 3600 секунд,
а manual freshness limit остаётся 900 секунд. Поэтому STATUS_STALE для parent
может быть корректным ожидаемым результатом. Кэш, квота и TTL не ослаблялись;
текст «Обновить из БД» не означает свежий provider GET. Это отдельное условие
перед LIVE, а не основание объявить effective/configured state подтверждённым.

## Когда возможны реальные переключения

После локальной ручной приёмки нужны обязательные сведения о WRITE ID namespace,
правах текущего подключения на конкретный объект, ACK/UNKNOWN и надёжном readback.
Затем завершается и проверяется production одноразовый permit/dispatcher.
Агент не заменяет эти сведения предположениями или checkbox подтверждения.

Предлагаемый порядок первого LIVE теста: один AD PAUSE -> отдельный AD ENABLE;
затем один adset PAUSE/ENABLE; затем одна campaign PAUSE/ENABLE. Каждый запуск
требует отдельного разрешения, проверенного исходного состояния, ограниченного
числа попыток, остановки при неизвестном результате и проверки последствий для
дочерних объектов. Включение родителей может затрагивать множество AD; текущий
выбор AD не считается разрешением менять кампанию. До этих условий дата LIVE
теста не назначается. Реальные проверки Rule Engine следуют после ручного пути.

## Фактические проверки и установка

Проверка установки: 18.10.2026 19:14:10 UTC / 22:14:10 МСК.

- Backend: 147 PASS — multilevel manual, прежний manual lifecycle и typed
  MetricFlow WRITE contract; отдельно 99 PASS — job observation, readback и
  Smart Rules regression. Это два запуска, не единый полный backend suite.
- PostgreSQL на изолированной восстановленной БД: все шесть локальных операций
  SIMULATED; гонки одинакового ключа, конфликтов и подтверждений — по 8 callers.
  Provider HTTP = 0; fixture workspace очищен, рабочая БД не использовалась.
- Frontend: 36 unit PASS; TypeScript PASS; production Next build PASS.
- Playwright: 9 API/UI cases PASS в изолированной БД; отдельный browser-only mock
  case PASS, прошёл все шесть комбинаций уровня/операции без сохранения команд.
  В общем запуске эти девять прошли, mock case потребовал исправления fixture
  external_id и отдельного повторного запуска. Первоначально оба новых cases
  выявили отсутствие точного accessible label у нового select; aria-label
  исправлен в продукте. Единый чистый запуск 10/10 не заявляется.
- Ruff check изменённых Python-модулей PASS; format --check четырёх файлов PASS
  (manual_schema, writer, новый multilevel test, PostgreSQL script).
  Проверка форматирования всего старого репозитория не заявляется.
- Локальный security scan PASS. Dependencies/lock не менялись; backend image
  собран обновлением source layers поверх проверенного текущего image без сети,
  совпадение pyproject/requirements.lock с running backend проверено.
  Frontend Docker build PASS, проверен тем же изолированным UI.

Свежий защищённый pg_dump создан перед установкой: 10 520 018 bytes,
SHA256 64f7847903e921a2e59e4e1aebe66c174203cbc861874f02b4b1ca45110804e7.
Checksum и pg_restore --list PASS; ACL — владелец и SYSTEM. Это проверка
каталога архива, новое полное восстановление этого backup не заявляется.
Для PostgreSQL/browser приёмки использована ранее восстановленная изолированная БД.

Установлены только backend/frontend. Health live/ready и /login — HTTP 200.
Остальные пять рабочих контейнеров MCC (worker, scheduler, credential-manager,
PostgreSQL, Redis) имеют прежние IDs. Изолированные UI backend/frontend остановлены;
БД, volumes и прежние images сохранены. Рабочие migrations не запускались,
revision 0016_smart_control. Штатные backend/frontend image tags обновлены только
после health и integrity checks; rollback по прежним image IDs сохранён.

Все 14 защищённых таблиц совпали по количеству строк и digest до/после установки:
users, user_sessions, economics_profiles/assignments/grants, rules, rule_versions,
rule_grants, action_requests/executions/logs, provider_credentials,
write_credential_states/audit. SHA256 .env неизменен. Рабочие provider READ факты
не замораживались и могли обновляться обычной синхронизацией; их исходные
статусы/времена никогда не подменялись ради теста.

На момент проверки MetricFlow READ локально healthy, enabled, revision 1,
last_success_at 2026-10-18T19:10:03.197433Z. Дополнительных provider probes для
этой проверки не выполнялось. Meta disconnected, disabled, revision 4.
WRITE scope check 17:30:26 МСК является историческим, свежим сейчас не объявлен.

Подтверждены runtime flags backend:
ACTIONS_ENABLED=false, LOCAL_READ_ONLY=true, AI_ENABLED=false,
AI_AUTOPILOT_ALLOWED=false. .env не менялся. Meta permit ID и подтверждённая
разрешающая версия не устанавливались. Rule Engine не активирован для LIVE.
ActionExecution=0. Advertising WRITE requests=0; Meta LIVE requests=0.

Результат: следующий шаг — ручная локальная приёмка кампании и группы по разделу
выше. LIVE AD/ADSET/CAMPAIGN остаются BLOCKED, автоматические рекламные действия
не разрешены. Реальная остановка/включение не являются частью этой проверки.
