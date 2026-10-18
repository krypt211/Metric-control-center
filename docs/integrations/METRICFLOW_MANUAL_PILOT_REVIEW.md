# MetricFlow — manual pilot review without a provider letter

Дата: 18.10.2026, Europe/Moscow.
MANUAL READ-ONLY REVIEW: READY. Phase 4B: PARTIAL. LIVE WRITE: BLOCKED.

## Что сделано

В существующий /manual-control добавлена карточка ручной сверки выбранного AD.
Она доступна администратору и оператору с действующим grant. Backend проверяет
права по PostgreSQL, workspace, provider=metricflow и kind=ad. VIEWER и оператор
без grant получают 403; чужой workspace/не-AD/Meta не перечисляются.

GET /api/manual-control/pilot-review/{entity_id}?operation=PAUSE_AD|ENABLE_AD
возвращает только разрешённые локальные поля. Ответ Cache-Control: no-store.
Next proxy допускает для этой ветки только GET. POST не является способом
создать разрешение: backend возвращает 405, proxy также отклоняет unsafe method.

Карточка показывает account/AD/adset/campaign IDs, timezone, сохранённый статус,
effective_status если известен, время наблюдения, READ/WRITE revisions,
свежесть cached WRITE scope, незавершённые команды и ручные шаги.
Чтение выполняет SELECT; не открывает vault, не создаёт ActionRequest/permit,
не обращается к MetricFlow/Meta и не расходует provider quota.
Raw permissions, ciphertext, token, fingerprint не возвращаются.

execution_allowed=false остаётся неизменным даже при смене системных флагов.
Нет кнопки LIVE исполнения, подтверждения WRITE или checkbox обхода контракта.
При смене операции/AD старые асинхронные ответы не заменяют актуальную карточку.

## Официальные источники и предел доказательств

Повторно прочитаны публичные официальные страницы:
- https://metricflowit.click/api/v1/docs
- https://metricflowit.click/api/v1/openapi.json?lang=en
- https://metricflowit.click/docs

Описанные PAUSE/ENABLE POST, body level=ad, async=true и GET job сохранены.
Общая документация не добавила точного namespace entity_id, отдельной проверки
asset permission или authoritative per-AD readback. Контракт не повышен до
VERIFIED, ActionSafetyGate не изменён. Письмо провайдеру не является обязательным
этапом этой ручной сверки. В Context7 самого MetricFlow не найдено; сторонняя
Sitejabber API и dbt MetricFlow не использовались вместо официального источника.
FastAPI query/error contracts и React async cleanup проверены по official docs
через Context7; новых зависимостей нет.

Проверка видимых данных в MetricFlow/Ads Manager помогает подтвердить identity,
исходное состояние и контекст доступа. Она не доказывает API asset permission,
не заменяет namespace WRITE ID и не делает cache timestamp авторитетным.
Неизвестные требования остаются BLOCKED; письмо — лишь один из способов
получить evidence. Ручной ответ не снимает server-side gates автоматически.

## Измеренное состояние выбранного объявления

Карточка из рабочей PostgreSQL, READ ONLY, 18.10.2026 08:45:15 UTC
(11:45:15 МСК):

| Поле | Значение |
| --- | --- |
| Cabinet | Valya Sergeeva / act_1047962734516123 |
| AD | #70495691_EGR_Creo 06 / 120247747556780571 |
| AdSet | 120247747556830571 |
| Campaign | 120247747556760571 |
| Timezone | America/Los_Angeles |
| Сохранённый статус | CAMPAIGN_PAUSED |
| Отдельный effective_status | UNKNOWN / null |
| READ revision | 1 |
| WRITE revision | 1 |
| Последняя WRITE check | 12.10.2026 22:04:27 UTC; устарела |
| Scope evidence fresh | false |
| Execution allowed | false |

В raw выбранного EntityCurrentState есть только status=CAMPAIGN_PAUSED.
Это не доказательство собственного configured_status AD. В предыдущем замере
был ACTIVE; агент не отправлял команд изменения статуса. Первопричина внешнего
изменения не установлена и не приписывается агенту или правилу.
READ healthy, mapping/hierarchy подтверждены локально, pending action нет.
Исходное состояние не соответствует PAUSE из ACTIVE; ENABLE из собственного
PAUSED тоже не подтверждён. Кампания/группа автоматически не включаются.

## Автоматические проверки

- Backend targeted manual-control/auth/API: 101 PASS (142.37 s).
- Финальный unit набор карточки после нормализации raw status: 18 PASS,
  25 deselected (уже проверенные inherited auth/API cases); 19.86 s.
  Наборы пересекаются, результаты не суммируются.
- Проверено: только SELECT; vault/HTTP запрещены mocks; stale scope и status;
  разные роли/grants; чужой workspace; no secret projection; unexpected raw
  effective_status; флаги не создают разрешение; отсутствие execution/draft.
- Frontend TypeScript PASS, 36/36 unit PASS, production build PASS.
- Playwright: 6/6 PASS, 1.1 min, на восстановленной isolated БД и отдельном UI.
  Полный manual flow, grants, rule handoff и новая карточка с delayed-response
  race приняты. После review список команд точно совпадает с исходным.
