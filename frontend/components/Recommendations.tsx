"use client";
import { useCallback, useEffect, useState } from "react";

type Settings = {level: string; window: string; currency: string; minimum_spend: string; minimum_conversions: number; target_roi: string; target_cpl: string; loser_spend_multiplier: string; fatigue_days: number; ctr_decline_percent: string; cpc_increase_percent: string; frequency_increase_percent: string; cpl_increase_percent: string; minimum_daily_impressions: number; minimum_daily_clicks: number; current_max_age_minutes: number; historical_max_age_hours: number};
type Check = {metric: string; value?: string | number; operator?: string; target?: string; change_percent?: string; target_percent?: string; monotonic?: boolean; passed: boolean};
type Point = {date: string; ctr: string | null; cpc: string | null; frequency: string | null; cpl: string | null};
type Signal = {matched: boolean; reason: string; missing?: string[]; checks?: Check[]; series?: Point[]; window?: string[]};
type Item = {id: string; external_id: string; name: string; level: string; currency: string; timezone: string; category: string; window: string[]; current_fresh: boolean; metrics: Record<string, string | number | null>; signals: {winner: Signal; loser: Signal; fatigue: Signal}};
type Data = {settings: Settings; revision: number; as_of: string; counts: Record<string, number>; rows: Item[]; total: number; next_offset: number | null};
const categories = [["scale", "🔥 Scale", "WINNER"], ["watch", "⚠ Watch", "Наблюдать"], ["stop", "🛑 Stop", "STOP CANDIDATE"], ["fatigue", "♻ Fatigue", "CREATIVE FATIGUE"]];
const reasons: Record<string, string> = {winner: "Все условия Winner выполнены", stop_candidate: "Расходы достигли лимита при нуле лидов", creative_fatigue: "Подтверждён тренд по четырём показателям", thresholds_not_met: "Пороги не достигнуты", unknown_metrics: "Недостаточно показателей", incomplete_history: "Нет полного ряда завершённых дней", incomplete_period: "Нет данных за весь выбранный период", stale_metrics: "Статистику периода нужно обновить", stale_history: "Историю нужно обновить", frequency_unavailable: "Нет сопоставимой дневной frequency", stale_frequency: "Frequency нужно обновить", insufficient_daily_volume: "Мало показов или кликов для оценки тренда", conversion_source_changed: "Источник конверсий менялся или данные трекера неполные", delivery_cohort_changed: "Состав объявлений менялся между днями", zero_baseline: "Исходный показатель равен нулю", trend_not_confirmed: "Совместный тренд не подтверждён", account_units_mismatch: "Валюта или часовой пояс данных не совпадают с кабинетом"};
const labels: Record<string, string> = {spend: "Расходы", conversions: "Конверсии", roi: "ROI", cpl: "CPL", leads: "Лиды", ctr: "CTR", cpc: "CPC", frequency: "Frequency"};
function number(value: string | number | null | undefined) {return value === null || value === undefined ? "—" : Number(value).toLocaleString("ru-RU", {maximumFractionDigits: 2});}

function Trend({series, metric}: {series: Point[]; metric: "ctr" | "cpc" | "frequency" | "cpl"}) {
  const known = series.every(point => point[metric] !== null);
  const values = series.map(point => Number(point[metric]));
  const min = Math.min(...values), max = Math.max(...values), span = max - min || 1;
  const points = values.map((value, index) => `${8 + index * 204 / Math.max(1, values.length-1)},${70 - (value-min) * 54/span}`).join(" ");
  return <div className="trend"><strong>{labels[metric]}</strong>{known && values.length > 1 ? <svg viewBox="0 0 220 80" role="img" aria-label={`${labels[metric]}: ${values.map(number).join(" → ")}`}><polyline points={points} fill="none" stroke="currentColor" strokeWidth="2" /></svg> : <p>Нет полного ряда</p>}<small>{number(series[0]?.[metric])} → {number(series.at(-1)?.[metric])}</small></div>;
}

