## Core Statistics

Core READ работает. Контрольный срез: 08.10.2026, 05:41:58 МСК.

Сохранены ключ ad_account_id + ad_id + date, cursor pagination и основной pipeline /insights. Digest конфигурации: 4d5752498edb1744695f4b29c5674cfc381a869c6611dc5180286e31e2bbd6ce.

В PostgreSQL: 3 кабинета, 48 кампаний, 105 ad sets, 120 объявлений, 273 текущих состояния, 364 ad/day факта. Доступны расход, показы, клики, лиды, покупки, конверсии, CTR/CPC/CPM, CPL/CPS/CPA/CR при известных исходных значениях, статусы. Добавлены счётчики событий из raw /insights. Reach, frequency и уникальные счётчики не суммируются между разными аудиториями; общий показатель известен только для одной ad/day записи.

Суммы account → campaign → adset → ad совпали во всех семи проверенных периодах. Таблицы читают собственную БД.

Дополнительная проверка /summary и /insights за 07.10.2026: одинаковая версия 2026-10-08T02:18:17.562016+00:00, те же три кабинета и часовые пояса. Расход 629.25, показы 55189, клики 5969 совпали; /ads и /daily подтвердили суммы по кабинетам. День ещё не был закрыт во всех часовых поясах.

Старое доказательство за 06–07.10.2026 на версии 2026-10-07T16:33:17.402594+00:00 сохранено: /summary расход +0.14, показы −12 относительно /insights. Причина не доказана. Разные внутренние источники агрегации — возможная гипотеза. Новая проверка другого диапазона прежнее расхождение не объясняет. Принудительного выравнивания нет.

Доказательства: [db-final.json](db-final.json), [dashboard-performance.json](dashboard-performance.json), [source-research.json](source-research.json), [старое расхождение](../metricflow-live-contract/provider-aggregate-difference.json).

## Tracker Contract

PARTIAL. Импорт сохраняет отдельно:

- /tracker: кабинет / дата — clicks, unique_clicks, conversions, leads, sales, regs, deposits.
- /ads.tracker: объявление / точный период — t_clicks, t_unique_clicks, t_conversions, t_conversions_raw, t_leads, t_sales, t_regs, t_deposits.
- /creatives.tracker: creative_key / кабинет / точный период — доступные clicks, conversions, leads, sales.

Сохранены 29 наблюдений account/day и 597 ad/window, включая перекрывающиеся периоды. Отсутствующее объявление в разреженном tracker-каталоге не считается нулём. Эти наблюдения не превращаются в дневные core-факты.

В исследованной неделе суммы ad t_conversions_raw совпали с /tracker.conversions: 28, 172, 1064. Суммы t_conversions — 10, 34, 205. Документация различает настроенное событие и наблюдаемые события; счётчики сохранены раздельно. Их нельзя автоматически объявлять одной метрикой или продажами.

Клики /creatives.tracker отличаются от сумм /ads.tracker. Tracker в /daily не даёт согласованного контракта и не импортируется. Дневные campaign/adset/ad tracker-факты, валюта и timezone tracker не доказаны.

