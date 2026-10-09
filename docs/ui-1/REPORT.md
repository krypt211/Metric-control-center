# PHASE UI-1 — Statistics UI Customization
Дата: 2026-10-08, Europe/Moscow. Проект: E:\Creative_Factory\metric-control-center.

## ROOT CAUSE
В Statistics.tsx уже были сохранены буквальные ASCII question marks в десяти русских подписях. Остальные русские строки этого же файла были корректными UTF-8. Это повреждение текста исходника, а не HTTP charset, шрифт, PostgreSQL или значения MetricFlow. Ключи метрик сохранились, поэтому названия восстановлены по подтверждённым полям. Механизм такого повреждения — запись кириллицы через кодировку, которая её не поддерживает; точную историческую команду нельзя установить только по повреждённому файлу.

## ENCODING FIX
Удалён повреждённый локальный mapping из Statistics.tsx. Правильные подписи перенесены в metric-registry.json: reach — Охват, frequency — Частота, inline_link_clicks — Клики по ссылке, registrations — Регистрации, app_installs — Установки приложения, landing_page_views — Просмотры посадочной страницы, video_views — Просмотры видео, video_3s_views — Просмотры видео 3 сек., video_p100_views — Досмотры видео 100%, video_starts — Запуски видео.
Statistics.tsx, OptionalStatistics.tsx и карточки page.tsx используют общий реестр. Все новые пользовательские строки сохранены непосредственно в UTF-8. Проверены исходники TSX и production JS bundle. Повреждённых вопросительных подписей и replacement characters не найдено. Подтверждение: compiled-labels.json; регрессионные проверки в test_preferences.py и columns.test.cjs.

## METRIC REGISTRY
47 реальных ключей, 5 категорий, 6 scopes. Обязательное name; ID, статус, валюта, timezone, budget/bid; spend, impressions, reach/frequency, clicks/unique/link clicks, CTR/CPC/CPM; leads/sales/conversions, CPL/CPA/CPS/CR; регистрации, установки, LP views и видео; tracker counts/regs/deposits; revenue/profit/ROI/EPC; идентификатор креатива и ads_count.
Доступность привязана к фактическому виду таблицы. Условные поля без данных отмечены «Нет данных». Лиды и конверсии трекера и Meta различаются в контексте таблицы. JSON — единственный источник метаданных для TypeScript и Python. Реестр не меняет формулы или контракт провайдера. NULL отображается как «—», числовой ноль остаётся нулём; валюта не выдумывается.

## COLUMN MANAGER
Над каждой основной таблицей есть «Настроить колонки»: поиск по названию/ключу/описанию, категории, checkboxes, выбор/скрытие группы, список порядка, ширина, управление наборами. Выбор сразу отражается в таблице. Название нельзя скрыть или убрать с первого места; переход по иерархии сохранён. Настройка не изменяет рекламную статистику.
Изменения рабочего вида сохраняются автоматически с debounce 450 ms; отпускание resize инициирует сохранение сразу. Перед logout очередь завершается. Состояния: загрузка, изменения, сохранение, сохранено, ошибка/конфликт. При конфликте предлагается загрузить серверные настройки, без слепого перезаписывания.

## DRAG AND DROP
Перенос за ⋮⋮ у заголовка. У края длинной таблицы реализована горизонтальная автопрокрутка. Можно перемещать все обычные колонки; name остаётся первым. В диалоге есть доступная альтернатива через кнопки вверх/вниз. Сортировка и resize имеют отдельные элементы управления.

## COLUMN RESIZE

Правая граница заголовка — pointer resize с cursor col-resize и pointer capture. Изменяется только выбранная колонка. Ограничения: 80–600 px, название 180–720 px. Двойной клик подбирает ширину по видимой странице с ограничением максимума; доступен сброс ширин и числовой ввод в диалоге. Слева закреплено название, горизонтальная прокрутка сохраняется.
Mouse resize, shrink, ordinary-column resize and double-click autofit: PASS (Windows Chromium).

## USER PRESETS
Шесть неизменяемых системных шаблонов: Базовые, Трафик, Конверсии, Финансы, Креативы, Трекер. Можно создать несколько собственных наборов, сохранить текущий, сохранить как новый, переименовать, дублировать, удалить, восстановить шаблон, выбрать основной и переключить набор.
Рабочий вид хранится отдельно от шаблона: изменения переживают refresh, смену уровня и повторный вход даже до «Сохранить набор». «Сохранить набор» обновляет собственный шаблон; системный сохраняется как копия. При переключении с изменённого шаблона показывается предупреждение. Чтобы изменения остались при последующем переключении между шаблонами, нажмите «Сохранить набор».
Основной набор и последний выбранный набор хранятся отдельно для каждого scope; при повторном входе восстанавливается последний рабочий вид.

## DATABASE
Миграция 0008_column_preferences поверх 0007_auth:
- user_column_presets: UUID, user_id FK, workspace_id, scope, name, config_json JSONB, revision, timestamps, индекс владельца/workspace/scope.
- user_table_preferences: composite PK (user_id, workspace_id, scope), active/default IDs, рабочая config_json JSONB, revision, updated_at.

