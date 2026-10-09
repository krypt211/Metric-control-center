"use client";
import { useEffect, useState } from "react";
import { formatMetric } from "../lib/column-model";
import { localized, type Profile } from "../lib/economics";
import { useColumnPreferences } from "../lib/use-column-preferences";
import {
  conditionNames,
  newRule,
  readRules,
  ruleLabel,
  ruleRow,
  thresholdNames,
  writeRules,
  type Definition,
  type History,
  type Row,
  type Rule,
  type Simulation,
  type ThresholdKey,
} from "../lib/smart-rules";
import ColumnManager from "./ColumnManager";
import StatisticsTable from "./StatisticsTable";
import RuleExpression from "./RuleExpression";

type Option = { id: string; name: string };
type Scopes = {
  options: Record<string, Option[]>;
  profiles: Profile[];
  templates: Definition[];
  can_edit: boolean;
  is_admin: boolean;
  operators: { id: string; login: string; can_edit: boolean }[];
};
const statuses = [
  "WOULD_PAUSE",
  "REVIEW",
  "KEEP",
  "INSUFFICIENT_DATA",
  "DATA_STALE",
];
function formatTime(value?: string) {
  return value ? new Date(value).toLocaleString("ru-RU") : "—";
}
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

export default function SmartRules() {
  const columns = useColumnPreferences("rule_ad");
  const [rules, setRules] = useState<Rule[]>([]),
    [scopes, setScopes] = useState<Scopes | null>(null),
    [active, setActive] = useState<Rule | null>(null),
    [draft, setDraft] = useState<Definition>(newRule),
    [history, setHistory] = useState<History | null>(null),
    [simulation, setSimulation] = useState<Simulation | null>(null),
    [cardId, setCardId] = useState(""),
    [statusFilter, setStatusFilter] = useState(""),
    [search, setSearch] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [message, setMessage] = useState("");
  async function load() {
    const [list, s] = await Promise.all([
      readRules<{ rules: Rule[] }>(),
      readRules<Scopes>("/available-scopes"),
    ]);
    setRules(list.rules);
    setScopes(s);
  }
  useEffect(() => {
    void load().catch((e) => setError(e.message));
  }, []);
  useEffect(() => {
    if (!active) {
      setHistory(null);
      return;
    }
    const c = new AbortController();
    void readRules<History>(`/${active.id}/history`, c.signal)
      .then(setHistory)
      .catch((e) => {
        if (!c.signal.aborted) setError(e.message);
      });
    return () => c.abort();
  }, [active?.id, active?.revision]);
  function choose(rule: Rule | null, definition?: Definition) {
    setActive(rule);
    setDraft(structuredClone(definition ?? rule?.definition ?? newRule()));
    setSimulation(null);
    setCardId("");
    setMessage("");
  }
  async function operate(fn: () => Promise<void>) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await fn();
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Не удалось выполнить операцию",
      );
    } finally {
      setBusy(false);
    }
  }
  function set<K extends keyof Definition>(key: K, value: Definition[K]) {
    setDraft((d) => ({ ...d, [key]: value }));
  }
  const canEdit = scopes?.can_edit ?? false,
    dirty =
      !active || JSON.stringify(active.definition) !== JSON.stringify(draft),
    profile = scopes?.profiles.find((p) => p.id === draft.profile_id),
    readyToRun = active && !active.deleted && !dirty;
  async function save() {
    const r = await writeRules<Rule>(
      active ? `/${active.id}` : "",
      active ? "PUT" : "POST",
      active ? { ...draft, revision: active.revision } : draft,
    );
    choose(r);
    await load();
    setMessage(`Правило сохранено · версия ${r.revision}`);
  }
  async function simulate() {
    if (!active) return;
    const result = await writeRules<Simulation>(
      `/${active.id}/simulate`,
      "POST",
      { version: active.revision },
    );
    setSimulation(result);
    setCardId("");
    setHistory(await readRules<History>(`/${active.id}/history`));
    await load();
    setMessage("DRY RUN завершён. Рекламные объявления не изменены.");
  }
  const filtered = (simulation?.rows ?? []).filter(
    (r) =>
      (!statusFilter || r.status === statusFilter) &&
      (!search ||
        `${r.name} ${r.id} ${r.external_id}`
          .toLocaleLowerCase("ru")
          .includes(search.toLocaleLowerCase("ru"))),
  );
  const flat = filtered.map(ruleRow),
    sort = columns.config.sorting;
  if (sort)
    flat.sort((a, b) => {
      const left = a[sort.key],
        right = b[sort.key];
      if (left == null || right == null)
        return left == null ? (right == null ? 0 : 1) : -1;
      const numeric =
        typeof left === "number" || /^-?\d+(\.\d+)?$/.test(String(left));
      const value = numeric
        ? Number(left) - Number(right)
        : String(left).localeCompare(String(right), "ru");
      return sort.direction === "asc" ? value : -value;
    });
  const card = simulation?.rows.find((r) => r.id === cardId) ?? filtered[0];
  return (
    <>
      <p className="notice">
        Только симуляция. DRY RUN. Рекламные объявления не изменяются. Уровень
        проверки: объявление (AD). Прогнозные покупки и апрувы не заменяют
        подтверждённые продажи.
      </p>
      {error && (
        <p role="alert" className="notice error">
          {error}
        </p>
      )}
      {message && (
        <p role="status" className="notice">
          {message}
        </p>
      )}
      {!scopes && !error && <p role="status">Загрузка правил…</p>}
      <section aria-label="Правила">
        <h2>Правила</h2>
        <div className="filters">
          <label>
            Открыть правило
            <select
              aria-label="Открыть правило"
              value={active?.id ?? ""}
              disabled={busy}
              onChange={(e) =>
                choose(rules.find((r) => r.id === e.target.value) ?? null)
              }
            >
              <option value="">Новое правило</option>
              {rules.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.definition.name} · v{r.revision}
                  {r.deleted ? " · архив" : ""}
                </option>
              ))}
            </select>
          </label>
          <button disabled={!canEdit || busy} onClick={() => choose(null)}>
            Создать правило
          </button>
          <label>
            Копировать системный шаблон
            <select
              value=""
              disabled={!canEdit || busy}
              onChange={(e) => {
                const t = scopes?.templates[Number(e.target.value)];
                if (t) choose(null, t);
              }}
            >
              <option value="">Выберите шаблон</option>
              {scopes?.templates.map((t, i) => (
                <option key={i} value={i}>
                  {t.name}
                </option>
              ))}
            </select>
          </label>
        </div>
        {active && (
          <p>
            Версия {active.revision} ·{" "}
            {active.deleted ? "Архив" : "Только симуляция"} · последний редактор{" "}
            {active.updated_by} · последняя проверка{" "}
            {formatTime(
              rules.find((r) => r.id === active.id)?.last_simulation_at,
            )}
          </p>
        )}
        <p className="card-note">
          Наборы независимы. Шаблоны не назначаются аккаунтам автоматически.
          Профиль ниже применяется явно в этом наборе; назначения Phase 2 не
          изменяются.
        </p>
      </section>
      <section aria-label="Конструктор">
        <h2>Конструктор</h2>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void operate(save);
          }}
        >
          <fieldset
            disabled={!canEdit || busy || !!active?.deleted}
            className="economic-fields"
          >
            <legend>Настройки набора</legend>
            <label>
              Название правила
              <input
                required
                maxLength={120}
                value={draft.name}
                onChange={(e) => set("name", e.target.value)}
              />
            </label>
            <label>
              Описание
              <textarea
                maxLength={1000}
                value={draft.description}
                onChange={(e) => set("description", e.target.value)}
              />
            </label>
            <label>
              Экономический профиль
              <select
                value={draft.profile_id ?? ""}
                onChange={(e) => set("profile_id", e.target.value || null)}
              >
                <option value="">
                  Назначения Phase 2 · без произвольного профиля
                </option>
                {scopes?.profiles.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} · {p.currency} · v{p.version}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Источник
              <select
                value={draft.selection.provider ?? ""}
                onChange={(e) =>
                  set("selection", {
                    ...draft.selection,
                    provider: (e.target.value ||
                      null) as Definition["selection"]["provider"],
                  })
                }
              >
                <option value="">Маршрутизация по аккаунтам</option>
                <option value="metricflow">MetricFlow</option>
                <option value="meta">
                  Meta · только подключённые сохранённые данные
                </option>
              </select>
            </label>
            <fieldset className="rule-accounts">
              <legend>Рекламные аккаунты · пусто = все</legend>
              {scopes?.options.account?.map((a) => (
                <label key={a.id}>
                  <input
                    type="checkbox"
                    checked={draft.selection.account_ids.includes(a.id)}
                    onChange={(e) =>
                      set("selection", {
                        ...draft.selection,
                        account_ids: e.target.checked
                          ? [...draft.selection.account_ids, a.id]
                          : draft.selection.account_ids.filter(
                              (id) => id !== a.id,
                            ),
                      })
                    }
                  />
                  {a.name}
                </label>
              ))}
            </fieldset>
            {(["campaign", "adset", "ad", "offer", "geo"] as const).map(
              (key) => (
                <label key={key}>
                  {
                    {
                      campaign: "Кампания",
                      adset: "Группа объявлений",
                      ad: "Объявление",
                      offer: "Оффер",
                      geo: "GEO",
                    }[key]
                  }
                  <select
                    value={draft.selection[key] ?? ""}
                    onChange={(e) =>
                      set("selection", {
                        ...draft.selection,
                        [key]: e.target.value || null,
                      })
                    }
                  >
                    <option value="">Все доступные</option>
                    {scopes?.options[key]?.map((o) => (
                      <option key={o.id} value={o.id}>
                        {o.name}
                      </option>
                    ))}
                  </select>
                </label>
              ),
            )}
            <label>
              Статус объявления
              <select
                value={draft.selection.status ?? ""}
                onChange={(e) =>
                  set("selection", {
                    ...draft.selection,
                    status: (e.target.value ||
                      null) as Definition["selection"]["status"],
                  })
                }
              >
                <option value="">Любой подтверждённый</option>
                <option value="ACTIVE">Активно</option>
                <option value="PAUSED">Остановлено</option>
              </select>
            </label>
            <label>
              Период оценки
              <select
                value={draft.period}
                onChange={(e) =>
                  set("period", e.target.value as Definition["period"])
                }
              >
                <option value="last_7">7 завершённых дней</option>
                <option value="today">Сегодня · неполный день</option>
                <option value="yesterday">Вчера</option>
                <option value="last_3">3 завершённых дня</option>
                <option value="last_14">14 завершённых дней</option>
                <option value="last_30">30 завершённых дней</option>
                <option value="custom">Свой период · максимум 31 день</option>
              </select>
            </label>
            {draft.period === "custom" && (
              <>
                <label>
                  Начало периода
                  <input
                    type="date"
                    required
                    value={draft.start ?? ""}
                    onChange={(e) => set("start", e.target.value)}
                  />
                </label>
                <label>
                  Конец периода
                  <input
                    type="date"
                    required
                    value={draft.end ?? ""}
                    onChange={(e) => set("end", e.target.value)}
                  />
                </label>
              </>
            )}
            <label>
              Действует с
              <input
                type="date"
                value={draft.effective_start ?? ""}
                onChange={(e) => set("effective_start", e.target.value || null)}
              />
            </label>
            <label>
              Действует до
              <input
                type="date"
                value={draft.effective_end ?? ""}
                onChange={(e) => set("effective_end", e.target.value || null)}
              />
            </label>
            <label>
              Политика прогнозных сигналов
              <select
                value={draft.estimated_policy}
                onChange={(e) =>
                  set(
                    "estimated_policy",
                    e.target.value as Definition["estimated_policy"],
                  )
                }
              >
                <option value="review">Прогноз → требуется проверка</option>
                <option value="allow_simulated">
                  Допускать прогнозного кандидата в симуляции
                </option>
              </select>
            </label>
            <p className="card-note">
              Europe/Moscow — календарь отчёта; timezone кабинета видна в
              результате. Сегодня всегда требует проверки полноты. UNKNOWN
              остаётся неизвестным даже в OR. Реальное выполнение всегда
              запрещено.
            </p>
            <fieldset className="rule-thresholds">
              <legend>Минимальные пороги · пусто = наследовать профиль</legend>
              {(Object.entries(thresholdNames) as [ThresholdKey, string][]).map(
                ([k, title]) => {
                  const inherited = profile
                    ? k === "minimum_approved_sales"
                      ? profile.sale_threshold_type === "approved"
                        ? profile.minimum_sales
                        : 0
                      : (profile[k as keyof Profile] ?? 0)
                    : "назначение объявления";
                  return (
                    <label key={k}>
                      {title}
                      <input
                        inputMode={
                          k === "minimum_spend" ? "decimal" : "numeric"
                        }
                        value={draft.thresholds[k] ?? ""}
                        onChange={(e) =>
                          set("thresholds", {
                            ...draft.thresholds,
                            [k]:
                              e.target.value === ""
                                ? null
                                : k === "minimum_spend"
                                  ? e.target.value
                                  : Number(e.target.value),
                          })
                        }
                      />
                      <small>
                        Профиль: {String(inherited)}; локально:{" "}
                        {String(draft.thresholds[k] ?? "наследовать")};
                        применяется: {String(draft.thresholds[k] ?? inherited)}
                      </small>
                    </label>
                  );
                },
              )}
              <p className="card-note">
                Расход без лидов использует свой порог и не требует минимального
                числа лидов. Пороги апрувов применяются к условиям о
                подтверждённых продажах. Ни один порог не ослабляет строгий
                допуск Phase 2.
              </p>
            </fieldset>
            <RuleExpression
              value={draft.expression}
              change={(next) => set("expression", next)}
            />
            <button type="submit">Сохранить правило</button>
          </fieldset>
        </form>
        {active && (
          <div className="filters">
            <button
              disabled={!canEdit || busy}
              onClick={() =>
                void operate(async () => {
                  const copied = await writeRules<Rule>(
                    `/${active.id}/copy`,
                    "POST",
                    { version: active.revision },
                  );
                  choose(copied);
                  await load();
                  setMessage("Копия создана");
                })
              }
            >
              Дублировать правило
            </button>
            <button
              disabled={!canEdit || busy || active.deleted}
              onClick={() =>
                void operate(async () => {
                  const r = await writeRules<Rule>(`/${active.id}`, "DELETE", {
                    version: active.revision,
                  });
                  choose(r);
                  await load();
                  setMessage("Правило архивировано");
                })
              }
            >
              Архивировать правило
            </button>
            <button
              disabled={!canEdit || busy || !active.deleted}
              onClick={() =>
                void operate(async () => {
                  const r = await writeRules<Rule>(
                    `/${active.id}/restore`,
                    "POST",
                    {
                      version: active.revision,
                      restore_version: Math.max(1, active.revision - 1),
                    },
                  );
                  choose(r);
                  await load();
                  setMessage("Правило восстановлено");
                })
              }
            >
              Восстановить правило
            </button>
          </div>
        )}
        {!canEdit && (
          <p className="notice">
            Просмотр. Редактирование и создание симуляций доступны
            администратору или оператору с отдельным разрешением.
          </p>
        )}
      </section>
      <section aria-label="Симуляция" className="statistics-grid">
        <h2>Симуляция</h2>
        <button
          disabled={!canEdit || busy || !readyToRun}
          onClick={() => void operate(simulate)}
        >
          {busy ? "Проверка…" : "Проверить правила"}
        </button>
        {dirty && active && <p>Сохраните изменения перед проверкой.</p>}
        {simulation && (
          <>
            <p>
              DRY RUN · версия правила {simulation.rule_revision} ·{" "}
              {simulation.start} — {simulation.end} · Europe/Moscow ·{" "}
              {formatTime(simulation.created_at)} · проверено {simulation.total}{" "}
              · без профиля {simulation.missing_profiles}
            </p>
            <div className="rule-counts">
              {statuses.map((s) => (
                <span key={s} className={`rule-badge rule-${s}`}>
                  {ruleLabel(s)}: {simulation.counts[s] ?? 0}
                </span>
              ))}
            </div>
            <div className="filters">
              <label>
                Результат проверки
                <select
                  value={statusFilter}
                  onChange={(e) => setStatusFilter(e.target.value)}
                >
                  <option value="">Все</option>
                  {statuses.map((s) => (
                    <option value={s} key={s}>
                      {ruleLabel(s)}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Поиск объявления
                <input
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Название или ID"
                />
              </label>
            </div>
            <ColumnManager scope="rule_ad" controller={columns} rows={flat} />
            <StatisticsTable
              scope="rule_ad"
              rows={flat}
              config={columns.config}
              change={columns.change}
              commit={() => void columns.persist().catch(() => {})}
              disabled={!columns.ready || columns.busy}
              onName={(r) => setCardId(String(r.id))}
            />
            {card && (
              <article className="rule-details" aria-label="Объяснение решения">
                <h3>
                  {String(card.name)} ·{" "}
                  <span className={`rule-badge rule-${card.status}`}>
                    {ruleLabel(card.status)}
                  </span>
                </h3>
                <p>
                  Объявление: {String(card.external_id ?? card.id)} · аккаунт:{" "}
                  {String(card.account_name)} · кампания:{" "}
                  {String(card.campaign ?? "—")} · группа:{" "}
                  {String(card.adset ?? "—")}
                </p>
                <p>
                  Профиль: {String(card.profile_name ?? "не назначен")} · v
                  {String(card.profile_version ?? "—")} · период:{" "}
                  {String(card.period_start)} — {String(card.period_end)} ·
                  timezone кабинета: {String(card.timezone)} · источник:{" "}
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
                              observed_meta_purchases:
                                "Покупки Meta (не апрувы)",
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
                  {card.eligible_for_rule_evaluation ? "да" : "нет"}.
                  Препятствия:{" "}
                  {(card.future_action_blockers as string[])
                    .map(ruleLabel)
                    .join("; ")}
                </p>
                <details>
                  <summary>
                    Применённые пороги и изменения с предыдущей проверкой
                  </summary>
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
            )}
          </>
        )}
      </section>
      <section aria-label="История проверок">
        <h2>История проверок</h2>
        {history && (
          <>
            <h3>Сохранённые симуляции</h3>
            <ul>
              {history.simulations.map((run) => (
                <li key={run.id}>
                  <button
                    disabled={busy}
                    onClick={() =>
                      void operate(async () => {
                        setSimulation(
                          await readRules<Simulation>(`/simulations/${run.id}`),
                        );
                        setCardId("");
                      })
                    }
                  >
                    Открыть проверку {formatTime(run.created_at)} · правило v
                    {run.rule_revision} · {run.total} объявлений
                  </button>
                </li>
              ))}
            </ul>
            <h3>Версии правила</h3>
            <ul>
              {history.versions.map((v) => (
                <li key={v.revision}>
                  v{v.revision} · {formatTime(v.at)} ·{" "}
                  {v.snapshot.definition.name}
                  <button
                    disabled={
                      !canEdit || busy || v.revision === active?.revision
                    }
                    onClick={() =>
                      void operate(async () => {
                        if (!active) return;
                        const r = await writeRules<Rule>(
                          `/${active.id}/restore`,
                          "POST",
                          {
                            version: active.revision,
                            restore_version: v.revision,
                          },
                        );
                        choose(r);
                        await load();
                        setMessage(
                          "Старая конфигурация восстановлена новой версией",
                        );
                      })
                    }
                  >
                    Вернуться к версии {v.revision}
                  </button>
                </li>
              ))}
            </ul>
            <details>
              <summary>Аудит</summary>
              {history.audit.map((v, i) => (
                <p key={i}>
                  {formatTime(v.at)} · {ruleLabel(v.event)} · {v.actor_id}
                </p>
              ))}
            </details>
          </>
        )}
        {!active && (
          <p>
            Откройте сохранённое правило, чтобы просмотреть версии и проверки.
          </p>
        )}
      </section>
      <section aria-label="Настройки безопасности">
        <h2>Настройки безопасности</h2>
        <p>
          DRY RUN · действия запрещены · AI отключён. Лимит: 500 объявлений, до
          31 дня, до 10 секунд вычисления. Симуляции не создают запросы в Action
          Engine. Для будущего выполнения потребуется новая проверка прав,
          состояния и свежести.
        </p>
        {scopes?.is_admin && (
          <fieldset disabled={busy}>
            <legend>Отдельное разрешение операторов на правила</legend>
            {scopes.operators.map((u) => (
              <label key={u.id}>
                <input
                  type="checkbox"
                  checked={u.can_edit}
                  onChange={(e) =>
                    void operate(async () => {
                      await writeRules("/grants", "PUT", {
                        user_id: u.id,
                        can_edit: e.target.checked,
                      });
                      await load();
                      setMessage("Права оператора обновлены");
                    })
                  }
                />
                {u.login}
              </label>
            ))}
          </fieldset>
        )}
      </section>
    </>
  );
}
