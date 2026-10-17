# MetricFlow READ readback — acceptance

Дата: 18.10.2026, Europe/Moscow. Phase 4B: PARTIAL; LIVE WRITE: BLOCKED.
Результаты относятся к текущему этапу, не являются разрешением рекламных операций.

## Что завершено

В существующем ActionEngine добавлен завершающий диагностический READ после
коррелированного успешного job. Это только MOCK_ONLY на изолированных fixtures.
Рабочего LIVE dispatcher, HTTP route или нового scheduler не добавлено.

Проверка использует отдельный явно переданный synthetic READ credential, существующий
GET-only MetricFlowConnector и документированный GET /api/v1/insights:
from=to (день команды в timezone кабинета), level=ad,
ad_account_ids=точный act_ID, fields=spend, currency=native, limit=100,
затем документированный cursor. Фильтр ad_id и cache-bypass не выдуманы.

- Не более 3 страниц / 300 строк, read_retries=0; каждый GET проходит локальные
  quota, permission, identity, credential revision, deadline и claim guards.
- READ credential не берётся из WRITE vault; реальных ключей этот этап не открывает.
  Параметр synthetic read_key не является production credential resolver.
- READ revision закреплена по локальному snapshot подключения. Это не доказательство
  соответствия произвольного ключа подключению и не LIVE проверка прав.
- Проверяются кабинет, AD, adset, campaign, день, типы полей, уникальность AD,
  полнота pagination, цикл cursor и неизменность source timestamp между страницами.
- Учитываются missing/stale/future sync timestamp, неизвестный status,
  effective status родителя, отсутствие AD и исчерпание бюджета страниц.
- Claim сохраняется до HTTP; restart не сбрасывает бюджет и не повторяет скан.
  После аварии незавершённый READ закрывается UNKNOWN по исходному deadline.
- Timeout всего скана не более 30 секунд и не позже исходного permit deadline.
  Это локальный лимит, а не гарантия провайдера. Новой задержки/scheduler нет.
- 401/403/429/timeout/invalid response останавливают скан; 429 сохраняет существующий
  консервативный cooldown. Лимиты не повышаются, POST не повторяется.
- Факты EntityCurrentState и MCC pause ownership не меняются. Даже совпадение статусов
  даёт REPORTED_STATUS_MATCH_NEEDS_AUTHORITY, authoritative=false;
  ActionRequest остаётся UNKNOWN, не SUCCEEDED. Существующий verify_pending
  не превращает mock evidence в LIVE verified event.

## Официальный контракт и его границы

