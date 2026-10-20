# Scoped pilot contract acceptance — 20.10.2026

Статус разработки: READY LOCAL/MOCK. LIVE остаётся BLOCKED.
Это завершение внутренней серверной приёмки для одного ручного AD status POST;
не подтверждение работоспособности рекламного WRITE на стороне MetricFlow.

## Что изменено

- Вместо безусловного отказа во всех случаях ActionSafetyGate принимает только
  приватный PilotContract, связанный с одним workspace/admin/request/AD/operation,
  ревизией и ciphertext digest отдельного WRITE credential, конкретным audit evidence
  и неизменным deadline. Без такого объекта контракт по-прежнему отклоняется.
- Доказательство namespace не принимается из authorize/execute body. Оно должно быть
  ранее принято доверенным оператором в существующем pilot_external_evidence_accepted.
  Дополнительный contract_review строго задаёт provider=metricflow, status-sync-v1,
  PAUSE_AD или ENABLE_AD, namespace PROVIDER_AD_ID, provider-authored источник,
  SHA256 источника и reviewed_by. USER_ATTESTED допустим для отдельно подтверждённых
  прав управления, но не для подтверждения API namespace.
- В этом этапе endpoint/CLI для записи такого evidence не добавлялся, production
  evidence не создавался. Типизированная запись фиксирует результат операторского
  review; приложение не определяет по хешу, действительно ли текст источника
  подтверждает namespace. Это обязанность доверенного review, не автоматическая гарантия.
- На каждой границе проверяются актуальные actor/workspace, accepted/revoked evidence,
  полный SHA его содержимого, свежесть и revision/digest ключа. Ротация, отзыв, подмена
  proof/pin/authorization или expiry останавливают исполнение до HTTP.
- После явного authorization контракт сохраняется в существующем controlled permit.
  Глобальный capability registry остаётся BLOCKED/UNVERIFIED, legacy/Rule Engine WRITE
  не получает общего разрешения. Правила автоматически не запускают пилот.
- Перед сетевым вызовом транспорт допускает ровно POST entities/{выбранный_AD}/pause
  или /enable, строго body {"level":"ad"}, без async/query и без других полей.
  Campaign/adset/budget, job GET и другой AD/operation отклоняются.
- Непосредственно перед HTTP под существующими workspace/user/request locks атомарно
  сохраняется wire_spent=true. Требуются durable claim, http_started=true и единственное
  незавершённое ActionExecution. Новый объект контракта или новый процесс не сбрасывает
  бюджет. Crash после расходования не приводит к автоматическому повтору.
- Один POST, окно не более 600 секунд, существующий предел ожидания POST 30 секунд,
  общая локальная quota/cooldown, UNKNOWN и ручной non-authoritative readback сохранены.
  Ошибка/timeout/поздний ACK не разрешают повтор или автоматическое восстановление статуса.

## Проверки

Все рекламные HTTP операции в тестах использовали только httpx.MockTransport,
изолированные fixtures и синтетический ключ. Рабочий WRITE credential не раскрывался.

- Новые тесты настоящего, неподменённого gate: финальные 35 PASS за 43.04 s. Проверены PAUSE/ENABLE,
  exact body/path, запрет async/budget/GET, чужой workspace/revision, отсутствие
  explicit authorization, отзыв/подмена proof, inactive user, deadline, emergency flags,
  durable wire budget, restart и отсутствие повторов после timeout/403/429/503.
  Финальные 4 дополнительных случая проверяют неизменное 600-секундное окно и запрет
  открытия vault до authorization/durable claim. После этих изменений целевой набор
  и оба PostgreSQL harness повторно прошли на окончательных исходниках.
- Backend regression: 155 PASS за 111.65 s; включает исходные 31 и существующие
  controlled rehearsal, synchronous status, deadlines, adapter и WRITE preparation.
- Отдельный production pilot/private ASGI/admin/CSRF regression: 68 PASS за 98.35 s.
- PostgreSQL restored DB mcc_integrations_controlled_20261016_211626: PASS.
  Production-shaped ветка использует настоящий gate/registry без patch; 8 процессов
  дают один claim и один mock POST, restart не повторяет, crash exit 17 -> UNKNOWN.
  Полный harness также сохраняет старые mock-only сценарии: 13 физических mock attempts,
  включая 3 deadline и 6 multilevel sync cases; реальных provider requests=0.
- Credential Manager DB role: PASS на restored DB в отдельной внешней транзакции.
  Gate не подменялся; один mock POST, no resend, manual readback без API authority.
  Все 6 лишних прав отклонены; роль, схема и тестовые строки полностью rolled back.
- Ruff новых компонентов и изменённых pilot/factory/writer/scripts: PASS;
  format --check 9 файлов: PASS; security_scan: PASS; frontend typecheck: PASS.
  В legacy engine остаются ровно 5 прежних Ruff findings, сверено с HEAD;
  в transport сохранился прежний TRY004. Проверки не отключались.

