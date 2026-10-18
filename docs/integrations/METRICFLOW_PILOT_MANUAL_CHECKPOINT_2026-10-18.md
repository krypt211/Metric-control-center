# MetricFlow pilot — ручной checkpoint и повторная проверка WRITE scope

Дата: 18.10.2026. Часы автоматических проверок ниже — Europe/Moscow (UTC+3).
MANUAL BASELINE REVIEW: COMPLETE. WRITE SCOPE: VERIFIED.
Phase 4B: PARTIAL. LIVE WRITE: BLOCKED. Advertising WRITE requests: 0.

## Ручные сведения пользователя

Сверка в 17:28 — время, указанное пользователем; timezone отдельно не уточнялась.
Кабинет Valya Sergeeva / act_1047962734516123.
AD #70495691_EGR_Creo 06 / 120247747556780571.
AdSet 120247747556830571; Campaign 120247747556760571.

| Объект / условие | Сообщено пользователем |
| --- | --- |
| Собственный переключатель AD | Включён |
| Группа | Включена |
| Кампания | Выключена |
| Доставка | Не активно |
| Роль / право управления в MetricFlow | Не видно |

Ранее пользователь сообщил об отключении по расписанию. Время/причина
перехода кампании не подтверждались независимым API-аудитом. Ручные сведения
не записывались поверх EntityCurrentState и не изменяли рекламные факты.

Выключенная родительская кампания согласуется с неактивной доставкой при включённом
объявлении. AD ACTIVE сам по себе не подтверждает effective ACTIVE и доставку.
Текущий AD не обеспечивает исходное состояние для проверки влияния PAUSE на
активную доставку. Автоматическое включение родителей или замена AD не разрешены.

## Измерено локально и через существующий Credential Manager

18.10.2026 17:30:26 МСК / 14:30:26 UTC выполнен существующий административный
check через backend и приватный Credential Manager. Он использует сохранённый
WRITE credential и GET-only MetricFlowConnector, read_retries=0, один GET
/api/v1/me через существующее резервирование квоты. PAUSE/ENABLE/BUDGET endpoints
не вызывались. POST внутри приложения проверяет credential metadata и не является
рекламным WRITE-запросом.

| Проверка | Результат |
| --- | --- |
| Локальный Credential Manager check | HTTP 200, checked_at обновлён |
| WRITE state | SCOPES_VERIFIED |
| Документированный entities:write | PRESENT |
| access_state | active_paid |
| WRITE credential revision | 1, не изменена |
| Зашифрованный WRITE credential | Не изменён; открывается существующим vault |
| READ revision | 1, не изменена |
| READ status | healthy; last success 17:30:02 МСК |
| READ credential file / DB envelope | Не изменены |
| Локальная квота MetricFlow | 237 -> 238 из 800; лимит не менялся |
| WRITE audit | Добавлена одна штатная запись check |
| Временная локальная admin session | Удалена; существующие сессии не затронуты |
| ActionRequest | Число записей не изменилось |
| ActionExecution | 0 |
| Рекламные WRITE / Meta LIVE в этой проверке | 0 / 0 |

API credential не выводился из Credential Manager, не возвращался в браузер,
логи или отчёт. Временный административный session token существовал только
в памяти backend diagnostic; в БД был штатный hash. Auth/CSRF и квота не обходились.

READ ONLY SQL после проверки: AD status=ACTIVE, observed_at=17:30:00 МСК,
effective_status=null; account/provider/AD ID совпадают. Этот сохранённый
status не переименован в доказанный configured/effective status.

## Документированность и пределы проверки

GET /api/v1/me подтверждён сохранённым официальным OpenAPI:
.tools/write-openapi/openapi.json, SHA256
12cf5cc017e36ba54add51cb10eb2e625607f60bd55b7fa79f2cee5467d35077.
При текущем анонимном получении публичного OpenAPI сервер вернул HTTP 403;
это отдельно от успешной аутентифицированной проверки GET /me. Актуальность
всего публичного WRITE-контракта на основании этого запроса не объявляется.
Новые endpoints/параметры не предполагались.

entities:write и active_paid подтверждают scope и платный доступ, но не право
на выбранный рекламный объект. Роль пользователя осталась неизвестной.

## Остаточные блокеры

1. Точный namespace WRITE entity_id и доказанная связь с выбранным READ ad_id.
2. Права текущего подключения на кабинет/AD; роли в UI и общий scope недостаточны.
3. Принятый async ACK/error contract: формальный 202, partial/failed,
   timeout и потерянный job_id; без автоматического повторного POST.
4. Авторитетный readback: собственный configured status AD, effective status
   родителей, свежесть конкретного объекта и предельная задержка обновления.
5. Production одноразовый permit/dispatcher остаётся не завершён до принятия
   обязательных условий. Mock-only permits не повышаются до LIVE флагами.
6. Для проверки влияния PAUSE на доставку нужно согласованное рабочее окно
   кампании или отдельно выбранный пользователем подходящий AD.
7. До первого реального WRITE необходимо отдельное разрешение на конкретную
   операцию, target IDs, исходное состояние, credential revision и бюджет попыток.

Следующий ручной шаг в MCC: обновить карточку из БД; проверка свежести WRITE scope
должна использовать новый checked_at. Включать кампанию для этой сверки не нужно.
Неизвестные права не заменяются предположением об администраторе.

ACTIONS_ENABLED=false; LOCAL_READ_ONLY=true; AI_ENABLED=false;
AI_AUTOPILOT_ALLOWED=false подтверждены в рабочем backend. Подключения, revisions,
правила, экономика, расписания и рекламные данные этой проверкой не менялись.
Source code не изменялся; unit/Playwright повторно не запускались. Выполнены
диагностическая end-to-end credential check и локальные проверки сохранности.
