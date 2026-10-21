# MetricFlow — первый экспериментальный LIVE PAUSE_AD, 21.10.2026

## Результат

ONE POST SENT / HTTP 200 / ACKNOWLEDGED / MANUAL READBACK PENDING.
Это подтверждение приёма одной команды, не доказательство изменения собственного
статуса AD и не подтверждение общего WRITE namespace для всех объектов.

Пользователь отдельно разрешил один экспериментальный PAUSE_AD для
120247730105960571 с принятием риска неподтверждённого WRITE ID. Перед этим вручную
подтвердил: кампания и группа выключены, AD включено. Разрешение не распространяется
на ENABLE, родителей, бюджеты, ставки, повторный POST или автоматические правила.

- Account: Valya Sergeeva / act_1047962734516123.
- AD: #71012012_EGR_Creo 03 / 120247730105960571.
- AdSet: 120247730105950571; Campaign: 120247730079240571.
- Request: 79e47858-d850-4935-b2a3-e0d6c1b72b85.
- PostgreSQL: verifying, revision 9.
- Control: SYNC_ACKNOWLEDGED_NEEDS_MANUAL_READBACK.
- ActionExecution: live_acknowledged, error_code null.
- attempts=1, wire_spent=true. Повторная отправка запрещена.

## Последовательность

Предыдущая команда 20 октября была остановлена auto-review из-за отсутствия кредитов
до исполнения. При продолжении 21 октября Docker Desktop оказался остановлен;
первая команда не дошла до контейнера. Запущен существующий Desktop, без удаления
volumes и пересоздания сервисов. Ни один из этих отказов рекламный POST не отправил.

Старая карточка 776a0dd3-6130-4785-ba41-b6d3596afd10 закрыта штатным переходом после
истечения. Подготовлена новая на тот же выбранный пользователем AD. GET /me через CM
подтвердил SCOPES_VERIFIED / active_paid, WRITE revision 1. Три GET каталогов дали
снимок source_updated_at 21.10.2026 09:25:14 UTC: campaign PAUSED/PAUSED,
adset PAUSED/PAUSED, AD ACTIVE/ADSET_PAUSED. Полная иерархия сопоставлена.

Обычные backend/CM/worker/scheduler не включались в WRITE. Для отдельного docker exec
процесса конфигурация ACTIONS_ENABLED=true и LOCAL_READ_ONLY=false была передана
только на время одной авторизации и одного исполнения. .env и environment работающих
сервисов не изменялись. Существующие ActionSafetyGate, проверка PilotContract,
preflight/confirmation, explicit authorization, durable claim, credential revision,
quota и consume-before-HTTP не подменялись и не отключались.

В permit записано AUTHORIZE_ONE_EXPERIMENTAL_PAUSE_WITH_UNVERIFIED_ID. Использован
ограниченный реальный transport: только три документированных GET выбранного account
и один точный POST; retries=0, redirects запрещены, прочие пути/методы отклоняются.
Перед POST после durable claim повторены три GET campaigns/adsets/ads, все HTTP 200.
Проверка родителей прошла; transport не изменяет результаты этих проверок.

Рекламный запрос 21.10.2026 09:31:23 UTC / 12:31:23 МСК:

```http
POST https://metricflowit.click/api/v1/entities/120247730105960571/pause
Content-Type: application/json

{"level":"ad"}
```

Получен HTTP 200. Existing typed adapter принял sync ACK с success=true и точным
entity_id, без async job. Тело ответа/заголовки с секретами в отчёт не копировались.
Execution completed_at 09:31:26 UTC. Не вызывались ENABLE/BUDGET/BID, Campaign/AdSet
WRITE, Meta API, async job GET, повторный POST или дополнительный автоматический
READ polling. Выполнено 3 GET + 1 POST в стадии исполнения; с подготовкой всего
7 authenticated GET + 1 POST (GET /me + 3 GET подготовки + 3 GET повторной проверки).

## Проверка после исполнения

Локальные SELECT и runtime probes подтвердили в backend и CM:

- ACTIONS_ENABLED=false; LOCAL_READ_ONLY=true.
- AI_ENABLED=false; AI_AUTOPILOT_ALLOWED=false.
- ActionSafetyGate: WRITE_DISABLED; global capability: BLOCKED.
- .env SHA256 не изменился.
- WRITE credential revision 1; READ revision 1, сохранённый health healthy.
  Последний обычный успешный sync на момент probe — 20.10.2026 20:10:04 UTC;
  это не новый замер freshness обычной READ-публикации.
- Meta disabled/disconnected revision 4.
- ActionExecution ровно 1, рекламный POST ровно 1, исполненный повтор 0.
- Provider accepted contract evidence=0. Сохранён один исторический
  LIVE_SINGLE_OPERATION control record с израсходованным wire budget, не открытый
  глобальный допуск и не разрешение на второй запрос.

Санитизированные evidence: ignored .tools/experimental-live-20261021/
card.json, execution.jsonl, database-result.json, runtime-before.json,
runtime-after-backend.json, runtime-after-credential-manager.json.

## Следующий обязательный шаг

Пользователю отправлен запрос ручной сверки в Ads Manager: обновить карточку точного
AD и проверить его собственный переключатель, оба родителя и время наблюдения.
HTTP 200 не заменяет эту сверку. До неё не объявлять PAUSE функционально проверенным.
Окно permit истекает 21.10.2026 09:40:14 UTC / 12:40:14 МСК. Позднее наблюдение
можно сохранить как ручной факт, но нельзя задним числом объявлять своевременную
верификацию, снимать UNKNOWN или автоматически повторять команду.

Ручной ответ записывается существующим record_manual_readback. Успешная ручная сверка
не создаёт authoritative API readback или ownership для Rule Engine. Никакого ENABLE
без отдельного разрешения и отдельной проверки. Campaign/AdSet WRITE не проверены.