Миграция добавляет только эти таблицы. JSON schema version = 1; revision защищает от конкурентных изменений. Сохранённые ключи/порядок не сбрасываются при добавлении новых метрик; устаревшие ключи игнорируются при чтении.

Создана резервная копия backups/mcc-20261008T122352Z-6e603495.dump (1 648 377 bytes).
До/после миграции и проверок совпали количества строк и SHA-256 в 15 защищённых таблицах: users, ad_accounts, entities, campaigns, adsets, ads, creatives, daily_metrics, tracker_metrics, breakdowns, entity_current_state, read_statistics, action_requests, action_executions, action_logs.
Основные данные: 1 исходный пользователь, 3 кабинета, 273 сущности, 48 кампаний, 105 ad sets, 120 ads, 375 daily facts, 1040 optional observations. Тестовые пользователи/настройки удалены после проверки; исходный пользователь не изменён.

## USER PROFILE
Identity определяется существующей PostgreSQL-сессией. user_id/workspace не принимаются от браузера. Любой авторизованный пользователь может менять только собственные UI-настройки текущего workspace. Чужой ID возвращает 404. Сквозные проверки выполнены на временных viewer/operator; постоянные аккаунты и пароли пользователя не менялись. Наборы хранятся в PostgreSQL и доступны другим сессиям того же пользователя, без зависимости от localStorage.

## BACKEND API

- GET /api/preferences/columns/{scope}: системные/собственные наборы + текущий рабочий вид.
- POST /api/preferences/columns: создать собственный набор и выбрать его.
- PUT /api/preferences/columns/presets/{id}: сохранить/переименовать.
- DELETE /api/preferences/columns/presets/{id}: удалить собственный набор; revision и preference_version обязательны.
- PUT /api/preferences/columns/{scope}/view: сохранить рабочий вид.
- POST /api/preferences/columns/{scope}/activate: выбрать/восстановить шаблон.
- PUT /api/preferences/columns/{scope}/default: выбрать основной.

Scopes: account, campaign, adset, ad, creative, tracker.
Все mutations требуют существующую identity, Origin и CSRF. Проверяются ключи, scope, обязательная первая колонка, уникальность колонок, имя, целочисленная ширина и её ограничения. PostgreSQL advisory lock и optimistic revisions возвращают 409 при конфликте.
В READ ONLY разрешена узкая запись приватных UI-настроек. Advertising actions, AI, Rules, Telegram не включены.
GET /api/stats/table и GET /api/stats/optional получили sort_key/sort_direction и пагинацию. Сортируется весь отфильтрованный набор до slice; Decimal для чисел, стабильный tie-break, NULL в конце обоих направлений. Финансовые формулы и provider contract сохранены.

## TESTS
PASS:

- Полный backend suite: 228 tests, 227 passed, 1 PostgreSQL integration initially skipped.
- Этот PostgreSQL integration запущен отдельно на работающей БД: 1 passed.
- Три дополнительные проверки после расширения покрытия: stale delete, invalid sort в пустом workspace, optional sorting до пагинации с неизвестными финансами: 3 passed.
- Итого 231 различных backend tests проверены.
- Frontend unit + server rendering: 13 passed.
- TypeScript: PASS.
- Реальные HTTP/Next/FastAPI/PostgreSQL: login, dashboard, все 6 scopes, несколько наборов, rename/duplicate/default/delete, ownership, sequential и concurrent conflicts, refresh через повторное чтение, logout/login, Docker restart sessions/settings, сортировка всех строк до пагинации: PASS.
- Миграция/колонки PostgreSQL и сохранность исходных данных: PASS.
- UTF-8 исходники и production bundle: PASS.

Evidence: http-evidence.json, data-preservation.json, read-only-evidence.json, compiled-labels.json.

BROWSER: PASS (2026-10-08).
Native Chromium/Windows: 6 E2E passed, 0 failed. Console errors = 0, page errors = 0, advertising mutations = 0. Full report: [BROWSER_ACCEPTANCE.md](BROWSER_ACCEPTANCE.md). Real data counts/hashes preserved; temporary users cleaned up.

## FRONTEND BUILD
PASS. Production Next.js build, TypeScript и route /api/preferences/columns/[[...path]].
Backend image получает единственный JSON registry; исключения в .dockerignore включают только нужный файл frontend/lib/metric-registry.json.

## DOCKER
PASS. PostgreSQL head = 0008_column_preferences. Пересобраны backend/migrate/worker/scheduler/frontend. Приложение запущено на http://127.0.0.1:3000; backend 127.0.0.1:8000 healthy, PostgreSQL/Redis healthy. READ worker и scheduler возобновлены.
Проверка перезапуска охватила frontend/backend/postgres/redis; настройки и PostgreSQL-сессия сохранились. Volumes не удалялись.
ACTIONS_ENABLED=false; LOCAL_READ_ONLY=true; AI_ENABLED=false; WRITE-key не смонтирован в backend. Рекламные action requests/executions/logs = 0. Профили действий/AI/Telegram не запускались.

## FILES CHANGED
Frontend:

- frontend/lib/metric-registry.json — общий реестр.
- frontend/lib/metric-registry.ts — типы, scopes, labels.
- frontend/lib/column-model.ts — модель отображения/ширины/порядка/формата.
- frontend/lib/use-column-preferences.ts — приватные настройки, очереди, autosave, конфликт версии.
- frontend/components/ColumnManager.tsx — настройка и наборы.
- frontend/components/StatisticsTable.tsx — fixed table, sort, drag, resize, tooltips.
- frontend/components/StatisticsGrid.tsx — загрузка, серверная сортировка, пагинация.
- frontend/components/Statistics.tsx — подключение core hierarchy к общей таблице.
- frontend/components/OptionalStatistics.tsx — подключение creative/tracker.
- frontend/components/SessionBar.tsx — завершение сохранений перед logout.
- frontend/app/page.tsx — подписи карточек из общего реестра.
- frontend/app/globals.css — стили таблицы/диалога/resize/sticky.
- frontend/app/api/preferences/columns/[[...path]]/route.ts — authenticated proxy.
- frontend/package.json, frontend/package-lock.json — test scripts/Playwright.
- frontend/tsconfig.json — исключения test artifacts.
- frontend/tsconfig.unit.json — сборка unit/SSR тестов.
- frontend/tests/columns.test.cjs — 13 unit/SSR тестов.
- frontend/playwright.config.mjs — локальные E2E.
- frontend/e2e/columns.spec.mjs — сценарии браузера.
- frontend/e2e/accounts.py — изолированные временные аккаунты/cleanup.
- frontend/.dockerignore — исключения тестовых artifacts.

Backend/data:

- backend/preferences_api.py — owned preferences endpoints/validation/concurrency.
- backend/app.py — подключение router, узкое READ исключение, sorting parameters.
- backend/auth.py — разрешение приватных UI mutations при действующей auth/CSRF.
- services/preferences/__init__.py — пакет.
- services/preferences/registry.py — общий JSON, validation/normalization/sort.
- services/storage/models.py — две новые модели.
- services/analytics/table.py — сортировка до пагинации, существующий bid из current state.
- services/analytics/optional.py — сортировка/пагинация без изменения scope/formulas.
- migrations/versions/0008_column_preferences.py — аддитивная миграция.

Testing/build/docs:

- tests/test_preferences.py — API/security/concurrency/encoding/registry tests.
- tests/test_statistics.py — full sorting before pagination, empty-workspace validation.
- tests/test_full_read.py — optional sorting/pagination/NULL regression.
- scripts/check_ui_preferences.py — repeatable live HTTP/PostgreSQL acceptance.
- scripts/ui_data_snapshot.py — counts/hashes of protected data, no raw secrets.
- docker/backend.Dockerfile — доставка JSON registry.
- .dockerignore — registry exception.
- .gitignore — test artifact exclusions.
- docs/ui-1/REPORT.md — этот отчёт.
- docs/ui-1/WINDOWS_E2E.md — запуск браузерных тестов.
- docs/ui-1/http-evidence.json — реальные HTTP результаты.
- docs/ui-1/data-preservation.json — до/после сохранность таблиц.
- docs/ui-1/read-only-evidence.json — READ gates/actions.
- docs/ui-1/compiled-labels.json — production UTF-8 проверка.
- docs/ui-1/verification.json — итоги тестов/health.

Browser acceptance additions:

- frontend/e2e/columns.spec.mjs
- frontend/playwright.config.mjs
- docs/ui-1/BROWSER_ACCEPTANCE.md
- docs/ui-1/browser-playwright.json
- docs/ui-1/browser-verification.json
- docs/ui-1/browser-data-preservation.json
- docs/ui-1/browser-read-only.json

## HOW TO USE

1. Откройте http://127.0.0.1:3000, войдите и выберите «Статистика», «Креативы» или «Трекер». Нажмите «Настроить колонки».
2. Найдите метрику по названию/ключу и включите checkbox. Можно выбрать целую группу.
3. Снимите checkbox, чтобы убрать показатель. Название остаётся обязательным.
4. Тяните правый край заголовка вправо/влево. Двойной клик — автоподбор. Дождитесь «Рабочий вид сохранён».
5. Перенесите ⋮⋮ у заголовка или используйте ↑/↓ в диалоге.
6. Введите «Название нового набора» и нажмите «Создать набор».
7. После изменения собственного шаблона нажмите «Сохранить набор». Системный сохраняется как собственная копия.
8. Выберите нужный набор и нажмите «Сделать основным». Для каждого уровня настройка отдельная.
9. После повторного входа откройте тот же уровень: последний набор, ширина, порядок и сортировка восстановятся автоматически. Другой набор выбирается через selector; «Восстановить настройки набора» возвращает его сохранённый шаблон.

## FINAL STATUS

STATISTICS UI CUSTOMIZATION: READY
UI-1 BROWSER ACCEPTANCE: PASS

Implementation, build, migration, HTTP persistence and final Windows Chromium browser acceptance PASS. Six E2E passed; browser console/page errors = 0. See BROWSER_ACCEPTANCE.md.
