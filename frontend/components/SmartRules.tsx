"use client";
import { useEffect, useState } from "react";
import { type Profile } from "../lib/economics";
import { useColumnPreferences } from "../lib/use-column-preferences";
import {
  newRule,
  conditionNames,
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
import RuleDecisionDetails from "./RuleDecisionDetails";
import RuleTargetPicker from "./RuleTargetPicker";
import RuleTargetActions from "./RuleTargetActions";
import SearchableSelect from "./SearchableSelect";
import {targetSummary,type Target} from "../lib/rule-targets";

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
  "WOULD_ENABLE",
  "NOTIFY",
  "REVIEW",
  "KEEP",
  "INSUFFICIENT_DATA",
  "DATA_STALE",
];
function formatTime(value?: string) {
  return value ? new Date(value).toLocaleString("ru-RU") : "—";
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
    void load()
      .then(async () => {
        const id = new URLSearchParams(window.location.search).get("rule");
        if (id && /^[a-f0-9-]{36}$/.test(id))
          choose(await readRules<Rule>(`/${id}`));
      })
      .catch((e) => setError(e.message));
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
  function chooseTargets(items: Target[]) {
    setDraft(d=>({...d,selection:{...d.selection,target_mode:true,targets:items,
      account_ids:[],campaign:null,adset:null,ad:null}}));
  }
  useEffect(()=>{
    const saved=sessionStorage.getItem("mcc.rule-target-draft");
    if(!saved)return;
    sessionStorage.removeItem("mcc.rule-target-draft");
    try {chooseTargets(JSON.parse(saved));} catch {setError("Не удалось восстановить выбор");}
  },[]);
  useEffect(()=>{
    function warn(e:BeforeUnloadEvent){if(canEdit&&dirty){e.preventDefault();e.returnValue="";}}
    window.addEventListener("beforeunload",warn);
    return()=>window.removeEventListener("beforeunload",warn);
  });
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
      active?JSON.stringify(active.definition) !== JSON.stringify(draft):JSON.stringify(newRule())!==JSON.stringify(draft),
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
      {!!(simulation as Simulation & {target_issues?:{reason_code:string}[]}|null)?.target_issues?.length&&
        <p role="alert">Область не разрешена полностью: {(simulation as Simulation & {target_issues:{reason_code:string}[]}).target_issues.map(i=>i.reason_code).join(" · ")}</p>}
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
                  {r.definition.name} · v{r.revision} · {targetSummary(r.definition.selection.targets??[])}
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
      {!!draft.selection.targets?.length&&<RuleTargetActions refreshKey={rules.map(r=>r.id+":"+r.revision).join(",")} targets={draft.selection.targets} onChange={chooseTargets}
        onSaved={r=>{if(active?.id===r.id)choose(r);void load();}}
        onCreate={items=>{choose(null);setDraft({...newRule(),selection:{...newRule().selection,target_mode:true,targets:items}});}}/>}
      {active&&<p>Применяется к: {active.definition.selection.target_mode?targetSummary(active.definition.selection.targets??[]):"сохранённая область Phase 3"}</p>}
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
            <label>Действие правила<select value={draft.action ?? "PAUSE_AD"} onChange={e=>set("action", e.target.value as Definition["action"])}>
              <option value="PAUSE_AD">PAUSE — отключение</option><option value="ENABLE_AD">ENABLE — включение</option><option value="NOTIFY_ONLY">NOTIFY — уведомление</option>
            </select></label>
            <label><input type="checkbox" checked={draft.enabled ?? false} onChange={e=>set("enabled", e.target.checked)}/>Проверять правило каждые 30 минут · только DRY RUN</label>
            <label>Приоритет правила<input type="number" min={0} max={100} value={draft.priority ?? 0} onChange={e=>set("priority",Number(e.target.value))}/></label>
            <label>Cooldown, секунд<input type="number" min={1800} max={604800} value={draft.cooldown_seconds ?? 3600} onChange={e=>set("cooldown_seconds",Number(e.target.value))}/></label>
            {draft.action === "ENABLE_AD" && <label><input type="checkbox" checked={draft.allow_reenable ?? false} onChange={e=>set("allow_reenable",e.target.checked)}/>Разрешить проверку повторного включения · дополнительно нужны разрешение на AD, подтверждённое отключение нашей системой и активные родители</label>}
            <p>Timezone: {scopes?.profiles.find(p=>p.id===draft.profile_id)?.timezone ?? "Europe/Moscow"}. Включение проверок не разрешает рекламные WRITE.</p>

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
            <RuleTargetPicker value={draft.selection.targets??[]} onChange={chooseTargets} disabled={!canEdit||busy}/>
            {!draft.selection.target_mode&&<p>Ранее сохранённая область: {draft.selection.account_ids.length} кабинетов
              {draft.selection.campaign?" · кампания "+draft.selection.campaign:""}
              {draft.selection.adset?" · группа "+draft.selection.adset:""}
              {draft.selection.ad?" · AD "+draft.selection.ad:""}.
              Пустая прежняя область означает все доступные Ads. Явный выбор заменит эту область при сохранении.</p>}
            {(["offer","geo"] as const).map(key=><label key={key}>{key==="offer"?"Оффер":"GEO"}
              <select value={draft.selection[key]??""} onChange={e=>set("selection",{...draft.selection,[key]:e.target.value||null})}>
               <option value="">Все доступные</option>{scopes?.options[key]?.map(o=><option key={o.id} value={o.id}>{o.name}</option>)}
              </select></label>)}
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
                        aria-label={title}
                        aria-describedby={`rule-threshold-help-${k}`}
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
                      <small id={`rule-threshold-help-${k}`}>
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
            {card && <RuleDecisionDetails card={card} simulationId={simulation.id} />}
          </>
        )}
      </section>
      <section id="history" aria-label="История проверок">
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
                  {v.notification && <span> · {String(v.notification.object)} · {String(v.notification.rule)} · {String(v.notification.decision)} · {Array.isArray(v.notification.metrics) ? (v.notification.metrics as Row[]).map(m=>(conditionNames[m.type as keyof typeof conditionNames] ?? String(m.type))+": "+String(m.value ?? "неизвестно")+"; порог "+String(m.threshold ?? "неизвестно")).join(" · ") : ""} · <a href={String(v.notification.history_url)}>История уведомления</a></span>}
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
