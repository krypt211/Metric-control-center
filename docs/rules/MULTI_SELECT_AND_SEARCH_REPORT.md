# Phase 3.1 — MULTI-SELECT & SEARCH

Дата проверки: 2026-10-12 (Europe/Moscow). Проект: Metric Control Center.
Назначения правил записываются только локально; Rule Engine остаётся DRY RUN.

## Existing Architecture

Использован существующий Smart Rule Engine: `rules.payload`, `RuleVersion`,
`RuleAuditLog`, `RuleSimulation`, Economics Engine и canonical identity mapping.
Отдельной системы правил и дублирующих таблиц не создано. Прежний контракт
одиночных Campaign/AdSet/Ad и нескольких Account сохраняется для старых правил.

## UI Multi-Select

Чекбоксы доступны в статистике Account/Campaign/AdSet/Ad независимо от флага
рекламных действий. Название по-прежнему открывает следующий уровень; checkbox
не запускает переход. В конструкторе есть общий picker четырёх уровней и обзор
выбранного с возможностью удалить отдельный объект. Выбор сохраняется при поиске,
пагинации, сортировке, переключении уровня и закрытии dropdown.
После сохранения список восстанавливается из PostgreSQL.
Несохранённый выбор конструктора предупреждает об уходе/перезагрузке страницы.

## Account Selection

Можно выбрать несколько кабинетов как назначения ACCOUNT или использовать их как
контекст поиска. Фильтры не создают назначения самостоятельно. Сохраняется canonical
account ID и provider; совпадение названий не используется для связи.

## Campaign Selection

CAMPAIGN — исходный уровень назначения. Правило проверяет отдельные дочерние Ads,
включая новые Ads после синхронизации. Действие PAUSE_CAMPAIGN не создаётся.

## AdSet Selection

ADSET разрешается через реальную группу и Campaign foreign keys того же кабинета.
Назначение охватывает текущие и будущие Ads этой группы.

## Ad Selection

AD привязан к конкретной canonical identity и provider/account. Выбор объявления
не изменяет его статус, бюджет, ставку или рекламные факты.

## Search Implementation

Поиск выполняется backend по всему локальному каталогу до пагинации.
Все слова должны совпасть (AND), порядок слов не важен, регистр не учитывается.
Проверяются название, external ID и canonical ID; поддерживаются кириллица,
латиница и смешанные буквенно-цифровые запросы. Workspace ограничен
параметризованным SQL; поисковые слова обрабатываются через Unicode casefold,
без построения SQL из пользовательской строки.
Есть debounce 250 ms, очистка, количество результатов, стабильная сортировка
и «Ничего не найдено». Старые ответы отменяются; старые строки сразу скрываются
при смене страницы/поиска/уровня. Поиск статистики и Manual Control также применяется
на backend перед пагинацией.

## Searchable Dropdowns

Общий SearchableSelect используется в статистике, picker правил, Manual Control,
экономических фильтрах/назначениях и account routing/mapping настройках.
Dropdown четырёх рекламных типов имеет встроенный поиск по всему каталогу.
Mapping-селекторы используют полные локальные options с исходными ID.
Single-select остаётся одиночным; multi-select остаётся открытым после выбора.
Фокус переходит в поиск, стрелки меняют активный пункт, Enter выбирает,
Escape закрывает и возвращает фокус. Применены combobox/listbox и selected state.
Popup смещается к правому краю при необходимости, чтобы остаться в viewport.

## Cascade Filters

Account → Campaign → AdSet → Ad; множественные родительские фильтры объединяются.
Изменение контекста не удаляет выбранные targets. Picker показывает несовместимые
объекты и предлагает сохранить выбор или убрать их явно.
Источником иерархии служат существующие foreign keys и canonical mappings,
а не совпадение имён.

## Bulk Rule Assignment

