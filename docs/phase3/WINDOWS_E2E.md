# Phase 3: приёмка на Windows

Проект: `E:\Creative_Factory\metric-control-center`.
Ручная проверка: <http://127.0.0.1:3000/rules>.

## Подготовка

Сохранить `ACTIONS_ENABLED=false`, `LOCAL_READ_ONLY=true`, `AI_ENABLED=false`,
`AI_AUTOPILOT_ALLOWED=false`. Meta должен оставаться отключённым. Проверить
`/health/ready`, revision `0011_smart_rules`, PostgreSQL backup, checksum и
restore в отдельную БД. Не удалять volumes и не очищать Redis rate limits.

Используется существующий `frontend/playwright.config.mjs` и Chromium.

```powershell
$env:PATH=(Join-Path $PWD '.tools/node-v24.21.0-win-x64')+';'+$env:PATH
$env:PLAYWRIGHT_BROWSERS_PATH=Join-Path $PWD '.tools/playwright-browsers'
Push-Location frontend
npm.cmd run typecheck
npm.cmd run test:unit
npm.cmd run test:e2e -- rules.spec.mjs
Pop-Location
```

`rules_accounts.py` создаёт трёх временных пользователей и один собственный
экономический профиль. Выбирает существующий MetricFlow-аккаунт с объявлениями.
Рекламные факты не создаёт и не изменяет. В `finally` удаляет только записи,
принадлежащие точным тестовым user/profile/rule ID и nonce. Действия рекламы
не вызываются. Реальная PostgreSQL, session auth, CSRF, CSP и rate limits активны.

## Сценарии

1. Login, навигация, название на русском, профиль, аккаунт, семь завершённых дней,
   CPL и ROI, AND/OR, минимальные лиды и продажи, save/reload, реальный локальный
   DRY RUN, фильтр кандидатов, объяснение, копирование, изменение, архив,
   восстановление старой конфигурации новой версией, неизменная история.
2. Общий Column Manager: добавление/скрытие метрик, private preset, native mouse
   drag-and-drop, pointer resize, double-click autofit, сортировка,
   logout/login persistence, 1440/768/390, горизонтальный scroll и sticky name,
   удаление собственного набора.
3. VIEWER и OPERATOR: просмотр, запрет редактирования/симуляций, отдельный ADMIN
   grant, отзыв grant, повторная загрузка, CSRF. Дополнительные backend-тесты
   проверяют workspace isolation, CAS, ограничения выражений и времени.

Console/page errors и рекламные запросы фиксируются в test attachment
`rule-browser-audit`. JSON-отчёт сохраняется в
`frontend/test-results/browser-acceptance.json`. Перед запуском других наборов
копировать отчёт в `.tools`, поскольку Playwright перезаписывает его.

После повторного login использовать новое состояние сессии. Для другого
пользователя создавать context с `storageState: {cookies: [], origins: []}`.
При исчерпании штатного rate limit дождаться его естественного истечения.

## Регрессия

```powershell
Push-Location frontend
npm.cmd run test:e2e -- columns.spec.mjs dashboard-hotfix.spec.mjs providers.spec.mjs economics.spec.mjs
Pop-Location
```

Общие лимиты API/login сохраняются. Повторные попытки запускать после истечения
окна лимита, не меняя конфигурацию безопасности. Длинные русские имена также
проверяются существующими UI-1 сценариями на браузерных mock responses;
фиктивные рекламные факты в рабочую PostgreSQL не добавляются.
