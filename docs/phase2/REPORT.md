# PHASE 2 — AD ECONOMICS REPORT

Дата проверки: 2026-10-09. Проект: `E:\Creative_Factory\metric-control-center`.

## Architecture

Модуль `services/economics` отделён от получения статистики и выполнения действий.
`schema.py` валидирует команды; `core.py` выполняет чистые Decimal-расчёты;
`store.py` управляет версиями, назначениями, когортами, правами и audit;
`evaluation.py` читает существующие routed facts и сохраняет воспроизводимые оценки.
FastAPI предоставляет authenticated API, Next.js — proxy и страницу `/economics`.
Новые финансовые показатели не записываются в рекламные факты.

## Financial Formulas

`p` — выплата, `a` — применённый апрув от 0 до 1, `t`/`m` — целевой/минимальный ROI
в процентах, `s` — расход, `l` — лиды, `approved` — совместимые подтверждённые продажи.

| Показатель | Формула |
| --- | --- |
| Expected Revenue Per Lead | `p × a` |
| Target CPL | `p × a / (1 + t / 100)` |
| Maximum CPL | `p × a / (1 + m / 100)` |
| Target Approved CPS | `p / (1 + t / 100)` |
| Maximum Approved CPS | `p / (1 + m / 100)` |
| Actual CPL | `s / l`, при известных данных и `l > 0` |
| Observed Purchase Cost | `s / Meta Purchases`, при положительном счётчике |
| Approved CPS | `s / approved`, при доказанной совместимости |
| Estimated Revenue | `l × a × p` |
| Estimated ROI | `(Estimated Revenue - s) / s × 100`, при `s > 0` |
| Actual ROI | `(Actual Revenue - s) / s × 100`, при `s > 0` и подтверждении |

Денежные операции выполняются с Decimal и precision 64; API возвращает decimal
strings с восемью знаками. Двоичные float для финансовой арифметики не используются.
Неизвестное значение остаётся `null`; ноль не заменяет неизвестность. ROI ≤ −100%
и Target ROI ниже Minimum ROI отклоняются. Валюты не конвертируются автоматически.

Эталонные примеры A–H проверены unit-тестами: 16 USD / 30% / 20% дают Target CPL
4.00 USD; расход 40 и 10 лидов дают прогноз 48 USD и ROI 20%; три подтверждённые
продажи с выплатой 16 при расходе 60 дают фактический ROI −20% только при совместимости.

## Profiles

Поддержаны создание, изменение, копирование, soft delete, восстановление и история.
Профиль содержит Name, Offer, GEO, Payout, Currency, ROI, плановый апрув, источник
лидов, пороги, задержку созревания, политику апрува, actor, timestamps и version.
Изменение и восстановление требуют текущую version; конфликт возвращает 409.

Назначения задаются явно: группа Offer/GEO, account, campaign, adset, ad и effective
dates. Более конкретное назначение имеет приоритет. Сходство названий не используется.
Групповой профиль выбирается только по точному Offer/GEO или явно пользователем.
Историческая ручная когорта сохраняет Offer/GEO и версию профиля на момент создания:
изменение GEO профиля не переименовывает старые подтверждения.

## Approval Rate

Наблюдаемый апрув: `Approved / (Approved + Rejected)`. Pending показан отдельно.
Одна когорта обновляется с CAS version и audit; её новые итоги заменяют прежние.
Перекрывающиеся окна разных когорт одного scope/profile отклоняются.

Политика `planned` всегда применяет плановый процент. `mature_actual` использует
ручной процент только после минимального числа обработанных решений, окончания
настроенной задержки и отсутствия Pending. До этого применяется плановый процент
с объяснением. Порог не является утверждением статистической точности.

Групповой апрув может использоваться дочерними объектами для прогноза. Число Approved,
фактическая выручка и Actual ROI группы не распределяются по объявлениям.

## Actual vs Estimated ROI

Отдельно сохранены Meta Leads/Purchases/Conversions и Tracker Leads/Sales/Conversions.
Ни Meta Purchases, ни Tracker Sales автоматически не становятся Approved.
Для ручной фактической выручки проверяются scope, полный период, валюта, timezone,
provider, источник лидов, Offer/GEO, база когорты, явное подтверждение атрибуции
и оплачиваемости. Несовместимость оставляет Actual ROI неизвестным.

Качество предоставляется по каждой метрике: `ACTUAL_VERIFIED`, `ACTUAL_MANUAL`,
`ESTIMATED`, `UNKNOWN`. Ручной ввод явно обозначен `ACTUAL_MANUAL`; интерфейс
не выдаёт его за автоматическую проверку CRM. Старый provider ROI не подменён прогнозом.
При несовместимой валюте сохраняется валюта расхода, денежные ориентиры и ROI
профиля становятся неизвестными; конвертация отсутствует.