Диалог показывает выбранное правило, объекты, уровни, provider/account, период,
наследование, пересечения и число потенциальных Ads.
Можно создать правило с уже выбранными targets, назначить существующий rule ID,
снять прямые назначения или выполнить DRY RUN.
Назначение к существующему правилу не создаёт его копий. При переходе старого
общего охвата к явным targets UI предупреждает о смене области.
Прежние явные назначения сохраняются при add; replace меняет набор явно.
Есть лимит 200 targets. Невалидный target отклоняет всю транзакцию.

Header checkbox выбирает только текущую страницу. «Все найденные» имеет отдельное
подтверждение и один серверный запрос разрешения полного набора IDs; выбор свыше
200 запрещён. Скрытого назначения всему аккаунту нет.

## Rule Scope Inheritance

В `selection.target_mode=true` сохранены `targets`: scope_type, scope_id,
canonical account_id, provider, effective dates, actor, created_at и policy LATEST.
Метаданные идентичности и авторства проверяются/заполняются сервером.
Обновление условий сохраняет назначения; их удаление остаётся в истории версий.
Обычная симуляция использует сохранённую область. Выборочная симуляция сохраняет
свой снимок области в истории, не меняя само правило или его назначения.

Resolver возвращает явные причины TARGET_NOT_FOUND, HIERARCHY_UNVERIFIED,
PROVIDER_REVISION_CHANGED, PROVIDER_UNAVAILABLE, NO_MATCHING_ADS.
Пустой явный набор никогда не превращается в все объявления аккаунта.
Неразрешённые исходные назначения не подменяются более широкой областью.

## Duplicate Prevention

Union выполняется по provider + canonical account + canonical Ad ID.
Campaign + AdSet + прямой Ad дают один результат данного правила для Ad,
с полным `target_provenance` всех исходных назначений. Расходы/лиды не складываются
повторно. Разные правила анализируются независимо.
Дубли assignments внутри правила запрещены контрактом и серверным merge.
Конкурентные сохранения сериализуются существующим PostgreSQL advisory lock
workspace и проверкой revision. Устаревшая запись получает 409.

## Backend API

Все новые маршруты находятся в `/api/smart-rules`:

- GET `/catalog/search`: kind, q, accounts[], campaigns[], adsets[], offset, limit.
- POST `/catalog/select-all`: явное серверное разрешение всего результата, максимум 200.
- POST `/catalog/resolve`: проверка выбранной области и число Ads.
- GET `/{rule}/targets`: сохранённые assignments и revision.
- POST `/{rule}/targets/resolve`: разрешение сохранённых assignments с provenance.
- POST `/{rule}/assignments/bulk`: revision, operation add/remove/replace, targets.
- POST `/{rule}/simulate-selected`: отдельный сохраняемый DRY RUN выбранной области.

Существующие create/update/history/simulate используются без второго движка.
Снятие выполняется bulk operation=remove; само правило и другие исходные
назначения остаются. Next.js-прокси разрешает только конкретные маршруты.
Ответ каталога уже содержит данные для безопасного просмотра выбранного.

## PostgreSQL Migration

Миграция не требуется: существующий JSONB payload и immutable versions поддерживают
множество target IDs. Alembic head остаётся `0012_manual_actions`;
`alembic check` не обнаружил новых операций. Рабочая схема не изменена;
backup/restore для новой миграции не понадобились.
Concurrency проверен в ранее восстановленной изолированной БД `mcc_phase4_*`:
8 потоков, одно сохранение, 7 конфликтов, ноль дубликатов. Fixture очищен адресно.
Ни один Docker volume не удалён.

## Permissions

ADMIN редактирует. OPERATOR использует существующий RuleGrant.can_edit;
без grant редактирование запрещено. VIEWER читает объекты/назначения/историю,
без права редактирования. Backend проверяет workspace, роль/grant, revision,
ID и иерархию. Изменяющие запросы требуют CSRF; скрытие кнопок не является защитой.

## DRY RUN

