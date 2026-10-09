"use client";

import { useEffect, useState } from "react";
import BulkActions from "./BulkActions";
import StatisticsGrid from "./StatisticsGrid";
import DataSources from "./DataSources";
import {dateRange as reportingRange} from "../lib/reporting-period";
const dateRange=(preset:string)=>reportingRange(preset,new Date(),process.env.NEXT_PUBLIC_REPORTING_TIMEZONE??"Europe/Moscow");

type Level = "account" | "campaign" | "adset" | "ad" | "creative";
type Item = {id: string; external_id: string; name: string; level: Level; currency: string; timezone: string; status: string | null; budget: string | null; media_url: string | null; [key: string]: string | number | null};
type Option = {id: string; name: string};
type FilterData = {options: Record<string, Option[]>; unavailable: Record<string, string>};
const levels: Level[] = ["account", "campaign", "adset", "ad", "creative"];
const levelNames = {account: "Кабинеты", campaign: "Кампании", adset: "Группы", ad: "Объявления", creative: "Креативы"};
const filterNames: Record<string, string> = {account: "Кабинет", campaign: "Кампания", adset: "Группа", ad: "Объявление", creative: "Креатив", geo: "GEO", buyer: "Байер", offer: "Оффер", tracker_campaign: "Кампания трекера"};
const statusNames: Record<string, string> = {queued: "В очереди", executing: "Выполняется", verifying: "Проверяем результат", succeeded: "Результат подтверждён", rejected: "Отклонено", unknown: "Результат пока не подтверждён"};


