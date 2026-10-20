# Experimental AD pilot — подготовка 20.10.2026

Пользователь выбрал «Подготовить экспериментальный пилот на этом AD».
Это разрешение на разработку и подготовку, не на рекламный POST.
Цель: act_1047962734516123, AD 120247730105960571, Campaign 120247730079240571,
AdSet 120247730105950571. Первая будущая команда — только PAUSE_AD.

## Допуск и границы

Использован существующий ActionEngine, его workspace locks, durable claim,
ActionExecution, quota/cooldown, deadline, UNKNOWN и manual readback. Второй
рекламный dispatcher не создавался. Эксперимент — отдельный тип допуска внутри
приватного PilotContract, не общее включение WRITE.

- Namespace записан как UNVERIFIED_CANDIDATE_FACEBOOK_AD_ID.
- Источник допуска USER_REQUESTED_EXPERIMENT, аудит pilot_experimental_prepared.
  Это не PROVIDER_DOCUMENTATION/PROVIDER_CLARIFICATION и не событие
  pilot_external_evidence_accepted. Подтверждение namespace не подделывается.
- Первый эксперимент поддерживает только PAUSE_AD, строго один указанный AD.
  ENABLE_AD, Campaign/AdSet, budget/bid, async/job GET этим допуском не разрешены.
- Отдельное будущее POST-согласие:
  AUTHORIZE_ONE_EXPERIMENTAL_PAUSE_WITH_UNVERIFIED_ID.
  Обычное согласие для подтверждённого контракта или PREPARE не принимается вместо него.
- Общий capability registry остаётся BLOCKED/UNVERIFIED. Legacy/Rule/AI не получают
  разрешения; все четыре защитных флага сохранены при подготовке. Исполнение требует
отдельного согласования и прохождения существующего ActionSafetyGate.

Приватный POST /controlled-pilot-experimental/prepare создаёт только локальный DRAFT.
Требует действующие admin session, CSRF, trusted origin, точную revision ключа и
явную boolean-attestation о правах. Caller не может передать свой baseline, токен,
разрешающий флаг или POST authorization в body подготовки.

## Собственный статус и выключенные родители

Обычный EntityCurrentState продолжает хранить effective/delivery status. Он не
переписывается ради подготовки. Для экспериментальной команды отдельно сохраняется
проверенный READ baseline в её provenance/audit:

- Campaign status/effective = PAUSED/PAUSED;
- AdSet status/effective = PAUSED/PAUSED;
- AD status/effective = ACTIVE/ADSET_PAUSED.

Только этот тип команды использует собственный status из catalog как исходный статус
переключателя. Обычные manual/Rule Engine snapshots не меняют семантику. Сопоставляются
точные account/AD/AdSet/Campaign IDs, parent_id/campaign_id, READ/WRITE revisions и routing.
Все три ответа должны быть полными, без дублей, с одним timestamp источника. Источник
должен быть не старше 900 секунд и не из будущего; время HTTP-ответа его не продлевает.

Подготовка выполняет существующую проверку WRITE credential GET /me через Credential
Manager и три документированных GET каталога campaigns/adsets/ads. Используется
отдельный encrypted WRITE credential с campaigns:read/entities:write; READ key никогда
не используется для WRITE. Все physical attempts резервируют общую квоту MetricFlow.
Нет retry или guessed endpoints/fields.

Перед будущим рекламным POST, после durable claim, приватный factory повторяет три
GET тем же привязанным WRITE credential и проверяет родителей/собственный статус.
Счётчик validation_gets сохраняется в БД и ограничен тремя. Успешная проверка привязана
к claim, действительна <=30 секунд и обязательна перед расходованием wire budget.

Лимит одной попытки исполнения: 3 GET + 1 POST; один POST на permit, concurrency 1,
window <=600 s, существующий общий timeout POST-stage <=30 s. При недостатке квоты,
429, изменении статусов/иерархии, rotation/revocation, cache age или ошибке READ — POST
не отправляется. Попытка не повторяется автоматически, даже если до POST не дошла.

## Чего этот тест не доказывает

Принятие экспериментального допуска не подтверждает WRITE namespace. При неверной
интерпретации ID запрос может быть отклонён или интерпретирован провайдером иначе,
чем ожидается. Этот риск нужно отдельно принять в окончательном согласовании.

READ MetricFlow является кэшированным состоянием, не атомарной блокировкой Meta.
Нельзя гарантировать, что внешний оператор или расписание не изменят родителей после
снимка. Перед запуском нужна ручная сверка Ads Manager; родителей не следует включать
в окно пилота. Первый PAUSE уменьшает активность, но это не отменяет неопределённость ID.
ACK не доказывает доставку/own status. После первой попытки необходимы readback и ручная
сверка; UNKNOWN останавливает дальнейшие действия. Возврат ENABLE не автоматический,
требует отдельной приёмки и отдельного разрешения после результата первого теста.
Ручной readback по-прежнему не создаёт API authority или ownership для Rule Engine.

## Проверки разработки

