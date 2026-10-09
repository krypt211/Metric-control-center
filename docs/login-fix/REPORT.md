# LOGIN / AUTHENTICATION FIX REPORT

08.10.2026. Проект: E:\Creative_Factory\metric-control-center.

### ROOT CAUSE

Подтверждённая причина отказа — в PostgreSQL metric_control, workspace default, таблица users была пуста. Поэтому введённым credentials не соответствовала учётная запись, а login возвращал 401 INVALID_CREDENTIALS. Backend и create_admin.bat используют одну БД; migration 0007_auth применена.

Почему прошлый запуск create_admin.bat не завершился созданием, точно восстановить невозможно: его результат не сохранён, пользователь не помнит подтверждение. Обнаружен конкретный недостаток launcher: окно закрывалось сразу после завершения, скрывая ошибку bootstrap. В прежней версии короткий пароль/несовпадение подтверждения завершали bootstrap с ошибкой без повторного ввода. Это возможные причины неуспешного создания, а не подтверждённый диагноз конкретного прошлого ввода.

Argon2id, CSRF, Origin, cookie forwarding и sessions работают в сквозном HTTP-тесте. Ошибку в этих механизмах не воспроизвели и защиту не отключали.

### FIX

- create_admin.bat сохраняет exit code, сообщает успех/неуспех и оставляет окно открытым до нажатия клавиши.
- Bootstrap подтверждает PostgreSQL database/workspace, отклоняет SQLite и несовпадающий workspace. Existing ADMIN не перезаписывается.
- Короткий пароль и несовпадающее подтверждение запрашиваются снова. Пароль не trim/normalize, не передаётся как shell argument и не выводится.
- Login показывает отдельные безопасные сообщения для 401, CSRF/Origin 403, invalid input 400/422, rate limit 429 и server unavailable 5xx.
- В безопасных logs различаются INVALID_CREDENTIALS, CSRF_ORIGIN, CSRF_INVALID и AUTHENTICATION_REQUIRED.
- Образы пересобраны, работающие контейнеры обновлены. БД сохранена; новые migrations не требуются.

### ADMIN

Постоянного ADMIN в используемой БД нет. Учётная запись не создана автоматически, пароль пользователя не сбрасывался. Временный тестовый ADMIN создавался через настоящий bootstrap в этой же БД и был удалён вместе со своими sessions после теста.

Перед созданием: users=0. После cleanup: users=0, sessions=0. Это не удаление постоянного пользователя; временный login имел уникальный случайный test suffix.

### LOGIN TEST

PASS. Реальный http://127.0.0.1:3000/login → CSRF → POST через Next.js → PostgreSQL → session → Dashboard. Проверены неправильные credentials, успешный вход, logout и повторный login. Проверка включала Unicode, специальные символы и ведущие/конечные пробелы в временном пароле.

### COOKIE TEST

PASS. Set-Cookie от FastAPI дошёл через Next.js до cookie jar. Локальный mcc_session: HttpOnly, SameSite=Strict, Path=/, без Domain и Secure. Production Secure/Host cookie не изменены; существующий production-cookie regression test прошёл.

### SESSION TEST

PASS. Запись user_sessions создаётся в PostgreSQL, сохраняется при refresh, распознаётся backend/frontend. Logout удаляет запись и закрывает доступ с 401; повторный login работает.

### NEXT.JS PROXY TEST

PASS. 25 HTTP E2E checks; proxy передаёт CSRF/cookies/Origin и не создаёт человеческую identity через общий token. Browser bootstrap scripts имеют CSP nonce.

### DASHBOARD ACCESS

PASS. Dashboard HTML, повторный GET после refresh, /api/dashboard и /api/stats/filters доступны после login. Доступ после logout закрыт.

### FILES CHANGED

- services/auth/bootstrap.py
- create_admin.bat
- backend/auth.py
- frontend/app/login/page.tsx
- frontend/lib/login-error.ts
- tests/test_auth.py
- RUN_LOCAL.md
- docs/login-fix/REPORT.md и обезличенные verification JSON

### TESTS

Полный suite: 216 tests за 109.449 секунд, 215 PASS, 0 FAIL, один PostgreSQL test пропущен на хосте без TEST_POSTGRES_URL. Он отдельно выполнен на реальном PostgreSQL 16: 1 PASS, 0 FAIL за 0.320 секунды. Итого все 216 tests подтверждены.

Auth/bootstrap subset: 20 PASS, 0 FAIL и тот же PG host skip. Добавлены пять регрессий bootstrap: пароль/Unicode/пробелы, повторный ввод, запрет SQLite, workspace mismatch и отсутствие перезаписи существующего ADMIN.

HTTP E2E: 25 PASS, 0 FAIL. Login error messages: 8 PASS, 0 FAIL. Frontend TypeScript/build, Alembic check, secret scan и status.bat: PASS.

Observed HTTP results:

| Запрос | Status | Причина |
|---|---:|---|
| Login неизвестного/неверного пользователя | 401 | INVALID_CREDENTIALS |
| Login без CSRF | 403 | CSRF_INVALID |
| Origin null/localhost/посторонний host | 403 | CSRF_ORIGIN |
| Login валидного временного ADMIN на 127.0.0.1 | 200 | Session создана |
| Dashboard после login | 200 | Доступ разрешён |
| Session после logout | 401 | Session отозвана |

Дополнительно unit suite проверяет 422 для invalid payload, 429 для rate limit и 503 для недоступного limiter без утечки input/secret.

VISUAL CHECK NOT VERIFIED: computer-use inventory не содержит browsers/apps. Сквозной HTTP cookie-jar test выполнен; визуальная проверка остаётся за пользователем.

### ЧТО МНЕ СДЕЛАТЬ

1. Открой E:\Creative_Factory\metric-control-center и запусти create_admin.bat. Приложение уже запущено; после остановки сначала start.bat.
2. Введи тот же желаемый login и пароль дважды. Пароль должен содержать 12–256 символов. Ввод скрыт. Существующую учётную запись это не перезаписывает — её сейчас нет в рабочей БД.
3. Обязательно дождись First administrator created и Administrator creation confirmed. Теперь окно не закроется при ошибке; при коротком пароле или несовпадении подтверждения можно повторить ввод.
4. Открой строго http://127.0.0.1:3000/login и войди. Не смешивай localhost и 127.0.0.1: настроенный Origin — 127.0.0.1.
5. Проверь Dashboard → refresh → Logout → повторный login. При слишком большом числе попыток дождись указанного времени.

Пароль не нужно присылать в чат. Сброс/удаление БД, очистка постоянных sessions или создание default admin не требуются.

### FINAL RESULT

LOCAL LOGIN: READY

Authentication pipeline и исправленный bootstrap проверены на работающем stack. Для входа владельца требуется один раз завершить интерактивное создание ADMIN; постоянный пароль выбирает и вводит сам владелец.

Safety: ACTIONS_ENABLED=false; WRITE KEY USED=NO; METRICFLOW WRITE REQUESTS=0. Рекламные entities не изменялись; Creative Factory, AI, Telegram и Rules не развивались/не запускались.