## Minimum Lead/Sale Thresholds

Сохраняются Minimum Leads, Minimum Sales и тип продаж: approved, observed, estimated.
Недостаточная выборка показана отдельным статусом. Будущий eligibility всегда
требует подтверждённые продажи независимо от выбранного прогнозного порога.
Неизвестные Approved не проходят порог даже при наличии Meta Purchases.

## Late Conversion Handling

Существующий last7 reconciliation сохранён: `workers/ingestion.py` собирает последние
семь дней по прежнему расписанию и с прежней quota. Новый scheduler не добавлен.
Оценка пересчитывается при чтении обновлённых локальных фактов; snapshots содержат
точные входы, source facts, выбранный источник лидов, параметры/версию профиля,
версии наблюдений, фильтры, период и maturity. Старые оценки сохраняются.
Показаны дельты лидов и продаж, время обновления и причины изменений.
Созревание само по себе создаёт новую оценку даже без изменения числа событий.

## Seven-Day Evaluation

По умолчанию выбраны семь завершённых дат относительно `Europe/Moscow`: вчера
и шесть предшествующих дней, обе границы включены. Каждая дата интерпретируется
в существующем timezone аккаунта; старые правила времени статистики сохранены.
Сегодня не входит в основной период. Доступны сегодня, вчера, 3/7/14/30 дней
и произвольный диапазон. Timezone и даты показаны явно; maturity проверяется
от конца периода в timezone аккаунта с добавлением задержки профиля.

## Rule Engine Contract

Оценка содержит scope/id, период, валюту, расход и независимые счётчики, payout,
плановый/применённый/наблюдаемый апрув, CPL/CPS, прогнозную и фактическую выручку/ROI,
пороги, status, metric provenance, machine-readable reason codes и evaluation ID.
`eligible_for_rule_evaluation` требует зрелые совместимые подтверждения, достаточную
выборку и актуальные источники. `actions_enabled` всегда `false`.
Этот контракт готовит будущий DRY RUN; выполнение правил не включено.

## Backend API

Все пути начинаются с `/api/economics`:

| Метод и путь | Назначение |
| --- | --- |
| GET `/settings` | Профили, назначения, наблюдения, options и доступы |
| POST `/preview` | Валидированный расчёт ориентиров |
| POST `/profiles` | Создание |
| PUT `/profiles/{id}` | Новая версия |
| POST `/profiles/{id}/copy` | Копия |
| DELETE `/profiles/{id}` | Soft delete с version |
| POST `/profiles/{id}/restore` | Восстановление с version |
| POST / DELETE `/assignments[/{id}]` | Явные назначения |
| POST `/observations` | Создание/версионное исправление когорты |
| PUT `/grants` | ADMIN разрешает OPERATOR редактировать |
| GET `/audit` | История изменений |
| GET `/evaluate` | Оценки с фильтрами, сортировкой и pagination |
| GET `/evaluations` | Исторические snapshots |

Workspace и actor берутся из серверной session. Session auth и CSRF обязательны.
ADMIN управляет экономикой workspace, OPERATOR редактирует только с явным grant,
VIEWER читает. Экономические записи разрешены в LOCAL_READ_ONLY узким исключением;
рекламные endpoints остаются заблокированы. Все изменения экономики имеют audit.

## PostgreSQL Migration

Проверена исходная revision `0009_providers`; текущая — `0010_economics`.
Аддитивно добавлены `economics_profiles`, `economics_assignments`,
`approval_observations`, `economics_evaluations`, `economics_audit_log`,
`economics_grants`. Индексы, ограничения, workspace, версии и timestamps сохранены
в настоящей Alembic migration. Destructive downgrade запрещён кодом migration.

Два независимых backup/restore проверены, миграция отрепетирована на восстановленной БД.
Перед live migration создан backup `backups/economics-activation-20261009T080815Z.dump`,
размер 1,991,780 bytes, SHA256:
`448af8602cdf3b79f5a9b0bbc66369a66da32c2dca79c403f276a28e543ea343`.
Восстановление в `mcc_economics_activation_20261009_080815` подтвердило сохранность.
49 прежних таблиц совпали по полным count/hash до и после миграции
(единственное ожидаемое исключение — `alembic_version`). Docker volumes сохранены.

## Frontend UI

Раздел `/economics`: «Финансовая статистика», «Профили», «Апрув и назначения».
Карточки относятся к выбранному объекту, суммы разных валют не объединяются.
Account → Campaign → AdSet → Ad использует реальную иерархию.
Есть объяснения качества, maturity, порогов, несовместимости и поздних изменений.
Формы профиля и когорты сохраняются в PostgreSQL; версия и история доступны в UI.