- Existing pilot/private API/contract regressions: 103 PASS.
- Experimental unit + private ASGI/session/admin/CSRF: 52 PASS.
- Restored PostgreSQL restricted-role harness: PASS, включая INSERT локального DRAFT,
  3 preparation GET, 3 pre-POST GET и один mock POST. 6 лишних прав по-прежнему отклонены;
  тестовые role/schema/data rolled back.
- Restored PostgreSQL experimental race: PASS, 8 процессов, один claim и один mock POST.
  Restart — NO_RESEND; crash exit 17 — UNKNOWN_NO_RESEND. Факты не изменены, отдельная
  синтетическая schema удалена в finally. Все HTTP операции — MockTransport.
- Новые компоненты Ruff/check/format PASS; legacy engine имеет 5 прежних findings,
  manual.py — 0, новых нет. Secret scan PASS. Frontend typecheck PASS.

Для локального DRAFT CM получает INSERT на action_requests через существующий
идемпотентный provisioner. Нет новых прав на рекламные факты/экономику/роли, DELETE
или DDL. Уже существующие UPDATE(id) для row locks сохранены; это реальное право на
ID-столбец, не специальный lock-only privilege. Миграция схемы не требуется.

## Фактический результат подготовки

20.10.2026: PREPARED_NO_POST_AUTHORIZATION. Request UUID:
776a0dd3-6130-4785-ba41-b6d3596afd10, revision 1, PostgreSQL status DRAFT.
controlled authorization отсутствует; LIVE permits=0, accepted provider evidence=0,
ActionExecution=0. Это не готовность подтверждённого production WRITE-контракта.

Кабинет Valya Sergeeva, act_1047962734516123; AD #71012012_EGR_Creo 03,
120247730105960571; группа 3 / 120247730105950571; кампания
24.09 - 218-227.1-3 - Adenofrin - ES -ED - 123 / 120247730079240571.
Свежие каталоги подтвердили PAUSED/PAUSED у обоих родителей и
ACTIVE/ADSET_PAUSED у AD. Source timestamp 20.10.2026 19:08:35 UTC.
Baseline истекает 19:23:35 UTC / 22:23:35 МСК; DRAFT — 19:29:50 UTC.
Истечение требует повторной свежей подготовки/проверки, не автоматического запуска.

Отдельный WRITE credential revision 1 проверен GET /me через существующий CM:
SCOPES_VERIFIED, active_paid. Подготовка использовала всего 4 authenticated GET
(/me + campaigns/adsets/ads), без retry. READ credential revision 1 не заменялся;
READ healthy, last_success_at 19:10:03 UTC. Права на объект — USER_ATTESTED,
не независимо подтверждённая роль Meta. Namespace остаётся UNVERIFIED.

Обновлены только backend и Credential Manager образом
metric-control-center-experimental-pilot-20261020:local,
image SHA256 df734db7d2af1b2aad46525e5e83964ed8c87376dcb5683218a76e56b635d43a.
Хэши 12 модулей совпали с исходниками в обоих контейнерах. До подготовки
14 защищённых таблиц совпали полностью; после — 10 без изменений,
action_requests +1, action_logs +2, credential audit +1 и обновление результата
проверки ключа, без изменения credential revision. .env SHA не изменён.
Worker/scheduler/frontend/PostgreSQL/Redis не пересоздавались. Миграции не применялись.
Meta disabled/disconnected revision 4. WRITE gate WRITE_DISABLED,
capability live_status BLOCKED. Четыре защитных флага сохранены.

Дополнительные проверки: 258 PASS + 14 subtests PASS (manual/multilevel/parent refresh,
controlled execution/deadline/typed adapter). Всего отдельные наборы: 103 + 52 + 258
PASS; результаты не следует трактовать как число уникальных тестовых функций.
Playwright Edge smoke: 3 PASS (login, auth redirect, отсутствие page errors),
без авторизации и provider requests. Это не новый полный authenticated UI E2E.
Frontend typecheck PASS; backend/CM image build PASS; security scan и diff check PASS.
Локальные sanitized evidence: .tools/experimental-pilot-20261020/ (ignored).

## Следующий ручной этап и отдельное разрешение

1. В Ads Manager сверить точные три ID: родители выключены, AD включено.
   Не включать родителей в окно теста; не менять статусы во время проверки.
2. Отдельно принять неопределённость namespace и разрешить ровно один
   экспериментальный PAUSE_AD для AD 120247730105960571. Выбор подготовки этого
   разрешения не даёт. Для истёкшей карточки сначала подготовить свежую.
3. После разрешения пройти существующие private authorize/execute server-side gates
   и отдельную процедуру конфигурации пилота. Текущие false/true safety flags
   исключают исполнение; их нельзя обходить или считать разрешёнными автоматически.
   Контракт будущего запроса: POST /api/v1/entities/120247730105960571/pause,
   JSON {"level":"ad"}, без async; перед ним максимум 3 GET. Повторять POST нельзя.
4. После ACK/error/timeout остановиться и проверить фактический статус; UNKNOWN
   разбирать вручную. ENABLE и тесты Campaign/AdSet — отдельный последующий этап.

FINAL STATUS: EXPERIMENTAL PREPARATION READY; LIVE NOT AUTHORIZED.
ADVERTISING WRITE REQUESTS: 0.