Использован существующий Economics Engine и AND/OR evaluator с прежними
KEEP/REVIEW/WOULD_PAUSE/INSUFFICIENT_DATA/DATA_STALE решениями.
Проверка сохраняет RuleSimulation и immutable snapshot, включает target provenance
и scope issues. Неизвестные факты не превращаются в нули.
Лимиты симуляции: 500 Ads, каталог до 2000 Ads, 10 секунд; превышение требует
уточнить область и не создаёт частичного рекламного исполнения.

## Frontend Tests

35 unit-тестов прошли; TypeScript и production build прошли.
Добавлены тесты Unicode AND search, provider-aware identity и merge без дублей.

## Backend Tests

Полный прогон: 475 passed, 1 skipped, 77 subtests passed.
После последних изменений: 124 passed в затронутых suites; отдельно
35 passed для target resolver, bulk assignments и регрессий Economics API.
Проверены четыре уровня, новые Ads, пересечения, даты, audit, пустой scope,
исчезнувший target, отсутствующий Campaign row, атомарный отказ и CAS,
workspace/CSRF/роли и история. PostgreSQL concurrency: 8 threads,
1 сохранение, 7 revision conflicts, 0 duplicate assignments.
Skipped PostgreSQL-dependent auth case отдельно проверен на PostgreSQL: PASS.
Ruff check/format: PASS; scoped mypy smart_targets: PASS.

## Playwright E2E

Итог: 32 passed — Phase 3.1: 7; Rule Engine: 3; Economics: 4;
Manual Control: 5; UI-1/columns: 6; navigation: 7.
Новые сценарии проверили полный каталог, mixed selection, страницы/header,
подтверждение select-all, создание и назначение правила, persistence,
снятие прямого назначения, выбранный DRY RUN/history, dropdown/keyboard,
1440/1024/768/390 px. Регрессии проверили роли/CSRF/logout, экономику,
PAUSE_AD/ENABLE_AD drafts и интеграцию с реальными решениями Rule Engine.

Рабочие AD факты не создавались и даты их свежести не менялись.
Для Manual Control использована плановая READ-синхронизация MetricFlow:
2026-10-12 11:00 UTC, статус succeeded; перед повторным тестом квота 113/800.
Meta отключён. Порог свежести 12 минут сохранён.

Адресные временные users/profiles/rules удалены точной fixture cleanup.
UI_SESSION_FIXTURES=true включён только в тестовых процессах: normal серверные
сессии выдаются отдельным nonce users под LOCAL_READ_ONLY/ACTIONS guards,
с проверкой localhost. Production auth, лимит password login 10/900s,
права и CSRF не изменены. Эти feature runs проверяют session auth и logout,
а не ввод пароля через форму; password auth проверен backend/PostgreSQL tests.
Первоначальные ошибки locator/старая proxy allowlist/async pagination исправлены;
итоговые assertions не ослаблены. Console/page errors и advertising mutations
проверяются browser guards.

## Data Integrity

Исходные/итоговые хеши всех 62 таблиц сохранены в игнорируемых
.tools/phase31-before.json и .tools/phase31-after.json; сводка —
.tools/phase31-integrity.json. Во всех финальных browser integrity windows
62/62 таблицы совпали после точного fixture cleanup, action_execution_delta=0.
READ worker/scheduler на время окна останавливались и всегда возобновлялись.

За весь длительный этап 49 таблиц сохранили исходные count/hash, 13 изменились
штатной READ-синхронизацией: ad_accounts, ads, adsets, api_quotas, campaigns,
daily_metrics, entities, entity_current_state, provider_account_mappings,
provider_connections, provider_windows, raw_snapshots, sync_runs.
Это обновление реальных фактов и журналов READ: accounts 11→12,
ads 300→303, adsets 270→273, campaigns 107→109, entities 1635→1643,
daily_metrics 472→486, sync_runs 575→608. Утверждения о неизменности
рекламных фактов за весь этап нет; неизменность подтверждена для остановленных
browser windows и пользовательских таблиц правил/профилей/пресетов/сессий.
Action requests/executions/logs не изменились, executions delta=0.
Новые PostgreSQL concurrency/auth проверки выполнялись на изолированных fixtures.