function Evidence({signal, title}: {signal: Signal; title: string}) {
  return <div className="detector-evidence"><h3>{signal.matched ? "✓ " : "· "}{title}</h3><p>{reasons[signal.reason] ?? signal.reason}{signal.missing?.length ? `: ${signal.missing.join(", ")}` : ""}</p>
    {signal.checks && <ul>{signal.checks.map(check => <li key={check.metric}>{check.passed ? "✓" : "·"} {labels[check.metric] ?? check.metric}: {check.change_percent !== undefined ? `${number(check.change_percent)}% (порог ${number(check.target_percent)}%, ${check.monotonic ? "направление устойчивое" : "направление менялось"})` : `${number(check.value)} ${check.operator} ${number(check.target)}`}</li>)}</ul>}
  </div>;
}

export default function Recommendations({refreshKey}: {refreshKey: number}) {
  const [data, setData] = useState<Data | null>(null);
  const [category, setCategory] = useState("");
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState("");
  const [draft, setDraft] = useState<Settings | null>(null);
  const [revision, setRevision] = useState(0);
  const [operator, setOperator] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const load = useCallback(async () => {
    try {const query = new URLSearchParams({offset: String(offset)}); if (category) query.set("category", category);
      const response = await fetch(`/api/recommendations?${query}`, {cache: "no-store"}); const payload = await response.json();
      if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : "Рекомендации недоступны"); setData(payload); setError(""); return payload as Data;
    } catch (cause) {setError(cause instanceof Error ? cause.message : "Рекомендации недоступны");}
  }, [category, offset]);
  useEffect(() => {void load();}, [load, refreshKey]);
  useEffect(() => {if (data && draft === null) {setDraft(data.settings); setRevision(data.revision);}}, [data, draft]);
  useEffect(() => {void fetch("/api/capabilities").then(response => response.json()).then(payload => setOperator(!!payload.operator_enabled)).catch(() => {});}, []);
  async function save() {
    if (!draft) return; setSaving(true); setMessage("");
    try {const response = await fetch("/api/recommendations/settings", {method: "PUT", headers: {"Content-Type": "application/json"}, body: JSON.stringify({settings: draft, revision})}); const payload = await response.json();
      if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : "Проверьте значения порогов");
      setDraft(payload.settings); setRevision(payload.revision); setOffset(0); setMessage("Пороги сохранены. Рекомендации пересчитаны."); await load();
    } catch (cause) {setMessage(cause instanceof Error ? cause.message : "Настройки недоступны");} finally {setSaving(false);}
  }
  const fields: [keyof Settings, string, boolean][] = [["minimum_spend", "Минимальный расход", false], ["minimum_conversions", "Минимум конверсий", true], ["target_roi", "Целевой ROI, %", false], ["target_cpl", "Целевой CPL", false], ["loser_spend_multiplier", "Stop: расход × CPL", false], ["fatigue_days", "Fatigue: дней", true], ["ctr_decline_percent", "Снижение CTR, %", false], ["cpc_increase_percent", "Рост CPC, %", false], ["frequency_increase_percent", "Рост frequency, %", false], ["cpl_increase_percent", "Рост CPL, %", false], ["minimum_daily_impressions", "Показы в день, минимум", true], ["minimum_daily_clicks", "Клики в день, минимум", true], ["current_max_age_minutes", "Свежесть текущих данных, мин", true], ["historical_max_age_hours", "Свежесть истории, ч", true]];
  return <section>
    <p className="table-note">Сигналы рассчитываются по сохранённой статистике. Scale и Stop — кандидаты для проверки; реклама здесь не изменяется. Fatigue использует завершённые дни.</p>
    {error && <div className="notice error" role="alert">{error}</div>}
    <div className="cards recommendation-counts">{categories.map(([key, title]) => <button key={key} className={`card ${category === key ? "selected" : ""}`} onClick={() => {setCategory(category === key ? "" : key); setOffset(0);}}><span>{title}</span><strong>{data ? data.counts[key] : "—"}</strong></button>)}</div>
    {data && <p className="table-note">{data.settings.level} · {data.settings.window} · {data.settings.currency} · расчёт {new Date(data.as_of).toLocaleString("ru-RU")}</p>}
    {draft && <details className="actionpanel"><summary>Пороги и параметры детекторов</summary><div className="filterbar">
      <label>Уровень<select value={draft.level} onChange={event => setDraft({...draft, level: event.target.value})}><option value="adset">Ad Set</option><option value="campaign">Campaign</option><option value="ad">Ad</option><option value="creative">Creative</option></select></label>
      <label>Окно Winner / Loser<select value={draft.window} onChange={event => setDraft({...draft, window: event.target.value})}>{["today", "yesterday", "last3", "last7", "last14", "last30"].map(value => <option key={value}>{value}</option>)}</select></label>
      <label>Валюта целей<input value={draft.currency} maxLength={3} onChange={event => setDraft({...draft, currency: event.target.value.toUpperCase()})} /></label>
      {fields.map(([key, label, integer]) => <label key={key}>{label}<input type="number" step={integer ? "1" : "any"} value={draft[key]} onChange={event => setDraft({...draft, [key]: integer ? Number(event.target.value) : event.target.value})} /></label>)}
      <button disabled={!operator || saving} onClick={() => void save()}>Сохранить пороги</button><button disabled={!data || saving} onClick={() => void load().then(saved => {if (saved) {setDraft(saved.settings); setRevision(saved.revision);}})}>Загрузить сохранённые</button>
    </div><p className="table-note">Денежные пороги относятся к выбранной валюте. День определяется по часовому поясу кабинета. Для Fatigue нужны все дни и четыре сопоставимых ряда. Настройки сохраняет оператор.</p>{message && <p role="status">{message}</p>}</details>}
    <div className="recommendation-list">{data?.rows.map(item => <article className="actionpanel" key={`${item.id}-${item.currency}-${item.timezone}`}><div className="group-heading"><h2>{item.name}<span>{item.level} · {item.currency} · {item.timezone}</span></h2><span className={`badge recommendation-${item.category}`}>{categories.find(([key]) => key === item.category)?.[2]}</span></div>
      <p>Spend {number(item.metrics.spend)} · Conversions {number(item.metrics.conversions)} · Leads {number(item.metrics.leads)} · ROI {number(item.metrics.roi)}% · CPL {number(item.metrics.cpl)}</p><p className="table-note">Период: {item.window.join(" → ")}{!item.current_fresh && " · данные периода неполные или требуют обновления"}</p>
      <details><summary>Почему появился сигнал</summary><div className="detector-grid"><Evidence title="Winner" signal={item.signals.winner} /><Evidence title="Loser" signal={item.signals.loser} /><Evidence title="Fatigue" signal={item.signals.fatigue} /></div>
        {!!item.signals.fatigue.series?.length && <><p className="table-note">Fatigue: {item.signals.fatigue.window?.join(" → ")}</p><div className="trend-grid">{(["ctr", "cpc", "frequency", "cpl"] as const).map(metric => <Trend key={metric} metric={metric} series={item.signals.fatigue.series!} />)}</div><div className="tablewrap"><table><thead><tr><th>День</th><th>CTR, %</th><th>CPC</th><th>Frequency</th><th>CPL</th></tr></thead><tbody>{item.signals.fatigue.series.map(point => <tr key={point.date}><td>{point.date}</td>{(["ctr", "cpc", "frequency", "cpl"] as const).map(metric => <td key={metric}>{number(point[metric])}</td>)}</tr>)}</tbody></table></div></>}
      </details></article>)}</div>
    {data && !data.rows.length && <div className="empty"><h2>Нет рекомендаций по выбранным параметрам</h2><p>После загрузки статистики здесь появятся сигналы и причины. Сейчас показаны только реальные сохранённые данные.</p></div>}
    <div className="pagination"><button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset-100))}>Назад</button><button disabled={data?.next_offset === null || !data} onClick={() => data?.next_offset !== null && data?.next_offset !== undefined && setOffset(data.next_offset)}>Далее</button></div>
  </section>;
}
