"use client";
import {useCallback, useEffect, useState} from "react";
import Agent from "@/components/Agent";

type Policy = {mode: string; allow_enable: boolean; currency: string; max_change_percent: string; max_daily_budget: string; max_actions_per_day: number; max_analyses_per_day: number; daily_budget_verified: boolean; proposal_ttl_minutes: number};
type Configuration = {settings: Policy; revision: number; ai_enabled: boolean; model: string | null; autopilot_allowed: boolean; actions_enabled: boolean; automation: {stopped: boolean; generation: number}};
type Proposal = {entity_id: string; action: string; change_percent: number | null; confidence: number; reason: string; evidence: string[]; priority: number};
type Scope = {window: string[]; timezone: string; query: {country: string | null; offer: string | null; account_id: string | null; entity_id: string | null; currency: string; window: string; level: string}; conditions: {metric: string; operator: string; value: string}[]; metrics: {spend: string | null; sales: number | null; leads: number | null}};
type Decision = {id: string; status: string; mode: string; created_at: string; expires_at: string | null; summary: string | null; error_code: string | null; snapshot: unknown; requires_confirmation: boolean; command_summary: {currency: string; timezone: string; entities: number; spend: string | null}[]; actions: {id: string; status: string; request_id: string | null; entity_name: string | null; proposal: Proposal; target_budget: string | null; policy_reason: string | null; scope?: Scope}[]};
type Option = {id: string; name: string};

async function api(path: string, method = "GET", body?: unknown, key?: string) {
  const response = await fetch(`/api/ai/${path}`, {method, cache: "no-store", headers: {"Content-Type": "application/json", ...(key ? {"Idempotency-Key": key} : {})}, ...(body ? {body: JSON.stringify(body)} : {})});
  const payload = await response.json();
  if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : "Не удалось выполнить запрос");
  return payload;
}

