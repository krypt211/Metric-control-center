# MetricFlow — подготовка обратного ENABLE_AD, 21.10.2026

## Готовность

PREPARED_NO_POST_AUTHORIZATION. Реальный ENABLE не запускался.

- Request: 80836c7e-e9a9-41f8-a687-f88c0ce59997, revision 1, DRAFT.
- AD: #71012012_EGR_Creo 03 / 120247730105960571.
- Account: Valya Sergeeva / act_1047962734516123.
- Campaign: 120247730079240571; AdSet: 120247730105950571.
- Свежий READ: campaign PAUSED/PAUSED, adset PAUSED/PAUSED, AD PAUSED/PAUSED.
- Source timestamp: 21.10.2026 13:10:21 UTC / 16:10:21 МСК.
- Baseline expiry: 13:25:21 UTC / 16:25:21 МСК. DRAFT expiry: 13:28:01 UTC.
- Срок не продлевается временем HTTP-ответа. После истечения нужны свежие проверки.
- Новый POST/permit/ActionExecution для ENABLE отсутствует.

Подготовка потребовала GET /me через Credential Manager и три GET каталогов через
сохранённый отдельный WRITE credential revision 1 с campaigns:read/entities:write.
Ключ не заменялся; проверка SCOPES_VERIFIED / active_paid. READ revision 1 healthy,
last_success_at 13:10:02 UTC. Метаданные и статусы получены из документированных READ,
секреты не записывались. Четыре protective flags и .env SHA не изменены.

## Локальное закрытие прежнего PAUSE

Первый PAUSE: 79e47858-d850-4935-b2a3-e0d6c1b72b85. Пользователь уточнил иерархию
и подтвердил выключенный переключатель именно AD 120247730105960571.
Это сохранённое позднее наблюдение сопоставлено со свежим READ и обоими родителями.

Добавлен узкий локальный review: только тот же admin/workspace/entity, spent wire,
одна предыдущая попытка, завершённое execution live_unknown с точной причиной
MANUAL_READBACK_DEADLINE, истёкшее окно и последнее положительное ручное наблюдение
того же AD. Более поздний отрицательный ответ или изменение evidence блокируют review.

Старая ActionRequest переведена unknown -> MANUALLY_REVIEWED, revision 11. Это
закрытие локального ожидания после ручной проверки, а не переобъявление API-успеха.
ActionExecution остаётся live_unknown / MANUAL_READBACK_DEADLINE; control OUTCOME_UNKNOWN,
attempts=1 и wire_spent=true, все старые журналы сохранены. Новое событие
pilot_prior_pause_locally_reviewed содержит pinned ID/hash поздней сверки и свежий
baseline; authoritative_api=false, creates_pause_ownership=false.

Новая ENABLE-карточка привязана к ID/hash этого локального review. На каждом будущем
contract boundary проверяются прежняя команда, её spent wire, execution, последний
ручной ответ и неизменность pinned evidence. Namespace остаётся
UNVERIFIED_CANDIDATE_FACEBOOK_AD_ID, источник USER_REQUESTED_EXPERIMENT.

## Контракт и ограничения будущего теста

