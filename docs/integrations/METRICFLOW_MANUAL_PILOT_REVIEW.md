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

## Выбор AD без обязательного поиска — 2026-10-18

На /manual-control добавлен отдельный список «Объявление» на существующем
SearchableSelect и GET /api/smart-rules/catalog/search?kind=ad. После выбора
кабинета список открывается без поискового текста, показывает названия и IDs,
поддерживает страницы по 20 объектов и учитывает выбранные кампанию/группу.
Общий компонент выбора и Phase 3.1 не перерабатывались.

Выбор получает локальный снимок через существующий GET /api/manual-control/ads
и сопоставляет source_id и provider. Он не ограничен текущими 100 строками таблицы.
Название AD/статус берутся из локального снимка; рекламный API не вызывается.
Выбор строки таблицы и текстовый поиск сохранены. После выбора открывается
панель AD с карточкой ручной проверки и полем причины локальной команды.

Смена кабинета сбрасывает зависимые кампанию/группу и поиск таблицы; смена
кампании сбрасывает группу. Смена кабинета, кампании или группы снимает выбор AD.
Поздние ответы загрузки старого выбора игнорируются. Изменения выбора выполняют
только локальные GET и не создают ActionRequest/ActionExecution.
Проверки текущего изменения: TypeScript PASS; frontend unit 36/36 PASS;
Next production build PASS; Docker frontend build PASS; финальный Playwright
manual-control 7/7 PASS на изолированной восстановленной БД. Новый сценарий
проверяет открытие списка с пустым поиском, постраничный выбор, открытие панели,
GET-only выбор и отклонение запоздавшего ответа после снятия выбора кабинета.
Backend не менялся; отдельный backend unit rerun для этого UI-изменения не выполнялся.

Установлен только frontend; /login HTTP 200. Остальные шесть рабочих контейнеров
и SHA256 .env не изменились. Revision 0016_smart_control сохранена, миграции не
запускались. Старый image и rollback override сохранены, штатный image tag обновлён.
Изолированные backend/frontend остановлены; БД/volumes не удалялись. В рабочей БД
ActionExecution=0. ACTIONS_ENABLED=false; LOCAL_READ_ONLY=true; AI_ENABLED=false;
AI_AUTOPILOT_ALLOWED=false. Meta LIVE и рекламные WRITE не выполнялись.

Ручная проверка интерфейса: Ctrl+F5 на /manual-control → кабинет → «Объявление»
→ выбор строки в выпадающем списке (при необходимости «Далее») → панель AD.
Вводить название или ID в поиск необязательно. Статус AD, отключённого по
расписанию, сам по себе не разрешает ENABLE; это только выбор для просмотра.

## Чекбокс в основной колонке — 2026-10-18

На /manual-control в закреплённой колонке названия AD добавлен чекбокс.
Установка отметки выбирает одно объявление и открывает существующую панель.
Снятие отметки убирает выбор и панель; выбор другого AD снимает предыдущую
отметку. Нажатие названия, кнопка строки и выпадающий список используют то же
состояние выбора. Чекбокс содержит доступное имя с названием и Ad ID.

StatisticsTable получил необязательный nameControl; существующий механизм
массового выбора Phase 3.1 и его отдельная колонка не менялись. Контрол внутри
колонки названия сохраняет закрепление при горизонтальной прокрутке. Выбор
выполняется локально, без создания команды и без рекламных запросов.

Проверки: TypeScript PASS, frontend unit 36/36 PASS, production build PASS,
Docker build PASS, Playwright manual-control 7/7 PASS. В браузере проверены
выбор чекбоксом, снятие отметки/панели, переключение между двумя AD с единственной
отметкой, синхронизация с выбором по названию и видимость при горизонтальной
прокрутке. Для выбора и карточки зафиксированы только GET; список команд до/после
совпадает. Тесты выполнялись на изолированной восстановленной PostgreSQL.

Установлен только frontend; /login HTTP 200. Остальные шесть рабочих контейнеров
и SHA256 .env не изменились. Revision 0016_smart_control, migrations не запускались;
ActionExecution=0. Прежний frontend image/rollback сохранены. Изолированные UI
сервисы остановлены без удаления БД/volumes. Backend код не менялся.
ACTIONS_ENABLED=false; LOCAL_READ_ONLY=true; AI_ENABLED=false;
AI_AUTOPILOT_ALLOWED=false. Advertising WRITE requests=0, Meta LIVE не запускался.