export default function Copilot({refreshKey}: {refreshKey: number}) {
  const [configuration, setConfiguration] = useState<Configuration | null>(null);
  const [draft, setDraft] = useState<Policy | null>(null);
  const [revision, setRevision] = useState<number | null>(null);
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [options, setOptions] = useState<Record<string, Option[]>>({});
  const [level, setLevel] = useState("adset");
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [stopBusy, setStopBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<{key: string; ids: string[]} | null>(null);
  const load = useCallback(async () => {
    try {
      const [config, history, filters] = await Promise.all([api("settings"), api("decisions"), fetch("/api/stats/filters", {cache: "no-store"}).then(r => r.json())]);
      setConfiguration(config); setDecisions(history.decisions); setOptions(filters.options ?? {}); setError(null);
      setDraft(old => old ?? config.settings); setRevision(old => old ?? config.revision);
    } catch (cause) {setError(cause instanceof Error ? cause.message : "AI недоступен");}
  }, []);
  useEffect(() => {void load(); const timer = setInterval(() => {if (!document.hidden) void load();}, 15_000); return () => clearInterval(timer);}, [load, refreshKey]);
  useEffect(() => {try {const saved = sessionStorage.getItem("ai-analysis-pending"); if (saved) setPending(JSON.parse(saved));} catch {}}, []);
  async function save() {
    if (!draft) return;
    if (draft.mode === "AUTOPILOT" && !window.confirm("Разрешить AI ставить действия в очередь без ручного одобрения в пределах указанной policy?")) return;
    setBusy(true);
    try {const result = await api("settings", "PUT", {settings: draft, revision}); setConfiguration(result); setDraft(result.settings); setRevision(result.revision); setError(null);} catch (cause) {setError(String(cause));} finally {setBusy(false);}
  }
  async function analyze() {
    setBusy(true);
    const request = pending ?? {key: crypto.randomUUID(), ids: selected};
    sessionStorage.setItem("ai-analysis-pending", JSON.stringify(request)); setPending(request);
    try {await api("analyses", "POST", {entity_ids: request.ids}, request.key); sessionStorage.removeItem("ai-analysis-pending"); setPending(null); await load();} catch (cause) {setError(String(cause));} finally {setBusy(false);}
  }
  async function resolve(decision: Decision, operation: string) {
    const count = decision.actions.filter(a => a.status === "pending").length;
    if (operation === "approve" && !window.confirm(`Одобрить ${count} действий? Перед отправкой система снова проверит данные и лимиты.`)) return;
    setBusy(true);
    try {await api(`decisions/${decision.id}/resolve`, "POST", {operation}); await load();} catch (cause) {setError(String(cause));} finally {setBusy(false);}
  }
  async function automation(stopped: boolean) {
    if (!stopped && !window.confirm("Возобновить AI и rule actions в рамках сохранённых режимов и policy? Старые предложения останутся отменёнными.")) return;
    setStopBusy(true);
    try {await api("automation", "POST", {stopped, generation: configuration?.automation.generation}); await load();} catch (cause) {setError(String(cause));} finally {setStopBusy(false);}
  }
  return <section>
    {error && <div className="notice error" role="alert">{error}</div>}
    <div className="notice">Метрики и тренды рассчитывает аналитика. AI объясняет и предлагает действия. Confidence — самооценка модели, а не вероятность прибыли.</div>
    <div className="actionpanel emergency"><div><strong>AI AUTOPILOT: {configuration?.settings.mode === "AUTOPILOT" && !configuration.automation.stopped ? "ON" : "OFF"}</strong><p>{configuration?.automation.stopped ? "Emergency Stop активен: AI и rule actions остановлены." : "Сбор статистики работает независимо от автоматизаций."}</p></div><div className="bulkbar"><button disabled={!configuration || stopBusy} className="danger" onClick={() => void automation(true)}>EMERGENCY STOP</button>{configuration?.automation.stopped && <button disabled={stopBusy} onClick={() => void automation(false)}>Возобновить автоматизации</button>}</div></div>
    {draft && <details className="actionpanel" open><summary>Режим и ограничения AI</summary><div className="filters">
      <label>Автономность<select value={draft.mode} onChange={e => setDraft({...draft, mode: e.target.value})}>{[["OFF", "AI выключен"], ["READ_ONLY", "LEVEL 0 · READ ONLY"], ["RECOMMEND", "LEVEL 1 · RECOMMEND"], ["APPROVAL", "LEVEL 2 · APPROVAL"], ["AUTOPILOT", "LEVEL 3 · AUTOPILOT"]].map(([mode, label]) => <option key={mode} value={mode} disabled={mode === "AUTOPILOT" && !configuration?.autopilot_allowed}>{label}</option>)}</select></label>
      <label>Валюта<input maxLength={3} value={draft.currency} onChange={e => setDraft({...draft, currency: e.target.value.toUpperCase()})} /></label>
      <label>Изменение бюджета, %<input type="number" min={1} max={20} value={draft.max_change_percent} onChange={e => setDraft({...draft, max_change_percent: e.target.value})} /></label>
      <label>Дневной бюджет ≤<input type="number" min={1} max={300} value={draft.max_daily_budget} onChange={e => setDraft({...draft, max_daily_budget: e.target.value})} /></label>
      <label>Действий в день ≤<input type="number" min={1} max={30} value={draft.max_actions_per_day} onChange={e => setDraft({...draft, max_actions_per_day: Number(e.target.value)})} /></label>
      <label>Анализов в день ≤<input type="number" min={1} max={100} value={draft.max_analyses_per_day} onChange={e => setDraft({...draft, max_analyses_per_day: Number(e.target.value)})} /></label>
      <label>Срок предложения, мин<input type="number" min={1} max={30} value={draft.proposal_ttl_minutes} onChange={e => setDraft({...draft, proposal_ttl_minutes: Number(e.target.value)})} /></label>
      <label><input type="checkbox" checked={draft.daily_budget_verified} onChange={e => setDraft({...draft, daily_budget_verified: e.target.checked})} /> Проверено: API возвращает дневной бюджет</label>
      <label><input type="checkbox" checked={draft.allow_enable} onChange={e => setDraft({...draft, allow_enable: e.target.checked})} /> Разрешить предложения enable для Ad/Adset</label>
      <button disabled={busy} onClick={() => void save()}>Сохранить</button><button disabled={busy} onClick={async () => {const c = await api("settings"); setDraft(c.settings); setRevision(c.revision);}}>Загрузить сохранённые</button>
    </div><p className="table-note">LEVEL 0: только анализ. LEVEL 1: предложения. LEVEL 2: одобрение. LEVEL 3: разрешённые автоматические действия. Команды из чата всегда требуют CONFIRM. Ставки недоступны до проверки API. Модель: {configuration?.model ?? "не настроена"}.</p></details>}
    <Agent refreshKey={refreshKey} enabled={!!configuration?.ai_enabled && !!configuration.model && configuration.settings.mode !== "OFF"} onChanged={load} />
    <div className="actionpanel"><h2>Новый анализ</h2><div className="filters"><label>Уровень<select value={level} onChange={e => {setLevel(e.target.value); setSelected([]);}}>{[["campaign", "Кампания"], ["adset", "Ad Set"], ["ad", "Объявление"], ["creative", "Креатив"]].map(([id, title]) => <option key={id} value={id}>{title}</option>)}</select></label>
      <button disabled={busy || !configuration?.ai_enabled || !configuration.model || configuration.settings.mode === "OFF" || (!selected.length && !pending)} onClick={() => void analyze()}>{pending ? "Повторить тот же запрос" : `Анализировать (${selected.length}/30)`}</button></div>
      {!configuration?.ai_enabled && <p className="table-note">Внешний AI пока выключен. История и настройки доступны.</p>}
      <div className="ai-selection">{(options[level] ?? []).map(option => <label key={option.id}><input type="checkbox" checked={selected.includes(option.id)} disabled={!selected.includes(option.id) && selected.length >= 30} onChange={e => setSelected(ids => e.target.checked ? [...ids, option.id] : ids.filter(id => id !== option.id))} /> {option.name}</label>)}</div>
      {!options[level]?.length && <p>После синхронизации здесь появятся сущности для анализа.</p>}
    </div>
    {!decisions.length && <div className="empty"><h2>AI-анализов ещё нет</h2><p>Рекомендации появятся после загрузки статистики и подключения модели.</p></div>}
    {decisions.map(decision => <article className="actionpanel" key={decision.id}><div className="group-heading"><h2>{decision.mode}<span>{new Date(decision.created_at).toLocaleString("ru-RU")}</span></h2><span className="badge">{decision.status}</span></div><p>{decision.summary ?? (decision.error_code ? `Ошибка анализа: ${decision.error_code}` : "Ожидается анализ")}</p>
      {decision.expires_at && <p className="table-note">Действительно до {new Date(decision.expires_at).toLocaleString("ru-RU")}</p>}
      {decision.command_summary?.map(group => <p key={`${group.currency}/${group.timezone}`}>Найдено: {group.entities} · Текущие расходы: {group.spend ?? "неизвестно"} {group.currency} · {group.timezone}</p>)}
      {decision.requires_confirmation && <p className="notice">Команда из чата требует CONFIRM. Pause останавливает сущность целиком, включая другие GEO.</p>}
      {decision.actions.map(action => <div className="detector-evidence" key={action.id}><h3>{action.entity_name ?? action.proposal.entity_id}</h3>{action.scope && <p>Фильтр: GEO {action.scope.query.country ?? "ALL"} · offer {action.scope.query.offer ?? "ALL"} · {action.scope.query.currency} · {action.scope.query.window} · {action.scope.query.level}<br />{action.scope.conditions.map(c => `${c.metric} ${c.operator} ${c.value}`).join(" AND ")}<br />По фильтру: spend {action.scope.metrics.spend ?? "—"} · sales {action.scope.metrics.sales ?? "—"} · leads {action.scope.metrics.leads ?? "—"}</p>}<p>{action.proposal.action === "budget_change" ? `Бюджет ${action.proposal.change_percent! > 0 ? "+" : ""}${action.proposal.change_percent}% → ${action.target_budget ?? "отказ policy"}` : action.proposal.action === "pause" ? "Приостановить" : action.proposal.action === "enable" ? "Включить" : "Оставить без изменений"} · {action.status}</p><p>{action.proposal.reason}</p><small>Самооценка модели: {action.proposal.confidence}% · Приоритет: {action.proposal.priority} · Основания: {action.proposal.evidence.join(", ")}</small>{action.scope && <p>Account: {action.scope.query.account_id ?? "ALL"} / Entity: {action.scope.query.entity_id ?? "ALL"} / {action.scope.window.join(" - ")} / {action.scope.timezone}</p>}{action.policy_reason && <p className="notice">{action.policy_reason}</p>}</div>)}
      {decision.status === "pending" && <div className="bulkbar"><button disabled={busy || !configuration?.actions_enabled || configuration.automation.stopped || !decision.actions.some(a => a.status === "pending") || !decision.expires_at || Date.parse(decision.expires_at) <= Date.now()} onClick={() => void resolve(decision, "approve")}>{decision.requires_confirmation ? "CONFIRM" : "Одобрить все"}</button><button disabled={busy} onClick={() => void resolve(decision, "reject")}>Отклонить</button></div>}
      <details><summary>Исходный snapshot</summary><pre className="ai-snapshot">{JSON.stringify(decision.snapshot, null, 2)}</pre></details>
    </article>)}
  </section>;
}
