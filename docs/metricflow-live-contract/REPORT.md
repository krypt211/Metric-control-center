# METRICFLOW LIVE CONTRACT REPORT

07.10.2026. Только E:/Creative_Factory/metric-control-center. Реальная PostgreSQL, без preview/demo. Первое окно 2026-10-06–2026-10-07. Доказательства первого повтора сохранены отдельно от финального снимка: источник продолжал обновляться.

## Docker / Local Application

PASS. PostgreSQL, Redis, migrate, backend, frontend, worker, scheduler проверены status.bat. Backend readiness: database/migrations/redis OK; frontend HTTP 200; Celery pong. Backend/worker/scheduler пересобраны и запущены. sync_now.bat -NoPause завершён с кодом 0 и Docker: OK. Docker execution и результат контейнерного приложения теперь диагностируются отдельно.

Current local status rechecked on 2026-10-08: status.bat exit 0; backend readiness, frontend HTTP and worker response OK; last scheduled sync succeeded at 2026-10-08T01:40:00.016311+00:00 with 28 rows. These rows belong to its current scheduled window and are distinct from the fixed 59-row audit window.

## READ Authentication

PASS. /me сообщает scopes в api_key.scopes: только READ, включая analytics:read, ad_accounts:read, campaigns:read, insights:read. Исправлены проверка вложенных scopes и отображение daily_used/daily_remaining. Все внешние запросы — GET; ключ и identity владельца не выводились.

## Accounts

3 кабинета; статус каждого получен из catalog.status и доступен в account table/filter. Все USD; два America/Los_Angeles, один Europe/Kiev. В собственной БД сохранены оригинальные act_<numeric> IDs, в образцах — псевдонимы того же формата. Дата факта сохраняется с timezone кабинета, без пересчёта дневных агрегатов в московские сутки. Каталог содержит все 3 кабинета; Today имеет факты в 2, Yesterday в 3. Отсутствие ad-фактов не подменяется выдуманными нулями.

## Endpoint Contracts

Endpoint указан относительно /api/v1. Entity endpoints вызваны через /ad-accounts/{act_id}/{endpoint} для одного реального кабинета. Образцы *-headers.json и schema-inventory.json сохраняют структуру, наблюдаемые типы, массивы и null. Наблюдавшийся non-null не считается гарантией схемы.

| Endpoint | Envelope | Pagination | Mapping | Status |
|---|---|---|---|---|
| me | root object | N/A | api_key.scopes; identity redacted | VERIFIED CORE |
| usage | root object | N/A | daily_used/daily_limit/daily_remaining | VERIFIED CORE |
| ad-accounts | data[] + meta | meta.total=3; rows=3; limit/offset=null | id/currency/timezone/name | VERIFIED CORE |
| summary | root object | meta.total=3; rows=3; limit/offset=null | total_* and accounts[]; comparison only | READ OK; source difference |
| insights | data[] + meta + pagination | cursor/has_more; meta.total=page count | ad/day facts + hierarchy IDs + effective_status | VERIFIED CORE |
| campaigns | data[] + meta | meta.total=35; rows=35; limit/offset=null | ID/state and period aggregate; not daily facts | VERIFIED CORE STATE |
| adsets | data[] + meta | meta.total=99; rows=99; limit/offset=null | parent_id/campaign_id/state; budget/bid units unverified | VERIFIED CORE STATE |
| ads | data[] + meta | meta.total=113; rows=113; limit/offset=null | parents/state; creative_key and tracker period aggregate | READ observed; optional import OFF |
| daily | data[] + meta | meta.total=1; rows=1; limit/offset=null | account/day; nested tracker scope not proven | READ observed; optional import OFF |
| creatives | data[] + meta | meta.total=1; rows=1; limit/offset=null | creative_key grouping; no numeric Meta creative ID | READ observed; optional import OFF |
| tracker | data[] + meta | meta.total=2; rows=2; limit/offset=null | date and metrics; no entity ID or currency | READ observed; optional import OFF |
| breakdowns | data[] + meta | meta.total=3; rows=3; limit/offset=null | dimension; date and entity IDs null | READ observed; optional import OFF |

## `/insights` Contract