Docker: backend/PostgreSQL/Redis healthy; frontend/worker/scheduler запущены.
GET /health/ready: ready, database/migrations/schema/redis OK.
alembic check: No new upgrade operations detected; head 0012_manual_actions.
Исходные защитные флаги подтверждены внутри backend-контейнера.
Security source scan и git diff --cached --check: PASS.
Прежние пользовательские изменения roadmap и Phase 4 reports исключены из коммита.

## Files Changed

Backend: smart rule schema/store/simulation, новый smart_targets, API smart-rules,
поиск статистики и Manual Control.
Frontend: SearchableSelect, RuleTargetPicker, RuleTargetActions, rule-targets helpers,
существующие статистика/правила/Manual Control/экономика/подключения и стили.
Тесты: rule targets backend/unit/E2E, PostgreSQL concurrency script и адаптация
существующих UI-регрессий к searchable controls.
Документация: этот отчёт и ссылки на него.

## Remaining Issues

Функциональных блокеров Phase 3.1 после финальной приёмки не выявлено.
Лимиты 200 targets/500 Ads/2000 catalog Ads/10 секунд явно ограничивают scope.
Статистика и статусы зависят от READ-синхронизации; stale данные блокируют
подготовку Manual Control и соответствующий E2E, их нельзя искусственно освежать.
Старый migrate-контейнер остаётся stopped/exit 255 с прежней ошибкой revision
0010_economics; его не удаляли и не запускали. Работающая БД имеет head 0012.
MetricFlow WRITE API остаётся UNVERIFIED по прежнему Phase 4B аудиту:
этот этап не добавляет подтверждения provider WRITE contract и не разрешает WRITE.

## HOW TO USE

1. В «Статистика» выберите уровень «Кампании», отметьте несколько строк checkbox.
   Либо откройте «Правила» → «Изменить объекты» → «кампании».
2. Переключитесь на «группы» и выберите AdSets; прежний выбор сохранится.
3. Переключитесь на «объявления» и отметьте Ads. Смешанный набор допустим.
4. Введите часть названия кампании в поиск списка/объектов; слова работают как AND.
5. Найдите объявление по external или canonical ID.
6. Откройте dropdown кабинетов/кампаний/групп/Ads и введите название/ID.
   Стрелки + Enter выбирают; Escape закрывает.
7. Нажмите «Назначить правило выбранным», выберите существующее правило,
   проверьте список/период/наследование и нажмите «Сохранить назначения».
8. Нажмите «Создать правило для выбранных»; выбор переносится в конструктор.
   Задайте условия и сохраните правило.
9. Для снятия только конкретных прямых assignments оставьте нужные объекты
   в выборе, нажмите «Удалить правило у выбранных», проверьте число и подтвердите.
   Назначение через родительскую Campaign/AdSet отдельно не снимается.
10. «DRY RUN выбранных» проверяет выбранную область и сохраняет историю.
    «Проверить правила» в конструкторе проверяет сохранённый scope.
11. Header checkbox выбирает страницу; полный найденный набор требует отдельного
    подтверждения. Перед сохранением проверьте итоговый счётчик.
12. После повторного открытия правила сохранённые targets восстановятся.

## FINAL STATUS

RULE TARGET MULTI-SELECT & SEARCH: READY

Phase 3.1 реализована и проверена. Рекламные WRITE-запросы: 0.
ACTIONS_ENABLED=false, LOCAL_READ_ONLY=true, AI_ENABLED=false,
AI_AUTOPILOT_ALLOWED=false; Meta отключён, quota 800 не увеличена.
MetricFlow WRITE API: UNVERIFIED (предыдущий audit, без новых live WRITE probes).
