# PHASE 3 — SMART RULE ENGINE REPORT

Статус приёмки: **PHASE 3 SMART RULE ENGINE: READY**.
Локальная приёмка завершена 10 октября 2026 года (Europe/Moscow).

## Existing Architecture Audit

Существующий `services/automation/rules.py` реализует scheduled legacy правила,
связанные с Action Engine. Сохранён совместимым; новые записи используют
внутренние статусы SMART_DRY_RUN / SMART_ARCHIVED и не попадают в его scheduler.
Редактирование новых записей через legacy engine запрещено. Пользовательский
режим всегда DRY_RUN. Повторной таблицы rule_sets и второй финансовой модели нет.

## Rule Engine Architecture

Расширение существующего пакета `services/automation/`: `smart_schema`,
`smart_store`, `smart_core`, `smart_simulation`, `smart_models`, `smart_templates`.
Получение фактов — EconomicsAdapter; финансовые расчёты — Phase 2; выражения —
чистый evaluator; качество/пороги — decision; сохранение — immutable simulation.
Ни один новый модуль не импортирует Action Engine или рекламный HTTP provider.

## Rule Types

ROI_BELOW_MINIMUM, ROI_BELOW_TARGET, CPL_ABOVE_LIMIT, CPS_ABOVE_LIMIT,
NO_LEADS_SPEND, NO_APPROVED_SALES_SPEND, MINIMUM_LEADS_GATE,
MINIMUM_SALES_GATE, SPEND_THRESHOLD. Пять редактируемых системных шаблонов
не назначаются аккаунтам и не запускаются автоматически.

## ROI / CPL / CPS Logic

Готовые ROI/CPL/CPS/ориентиры получает Phase 2. Дополнительный estimated CPS
использует её же `ratio(spend, estimated_sales)` с Decimal. Фактический ROI,
approved CPS, observed purchase cost и прогноз различаются. Неизвестные
значения — null; нулевые лиды не дают бесконечный CPL. Отклонение ROI — п.п.
Целевой ROI может быть оптимизационным условием; результат не доказывает убыток.

## Thresholds

Наследование профиля / локальное значение / применённое значение сохраняются
отдельно. Пороги: расход, лиды, апрувы, покупки, обработанные решения, возраст
окна и maturity delay. Профиль Phase 2 получил обратно совместимые поля
minimum_spend / minimum_observed_purchases / minimum_data_age_hours.
Существующие финансовые формулы и strict eligibility не изменены.
Для нулевых лидов — собственный расход; TRUE-ветви OR определяют применимость
sample gates. Пороги апрувов относятся к условиям о подтверждённых продажах.

## AND / OR / UNKNOWN

Трёхзначная логика Kleene: FALSE доминирует в AND, TRUE — в OR; иначе наличие
UNKNOWN сохраняет UNKNOWN. UNKNOWN не приводится к bool. Например TRUE AND
UNKNOWN = UNKNOWN, TRUE OR UNKNOWN = TRUE. Неизвестные ветви учитываются
quality gate и не разрешают строгое WOULD_PAUSE. Максимум 40 узлов и 3 уровня.

## Economics Phase 2 Integration

Используются её routed evaluation, profile/observation versions, snapshot ID,
provenance, payout, approval policy и event deltas. Явно выбранный профиль
применяется в этом наборе, не меняя assignments. Без выбора действуют реальные
назначения Phase 2; профиль не угадывается по имени кампании. Account/Campaign/
AdSet — фильтры; единственная цель оценки — AD. Когорта группы не распределяется
по объявлениям. Неподтверждённые покупки не превращаются в approved.

## Seven-Day Evaluation

По умолчанию вчера и шесть предыдущих дней в Europe/Moscow. Сегодня отображается
неполным; custom — 1–31 день, будущий период запрещён. Timezone кабинета и
период сохраняются в каждой строке. Monetary значения разных валют не смешиваются.

## Approval / Late Conversion Handling

Плановый/зрелый фактический апрув рассчитывается Phase 2 с её min processed и
pending. Новый запуск читает актуальные локальные факты; сравнивает лиды,
покупки, approved/rejected/pending, CPL, ROI, rate, profile version и статус.
Прежние оценки не перезаписываются. Групповые подтверждения остаются прогнозом.
Integration test изменяет payout 16 → 20 и лиды 10 → 12 в изолированной БД:
новая симуляция получает новую версию профиля и CPL; старая сохраняет прежние
входы, метрики и причины. Рабочие рекламные факты этим тестом не изменяются.

## Data Quality & Safety Gates

