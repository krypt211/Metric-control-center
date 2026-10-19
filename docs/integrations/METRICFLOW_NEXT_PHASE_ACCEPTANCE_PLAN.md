# MetricFlow: следующий этап и условия приёмки LIVE

Обновлено 18.10.2026, Europe/Moscow. Phase 4B: PARTIAL. LIVE WRITE: BLOCKED.
Документ не разрешает рекламные операции.

## Принятый локальный результат

Кабинет Valya Sergeeva / act_1047962734516123.
AD #70495691_EGR_Creo 06 / 120247747556780571.
Профиль MX AD v1; правило TEST — Creo 06 — PAUSE, revision 4.
[Измеренное evidence](../rules/CREO06_DRY_RUN_CHECKPOINT_2026-10-17.md):

- Ручной PAUSE прошёл только локальную SIMULATED-проверку.
- Устаревший период дал UNKNOWN / DATA_STALE.
- Свежие данные: CPL 2.84781395 < maximum 7.11864407 -> FALSE / KEEP.
- Временный технический порог 2 USD -> TRUE / REVIEW, ATTRIBUTION_UNVERIFIED.
- Максимальный ориентир профиля восстановлен; расписание выключено.
- Положительное actionable WOULD_PAUSE, LIVE PAUSE/ENABLE и автодействия не приняты.

## Документации достаточно для продолжения разработки

Публичный OpenAPI 1.0.0 получен 17.10.2026 без credentials:
https://metricflowit.click/api/v1/openapi.json?lang=en
SHA256 f52bc8ca0691fa0e2f2b5a5de06aa74a897546b88705ee16851859138a2f3327.
GET /jobs/{job_id}, его response model, PAUSE/ENABLE body и READ operations
документированы. Ответ поддержки на весь список не является условием
реализации подтверждённых частей. Неизвестные части остаются заблокированными.
Специфичный OpenAPI задаёт entities:write; старая общая страница с campaigns:write
не является основанием требовать новый ключ или менять текущую scope policy.

| Часть | Подтверждено | Неподтверждено |
| --- | --- | --- |
| READ insights | GET, from/to, level, ad_account_ids, currency, cursor | Attribution исторической строки |
| Metadata | data_updated_at описан как last successful sync timestamp | Per-AD freshness и consistency deadline |
| PAUSE/ENABLE | POST, body level=ad, entities:write | WRITE ID namespace и asset permission |
| Sync ACK | 200 EntityActionResponse | Применение изменения и полный error contract |
| Async ACK | description 202 + job_id | Formal response schema 202 отсутствует |
| Jobs | GET, статусы, EntityActionJobResponse | Job visibility, retention, polling guarantees |
| Retry | Локально один POST attempt, UNKNOWN при неопределённости | Provider idempotency/lookup потерянного job_id |
| Readback | status/effective_status описаны | Точная configured/effective семантика, кеш, deadline |

## Раздельные ограничения приложения

ATTRIBUTION_UNVERIFIED — локальная политика Rule Engine. Она блокирует
положительное экономическое решение. Это не ошибка API и не универсальное
дополнительное условие ручного preflight. Необходимость/область этой политики
проверяются отдельно; в текущем этапе защитная проверка не ослабляется.

Рабочий one-operation LIVE permit/dispatcher ещё не завершён. Существующие
MOCK_ONLY permits и новый observer принимают только изолированные fixtures;
они не могут быть повышены до LIVE изменением флага.

## Порядок работ

1. Реализовать документированный typed GET job и ограниченное наблюдение в
   существующем ActionEngine. Один шаг делает максимум один GET; durable attempts,
   next_poll_at и deadline предотвращают reset после restart. Сначала mocks и
   изолированная PostgreSQL. См. [отчёт observer](METRICFLOW_JOB_OBSERVER_ACCEPTANCE.md).
2. Подготовить авторитетный READ readback. Job success означает необходимость
   readback; success сам по себе не подтверждает configured/effective status
   и не создаёт MCC pause ownership. Неизвестная семантика остаётся блокером.
3. Реализовать production разрешение на один AD/операцию только после принятия
   обязательного identity/permission/ACK/timeout/readback контракта. Никаких
   READ-key fallback, автоматического resend и общего включения очереди действий.
4. Принять точный путь на mocks и отдельной PostgreSQL: duplicate/race, wrong ID,
   отзыв прав, смена ключа, late ACK, timeout, partial/expired, crash/restart,
   stale readback. Неизвестный результат остаётся UNKNOWN до reconciliation.
5. Разобрать attribution policy и документированную семантику исторических
   метрик. Не присваивать вручную 7d_click/1d_view, truthy dict или checkbox обхода.
6. Решить отдельное несоответствие исторической свежести: last7 работает раз
   в сутки в 04:07, source TTL=1800 секунд, DRY_RUN interval=1800 секунд.
   Нужны расчёт pagination/квоты и использование существующего ingestion,
   lease и dedup. Лимит 800 и требования свежести не повышать и не ослаблять.
7. Перед пилотом проверить fresh READ, paid access/scopes, asset permissions и
   exact AD/account binding документированным non-mutating способом.
   Исторический cached check не является свежим подтверждением доступа.
8. Подготовить карточку одного PAUSE: AD/account, credential revision, исходное
   состояние, один POST attempt, окно, GET budget, stop conditions/readback.
   Пользователь отдельно разрешает именно эту операцию после готовности кода.
