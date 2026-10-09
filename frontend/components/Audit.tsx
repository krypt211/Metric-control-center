"use client";
import { useCallback, useEffect, useState } from "react";
type Action = {id: string; at: string; action: string; status: string; provenance: {entity_name?: string; actor?: string; source?: string; rule_name?: string; currency?: string; before?: {budget: string | null; status: string}; after?: {budget: string | null; status: string}; reason?: unknown}};
export default function Audit({refreshKey}: {refreshKey: number}) {
  const [actions, setActions] = useState<Action[]>([]);
  const [error, setError] = useState("");
  const [events, setEvents] = useState<{event: string; at: string; details: unknown}[]>([]);
  const [opened, setOpened] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {const response = await fetch("/api/automation/audit", {cache: "no-store"}); const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Журнал недоступен");
      setActions(data.actions); setError("");
    } catch (cause) {setError(cause instanceof Error ? cause.message : "Журнал недоступен");}
  }, []);
  useEffect(() => {void load(); const timer = setInterval(() => void load(), 5000); return () => clearInterval(timer);}, [load, refreshKey]);
  async function history(id: string) {
    setOpened(id); setEvents([]);
    try {const response = await fetch(`/api/actions/${id}`, {cache: "no-store"}); if (!response.ok) throw new Error("События недоступны"); setEvents((await response.json()).events);}
    catch (cause) {setError(cause instanceof Error ? cause.message : "События недоступны");}
  }
  return <section>{error && <div className="notice error" role="alert">{error}</div>}<p className="table-note">Последние 100 команд. Успех отображается после подтверждения нового состояния при синхронизации.</p>
    <div className="tablewrap"><table><thead><tr><th>Время</th><th>Объект / действие</th><th>До → после</th><th>Автор / источник</th><th>Результат</th><th /></tr></thead><tbody>{actions.map(action => <tr key={action.id}>
      <td>{new Date(action.at).toLocaleString("ru-RU")}</td><td>{action.provenance.entity_name ?? "—"}<small>{action.action}</small></td>
      <td>{action.action === "budget_set" ? `${action.provenance.before?.budget ?? "—"} → ${action.provenance.after?.budget ?? "—"} ${action.provenance.currency ?? ""}` : `${action.provenance.before?.status ?? "—"} → ${action.provenance.after?.status ?? "—"}`}</td>
      <td>{action.provenance.actor ?? "—"}<small>{action.provenance.source ?? "—"}{action.provenance.rule_name && ` · ${action.provenance.rule_name}`}</small></td><td>{action.status}</td><td><button onClick={() => void history(action.id)}>События</button><details><summary>Причина</summary><pre>{JSON.stringify(action.provenance.reason ?? {}, null, 2)}</pre></details></td></tr>)}
      {!actions.length && <tr><td colSpan={6} className="empty-cell">Команд ещё не было</td></tr>}
    </tbody></table></div>
    {opened && <div className="actionpanel"><h2>События команды</h2>{events.map((event, index) => <details key={index}><summary>{new Date(event.at).toLocaleString("ru-RU")} · {event.event}</summary><pre>{JSON.stringify(event.details, null, 2)}</pre></details>)}</div>}
  </section>;
}