Доказательства: [capture.json](capture.json), [tracker-semantics.json](tracker-semantics.json), [optional-audit.json](optional-audit.json). Первичный справочник: [документация MetricFlow](https://metricflowit.click/docs).

## Revenue / Profit / ROI

NOT AVAILABLE для живого dashboard. Monetary-поля сохранены в raw, но проверенные ответы tracker имеют currency=null и не указывают timezone. Валюта рекламного кабинета не назначается tracker автоматически.

Пример источника: revenue=102, cost=94.68, profit=7.32, provider ROI=107.73. Формула задания даёт 7.7313%, тогда как provider ROI численно совпадает с revenue/cost×100. В одном кабинете account profit=−345.08, сумма ad profit=−455.08; последняя численно совпадает с sale revenue−cost, но не total revenue−cost. Причина не подтверждена.

Расчёт реализован и протестирован: profit=revenue−spend; ROI=profit/spend×100. Только при совпадающих доказанных scope и валюте. Unknown/mismatch → null; нулевой расход → ROI=null. Убытки поддерживаются. Сейчас денежные показатели — «—».

## Creatives

PARTIAL. Импорт и аналитика работают по непрозрачному creative_key, кабинету и точному диапазону. Повторный запрос подтвердил стабильность ключей в исследованных snapshots; ключи дневного ответа входят в недельный набор. Глобальная неизменность ключа на всю историю не доказана.

Для каждого creative_key найдены /ads.creative_key той же версии. Spend, impressions, clicks, leads, purchases, conversions совпали с суммой связанных ads. Во всех семи загруженных периодах creative totals совпали с core totals.

Доступны type, thumbnail, title/body, число найденных связанных ads, Meta-счётчики и отдельные tracker-счётчики. Если title/body отсутствуют, используется подпись с ключом. Preview URL может истечь. Source ads_count местами отличается от числа связей каталога; UI показывает доказанные связи.

Сохранены 414 creative/window наблюдений по семи перекрывающимся периодам, а не 414 уникальных Meta-креативов. Незагруженный Custom возвращает not_loaded, без подстановки более широкого окна. Numeric Meta creative ID и историческая смена creative у ad не доказаны.

## Breakdowns

NOT AVAILABLE для безопасного импорта по проверенным ответам. Проверены country, region, impression_device, publisher_platform, age, gender, hourly_stats_aggregated_by_advertiser_time_zone и альтернативные имена query-параметров.

Country/gender возвращают те же возрастоподобные значения без подтверждения выбранного типа dimension. Entity identity, date и currency в исследованных строках не определены. Полнота ответа подтверждается meta.total и limit/offset=null, но идентичность измерения остаётся неизвестной.

Импорт отключён. Возрастоподобные значения не помечаются как country/gender. Это ограничение проверенного контракта; нужен корректный документированный запрос с явными dimension/scope/currency.

Доказательства: [capture.json](capture.json), [breakdown-query-probes.json](breakdown-query-probes.json).

## Historical Backfill

days imported: обработан диапазон 08.09–07.10.2026, 30 дней / 10 окон. API вернул 363 факта на 10 датах, 28.09–07.10. За остальные 20 дней строки не получены; нулевые факты не создавались. Отдельный текущий sync добавил запись за 08.10, всего 364.

API requests used: прогноз до запуска — 90 GET; первый backfill — 36 GET; replay — 22 GET; resume — 0 GET. Всего backfill с проверкой — 58 GET.

duplicate test: PASS. После replay 363 строки / 363 уникальных ключа, digest фактов не изменился. PostgreSQL duplicate groups core=0, optional=0. Отсутствующих родителей и null external IDs нет.

Backfill использует атомарный core sync, persistent checkpoints с digest схемы, общий quota counter, overlap lease и обработку 429. Низкая квота приостанавливает работу; лимит 800 не повышается. Обычный повтор пропускает успешные окна, --replay явно повторяет их.

Доказательства: [backfill-estimate.json](backfill-estimate.json), [backfill-audit.json](backfill-audit.json). Команды: [RUN_LOCAL.md](../../RUN_LOCAL.md).

## Dashboard

Панель запущена: http://127.0.0.1:3000. Backend readiness, PostgreSQL, Redis, worker и frontend HTTP прошли status.bat.

Проверены Today, Yesterday, 3d, 7d, 14d, 30d и Custom. Сохранены основные фильтры и иерархия. Добавлены Tracker и Creatives с периодом и кабинетом. Tracker переключается account/day ↔ ad/window; настроенные и наблюдаемые конверсии отображаются отдельно.

Unknown → null / «—». Creatives и ad/window требуют точного загруженного диапазона. Account/day допускает любой диапазон сохранённой истории. Optional refresh пока выполняется вручную; существующий core scheduler не изменён и не расходует квоту на optional endpoints.

Финальная optional-проверка: семь периодов + replay 7d, 72 GET; предыдущая проверка account/day + creatives — ещё 72 GET. Всего optional refresh этапа — 144 GET. Replay не изменил число строк и состав областей.

Next.js и TypeScript build PASS. Полный suite: 195 tests PASS, 92.167 секунд, включая 18 новых regression tests. Проверены mapping, currency/scope mismatch, identity, null/ROI, backfill/resume/quota/atomicity и дубли. Тесты других модулей используют локальные fixtures/mocks; эти модули в живой панели не включались.

Визуальная проверка кликами не выполнена: инструмент управления браузером не обнаружил доступных браузеров/приложений. Сборка и HTTP/API-проверки выполнены. Результат: [validation.json](validation.json).

## Performance

Пять HTTP-измерений внутри Docker после импорта; медиана. Table — account level. Время не включает отрисовку браузера.

| Период | Summary, ms | Table, ms | Ad/day факты | Загружено строк summary / table |
| --- | ---: | ---: | ---: | ---: |
| Today | 5.484 | 19.609 | 1 | 1 / 775 |
| 7d | 17.188 | 31.916 | 198 | 198 / 972 |
| 30d | 24.143 | 42.456 | 364 | 364 / 1138 |

Endpoints: /api/stats/summary и /api/stats/table. Loaded rows измерены через cursor.rowcount SELECT и включают metadata; это не число уникальных сущностей и не полный физический I/O. Summary — 2 SELECT, table — 8 SELECT.

Представительный EXPLAIN ANALYZE для фактов 30d: 0.492 ms. Index Only Scan daily_metrics — 364 строки; Seq Scan entities — 120 прошли фильтр, 153 отброшены; Index Scan ad_accounts — 1 строка × 3 loops. Это не полный план всех запросов endpoint.

На текущем объёме узкое место Python aggregation не выявлено, большой SQL rewrite не требуется. При росте нужны повторные измерения; возможны SQL GROUP BY и сокращение metadata-загрузок.

## Remaining Unsupported MetricFlow Data

По проверенным ответам пока не удаётся безопасно сопоставить:

- Tracker currency/timezone и денежные результаты с рекламными расходами.
- Дневные tracker-факты campaign/adset/ad и согласованный tracker из /daily.
- Общий смысл provider ROI и различающегося profit account/ad.
- Тип breakdown и entity/date/currency.
- Numeric Meta creative ID, историческую смену creative и стабильность ключа вне проверенных snapshots.
- Историю первых 20 дней backfill: неизвестно, данных нет или API их не отдаёт.

Ограничения реализации: optional refresh вручную; новый Custom требует отдельной загрузки; preview зависит от provider URL. Перекрывающиеся snapshots нельзя складывать как независимые факты.

## Safety

ACTIONS_ENABLED=false. LOCAL_READ_ONLY=true. WRITE key used: NO; WRITE-secret не подключён к READ-сервисам. MetricFlow POST requests: 0. DELETE/write requests: 0. Advertising entities modified: 0. Action requests/executions в живой БД: 0 / 0.

Quota на контрольном срезе: 329 / 800 GET за 08.10.2026 UTC, осталось 471. Provider budget 20 000 не заменяет локальный лимит. Scheduler может увеличить счётчик после среза.

Изменения только в metric-control-center. Creative Factory не изменялся. Manual controls, Rules, Telegram, AI не включались. READ-key не выводился в отчёт или доказательства.

Основные файлы: services/sync/backfill.py, services/sync/optional.py, services/analytics/scopes.py, services/analytics/optional.py, services/analytics/dashboard.py, services/storage/models.py, migrations/versions/0006_read_statistics.py, backend/app.py, frontend/components/OptionalStatistics.tsx, frontend/components/Statistics.tsx, frontend/app/page.tsx, frontend/app/api/stats/[kind]/route.ts, tests/test_full_read.py, RUN_LOCAL.md.

## FINAL RESULT

V1 FULL READ STATISTICS: PARTIAL

Выполнены READ tracker counts, creative analytics, управляемый 30-дневный backfill и проверки dashboard/performance. READY пока недоступен из-за неподтверждённых currency/scope tracker, контракта breakdowns и creative/history identity. Денежные показатели остаются неизвестными до появления доказанного контракта.