9. ENABLE restoration — другая операция с отдельным разрешением и свежей
   проверкой. При UNKNOWN/timeout/403/429/mismatch остановка без resend.
   После принятого ручного пилота отдельно проектируется LIVE одного правила.

## Точечные уточнения провайдеру

[Готовый текст](METRICFLOW_PROVIDER_CLARIFICATION_REQUEST.md) подготовлен,
агент никому его не отправлял. Использовать для действительно оставшихся
вопросов; общей ссылки на документацию достаточно для описанных в ней операций.
Точное письменное подтверждение провайдера может закрыть пробел без новой
страницы. Если возможность не поддерживается, фиксировать UNSUPPORTED и
проектировать безопасное поведение. Не принимать любой 2xx за доказанный успех.

## Границы проверки и сохранность

Исторический аудит 17.10 в 22:39 МСК: 62 mock-теста PASS, 21 deselected,
PostgreSQL 0016_smart_control, READ healthy revision 1, Meta disconnected revision 4,
квота 117/800 без cooldown. Эти значения не объявляются текущими 18 октября.
Новые результаты observer записываются в отдельный отчёт.

ACTIONS_ENABLED=false, LOCAL_READ_ONLY=true, AI_ENABLED=false,
AI_AUTOPILOT_ALLOWED=false сохраняются. Новые реальные рекламные WRITE и Meta
LIVE не разрешены. Миграции, бизнес-профиль, правила и действующие ключи
изменением документации не затрагиваются.
## Уточнение этапа READ readback — 18.10.2026

[Локальный диагностический путь](METRICFLOW_READBACK_ACCEPTANCE.md) реализован:
POST -> correlated job success -> максимум 3 READ insights pages, без retries.
Это закрывает документированную часть пункта 2 и соответствующую mock/PostgreSQL
приёмку пункта 4. Авторитетность READ, object permission и namespace WRITE ID
не подменены предположениями. LIVE permit/dispatcher по пункту 3 по-прежнему
ожидают обязательного evidence. Уже пройденные ручные DRY_RUN повторять не требуется.
## Ручная ветка без письма провайдеру — 18.10.2026

[Карточка сверки](METRICFLOW_MANUAL_PILOT_REVIEW.md) готова и доступна в локальном UI.
Письмо не требуется для следующего шага: пользователь сверяет identity, собственный
статус AD и родителей в MetricFlow/Ads Manager, ничего не изменяя. Текущий READ
сообщает CAMPAIGN_PAUSED, поэтому прежняя предпосылка ACTIVE больше не принимается.
Эта ручная сверка не подтверждает WRITE namespace/asset permission автоматически.
Production permit/dispatcher остаются BLOCKED до принятия обязательных сведений.

## Checkpoint 18.10.2026 — ручная сверка принята, WRITE scope обновлён

Пользователь в 17:28 подтвердил AD включён, группа включена, кампания выключена,
доставка неактивна; право управления в MetricFlow не видно. В 17:30:26 МСК
Credential Manager проверил сохранённый WRITE credential одним GET /me:
SCOPES_VERIFIED, entities:write, active_paid; READ healthy, revisions 1/1 сохранены.
Квота 237 -> 238/800. Это снимает блокер устаревшего scope check на момент проверки,
но не подтверждает object permissions/WRITE ID/authoritative readback и не разрешает
LIVE. Подробности: [checkpoint](METRICFLOW_PILOT_MANUAL_CHECKPOINT_2026-10-18.md).

## Checkpoint 18.10.2026 — три уровня локального управления

[Локальная подготовка кампаний, групп и объявлений](MULTILEVEL_STATUS_LOCAL_ACCEPTANCE.md)
установлена в backend/frontend и проверена без рекламного WRITE. Для кампании
и группы доступны отдельный уровень каталога, стандартные чекбоксы и тот же
DRAFT/preflight/confirm/SIMULATED путь. AD-поведение и прежние черновики совместимы.
Следующая ручная проверка — только локальная: campaign 120247747556760571,
затем adset 120247747556830571 в Valya Sergeeva. При stale/unknown статусе
нужно передать блокер, а не обходить freshness gate.

READ healthy подтверждён локально на 19:14 UTC. Исторический WRITE scope check
17:30:26 МСК не объявляется текущим. Namespace WRITE ID, object permissions,
ACK/UNKNOWN/authoritative readback и одноразовый production dispatcher остаются
обязательными условиями перед отдельным разрешением на каждый LIVE запуск.
Расширение локальных уровней не закрывает эти блокеры и не активирует правила.

## Checkpoint 19.10.2026 — POST deadline и late ACK

[Актуальный разбор готовности](METRICFLOW_CONTROLLED_WRITE_READINESS_2026-10-19.md):
169 backend tests PASS; PostgreSQL race/crash и deadline cases PASS.
Исправлены таймаут однократного POST и повторное открытие UNKNOWN поздним ACK.
Backend/READ-worker обновлены с прежним закрытым hard gate и четырьмя флагами.
Ручной ENABLE_CAMPAIGN / SIMULATED уже принят; повторять его не требуется.

Перед production dispatcher нужны три внешних факта: WRITE ID binding,
управляющее право на конкретный объект и авторитетный configured/effective readback.
Production dispatcher пока не реализован, LIVE остаётся BLOCKED.
Formal 202 обязателен только для async: возможный первый synchronous-200 пилот
не требует этой схемы. Отсутствие provider idempotency не отменяет принятую
локальную no-resend стратегию и не является основанием послать второй POST.
