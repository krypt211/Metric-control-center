"use client";
import { useEffect, useState } from "react";
import { readRules, ruleLabel, type Simulation } from "../lib/smart-rules";
import { useColumnPreferences } from "../lib/use-column-preferences";
import {
  prioritizedRules,
  recommendationRows,
  recheckNames,
  reviewStatuses,
  type RecommendationSummary,
  type RecommendationItem,
} from "../lib/rule-recommendations";
import ColumnManager from "./ColumnManager";
import StatisticsTable from "./StatisticsTable";
import RuleDecisionDetails from "./RuleDecisionDetails";

function time(value: string | null) {
  return value
    ? new Date(value).toLocaleString("ru-RU", { timeZone: "Europe/Moscow" })
    : "—";
}

export default function RuleRecommendations() {
  const columns = useColumnPreferences("rule_ad");
  const [data, setData] = useState<RecommendationSummary | null>(null);
  const [active, setActive] = useState<RecommendationItem | null>(null);
  const [simulation, setSimulation] = useState<Simulation | null>(null);
  const [offset, setOffset] = useState(0),
    [refresh, setRefresh] = useState(0);
  const [status, setStatus] = useState(""),
    [search, setSearch] = useState("");
  const [ruleSearch, setRuleSearch] = useState(""),
    [cardId, setCardId] = useState("");
  const [busy, setBusy] = useState(true),
    [loadingRun, setLoadingRun] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    setBusy(true);
    setError("");
    readRules<RecommendationSummary>(
      `/recommendations?offset=${offset}`,
      controller.signal,
    )
      .then((result) => {
        if (!controller.signal.aborted) setData(result);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setBusy(false);
      });
    return () => controller.abort();
  }, [offset, refresh]);
  useEffect(() => {
    const controller = new AbortController();
    setSimulation(null);
    setCardId("");
    setError("");
    if (!active?.simulation_id) {
      setLoadingRun(false);
      return;
    }
    setLoadingRun(true);
    readRules<Simulation>(
      `/simulations/${active.simulation_id}`,
      controller.signal,
    )
      .then((run) => {
        if (!controller.signal.aborted) setSimulation(run);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoadingRun(false);
      });
    return () => controller.abort();
  }, [active?.simulation_id]);
  useEffect(() => {
    if (data)
      setActive((previous) =>
        previous
          ? (data.rows.find((row) => row.rule_id === previous.rule_id) ?? null)
          : null,
      );
  }, [data]);
  const items = prioritizedRules(data?.rows ?? []).filter((item) =>
    item.name
      .toLocaleLowerCase("ru")
      .includes(ruleSearch.toLocaleLowerCase("ru")),
  );
  const rows = recommendationRows(
    simulation?.rows ?? [],
    status,
    search,
    columns.config.sorting,
  );
  const selected =
    simulation?.rows.find((row) => row.id === cardId) ??
    simulation?.rows.find((row) => row.id === rows[0]?.id);
  return (
    <>
      <p className="notice">
        Сохранённые результаты DRY RUN. Реклама не изменяется. Исторический
        сигнал не является разрешением на действие. Новые факты учитываются
        только при новой проверке правила.
      </p>
      {error && (
        <p className="notice error" role="alert">
          {error}
        </p>
      )}
      <div className="filters">
        <button
          disabled={busy}
          onClick={() => setRefresh((value) => value + 1)}
        >
          {busy ? "Загрузка…" : "Обновить сводку"}
        </button>
        <a href="/rules">Создать или проверить правило</a>
      </div>
      <section aria-label="Сводка рекомендаций">
        <h2>Последние сохранённые проверки</h2>
        <p>
          Активных наборов: {data?.total_rules ?? "—"}. Счётчики относятся к
          текущей странице наборов. Одно объявление может учитываться в
          нескольких правилах; расходы и результаты разных правил не
          суммируются.
        </p>
        <div className="rule-counts">
          {reviewStatuses.map((key) => (
            <span key={key} className={`rule-badge rule-${key}`}>
              {ruleLabel(key)}: {data?.counts[key] ?? "—"}
            </span>
          ))}
        </div>
        <p className="table-note">
          Обновлено: {time(data?.as_of ?? null)} · Europe/Moscow. Сначала
          показаны наборы, требующие повторной проверки, затем кандидаты и
          предварительные сигналы. Отсутствие предупреждения не подтверждает
          актуальность рекламных данных.
        </p>
        <label>
          Поиск правила
          <input
            value={ruleSearch}
            onChange={(event) => setRuleSearch(event.target.value)}
          />
        </label>
        <div className="recommendation-list">
          {items.map((item) => (
            <article className="actionpanel" key={item.rule_id}>
              <h3>{item.name}</h3>
              <p>
                Правило v{item.rule_revision} · проверка{" "}
                {item.simulation_revision
                  ? `v${item.simulation_revision}`
                  : "не запускалась"}{" "}
                · {time(item.created_at)}
              </p>
              {item.start && (
                <p>
                  Период: {item.start} — {item.end} · объявлений: {item.total}
                </p>
              )}
              {!!item.recheck_reasons.length && (
                <p className="notice">
                  Нужна проверка:{" "}
                  {item.recheck_reasons
                    .map((reason) => recheckNames[reason] ?? reason)
                    .join("; ")}
                </p>
              )}
              <div className="rule-counts">
                {reviewStatuses
                  .filter((key) => item.counts[key])
                  .map((key) => (
                    <span key={key} className={`rule-badge rule-${key}`}>
                      {ruleLabel(key)}: {item.counts[key]}
                    </span>
                  ))}
              </div>
              <div className="filters">
                <button
                  disabled={!item.simulation_id || loadingRun}
                  onClick={() => {
                    setActive(item);
                    setStatus("");
                    setSearch("");
                  }}
                >
                  Открыть результаты: {item.name}
                </button>
                <a href={`/rules?rule=${item.rule_id}`}>
                  Правило и история: {item.name}
                </a>
              </div>
            </article>
          ))}
        </div>
        {!busy && !items.length && (
          <div className="empty">
            <h3>
              {data?.total_rules
                ? "Правила не найдены"
                : "Нет сохранённых правил"}
            </h3>
            <p>
              Создайте правило и выполните DRY RUN. Демонстрационные
              рекомендации здесь не создаются.
            </p>
          </div>
        )}
        <div className="pagination">
          <button
            disabled={!offset || busy}
            onClick={() => {
              setActive(null);
              setOffset(Math.max(0, offset - 50));
            }}
          >
            Предыдущие наборы
          </button>
          <button
            disabled={data?.next_offset == null || busy}
            onClick={() => {
              setActive(null);
              setOffset(data!.next_offset!);
            }}
          >
            Следующие наборы
          </button>
        </div>
      </section>
      <section className="statistics-grid" aria-label="Результаты рекомендаций">
        <h2>{active ? `Объявления · ${active.name}` : "Объявления"}</h2>
        {loadingRun && <p role="status">Загрузка сохранённой проверки…</p>}
        {simulation && (
          <>
            <p>
              Историческая симуляция {time(simulation.created_at)} · правило v
              {simulation.rule_revision} · {simulation.start} — {simulation.end}
            </p>
            {!!active?.recheck_reasons.length && (
              <p className="notice">
                Этот результат требует повторной проверки. Сохранённые решения
                показаны без изменений.
              </p>
            )}
            <div className="filters">
              <label>
                Результат проверки
                <select
                  value={status}
                  onChange={(event) => {
                    setStatus(event.target.value);
                    setCardId("");
                  }}
                >
                  <option value="">Все</option>
                  {reviewStatuses.map((key) => (
                    <option key={key} value={key}>
                      {ruleLabel(key)}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Поиск объявления
                <input
                  placeholder="Название или ID"
                  value={search}
                  onChange={(event) => {
                    setSearch(event.target.value);
                    setCardId("");
                  }}
                />
              </label>
            </div>
            <p>
              Показано объявлений: {rows.length} из {simulation.total}
            </p>
            <ColumnManager scope="rule_ad" controller={columns} rows={rows} />
            <StatisticsTable
              scope="rule_ad"
              rows={rows}
              config={columns.config}
              change={columns.change}
              commit={() => void columns.persist().catch(() => {})}
              disabled={!columns.ready || columns.busy}
              onName={(row) => setCardId(String(row.id))}
            />
            {selected && <RuleDecisionDetails card={selected} simulationId={simulation.id} />}
            {!rows.length && <p>Нет объявлений по выбранному фильтру.</p>}
          </>
        )}
        {!active && (
          <p>
            Откройте результаты нужного набора. Решения разных правил могут
            различаться; каждый набор сохраняет свой профиль, период и пороги.
          </p>
        )}
      </section>
    </>
  );
}
