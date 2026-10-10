# Центр рекомендаций без AI

Статус: **READY**. Локальная приёмка: 10 октября 2026, Europe/Moscow.

## Реализовано

Раздел `/recommendations` собирает последние сохранённые проверки активных
правил Phase 3. Показывает кандидатов, предварительные сигналы, недостаток
данных и устаревшие окна. Можно открыть объявления набора, отфильтровать
результат, найти название/ID и посмотреть причины, метрики, профиль, апрув,
пороги и изменения между симуляциями.

Сначала показаны наборы, требующие новой проверки, затем WOULD_PAUSE, REVIEW,
DATA_STALE, INSUFFICIENT_DATA, KEEP. Приоритет действует внутри страницы наборов.
Используются общие Column Manager и объяснения Phase 3. Scope `rule_ad`
сохраняет порядок, ширины, сортировку и presets между разделами.
«Правило и история» открывает выбранное правило через `/rules?rule=ID`.

## Данные и ограничения

GET `/api/smart-rules/recommendations` читает PostgreSQL: один последний результат
на активное правило с детерминированным порядком created_at/ID. Сводка извлекает
маленькие JSON-поля counts/period/total; полные строки читаются только при
открытии результата. Пагинация — 50 наборов, API позволяет 1–100.
Архив и legacy rules исключены. Таблицы и миграция не добавлялись.

Счётчики — пары правило/объявление на текущей странице. Объявление может входить
в несколько наборов с разными профилями и периодами. Денежные итоги между
правилами не суммируются. Метрики и решения взяты из Phase 3; финансовые формулы
не дублируются. Неизвестные значения сохранены, прогноз отличается от факта.

Пометки о повторной проверке:

- Проверка ещё не запускалась.
- Версия правила изменилась после симуляции.
- Результату больше 36 часов.
- Изменился rolling period или правило вне effective dates.
- После запуска менялась экономика workspace: профили, назначения или апрувы.

Проверка экономики консервативная: изменение другого профиля workspace также
может дать предупреждение. Возраст результата не подтверждает свежесть
исходных фактов. Новые рекламные факты учитываются после нового DRY RUN.
Прежние результаты не переписываются; отсутствие предупреждения не выдаёт
исторический результат за актуальное разрешение на действие.

## Безопасность

ADMIN/OPERATOR/VIEWER читают свой workspace. Отдельный grant редактирования
правил сохранён. Session auth, CSRF, CSP и rate limits действуют. Центр не
запускает провайдерные запросы, AI, Action Engine или очередь. Настройки колонок
сохраняются через существующий authenticated CAS API.

Runtime: ACTIONS_ENABLED=false, LOCAL_READ_ONLY=true, AI_ENABLED=false,
AI_AUTOPILOT_ALLOWED=false; Meta disconnected. Actions/AI queues пусты.
Readiness database/migrations/schema/Redis OK; worker/scheduler heartbeat OK.
Advertising WRITE = 0.

## Проверки

- Backend: 368 PASS, 1 SKIP, 77 subtests PASS. Пропущенный PostgreSQL auth/schema
  test отдельно PASS на изолированной БД.
- Новые целевые backend-тесты: 11 PASS; isolation, latest-only, отсутствие
  записей при GET, pagination, archive/legacy, сроки, версии, экономика и история.
- Scoped Ruff/mypy и basic security scan: PASS.
- Frontend: 28 unit PASS; typecheck и production build PASS.
- Playwright Chromium: 3 новых + 2 регрессионных сценария Phase 3 PASS.
- Console/page errors: 0; рекламных mutation requests: 0.
- Поиск, фильтры, детали, deep link/history, version warning, роли: PASS.
- Shared columns, DND/resize/autofit, presets, logout persistence: PASS.
- Responsive 1440/768/390, длинные русские названия, horizontal scroll,
  sticky name: PASS.

В браузере используются временные users/profile/rules с точными ID. Симуляция
читает реальные локальные данные. Pagination edge case изолирован browser route
mock; рекламные факты в PostgreSQL не создаются. Cleanup — в finally.
Первый E2E helper отклонён CSRF-защитой из-за отсутствующего Origin; helper
исправлен для передачи origin страницы. Защита не менялась.

Команды (из корня проекта, Node/Chromium из `.tools`):

```powershell
$env:PATH=(Join-Path $PWD '.tools/node-v24.21.0-win-x64')+';'+$env:PATH
$env:PLAYWRIGHT_BROWSERS_PATH=Join-Path $PWD '.tools/playwright-browsers'
Push-Location frontend
npm.cmd run test:e2e -- rule-recommendations.spec.mjs
npm.cmd run test:e2e -- rules.spec.mjs --grep 'rule lifecycle|rule columns'
Pop-Location
```

Не сбрасывать rate limits; при повторных запусках дождаться штатного окна.
Playwright JSON перезаписывается следующим запуском.

## Активация и сохранность

Backup: `backups/recommendations-20261009T212719Z.dump`.
SHA256: `fcc790d5816c190675317fde559662ce8877fcbe6357fe45ae7662beef3b5e46`.
Restore DB: `mcc_recommendations_20261009_212719`. Все 60 таблиц восстановленной
копии совпали с замороженным исходным состоянием. Revision `0011_smart_rules`
сохранена. Volumes не удалялись.

Docker Hub дважды вернул 504 при разрешении Python base tag. Для локальной
активации использован проверенный backend-образ с прежними зависимостями и
актуальным кодом поверх него; pip check PASS. Frontend собран обычным production
Dockerfile. Репозиторные Dockerfiles сохранены; следующая полная сборка требует
доступности Docker Hub. Backend/frontend/worker/scheduler активированы локально.

После всех тестов 27 защищённых таблиц совпали по count/hash: пользователи,
presets, profiles/assignments, approval observations, rules, AI и рекламные
журналы сохранены. Все прежние ключи рекламных объектов/фактов сохранены.
Полные строки восьми прежних economics snapshots совпали с restore.
Raw READ snapshots выросли 785 → 907 из-за штатной синхронизации; старые записи
сохранены. Локальные evidence находятся в `.tools/recommendations-*.json`;
backups и эти артефакты не публикуются в GitHub.

## Использование

Основные файлы изменений: `services/automation/smart_recommendations.py`,
`backend/smart_rules_api.py`, `frontend/app/recommendations/page.tsx`,
`frontend/components/RuleRecommendations.tsx`, общий `RuleDecisionDetails.tsx`,
`frontend/lib/rule-recommendations.ts`, navigation/proxy, backend/unit/E2E tests.

1. Войдите и откройте «Центр рекомендаций» в верхней навигации.
2. Если наборов нет, создайте правило и выполните DRY RUN.
3. Найдите набор и прочитайте предупреждения о повторной проверке.
4. Нажмите «Открыть результаты», выберите статус и найдите объявление.
5. Нажмите название объявления для причин, порогов и подтверждений.
6. Настройте колонки; настройки общие с таблицей симуляций правил.
7. Для новой оценки откройте «Правило и история» и выполните проверку там.
8. Вернитесь в центр и нажмите «Обновить сводку».

Следующее улучшение по плану — расписание повторных DRY RUN с лимитами и
локальными уведомлениями. AI и управление рекламой — отдельные этапы.