Offer/GEO фильтры используют уже имеющиеся labels/breakdowns. При отсутствии этих
данных опции недоступны с объяснением; GEO не угадывается по имени кампании.
Выбор самого экономического профиля остаётся доступным независимо от breakdowns.
Будущий CSV/CRM import не реализован, поскольку подтверждённый источник не предоставлен.

## Column Manager Integration

Добавлены независимые `eco_account`, `eco_campaign`, `eco_adset`, `eco_ad`.
Исходные 47 метрик и существующие presets сохраняют прежние ключи и поведение.
Новые финансовые метрики доступны через общий registry и UI-1: visibility, порядок,
resize, autofit, sorting, private presets и persistence после logout/login.
Новые scopes помещаются в существующую колонку PostgreSQL; старые preferences
не переписывались. Записи форм, preferences и logout сериализованы для CSRF rotation.

## Browser E2E

**Playwright: PASS, 12 уникальных сценариев.** Приёмка объединяет несколько
реальных Windows Chromium прогонов; для каждого сценария взят его последний
результат после необходимых исправлений. Сценарии, затронутые проблемами,
перезапущены целевыми прогонами; rate limits оставались включены.

| Проверка | Результат |
| --- | --- |
| UI-1 regression | 6/6 PASS |
| Dashboard/catalog/timezones/proxy | 1/1 PASS |
| Provider READ connections | 1/1 PASS |
| Economics profiles/cohorts/columns/roles | 4/4 PASS |
| Реальный drag-and-drop мышью | PASS |
| Resize / double-click autofit | PASS |
| Private presets / переключение / удаление | PASS |
| Width / order / sorting после logout/login | PASS |
| 1440 / 768 / 390 px | PASS |
| Горизонтальная прокрутка / неизменное положение sticky name | PASS |
| Browser console errors / page exceptions | 0 |
| Advertising mutation requests из браузера | 0 |

Локальные доказательства: `.tools/economics-browser-summary.json` и raw JSON
прогонов в `.tools/economics-browser-*.json`. Они не публикуются с реальными
account names. URL ручной проверки: <http://127.0.0.1:3000/economics>.

Исправления, обнаруженные при приёмке:

- Независимые Meta Purchases/Conversions добавлены в экономический registry.
- Валюта профиля больше не подменяет валюту расходов при несовместимости.
- Logout ожидает завершения CSRF-записей экономики и preferences.
- Фильтры и длинные русские session labels адаптированы для узкого экрана.
- Широкая sticky-таблица ограничена собственной областью прокрутки.
- Snapshot сохраняет выбранный источник лидов и полный контекст оценки.
- Изменение GEO профиля не переименовывает существующую ручную когорту.
- Тест будущей даты вычисляет её относительно timezone аккаунта.
- Тест каталога сравнивает строки с текущим каталогом, вместо устаревшего числа 3.
- Drag-and-drop сценарий переносит одновременно видимые колонки мышью через промежуточные точки и проверяет немедленный DOM-порядок.
- Ролевые контексты стартуют с пустыми cookies/origins, без наследования ADMIN session.
- Checkbox grants проверяется после подтверждения сервера; выдача и отзыв проверены в UI оператора.

## Tests

- Backend: **325 passed, 1 skipped, 77 subtests passed** (224.12 s).
- Пропущенная environment-dependent PostgreSQL auth/schema проверка выполнена
  отдельно на восстановленной БД: **PASS**, 56 таблиц согласованы с metadata.
- Реальная PostgreSQL concurrency: одновременные изменения одной версии дают
  один успех и один 409; перекрывающиеся когорты — один успех и один 409;
  workspace isolation — **PASS**, advertising facts modified = 0.
- Frontend unit: **22/22 PASS**; TypeScript: **PASS**; Docker build: **PASS**.
- Ruff check/format для Python экономики, API, tests и новой fixture: **PASS**.
- mypy `services/economics --follow-imports=silent`: **PASS**, 6 files.
- Проверка секретов `scripts/security_scan.py`: **PASS**.

Весь старый Python-код не переформатировался. В репозитории до этой фазы были
глобальные ошибки Ruff и конфликт discovery mypy для migrations; scoped PASS
не означает, что глобальные `ruff check .` / `mypy .` полностью чисты.

## Data Integrity

Миграция: **PASS**, сохранены все 49 прежних таблиц. После очистки fixtures 18
защищённых таблиц совпали с baseline: users, private presets/preferences и таблицы
Actions/Rules/AI/Telegram. Временных test users и строк экономики осталось 0.
Все исходные primary keys девяти рекламных таблиц сохранены: accounts, entities,
campaigns, adsets, ads, creatives, daily metrics, tracker metrics, raw snapshots.
READ sync продолжает работу: добавленные записи и изменения статистики/служебных
timestamps после миграции являются обычным обновлением источника, а не обещанием
постоянного hash всей live БД. Во время самой миграции сравнение было точным.
Локальные подтверждения: `.tools/economics-activation.json`,
`.tools/economics-final-integrity.json`, `.tools/economics-advertising-integrity.json`.
Тестовые пользователи, профили и когорты удаляются только по nonce/ID текущего
прогона. Фиктивные конверсии в рекламные таблицы не добавлялись.

