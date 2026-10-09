# Архитектура

Получение данных, аналитика, принятие решения и исполнение разделены.

```text
MetricFlow / Meta → connector → raw data → normalization → PostgreSQL
                                                        ↓
                                                  analytics
                                                        ↓
                                    dashboard / rules / AI
                                                        ↓
                                              action proposal
                                                        ↓
                                         policy + action engine
                                                        ↓
                                          provider write adapter
                                                        ↓
                                      reconciliation + audit + Telegram
```

| Каталог | Ответственность |
|---|---|
| frontend | Интерфейс, без ключей и вызовов API провайдеров |
| backend | HTTP API и серверная identity локального оператора |
| services/metricflow | Пути, авторизация, транспорт MetricFlow |
| services/analytics | Агрегаты и формулы из БД |
| services/sync | Нормализация и синхронизация с quota/lease |
| services/actions | Единственная точка подключения write-ключа, далее исполнение и аудит |
| services/rules | Публичный импорт RuleEngine / RuleDefinition |
| services/automation | Batch orchestration, правила и общий Emergency Stop без provider credentials |
| services/ai | Python snapshots, LLM/agent DB tools, GEO/offer profiles, durable proposals, approvals и policy |
| services/telegram | Личный чат, /stop_auto, notifications, confirm/review/reject и replay guards |
| workers | Фоновые процессы |
| migrations | Версионируемая схема БД |

`StatisticsSource` и `ActionSource` определяют минимальные границы адаптеров.
Полный нормализованный доменный контракт будет создан после проверки API.
Сейчас переносимый интерфейс не обещает одинаковые JSON-схемы разных провайдеров.

В БД сущность получает внутренний UUID и provider/account/external_id.
Прямой Meta пока не подключён. Для будущей интеграции нужно подтвердить
сопоставление provider IDs; одинаковые строки не доказывают общий identity.
При одновременном подключении Meta/MetricFlow выбираем один источник
статистики для кабинета/периода, не суммируем дубли. Tracker имеет отдельные
таблицы, даты и валюту.

Траты и конверсии храним по дням, аудитории — отдельно от общих итогов.
CTR/CPC/CPM рассчитываем из суммарных числителей и знаменателей.
Данные последних дней перечитываем с upsert: результаты могут уточняться.
Окно повторной загрузки и расписание задаются после проверки лимитов.

БД, приложение и очередь расположены на одном сервере на первом этапе.
Схема PostgreSQL и persistence реализованы через SQLAlchemy и Alembic.
Первая миграция использует замороженный metadata snapshot, поэтому изменение
ORM-моделей не изменяет прошлую миграцию. Для следующих изменений добавлять
новые ревизии, а не редактировать schema_v1.py.

Факты уровня ad используются для агрегации кабинетов, кампаний, групп и
креативов. Таблица не складывает ad-факты с campaign/adset-фактами.
Один креатив в нескольких объявлениях получает сумму их уникальных строк.
Родительские связи и labels приходят через явно настроенные поля adapter.
GEO читает country-only breakdowns; общие tracker-итоги к ним не присоединяются.

В этой версии UI читает только БД. Backend не получает MetricFlow-ключей.
Read worker получает READ, Action worker — WRITE. Проверку результата
команды выполняет Action Engine по более новой текущей state-записи,
которую read worker получает от провайдера. Это периодическая сверка,
а не немедленный проверочный HTTP-запрос из action worker.

Правила получают те же ad-агрегаты, что таблица. Их due-оценка, запись
Run, постановка ActionRequest и cooldown атомарны. DRY_RUN сохраняет
только Run. Вторая миграция добавляет provenance, batches и rule cooldowns;
не изменяет первую ревизию. Frontend вызывает backend через серверный
proxy с operator token; WRITE остаётся только в action worker.

Третья миграция добавляет daily reach/frequency и отдельные detector settings.
Recommendations читают факты/тренды и не создают команд. Частота родительской
сущности загружается отдельным optional /insights job через READ worker;
её не восстанавливают суммой reach или средним frequency отдельных ads.

Четвёртая миграция добавляет AI settings/quotas и durable approvals; пятая —
общий automation control/event log, GEO/offer profiles/cooldowns и историю чата.
AI-worker обрабатывает вопросы с ограниченными DB tools, сохраняет предложения,
а CopilotEngine ставит одобренные команды в общий Action Engine. Natural-language
scope имеет отдельный fingerprint фактов страны/оффера. Команды из чата требуют
ручного CONFIRM при любом уровне автономности. Правила и AI проверяют persistent
Emergency Stop при постановке в очередь и непосредственно перед HTTP;
ingestion от этого состояния не зависит. Автоматические транзакции блокируют
control до ActionRequest, чтобы stop и worker соблюдали один порядок блокировок.
Подробности: [ai-agent.md](ai-agent.md).
