"use client";
import {useCallback, useEffect, useState} from "react";

type Profile = {country: string; offer: string; enabled: boolean; currency: string; target_cpl: string; critical_cpl: string; target_roi: string; scaling_percent: string; scaling_cooldown_seconds: number; max_adset_budget: string; stop_spend: string};
type SavedProfile = {id: string; revision: number; profile: Profile};
type Turn = {id: string; text: string; status: string; answer: string | null; error_code: string | null; trace: {tool: string; arguments: unknown; result: unknown}[]; decision: {id: string; status: string} | null};
const preset: Profile = {country: "IT", offer: "Adenofrin", enabled: true, currency: "USD", target_cpl: "8", critical_cpl: "15", target_roi: "70", scaling_percent: "15", scaling_cooldown_seconds: 28800, max_adset_budget: "250", stop_spend: "20"};

async function api(path: string, method = "GET", body?: unknown, key?: string) {
  const response = await fetch(`/api/ai/${path}`, {method, cache: "no-store", headers: {"Content-Type": "application/json", ...(key ? {"Idempotency-Key": key} : {})}, ...(body ? {body: JSON.stringify(body)} : {})});
  const result = await response.json();
  if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "Запрос не выполнен");
  return result;
}

export default function Agent({refreshKey, enabled, onChanged}: {refreshKey: number; enabled: boolean; onChanged: () => Promise<void>}) {
  const [turns, setTurns] = useState<Turn[]>([]), [profiles, setProfiles] = useState<SavedProfile[]>([]);
  const [text, setText] = useState(""), [draft, setDraft] = useState<Profile>(preset), [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<{key: string; text: string} | null>(null);
  const load = useCallback(async () => {
    try {const [chat, settings] = await Promise.all([api("messages"), api("profiles")]); setTurns(chat.messages); setProfiles(settings.profiles);} catch (cause) {setError(String(cause));}
  }, []);
  useEffect(() => {void load(); const timer = setInterval(() => {if (!document.hidden) void load();}, 15_000); return () => clearInterval(timer);}, [load, refreshKey]);
  useEffect(() => {try {const saved = sessionStorage.getItem("agent-message-pending"); if (saved) setPending(JSON.parse(saved));} catch {}}, []);
  async function send() {
    const request = pending ?? {key: crypto.randomUUID(), text};
    sessionStorage.setItem("agent-message-pending", JSON.stringify(request)); setPending(request); setBusy(true);
    try {await api("messages", "POST", {text: request.text}, request.key); sessionStorage.removeItem("agent-message-pending"); setPending(null); setText(""); setError(null); await load(); await onChanged();} catch (cause) {setError(String(cause));} finally {setBusy(false);}
  }
  async function save() {
    setBusy(true);
    try {const result = await api("profiles", "PUT", {profile: draft, revision}); setProfiles(result.profiles); const saved = (result.profiles as SavedProfile[]).find(p => p.profile.country === draft.country && p.profile.offer === draft.offer); if (saved) {setDraft(saved.profile); setRevision(saved.revision);} setError(null); await onChanged();} catch (cause) {setError(String(cause));} finally {setBusy(false);}
  }
  return <div className="agent-area">
    {error && <div className="notice error" role="alert">{error}</div>}
    <details className="actionpanel"><summary>Постоянные инструкции медиабайера · {profiles.length}</summary>
      <div className="filters"><label>Профиль<select value={revision ? `${draft.country}/${draft.offer}` : "new"} onChange={e => {const saved = profiles.find(p => `${p.profile.country}/${p.profile.offer}` === e.target.value); setDraft(saved?.profile ?? {...preset}); setRevision(saved?.revision ?? 0);}}><option value="new">Новый профиль</option>{profiles.map(p => <option key={p.id} value={`${p.profile.country}/${p.profile.offer}`}>{p.profile.country} / {p.profile.offer}{!p.profile.enabled && " · OFF"}</option>)}</select></label>
      <label>GEO<input maxLength={2} disabled={revision > 0} value={draft.country} onChange={e => setDraft({...draft, country: e.target.value.toUpperCase()})} /></label>
      <label>Offer<input maxLength={128} disabled={revision > 0} value={draft.offer} onChange={e => setDraft({...draft, offer: e.target.value})} /></label>
      <label>Валюта<input maxLength={3} value={draft.currency} onChange={e => setDraft({...draft, currency: e.target.value.toUpperCase()})} /></label>
      {([['target_cpl','Target CPL'], ['critical_cpl','Critical CPL'], ['target_roi','Target ROI, %'], ['scaling_percent','Scaling, %'], ['max_adset_budget','Max budget'], ['stop_spend','Stop: spend >']] as [keyof Profile, string][]).map(([key, label]) => <label key={key}>{label}<input type="number" value={String(draft[key])} onChange={e => setDraft({...draft, [key]: e.target.value})} /></label>)}
      <label>Scaling cooldown, часов<input type="number" min={1/60} max={168} step="any" value={draft.scaling_cooldown_seconds/3600} onChange={e => setDraft({...draft, scaling_cooldown_seconds: Math.round(Number(e.target.value)*3600)})} /></label>
      <label><input type="checkbox" checked={draft.enabled} onChange={e => setDraft({...draft, enabled: e.target.checked})} /> Профиль активен</label>
      <button disabled={busy} onClick={() => void save()}>Сохранить профиль</button><button onClick={() => {const saved = profiles.find(p => p.profile.country === draft.country && p.profile.offer === draft.offer); if (saved) {setDraft(saved.profile); setRevision(saved.revision);}}}>Загрузить сохранённый</button></div>
      <p className="table-note">Stop candidate: spend больше порога и 0 leads. Профиль применяется к подтверждённым GEO/offer; он ограничивает scaling и бюджет, сохраняя общую policy. Значения IT/Adenofrin — шаблон, он начнёт действовать после сохранения. Offer должен совпадать с меткой в данных. Cooldown хранится в БД.</p>
    </details>
    <div className="actionpanel"><h2>Чат с агентом</h2><p className="table-note">Например: «Что сегодня происходит по Италии?» или «Выключи по Италии объявления: spend &gt; 30 USD и sales = 0». Перед действием появится конкретный фильтр и список для подтверждения.</p>
      <label className="agent-input">Сообщение<textarea maxLength={4000} rows={3} value={text} onChange={e => setText(e.target.value)} disabled={!!pending} /></label><button disabled={busy || !enabled || (!text.trim() && !pending)} onClick={() => void send()}>{pending ? "Повторить тот же запрос" : "Отправить"}</button>
      {!enabled && <p className="table-note">Чат будет доступен после подключения модели и выбора уровня автономности. Telegram-команда /stop_auto работает без LLM.</p>}
      {!turns.length && <p>История чата пуста.</p>}
      {turns.map(turn => <article className="agent-turn" key={turn.id}><strong>Вы</strong><p>{turn.text}</p><strong>Агент · {turn.status}</strong><p>{turn.answer ?? (turn.error_code ? `Ошибка: ${turn.error_code}` : "Ожидается ответ")}</p>{turn.decision && <p className="notice">Предложения: {turn.decision.status}. Проверьте список и фильтры в журнале AI ниже. Команда ещё не означает отправку в рекламу.</p>}<details><summary>Данные и вызовы инструментов</summary><pre className="ai-snapshot">{JSON.stringify(turn.trace, null, 2)}</pre></details></article>)}
    </div>
  </div>;
}