items_path=data; level=ad; from/to включительно. Ключ факта: ad_account_id + ad_id + date. Родители campaign_id/adset_id; имена ad_name/campaign_name/adset_name; текущее состояние ad — effective_status. Currency явная в строке, timezone берётся из проверенного каталога того же кабинета. Все 59 строк прошли проверки ID, родителей, периода, валюты, timezone и числовых типов. Conversions — отдельный счётчик источника, не сумма leads+purchases.

## Pagination Contract

Реальный проход limit=20: 20+20+19=59 строк, 59 уникальных ключей; ключи и значения полностью совпали с ответом limit=100. pagination.cursor — следующий cursor; передаётся query-параметром cursor. Первые две страницы has_more=true; последняя has_more=false и cursor=null. meta.total у insights — длина страницы, не общий размер выборки. page=1/page=2 с limit=1 возвращают один и тот же первый элемент: page не переключает страницы.

Каталог: 3 строки, meta.total=3, meta.limit=null, meta.offset=null. limit=1/page=1, limit=1/page=2, limit=1/offset=1, per_page=1/page=1 не урезали ответ. Полнота доказана явным total, равным длине, при null limit/offset; отсутствие pagination само по себе не используется. Несовпадение total или появление limit/offset останавливает импорт.

В сохранённых заголовках нет Link/X-Total-Count или иного paging-механизма; Content-Type=application/json. Доказательства: pagination-evidence.json, insights-cursor-page1/2/3.json. Каждый sync проверяет cursor/has_more, page count, диапазон, стабильность meta.data_updated_at между страницами, caps, повторные cursor и дубли. Неизвестный/противоречивый контракт или смена снимка не публикует частичные данные. Optional endpoints имеют observed total=rows, но их периодные агрегаты не превращаются в ad/day факты.

## Schema File

config/metricflow-schema.json создан по живым ответам. State catalogs campaign/adset обновляются после истечения кэша 3600 секунд или при появлении новых родителей; наблюдаемые status/name и parent IDs проверяются до атомарной публикации. Budgets/bids не пересчитываются. Сначала схема-кандидат прошла первый импорт и точный повтор, затем опубликована для штатных worker/scheduler. Синтетический example не использован. В verification сохранены источник доказательств, окно и cursor-проба; новые ответы проходят runtime-проверки.

## Metrics Mapping

| Система | Источник | Результат |
|---|---|---|
| spend | insights.spend | Decimal, основные единицы currency; не делить на 100 |
| impressions/clicks/reach | одноимённые поля | целые; reach не складывать как уникальную аудиторию разных ads |
| frequency | insights.frequency | Decimal конкретного ad/day |
| leads | insights.leads | Meta leads |
| sales | insights.purchases | Meta purchases, не tracker sales |
| conversions | insights.conversions | без догадки о составе событий |
| revenue | отсутствует в insights | null |
| profit/ROI | Python от revenue/spend | null при неизвестном revenue |
| CTR/CPC/CPM | Python от сумм | проценты / деньги за клик / за 1000 показов |
| tracker clicks/conversions/revenue/profit | /tracker.data[].clicks/conversions/revenue/profit; /ads tracker.t_*; /creatives tracker.* | образцы есть; импорт OFF: без доказанного ad/day identity и currency |
| parent budget/bid | entity endpoints | единицы не доказаны; нормализованные значения null |

/Tracker возвращает даты и метрики без ad/entity ID и явной валюты: распределение по ads и currency Meta не предполагаются. В /daily nested tracker cost не согласован с расходом запрошенного кабинета; scope не доказан. Creatives используют creative_key, не numeric creative_id; breakdowns без дополнительных параметров дают date/entity IDs=null. Optional данные не блокируют базовые ad READ-метрики, но остаются вне импорта.

## First Sync

SUCCESS: 3 accounts, 19 campaigns, 34 adsets, 39 ads, 59 daily rows, 39 состояний ads. Run: каталог + insights = 2 GET, плюс 3 GET предварительного probe. Начальное окно только 2026-10-06–2026-10-07 включительно. Затем Core state catalogs campaign/adset были загружены для всех 3 аккаунтов, в БД теперь 92 состояния entities и 3 account status. Доказательство: state-catalog-snapshots.json. Backfill не выполнялся; расписание не менялось.

