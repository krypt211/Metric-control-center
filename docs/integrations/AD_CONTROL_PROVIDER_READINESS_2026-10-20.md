# AD CONTROL PROVIDER READINESS — 20.10.2026

METRICFLOW ADVERTISING API: DOCUMENTED AVAILABLE.
CURRENT WRITE KEY: BUSINESS / ACTIVE_PAID / ENTITIES:WRITE CONFIRMED BY GET.
CONTROLLED WRITE EXECUTOR: DEPLOYED, GATES CLOSED.
LIVE ADVERTISING TEST: BLOCKED / NOT EXECUTED.

## Решение по провайдерам

Официальный MetricFlow Public API документирует PAUSE/ENABLE кампаний, групп и объявлений,
а также budget/bid endpoints. Поэтому условие «если API не умеет управлять рекламой,
переключаться на Meta и удалять MetricFlow» сейчас не выполнено. MetricFlow сохранён;
рабочий READ, история, сопоставления и данные не удалялись.

Наличие платных правил в MetricFlow не означает запрет команд нашего Action Engine.
Наш Rule Engine вычисляет решения локально. Для команд требуется entities:write;
платные правила, созданные в MetricFlow, для этого локального механизма не используются.
Тариф/скоуп и право на конкретный рекламный объект проверяются отдельно.

## Измерено: текущая подписка WRITE-ключа

20.10.2026 07:59:28 UTC / 10:59:28 МСК выполнены два документированных GET:
GET /api/v1/me и GET /api/v1/usage. Использованы существующий приватный Credential Manager,
его stored_token/vault, GET-only MetricFlowConnector и общий ProviderManager quota.
Новый ключ не создавался; plaintext не покидал процесс CM и не записывался в отчёты.
Нет retries, POST, смены ключей, обновления checked_at или записей принятия LIVE-контракта.

| Показатель | Измеренное значение |
| --- | --- |
| Plan WRITE-ключа | business |
| Access state | active_paid |
| entities:write | Есть в /me.api_key.scopes |
| rules:write | Есть в /me.api_key.scopes |
| Слоты правил MetricFlow | used=0, limit=200, remaining=200 |
| Provider daily quota на момент /usage | 2 / 20000, remaining=19998 |
| READ / WRITE credential revision | 1 / 1, не менялись |
| Authenticated provider GET attempts | 2 |
| Advertising WRITE | 0 |

Не обнаружено признака отсутствующей подписки или entities:write scope у этого ключа.
Это не является доказательством успешного POST, разрешения на конкретный AD или
полной семантики результата. Метаданные прежнего сохранённого credential check не
перезаписаны; перед реальным пилотом потребуется свежий штатный check в CM.
Локальный лимит 800 запросов/UTC-день не увеличен до provider limit 20000.

## Что доделано в реализации

1. ActionCapabilityRegistry отдельно сообщает документированные статусные операции,
   источник контракта, неподтверждённый ID binding и отсутствие LIVE verification.
   Старые write_permission=false, operations=UNVERIFIED и live_status=BLOCKED сохранены.
2. USER_ATTESTED с management_confirmed=true распознаётся как отдельный источник
   подтверждения управления. Он не выдаётся за MANUAL_META_ACCESS_REVIEW или конкретную
   Meta роль FULL_CONTROL. Чужой namespace, отсутствие источника ID, устаревшие/неверные
   привязки и клиентские разрешающие поля по-прежнему не принимаются.
3. Исправлен deployment gap: приватная DB-роль CM раньше не могла читать/изменять
   ActionRequest/Execution/Log и брать actor/entity row locks. Provisioner теперь
   идемпотентно выдаёт только необходимые grants. Нет DELETE/DDL, изменений ролей
   пользователей, статусов/экономики/метрик или чтения provider_credentials.
4. Для PostgreSQL FOR UPDATE нужны UPDATE-права хотя бы на один столбец. Для users/entities
   выданы только UPDATE(id), без UPDATE(role/name/password/status). Это реальное право
   на ID-столбец, а не особый «lock-only» privilege; используются существующие блокировки.
5. Синтетический полный authorize -> один mock POST -> restart/no resend -> ручная запись
   результата проверен под NOLOGIN/NOSUPERUSER ролью в restored DB. Тестовые роль, схема и
   все строки откатились одной внешней транзакцией. Ручная сверка не создаёт API authority
   или pause ownership для автоматического включения правилом.

## Развёртывание и проверка сохранности

Собран image metric-control-center-closed-pilot-20261020:local; обновлены только backend
и credential-manager. Предыдущие image IDs и rollback override сохранены локально.
Bootstrap использовал явный python /provision.py вместо команды миграции: только GRANT,
без alembic upgrade и без замены исходного migrate container. PostgreSQL остаётся
0016_smart_control, migrate exited 0. Рабочие volumes не удалялись и не перемещались.