Используются provider window, freshness, attribution, credential revision,
source timestamp, timezone, currency и maturity. Legacy доступность исторических
данных не считается подтверждением полноты. Каталожные AD без фактов видны с
неизвестными метриками. Provider/router выбирает одну семью источника, без
сложения Meta и MetricFlow. Meta отключён; его доступность не имитируется.

## DRY RUN

Рекламные actions запрещены. `action_eligibility=false`, `real_action=false`.
Нет ActionRequest/Execution/Queue записей. Аналитический сигнал, решение
симуляции и строгая пригодность Phase 2 — разные поля. Даже пригодность данных
не является разрешением выполнить сохранённый результат.

## Simulation Decisions

KEEP — условия риска не выполнены, не гарантия прибыльности; REVIEW —
предварительный риск/неполные подтверждения; WOULD_PAUSE — только кандидат
по заданной политике в симуляции; INSUFFICIENT_DATA — недостаточная информация
или выборка; DATA_STALE — источник/окно требует обновления. Прогноз по умолчанию
даёт REVIEW; отдельная политика позволяет прогнозный WOULD_PAUSE с явной меткой.

## Explanation Engine

Для каждого объявления: факт/порог/delta каждого условия, TRUE/FALSE/UNKNOWN,
источник, профиль/version, период/timezone, финансовые значения и качество,
pending/maturity, applied thresholds, причины и блокировки будущего действия.
Технический JSON не требуется для работы конструктора.

## Rule History

CAS revision для изменения/архива/copy/restore/simulate. Старые конфигурации
восстанавливаются новой версией. Симуляция содержит immutable definition,
profile inputs/version, observations, evaluation ID, source revision/timestamp,
факты, причины, дату и инициатора. Отдельный audit для изменений и запусков.

## Backend API

Namespace `/api/smart-rules` отделяет новую строго DRY_RUN семью от legacy
`/api/rules`. GET/POST list/create; GET/PUT/DELETE `/{id}`;
POST copy/restore/simulate; GET history и `/simulations/{id}`;
GET available-scopes; PUT grants. Workspace/actor берутся из session.
ADMIN — управление; OPERATOR — отдельный rule grant; VIEWER — просмотр.
Finance grant и rule grant независимы. CSRF/session/rate limits сохранены.

## PostgreSQL Migration

0010_economics → 0011_smart_rules. Четыре дополнительные таблицы:
rule_versions, rule_simulations, rule_audit_log, rule_grants. Наборы и selection
хранятся в существующих rules и immutable JSON versions; результаты — в
immutable simulation payload. Прежние таблицы не переписываются.
Rehearsal и concurrent CAS на изолированном restore: PASS.
Локальная миграция: PASS, 55 прежних таблиц сохранили полные count/hash.
Backup `backups/rules-activation-20261009T205338Z.dump`, 3266879 байт;
SHA256 `99b4738d867ac01c0498dcc4775807c16f9d953b8f48ae11f145a436a4bc02c5`.
Restore DB `mcc_rules_activation_20261009_205338`. Volumes не удалялись.

## Frontend UI

`/rules`: русский конструктор, правила, симуляции, история, безопасность,
профиль и scope filters, AND/OR groups, отдельные metric sources, thresholds,
архив/restore/copy, приватные роли, быстрые status filters и поиск AD.
Риск прогноза и строгий результат имеют разные цвета и подписи.

## Column Manager Integration

Новый scope `rule_ad` длиной 7 символов; существующий UI-1 manager/table.
Колонки, widths, DND, sort, private presets, logout persistence используют
те же CAS API и общую очередь CSRF. Старые scopes/configurations не заменяются.

## Browser E2E

Playwright Chromium: **15 уникальных сценариев PASS**, без retries/flaky:
3 сценария Phase 3 и 12 сценариев регрессии предыдущих фаз.
Console/page errors: **0**; рекламных mutation requests: **0**.

Drag-and-drop, resize/autofit, presets, logout/login persistence, сортировка,
длинные русские названия, горизонтальная прокрутка/sticky name и responsive
1440/768/390: PASS. ADMIN/OPERATOR/VIEWER и отдельные rule grants: PASS.
MetricFlow READ и настройки подключений: PASS; Meta остаётся отключённым.

Исправлены обнаруженные проблемы:

- Длинная подсказка порога включалась в accessible name поля. Добавлены стабильные
  `aria-label` и связанная через `aria-describedby` подсказка.
- Полный каталог повторно обходился для каждой строки Phase 2, а фильтр одного
  аккаунта применялся поздно; симуляция достигала timeout. Переиспользуется одна
  identity map, account filter применяется до расчёта; формулы сохранены.
- Браузерные сценарии используют отдельные пустые session contexts для ролей,
  адресные status selectors и реальные координаты DND после прокрутки.

Сценарии и команды: [WINDOWS_E2E.md](WINDOWS_E2E.md).

