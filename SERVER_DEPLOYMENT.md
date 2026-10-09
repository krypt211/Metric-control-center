# Серверный запуск — READ ONLY

Проект: metric-control-center. Рекомендуемая среда — Ubuntu 24.04 LTS, Docker Engine и Compose plugin. Команды выполняет отдельный пользователь сервера с sudo. Домен, VPS и публичный сертификат в текущей сессии не предоставлены: эти шаги ещё нужно выполнить на выбранном сервере.

## 1. Docker

Установка использует официальный apt repository Docker; [официальная инструкция](https://docs.docker.com/engine/install/ubuntu/) описывает поддерживаемые Ubuntu и обновления.

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl python3 git
sudo install -d -m 0755 /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
. /etc/os-release
printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu %s stable\n' "$(dpkg --print-architecture)" "$VERSION_CODENAME" | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker "$USER"
```

Завершите SSH-сеанс и подключитесь заново. Членство в группе docker даёт административные возможности на сервере. Проверьте docker version и docker compose version.

## 2. Код и подтверждённая READ-схема

Если проект уже опубликован в вашем Git repository:

```bash
REPOSITORY_URL='YOUR_GIT_REPOSITORY_URL'
sudo install -d -o "$USER" -m 0750 /opt/metric-control-center
git clone "$REPOSITORY_URL" /opt/metric-control-center
cd /opt/metric-control-center
```

В текущем workspace файлы проекта ещё не оформлены в release commit. Альтернатива — передать именно папку metric-control-center через SFTP в /opt/metric-control-center, исключив .venv, node_modules, .tools, .git, .env, .secrets и backups. Для deploy_update.sh потребуется Git checkout с выбранным release commit.

Отдельно скопируйте существующий проверенный config/metricflow-schema.json. Он не заменяется schema.example.json; deploy_server.sh остановится, если рабочей схемы нет. Передайте secrets и дампы только по защищённому SSH/SFTP при переносе существующей установки; не помещайте их в Git.

## 3. Домен, env и secrets

Создайте DNS A record, например stats.example.com → публичный IPv4 сервера. AAAA добавляйте только при рабочем IPv6. Откройте входящие TCP 80/443 и SSH в сетевом firewall VPS. Порты 3000, 8000, 5432 и 6379 production Compose не публикует.

```bash
cd /opt/metric-control-center
cp .env.production.example .env.production
nano .env.production
python3 scripts/prepare_secrets.py
```

Укажите реальный APP_DOMAIN без схемы/пути/порта и ACME_EMAIL. Оставьте HSTS_MAX_AGE=0 до проверки HTTPS. WORKSPACE_ID должен совпадать при переносе истории. SYNC_TIMEZONE задаёт календарные дни; SESSION_TTL_SECONDS — срок сессии (по умолчанию 8 часов); BACKUP_RETENTION_DAYS — срок хранения (14 дней).

Подготовка запрашивает только READ-ключ через скрытый ввод и генерирует DB password/session secret, если файлов нет. Существующие значения сохраняются. .secrets имеет права 0700; каждый контейнер получает только перечисленные для него файлы. Общие файлы доступны различным container UID, но родительская host-директория закрыта. Пароль администратора не находится в env или secrets: он вводится интерактивно и сохраняется как Argon2id hash.

READ режим и бюджет 800 запросов/сутки жёстко закреплены в production Compose. Значения ACTIONS_ENABLED/AI_ENABLED/AI_AUTOPILOT_ALLOWED/TELEGRAM_ENABLED остаются false; они не включают управление через env.

## 4. Запуск

```bash
bash scripts/deploy_server.sh
```

Скрипт проверяет схему, готовит secrets, собирает образы, запускает PostgreSQL/Redis, выполняет alembic upgrade head, интерактивно создаёт первого администратора, затем запускает stack и проверяет readiness, HTTPS, redirect и heartbeat. Любой сбой даёт ненулевой exit code; успешность не предполагается заранее.

Caddy получает и обновляет публичный сертификат автоматически при доступном домене и входящих 80/443. [Automatic HTTPS](https://caddyserver.com/docs/automatic-https). До получения сертификата внешний сайт может быть недоступен. Caddy data/config сохраняются в volumes.

Для ручного bootstrap после migrations:

```bash
docker compose --env-file .env.production -f docker-compose.production.yml run --rm backend python -m services.auth.bootstrap
```

Введите login и пароль дважды. Пароль не отображается. Повторный bootstrap откажет, если активный администратор с password hash уже существует; это ожидаемая защита.

## 5. Проверка и управление сервисами

```bash
bash scripts/check_server.sh
docker compose --env-file .env.production -f docker-compose.production.yml ps
docker compose --env-file .env.production -f docker-compose.production.yml logs --tail 50 backend worker scheduler caddy backup-job
```

В браузере: https://YOUR_DOMAIN/login → login → dashboard. Администратор открывает /admin: пользователи, настройки, readiness, quota, last sync и heartbeat. Незалогиненный /api/dashboard/* отвечает 401; OPERATOR/VIEWER не имеют административного доступа.

После реальной проверки HTTPS можно установить HSTS_MAX_AGE=31536000 и пересоздать Caddy:

```bash
docker compose --env-file .env.production -f docker-compose.production.yml up -d caddy
```

## Перенос локальной истории и quota

Не запускайте два независимых scheduler с одним MetricFlow ключом: локальные счётчики квоты не объединяются между разными БД. Остановите локальные worker/scheduler, создайте финальный backup, передайте dump и соответствующий .sha256 на сервер. Восстановите в пустую серверную БД до включения серверного worker; сохраните WORKSPACE_ID и api_quota/history. Полная процедура — BACKUP_RESTORE.md. Новая session secret автоматически сделает старые browser cookies недействительными. Пароль существующего пользователя остаётся в восстановленной БД, повторный first-admin bootstrap не нужен.

## Обновление

Сначала получите выбранный release, не меняя рабочее дерево:

```bash
git fetch origin
bash scripts/deploy_update.sh origin/YOUR_RELEASE_BRANCH
```

Порядок: backup → сохранение предыдущих image IDs/config/env/revision → checkout указанного существующего commit → build → остановка входа и ingestion → migrations → restart → readiness/HTTPS. Ненулевой exit code означает незавершённое обновление. Сохранённые образы называются mcc-rollback-SERVICE:TIMESTAMP; конфигурация хранится в .deploy-state/TIMESTAMP. Каталог не включается в Git. Не удаляйте сохранённые образы до завершения периода наблюдения.

## Rollback

Перед откатом проверьте совместимость предыдущего кода с текущей схемой БД. Даже additive migration может не пройти проверку head старого образа. Автоматический downgrade БД не выполняется.

При совместимой схеме:

```bash
bash scripts/rollback_images.sh SAVED_TIMESTAMP
```

Скрипт запрашивает буквальное schema-compatible, поднимает сохранённые образы и Caddy, проверяет readiness и доверенный HTTPS. При отсутствии совместимости сохраните текущую БД для расследования, остановите ingestion/приложение, восстановите pre-update dump в НОВУЮ БД и переключите POSTGRES_DB вместе с предыдущей конфигурацией/образами. Порядок и явное подтверждение restore — BACKUP_RESTORE.md. После этого отдельно проверьте head, вход, данные и HTTPS. Не выполняйте alembic upgrade head новым образом сразу после восстановления старой версии.

Синтаксис update/rollback проверен локально. Реальное обновление release на VPS и rollback на VPS в этой сессии не выполнялись.

## Остановка

```bash
docker compose --env-file .env.production -f docker-compose.production.yml stop
```

Остановка сохраняет volumes. Не используйте down -v для рабочей установки.
