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
