"use client";
import { useCallback, useEffect, useState } from "react";

type Condition = {metric: string; operator: string; value: string};
type Definition = {name: string; level: string; window: string; currency: string; timezone: string; account_ids: string[]; conditions: Condition[]; operation: {kind: string; value?: string | null}; max_budget: string | null; cooldown_seconds: number; interval_seconds: number; minimum_events: number; schedule_start: string; schedule_end: string};
type Rule = {id: string; mode: string; revision: number; definition: Definition};
type Run = {id: string; at: string; status: string; action_status: string | null; details: {entity_name?: string; metrics?: Record<string, string | number | null>; before?: {budget?: string; status?: string}; action?: string; value?: string; reason?: string}};
const metrics = ["spend", "conversions", "roi", "leads", "sales", "revenue", "profit", "clicks", "impressions", "ctr", "cpc", "cpm", "cpl", "cpa", "cr", "epc"];
const results: Record<string, string> = {would_act: "DRY RUN · предложено", queued: "В очереди", no_match: "Условия не выполнены", stale_metrics: "Устаревшая статистика", unknown_metrics: "Недостаточно данных", cooldown: "Cooldown", rejected: "Отклонено", account_units_mismatch: "Валюта или часовой пояс не совпадают"};
function initial(stop = false): Definition { return {name: stop ? "Stop Without Conversions" : "Scale Winner", level: "adset", window: "today", currency: "USD", timezone: "Europe/Moscow", account_ids: [],
  conditions: stop ? [{metric: "spend", operator: ">=", value: "20"}, {metric: "conversions", operator: "=", value: "0"}] : [{metric: "roi", operator: ">=", value: "100"}, {metric: "conversions", operator: ">=", value: "5"}, {metric: "spend", operator: ">=", value: "50"}],
  operation: stop ? {kind: "pause"} : {kind: "budget_change", value: "20"}, max_budget: stop ? null : "300", cooldown_seconds: 28800, interval_seconds: 300, minimum_events: 0, schedule_start: "00:00", schedule_end: "00:00"}; }

