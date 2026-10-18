"use client";

import { useEffect, useState } from "react";
import { manualRead } from "../lib/manual-control";

type Review = {
  mode: "MANUAL_REVIEW_ONLY";
  execution_allowed: false;
  generated_at: string;
  operation: "PAUSE_AD" | "ENABLE_AD";
  target_status: string;
  entity: {
    id: string; name: string; ad_id: string; account_id: string;
    account_name: string; adset_id: string | null; campaign_id: string | null;
    timezone: string; status: string | null; effective_status: string | null;
    observed_at: string | null;
  };
  read_connection: { revision: number | null; last_success_at: string | null };
  write_connection: { revision: number; checked_at: string | null; fresh_scope_evidence: boolean };
  local_checks: Record<string, boolean>;
  proposed_limits: { total_http_attempts: number; post_attempts: number; timeout_seconds: number };
};
const labels: Record<string, string> = {
  READ_CONNECTED_HEALTHY: "READ-подключение работает",
  STATUS_FRESH: "Сохранённый статус свежий",
  BASELINE_MATCHES_OPERATION: "Исходный статус соответствует операции",
  ACCOUNT_MAPPING_CONFIRMED: "Кабинет сопоставлен",
  HIERARCHY_MAPPING_CONFIRMED: "Иерархия объявления сопоставлена",
  PRIMARY_PROVIDER_METRICFLOW: "Источник — MetricFlow",
  WRITE_CREDENTIAL_CONFIGURED: "Отдельный WRITE-ключ сохранён",
  WRITE_SCOPE_EVIDENCE_FRESH: "Проверка WRITE scope свежая",
  NO_PENDING_ACTION: "Нет незавершённой команды на это объявление",
};
const time = (value: string | null) => value ? new Date(value).toLocaleString("ru-RU") : "Неизвестно";

export default function PilotReview({ entityId }: { entityId: string }) {
  const [opened, setOpened] = useState(false);
  const [operation, setOperation] = useState<"PAUSE_AD" | "ENABLE_AD">("PAUSE_AD");
  const [revision, setRevision] = useState(0);
  const [card, setCard] = useState<Review | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!opened) return;
    let ignore = false;
    setCard(null);
    setError("");
    void manualRead<Review>(`/pilot-review/${encodeURIComponent(entityId)}?operation=${operation}`)
      .then(value => { if (!ignore) setCard(value); })
      .catch(value => { if (!ignore) setError(value instanceof Error ? value.message : "Не удалось загрузить карточку"); });
    return () => { ignore = true; };
  }, [opened, entityId, operation, revision]);
  if (!opened) return <button onClick={() => setOpened(true)}>Подготовить ручную проверку пилота</button>;
  return <section aria-label="Карточка ручной сверки пилота">
    <h4>Ручная сверка перед пилотом</h4>
    <p>Это проверка сохранённых данных. Она не разрешает и не запускает рекламную команду.</p>
    <label>Операция для сверки <select value={operation} onChange={event => setOperation(event.target.value as typeof operation)}>
      <option value="PAUSE_AD">Отключение объявления</option>
      <option value="ENABLE_AD">Включение объявления</option>
    </select></label>
    <button onClick={() => setRevision(value => value + 1)}>Обновить карточку из БД</button>
    {error && <p role="alert">{error}</p>}
    {!card && !error && <p role="status">Загрузка карточки…</p>}
    {card && <>
      <dl className="rule-facts">
        <div><dt>Кабинет</dt><dd>{card.entity.account_name} · {card.entity.account_id}</dd></div>
        <div><dt>Объявление</dt><dd>{card.entity.name} · {card.entity.ad_id}</dd></div>
        <div><dt>AdSet ID / Campaign ID</dt><dd>{card.entity.adset_id ?? "—"} / {card.entity.campaign_id ?? "—"}</dd></div>
        <div><dt>Timezone кабинета</dt><dd>{card.entity.timezone}</dd></div>
        <div><dt>Сохранённый / effective статус</dt><dd>{card.entity.status ?? "Неизвестно"} / {card.entity.effective_status ?? "Неизвестно"}</dd></div>
        <div><dt>Целевой статус</dt><dd>{card.target_status}</dd></div>
        <div><dt>Время сохранённого статуса</dt><dd>{time(card.entity.observed_at)}</dd></div>
        <div><dt>READ / WRITE revision</dt><dd>{card.read_connection.revision ?? "—"} / {card.write_connection.revision}</dd></div>
        <div><dt>Последняя проверка WRITE</dt><dd>{time(card.write_connection.checked_at)}</dd></div>
        <div><dt>Карточка сформирована</dt><dd>{time(card.generated_at)}</dd></div>
      </dl>
      <ul aria-label="Локальные условия пилота">{Object.entries(card.local_checks).map(([code, passed]) =>
        <li key={code}>{labels[code] ?? code}: {passed ? "подтверждено локально" : "требует проверки"}</li>)}</ul>
      <p>WRITE scope не подтверждает право изменять конкретное объявление. Карточка не проверяет ключ запросом к провайдеру.</p>
      <h4>Что сверить вручную сейчас</h4>
      <ol>
        <li>Откройте MetricFlow и найдите этот кабинет и AD по точным ID. Сверьте название и иерархию.</li>
        <li>Откройте тот же AD в Ads Manager. Сверьте собственный статус объявления и effective статус с учётом родителей.</li>
        <li>Проверьте, какой пользователь MetricFlow подключил кабинет и имеет ли он право управления этим AD.</li>
      </ol>
      <p>Не нажимайте переключатели статуса. Сообщите ID кабинета и AD, видимые статусы, время сверки и наличие права управления. Не передавайте ключи или токены.</p>
      <p>После сверки останутся отдельные проверки WRITE ID, API-доступа и результата команды; ручной ответ не снимает server-side ограничения.</p>
      <p>Предлагаемый предел будущего пилота: {card.proposed_limits.post_attempts} POST, всего не более {card.proposed_limits.total_http_attempts} HTTP attempts, timeout {card.proposed_limits.timeout_seconds} секунд. Эти лимиты пока не активированы.</p>
      <strong>LIVE заблокирован. Разрешение на запуск не предоставлено.</strong>
    </>}
  </section>;
}