- Ruff check: PASS для нового сервиса, новых tests и изменённого API.
  Ruff format --check: PASS для новых Python файлов.
- Рабочий локальный GET без session: 401, данные не раскрыты.

## Docker и локальное развёртывание

Frontend Docker build PASS. Прямой backend build с повторной установкой пакетов
завершился ошибкой; fresh dependency rebuild не объявляется принятым.
Release backend собран без сети поверх ранее проверенного
metric-control-center-readback-final:local: SHA256 pyproject.toml и requirements.lock
в base image полностью совпадают с текущими файлами; затем скопированы текущие
backend/services. Зависимости не заменены, lock/проверки не ослаблены.
Этот source-layer Docker build PASS; тот же код проверен на PostgreSQL.

Обновлены только локальные backend/frontend. Штатные локальные image tags
указывают на проверенные release images; прежние image IDs сохранены для отката.
Worker, scheduler, credential-manager, PostgreSQL, Redis не пересоздавались.
Никакие migrations не запускались: revision 0016_smart_control сохранена;
старый migrate container Exited(0), не запускался повторно.

Свежий custom SQL backup: 9778896 bytes, SHA256 проверен, archive catalogue PASS.
Новый каталог backup имеет ACL только владельца/SYSTEM. Старые backup/volumes
не удалялись. Рабочая БД не восстанавливалась. Полная новая restore-проверка этого
дампа не выполнялась: это обновление кода без schema/data migrations.
До/после deployment совпали 14 защищённых таблиц: users/sessions, экономика,
правила, actions/logs, READ credentials и WRITE state/audit. .env checksum совпал.

Health backend и frontend PASS. В рабочей БД ActionExecution=0.
Изолированный UI после тестов остановлен; его БД/volumes оставлены.

## Следующая ручная проверка — без изменения рекламы

1. Открыть http://127.0.0.1:3000/manual-control и выбрать кабинет Valya Sergeeva.
2. В поиске найти AD 120247747556780571, нажать название объявления.
3. Нажать «Подготовить ручную проверку пилота» и сверить ID в карточке.
4. В MetricFlow открыть этот кабинет/AD. В Ads Manager открыть те же IDs.
   Только посмотреть положение переключателей AD, группы и кампании, а также
   сообщения о доставке. Ничего не включать/отключать и не нажимать Apply.
5. Сообщить: ID кабинета и AD; собственный статус/переключатель AD;
   статус группы и кампании; сообщение о доставке; время сверки;
   видимую роль/право управления в MetricFlow или «не видно».
   Ключи, токены, .env и приватные данные аккаунта не нужны.

Это проверка текущего исходного состояния, а не PAUSE/ENABLE pilot.
Из-за CAMPAIGN_PAUSED сначала требуется понять, какой именно объект уже остановлен
и остаётся ли выбранный AD подходящим для согласованного теста. Другой AD агент
самостоятельно не выбирает. Затем проверяются оставшиеся contract/permission
сведения и завершается production permit/dispatcher. Один рекламный WRITE
возможен только после отдельного разрешения на конкретную операцию.

ACTIONS_ENABLED=false; LOCAL_READ_ONLY=true; AI_ENABLED=false;
AI_AUTOPILOT_ALLOWED=false. Meta LIVE не запускался. Advertising WRITE requests=0.

## Исправление видимости кнопки — 2026-10-18

Пользователь подтвердил страницу /manual-control. Причина: панель выбранного AD
располагалась после всей таблицы, а выбор строки не перемещал к ней экран.
Название кнопки присутствовало и в ранее установленном frontend.

При нажатии на название AD или «Подготовить команду» экран теперь прокручивается
к панели «Выбранное объявление», а фокус переносится в эту панель. Повторный выбор
того же AD также возвращает к панели. Кнопка «Подготовить ручную проверку пилота»
остаётся в существующей карточке; права доступа и READ-only контракт не менялись.

Проверки: TypeScript PASS, production Next build PASS, Docker frontend build PASS.
Playwright manual-control: 6/6 PASS на изолированной восстановленной PostgreSQL.
Проверены повторный выбор AD после загрузки полной таблицы, фокус панели,
видимость кнопки в viewport, GET-only карточка, неизменность списка команд
и защита от устаревшего ответа при смене операции.

Установлен только frontend. HTTP /login: 200. Остальные шесть рабочих сервисов
не пересоздавались, SHA256 .env совпал; миграции не запускались. Штатный frontend
image tag обновлён, прежний image и rollback override сохранены локально.
Изолированные backend/frontend после проверки остановлены без удаления volumes.
В рабочей БД ActionExecution=0. Рекламных WRITE и Meta LIVE в этой задаче не было.
ACTIONS_ENABLED=false; LOCAL_READ_ONLY=true; AI_ENABLED=false;
AI_AUTOPILOT_ALLOWED=false.

Для проверки: обновить /manual-control через Ctrl+F5, выбрать Valya Sergeeva,
найти AD 120247747556780571 и нажать на его название. В открывшейся панели нажать
«Подготовить ручную проверку пилота». Это только просмотр локальной карточки,
без отправки команды рекламному провайдеру.
