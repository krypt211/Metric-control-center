"use client";
import { useEffect, useState } from "react";

type Subject = {id: string; name: string; level: string; currency: string; budget: string | null};
type Result = {batch_id: string; items: {entity_id: string; request_id: string | null; status: string; reason: string | null; provenance: {entity_name?: string; before?: {budget: string | null}; after?: {budget: string | null}; currency?: string}}[]};
const names: Record<string, string> = {queued: "В очереди", executing: "Выполняется", verifying: "Проверяем", succeeded: "Подтверждено", rejected: "Отклонено", unknown: "Результат неизвестен"};

export default function BulkActions({subjects, enabled, budgetEnabled, singleBusy, onBusy}: {subjects: Subject[]; enabled: boolean; budgetEnabled: boolean; singleBusy: boolean; onBusy: (busy: boolean) => void}) {
  const [operation, setOperation] = useState("pause");
  const [value, setValue] = useState("10");
  const [busy, setBusy] = useState(false);
  const [key, setKey] = useState<string | null>(null);
  const [result, setResult] = useState<Result | null>(null);
  const [message, setMessage] = useState("");
  function pending(state: boolean) {setBusy(state); onBusy(state);}
  useEffect(() => {
    const saved = sessionStorage.getItem("acc.pending-batch-key");
    if (saved) {setKey(saved); setBusy(true); onBusy(true);}
    // Parent state setter is stable.
  }, [onBusy]);
  useEffect(() => {
    if (!key) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const response = await fetch(result ? `/api/automation/batches/${result.batch_id}` : `/api/automation/batches/lookup?key=${encodeURIComponent(key)}`, {cache: "no-store"});
        if (!response.ok || cancelled) return;
        const data: Result = await response.json(); if (cancelled) return;
        setResult(data);
        if (data.items.every(item => ["succeeded", "rejected", "unknown"].includes(item.status))) {
          setBusy(false); onBusy(false); setKey(null); sessionStorage.removeItem("acc.pending-batch-key");
        }
      } catch { /* Read-only recovery; never resubmit an uncertain batch. */ }
    };
    void poll(); const timer = setInterval(() => void poll(), 3000);
    return () => {cancelled = true; clearInterval(timer);};
  }, [key, result?.batch_id, onBusy]);

  async function submit() {
    if (!subjects.length || busy || singleBusy) return;
    const isBudget = operation.startsWith("budget");
    const description = operation === "pause" ? "Приостановить" : operation === "enable" ? "Включить" : operation === "budget_change" ? `Изменить бюджет на ${value}%` : `Установить бюджет ${value} в валюте каждого кабинета`;
    const preview = subjects.slice(0, 20).map(item => `${item.name}${isBudget ? `: ${item.budget ?? "—"} → ${operation === "budget_change" && item.budget ? (Number(item.budget) * (1 + Number(value)/100)).toFixed(2) : value} ${item.currency}` : ""}`).join("\n");
    if (!window.confirm(`${description}. Объектов: ${subjects.length}.\n${preview}${subjects.length > 20 ? "\n…" : ""}\nКаждый объект проходит проверку отдельно.`)) return;
    const idempotencyKey = crypto.randomUUID();
    setKey(idempotencyKey); sessionStorage.setItem("acc.pending-batch-key", idempotencyKey);
    pending(true); setResult(null); setMessage("Отправляем пакет…");
    try {
      const response = await fetch("/api/automation/batches", {method: "POST", headers: {"Content-Type": "application/json", "Idempotency-Key": idempotencyKey},
        body: JSON.stringify({entity_ids: subjects.map(item => item.id), operation: {kind: operation, ...(isBudget ? {value} : {})}})});
      const data = await response.json();
      if (!response.ok) {
        if (response.status < 500) {pending(false); setKey(null); sessionStorage.removeItem("acc.pending-batch-key");}
        throw new Error(typeof data.detail === "string" ? data.detail : "Проверьте параметры пакета");
      }
      setResult(data); setMessage("Пакет зарегистрирован. Результаты появятся ниже.");
    } catch (error) {setMessage(error instanceof Error ? error.message : "Проверьте журнал пакета");}
  }
  if (!subjects.length && !result && !busy) return null;
  return <aside className="actionpanel"><h2>Массовое действие · {subjects.length} объектов</h2>
    <div className="actionbuttons"><select aria-label="Массовое действие" value={operation} onChange={event => {setOperation(event.target.value); setValue(event.target.value === "budget_set" ? "50" : "10");}} disabled={busy}>
      <option value="pause">Пауза</option><option value="enable">Включить</option><option value="budget_change">Бюджет ±%</option><option value="budget_set">Установить бюджет</option></select>
      {operation.startsWith("budget") && <input aria-label="Значение массового изменения" type="number" step="0.01" value={value} onChange={event => setValue(event.target.value)} />}
      <button onClick={() => void submit()} disabled={!enabled || busy || singleBusy || !subjects.length || (operation.startsWith("budget") && (!budgetEnabled || !value))}>Применить к выбранным</button></div>
    {message && <p role="status">{message}</p>}
    {result && <div className="tablewrap"><table><thead><tr><th>Объект</th><th>Изменение бюджета</th><th>Результат</th></tr></thead><tbody>{result.items.map(item => <tr key={item.entity_id}>
      <td>{item.provenance.entity_name ?? subjects.find(subject => subject.id === item.entity_id)?.name ?? item.entity_id}</td>
      <td>{result.items.some(row => row.provenance.before?.budget !== row.provenance.after?.budget) ? `${item.provenance.before?.budget ?? "—"} → ${item.provenance.after?.budget ?? "—"} ${item.provenance.currency ?? ""}` : "—"}</td>
      <td>{names[item.status] ?? item.status}{item.reason && <small>{item.reason}</small>}</td></tr>)}</tbody></table></div>}
    <p className="table-note">Процент считается от сохранённого бюджета каждого объекта. Потолок и лимит изменения проверяются перед выполнением.</p>
  </aside>;
}
