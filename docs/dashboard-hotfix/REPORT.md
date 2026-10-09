# DASHBOARD MULTI-PROVIDER HOTFIX REPORT

Дата: 09.10.2026, Europe/Moscow. Проект: `E:/Creative_Factory/metric-control-center`.

## ROOT CAUSE — TODAY STATISTICS

За 09.10.2026 сам MetricFlow вернул 0 ad/day строк, без следующей страницы. PostgreSQL также содержит 0 фактов этой даты. Последний Today sync на момент диагностики: SUCCESS, 03:40 MSK, окно 08–10 октября, 20 строк / 2 GET; все строки относятся к 08.10. Ошибки sync, активного lease, quota block или второго namespace не обнаружены.

Пустая таблица не была потерей статистики в Multi-Provider: таблица требует явно выбранную календарную дату, а обзор использует текущую дату каждого кабинета. Реальная регрессия отображения — отсутствие каталожных строк при отсутствии фактов. Теперь сохраняются кабинеты и объясняется отсутствие данных, без вымышленных нулевых фактов.

## DATABASE EVIDENCE

READ-only срез до изменений, 03:41 MSK:

| Дата | Ad/day факты | Кабинеты с фактами | Spend USD | Impressions | Clicks | Leads | Purchases |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 07.10 | 27 | 2 | 652.66 | 57400 | 6234 | 156 | 31 |
| 08.10 | 20 | 3 | 476.76 | 48407 | 5267 | 114 | 14 |
| 09.10 | 0 | 0 | — | — | — | — | — |

Отсутствие строк за 09.10 не доказывает нулевой spend. SOURCE = metricflow, credential revision = 1. Все три каталожных кабинета ACTIVE/USD. Последнее окно complete = true, 08–10 октября, imported_at около `2026-10-09T00:40:01Z`; provider timestamp `2026-10-09T00:35:45.704552+00:00`. Факты 08.10 observed_at `00:40:00.030587Z`; 07.10 — `2026-10-08T20:20:00.032859Z`.

Подробный срез без credentials: `.tools/hotfix-before-diagnostics.json`. Использовались только SELECT-запросы для диагностики рабочей БД.

## METRICFLOW API

LIVE READ PASS: один GET insights 09.10–09.10 и один GET usage через существующий connector/ProviderManager; 0 строк, cursor = null. Использовано 2 GET, WRITE = 0, backfill не запускался. Квота до проверки 15/800, после 17/800. Provider usage ответил daily_used=17, daily_limit=20000, daily_remaining=19983.

Срез сохранён в `.tools/hotfix-live-before.json`. Исходный лог сохраняется; вывод logging в stderr был оформлен PowerShell как NativeCommandError, но API-запросы и диагностика завершились успешно. Повторные GET ради исправления формата лога не выполнялись.

## TIMEZONE ANALYSIS

Хост Windows и browser reporting model — Europe/Moscow; Docker/backend системный TZ — UTC; Celery scheduler — Europe/Moscow. Два кабинета имеют America/Los_Angeles, один — Europe/Kiev.

09.10, 03:30 MSK = 09.10, 00:30 UTC = 08.10, 17:30 Los Angeles = 09.10, 03:30 Kiev. У двух кабинетов выбранная дата 09.10 ещё не началась; у Kiev началась, но источник не доставил факты.

Семантика сохранена и явно подписана: обзор Today — текущий локальный день каждого кабинета. Табличные Today/Yesterday выбирают календарную дату Europe/Moscow; date_from/date_to включительны и передаются без преобразования в timestamp. Данные 08.10 не показываются в таблице 09.10. Пресеты пересчитываются после смены даты при focus и раз в минуту; Custom остаётся неизменным.

Исправлено сопоставление provenance обзора: для каждой timezone берётся источник именно её кабинетов, а не последнее окно чужой timezone.

## ACCOUNT VISIBILITY

Раньше `table_data` создавал account rows только при обходе DailyMetric. Теперь проверенный каталог выбранного провайдера присоединяется к реальным фактам: эквивалент LEFT JOIN в существующем Python data layer.

