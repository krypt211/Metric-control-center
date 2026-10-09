# Первый запуск — Windows 10

Папка программы: E:\Creative_Factory\metric-control-center.

1. Установите Docker Desktop, выберите Linux containers и запустите Docker Desktop.
2. Откройте папку программы и дважды нажмите **setup.bat**.
3. На вопрос **Paste MetricFlow READ API key** вставьте READ-ключ. Ввод скрыт: это нормально. Нажмите Enter. Поддерживаются префиксы mf_live_ и mfk_. Вставляйте полный оригинальный ключ, без звёздочек маскировки. WRITE-ключ не нужен.
4. Дважды нажмите **start.bat**. Первая сборка может занять несколько минут. Дождитесь **LOCAL APPLICATION: PASS**.
5. Запустите **create_admin.bat**: введите login и пароль дважды (ввод скрыт; default password нет). Затем запустите **probe_read.bat**. Ожидается **MetricFlow READ API: OK**.
6. Запустите **sync_now.bat**. Дождитесь **Last sync: SUCCESS**.
7. Откройте обычный браузер: **http://127.0.0.1:3000/login**, войдите созданным пользователем. После login откроется dashboard. Logout завершает серверную сессию.

READ-ключ создаётся в MetricFlow: Settings → API. Нужны права analytics:read, ad_accounts:read, campaigns:read. Не добавляйте write-права.

## Последующие запуски

1. Откройте Docker Desktop и дождитесь готовности.
2. Запустите **start.bat**.
3. Откройте **http://127.0.0.1:3000**.

Ключ вводится один раз. Статистика автоматически обновляется каждые 10 минут после настройки READ-схемы.

## Куда сохраняется ключ

E:\Creative_Factory\metric-control-center\.secrets\metricflow_read_key

Удобнее использовать **setup.bat**. Ключ не показывается, не включается в frontend и исключён из Git. Для замены ключа очистите содержимое только этого файла, затем снова запустите setup.bat. Не присылайте ключ в чат.

## Первый sync и формат API

**sync_now.bat** проверяет READ-доступ, получает каталог кабинетов и статистику за Today + Yesterday (два включённых календарных дня), затем сохраняет данные в PostgreSQL. Команда показывает количество обработанных сущностей и строк. Повторный запуск обновляет существующие данные.

При первом sync программа пытается определить поля и пагинацию из настоящего ответа API. Проверенная схема сохраняется в config\metricflow-schema.json; обычный worker читает её без права изменения.

Если ответ пустой, поля неоднозначны или полнота страниц не подтверждена, команда покажет **READ schema: NOT VERIFIED** и не опубликует неполную статистику. В таком случае разработчику нужно проверить формат ответа и подготовить схему, затем снова запустить sync_now.bat. Не копируйте синтетический example как рабочую схему.

Для текущего живого API проверены: каталог data + meta.total (полная длина; limit/offset=null) и insights data + pagination.cursor/has_more. Cursor передаётся обратно параметром cursor; meta.total у insights означает количество строк текущей страницы. При изменении этих условий импорт останавливается. Обезличенные доказательства находятся в docs/metricflow-live-contract.

Ошибка схемы выводит Docker: OK / Schema: FAILED / Import: NOT PUBLISHED и не означает, что Docker или веб-панель сломаны. Код 20 обозначает ошибку READ API/ключа, 21 — схему, 22 — локальный импорт, 23 — квоту.

Состояния Campaign/Ad Set загружаются из READ-каталогов для родителей присутствующих ad-фактов и обновляются при ближайшем sync после истечения часового кэша; новые родители загружаются при следующем sync. Состояние Ad приходит из insights. Budgets/bids остаются неизвестными до подтверждения единиц.

Некоторые показатели, креативы и preview появятся только если API передаёт соответствующие поля. Отсутствующие показатели отображаются как «—».

## Проверка состояния

**status.bat** показывает контейнеры, readiness и ответ worker. Последняя/следующая синхронизация, quota и heartbeat доступны после login администратора на **http://127.0.0.1:3000/admin**; приватный API без session отвечает 401.

Backend: **http://127.0.0.1:8000** — служебный API, не отдельная панель.

Liveness: **http://127.0.0.1:8000/health/live**.

Готовность БД, схемы и Redis: **http://127.0.0.1:8000/health/ready**.

## Остановка

**stop.bat**. Статистика и база сохраняются. Не удаляйте Docker volumes.

## Логи

**logs.bat**. Для выхода нажмите Ctrl+C. Это не останавливает приложение.

## Если не запускается

- **Docker Desktop is not installed** — установите Docker Desktop.
- **Docker Desktop is not running** — откройте Docker Desktop и дождитесь готовности Linux engine.
- **READ key is missing** — запустите setup.bat.
- **401** — ключ недействителен или отозван.
- **403** — проверьте READ-права; ключ с write-правами не подходит этому режиму.
- **429** — достигнут API-лимит; дождитесь сброса. Не повторяйте sync непрерывно.
- **NOT READY / порт занят** — посмотрите logs.bat; порты 3000 и 8000 должны быть свободны.
- **Last sync: FAILED** — status.bat показывает код ошибки; прежние сохранённые данные остаются.