Ручная проверка: Ctrl+F5 на /manual-control → кабинет → квадрат слева от названия
AD в основной колонке. После отметки открывается панель выбранного объявления.
Снятие отметки закрывает её; выбор другого AD переносит отметку на новую строку.

## Единый выбор чекбоксами — текущая реализация, 2026-10-18

По уточнению пользователя /manual-control переведён на стандартный selection
компонента StatisticsTable, как в статистике: отдельная закреплённая колонка
слева, выбор нескольких строк, общий чекбокс текущей страницы, indeterminate
для частичного выбора. Прежний nameControl внутри названия и его CSS удалены.
StatisticsTable и globals.css совпадают с версией до добавления nameControl;
реализация Phase 3.1 не переписывалась.

Выбранные AD хранятся по внутреннему ID в локальном состоянии. Отметки сохраняются
при поиске, фильтре статуса и перелистывании; смена кабинета/кампании/группы
сбрасывает их. Действует существующий предел 200 выбранных объектов.
Общий чекбокс затрагивает текущую страницу. Счётчик и «Очистить выбор» показывают
и снимают весь набор, включая временно скрытые строки.

Отметка строки больше не прокручивает экран к панели и не открывает её.
Кнопка «Открыть выбранное объявление» доступна при одной отметке; название строки
и выпадающий список по-прежнему открывают конкретный AD. Отметки и открытая
панель имеют разное назначение, как в статистике: очистка отметок не закрывает
уже открытую панель. Все ручные команды остаются индивидуальными и локальными.
Массовые рекламные операции не добавлены. Выбор не создаёт ActionRequest,
ActionExecution, provider HTTP или разрешение на LIVE.

Финальная проверка: TypeScript PASS, frontend unit 36/36 PASS, production Next
build PASS, Docker build PASS, Playwright manual-control 8/8 PASS (1.3 min).
Новый сценарий подтвердил отдельную первую колонку, две одновременные отметки,
частичный общий флажок, сохранение при пустом результате поиска, выбор/снятие
текущей страницы, закрепление при горизонтальной прокрутке, очистку набора
и открытие одного AD отдельной кнопкой. Стандартный выбор и просмотр не отправили
POST/PUT/DELETE в manual-control; список ActionRequest до/после совпал.

Установлен только frontend. /login HTTP 200; остальные шесть рабочих контейнеров
и SHA256 .env не изменились. Revision 0016_smart_control; миграции не запускались.
ActionExecution=0. Штатный frontend image tag обновлён; прежний image и rollback
сохранены. Изолированные backend/frontend остановлены без удаления БД/volumes.
Backend код не менялся. ACTIONS_ENABLED=false; LOCAL_READ_ONLY=true;
AI_ENABLED=false; AI_AUTOPILOT_ALLOWED=false. Advertising WRITE requests=0;
Meta LIVE не запускался.

Ручная проверка: Ctrl+F5 на /manual-control → выбрать кабинет → отметить строки
в первой колонке или общий флажок заголовка. Отметки не перемещают страницу.
Для карточки оставить одну отметку и нажать «Открыть выбранное объявление»
либо нажать название нужного AD. «Очистить выбор» снимает все отметки.

## Checkpoint 18.10.2026 — ручная сверка принята, WRITE scope обновлён

Пользователь в 17:28 подтвердил AD включён, группа включена, кампания выключена,
доставка неактивна; право управления в MetricFlow не видно. В 17:30:26 МСК
Credential Manager проверил сохранённый WRITE credential одним GET /me:
SCOPES_VERIFIED, entities:write, active_paid; READ healthy, revisions 1/1 сохранены.
Квота 237 -> 238/800. Это снимает блокер устаревшего scope check на момент проверки,
но не подтверждает object permissions/WRITE ID/authoritative readback и не разрешает
LIVE. Подробности: [checkpoint](METRICFLOW_PILOT_MANUAL_CHECKPOINT_2026-10-18.md).