Анонимным GET повторно проверен официальный
[OpenAPI](https://metricflowit.click/api/v1/openapi.json?lang=en).
SHA256 f52bc8ca0691fa0e2f2b5a5de06aa74a897546b88705ee16851859138a2f3327.
ENABLE endpoint, EntityActionRequest и EntityActionResponse совпали с предыдущим
официальным snapshot. Первый локальный разбор не завершился из-за неверной кодировки
чтения cached файла; после исправления UTF-8 выполнена успешная проверка.
Web-инструмент страницу не открыл, использован прямой анонимный GET без credentials.
Context7 использован для Pydantic 2 cross-field validators; он не заменяет MetricFlow
спецификацию. Новый provider HTTP-контракт не придумывался.

```http
POST /api/v1/entities/120247730105960571/enable
Content-Type: application/json

{"level":"ad"}
```

Будущий допуск — только ENABLE_AD одного AD с own/effective PAUSED/PAUSED и обоими
родителями PAUSED/PAUSED. Ни Campaign/AdSet WRITE, ни budget/bid, ни async jobs не
допускаются. Перед POST после durable claim — ровно три GET каталогов и повторная
проверка полного согласованного свежего снимка. Максимум 3 pre-POST GET + 1 POST,
concurrency 1, window <=600 s, общий POST-stage timeout <=30 s. Нет retries/resend.

Отдельное обязательное согласие:
AUTHORIZE_ONE_EXPERIMENTAL_ENABLE_WITH_UNVERIFIED_ID.
PAUSE statement и PREPARE statement его не заменяют. Подготовка не разрешает запуск.

Общий capability registry остаётся BLOCKED. Без разрешения глобальные сервисы
ACTIONS_ENABLED=false / LOCAL_READ_ONLY=true. AI_ENABLED=false,
AI_AUTOPILOT_ALLOWED=false, Meta LIVE отключён. При будущем разрешённом запуске
допуск задаётся только отдельному single-operation процессу, без открытия обычных
workers/scheduler. Все существующие gates продолжают действовать.

## Риски и следующий ручной этап

WRITE namespace для произвольных объектов по-прежнему не подтверждён. Первый PAUSE
дал эмпирическое наблюдение на этом AD, но ENABLE отдельно ещё не проверен.
Право управления объектом — USER_ATTESTED. MetricFlow READ кэшируется, не является
атомарной блокировкой родителей в Meta. Включение AD может разрешить доставку, если
кто-то извне включит родителей; перед запуском нужно проверить их переключатели и
не включать их в окно теста.

После отдельного явного разрешения пользователя: обновить истёкшие проверки, пройти
existing private authorize/execute, отправить максимум один ENABLE, остановиться,
получить ручную сверку собственного переключателя AD. ACK не равен успеху.
Нельзя автоматически восстанавливать статусы, повторять POST, создавать Rule Engine
ownership или объявлять поддержку Campaign/AdSet по результату одного AD.

## Фактические проверки

- Existing experimental/private API: 52 PASS.
- Existing production pilot/contract/private API: 103 PASS.
- New ENABLE tests: 13 PASS. В начальных запусках исправлены только тестовые
  FK-ссылка на несуществующий объект и имя переменной; финальные наборы выше зелёные.
- Restored PostgreSQL private schema: PASS; late review + ENABLE, 6 mock GET
  (подготовка и повторная проверка), 1 mock ENABLE, NO_RESEND; прежний UNKNOWN и факты
  сохранены. Все provider HTTP — MockTransport; isolated schema удалена в finally.
- Ruff check/format: PASS для изменённых модулей и новых тестов/scripts.
- Playwright Edge smoke: 3 PASS, без provider requests. UI исходники не менялись;
  это проверка login/auth redirect/page errors, не authenticated end-to-end ENABLE.
- Source secret scan и staged diff check: PASS. Миграции и role grants не требовались.

Обновлены только backend и CM образом
metric-control-center-experimental-enable-20261021:prepared. Полная сборка
задержалась и остановлена; зависимости не менялись. Итоговый слой COPY services
собран поверх проверенного фактически работающего образа
sha256:df734db7d2af1b2aad46525e5e83964ed8c87376dcb5683218a76e56b635d43a.
13 module hashes совпали с исходниками в обоих обновлённых контейнерах.

До подготовки 14 защищённых таблиц совпали полностью. После подготовки ожидаемо:
action_requests +1 и локальный review старого запроса, action_logs +3,
write_credential_audit +1, обновлён результат проверки ключа. Остальные 10 таблиц,
включая ActionExecution, не изменены. .env и остальные пять service container IDs
не изменены; volumes не удалялись. Sanitized evidence: ignored
.tools/experimental-live-20261021/enable-*.

FINAL STATUS: ENABLE PILOT PREPARED — EXPLICIT AUTHORIZATION REQUIRED.
ENABLE LIVE POST: 0. ADVERTISING WRITE REQUESTS TOTAL: 1 (PREVIOUS PAUSE ONLY).
