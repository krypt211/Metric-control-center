# UI-1: browser checks on Windows
Проект должен уже работать на http://127.0.0.1:3000 с миграцией 0008_column_preferences, LOCAL_READ_ONLY=true и ACTIONS_ENABLED=false. Это тесты локальной установки; production база запрещена fixture guard.

Нужны Node.js 24/npm и работающий Docker Desktop. В PowerShell:

~~~powershell
Set-Location E:\Creative_Factory\metric-control-center\frontend
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path (Resolve-Path '..') '.tools/playwright-browsers'
# If Node is not on PATH, use the existing portable runtime:
# $env:PATH = (Join-Path (Resolve-Path '..') '.tools/node-v24.21.0-win-x64') + ';' + $env:PATH
npm ci
npx playwright install chromium
npm run test:unit
npm run test:e2e
~~~

По умолчанию Docker берётся из %LOCALAPPDATA%\Programs\DockerDesktop\resources\bin\docker.exe. Если установлен иначе:

~~~powershell
$env:DOCKER_EXE = 'C:\Program Files\Docker\Docker\resources\bin\docker.exe'
npm run test:e2e
~~~

Тесты создают два случайных временных viewer/operator только для проверки изоляции, используют пароль исключительно в памяти и удаляют свои users/sessions/presets/views в finally. Исходный пользователь и пароль не меняются. Не включены traces/video; screenshots только при ошибке, сохраняются локально в игнорируемом test-results. Тестовые stats rows подставляются только в browser routing; PostgreSQL факты рекламы не меняются. API настроек, авторизация, CSRF и persistence реальные.

Проверяются:

- Русские подписи, NULL, обязательное название, поиск, checkbox, width input, accessible reorder.
- Реальное движение мыши вправо/влево, double-click autofit, HTML drag/drop, sticky имя, tooltip, горизонтальная прокрутка и узкий viewport.
- Несколько наборов, сохранение, rename/duplicate/default/delete, refresh, logout/login.
- Изоляция двух пользователей и все шесть scopes.

Тесты выполняются последовательно одним worker. Discovery через --list НЕ является выполнением браузерных проверок.

Реальный HTTP тест перезапуска контейнеров, отдельно от browser tests:

~~~powershell
Set-Location E:\Creative_Factory\metric-control-center
& .venv\Scripts\python.exe scripts\check_ui_preferences.py --restart
~~~

--restart перезапускает frontend/backend/postgres/redis; это кратковременно прерывает доступ к локальной панели. Volumes и рекламные данные не удаляются. Результат: .tools/ui-http-evidence.json.

Если прервать browser process принудительно, finally может не выполниться. Для удаления только конкретного test-run используйте nonce из названия временного пользователя и accounts.py с mode=cleanup. Не удаляйте пользователей по широкому шаблону и не удаляйте volumes.
## Verified acceptance
2026-10-08: Windows Chromium headless, 6 tests PASS; browser console errors = 0. See [BROWSER_ACCEPTANCE.md](BROWSER_ACCEPTANCE.md).

The fixture now signs in once per worker and reuses legitimate session cookies. The logout/login test still exercises the real UI and refreshes storageState. Do not disable or clear rate limits; after many repeated runs, wait for their normal expiry.

JSON reporter output: frontend/test-results/browser-acceptance.json. Browser audit requires zero console errors, page exceptions and advertising mutation requests. All six scopes and viewport widths 1440/768/390 are covered.

The combined table/hotfix/provider suite shares the backend API rate budget. The provider smoke test waits one minute before starting, so earlier table scenarios cannot exhaust its API window. No limits or Redis rate keys are changed. The provider smoke timeout includes this pause.
