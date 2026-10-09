# UI-1 FINAL BROWSER ACCEPTANCE
Дата: 2026-10-08, Europe/Moscow.
Проект: E:\Creative_Factory\metric-control-center.
URL: http://127.0.0.1:3000

UI-1 BROWSER ACCEPTANCE: PASS

## Environment

- Windows, native Node.js 24.21.0.
- Chromium 156.0.8078.4 / Playwright browser v1248, headless.
- Playwright 1.64.0, существующий frontend/playwright.config.mjs.
- Docker Desktop engine 29.8.2.
- PostgreSQL, backend, frontend, Redis доступны.
- Миграция 0008_column_preferences.
- Chromium установлен штатным Playwright CLI в .tools/playwright-browsers. См. [официальную документацию](https://playwright.dev/docs/browsers).

## Final results

| Check | Result |
| --- | --- |
| Playwright | PASS: 6 passed, 0 failed, 20.1 s |
| Drag-and-drop | PASS: физический HTML drag/drop меняет порядок |
| Resize | PASS: мышь расширяет/сужает название; обычная колонка тоже расширяется мышью; соседние ширины сохраняются |
| Double click | PASS: подбор под длинное название с ограничением 720 px |
| Add/hide metrics | PASS: checkbox, поиск, обязательное название |
| Presets | PASS: несколько наборов, create/save/rename/duplicate, selector switching, default, delete/fallback |
| Persistence | PASS: refresh, logout/login восстанавливают весь config, порядок заголовков и aria-sort; отдельные scopes |
| Rapid scope switching | PASS: немедленный переход без ожидания debounce сохраняет новую ширину |
| Long Russian names | PASS: корректный UTF-8, полный title, текст в строке таблицы |
| Horizontal scroll/sticky | PASS: scrollLeft увеличивается; название остаётся слева по координатам |
| Responsive | PASS: 1440, 768, 390 px; документ/контейнер/диалог не выходят за ширину viewport |
| Browser console errors | 0 в финальном прогоне, включая первичный login и второй пользователь |
| Uncaught page errors | 0 |
| Advertising mutation requests | 0 |
| Real advertising data | PASS: SHA-256 и количество строк совпали в 15 защищённых таблицах |
| ACTIONS_ENABLED | false |

TypeScript и 13 frontend unit/SSR тестов также PASS. Изменения в этой приёмке касаются E2E и отчётов; код приложения, MetricFlow contract, финансовые формулы и механизм безопасности не менялись.

## Scenarios executed

1. labels, visibility/search, bounds, keyboard reorder, scope and refresh.
2. real pointer resize, shrink, double-click autofit, drag, sticky name and sort.
3. multiple private presets, rename/duplicate/default/delete, login persistence and isolation.
4. all six scopes expose independent column manager and system templates.
5. long Russian names, independent column widths and narrow viewport layout.
6. rapid scope navigation flushes unsaved width before restoring the view.

Тестовые table rows подменяются только через browser route для воспроизводимых длинных названий и значений. Auth, CSRF, user preferences и PostgreSQL настоящие. Core advertising tables не заполнялись тестовыми фактами и не обновлялись. Проверки охватывают Chromium на Windows и указанные viewport, а не отдельные реальные Android/iOS устройства.

## Issues corrected

1. Пустой служебный alert Next.js route announcer ошибочно считался сообщением об ошибке. Проверка alert ограничена main приложения; реальные ошибки UI по-прежнему приводят к FAIL.
2. Координатный mouse resize выполнялся до прокрутки resize handle в viewport. Добавлен scrollIntoViewIfNeeded перед движением мыши; assertions сохранённых ширин сохранены.
3. Regex для кнопки сортировки находил и drag handle «Переместить: Расходы», и кнопку «Расходы ↓». Locator теперь выбирает название, начинающееся с «Расходы».
4. Повторный login перед каждым тестом и несколько повторных запусков достигали штатного login rate limit. Он не сбрасывался, не отключался и не повышался. Дождались истечения окна; fixture переиспользует cookie state настоящего UI-login между тестами. После проверенного logout/login cookie state обновляется.
5. Усилено покрытие: проверяется весь сохранённый config после входа, ручное переключение selector между двумя собственными наборами, независимость ширин и быстрый переход между scopes.

Первые неудачные прогоны включали ожидаемый HTTP 429 от защиты входа. Это не скрыто фильтром console: финальный прогон требует строго пустые consoleErrors/pageErrors и запрещённые рекламные mutations.

## Data safety

Перед тестами READ worker/scheduler временно остановлены для стабильного сравнения. После тестов SHA-256 и row counts совпали для users, ad_accounts, entities, campaigns, adsets, ads, creatives, daily_metrics, tracker_metrics, breakdowns, entity_current_state, read_statistics, action_requests, action_executions, action_logs.

Временные viewer/operator и их sessions/presets/views удалены fixture cleanup. Временных пользователей осталось 0. Имеющиеся собственные наборы исходного пользователя сохранены; они не удалялись по общему шаблону. Рекламные actions/exec/logs — 0; WRITE key не смонтирован в backend. READ worker/scheduler возобновлены. Volumes и реальные рекламные данные не удалялись.

## Artifacts

- browser-playwright.json — исходный JSON report финального Playwright run.
- browser-verification.json — сводка по шести тестам и browser audit.
- browser-data-preservation.json — SHA-256/counts до и после.
- browser-read-only.json — gates, cleanup и action counts.
- verification.json — обновлённая сводка UI-1.
- .tools/ui-browser-first-run.log, ui-browser-second-run.log, ui-browser-third-run.log — диагностика ранних запусков.
- .tools/ui-browser-fourth-run.log — финальный PASS.
- WINDOWS_E2E.md — повторный запуск.

## Files changed

- frontend/e2e/columns.spec.mjs
- frontend/playwright.config.mjs
- docs/ui-1/WINDOWS_E2E.md
- docs/ui-1/REPORT.md
- docs/ui-1/verification.json
- docs/ui-1/BROWSER_ACCEPTANCE.md
- docs/ui-1/browser-playwright.json
- docs/ui-1/browser-verification.json
- docs/ui-1/browser-data-preservation.json
- docs/ui-1/browser-read-only.json

Creative Factory не изменялся. Следующая фаза не запускалась.