[Официальный OpenAPI](https://metricflowit.click/api/v1/openapi.json?lang=en)
получен без credentials; 334703 bytes, API 1.0.0, SHA256:
f52bc8ca0691fa0e2f2b5a5de06aa74a897546b88705ee16851859138a2f3327.
Неизменённый READ operation и 6 referenced schemas сохранены отдельно:
[READ evidence](METRICFLOW_READBACK_OPENAPI_2026-10-18.json).

Документированы status/effective_status, account filter, date range, cursor и
ApiMeta.data_updated_at = last successful sync timestamp. Только HTTP 200
принимается для insights; неожиданный 2xx не считается валидным READ результатом.
Изменение не добавляет WRITE scope и не подменяет READ ключ.

OpenAPI НЕ гарантирует configured_status, обновление конкретного AD после job,
cache invalidation, monotonic per-AD version или максимальный readback lag.
Список распознаваемых status labels в коде — консервативная локальная обработка,
не объявление полного provider enum. Совпадение PAUSED/PAUSED или ACTIVE/ACTIVE
является диагностикой возвращённых полей, не доказательством рекламного применения.

## Проверки

Фактические результаты и timestamped runtime evidence приведены ниже.
PostgreSQL предварительно: 8 процессов -> 1 claim / 1 physical mock READ;
отдельный abrupt exit 17 -> UNKNOWN, повторного READ нет, verified events = 0.
Проверены новые private schemas восстановленной mcc_integrations_* БД;
рабочая БД для rehearsal отвергается до SQL.

PostgreSQL обнаружил длину outcome > String(32), незаметную SQLite.
Исправлено коротким mock_readback_needs_authority, без миграций/ослабления schema.
Невалидные тестовые private schemas не удалялись; production данные не затронуты.

Browser fixture исправлен отдельно: mock карточка берётся из полной сохранённой
строки даже при отсутствии ACTIVE в области правила. Никакие реальные статусы
или решения правил не подменены. Отрицательные server-side проверки сохранены.

## Точные оставшиеся блокеры LIVE

1. Явное подтверждение namespace WRITE entity_id и связи с READ ad_id.
2. Права текущего WRITE подключения на выбранный AD и кабинет. Scope entities:write
   не доказывает object permission; cached проверка ключа не является свежей.
3. Точный HTTP 202 ACK contract и согласованная семантика job partial/failed,
   ошибок и потерянного job_id. Без этого UNKNOWN не превращается в безопасный retry.
4. Authoritative readback: configured/effective semantics, freshness конкретного AD,
   cache lag, срок/способ независимой проверки результата.
5. Production разрешение на одну операцию/AD и dispatcher остаются не реализованы
   до принятия обязательного контракта. MOCK_ONLY permit нельзя повысить до LIVE.
6. Для LIVE правила отдельно остаются attribution policy и свежесть исторического
   окна; принятый TRUE/REVIEW не равен actionable WOULD_PAUSE. Защиты не ослаблены.

Provider idempotency/lookup не подтверждены: реализация работает без автоматического
resend; при потере ответа нужен отдельный reconciliation, а не повтор POST.
Недокументированная idempotency не требуется для локального скана и не выдумывается.

## Что требует ручного участия дальше

Повторять уже принятые клики DRY_RUN не нужно. Следующий внешний шаг — получить
точечные подтверждения MetricFlow по пунктам 1–4; готовый
[текст вопросов](METRICFLOW_PROVIDER_CLARIFICATION_REQUEST.md) никому не отправлялся.
Одной общей ссылки на docs достаточно для документированных операций; вопросы
остаются только к перечисленным отсутствующим гарантиям.

После появления evidence агент проверяет его, завершает production permit/dispatcher
и автоматические проверки, затем готовит карточку одного PAUSE для:
act_1047962734516123 / AD 120247747556780571 (#70495691_EGR_Creo 06).
Только после отдельного разрешения возможен один WRITE attempt с наблюдением job
и независимой ручной сверкой статусов в интерфейсе рекламной системы.
ENABLE — другая операция с отдельным разрешением и свежим исходным состоянием.
При timeout/UNKNOWN/403/429/mismatch остановка, без повторной команды.

Сейчас эти рекламные ручные тесты запускать рано: смена флагов не закрывает блокеры.

## Безопасность

ACTIONS_ENABLED=false; LOCAL_READ_ONLY=true; AI_ENABLED=false;
AI_AUTOPILOT_ALLOWED=false. Реальные advertising WRITE этого этапа: 0.
Meta LIVE не запускался. Рабочие READ/WRITE credentials не изменены и не раскрыты.
Профиль MX AD и правило TEST — Creo 06 — PAUSE не редактировались.
Миграции/production deployment не выполнялись, рабочие volumes не удалялись.

FINAL STATUS: MOCK READBACK READY; PHASE 4B PARTIAL; LIVE WRITE BLOCKED.
### Измеренные результаты этапа

- Targeted POST/job/readback/contract suite: 157 PASS.
- Финальный READ/readback/connector/sync regression после ужесточения HTTP 200:
  69 PASS + 25 subtests PASS (49.52 s). Наборы пересекаются, суммы не складываются.
- Полная backend-регрессия: 787 PASS, 1 SKIP, 78 subtests PASS (925.99 s). Пропущен отдельный auth PostgreSQL test: TEST_POSTGRES_URL не настроен. Завершающие 5 новых readback guard tests включены в финальный READ-набор из 69 PASS.
- Frontend: TypeScript PASS; unit 36/36 PASS; production build PASS.
- Playwright: 24 уникальных сценария приняты. В исходном общем запуске 23/24 PASS,
  затем после исправления fixture повторён весь manual-control набор: 5/5 PASS
  (60.34 s). Остальные 19 сценариев не менялись и не повторялись без необходимости.
- Новые Python файлы: Ruff check PASS, format --check PASS (4 файла).
  Existing engine/reader: baseline 5/3 findings соответственно, новых 0.
- Staged diff --check и поиск приватных ключей/реальных token patterns: PASS.
- Docker backend build PASS; финальный source-layer image
  metric-control-center-readback-final:local проверен с network=none/read-only:
  hard gate ДО БД и HTTP, 0 attempts.
- Финальная PostgreSQL приёмка выполнена из этого image без services source mounts.
  БД mcc_integrations_audit_20261014_165636, revision 0016_smart_control.
  Race schema: controlled_rehearsal_readback_e806161a94514c85b9dadbd912e1096e.
  Crash schema: controlled_rehearsal_readback_f7513d34afd94432af62ad82666d875a.
  8 процессов -> 1 physical mock READ; abrupt exit 17 -> UNKNOWN без resend.
  В каждом сценарии один mock POST и один mock job GET; LIVE requests = 0.
- Playwright работал только на отдельном acceptance stack и восстановленной
  mcc_integrations_controlled_20261016_211626; обычная sync там выключена.
  После проверки его сервисы остановлены; volumes/БД не удалены.

Локальный рабочий runtime проверен READ ONLY в 2026-10-17 21:35:54 UTC
(18.10.2026 00:35:54 МСК): PostgreSQL 0016_smart_control; MetricFlow READ
healthy/enabled revision 1, last success 21:30:03 UTC; Meta disconnected/disabled
revision 4. Квота UTC 17.10: 153/800, cooldown отсутствовал.
ActionExecution во всей рабочей БД: 0; выбранный AD ACTIVE, observed 21:30 UTC.
Manual request cb3370e7-036d-43ad-b243-190b6d8de6d4: SIMULATED revision 7;
правило 9cf962b0-a2ed-4b87-9e74-7695aedb8efd: revision 4,
DRY_RUN, enabled=false, next_evaluation_at=null. Это timestamped evidence,
а не гарантия неизменности внешней рекламы после проверки.