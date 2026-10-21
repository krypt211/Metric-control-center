# Creo 03 — IT economics, local rule preparation — 21.10.2026

## Подготовленный результат

По выбору пользователя «можно взять правила для IT» создано отдельное правило:

- Name: TEST - Creo 03 - PAUSE - IT.
- UUID: 4ce4ba4b-6c54-42f7-9da8-9e55e75cab3a, revision 1.
- Mode DRY_RUN, enabled=false, next_evaluation_at=null, allow_reenable=false.
- Action PAUSE_AD. Единственная цель — AD 120247730105960571,
  #71012012_EGR_Creo 03, account act_1047962734516123.
- Profile: существующий IT «1», 3f5e842d-4f14-4646-af7f-79538cf00d2f, version 1.
- Условие: CPL_ABOVE_LIMIT, maximum, actual CPL, USD.
- Период диагностического прогона: 28.09.2026, единственный день с сохранёнными
  дневными фактами этого AD. Это диагностический historical scope, не расписание LIVE.
- Cooldown 3600 s, estimated_policy=review. Унаследованные ограничения не ослаблялись.

Параметры IT: payout 52 USD, planned approval 20%, minimum ROI 18%, target ROI 50%.
Максимальный CPL: 52 * 0.2 / 1.18 = 8.81355932 USD.
Целевой CPL: 52 * 0.2 / 1.50 = 6.93333333 USD.
Профиль имеет legacy default timezone Europe/Moscow; аккаунт — America/Los_Angeles.
Настройки существующего IT-профиля не менялись. Перед применением к текущему периоду
необходимо подтвердить календарь фактов; дни не сдвигались по догадке.
Использование IT-экономики на этом AD — пользовательский выбор для локального теста,
не подтверждение гео/экономической применимости к произвольной ES-кампании.

## Измеренные локальные результаты

Существующее Creo 06 правило не переназначалось, revision 4 и payload сохранены.
Оба исходных профиля экономики сохранены. Новое правило создано существующим
smart_store.save и проверено существующим simulate, атомарно одной транзакцией.
Обычное расписание не включалось. Новых ActionRequest и ActionExecution нет:
до/после — 8 requests и 2 executions. Provider HTTP во всём этапе: 0.

Simulation: 455db8db-f65a-446c-a6a1-b5ca12982c82.
Результат: DATA_STALE, 1 AD. Причины: ATTRIBUTION_UNVERIFIED, WINDOW_INCOMPLETE.
Исторический actual CPL 5.38333333 USD, максимум 8.81355932 USD, estimated ROI
93.18885449% — модель по IT-параметрам, не фактически подтверждённый ROI продаж.
Неполнота окна не позволяет использовать эти числа для боевого решения.

Контекст: ad_status ADSET_PAUSED (effective snapshot), status_fresh=false,
parents_active=false, paused_by_system=false, unresolved_action=true.
Ручное подтверждение собственного переключателя ACTIVE не переписывало рекламные
факты и не создавало verified pause ownership для правил.

Предыдущие диагностические симуляции текущего старого правила:
11823eb4-b920-44ce-a77d-63b405e0f55f — исходная цель Creo 06;
d2597c9c-163b-4eaf-b2e7-830dd8141efe — временный preview Creo 03 без сохранения назначения.
Обе DATA_STALE на старом периоде 10–16 октября; они не являются новым бизнес-правилом.
Первый preview остановился на передаче dict вместо типизированного RuleTarget;
исправлен только локальный диагностический вызов, production не менялся.

## Проверка вычислений и защиты

98 PASS: test_smart_completion, test_smart_rules, test_rule_targets,
test_smart_recommendations. В этом этапе production-код не менялся.

Дополнительно проверен настоящий pure condition evaluator с фактическим IT-порогом,
но явно синтетическими входами с полным окном:

| Synthetic actual CPL | Порог | Truth |
| --- | --- | --- |
| 9 USD | 8.81355932 USD | TRUE |
| 8 USD | 8.81355932 USD | FALSE |
| unknown | 8.81355932 USD | UNKNOWN |

В первом synthetic вызове не был указан window_complete: evaluator вернул UNKNOWN,
assertion остановила транзакцию до создания правила. Добавлен флаг полноты только
в синтетическую fixture; реальные guards и результаты DATA_STALE не ослаблялись.
Это 3 проверки условия, не LIVE и не полная проверка финансовых фактов.

Создание ранее не выполнялось из-за сбоя auto-review по кредитам; после «продолжай»
доступ восстановился. Команда не обходила отказ проверки. Повторная операция защитилась
от дубля по точному имени и имела одну атомарную транзакцию create/version/audit/simulate.

## Сверка завершённого ручного пилота

Пользователь дополнительно сообщил статус «группа объявлений отключена»:
зафиксирован effective_status ADSET_PAUSED при собственном ACTIVE и родителях PAUSED.
Точное время ручного наблюдения не выдумывалось. Добавлено audit событие
pilot_manual_effective_status_confirmed. Новых GET/POST не отправлялось.

ENABLE execution после исходного deadline переведён штатным verify_pending в
unknown / live_unknown / MANUAL_READBACK_DEADLINE. Это формальный исход полного
readback-протокола; он не отменяет сохранённое ручное подтверждение переключателей.
Нельзя переписать этот исход ради допуска правил. Первый PAUSE локально reviewed,
но не создал authoritative ownership. Для будущей автоматизации нужны отдельные
проверенный configured-status источник, bounded readback и разрешение режима.