## Backend Tests

Полный прогон перед последними адресными изменениями: 356 PASS, 1 SKIP,
77 subtests PASS. После оптимизации — 80 целевых regression tests PASS;
после дополнительного теста долётов — 32 rule tests PASS. PostgreSQL auth/schema
тест, пропущенный в общем прогоне, отдельно PASS.
Изолированная PostgreSQL CAS/schema/workspace проверка: PASS, 59 model tables.
Scoped Ruff и mypy для новых модулей и изменённого evaluation: PASS.
Security scan: PASS. Старые нарушения глобального lint/typecheck вне этой фазы
не исправлялись и не объявляются успешно прошедшей глобальной проверкой.

## Frontend Tests

26 unit PASS; typecheck PASS; production build PASS; Docker images PASS.

## Data Integrity

Перед миграцией новая backup/checksum/restore verification; после миграции
55 прежних таблиц count/hash совпадают. После всех 15 браузерных сценариев
повторная проверка: **27 защищённых таблиц полностью совпали** по count/hash.
Сохранены пользователи, presets, profiles/assignments, approval observations,
правила и журналы действий/AI. Все прежние ключи рекламных объектов, фактов
и экономических snapshots сохранены. Полные строки всех восьми прежних
экономических snapshots совпадают с восстановленной исходной БД.
Raw READ snapshots выросли 773 → 783 из-за штатных чтений; прежние записи сохранены.
Fixtures создают только собственные users/profiles/rules/presets/sessions.
Фиктивные рекламные факты в рабочую БД не добавляются.

## Safety

Runtime проверены: ACTIONS_ENABLED=false, LOCAL_READ_ONLY=true,
AI_ENABLED=false, AI_AUTOPILOT_ALLOWED=false; Meta disconnected.
Readiness: database/migrations/schema/Redis OK; worker/scheduler heartbeat OK.
Очереди actions/AI пусты. Docker PostgreSQL/Redis и volumes сохранены.
Рекламный провайдер не вызывается новым контуром. CSP, CSRF, auth, rate limits
не отключались. Максимум 500 результатов и 2000 каталожных AD на workspace;
PostgreSQL statement timeout 10s, lock timeout 2s; Python deadline 10s.
Изолированная проверка времени: 90 AD — 1.073s; все 137 канонических AD — 1.320s. Исправлен избыточный повторный обход каталога; identity map загружается один раз на evaluation, single-account filter применяется перед расчётом. Формулы не менялись. Слишком большая выборка отклоняется с предложением сузить scope; повторного
Celery цикла или GET на каждое объявление нет. Фаза 4 не начиналась.

## Files Changed

- `services/automation/smart_*.py`, узкая защита `rules.py`.
- `services/storage/models.py`, `services/economics/schema.py`,
  `services/economics/evaluation.py` (переиспользование identity map).
- `backend/smart_rules_api.py`, auth/app и preferences scope.
- `migrations/versions/0011_smart_rules.py`.
- `frontend/app/rules`, API proxy, SmartRules и RuleExpression.
- Shared metric registry, column scopes, economics profile inputs, navigation/CSS.
- Backend/frontend/Chromium tests, PostgreSQL check script, этот отчёт.

## Remaining Blockers

Блокеров приёмки Phase 3 нет.
Неполные/устаревшие реальные периоды будут DATA_STALE до обычной успешной
READ-синхронизации полного окна. Не ослаблять проверки для получения кандидатов.

## HOW TO USE

1. Откройте <http://127.0.0.1:3000/rules> после входа.
2. Нажмите «Создать правило» или выберите системный шаблон.
3. Задайте название и экономический профиль; без выбора используются назначения.
4. Отметьте нужные аккаунты, при необходимости выберите Campaign/AdSet/AD.
5. Оставьте семь завершённых дней или выберите другой период.
6. Добавьте ROI condition и выберите факт либо прогноз; пустой порог наследует профиль.
7. Добавьте CPL/CPS condition и выберите целевой, максимальный или свой лимит.
8. Установите AND/OR и минимальные пороги отдельно; посмотрите значения наследования.
9. Сохраните набор и нажмите «Проверить правила».
10. Отфильтруйте кандидатов/REVIEW и откройте объявление для причин и неизвестных условий.
11. Откройте историю проверок; сравните дельты, профиль/version, источник и maturity.
12. Измените правило и сохраните новую версию, либо восстановите старую конфигурацию.
    Настройте и сохраните приватный набор колонок; все результаты остаются DRY RUN.

## FINAL STATUS

**PHASE 3 SMART RULE ENGINE: READY**

Advertising WRITE = 0. Phase 4 и рекламный Action Engine не активированы.