## Imported Counts

Фактические числа в собственной PostgreSQL. Campaign/adset/ad представлены в дневных фактах выбранного периода; это не полный архив всех zero-spend сущностей.

| Таблица | Первый sync | Первый повтор | Финальная проверка |
|---|---|---|---|
| ad_accounts | 3 | 3 | 3 |
| campaigns | 19 | 19 | 19 |
| adsets | 34 | 34 | 34 |
| ads | 39 | 39 | 39 |
| creatives | 0 | 0 | 0 |
| daily_metrics | 59 | 59 | 59 |
| tracker_metrics | 0 | 0 | 0 |
| breakdowns | 0 | 0 | 0 |
| raw_snapshots | 2 | 4 | 24 |
| sync_runs | 1 | 2 | 9 |
| entity_current_state | 39 | 39 | 92 |
| action_requests | 0 | 0 | 0 |
| action_executions | 0 | 0 | 0 |

Counts above are a fixed database audit checkpoint on 2026-10-07, before the next scheduled Today job at 17:00 UTC. The scheduler remains active; these are evidence counts, not an assertion that the live database is frozen.

## Duplicate Test

PASS. Первый повтор оставил сущности и 59 фактов без изменения числа записей; facts_digest совпал. Raw snapshots 2→4, sync runs 1→2 — журнал запусков. После этого были дополнительные проверки BAT, два штатных Today job и полная загрузка состояний. Всего в финальном снимке 9 sync runs, 24 raw snapshots, 59 фактов и 92 entity current states. Первый полный state refresh: 8 GET; его повтор: 2 GET. В db-first-state-sync.json и db-state-replay.json одинаковый facts_digest. По финальному снимку отсутствующие состояния entities/accounts=0. Значения фактов обновлялись только вслед за источником. Финальный digest поэтому отличается от первого снимка. Проверки: duplicate groups=0; отсутствующие parents=0; cross-account parents=0; неверные provider IDs=0; raw→PG mismatches=0. См. db-before/first-sync/replay/final.json.

## Dashboard

HTTP/API PASS: localhost:3000, /api/dashboard, Today/Yesterday и account→campaign→adset→ad. Базовые суммы и известные статусы проверены на всех уровнях; фильтр ACTIVE на уровне аккаунта покрыт тестом и реальным mapping. Overview возвращает реальные USD/timezone группы, LOCAL READ ONLY, revenue/profit/ROI=null. Creative-таблица пуста: подтверждённый creative mapping отсутствует.

VISUAL BROWSER CHECK NOT VERIFIED. Browser inventory текущей сессии пуст; Chrome и встроенный browser возвращают Browser is not available. HTTP и frontend proxy API проверены, но видимая отрисовка, клики Today/Yesterday и раскрытие дерева не подтверждены. Это конкретный незакрытый критерий полной готовности.

## Metric Reconciliation

Raw ниже — именно импортированные raw snapshots, PG — факты, Dashboard — реальный GET через frontend /api/stats/table, сумма account-строк. Все currency=USD. Дополнительно проверены campaign/adset/ad. Даты — фиксированные календарные даты в timezone источника. Коэффициенты не суммируются/не усредняются между аккаунтами.

| Metric | Raw | PostgreSQL | Dashboard API | Difference |
|---|---|---|---|---|
| Today spend | 282.95 | 282.95000000 | 282.95000000 | 0E-8 |
| Today impressions | 21339 | 21339 | 21339 | 0 |
| Today clicks | 1894 | 1894 | 1894 | 0 |
| Today leads | 43 | 43 | 43 | 0 |
| Today sales | 6 | 6 | 6 | 0 |
| Today conversions | 104 | 104 | 104 | 0 |
| Today revenue | UNKNOWN | null | null | N/A |
| Today profit | UNKNOWN | null | null | N/A |
| Today roi | UNKNOWN | null | null | N/A |
| Yesterday spend | 892.91 | 892.91000000 | 892.91000000 | 0E-8 |
| Yesterday impressions | 73950 | 73950 | 73950 | 0 |
| Yesterday clicks | 8303 | 8303 | 8303 | 0 |
| Yesterday leads | 217 | 217 | 217 | 0 |
| Yesterday sales | 41 | 41 | 41 | 0 |
| Yesterday conversions | 557 | 557 | 557 | 0 |
| Yesterday revenue | UNKNOWN | null | null | N/A |
| Yesterday profit | UNKNOWN | null | null | N/A |
| Yesterday roi | UNKNOWN | null | null | N/A |