## Что остаётся до первого рекламного теста

1. Получить provider-authored подтверждение namespace WRITE entity_id для level=ad.
   Текущий OpenAPI подтверждает path/body, но string не устанавливает равенство Facebook
   Ad ID. Business/entities:write уже измерены предыдущим этапом; это не доказательство ID.
   Нельзя записывать принятый contract_review на основании предположения или этого отчёта.
2. По подтверждённому источнику выполнить доверенный review с точной привязкой к одному
   новому ручному запросу, оператору, READ/WRITE revisions, hierarchy и статусам.
   Сейчас trusted acceptance record отсутствует; интерфейса его самоподтверждения нет.
3. Обновить штатным Credential Manager проверку WRITE scope и READ snapshot; вручную
   сверить own/effective status и родителей. Подтверждение прав пользователя сохраняется
   как USER_ATTESTED, оно не заменяется независимой проверкой Meta.
4. Сформировать окончательную карточку одного PAUSE_AD и получить отдельное разрешение
   пользователя на эту команду. После него — ограниченная активация приватного CM по
   действующей процедуре, authorize с точным statement и execute с возвращённой revision.
   Не включать scheduler, Rule Engine LIVE или общий frontend WRITE proxy.
5. Сразу после попытки закрыть активацию и сверить статус вручную. При UNKNOWN сначала
   reconciliation; не повторять POST и не выполнять обратное ENABLE автоматически.

Выбранный ранее кандидат: act_1047962734516123, AD 120247747556780571.
Это исторический выбор, не актуальное разрешение и не проверка текущего статуса AD.
MetricFlow сохраняется: условие удаления интеграции не подтверждено. Прямой Meta остаётся
отдельным неподключённым запасным путём, а не готовой заменой.

## Развёртывание и проверка сохранности

Собран и развёрнут metric-control-center-scoped-pilot-20261020:local. Обновлены только
backend и credential-manager; worker/scheduler/frontend/PostgreSQL/Redis сохранили
исходные container IDs. Старые image IDs и rollback override сохранены локально.
Миграции и provisioner повторно не запускались; PostgreSQL остаётся 0016_smart_control,
исходный migrate container — exited 0. Рабочие volumes не удалялись.

- .env SHA до/после совпадает; 14 защищённых таблиц совпали по count/digest до/после
  deploy и повторно после runtime/browser smoke. Защищены пользователи/сессии,
  экономика, правила, action requests/executions/logs и READ/WRITE credential records.
- По 8 реально загруженных модулей backend/CM совпали по SHA с финальными исходниками,
  включая новый pilot_contract, engine, factory, writer, transport и safety.
- Runtime обоих сервисов: ACTIONS_ENABLED=false, LOCAL_READ_ONLY=true, AI_ENABLED=false,
  AI_AUTOPILOT_ALLOWED=false. Gate=WRITE_DISABLED, общий registry=BLOCKED.
- MetricFlow READ healthy, revision 1, последний сохранённый успех
  20.10.2026 08:30:03 UTC / 11:30:03 МСК. Отдельный WRITE configured, revision 1.
  Ни ключ, ни подключение, ни credential audit этим этапом не менялись.
  Нового GET /me этим этапом не было; прежнее подтверждение Business/entities:write
  относится к измерению из AD_CONTROL_PROVIDER_READINESS_2026-10-20.md.
- Meta disabled/disconnected, revision 4. Meta LIVE не включался.
- Production ActionExecution=0, LIVE_SINGLE_OPERATION permit=0, accepted evidence=0.
- Локальная MetricFlow квота на снимке 23/800, cooldown отсутствует. Это общий счётчик
  штатного READ; данный этап не инициировал authenticated provider requests.
- Frontend typecheck PASS. Playwright через установленный Edge: 3 anonymous smoke
  checks PASS (login, auth redirect /manual-control, zero page errors), внешняя сеть
  блокировалась, формы не отправлялись. Это не manual acceptance LIVE-кнопки.

Sanitized evidence: ignored .tools/scoped-contract-20261020/ — backend-regression.txt,
contract-final.txt, postgres-role-final.txt, postgres-race-final.txt, build-final.log,
deployment.json, runtime-final.json, browser-smoke.json, final-integrity.json, quality.json.

SERVER IMPLEMENTATION: READY LOCAL/MOCK; DEPLOYED CLOSED.
FIRST CONTROLLED AD POST: BLOCKED — external WRITE ID proof, trusted acceptance,
fresh credential/status checks and explicit user authorization are still required.

ADVERTISING WRITE REQUESTS: 0.
META LIVE REQUESTS INITIATED BY THIS STAGE: 0.
