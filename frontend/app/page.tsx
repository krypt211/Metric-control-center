"use client";

import { useCallback, useEffect, useState } from "react";
import SessionBar from "@/components/SessionBar";
import Statistics from "@/components/Statistics";
import OptionalStatistics from "@/components/OptionalStatistics";
import Rules from "@/components/Rules";
import Audit from "@/components/Audit";
import Recommendations from "@/components/Recommendations";
import Copilot from "@/components/Copilot";
import SourceSummary,{type Source} from "@/components/SourceSummary";
import {metricRegistry} from "@/lib/metric-registry";

type Group = {
  source_provider?:string; attribution?:unknown; currency: string; timezone: string; start: string; end: string; level: string;
  spend: string | null; revenue: string | null; profit: string | null; roi: string | null;
  leads: number | null; sales: number | null; cpl: string | null; cps: string | null;
  conversion_source: string; tracker_complete: boolean | null; stale: boolean;
};
type Dashboard = {
  sources?: Source[];
  status: string; mode?: string; groups: Group[]; last_success_sync: string | null;
  last_run: { status: string; error_code: string | null } | null; as_of: string;
};

function money(value: string | null, currency: string): string {
  if (value === null) return "—";
  return new Intl.NumberFormat("ru-RU", { style: "currency", currency, maximumFractionDigits: 2 }).format(Number(value));
}
function count(value: number | null): string { return value === null ? "—" : new Intl.NumberFormat("ru-RU").format(value); }