## Следующая ручная проверка и блокеры

Открыть «Правила» (/rules), найти TEST - Creo 03 - PAUSE - IT и сверить:
единственная цель 120247730105960571, IT-профиль, CPL выше maximum, режим DRY RUN,
правило выключено. В истории есть приведённая симуляция с DATA_STALE.
Не включать рекламные WRITE или родителей для проверки этого правила.

До осмысленного прогона на фактах требуются полный согласованный READ-период,
подтверждённая атрибуция/таймзона и свежий собственный статус AD. Для LIVE дополнительно
нужны reconciliation текущего UNKNOWN без подделки исхода, отдельный rule-bound
допуск и отдельное разрешение пользователя. Ручной single-AD pilot не даёт Rule Engine
права на автоматические POST. Авто-ENABLE не включён; расписание правила не запущено.

ACTIONS_ENABLED=false; LOCAL_READ_ONLY=true; AI_ENABLED=false;
AI_AUTOPILOT_ALLOWED=false. MetricFlow READ и Meta-настройки не менялись.
ADVERTISING WRITE REQUESTS TOTAL: 2 (PREVIOUS MANUAL PAUSE + ENABLE ONLY).
NEW PROVIDER REQUESTS: 0. NEW ADVERTISING ACTION REQUESTS: 0.

FINAL: LOCAL RULE CREATED AND TESTED; FACT-BASED RUN HELD; LIVE NOT AUTHORIZED.
Evidence (ignored): .tools/rules-after-pilot-20261021/.

## Повторная локальная проверка после пилота группы — 18:55 МСК

Проверено существующее правило 4ce4ba4b-6c54-42f7-9da8-9e55e75cab3a,
revision 1. Новое правило не создавалось, существующие профили и назначения
не менялись. DRY_RUN, enabled=false, allow_reenable=false, расписание отсутствует.

Существующий simulate сохранил новый диагностический результат:
b1b36f76-4c74-4cc2-8079-7745077a0c7f, период 28.09.2026, Europe/Moscow.
Один AD 120247730105960571: DATA_STALE, ATTRIBUTION_UNVERIFIED,
WINDOW_INCOMPLETE; action_eligibility=false. Actual CPL 5.38333333 USD,
maximum CPL 8.81355932 USD. Сохранённый effective статус ADSET_PAUSED устарел;
он не отменяет более поздние ручные подтверждения AD/группы и не был ими перезаписан.
В этом прогоне unresolved_action=false для AD; это не допуск LIVE и не закрытие
отдельного UNKNOWN результата группы.

Актуальные SELECT подтвердили ровно одну daily_metrics строку MetricFlow:
28.09.2026, timezone America/Los_Angeles, observed_at 08.10.2026 02:20:41 UTC.
Hourly rows=0. EntityCurrentState имеет тот же старый observed_at.
Legacy IT-профиль использует Europe/Moscow; без почасовых данных нельзя точно
пересчитать этот суточный факт в другой календарь. Исторические деньги и даты
не переписывались, полнота и атрибуция не помечались подтверждёнными вручную.

Пять дополнительных проверок pure condition evaluator на синтетических входах:
9 USD -> TRUE; 8 USD -> FALSE; ровно 8.81355932 USD -> FALSE;
неизвестный CPL -> UNKNOWN; CPL 9 при неполном окне -> UNKNOWN.
Эти fixtures не сохраняются как рекламная статистика и не запускают команды.

До/после все rule payload/revision/schedule и economics profile payload совпали.
ActionRequest=9, ActionExecution=3 без изменений. Добавлена только локальная
симуляция с её штатным audit. Provider HTTP=0, рекламных WRITE=0 за этот этап.
Все четыре защитных флага сохранены; общее историческое число POST теперь 3.

Следующая ручная проверка UI: /rules -> TEST - Creo 03 - PAUSE - IT.
Проверить цель Creo 03 / AD 120247730105960571, IT-профиль, выключенный DRY_RUN,
порог maximum CPL, и новый результат DATA_STALE в истории. Ничего не включать.
Если UI предлагает локальную симуляцию, её можно выполнить: ожидается остановка
по качеству данных. Повторный READ/сбор истории этим этапом не запускался.

Перед тестом бизнес-решения на реальных фактах нужны свежий configured/effective
статус, полное READ-окно, подтверждённая атрибуция и согласованный календарь
отдельного тестового профиля. Исходный IT-профиль сохраняется. Для последующего
LIVE правила необходимы отдельный rule-bound допуск, проверка readback/ownership
и отдельное разрешение. Включать кампанию для локального теста не требуется.

Evidence (ignored): recheck-after-group.json, coverage-after-group.json,
recheck-after-group.py в .tools/rules-after-pilot-20261021/.
CURRENT: LOCAL RULE RECHECK COMPLETED; REAL-DATA DECISION BLOCKED; LIVE DISABLED.

Регрессии этого повторного этапа: фактически выполнены test_smart_completion,
test_smart_rules, test_rule_targets, test_smart_recommendations — 98 PASS, 99.35 s.
Secret scan PASS; git diff --check PASS. Production-код не менялся;
backend/frontend/Docker/Playwright не перезапускались ради документации и DB-only
симуляции. Предыдущие результаты относятся к своим этапам, не к этому повтору.