CTR/CPC/CPM рассчитаны Decimal из сумм каждого account/day. Существующий API округляет коэффициенты до четырёх знаков; ненулевые остатки ниже не скрыты округлением. Null CPC при нулевых clicks корректен. Все периоды и строки — http-reconciliation.json; экранное форматирование не проверено.

| Metric / row | Raw derived | PostgreSQL derived | Dashboard API | Difference |
|---|---|---|---|---|
| Today, row 1, Europe/Kiev, ctr | 4.728440048585806003817456186 | 4.728440048585806003817456186 | 4.7284 | -0.000040048585806003817456186 |
| Today, row 1, Europe/Kiev, cpc | 0.3290275229357798165137614679 | 0.3290275229357798165137614679 | 0.3290 | -0.0000275229357798165137614679 |
| Today, row 1, Europe/Kiev, cpm | 15.55786916536526114870727052 | 15.55786916536526114870727052 | 15.5579 | 0.00003083463473885129272948 |
| Today, row 2, America/Los_Angeles, ctr | 13.74707021298277794762050341 | 13.74707021298277794762050341 | 13.7471 | 0.00002978701722205237949659 |
| Today, row 2, America/Los_Angeles, cpc | 0.07681986656782802075611564122 | 0.07681986656782802075611564122 | 0.0768 | -0.00001986656782802075611564122 |
| Today, row 2, America/Los_Angeles, cpm | 10.56048099459900132477325996 | 10.56048099459900132477325996 | 10.5605 | 0.00001900540099867522674004 |
| Yesterday, row 1, America/Los_Angeles, ctr | 0 | 0 | 0.0000 | 0.0000 |
| Yesterday, row 1, America/Los_Angeles, cpc | UNKNOWN / null | UNKNOWN / null | UNKNOWN / null | UNKNOWN / null |
| Yesterday, row 1, America/Los_Angeles, cpm | 50.00 | 50.00000000 | 50.0000 | 0.0000 |
| Yesterday, row 2, Europe/Kiev, ctr | 5.055478957389534502002494912 | 5.055478957389534502002494912 | 5.0555 | 0.000021042610465497997505088 |
| Yesterday, row 2, Europe/Kiev, cpc | 0.3043116883116883116883116883 | 0.3043116883116883116883116883 | 0.3043 | -0.0000116883116883116883116883 |
| Yesterday, row 2, Europe/Kiev, cpm | 15.38441336747423018843148841 | 15.38441336747423018843148841 | 15.3844 | -0.00001336747423018843148841 |
| Yesterday, row 3, America/Los_Angeles, ctr | 12.82955242182709993868792152 | 12.82955242182709993868792152 | 12.8296 | 0.00004757817290006131207848 |
| Yesterday, row 3, America/Los_Angeles, cpc | 0.08740740740740740740740740741 | 0.08740740740740740740740740741 | 0.0874 | -0.00000740740740740740740740741 |
| Yesterday, row 3, America/Los_Angeles, cpm | 11.21397915389331698344573881 | 11.21397915389331698344573881 | 11.2140 | 0.00002084610668301655426119 |

При одинаковом диапазоне и meta.data_updated_at сами /summary и /insights возвращают разные агрегаты. Источник основной таблицы — insights; с ним локальная цепочка совпадает. Причина расхождения агрегатов источника не доказана и не исправляется произвольным коэффициентом. См. provider-aggregate-difference.json.

| Metric | /summary | Sum /insights | Summary minus insights |
|---|---|---|---|
| spend | 1155.23 | 1155.09 | 0.14 |
| impressions | 93426 | 93438 | -12 |
| clicks | 9969 | 9969 | 0 |

Для одного кабинета в каждом периоде дополнительно выбраны три ads; сравнение каждой сущности (IDs псевдонимизированы):