export default function Rules({refreshKey}: {refreshKey: number}) {
  const [rules, setRules] = useState<Rule[]>([]);
  const [definition, setDefinition] = useState<Definition>(initial());
  const [mode, setMode] = useState("DRY_RUN");
  const [editing, setEditing] = useState<Rule | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [runRule, setRunRule] = useState<Rule | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    try {const response = await fetch("/api/automation/rules", {cache: "no-store"}); const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Правила недоступны");
      setRules(data.rules); setError("");
    } catch (cause) {setError(cause instanceof Error ? cause.message : "Правила недоступны");}
  }, []);
  useEffect(() => {void load();}, [load, refreshKey]);
  const history = useCallback(async (rule: Rule) => {
    setRunRule(rule);
    try {const response = await fetch(`/api/automation/rules/${rule.id}/runs`, {cache: "no-store"});
      if (!response.ok) throw new Error("Журнал правил недоступен"); setRuns((await response.json()).runs);
    } catch (cause) {setError(cause instanceof Error ? cause.message : "Журнал недоступен");}
  }, []);
  useEffect(() => {if (!runRule) return; const timer = setInterval(() => void history(runRule), 5000); return () => clearInterval(timer);}, [runRule, history]);
  function change<K extends keyof Definition>(key: K, value: Definition[K]) {setDefinition(previous => ({...previous, [key]: value}));}
  async function save() {
    if (mode === "ACTIVE" && !window.confirm("Включить ACTIVE? Подходящие объекты будут изменяться через Action Engine с заданным cooldown и лимитами.")) return;
    setBusy(true); setMessage("");
    let key = sessionStorage.getItem("acc.pending-rule-key");
    if (!editing && !key) {key = crypto.randomUUID(); sessionStorage.setItem("acc.pending-rule-key", key);}
    try {
      const response = await fetch(`/api/automation/rules${editing ? `/${editing.id}` : ""}`, {method: editing ? "PUT" : "POST", headers: {"Content-Type": "application/json", "Idempotency-Key": key ?? ""},
        body: JSON.stringify({definition, mode, ...(editing ? {revision: editing.revision} : {})})});
      const data = await response.json();
      if (response.status < 500) sessionStorage.removeItem("acc.pending-rule-key");
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Проверьте параметры правила");
      setEditing(data); setMessage(`Сохранено · ${data.mode}`); await load();
    } catch (cause) {setMessage(cause instanceof Error ? cause.message : "Сохранение не подтверждено");}
    finally {setBusy(false);}
  }
  async function evaluate(rule: Rule) {
    setBusy(true);
    try {const response = await fetch(`/api/automation/rules/${rule.id}/evaluate`, {method: "POST", headers: {"Content-Type": "application/json"}, body: "{}"});
      const data = await response.json(); if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Запуск недоступен");
      setMessage(data.status === "evaluated" ? `Проверено объектов: ${data.decisions}` : data.status === "outside_schedule" ? "Сейчас вне расписания" : "Правило выключено или интервал проверки ещё не прошёл"); await history(rule); await load();
    } catch (cause) {setMessage(cause instanceof Error ? cause.message : "Запуск недоступен");} finally {setBusy(false);}
  }
  return <section>
    {error && <div className="notice error" role="alert">{error}</div>}
    <p className="table-note">OFF отключает проверки. DRY RUN сохраняет предложения. ACTIVE создаёт команды на изменение рекламы. Пропущенные показатели не считаются нулём.</p>
    <div className="tablewrap"><table><thead><tr><th>Правило</th><th>Режим</th><th>Действие</th><th>Cooldown</th><th /></tr></thead><tbody>
      {rules.map(rule => <tr key={rule.id}><td>{rule.definition.name}<small>{rule.definition.level} · {rule.definition.window} · {rule.definition.currency}</small></td><td>{rule.mode}</td><td>{rule.definition.operation.kind} {rule.definition.operation.value}</td><td>{rule.definition.cooldown_seconds / 3600} ч</td><td><button onClick={() => {setEditing(rule); setDefinition(rule.definition); setMode(rule.mode);}}>Изменить</button> <button onClick={() => void history(rule)}>Журнал</button> <button disabled={busy || rule.mode === "OFF"} onClick={() => void evaluate(rule)}>Проверить</button></td></tr>)}
      {!rules.length && <tr><td colSpan={5} className="empty-cell">Правила ещё не созданы</td></tr>}
    </tbody></table></div>
    <div className="actionpanel"><h2>{editing ? `Изменить: ${editing.definition.name}` : "Новое правило"}</h2>
      <div className="actionbuttons"><button disabled={busy} onClick={() => {setEditing(null); setDefinition(initial()); setMode("DRY_RUN");}}>Scale Winner</button><button disabled={busy} onClick={() => {setEditing(null); setDefinition(initial(true)); setMode("DRY_RUN");}}>Остановить без конверсий</button></div>
      <div className="filterbar"><label>Название<input value={definition.name} onChange={event => change("name", event.target.value)} maxLength={128} /></label>
        <label>Режим<select value={mode} onChange={event => setMode(event.target.value)}>{["OFF", "DRY_RUN", "ACTIVE"].map(value => <option key={value}>{value}</option>)}</select></label>
        <label>Уровень<select value={definition.level} onChange={event => change("level", event.target.value)}><option value="adset">Ad Set</option><option value="campaign">Campaign</option><option value="ad">Ad</option></select></label>
        <label>Период<select value={definition.window} onChange={event => change("window", event.target.value)}>{["today", "yesterday", "last3", "last7", "last14", "last30"].map(value => <option key={value}>{value}</option>)}</select></label>
        <label>Валюта<input value={definition.currency} maxLength={3} onChange={event => change("currency", event.target.value.toUpperCase())} /></label>
        <label>Часовой пояс<input value={definition.timezone} onChange={event => change("timezone", event.target.value)} /></label>
        <label>Cooldown, ч<input type="number" min="0.017" max="168" step="0.5" value={definition.cooldown_seconds / 3600} onChange={event => change("cooldown_seconds", Math.round(Number(event.target.value) * 3600))} /></label>
        <label>Проверять каждые, мин<input type="number" min="1" max="1440" value={definition.interval_seconds / 60} onChange={event => change("interval_seconds", Math.round(Number(event.target.value) * 60))} /></label>
        <label>Минимум конверсий<input type="number" min="0" value={definition.minimum_events} onChange={event => change("minimum_events", Number(event.target.value))} /></label>
        <label>Расписание с<input type="time" value={definition.schedule_start} onChange={event => change("schedule_start", event.target.value)} /></label><label>До<input type="time" value={definition.schedule_end} onChange={event => change("schedule_end", event.target.value)} /></label>
      </div>
      <p className="table-note">Одинаковое время начала и конца означает весь день. Правило действует на кабинеты с выбранной валютой и часовым поясом.</p>
      <h3>Все условия должны выполняться</h3>
      {definition.conditions.map((condition, index) => <div className="actionbuttons" key={index}><select aria-label={`Показатель ${index + 1}`} value={condition.metric} onChange={event => change("conditions", definition.conditions.map((item, n) => n === index ? {...item, metric: event.target.value} : item))}>{metrics.map(metric => <option key={metric}>{metric}</option>)}</select>
        <select aria-label={`Сравнение ${index + 1}`} value={condition.operator} onChange={event => change("conditions", definition.conditions.map((item, n) => n === index ? {...item, operator: event.target.value} : item))}>{[">=", ">", "<=", "<", "=", "!="].map(operator => <option key={operator}>{operator}</option>)}</select>
        <input aria-label={`Порог ${index + 1}`} type="number" step="any" value={condition.value} onChange={event => change("conditions", definition.conditions.map((item, n) => n === index ? {...item, value: event.target.value} : item))} />
        <button disabled={definition.conditions.length === 1} onClick={() => change("conditions", definition.conditions.filter((_, n) => n !== index))}>Удалить</button></div>)}
      <button disabled={definition.conditions.length >= 20} onClick={() => change("conditions", [...definition.conditions, {metric: "spend", operator: ">=", value: "0"}])}>Добавить условие</button>
      <div className="filterbar"><label>Действие<select value={definition.operation.kind} onChange={event => {const kind = event.target.value; change("operation", {kind, ...(kind.startsWith("budget") ? {value: kind === "budget_set" ? "50" : "20"} : {})}); if (kind.startsWith("budget") && !definition.max_budget) change("max_budget", "300");}}><option value="pause">Пауза</option><option value="enable">Включить</option><option value="budget_change">Бюджет ±%</option><option value="budget_set">Установить бюджет</option></select></label>
      {definition.operation.kind.startsWith("budget") && <><label>Значение<input type="number" step="0.01" value={definition.operation.value ?? ""} onChange={event => change("operation", {...definition.operation, value: event.target.value})} /></label><label>Потолок бюджета<input type="number" min="0.01" step="0.01" value={definition.max_budget ?? ""} onChange={event => change("max_budget", event.target.value)} /></label></>}
      <button disabled={busy || !!error} onClick={() => void save()}>{busy ? "Сохраняем…" : "Сохранить правило"}</button></div>
      {message && <p role="status">{message}</p>}
    </div>
    {runRule && <section className="actionpanel"><h2>Журнал: {runRule.definition.name}</h2><div className="tablewrap"><table><thead><tr><th>Время</th><th>Объект</th><th>Результат</th><th>Причина / расчёт</th></tr></thead><tbody>{runs.map(run => <tr key={run.id}><td>{new Date(run.at).toLocaleString("ru-RU")}</td><td>{run.details.entity_name}</td><td>{results[run.status] ?? run.status}{run.action_status && <small>{run.action_status}</small>}</td><td>{run.details.action && <p>{run.details.action}: {run.details.before?.budget ?? run.details.before?.status ?? "—"} → {run.details.value ?? run.details.action}</p>}<details><summary>Показатели и причина</summary><pre>{JSON.stringify(run.details, null, 2)}</pre></details></td></tr>)}{!runs.length && <tr><td colSpan={4} className="empty-cell">Проверок ещё не было</td></tr>}</tbody></table></div></section>}
  </section>;
}