Без фактов: имя, external ID, статус, валюта, timezone, источник и понятное сообщение; метрики = null / «—». Настоящий 0 сохранён. daily_metrics не пополняется искусственными строками. Конкретные фильтры по кампании/ad/creative/GEO/labels не создают пустых искусственных объектов. Campaign/AdSet/Ad основаны на доказанных фактах и иерархии.

## PROVIDER WINDOW / ROUTING

Основной источник MetricFlow; Meta disconnected; fallback/action disabled. Окна выбираются с учётом текущей revision. Незавершённое окно или несовпадающая revision не разрешают выдачу его фактов; каталог при этом остаётся видимым. Исторические проверенные MetricFlow факты до появления provider windows сохранены, включая смешанные интервалы старой истории и новых complete windows. Два провайдера не суммируются.

Отдельно возвращаются connection health, sync status, coverage, freshness, window status, source timestamp и revision. HEALTHY не означает наличие фактов выбранного дня. Complete пустое окно — успешный sync с отсутствием данных.

## DUPLICATE SOURCE BANNERS

Исходный Dashboard выводил отдельную полноразмерную плашку для каждого из трёх аккаунтов, а Statistics добавлял свой DataSources. Теперь общий `SourceSummary` существует один раз для активной вкладки. Один provider — одна компактная строка; разные provider — «Несколько источников». Подробности по кабинетам раскрываются отдельно; источник также указан в account row.

Healthy PRIMARY имеет нейтральное оформление. Warning используется при stale/error или отсутствии требуемых данных. Routing/connection/sync/coverage статусы локализованы.

## CONNECTIONS UI

Вместо raw JSON в основном интерфейсе — таблица возможностей Meta/MetricFlow, подтверждённых/неподтверждённых READ операций и отключённых WRITE. ACTIONS_ENABLED=false не позволяет показать WRITE доступным.

API добавляет совместимый структурированный `provider_quota`; старый `quota.summary` сохранён для существующих клиентов. Разбирается только известное поле summary, с whitelist числовых counters, finite/non-negative checks. Общего JSON.parse всех строк нет.

Raw технические capabilities доступны только в закрытом по умолчанию блоке «Технические подробности». Credentials, App Secret, token, key, cookie, Authorization и credential URLs не передаются в эти компоненты.

Health probe сохраняет время измерения quota отдельно от sync и сохраняет уже подтверждённые READ capabilities текущей revision.

## QUOTA

Локальный лимит подтверждён runtime: **800 GET/day, UTC**. Provider daily_limit из настоящего usage: **20000**. UI показывает used/limit, remaining и progress; неизвестные provider counters остаются «Неизвестно». Provider usage явно имеет время проверки; счётчик локальных запросов берётся из текущей PostgreSQL quota.

Итоговый runtime snapshot 2026-10-09T01:27:27.415282+00:00: local=54/800; provider=51/20000, remaining=19949, измерен 2026-10-09T01:27:08.066670+00:00. Продолжающиеся scheduled READ учитываются в том же лимите; provider snapshot не подменяется текущим временем sync.

## TESTS

- Backend: **276 PASS + 77 subtests PASS**, 1 SKIP за 194.02 s; пропущенный PostgreSQL testcase отдельно **1 PASS** на изолированной БД.
- Hotfix regressions: 12 PASS, включая timezone/rollover, отсутствие/нулевые факты, incomplete/revision windows, primary, исторические периоды, quota/null values, health != coverage.
- Frontend: **17 unit/SSR PASS**, TypeScript PASS, Docker Next.js build PASS.
- Ruff новых Python-файлов PASS; mypy нового модуля PASS. Общий `ruff check .` обнаружил 397 замечаний существующего стиля репозитория; общий `mypy .` останавливается на дублирующем модуле migrations/schema_v1. Это не скрывалось и проверки не выключались. Массовое форматирование прежнего кода не выполнялось ради точечного P0 hotfix.
- Browser: **Playwright 8/8 PASS** за 121.22 s, Windows Chromium. Drag-and-drop PASS; mouse resize / double-click PASS; presets PASS; logout/login persistence PASS; Russian names / scroll / sticky / responsive PASS. Browser console errors=0, page errors=0, advertising WRITE=0. Browser timezone: Europe/Moscow. Today / Yesterday / 3 / 7 / 14 / 30 days, реальная иерархия и backend/proxy PASS. JSON и 9 audit-блоков сохранены локально в .tools/hotfix-browser-final.json.