## Проверки кода

В этом этапе production-код не менялся; повторные unit-тесты не запускались.
Использована реализация коммита 58ac0b9, ранее проверенная наборами 103/52/258 PASS,
PostgreSQL race/restricted-role mock harness, frontend typecheck и Playwright smoke.
Текущее исполнение — один реальный ограниченный интеграционный тест, не mock.

FINAL STATUS: ACKNOWLEDGED; MANUAL READBACK PENDING; NO RESEND.
ADVERTISING WRITE REQUESTS: 1.

## Ручная сверка и противоречие источников — 21.10.2026

Пользователь ответил: «AD по-прежнему включено». Это отрицательная ручная сверка:
собственный статус ACTIVE не совпадает с целевым PAUSED. Точное время наблюдения,
effective status и повторное подтверждение обоих родителей не были сообщены;
эти значения не выдумывались. В ActionLog добавлено pilot_manual_status_mismatch_reported
с observed_at=null и USER_REPLY. Полный record_manual_readback с обязательным effective
status не использован для неполного ответа.

На момент локальной фиксации 11:17 UTC окно permit уже истекло. Существующий
ActionEngine.verify_pending штатно перевёл запрос в unknown, revision 10,
control OUTCOME_UNKNOWN, execution live_unknown / MANUAL_READBACK_DEADLINE.
Это техническая причина закрытия окна, а не диагностированный ответ MetricFlow.
Сохранены attempts=1, wire_spent=true. ACK HTTP 200 остаётся историческим фактом.

Один диагностический READ через отдельный READ-ключ, с общей квотой и retries=0,
получил именно AD 120247730105960571:

- configured_status PAUSED;
- effective_status PAUSED;
- parent_id 120247730105950571; campaign_id 120247730079240571;
- source_updated_at 21.10.2026 11:16:04 UTC / 14:16:04 МСК;
- retrieved_at 11:19:04 UTC / 14:19:04 МСК.

Ранние локальные диагностические запуски остановились до GET. Был обнаружен сохранённый
READ health error / PROVIDER_READ_FAILED после сетевого TransportUnavailable штатного
sync в 11:10 UTC; предыдущий sync 11:03 UTC был успешным. Однократный GET каталога
успешен, но health вручную не переписывался. Cooldown отсутствовал, лимит не менялся.

MetricFlow READ — кэшированное состояние провайдера, не прямой authoritative Meta
readback. Оно противоречит пользовательской сверке Ads Manager. Нельзя объявить PAUSE
успешно проверенным, выбрать удобный источник, подтвердить WRITE namespace, снять
UNKNOWN или создать pause ownership для правил. Причина расхождения пока неизвестна:
данные не позволяют отличить задержку/кэш, отображение другого объекта или проблему
на стороне провайдера. Гипотезы не считаются диагнозом.

В ActionLog добавлено pilot_read_manual_conflict_recorded; UNKNOWN сохранён.
Запрошена повторная ручная сверка точного Ad ID после обновления страницы Ads Manager
с указанием собственного переключателя и времени. Ни PAUSE, ни ENABLE не повторялись.
Глобальные четыре safety flags сохранены; Meta LIVE не подключался.

Новый итог: MANUAL/READ CONFLICT; OUTCOME UNKNOWN; NO RESEND.
ADVERTISING WRITE REQUESTS TOTAL: 1.
Additional diagnostic GET: 1. Код не менялся; unit-тесты повторно не запускались.

## Уточнение объекта и положительная поздняя сверка

После сопоставления точных ID пользователь подтвердил нужную кампанию
120247730079240571 и объявление #71012012_EGR_Creo 03. На вопрос о собственном
переключателе AD 120247730105960571 ответил: «выключен».
120247730105950571 — родительская группа «3», а не ID объявления; это проверено
локальными entities/adsets/ads и иерархией. Журнал физической отправки подтверждает
POST именно на разрешённый AD 120247730105960571, без смены цели.

Текущая ручная сверка теперь совпадает с диагностическим MetricFlow READ: собственный
статус AD PAUSED. Предыдущее отрицательное сообщение заменено последующим уточнением
пользователя; его исторический аудит не удалялся. Нельзя достоверно восстановить,
какой переключатель был осмотрен ранее или точный момент смены статуса. Точное время
новой сверки и effective status не сообщались и не подставлялись из старого снимка.

В БД добавлен pilot_late_manual_target_confirmed с matches_target=true,
configured_status=PAUSED, source USER_REPLY_AFTER_ID_CLARIFICATION, observed_at=null.
Срок первоначального permit уже истёк: request остаётся unknown / revision 10,
execution live_unknown / MANUAL_READBACK_DEADLINE. Позднее наблюдение не превращает
проверку в своевременный authoritative readback и не создаёт pause ownership правил.

Результат ограниченного опыта: один PAUSE принят HTTP 200, после него выключенный
переключатель нужного AD подтверждён пользователем; MetricFlow также сообщает PAUSED.
Это эмпирическое подтверждение для данного AD и операции, не общее подтверждение
namespace, ENABLE_AD, Campaign/AdSet WRITE или автоматического Rule Engine.
Глобальные ACTIONS_ENABLED=false, LOCAL_READ_ONLY=true, AI_ENABLED=false,
AI_AUTOPILOT_ALLOWED=false сохранены. Новых provider GET/POST не выполнялось.

FINAL OBSERVATION: TARGET PAUSED CONFIRMED MANUALLY (LATE).
FORMAL EXECUTION: UNKNOWN — ORIGINAL READBACK DEADLINE EXPIRED.
ADVERTISING WRITE REQUESTS TOTAL: 1. ENABLE NOT AUTHORIZED / NOT EXECUTED.
