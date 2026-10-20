# MetricFlow WRITE ID decision — 20.10.2026

STATUS: EXTERNAL CLARIFICATION REQUIRED. LIVE BLOCKED.

## Выполненная проверка

20.10.2026 в 00:06 МСК повторно получены только публичные официальные материалы:

- https://metricflowit.click/api/v1/openapi.json?lang=en — HTTP 200, version 1.0.0,
  102 paths, SHA256 f52bc8ca0691fa0e2f2b5a5de06aa74a897546b88705ee16851859138a2f3327.
- https://metricflowit.click/api/v1/docs — HTTP 200, Scalar UI с OpenAPI.
- https://metricflowit.click/docs — HTTP 200, руководство и перечень Business API.

OpenAPI совпадает с проверенным 19.10.2026. Context7 не индексирует этот MetricFlow:
результаты для других Business API не использованы. Web reader не открыл API docs,
поэтому JSON и HTML получены непосредственно публичным HTTPS GET без API key.
Сырые документы, URL, время и SHA сохранены в ignored .tools/write-id-audit-20261020/.

## Что установлено

| Проверка | Результат |
| --- | --- |
| POST /api/v1/entities/{entity_id}/pause и /enable | Документированы |
| Path entity_id | string; без description/example о namespace |
| EntityActionRequest | Обязательное поле level, для AD значение ad |
| AdCreativeInfo.ad_id из READ | Явно описан как Facebook Ad ID |
| Равенство READ ad_id и WRITE entity_id | Явно не установлено опубликованным контрактом |
| BulkStatusActionRequest.entities | entity_id + level, без пояснения namespace |
| Неизменяющий validate/dry-run/resolve endpoint для WRITE ID | Не найден среди опубликованных routes |
| Руководство Business API | Перечисляет pause/enable/budget; не уточняет ID |

Тот факт, что READ возвращает Facebook ID, не доказывает контракт отдельного WRITE path.
Наличие scope и пользовательское подтверждение прав не решают этот вопрос.
Authenticated READ по существующим маршрутам не является проверкой корректности WRITE ID.
Пробный POST, неизвестный GET/endpoint или клиентский флаг для обхода не использованы.

## Единственное необходимое уточнение по ID

Готовый вопрос в чат поддержки или автору официальной спецификации:

> Для POST /api/v1/entities/{entity_id}/pause и /enable при body {"level":"ad"}
> параметр entity_id — это Facebook Ad ID, тот же ad_id из GET /api/v1/insights
> и AdCreativeInfo.ad_id, или внутренний ID MetricFlow? Если требуется другой ID,
> укажите документированный READ endpoint и поле, из которого его получить.

Вопрос подготовлен, но никому не отправлен. Подойдёт проверяемое подтверждение от
провайдера либо дополнение официальной документации. Формальное письмо не обязательно.
Ключи и токены для этого вопроса не нужны; личные рекламные IDs не включены.

## Что после ответа

При однозначном подтверждении ID завершить серверную приёмку подтверждённых evidence,
учитывая USER_ATTESTED права профиля Jacquelin Guadalupe Trejo Tovilla; повторный общий
вопрос о наличии прав пользователю не нужен. Не выдавать USER_ATTESTED за API review.
Затем проверить и развернуть закрытый single-use путь без ослабления gates, получить
свежие READ/WRITE checks и own/effective baseline, подготовить точную карточку одного
PAUSE_AD для кабинета act_1047962734516123 / AD 120247747556780571.
Сама карточка не разрешает POST: требуется отдельное явное разрешение пользователя.
Включение, кампании, группы и автоматические правила не входят в эту первую попытку.

## Границы текущего шага

Только чтение документации и изменение отчётов. Код, credentials, подключения и
четыре защитных флага не менялись; приложения не развёртывались. Новые backend/Playwright
тесты не запускались, поскольку реализация не менялась. Проверены парсинг OpenAPI,
равенство SHA предыдущему снимку и определения соответствующих полей/routes.

Public documentation GET: 3. Authenticated provider API requests: 0.
Meta API requests: 0. Advertising WRITE requests: 0.
ACTIONS_ENABLED=false; LOCAL_READ_ONLY=true; AI_ENABLED=false; AI_AUTOPILOT_ALLOWED=false.

## Повторное подтверждение по запросу пользователя — 20.10.2026

Проверка выполнена по команде «подтверждай», без рекламного POST. Свежий EN OpenAPI
получен в 09:10:48 UTC / 12:10:48 МСК; он полностью совпадает с прежним SHA256
f52bc8ca0691fa0e2f2b5a5de06aa74a897546b88705ee16851859138a2f3327.
Проверены также RU OpenAPI, публичное руководство и отрисованный официальный changelog.

