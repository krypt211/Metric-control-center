# Синхронизация и действия

## Smart Sync

Единственный Celery Beat: today каждые 10 минут, yesterday каждый час,
last7 ежедневно в 04:07, breakdowns ежедневно в 04:17 по SYNC_TIMEZONE.
Для разных часовых поясов кабинетов окна расширены на соседние даты:
today = сегодня−1…сегодня+1; yesterday = сегодня−2…сегодня;
last7/breakdowns = сегодня−7…сегодня+1. UI не переносит дневные totals
между часовыми поясами без почасовых данных.

Optional frequency job — ежедневно в 04:27, окно сегодня−15…сегодня
для 14 завершённых дней в разных timezones. Без проверенного отдельного
METRICFLOW_FREQUENCY_SCHEMA_FILE job не отправляет HTTP. Это parent-level
daily insights для детекторов, не усреднение частот объявлений.

При одной странице /insights базовый план — 169 запросов в сутки
(144 + 24 + 1), без breakdowns, повторов и ручных проверок. Число страниц
умножает этот расход. Breakdowns обходят кабинеты отдельно и считаются
в той же квоте. Frequency job, когда настроен, добавляет страницы ещё
одной дневной загрузки. По умолчанию лимит нашей системы — 800
запросов/UTC-день; это не учитывает запросы сторонних клиентов.
Реальный тариф и использование ключей нужно сверить с /usage.

Квота резервируется атомарно перед каждой HTTP-попыткой, включая retry.
429 блокирует дальнейшие запросы до UTC-сброса или более позднего Retry-After.
Lease не позволяет выполнять перекрывающиеся загрузки. Устаревший worker
не может опубликовать metrics, если потерял lease.

Каждая страница сохраняется в raw_snapshots. Metrics публикуются одной
транзакцией только после завершения всех страниц и проверки дат/ID/полей.
Повторная загрузка обновляет значения по entity/date/source. При ошибке
старые данные сохраняются, run получает status/error_code без текста
ошибки с потенциальными секретами. Есть caps страниц и строк.

Отсутствующие строки не удаляются автоматически: отсутствие в ответе может
означать фильтр/архив, а не нулевой расход. Явные нулевые значения обновляются.
Удаление исчезнувших строк требует отдельного подтверждения authoritative
snapshot-контракта. Raw snapshots пока не имеют автоматического retention.

## Проверка схемы

config/metricflow-schema.example.json — синтетический пример, не контракт
реального API. После проверки настроить config/metricflow-schema.json.
items_path, cursor и поля задаются явно. Если страниц нет, явно указать
pagination.mode=none. Не угадывать envelope, валюту или timezone.

Дополнительные mappings в fields: campaign_id/campaign_name,
adset_id/adset_name, creative_id/creative_name/media_url, conversions,
tracker_conversions, status/budget/bid, campaign_status/campaign_budget,
adset_status/adset_budget, buyer/offer/tracker_campaign. Names и labels
отображаются только при наличии. Статусы и бюджеты должны описывать именно
текущее состояние в денежных единицах UI, не исторические значения по дням.

Для GEO создать metricflow-breakdown-schema.json с endpoint=breakdowns,
dimension_fields={"country":"проверенный.путь"}, entity_level=ad, fields и
pagination. Можно использовать _context.account_id/currency/timezone:
контекст берётся из ранее загруженного кабинета. Не смешивать country-only
и country+age breakdowns. Почасовые таблицы готовы, загрузка часов ещё не реализована.

## Action Engine

POST /api/actions принимает provider entity_id, entity_type, action и value;
инициатор определяется сервером по операторскому токену. Заголовок
Idempotency-Key обязателен. Повтор с тем же ключом/командой возвращает ту же
заявку; иной payload с тем же ключом отклоняется.

Проверяются workspace, роль, существование сущности, current state,
давность state, разрешённый action, максимальный budget и процент изменения.
Перед отправкой worker повторяет проверку и отклоняет изменённый baseline.
Заявка хранится в PostgreSQL до попадания в worker: сбой broker её не теряет.
Celery task polls эту очередь. В БД фиксируется попытка до внешнего POST.
После сбоя процесс переходит к сверке и не отправляет вторую попытку.

Последовательность: queued → executing → verifying → succeeded.
Другие исходы: rejected / unknown. В verifying сопоставляется новая state
из sync с целевым статусом/бюджетом. Через 30 минут без подтверждения — unknown.
Такая заявка продолжает блокировать следующие команды; поздняя положительная
сверка может завершить её. Ручное разрешение конфликтного unknown ещё не добавлено.

Budget contract задаётся в config/action-budget-contract.json:
verified=true, field, positive scale, encoding=integer/decimal_string,
fixed_fields. Не включать verified до проверки единиц и тела запроса.
Изменение бюджета не предполагает наличие бюджета у объявления: только
campaign/adset, и только если провайдер подтвердил соответствующую семантику.

Сторонние изменения в Meta/MetricFlow между проверкой и POST нельзя
атомарно исключить без поддержки compare-and-set у провайдера.
Система обнаруживает результат последующей сверкой и хранит журнал.