export default function Statistics({creativeOnly = false, refreshKey = 0}: {creativeOnly?: boolean; refreshKey?: number}) {
  const [level, setLevel] = useState<Level>(creativeOnly ? "creative" : "account");
  const [dates, setDates] = useState<[string, string]>(["", ""]);
  const [preset, setPreset] = useState("1");
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [options, setOptions] = useState<FilterData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Item | null>(null);
  const [checked, setChecked] = useState<Record<string, Item>>({});
  const [batchBusy, setBatchBusy] = useState(false);
  const [capabilities, setCapabilities] = useState({actions_enabled: false, budget_enabled: false});
  const [budget, setBudget] = useState("");
  const [actionMessage, setActionMessage] = useState("");
  const [requestId, setRequestId] = useState<string | null>(null);
  const [pendingKey, setPendingKey] = useState<string | null>(null);
  const [commandBusy, setCommandBusy] = useState(false);
  const [requestStatus, setRequestStatus] = useState<string | null>(null);
  const [events, setEvents] = useState<{event: string; at: string}[]>([]);

  useEffect(() => {
    const saved = sessionStorage.getItem("acc.pending-action-key");
    if (saved) {setPendingKey(saved); setCommandBusy(true);}
    setDates(dateRange("1"));
    void fetch("/api/stats/filters").then(r => {if (!r.ok) throw new Error(); return r.json();}).then(setOptions).catch(() => setError("Не удалось загрузить фильтры"));
    void fetch("/api/capabilities").then(r => r.json()).then(setCapabilities).catch(() => {});
  }, []);
  useEffect(() => {
    if(preset === "custom")return;
    const update=()=>{const next=dateRange(preset);setDates(previous=>previous[0]===next[0]&&previous[1]===next[1]?previous:next);};
    const timer=window.setInterval(update,60000);window.addEventListener("focus",update);
    return()=>{window.clearInterval(timer);window.removeEventListener("focus",update);};
  },[preset]);
  useEffect(() => {
    if (!pendingKey || requestId) return;
    let cancelled = false;
    const lookup = async () => {
      try {
        const response = await fetch(`/api/actions?key=${encodeURIComponent(pendingKey)}`, {cache: "no-store"});
        if (!response.ok || cancelled) return;
        const data = await response.json();
        if (!cancelled) setRequestId(data.request_id);
      } catch { /* Read-only recovery: never resend an unknown command. */ }
    };
    void lookup(); const timer = setInterval(() => void lookup(), 3000);
    return () => {cancelled = true; clearInterval(timer);};
  }, [pendingKey, requestId]);
  useEffect(() => {setChecked({});}, [level, filters, dates]);
  useEffect(() => {
    if (!requestId) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const response = await fetch(`/api/actions/${requestId}`, {cache: "no-store"});
        if (!response.ok || cancelled) return;
        const data = await response.json();
        if (cancelled) return;
        setRequestStatus(data.status); setEvents(data.events); setActionMessage(statusNames[data.status] ?? data.status);
        if (["succeeded", "rejected", "unknown"].includes(data.status)) {
          setCommandBusy(false); setPendingKey(null); sessionStorage.removeItem("acc.pending-action-key");
        }
      } catch { /* Keep command disabled while its outcome is unknown. */ }
    };
    void poll(); const timer = setInterval(() => void poll(), 3000);
    return () => {cancelled = true; clearInterval(timer);};
  }, [requestId]);

  async function command(action: string, value?: string) {
    if (!selected || commandBusy || batchBusy) return;
    const description = action === "budget_set" ? `Установить бюджет ${value} ${selected.currency}` : action === "pause" ? "Приостановить" : "Включить";
    if (!window.confirm(`${description}: ${selected.name}?`)) return;
    setCommandBusy(true); setActionMessage("Отправляем команду…"); setEvents([]);
    setRequestId(null);
    const key = crypto.randomUUID(); setPendingKey(key); sessionStorage.setItem("acc.pending-action-key", key);
    try {
      const response = await fetch("/api/actions", {method: "POST", headers: {"Content-Type": "application/json", "Idempotency-Key": key}, body: JSON.stringify({entity_id: selected.external_id, entity_type: selected.level, action, ...(value ? {value} : {})})});
      const data = await response.json();
      if (!response.ok) {
        // A definite validation rejection allows correction. A transport failure
        // leaves the button locked because the request may have been accepted.
        if (response.status < 500) {setCommandBusy(false); setPendingKey(null); sessionStorage.removeItem("acc.pending-action-key");}
        throw new Error(typeof data.detail === "string" ? data.detail : "Команда отклонена");
      }
      setRequestId(data.request_id); setRequestStatus("queued"); setActionMessage("В очереди");
    } catch (cause) { setActionMessage(cause instanceof Error ? cause.message : "Проверьте журнал перед повтором команды"); }
  }
  function drill(item: Item) {
    setSelected(item); setBudget(item.budget ?? "");
    const index = levels.indexOf(item.level);
    if (index < levels.length - 1 && !creativeOnly) {
      setFilters(previous => ({...previous, [item.level]: item.id})); setLevel(levels[index + 1]);
    }
  }
  const query = new URLSearchParams({level, start:dates[0], end:dates[1]});
  for(const [key,value] of Object.entries(filters))if(value)query.set(key,value);

  return <section className="statistics">
    <DataSources start={dates[0]} end={dates[1]} account={filters.account??""} refreshKey={refreshKey}/>
    <p className="period-note">Календарные даты по timezone каждого кабинета; «Сегодня» в таблице выбирает дату Europe/Moscow. Обзор использует текущий день каждого кабинета.</p>
    <div className="filterbar">
      <label>Период<select value={preset} onChange={e => {setPreset(e.target.value);  if (e.target.value !== "custom") setDates(dateRange(e.target.value));}}>
        <option value="1">Сегодня</option><option value="yesterday">Вчера</option>{[3, 7, 14, 30].map(n => <option key={n} value={n}>{n} дней</option>)}<option value="custom">Свой период</option>
      </select></label>
      <label>С<input type="date" value={dates[0]} onChange={e => {setPreset("custom"); setDates([e.target.value, dates[1]]); }} /></label><label>По<input type="date" value={dates[1]} onChange={e => {setPreset("custom"); setDates([dates[0], e.target.value]); }} /></label>
      {Object.entries(filterNames).map(([key, name]) => <label key={key}>{name}<select value={filters[key] ?? ""} disabled={!options?.options[key]?.length} title={options?.unavailable[key]} onChange={e => {setFilters({...filters, [key]: e.target.value}); }}><option value="">Все</option>{options?.options[key]?.map(option => <option key={option.id} value={option.id}>{option.name}</option>)}</select></label>)}
      <label>Статус<select value={filters.status ?? ""} onChange={e => {setFilters({...filters, status: e.target.value}); }}><option value="">Все</option><option value="ACTIVE">ACTIVE</option><option value="PAUSED">PAUSED</option></select></label>
      <button onClick={() => {setFilters({}); setLevel(creativeOnly ? "creative" : "account"); setSelected(null); }}>Сбросить</button>
    </div>
    {!creativeOnly && <nav className="levelnav" aria-label="Уровень статистики">{levels.map(item => <button key={item} className={level === item ? "active" : ""} onClick={() => {setLevel(item); }}>{levelNames[item]}</button>)}</nav>}
    {error && <div className="notice error" role="alert">{error}</div>}
    <StatisticsGrid key={level} scope={level} endpoint="/api/stats/table" query={query.toString()} refreshKey={refreshKey} onName={row=>drill(row as Item)}
      selection={capabilities.actions_enabled?{selected:row=>!!checked[String(row.id)],
      disabled:row=>batchBusy||commandBusy||!["campaign","adset","ad"].includes(String(row.level))||(!checked[String(row.id)]&&Object.keys(checked).length>=200),
      toggle:(row,value)=>setChecked(previous=>{const next={...previous};if(value)next[String(row.id)]=row as Item;else delete next[String(row.id)];return next;})}:undefined}/>
    <BulkActions subjects={Object.values(checked)} enabled={capabilities.actions_enabled} budgetEnabled={capabilities.budget_enabled} singleBusy={commandBusy} onBusy={setBatchBusy} />
    {selected && ["campaign", "adset", "ad"].includes(selected.level) && <aside className="actionpanel"><div><h2>{selected.name}</h2><p>Статус: {selected.status ?? "—"} · Бюджет: {selected.budget ?? "—"} {selected.currency}</p></div>
      {!capabilities.actions_enabled && <p className="subtitle">Ручное управление ещё не включено.</p>}
      <div className="actionbuttons"><button disabled={!capabilities.actions_enabled || commandBusy || selected.status !== "ACTIVE"} onClick={() => void command("pause")}>Пауза</button><button disabled={!capabilities.actions_enabled || commandBusy || selected.status !== "PAUSED"} onClick={() => void command("enable")}>Включить</button>
      {selected.level !== "ad" && <>{[-20, -10, 10, 20].map(change => <button key={change} disabled={!capabilities.budget_enabled || commandBusy || !selected.budget} onClick={() => void command("budget_set", (Number(selected.budget) * (1 + change / 100)).toFixed(2))}>{change > 0 ? "+" : ""}{change}%</button>)}<input aria-label="Новый бюджет" type="number" step="0.01" min="0.01" value={budget} onChange={e => setBudget(e.target.value)} /><button disabled={!capabilities.budget_enabled || commandBusy || !budget} onClick={() => void command("budget_set", budget)}>Установить бюджет</button></>}</div>
      {actionMessage && <p aria-live="polite">{actionMessage}</p>}{requestId && <details><summary>Журнал команды · {statusNames[requestStatus ?? ""] ?? ""}</summary><ul>{events.map((event, i) => <li key={i}>{new Date(event.at).toLocaleString("ru-RU")} · {event.event}</li>)}</ul></details>}
    </aside>}
    <p className="table-note">Итоги всех уровней получены из статистики объявлений. Переход по названию открывает следующий уровень. GEO станет доступен после подключения разрезов по странам.</p>
  </section>;
}