Дополнительные официальные источники:

- [RU OpenAPI](https://metricflowit.click/api/v1/openapi.json?lang=ru), HTTP 200,
  SHA256 07750aff409c4b22405c21645a6a1b682ce5d55565aa2dc5227a1e5c7b417c24.
- [Changelog](https://metricflowit.click/changelog), HTTP 200; прочитан после загрузки
  JavaScript в отдельном анонимном Edge. Только same-origin GET, без ввода данных,
  без ключей, без аккаунта MetricFlow. Внешний запрос заблокирован.

Официальная запись changelog от 14.04.2026 описывает появление управления статусом
и бюджетом через Public API и исправления WRITE-операций. Это дополнительное
подтверждение существования API-функции. Оно не доказывает успешную работу текущего
ключа на выбранном AD и не определяет namespace параметра WRITE entity_id.

Результаты точного сравнения:

| Проверка | Статус |
| --- | --- |
| PAUSE/ENABLE через Public API | CONFIRMED_DOCUMENTED |
| Body для AD: level=ad | CONFIRMED_DOCUMENTED |
| READ AdCreativeInfo.ad_id — Facebook Ad ID | CONFIRMED_DOCUMENTED |
| WRITE entity_id — Facebook Ad ID | UNVERIFIED |
| WRITE entity_id — внутренний ID MetricFlow | UNVERIFIED |
| EN и RU path parameter entity_id | Только string / Entity Id, без description/example |
| Документированный GET resolver под /entities/ | Отсутствует в проверенных 102 paths |
| Changelog о mapping entity_id между ad/adset/campaign | Относится к scope правил; не является контрактом pause/enable |

Вычисленные schema assertions прошли для обоих языков и обоих status endpoints.
Обычные authenticated READ не выполнялись: они не устраняют найденную неясность,
поэтому квота подключения на эту проверку не тратилась. Пробный рекламный POST
не использован как способ выяснения namespace.

Первый GET RU OpenAPI вернул 403; один повтор с тем же User-Agent, что у успешной
EN проверки, дал 200. Всего прямых публичных GET: 6 (5 успешных, 1 HTTP 403), плюс
анонимные GET ресурсов/changelog браузером. /api/auth/get-session был анонимным
служебным запросом публичной страницы; Business API credential туда не передавался.
Никакие сообщения провайдеру не отправлены. Context7 не нашёл именно этот MetricFlow;
результаты для Click и других несвязанных продуктов не использованы.

Сохранены локальные evidence в ignored .tools/write-id-confirmation-20261020/:
sources.json, EN/RU JSON, guide-visible.txt, changelog-browser.txt/json,
verification.json. В рабочую БД не внесено принятого contract_review:
accepted evidence=0, LIVE_SINGLE_OPERATION permits=0, ActionExecution=0.
Эти значения проверены локальными SELECT. .env SHA совпадает с прежним снимком;
ACTIONS_ENABLED=false, LOCAL_READ_ONLY=true, AI_ENABLED=false,
AI_AUTOPILOT_ALLOWED=false. Код, контейнеры и подключения не менялись.
Backend-тесты не перезапускались: изменён только этот отчёт; выполнены schema
assertions и анонимная браузерная проверка официального changelog.

Итог: API-функция подтверждена официальными источниками; точный WRITE namespace
остаётся неподтверждённым. Оснований самостоятельно записывать accepted review нет.
Нужно provider-authored пояснение из раздела «Единственное необходимое уточнение по ID».
После него действуют scoped review, свежие scope/status checks и отдельное разрешение
на один рекламный POST. Текущая команда пользователя не является таким разрешением.

WRITE ID CONTRACT: UNVERIFIED.
FIRST CONTROLLED AD POST: BLOCKED.
Authenticated Business API requests: 0. Meta API requests: 0.
Advertising WRITE requests: 0.

## Дополнение: ограниченный эксперимент

Последующий выбор пользователя разрешил только подготовку экспериментального PAUSE_AD
с явно неподтверждённым namespace. Это отдельный USER_REQUESTED_EXPERIMENT,
не provider-authored подтверждение и не accepted production contract.
Создан локальный DRAFT без LIVE permit. Подробности и отдельный порядок согласования:
[Experimental preparation](METRICFLOW_EXPERIMENTAL_PILOT_PREPARATION.md).
WRITE ID CONTRACT остаётся UNVERIFIED; рекламных WRITE запросов 0.
