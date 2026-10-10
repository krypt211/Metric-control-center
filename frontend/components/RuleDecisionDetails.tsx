import { formatMetric } from "../lib/column-model";
import { useEffect, useState } from "react";
import { manualRead, manualWrite } from "../lib/manual-control";
import { localized } from "../lib/economics";
import {
  conditionNames,
  ruleLabel,
  thresholdNames,
  type Row,
  type ThresholdKey,
} from "../lib/smart-rules";

function ConditionResults({ node }: { node: Row }) {
  if (node.kind === "group")
    return (
      <div className="rule-expression-result">
        <strong>
          {node.operator === "AND" ? "И" : "ИЛИ"} · {ruleLabel(node.truth)}
        </strong>
        {(node.children as Row[]).map((child, i) => (
          <ConditionResults key={i} node={child} />
        ))}
      </div>
    );
  return (
    <p>
      {conditionNames[node.type as keyof typeof conditionNames]} ·{" "}
      {node.source === "estimated"
        ? "прогноз"
        : node.source === "observed"
          ? "наблюдаемые покупки"
          : node.source === "approved"
            ? "апрувы"
            : "факт"}
      : <strong>{ruleLabel(node.truth)}</strong>
      <br />
      Значение: {String(node.value ?? "неизвестно")}; порог:{" "}
      {String(node.threshold ?? "неизвестно")}; отклонение:{" "}
      {String(node.delta ?? "—")}
      {String(node.type).startsWith("ROI_") ? " п.п." : ""}
      {(node.reason_codes as string[])?.length > 0 && (
        <>
          <br />
          {(node.reason_codes as string[]).map(ruleLabel).join("; ")}
        </>
      )}
    </p>
  );
}

export default function RuleDecisionDetails({
  card,
  simulationId,
}: {
  card: Row;
  simulationId?: string;
}) {
  const [allowed, setAllowed] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  useEffect(() => {
    void manualRead<{ can_control: boolean }>("/settings")
      .then((s) => setAllowed(s.can_control))
      .catch((e) => setError(e.message));
  }, []);
  async function prepare() {
    setBusy(true);
    setError("");
    try {
      const r = await manualWrite<{ id: string }>(
        "/from-rule",
        { simulation_id: simulationId, entity_id: card.id },
        crypto.randomUUID(),
      );
      window.location.assign("/manual-control?request=" + r.id);
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Не удалось подготовить команду",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <article className="rule-details" aria-label="Объяснение решения">
      {card.status === "WOULD_PAUSE" && simulationId && allowed && (
        <button disabled={busy} onClick={() => void prepare()}>
          Подготовить отключение
        </button>
      )}
      {error && <p role="alert">{error}</p>}
      <h3>
        {String(card.name)} ·{" "}
        <span className={`rule-badge rule-${card.status}`}>
          {ruleLabel(card.status)}
        </span>
      </h3>
      <p>
        Объявление: {String(card.external_id ?? card.id)} · аккаунт:{" "}
        {String(card.account_name)} · кампания: {String(card.campaign ?? "—")} ·
        группа: {String(card.adset ?? "—")}
      </p>
      <p>
        Профиль: {String(card.profile_name ?? "не назначен")} · v
        {String(card.profile_version ?? "—")} · период:{" "}
        {String(card.period_start)} — {String(card.period_end)} · timezone
        кабинета: {String(card.timezone)} · источник:{" "}
        {String(card.source_provider)} · синхронизация:{" "}
        {String(card.source_facts_timestamp ?? "неизвестно")}
      </p>
      <dl className="rule-facts">
        {[
          "spend",
          "leads",
          "observed_meta_purchases",
          "approved_sales",
          "pending_sales",
          "actual_cpl",
          "target_cpl",
          "maximum_cpl",
          "approved_cps",
          "estimated_roi",
          "actual_roi",
          "minimum_roi",
          "applied_approval_percent",
        ].map((k) => (
          <div key={k}>
            <dt>
              {
                (
                  {
                    spend: "Расход",
                    leads: "Лиды",
                    observed_meta_purchases: "Покупки Meta (не апрувы)",
                    approved_sales: "Подтверждённые продажи",
                    pending_sales: "Pending",
                    actual_cpl: "Фактический CPL",
                    target_cpl: "Целевой CPL",
                    maximum_cpl: "Максимальный CPL",
                    approved_cps: "CPS апрувов",
                    estimated_roi: "Прогнозный ROI",
                    actual_roi: "Фактический ROI",
                    minimum_roi: "Минимальный ROI",
                    applied_approval_percent: "Применённый апрув",
                  } as Record<string, string>
                )[k]
              }
            </dt>
            <dd>
              {formatMetric(
                card[k],
                k as import("../lib/metric-registry").MetricKey,
                card.currency,
              )}
            </dd>
          </div>
        ))}
      </dl>
      <p>
        Основа: {localized(card.economics_data_quality)} · апрув:{" "}
        {localized(card.approval_source)} · зрелость:{" "}
        {localized(card.maturity_status)} · завершённость окна:{" "}
        {card.window_complete ? "подтверждена" : "не подтверждена"}
      </p>
      <ConditionResults node={card.expression_result as Row} />
      <p>
        {(card.reason_codes as string[]).map(ruleLabel).join("; ") ||
          "Условия проверены по выбранным порогам."}
      </p>
      <p>
        Реальное действие: запрещено. Строгая пригодность Phase 2:{" "}
        {card.eligible_for_rule_evaluation ? "да" : "нет"}. Препятствия:{" "}
        {(card.future_action_blockers as string[]).map(ruleLabel).join("; ")}
      </p>
      <details>
        <summary>Применённые пороги и изменения с предыдущей проверкой</summary>
        <dl>
          {Object.entries(
            card.applied_thresholds as Record<
              string,
              { inherited: unknown; local: unknown; applied: unknown }
            >,
          ).map(([k, v]) => (
            <div key={k}>
              <dt>{thresholdNames[k as ThresholdKey]}</dt>
              <dd>
                Профиль: {String(v.inherited)}; локально:{" "}
                {String(v.local ?? "наследовать")}; применено:{" "}
                {String(v.applied)}
              </dd>
            </div>
          ))}
        </dl>
        {Object.entries(
          (card.changes_since_previous ?? {}) as Record<
            string,
            { before: unknown; after: unknown; delta: unknown }
          >,
        ).map(([k, v]) => (
          <p key={k}>
            {(
              {
                leads: "Лиды",
                observed_meta_purchases: "Покупки Meta",
                approved_sales: "Апрувы",
                rejected_sales: "Отклонено",
                pending_sales: "Pending",
                actual_cpl: "CPL",
                estimated_roi: "Прогнозный ROI",
                actual_roi: "Фактический ROI",
                profile_version: "Версия профиля",
                status: "Результат",
                applied_approval_rate: "Применённый апрув",
              } as Record<string, string>
            )[k] ?? k}
            :{" "}
            {k === "status"
              ? ruleLabel(v.before)
              : String(v.before ?? "неизвестно")}{" "}
            →{" "}
            {k === "status"
              ? ruleLabel(v.after)
              : String(v.after ?? "неизвестно")}
            {v.delta !== null ? ` (изменение ${v.delta})` : ""}
          </p>
        ))}
      </details>
    </article>
  );
}