## Files Changed

- Backend: `backend/{app,auth,preferences_api,economics_api}.py`.
- Модель: `services/economics/{schema,core,models,store,evaluation,__init__}.py`,
  `services/storage/models.py`, `services/analytics/table.py`,
  `services/preferences/registry.py`.
- Migration: `migrations/versions/0010_economics.py`.
- Frontend: `app/economics/page.tsx`, economics proxy, preferences proxy,
  `components/{Economics,EconomicsTable,EconomicProfiles,EconomicSettings,SessionBar}.tsx`,
  `app/globals.css`, `lib/{economics,economics-api,column-model,use-column-preferences}.ts`,
  `lib/metric-registry.json`, `tsconfig.unit.json`.
- Проверки: `tests/test_economics*.py`, `scripts/check_economics_postgres.py`,
  `frontend/tests/economics.test.cjs`, `frontend/e2e/economics.spec.mjs`,
  `frontend/e2e/economics_accounts.py`, guards существующих fixtures,
  `frontend/e2e/dashboard-hotfix.spec.mjs`.
- Документация: `docs/phase2/REPORT.md`, `docs/phase2/WINDOWS_E2E.md`.

Локальные backups, `.tools` evidence, credentials и browser artifacts не публикуются.
Все завершённые изменения сохраняются отдельными commits и отправляются в `main`.

## Safety

Обязательные флаги сохранены: `ACTIONS_ENABLED=false`, `LOCAL_READ_ONLY=true`,
`AI_ENABLED=false`, `AI_AUTOPILOT_ALLOWED=false`. Meta остаётся отключённой.
Action Engine, Rules, AI, Telegram control не запускались. API quota и scheduler
не увеличены; auth/CSRF/workspace/rate guards сохранены. Экономический API
читает собственную БД и не вызывает рекламные WRITE endpoints.
Creative Factory вне каталога этого проекта не изменялся.
Итоговая runtime сверка: все четыре флага имеют указанные значения, Meta status =
`disconnected`, action_requests = 0, action_executions = 0. Advertising WRITE requests
MetricFlow/Meta = 0 по проверенным путям исполнения, guards и browser request audits;
рекламные сущности не изменялись командами этой фазы. Сетевой packet capture не выполнялся.

## HOW TO USE

1. Войти в панель и открыть ссылку **«Экономика рекламы»**:
   <http://127.0.0.1:3000/economics>.
2. Открыть **«Профили»**, выбрать создание нового, указать Name, Offer и GEO.
3. В поле **«Выплата за апрув»** задать выплату за одну оплачиваемую продажу,
   выбрать Currency и источник лидов Meta/Tracker.
4. Установить **«Целевой ROI, %»**, например 20.
5. Установить Minimum ROI, например 0; он должен быть не выше Target ROI
   и строго больше −100.
6. Задать Planned Approval в процентах и пороги лидов/продаж/обработанных решений,
   тип порога продаж, задержку и политику применения фактического апрува.
   Нажать **«Рассчитать ориентиры»**, затем **«Сохранить профиль»**.
7. На **«Апрув и назначения»** ввести cohort, scope, период, Approved/Rejected/Pending,
   выплату, валюту, timezone, provider, источник лидов и комментарий.
   Подтверждать атрибуцию и оплачиваемость только при наличии соответствующих данных.
   Для исправления открыть ту же когорту: новая версия заменит прежние итоги.
8. Здесь же выбрать профиль, уровень **account** и нужный аккаунт, задать effective
   dates и сохранить назначение. Для кампании выбрать campaign и конкретный ID.
9. Вернуться на **«Финансовая статистика»**, выбрать профиль/объект оценки:
   карточки и таблица показывают Target CPL и Maximum CPL.
10. Estimated ROI отмечен прогнозом. Actual ROI появится только для сопоставимых
    подтверждённых данных; «—» означает неизвестность. Открыть объяснения источников.
11. Оставить основной период **«7 завершённых дней»**, проверить даты/timezone,
    перейти Account → Campaign → AdSet → Ad, изучить sample/maturity и причины.
    В **«Настроить колонки»** добавить нужные финансовые метрики и сохранить свой набор.

## FINAL STATUS

`PHASE 2 AD ECONOMICS: READY`

Блокеров приёмки нет. Раздел развёрнут локально; исходные данные, пользователи и
presets сохранены. Изменения закоммичены и отправлены в GitHub `main`.
Следующая фаза не начинается.