export default function DashboardPage() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);
  const [tab, setTab] = useState("overview");
  const [refreshKey, setRefreshKey] = useState(0);
  const load = useCallback(async (signal?: AbortSignal) => {
    setBusy(true);
    try {
      const response = await fetch("/api/dashboard", { cache: "no-store", signal });
      const payload = await response.json();
      if (response.status === 401) { window.location.assign("/login"); return; }
      if (!response.ok) throw new Error(payload.error ?? "Не удалось загрузить статистику");
      setData(payload); setError(null);
    } catch (cause) {
      if (signal?.aborted) return;
      setError(cause instanceof Error ? cause.message : "Не удалось загрузить статистику");
    } finally { if (!signal?.aborted) setBusy(false); }
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    const timer = setInterval(() => { if (!document.hidden) void load(controller.signal); }, 30_000);
    return () => { controller.abort(); clearInterval(timer); };
  }, [load]);

  return <main>
    <header className="topbar"><a className="brand" href="/">ACC<span>Advertising Control Center</span></a><span className="version">{data?.mode === "LOCAL READ ONLY" ? "LOCAL READ ONLY · Actions disabled" : "Обзор рекламы"}</span><SessionBar/></header>
    <section className="heading"><div><p className="eyebrow">РАБОЧЕЕ ПРОСТРАНСТВО</p><h1>{tab === "tracker" ? "\u0422\u0440\u0435\u043a\u0435\u0440" : tab === "copilot" ? "AI Copilot" : tab === "overview" ? "Сегодня" : tab === "creatives" ? "Креативы" : tab === "rules" ? "Правила" : tab === "audit" ? "Журнал действий" : tab === "recommendations" ? "Рекомендации" : "Статистика"}</h1><p className="subtitle">Расходы и результаты в одном месте</p></div><button onClick={() => {setRefreshKey(key => key + 1); void load();}} disabled={busy}>{busy ? "Обновление…" : "Обновить"}</button></section>
    <nav className="tabs" aria-label="Раздел">{[["overview", "Обзор"], ["statistics", "Статистика"], ["creatives", "Креативы"], ["recommendations", "Рекомендации"], ["tracker", "\u0422\u0440\u0435\u043a\u0435\u0440"], ["copilot", "AI Copilot"], ["rules", "Правила"], ["audit", "Журнал"]].filter(([value]) => data?.mode !== "LOCAL READ ONLY" || ["overview", "statistics", "creatives", "tracker"].includes(value)).map(([value, name]) => <button key={value} className={tab === value ? "active" : ""} onClick={() => setTab(value)}>{name}</button>)}</nav>
    {tab==="overview"&&data?.sources&&<SourceSummary sources={data.sources}/>}
    {tab === "tracker" ? <OptionalStatistics kind="tracker" refreshKey={refreshKey} /> : tab === "creatives" && data?.mode === "LOCAL READ ONLY" ? <OptionalStatistics kind="creative" refreshKey={refreshKey} /> : tab === "copilot" ? <Copilot refreshKey={refreshKey} /> : tab === "recommendations" ? <Recommendations refreshKey={refreshKey} /> : tab === "rules" ? <Rules refreshKey={refreshKey} /> : tab === "audit" ? <Audit refreshKey={refreshKey} /> : tab !== "overview" ? <Statistics key={tab} refreshKey={refreshKey} creativeOnly={tab === "creatives"} /> : <>
    <div className="statusline"><span className={`dot ${error ? "bad" : data?.last_success_sync ? "good" : "waiting"}`} /><span>{data?.last_success_sync ? `Загрузка статистики: ${new Date(data.last_success_sync).toLocaleString("ru-RU")}` : "Ожидается первая загрузка статистики"}</span></div>
    {error && <div className="notice error" role="alert">{error}{data && ". Показаны последние полученные данные."}</div>}
    {data?.last_run?.status === "failed" && <div className="notice">Последняя синхронизация завершилась с ошибкой. Показаны данные предыдущей загрузки.</div>}
    {data?.last_run?.status === "skipped_quota" && <div className="notice">Обновление отложено: достигнут лимит запросов.</div>}
    {!data && busy && <div className="empty" aria-live="polite"><h2>Загружаем сводку</h2><p>Получаем сохранённые показатели.</p></div>}
    {data?.groups.length === 0 && <div className="empty"><div className="empty-icon">↗</div><h2>Статистика ещё не загружена</h2><p>После первой синхронизации здесь появятся расходы, выручка и результаты рекламы.</p></div>}
    {data?.groups.map((group) => {
      const cards = [
        { label: metricRegistry.spend.label, value: money(group.spend, group.currency), note: "Рекламный бюджет" },
        { label: metricRegistry.revenue.label, value: money(group.revenue, group.currency), note: group.conversion_source === "tracker" ? "По данным трекера" : "По данным рекламы" },
        { label: metricRegistry.profit.label, value: money(group.profit, group.currency), note: "Выручка минус расходы", positive: group.profit !== null && Number(group.profit) > 0 },
        { label: metricRegistry.roi.label, value: group.roi === null ? "—" : `${Number(group.roi).toLocaleString("ru-RU", {maximumFractionDigits: 2})}%`, note: "Прибыль / расходы", positive: group.roi !== null && Number(group.roi) > 0 },
        { label: metricRegistry.leads.label, value: count(group.leads), note: "Получено за сегодня" },
        { label: metricRegistry.sales.label, value: count(group.sales), note: "Получено за сегодня" },
        { label: metricRegistry.cpl.label, value: money(group.cpl, group.currency), note: "Стоимость лида" },
        { label: metricRegistry.cps.label, value: money(group.cps, group.currency), note: "Стоимость продажи" },
      ];
      return <section key={JSON.stringify([group.currency,group.timezone,group.source_provider,group.attribution])} className="group">
        <div className="group-heading"><h2>{group.currency}<span>{group.timezone} · {group.start} · {group.source_provider === "meta" ? "Meta API" : "MetricFlow API"}</span></h2><span className={`badge ${group.stale ? "stale" : ""}`}>{group.stale ? "Данные требуют обновления" : "Сохранённые данные"}</span></div>
        {group.tracker_complete === false && <div className="notice">Данные трекера неполные или имеют другую валюту. Итоги конверсий и выручки пока недоступны.</div>}
        <div className="cards">{cards.map(card => <article className="card" key={card.label}><h3>{card.label}</h3><p className={`value ${card.positive ? "positive" : ""}`}>{card.value}</p><p className="card-note">{card.note}</p></article>)}</div>
      </section>;
    })}
    </>}
    <footer>Валюты показаны отдельно. «Сегодня» в обзоре определяется по часовому поясу каждого кабинета. <span>«—» означает, что данных для расчёта недостаточно.</span></footer>
  </main>;
}