| Metric/entity | Raw | PostgreSQL | Dashboard API | Difference |
|---|---|---|---|---|
| Today ad 910985159065081092 spend | 0.53 | 0.53000000 | 0.53000000 | 0E-8 |
| Today ad 910985159065081092 impressions | 70 | 70 | 70 | 0 |
| Today ad 910985159065081092 clicks | 6 | 6 | 6 | 0 |
| Today ad 910985159065081092 leads | 0 | 0 | 0 | 0 |
| Today ad 910985159065081092 sales | 0 | 0 | 0 | 0 |
| Today ad 910985159065081092 conversions | 0 | 0 | 0 | 0 |
| Today ad 910985159065081092 ctr | 8.571428571428571428571428571 | 8.571428571428571428571428571 | 8.5714 | -0.000028571428571428571428571 |
| Today ad 910985159065081092 cpc | 0.08833333333333333333333333333 | 0.08833333333333333333333333333 | 0.0883 | -0.00003333333333333333333333333 |
| Today ad 910985159065081092 cpm | 7.571428571428571428571428571 | 7.571428571428571428571428571 | 7.5714 | -0.000028571428571428571428571 |
| Today ad 974330378546683543 spend | 7.95 | 7.95000000 | 7.95000000 | 0E-8 |
| Today ad 974330378546683543 impressions | 637 | 637 | 637 | 0 |
| Today ad 974330378546683543 clicks | 38 | 38 | 38 | 0 |
| Today ad 974330378546683543 leads | 0 | 0 | 0 | 0 |
| Today ad 974330378546683543 sales | 0 | 0 | 0 | 0 |
| Today ad 974330378546683543 conversions | 0 | 0 | 0 | 0 |
| Today ad 974330378546683543 ctr | 5.965463108320251177394034537 | 5.965463108320251177394034537 | 5.9655 | 0.000036891679748822605965463 |
| Today ad 974330378546683543 cpc | 0.2092105263157894736842105263 | 0.2092105263157894736842105263 | 0.2092 | -0.0000105263157894736842105263 |
| Today ad 974330378546683543 cpm | 12.48037676609105180533751962 | 12.48037676609105180533751962 | 12.4804 | 0.00002323390894819466248038 |
| Today ad 910184674294899873 spend | 5.89 | 5.89000000 | 5.89000000 | 0E-8 |
| Today ad 910184674294899873 impressions | 526 | 526 | 526 | 0 |
| Today ad 910184674294899873 clicks | 25 | 25 | 25 | 0 |
| Today ad 910184674294899873 leads | 0 | 0 | 0 | 0 |
| Today ad 910184674294899873 sales | 0 | 0 | 0 | 0 |
| Today ad 910184674294899873 conversions | 0 | 0 | 0 | 0 |
| Today ad 910184674294899873 ctr | 4.752851711026615969581749049 | 4.752851711026615969581749049 | 4.7529 | 0.000048288973384030418250951 |
| Today ad 910184674294899873 cpc | 0.2356 | 0.23560000 | 0.2356 | 0.0000 |
| Today ad 910184674294899873 cpm | 11.19771863117870722433460076 | 11.19771863117870722433460076 | 11.1977 | -0.00001863117870722433460076 |
| Yesterday ad 910985159065081092 spend | 10.42 | 10.42000000 | 10.42000000 | 0E-8 |
| Yesterday ad 910985159065081092 impressions | 1017 | 1017 | 1017 | 0 |
| Yesterday ad 910985159065081092 clicks | 74 | 74 | 74 | 0 |
| Yesterday ad 910985159065081092 leads | 1 | 1 | 1 | 0 |
| Yesterday ad 910985159065081092 sales | 0 | 0 | 0 | 0 |
| Yesterday ad 910985159065081092 conversions | 2 | 2 | 2 | 0 |
| Yesterday ad 910985159065081092 ctr | 7.276302851524090462143559489 | 7.276302851524090462143559489 | 7.2763 | -0.000002851524090462143559489 |
| Yesterday ad 910985159065081092 cpc | 0.1408108108108108108108108108 | 0.1408108108108108108108108108 | 0.1408 | -0.0000108108108108108108108108 |
| Yesterday ad 910985159065081092 cpm | 10.24582104228121927236971485 | 10.24582104228121927236971485 | 10.2458 | -0.00002104228121927236971485 |
| Yesterday ad 936613043970637529 spend | 0.33 | 0.33000000 | 0.33000000 | 0E-8 |
| Yesterday ad 936613043970637529 impressions | 42 | 42 | 42 | 0 |
| Yesterday ad 936613043970637529 clicks | 3 | 3 | 3 | 0 |
| Yesterday ad 936613043970637529 leads | 0 | 0 | 0 | 0 |
| Yesterday ad 936613043970637529 sales | 0 | 0 | 0 | 0 |
| Yesterday ad 936613043970637529 conversions | 0 | 0 | 0 | 0 |
| Yesterday ad 936613043970637529 ctr | 7.142857142857142857142857143 | 7.142857142857142857142857143 | 7.1429 | 0.000042857142857142857142857 |
| Yesterday ad 936613043970637529 cpc | 0.11 | 0.11000000 | 0.1100 | 0.0000 |
| Yesterday ad 936613043970637529 cpm | 7.857142857142857142857142857 | 7.857142857142857142857142857 | 7.8571 | -0.000042857142857142857142857 |
| Yesterday ad 974747938179401966 spend | 35.77 | 35.77000000 | 35.77000000 | 0E-8 |
| Yesterday ad 974747938179401966 impressions | 3592 | 3592 | 3592 | 0 |
| Yesterday ad 974747938179401966 clicks | 182 | 182 | 182 | 0 |
| Yesterday ad 974747938179401966 leads | 6 | 6 | 6 | 0 |
| Yesterday ad 974747938179401966 sales | 4 | 4 | 4 | 0 |
| Yesterday ad 974747938179401966 conversions | 24 | 24 | 24 | 0 |
| Yesterday ad 974747938179401966 ctr | 5.066815144766146993318485523 | 5.066815144766146993318485523 | 5.0668 | -0.000015144766146993318485523 |
| Yesterday ad 974747938179401966 cpc | 0.1965384615384615384615384615 | 0.1965384615384615384615384615 | 0.1965 | -0.0000384615384615384615384615 |
| Yesterday ad 974747938179401966 cpm | 9.958240534521158129175946548 | 9.958240534521158129175946548 | 9.9582 | -0.000040534521158129175946548 |

