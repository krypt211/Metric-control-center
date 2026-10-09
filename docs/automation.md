# Массовые действия и собственные правила

## Bulk actions

В статистике campaign/adset/ad можно отметить до 200 объектов, в том числе
на разных страницах. Изменение уровня/фильтров сбрасывает выбор. Перед
отправкой UI показывает подтверждение с объектами и целевыми бюджетами.

POST /api/batches принимает внутренние entity UUID и operation:
pause, enable, budget_set или budget_change. Процент считается Decimal
от собственного текущего бюджета объекта, результат округляется до 0.01.
Для mixed-currency объектов точное значение применяется в валюте каждого
кабинета; подтверждение явно показывает валюты, конвертации нет.

Batch и его items сохраняются одной транзакцией. Каждый item проходит
Action Engine через savepoint: ошибки ролей, state, pending-команд и
budget limits дают rejected только этому item. Успешные items получают
свои ActionRequest и исполняются отдельно. Пакет не является атомарной
операцией на стороне рекламной платформы, общего rollback у него нет.

Idempotency-Key обязателен; повтор payload с тем же ключом возвращает
тот же batch. Другой payload отклоняется. GET /api/batches/{id} показывает
текущий status каждой request, GET /api/batches/lookup?key=... помогает
восстановить результат без повторной отправки. UI хранит pending key в
sessionStorage и опрашивает результат; неизвестный HTTP исход не вызывает
повторный POST. Отклонённые до создания request items доступны в журнале
пакета; общий audit содержит зарегистрированные ActionRequest.

## Правила

Новые правила по умолчанию DRY_RUN. Конфигурация хранится в rules.payload;
каждое изменение увеличивает revision. PUT требует текущую revision,
повторная конфликтная запись не перетирает более новую конфигурацию.
POST create также идемпотентен по ключу оператора и workspace.

Пример формы API:

```json
{
  "mode": "DRY_RUN",
  "definition": {
    "name": "Scale Winner",
    "level": "adset",
    "window": "today",
    "currency": "USD",
    "timezone": "Europe/Moscow",
    "conditions": [
      {"metric": "roi", "operator": ">=", "value": "100"},
      {"metric": "conversions", "operator": ">=", "value": "5"},
      {"metric": "spend", "operator": ">=", "value": "50"}
    ],
    "operation": {"kind": "budget_change", "value": "20"},
    "max_budget": "300",
    "cooldown_seconds": 28800,
    "interval_seconds": 300,
    "minimum_events": 0,
    "schedule_start": "00:00",
    "schedule_end": "00:00"
  }
}
```

Все условия объединяются AND; поддерживаются >=, >, <=, <, =, !=.
Периоды: today, yesterday, last3/7/14/30. Дата определяется в timezone
правила, совпадающей с timezone фактов. Валюты не складываются и не
конвертируются. account_ids, если указаны через API, ограничивают кабинеты.
Уровни campaign/adset агрегируются из ad-фактов с проверенными parent IDs,
как в таблице. Необходимо настроить parent/current-state/conversions mappings.

OFF не оценивается. DRY_RUN сохраняет would_act либо причину пропуска/
отклонения в rule_runs, не создаёт команд и cooldown. Он проверяет
роль, current state, capability и числовые policy limits, но не требует
включённого live action worker или подтверждённого HTTP budget contract.

ACTIVE проходит полный Action Engine. По умолчанию изменение бюджета
ограничено 20% и общим ACTION_MAX_BUDGET. Rule ceiling — дополнительный
лимит; превышение отклоняется, бюджет не обрезается автоматически.
minimum_events относится к conversions выбранного окна. Неизвестный
показатель не превращается в ноль; устаревшие факты/state блокируют действие.
ROI/CPA/CTR вычисляются от сумм без предварительного округления процентов.

Расписание — ежедневный интервал HH:MM в timezone правила; одинаковые
границы означают весь день, поддерживаются интервалы через полночь.
Выбор дней недели пока не реализован. Scheduler ставит rules.evaluate
каждую минуту; БД учитывает interval_seconds. Одна due-оценка атомарно
занимает rule, вычисляет решения и сохраняет Run/Request/Cooldown. Конкурентный
worker не получает ту же due-оценку. Cooldown хранится по rule/entity,
ставится при успешной постановке команды, переживает перезапуск/редактирование.
Отклонённая позднее команда также сохраняет cooldown; автоматического retry нет.

Fingerprint revision/mode/window/metrics/observations/current-state подавляет
повторы одной оценки. Свежая наблюдаемая статистика позволяет новую проверку;
фактически отправленные/ожидающие команды дополнительно защищены pending lock.
Перед внешним POST rule worker проверяет ACTIVE/revision, окно/расписание,
условия/minimum events и свежесть заново. Затем действие подтверждается новым
sync, как ручная команда. Выключение правила не может отозвать уже начатый POST.

## Аудит и провайдеры

ActionRequest.provenance хранит серверного автора, entity name/provider,
source web/rule, batch/rule ID, rule name, показатели/причину, before/after
и валюту. ActionLog фиксирует очередь, попытку, ответ/ошибку и сверку.
GET /api/audit и вкладка «Журнал» показывают последние 100 команд;
rule_runs доступны отдельно, в том числе симуляции и причины пропуска.

services/actions/providers.py объявляет проверенные возможности MetricFlow:
pause/enable/budget_set. Meta пока зарезервирован без рабочих возможностей.
Неподтверждённый bid_set отвергается до очереди/HTTP. В публичном списке
[MetricFlow API](https://metricflowit.click/docs) есть pause/enable/budget;
описание bid в UI/rules не подтверждает отдельный публичный bid endpoint.
Будущий Meta-адаптер потребует авторизации, capabilities, provider IDs,
кодирования суммы/стратегии и проверок; он ещё не подключён.

AI не запускается и не имеет ключей. Будущий сервис решений должен подавать
структурированные предложения в Action Engine с серверной identity и
source/reason, не получать доступ к writer или выбирать обход policy.

Текущие ограничения: агрегаты собираются в Python; большой объём потребует
SQL-агрегатов и индексов под scope. Полнота входной статистики/атрибуция и
семантика daily/lifetime budget должны быть подтверждены на реальном API.
