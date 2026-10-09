# Backup и restore

В production работает backup-job: первый custom pg_dump после старта, затем каждые 24 часа; имя содержит UTC timestamp и случайный suffix. Retention по умолчанию 14 дней. Дамп и SHA256 сохраняются в backups/ с правами 0600, directory — 0700. Ошибка одноразовой команды даёт ненулевой exit code; job пишет безопасный ERROR и повторяет попытку на следующем цикле.

## Windows

Запустите backup.bat из корня проекта. Проверка restore с новой копией:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/maintenance.ps1 -Command restore-test
```

Скрипт временно останавливает worker/scheduler и восстанавливает их запуск в finally. Чтобы сравнение было согласованным, во время restore-test не создавайте пользователей и не запускайте ручной sync.

## Сервер: backup и тест восстановления

```bash
cd /opt/metric-control-center
dc=(docker compose --env-file .env.production -f docker-compose.production.yml)
"${dc[@]}" run --rm backup backup
```

Для теста требуется временно заморозить все источники изменений БД. Команды ниже ненадолго останавливают пользовательский доступ, ingestion и backup-job. Исходная БД не заменяется; создаётся отдельная mcc_restore_test_* БД и удаляется в finally:

```bash
set -Eeuo pipefail
dc=(docker compose --env-file .env.production -f docker-compose.production.yml)
"${dc[@]}" stop caddy frontend backend worker scheduler backup-job
trap '"${dc[@]}" up -d backend frontend worker scheduler backup-job caddy' EXIT
"${dc[@]}" run --rm backup restore-test
```

Тест создаёт новый дамп, проверяет SHA256, выполняет pg_restore --exit-on-error, сравнивает counts и сортированные row digests девяти критичных таблиц плюс Alembic revision. Это проверка согласованности данных и восстановления custom dump. pg_dump/pg_restore обрабатывают полную БД; digests выборочно охватывают основные данные, users/sessions и журналы.

Реальная локальная проверка 08.10.2026: PASS; 364 daily metrics, 3 ad accounts, 273 entities, 1040 read statistics, migration 0007_auth. [Доказательство](docs/production-read-only/restore-test.json). После теста отдельная БД удалена, рабочая БД сохранена, worker/scheduler снова запущены.

## Явное восстановление

Восстановление заменяет данные указанной БД. Перед ним сохраните текущую копию и остановите все приложения/ingestion. Требуется точное имя дампа из backups/ и точное подтверждение POSTGRES_DB; произвольные пути отвергаются.

```bash
dc=(docker compose --env-file .env.production -f docker-compose.production.yml)
"${dc[@]}" stop caddy frontend backend worker scheduler backup-job
"${dc[@]}" run --rm backup backup
"${dc[@]}" run --rm backup restore --file mcc-YYYYMMDDTHHMMSSZ-XXXXXXXX.dump --confirm-database metric_control
```

Указанное имя — шаблон, замените фактическим, а metric_control — действительным POSTGRES_DB. SHA256 sidecar должен присутствовать. При ошибке приложение оставьте остановленным, устраните причину, повторите restore.

Для восстановления после несовместимой migration используйте НОВУЮ БД: --clean удаляет объекты дампа, но не гарантирует удаления новых таблиц, которых нет в старом dump. Сохраните старую DB, создайте новую (имя только из букв/цифр/underscore), укажите её в .env.production и restore confirmation:

```bash
"${dc[@]}" exec -T postgres sh -c 'createdb -U "$POSTGRES_USER" metric_control_restored'
nano .env.production
"${dc[@]}" run --rm backup restore --file mcc-YYYYMMDDTHHMMSSZ-XXXXXXXX.dump --confirm-database metric_control_restored
```

После совместимого restore/переноса на текущую версию:

```bash
"${dc[@]}" run --rm migrate
"${dc[@]}" up -d
bash scripts/check_server.sh
```

При rollback запускайте предыдущие сохранённые образы и совместимую конфигурацию, сверяйте Alembic revision с ними. Не запускайте новую migration до оценки совместимости. Session secret и READ key не входят в дамп: их храните отдельно в защищённом хранилище; без старой session secret потребуется повторный login. DB password на новом сервере может быть новым.

## Хранение вне VPS

Backup на том же диске помогает при логической ошибке, но не при потере VPS. До рабочего запуска настройте отдельную зашифрованную offsite-копию backups и необходимых secrets с доступом владельца, без публикации в Git. Передавать дампы третьим сторонам и выбирать внешний аккаунт текущая задача не поручала; автоматическая offsite-доставка не настроена. Дампы содержат приватную статистику и password/session hashes. Проверяйте logs backup-job и регулярно повторяйте isolated restore-test.

## Provider credentials encryption key (Multi-Provider)

SQL dumps contain encrypted provider credentials, never `.secrets/provider_encryption_key`. Keep the original key separately in a protected recovery store. Losing it prevents decryption; generating a replacement does not recover the old credentials.

Windows `backup.bat`, maintenance `restore-test`, and `start.bat` check key presence, format and protected ACL without printing its value. Before recovery, restore the original key with access restricted to the owner, SYSTEM and Administrators; then run these checks before starting backend/worker. The key is mounted only in backend and ingestion worker, never frontend or the SQL backup container. On Linux check the original key exists at the configured secret path and is readable by the intended container before bringing up restored services.

The activation backup `activation-*.dump` uses a SHA256 sidecar and a separately verified isolated restore. Existing backups and volumes are retained. Restore test databases created for this activation are retained for review, without replacing the working database.