До финального прогона исправлены два E2E locator и ожидания точных диапазонов дат. Backend подтвердил 429 RATE_LIMITED при плотном прогоне; provider smoke теперь ждёт минуту до старта, сохраняя API limit=240/minute. После повторов дождались естественного истечения login limit=10/15 min. Лимиты не выключались, Redis rate keys не очищались. Повторный полный прогон прошёл без ошибок.

## DATA INTEGRITY

Перед кодовыми изменениями создан `backups/hotfix-20261009T004151Z.dump`, 1 836 086 bytes. SHA256: `267ba15f458006d178deb8ac5732b79056960a698850e990300159977c6b7bef`.

Восстановление в отдельную `mcc_hotfix_restore_20261009_004151`: все 50 таблиц совпали с before по count/SHA256. Рабочая БД не заменялась; downgrade/drop/down-v не выполнялись. Старые backups и volumes сохранены.

Исходные users/sessions/presets/views/actions/rules/AI: 10 защищённых таблиц совпали по SHA256, остались 1 пользователь, 1 preset, 2 сохранённых представления и 3 кабинета. Временные browser users удалены. Изменения daily_metrics за 02–08 октября подтверждены штатными успешными Today / Yesterday / Last7 READ sync; 4 более старых дня совпали, потери исторических строк нет. Tracker не изменён. PostgreSQL и Redis containers/volumes сохранены.

`ACTIONS_ENABLED=false`, `LOCAL_READ_ONLY=true`, AI/Rules/Telegram control выключены. Advertising WRITE=0; Meta READ connection не активирован. Creative Factory не изменялся.

## FILES CHANGED

`services/providers/{presentation.py,router.py,metricflow.py,manager.py}`, `services/analytics/{table.py,dashboard.py}`, `backend/provider_api.py`, `frontend/components/{SourceSummary.tsx,DataSources.tsx,StatisticsTable.tsx,Statistics.tsx,ProviderCapabilities.tsx}`, `frontend/app/{page.tsx,settings/connections/page.tsx}`, `frontend/lib/reporting-period.ts`, `frontend/tests/hotfix.test.cjs`, `frontend/e2e/{dashboard-hotfix.spec.mjs,providers.spec.mjs}`, `docs/ui-1/WINDOWS_E2E.md`, `frontend/tsconfig.unit.json`, `tests/test_dashboard_hotfix.py`, `pyproject.toml` (pytest test extra), `.github/workflows/ci.yml` (pytest + frontend unit checks), `.gitignore` (dev caches), этот отчёт.

Локальные `.tools`, backups, actual schemas, `.env` и `.secrets` не публикуются в Git. GitHub репозиторий до сохранения был пуст. Snapshot существующей программы с hotfix отправлен в main: `3674c09f633a3dbe03112a3877578ec870fc9d9e`. Итоговая приёмка сохраняется отдельным коммитом после PASS всех восьми сценариев. Секреты проверены перед публикацией.

## HOW TO CHECK

1. Откройте http://127.0.0.1:3000/ и войдите своим пользователем.
2. «Обзор»: один source indicator; в деталях — отдельные состояния каждого кабинета и его локальная дата.
3. «Статистика» → «Кабинеты» → Сегодня / 09.10: видны все три кабинета. Пока API не доставил факты, метрики «—», два LA-кабинета объясняют, что дата ещё не началась.
4. Вчера / 08.10, 7/30 дней: сохранённые данные; кабинеты не исчезают из-за отсутствия фактов. Campaign → AdSet → Ad показывает реальную иерархию.
5. Поменяйте даты вручную: preset становится Custom. Проверьте ширины, порядок, сортировку и свои column presets после logout/login.
6. ADMIN → http://127.0.0.1:3000/settings/connections → «Доступные возможности и API quota»: таблица, counters и progress. «Технические подробности» закрыты; Meta не подключён, WRITE отключён.

## FINAL RESULT

DASHBOARD MULTI-PROVIDER HOTFIX: READY — программные исправления развёрнуты локально, финальный Playwright 8/8 PASS, backend/frontend PASS, данные и пользовательские настройки сохранены. MetricFlow LIVE READ PASS; Meta LIVE Disabled; Advertising WRITE=0. Следующая фаза не начиналась.