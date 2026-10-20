# Пилот AD внутри выключенной кампании — 20.10.2026

STATUS: PLANNED ONLY / NOT EXECUTABLE.
ADVERTISING WRITE REQUESTS: 0.

## Выбранный кандидат

Кабинет Valya Sergeeva, act_1047962734516123, timezone America/Los_Angeles.
Пользователь разрешил подготовить тест на выключенной кампании; конкретный POST
не отправлен. Согласование экспериментального режима с неизвестным WRITE namespace
запрошено отдельно и ожидает ответа. Производственные gates не изменялись.

| Уровень | ID | Название | Provider status | Effective status |
| --- | --- | --- | --- | --- |
| Campaign | 120247730079240571 | 24.09 - 218-227.1-3 - Adenofrin - ES -ED - 123 | PAUSED | PAUSED |
| AdSet | 120247730105950571 | 3 | PAUSED | PAUSED |
| Ad | 120247730105960571 | #71012012_EGR_Creo 03 | ACTIVE | ADSET_PAUSED |

Это снимок READ, не гарантия текущего положения переключателей:
meta.data_updated_at = 20.10.2026 17:51:32 UTC / 20:51:32 МСК.
Получен 17:54:48 UTC / 20:54:48 МСК. Перед будущим POST требуется новая сверка
обоих родителей и собственного статуса AD. Снимок нельзя продлевать временем
получения ответа или использовать после истечения окна свежести.

Источник — документированные GET /api/v1/ad-accounts/{ad_account_id}/campaigns,
/adsets и /ads, один выбранный кабинет, дата в timezone кабинета. Response metadata:
25 campaigns, 70 adsets, 71 ads; total совпадает с числом строк, общий timestamp.
Иерархия AD parent_id -> AdSet id -> campaign_id сопоставлена по фактическим
READ-ответам, с проверкой совпадения campaign_id у AD и AdSet.

Первый сборщик ожидал adset_id в ответе /ads и не сформировал кандидатов.
После просмотра фактического контракта READ использован parent_id; сделано ещё
3 GET без retries. Итого 6 диагностических GET, все учтены общим ProviderManager.
Сохранены только ID, имена, статусы и метаданные; ключи не записывались.
Неподдерживаемые фильтры и недокументированные рекламные endpoints не вызывались.

## Последовательность предполагаемого теста

1. Снова проверить, что Campaign и AdSet выключены, AD имеет status=ACTIVE,
   и нет внешнего расписания/оператора, способного включить родителей в окно теста.
2. Одна отдельно согласованная PAUSE_AD на 120247730105960571, body level=ad.
   Не менять группу, кампанию, бюджеты или ставки.
3. Сверить AD собственный PAUSED в MetricFlow и Ads Manager. ACK не является
   доказательством статуса. При timeout/ошибке/расхождении — UNKNOWN и остановка.
4. Только после подтверждённого результата и нового отдельного разрешения — один
   ENABLE_AD для возврата исходного собственного ACTIVE; родители сохраняются PAUSED.
   При любой неопределённости не выполнять автоматическое восстановление.

Каждая команда: один POST, отдельный permit, window <=600 s, POST timeout 30 s,
никаких retries/resend, concurrency 1. Rule Engine/AI не исполняют команды.
Если сначала испытывается AD, AdSet WRITE не входит в этот пилот: существующий
приватный dispatcher ограничен AD. Группы требуют отдельного этапа приёмки.

## Найденные обязательные условия

- WRITE entity_id namespace остаётся UNVERIFIED. Наличие API методов не доказывает
  равенство WRITE ID и Facebook Ad ID; текущий server-side gate требует provider review.
- Ожидается выбор пользователя: сохранить требование подтверждения провайдером или
  подготовить явно экспериментальный пилот с неподтверждённым ID. Второй вариант не
  является разрешением POST и потребует отдельной политики/карточки; нельзя записывать
  его как PROVIDER_DOCUMENTATION или подменять им accepted подтверждённый контракт.
- Локальный EntityCurrentState выбранного AD хранит старый effective ADSET_PAUSED,
  observed_at 08.10.2026; raw содержит только status=ADSET_PAUSED. Между тем свежий
  /ads возвращает отдельно status=ACTIVE и effective_status=ADSET_PAUSED.
  Сейчас manual snapshot/preflight сравнивает сохранённый effective status с expected
  ACTIVE/PAUSED. Нельзя использовать этот baseline для пилота под выключенными родителями.
  Перед подготовкой исполнимой команды нужны отдельная корректная фиксация собственного
  статуса из свежего READ и проверки иерархии/родителей. Факты не переписаны вручную,
  существующая freshness-проверка не ослаблена.
- WRITE credential encrypted, revision 1, cached check 18.10.2026 14:30:26 UTC;
  перед будущим authorize требуется штатная свежая проверка через Credential Manager.
- Во время этого этапа executable request/permit/accepted evidence не создавались.

## Восстановление READ после запуска Docker

Docker Desktop был остановлен; после проверки .env запущен существующий Desktop
без изменения контейнеров/образов/volumes. Первый штатный today sync 17:50 UTC
завершился TransportUnavailable при сетевом старте, а диагностические GET затем прошли.
Повторён существующий metricflow_sync today с прежними lease/quota/revision guards,
без backfill. Run da55b11c-c4e5-4322-9518-b754d2f4f261: succeeded, 10 requests,
26 rows, 4 accounts. Это обычная публикация READ, не изменение рекламных объектов.
Последующий сохранённый READ health: healthy, revision 1,
last_success_at 20.10.2026 18:50:02 UTC / 21:50:02 МСК.

Meta disabled/disconnected revision 4. WRITE revision 1 без изменения credential.
.env SHA совпадает с прежним; ACTIONS_ENABLED=false, LOCAL_READ_ONLY=true,
AI_ENABLED=false, AI_AUTOPILOT_ALLOWED=false. ActionExecution=0, accepted evidence=0,
LIVE_SINGLE_OPERATION permit=0. Проверено локальными SELECT.

Sanitized local evidence: ignored .tools/off-campaign-pilot-20261020/
read-candidates.json, read-candidates-final.json, planned-card.json,
read-recovery.txt, local-final.json. Backend/frontend код не изменён; новые unit и
Playwright тесты не запускались. Проверены три актуальных READ-каталога, согласованность
ID/status/timestamp и штатное восстановление READ. Рабочие WRITE gates не обходились.

FINAL: CANDIDATE IDENTIFIED; LIVE BLOCKED; EXPERIMENTAL MODE DECISION PENDING.

## Дополнение: выбор экспериментальной подготовки принят

Пользователь выбрал подготовку экспериментального пилота на AD 120247730105960571.
Реализован отдельный fail-closed допуск PAUSE_AD с UNVERIFIED namespace, собственным
READ baseline и повторной проверкой выключенных родителей. Подготовлен DRAFT
776a0dd3-6130-4785-ba41-b6d3596afd10; разрешение POST не предоставлялось.
Предыдущие измерения и блокеры выше относятся к состоянию до этой реализации.
Namespace провайдером по-прежнему не подтверждён; production contract остаётся BLOCKED.
Актуальные лимиты, срок карточки и результаты проверок:
[Experimental preparation](METRICFLOW_EXPERIMENTAL_PILOT_PREPARATION.md).