Independent verification: final-evidence.json sums the separately exported provider RawSnapshot payloads and compares them with PostgreSQL and dashboard API for 2026-10-06/07. All six base metrics match exactly. All 59 unique ad/day keys match the first replay; no keys were omitted or invented. The numeric reconciliation uses snapshot run a1ec5089-5922-4eb6-9272-9c8e8a9d4da7, after the database-count checkpoint. The summary/insights discrepancy above uses the earlier fixed provider version 2026-10-07T16:33:17.402594+00:00.

## API Quota Estimate

Provider daily_limit=20,000 подтверждён /usage. Последний probe внутри sync: daily_used=88; после оставшихся трёх GET локальный счётчик=91. SYNC_DAILY_BUDGET=800 сохранён.

Today: 144 runs/day; Yesterday: 24; last7: 1. Формула: 144×(1+P_today)+24×(1+P_yesterday)+(1+P_last7)+S_state, где 1 — каталог, P — фактические cursor-страницы, S_state — parent metadata GET. Фактически Today sync: 2 GET с тёплым state cache, 8 при обновлении всех родителей. Основной поток Today: 12 GET/hour; Yesterday reconciliation: 2/hour; state refresh в среднем до 6/hour для существующих родителей, всего около 20/hour. Новые родители могут добавить ранний refresh. Cross-account insights не умножает каждый запрос на 3 кабинета. Optional breakdowns/frequency без схем не вызывают API; Actions/Rules/AI выключены.

