# Контракт MetricFlow

Проверено по публичной [документации](https://metricflowit.click/docs)
6 октября 2026 года. Живые запросы не выполнялись.

Пути и необходимые scopes опубликованы. Полные JSON-схемы ответов,
параметры пагинации, тело бюджета и единицы сумм в доступном разделе
не описаны достаточно для окончательного бизнес-контракта.

Base URL: `https://metricflowit.click/api/v1/`.
Авторизация: `Authorization: Bearer <полный API key>`. Клиент принимает префиксы `mfk_` и `mf_live_`; префикс не определяет права ключа.

| Метод коннектора | Путь после base URL |
|---|---|
| get_me / get_usage | GET me / usage |
| get_accounts | GET ad-accounts |
| get_summary / get_insights | GET summary / insights |
| get_campaigns | GET ad-accounts/{act_id}/campaigns |
| get_adsets | GET ad-accounts/{act_id}/adsets |
| get_ads | GET ad-accounts/{act_id}/ads |
| get_daily | GET ad-accounts/{act_id}/daily |
| get_creatives | GET ad-accounts/{act_id}/creatives |
| get_tracker_stats | GET ad-accounts/{act_id}/tracker |
| get_breakdowns | GET ad-accounts/{act_id}/breakdowns |
| get_rules / get_bundles | GET rules / bundles |
| pause_entity / enable_entity | POST entities/{id}/pause / enable |
| change_budget | POST entities/{id}/budget |

Даты передаются как `from`/`to`, YYYY-MM-DD. ID кабинета берётся из
ad-accounts с префиксом `act_`, ID сущности — числовой ID провайдера.
Дополнительные query-параметры передаются явно через `params`; их значения
и поддержка проверяются на следующем этапе. Даты нельзя перезаписать через params.

Reader не содержит методов изменения рекламы. Writer не содержит методов
чтения. Для POST не включены автоматические повторы.
При сетевой ошибке, HTTP 408/5xx или нечитаемом успешном ответе команды
получаем `ActionOutcomeUnknown`: сначала сверить состояние через reader,
затем решать, нужен ли повтор. HTTP 204 возвращается как пустой объект.

GET имеет максимум 3 попытки на сетевые ошибки и HTTP 408/5xx.
401/402/403/429 не повторяются автоматически. Для 429 числовой Retry-After
сохраняется в ошибке; время возобновления решает будущий scheduler.
Дневные лимиты: Starter 1000, Growth 2500, Pro 5000, Business 20000,
сброс в 00:00 UTC. Повторы тоже потребляют запросы.

Перед загрузкой всей статистики требуется проверить:

1. Поля me, scopes и состояние подписки, доступность нужных методов.
2. Формат списка, страниц, курсоров, totals и пустых ответов.
3. Уровни insights, связи сущностей, статусы, архивные данные.
4. Валюты, часовые пояса, комиссии и окна атрибуции.
5. Tracker и breakdowns, отсутствие данных, число разных типов результатов.
6. Формат budget, тип бюджета и размерность денег; затем проверка
   разрешённых write-операций на явно выбранной тестовой сущности.

`get_me` сам по себе не проверяет scopes автоматически: его схема ещё
не зафиксирована. Пользователь должен создать ключи с нужными правами.
