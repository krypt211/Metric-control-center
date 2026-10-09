# AI Copilot, approval и policy

Реализованы этапы 35–45; чат и инструкции описаны в [ai-agent.md](ai-agent.md).
По умолчанию `AI_ENABLED=false`, mode `OFF`,
`AI_AUTOPILOT_ALLOWED=false`, `TELEGRAM_ENABLED=false`, рекламные действия выключены.
Ключей провайдеров в исходниках нет. Реальные запросы к LLM/Telegram пока не выполнялись.

## Snapshot и расчёты

Оператор выбирает 1–30 Campaign/Adset/Ad/Creative. Python читает собственную БД,
считает totals и производные метрики тем же способом, что dashboard. Snapshot включает
иерархию IDs, spend/CTR/CPC/CPM/leads/sales/conversions/CPL/revenue/profit/ROI,
today и последние 1/3/7 завершённых дней, account CPL и относительную разницу,
Winner/Loser thresholds и Fatigue с причинами отсутствия подтверждения.

Тренды сравнивают завершённые периоды одинаковой длины: 1 день с предыдущим 1,
3 с предыдущими 3, 7 с предыдущими 7. Незавершённое today отдельно.
Ratios считаются из сумм, пропуск календарного дня не становится нулём,
изменение при неизвестном/неположительном baseline остаётся `null`.
При смешанных или неполных tracker sources производные conversion metrics неизвестны.
Frequency не усредняется между объявлениями. Валюты не конвертируются.

История собирается по текущим связям Campaign/Adset/Creative. При переназначении
креатива историческая связь отдельно пока не хранится. Большие аккаунты требуют
дальнейшей оптимизации построения snapshots; V1 ограничивает анализ 30 сущностями.

LLM получает IDs и аналитику, без provider raw JSON, названий, URLs, ключей и средств
управления рекламой. Он возвращает typed output: summary, entity_id, action,
percentage, confidence, reason, priority и evidence IDs. Известность ID/evidence,
единственность рекомендации и схема проверяются сервером. Объяснения остаются
текстом модели: числовые факты проверяют по snapshot. Confidence — самооценка модели,
не калиброванная вероятность и не замена statistical thresholds.

## Режимы

- `OFF`: новые анализы не принимаются.
- `READ_ONLY` (LEVEL 0): только анализ, без предложений и ActionRequests.
- `RECOMMEND` (LEVEL 1): рекомендации и причины отказа policy, никаких ActionRequests.
  Старый `COPILOT` совместим и преобразуется в `RECOMMEND`.
- `APPROVAL`: предложения сохраняются `pending`, оператор одобряет или отклоняет.
- `AUTOPILOT`: тот же путь одобрения и очереди вызывается автоматически;
  включение требует отдельно `AI_AUTOPILOT_ALLOWED=true` на сервере.

Analysis сохраняется в БД с idempotency key, snapshot, revision policy и сроком
действия (15 минут по умолчанию). Worker забирает queued → generating один раз;
после сбоя/таймаута повторного LLM-запроса нет. Generating/queued с истёкшим сроком
становятся expired при следующем запуске worker. При OFF worker не вызывается;
срок действия всё равно проверяется при одобрении/отправке.

Смена policy revision отменяет возможность исполнения старых предложений.
Одобрение проверяет свежую аналитику, fingerprint чисел/окон/иерархии и budget/status,
права оператора, policy, общую ActionPolicy и verified encoding API.
Проверки повторяются перед единственным provider POST. Любое изменение evidence
требует нового анализа. Это консервативная проверка: даже поздняя конверсия в
историческом окне может отменить предложение.

Approve All сохраняет результаты каждого предложения: queued либо denied.
Повторное одобрение не создаёт новых команд. Reject разрешён до одобрения;
одобренные/исполняющиеся команды через Reject отменить нельзя. В audit есть
source `ai`, proposal, reason, decision_id, before/after, инициатор и approval channel.

## Policy

Python разрешает pause Ad/Adset и изменение бюджета Campaign/Adset.
Enable Ad/Adset требует явного `allow_enable=true`, по умолчанию запрещён.
Delete/create/bid/tracking/pixel/URL отсутствуют в output schema и policy.
Defaults: максимум ±20%, бюджет ≤300 USD, ≤30 AI действий/день.
Эти максимумы можно уменьшить. При выборе другой валюты бюджетный потолок задан
в единицах этой валюты; FX не выполняется и аккаунты иной валюты не управляются.
`daily_budget_verified=false` запрещает budget changes до проверки, что источник
возвращает дневной, а не lifetime бюджет. Сверка единиц/encoding MetricFlow обязательна
в дополнение к этой настройке. Budget target и округление рассчитывает Decimal/Python.