- Хеши/количества строк всех 14 защищённых таблиц совпали до/после deploy.
- .env SHA совпадает. Backend и CM runtime подтверждают ACTIONS_ENABLED=false,
  LOCAL_READ_ONLY=true, AI_ENABLED=false, AI_AUTOPILOT_ALLOWED=false.
- Шесть реально загруженных модулей совпадают по SHA с проверенными исходниками.
- Три private pilot routes зарегистрированы; frontend/BFF WRITE proxy не добавлен.
- Worker, scheduler, frontend, PostgreSQL и Redis не пересоздавались этим deploy.
- MetricFlow READ healthy; последний зафиксированный успех 20.10.2026 08:00:05 UTC.
- ActionExecution=0; LIVE_SINGLE_OPERATION permits=0; accepted external proof records=0.
- Локальная квота на финальном снимке 10/800; cooldown отсутствует. Штатный READ может
  далее менять счётчик. Два диагностических GET входят в общую квоту.

Автоматическое approval review временно не выполнялось из-за исчерпания workspace credits.
Неисполненная операция не обходилась; после продолжения пользователя штатная проверка
разрешила действия, и закрытое развёртывание завершилось. Docker в момент продолжения
был остановлен; запущен существующий Desktop с неизменной конфигурацией проекта.

## Прямой Meta API как запасной путь

Официальный facebook-python-business-sdk 26.0.2 содержит api_update(status) и GET поля
id/account_id/status/configured_status/effective_status у Ad, AdSet и Campaign.
Это подтверждает соответствующие SDK definitions, не работу конкретного подключения.
Официальные источники:

- https://github.com/facebook/facebook-python-business-sdk/tree/26.0.2/facebook_business/adobjects
- https://raw.githubusercontent.com/facebook/facebook-python-business-sdk/26.0.2/facebook_business/apiconfig.py

Текущее локальное состояние Meta: disabled/disconnected, revision 4,
provider credential records=0. Наш MetaMarketingProvider реализован как GET_ONLY;
готового LIVE WRITE adapter/credential handoff нет. Поэтому немедленная замена MetricFlow
не обеспечит готовое управление или поток статистики. Для миграции понадобятся отдельное
Meta-подключение, проверка app/token/asset permissions, контролируемый READ, WRITE adapter
и приёмка нового пути. MetricFlow-ключ не является токеном Meta.
Meta LIVE не включался; запросов к Graph API в этом этапе нет.

## Проверки этого этапа

- Backend: 101 PASS (pilot, private ASGI/auth/CSRF, MetricFlow typed write contract).
- Credential/manual regressions: 17 PASS; READ/WRITE isolation, migration guard, revisions,
  локальные permissions. Наборы запускались отдельно, их результаты сохранены локально.
- PostgreSQL restricted-role harness: PASS; 6 запрещённых операций отклонены,
  один mock attempt, без resend, данные фактов неизменны, тестовые role/schema rolled back.
- Ruff check/format изменённых Python-компонентов: PASS.
- Frontend npm run typecheck: PASS; frontend исходники не менялись.
- Playwright: PASS, 3 anonymous smoke checks: login rendered, manual-control требует входа,
  нет page errors. Bundled Chromium отсутствовал; использован установленный Edge через
  документированный channel=msedge, headless temporary context. Это не полная UI-приёмка
  реального пилота; формы не отправлялись, внешняя сеть блокировалась.

Локальные санитизированные evidence: ignored .tools/provider-decision-20261020/
(subscription-current.json, credential-role.txt, credential-regression.txt, deployment.json,
runtime-final.json, browser-smoke.json, build/provision/deploy logs, SDK SHA metadata).

## Оставшиеся условия первого рекламного теста

1. Подтверждение namespace WRITE entity_id: для level=ad это Facebook Ad ID из READ
   или иной ID? Текущий OpenAPI задаёт string без уточнения. Это остаётся внешним
   контрактным блокером; [точный вопрос](METRICFLOW_WRITE_ID_DECISION_2026-10-20.md) подготовлен,
   но никому не отправлен. Наличие Business/entities:write не доказывает ID namespace.
2. После подтверждения ID нужна финальная серверная приёмка именно этого контракта.
   ActionSafetyGate.require_verified_contract пока безусловно закрыт; одной смены env
   недостаточно. Подтверждение пользователя о правах не снимает этот gate.
3. Перед карточкой нужны свежие own/effective status, иерархия и штатный WRITE check.
   Историческая симуляция не переводится в LIVE; сведения не продлеваются искусственно.
4. Только затем — отдельное явное разрешение пользователя на один PAUSE_AD для
   act_1047962734516123 / AD 120247747556780571. Первый тест не включает кампанию,
   не меняет бюджеты, не запускает автоматические правила и не повторяет неизвестный POST.

FINAL: METRICFLOW RETAINED; API DOCUMENTED; TARIFF/SCOPE CONFIRMED;
CONTROLLED EXECUTOR DEPLOYED CLOSED; FIRST LIVE WRITE BLOCKED.
ADVERTISING WRITE REQUESTS: 0.