## Режим безопасности

**LOCAL READ ONLY**: SYNC_ENABLED=true, ACTIONS_ENABLED=false; AI, Autopilot и Telegram выключены. Active rules не запускаются. Action Worker не запускается; WRITE-secret не подключается к работающим сервисам.

Порты Docker опубликованы только на 127.0.0.1. Адрес внутри контейнера нужен для связи контейнеров; приложение не публикуется на сетевых интерфейсах компьютера. Домен и доступ из интернета не настраиваются.

## Controlled historical backfill

Run commands from this project directory after start.bat. If docker is not in PATH, use its Docker Desktop installation path.

```powershell
docker compose --project-directory . --env-file .env -f docker-compose.yml -p metric-control-center exec worker python -m services.sync.backfill --start 2026-09-08 --end 2026-10-07
docker compose --project-directory . --env-file .env -f docker-compose.yml -p metric-control-center exec worker python -m services.sync.backfill --start 2026-09-08 --end 2026-10-07 --execute
```

The first command prints a plan without calling MetricFlow. The second processes three-day windows. Rerun the same command to resume: already successful windows with the same schema are skipped. Use --replay only for deliberate reconciliation of completed windows. Each window uses the core atomic cursor sync, shared quota and overlap lease. The default max-pages is 32, including account and parent catalogs; retries are included in request reservations. A low quota pauses work instead of raising SYNC_DAILY_BUDGET=800. Empty complete API windows are recorded as successful without inventing daily facts.

## Optional READ observations

```powershell
docker compose --project-directory . --env-file .env -f docker-compose.yml -p metric-control-center exec worker python -m services.sync.optional --start 2026-10-02 --end 2026-10-08
```

This requires nine GET calls for three accounts: tracker + ads + creatives per account. Every HTTP attempt uses the existing persistent daily quota. Tracker counters are stored separately by account/day and by ad/exact window. The latter keeps t_conversions and t_conversions_raw separate; absent sparse ad rows are not assumed to be zero. Tracker currency and timezone are unknown; its money is retained only in raw data and the displayed revenue/profit/ROI remain null.

Creative analytics uses the provider's opaque creative_key and exact date window, validated against ads from the same data version. It does not assign current creative metadata to historical ad/day facts or invent a numeric Meta creative ID. The Creatives tab reads these exact-window snapshots; a different custom window must be refreshed separately. The Tracker tab can filter the stored account/day counters over any loaded date range, or select ad/window counters for an exact loaded period. Creative tracker counters are shown separately from Meta counters.

Optional data is refreshed manually at this stage. The existing core scheduler remains unchanged. It continues refreshing core data without optional API calls. Preview URLs use provider metadata and may expire.

Additional event counters are derived from verified core raw ad/day observations. Reach, frequency and unique counters are shown only for a single ad/day observation; totals across different populations remain unknown.

See docs/metricflow-full-read/REPORT.md for live evidence and limitations.

## Пользователи и резервные копии

ADMIN создаёт VIEWER/OPERATOR/ADMIN на /admin. VIEWER и OPERATOR только читают статистику. Backend проверяет пользователя независимо от frontend; cookie HttpOnly/Strict, production также Secure. Пароли — Argon2id, сессии — PostgreSQL, срок по умолчанию 8 часов; общий operator token не используется как пользовательская identity.

backup.bat создаёт custom PostgreSQL dump и SHA256 в backups/. Restore test и серверные команды: [BACKUP_RESTORE.md](BACKUP_RESTORE.md). Серверный HTTPS deployment: [SERVER_DEPLOYMENT.md](SERVER_DEPLOYMENT.md).

create_admin.bat — bootstrap только первого credentialed администратора. Повторный запуск при существующем ADMIN откажет. Password reset/смена роли/деактивация через admin API отзывают сессии; новые пользователи создаются на /admin. Не удаляйте session secret при обычном restart.
## Если не получается войти

Запустите create_admin.bat и дождитесь именно First administrator created. Окно теперь остаётся открытым: ошибка больше не скрывается при завершении. Короткий пароль (менее 12 символов) или несовпадение подтверждения можно исправить повторным вводом. Bootstrap указывает целевые PostgreSQL database и workspace; существующий ADMIN и пароль не перезаписывает.

Для текущей local конфигурации используйте http://127.0.0.1:3000/login. localhost — другой Origin и cookie host. Login показывает разные сообщения для неверных credentials, CSRF, rate limit и недоступности сервера. Не удаляйте БД и secrets ради повторного входа.

[Отчёт проверки входа](docs/login-fix/REPORT.md).