Дневные лимиты общие для workspace по Europe/Moscow. Атомарный счётчик ограничивает
постановки в очередь и отдельно реальные попытки в день отправки. Повторное одобрение
не расходует слот. Отменённый уже принятый запрос не возвращает слот очереди;
quota/provider rejection после attempt reservation тоже расходует attempt slot.
Число анализов ограничено отдельно: defaults 20/day, максимум 100/day.

## OpenAI

Адаптер использует [Responses API](https://developers.openai.com/api/docs/guides/migrate-to-responses)
и [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses):
`text.format` json_schema strict, `store=false`, без retries.
Пакетный анализ работает без tools; чат использует ограниченные DB/propose tools.
`store=false` выключает хранение response state, не обещает отсутствие всех
провайдерских журналов. ProviderFailure сохраняет класс ошибки без raw response.
Модель задаётся явно через `OPENAI_MODEL`, универсальное имя по умолчанию не угадано.
Общий `CopilotProvider` позволяет добавить другого провайдера без смены Action Engine.

Для подключения:

1. Запустить `python scripts/setup_local.py` для создания отсутствующих secret files.
2. Поместить ключ в `.secrets/openai_api_key`; выбрать модель в `.env`.
3. Поставить `AI_ENABLED=true`, оставив `AI_AUTOPILOT_ALLOWED=false`.
4. Запустить `docker compose --profile web --profile ai up -d --build`.
5. На вкладке AI Copilot сохранить `READ_ONLY` или `RECOMMEND`, выбрать сущности после синхронизации.
6. Позже перейти к `APPROVAL`; рекламные команды требуют отдельно работающего
   actions profile и `ACTIONS_ENABLED=true`. Ключ WRITE остаётся только action-worker.

Backend/front-end получают лишь operator credentials, AI-worker — OpenAI key,
ingestion — READ MetricFlow, action-worker — WRITE. AI-worker не вызывает MetricFlow.
Scheduler отправляет `ai.process` каждые 15 секунд только при `AI_ENABLED=true`.

## Telegram

Опциональный процесс `python -m services.telegram.bot` использует
[Telegram Bot API](https://core.telegram.org/bots/api), long polling без публичного webhook.
Он получает только bot token и БД, не OpenAI/MetricFlow keys. Для каждой связи
`telegram_user_id == chat_id` и явный локальный `user_id` оператора.
Поддерживаются личные чаты, group chats в V1 не поддерживаются.

1. Добавить bot token в `.secrets/telegram_bot_token`.
2. Скопировать `config/telegram-bindings.example.json` в
   `config/telegram-bindings.json`, заменить синтетический ID на реальный и указать
   существующего оператора. Пользователь должен открыть личный чат с ботом.
3. Удалить ранее настроенный webhook у этого бота, если он есть: getUpdates с ним
   несовместим. Запускать один экземпляр long-polling процесса на bot token.
4. `TELEGRAM_ENABLED=true`, запустить `docker compose --profile telegram up -d`.
   Для чата включить AI и пересоздать оба сервиса:
   `docker compose --profile ai --profile telegram up -d --build`.

Pending решения отправляются их владельцу с APPROVE ALL / REVIEW / REJECT.
В кнопках случайный opaque token, проверяются sender/chat/message_id/owner/workspace.
Данные из callback не выбирают entity/value/actor. REVIEW обновляет сообщение;
approve/reject используют тот же CopilotEngine. Callback result и cursor сохраняются,
replay безопасен. Ack failure не блокирует inbox. Уведомления с неопределённым исходом
отправки не повторяются автоматически; решение остаётся доступно через веб-интерфейс.
Смена bot token на другой bot создаёт отдельный cursor, но старые notification rows
не рассылаются повторно. Telegram credentials/bindings не публиковать.

## Проверка

Mock-HTTP проверяет официальный request shape, refusal/incomplete/429 без retry,
а SQLite — proposal states, approvals, quotas, drift, expiry, role/workspace,
Autopilot gate, Telegram callback identity и повторную доставку. Live OpenAI/Telegram,
PostgreSQL/Celery runtime и работа с реальной рекламой требуют отдельной проверки
после настройки ключей и API contract.
