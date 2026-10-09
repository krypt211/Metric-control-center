# Migrations

Alembic revision 0001 создаёт 25 таблиц. schema_v1.py — неизменяемый
snapshot схемы первой ревизии. Последующие изменения оформлять новыми
ревизиями, сохраняя исторические snapshot-файлы.

`alembic upgrade head` использует DATABASE_URL либо настройки PostgreSQL
и POSTGRES_PASSWORD_FILE. В Compose migrate запускается перед backend/worker.
Production — PostgreSQL; SQLite используется только для локальных тестов
и пустого preview. Не выполнять downgrade на рабочей БД без плана восстановления.