Если одна insights-страница на job: 338 GET/day (1.69% provider limit). Прогноз по 59 строкам за два дня: около 89 за три дня, 266 за девять; 1/1/3 страницы дают около 340 GET/day. С parent state refresh 6×24=144 GET/day получается около 484/day, запас до provider limit примерно 19,516 и до local budget около 316. При двух insight-страницах на job: 507+144=651/day. Это оценка, а не доказанный объём исторических окон: прежде активные ads могут увеличить страницы. Breakdowns и frequency: 0 GET/day, схемы отсутствуют. Last7 reconciliation: ориентировочно 4 GET/day (catalog+3 insight pages), exact volume не измерялся. Локальная квота останавливает запросы на 800. Расписание не менялось; backfill требует отдельного расчёта.

## Files Changed

- scripts/local.ps1 — отдельный application result и коды 20/21/22/23; wiring probe/sync.
- services/metricflow/probe.py — nested READ-scopes и usage.
- services/metricflow/onboarding.py — живой cursor/full-total contract, purchases, effective_status, metadata.
- services/metricflow/local.py — Today+Yesterday, явные даты, атомарная схема, классификация ошибок.
- services/sync/schema.py — строгая общая проверка страниц.
- services/sync/engine.py — catalog completeness, диапазон, стабильность снимка, parent state refresh/cache и проверка parent chain.
- services/analytics/table.py — real account status и фильтр по нему.
- config/metricflow-schema.json — реальная схема.
- tests/test_live_contract.py; tests/test_windows_launch.py — регрессионные проверки.
- RUN_LOCAL.md — период, контракт, диагностика.
- docs/metricflow-live-contract/ — JSON-артефакты, инвентарь типов, DB/HTTP доказательства, этот отчёт и source difference.
- .tools/ — вспомогательные локальные сборщики/проверки; без ключей в коде и без WRITE вызовов.

## Problems Fixed

Ложный отказ Docker при ошибке схемы; неверное предположение next_cursor; отсутствие распознавания полного каталога meta.total; nested api_key.scopes; usage counters. Включён реальный атомарный импорт/upsert с сохранением unknown как null. 43 релевантных теста прошли: live contract 7, sync 11, local READ-only 17, Windows 5, statistics 3. Проверены TTL кэша, отсутствие частичной публикации при конфликте parent chain, account status filter. Проверены Docker builds, sync_now.bat и status.bat.

## Remaining Problems

1. Нет доступного браузерного подключения для визуальной проверки Today/Yesterday и дерева.
2. Агрегаты /summary и insights различаются у источника; причина не установлена, паритет с summary не подтверждён.
3. Optional tracker/creative/breakdown imports OFF: не подтверждены необходимые identity/date/currency contracts. Это не блокирует доказанные базовые ad-факты.
4. Состояния accounts и родителей всех импортированных ads загружены. Budgets/bids не нормализованы; zero-spend архивные сущности без ad/day фактов отдельным архивом не импортируются.

## Safety

```text
ACTIONS_ENABLED=false
MetricFlow WRITE key used: NO
MetricFlow write requests sent: 0
Advertising entities modified: 0
```

ACTIONS_ENABLED=false. WRITE key used: NO. MetricFlow write requests: 0. Ads modified: 0. Own DB action requests/executions: 0. Только GET. READ key читается серверным коннектором из существующего secret file; в schema/samples/frontend его нет. Names/emails/links/owners/credential fields в образцах обезличены; provider IDs сохраняют формат. Credential/email pattern matches в JSON samples: 0. Actions/Rules/Telegram/AI не разрабатывались. Изменения только в указанном проекте.

Final independent privacy scan: 56 JSON evidence files, zero credential/email pattern matches. final-evidence.json contains only pseudonymized snapshot references, totals and validation results.

## FINAL RESULT

**V1 REAL READ SYNC: NOT READY** по полному набору критериев. Основной READ sync работает: schema VERIFIED, импорт и повтор успешны, Raw→PG→frontend API сверены. Обязательный незакрытый критерий READY — визуальная проверка через подключённый браузер. Source difference /summary vs insights остаётся отдельным открытым вопросом; основной dashboard опирается на insights и сверку с ним проходит. Optional imports явно выключены.

Browser availability was rechecked on 2026-10-08 (Europe/Moscow): apps=[], browsers=[]. This report retains the fixed 2026-10-07 audit snapshots; Today/Yesterday labels in the tables refer to 2026-10-07/2026-10-06, respectively.
