"use client";

import { useEffect, useState } from "react";
import SessionBar from "./SessionBar";
import StatisticsTable, { type StatisticsRow } from "./StatisticsTable";
import ColumnManager from "./ColumnManager";
import { useColumnPreferences } from "../lib/use-column-preferences";
import { manualLabel, manualRead, manualWrite } from "../lib/manual-control";

type Provider = {
  provider: string;
  health: string;
  connected: boolean;
  write_credentials: boolean;
  read_credentials: boolean;
  required_permission: string;
  operations: Record<string, string>;
  last_error: string | null;
  last_checked_at: string | null;
};
type Settings = {
  can_control: boolean;
  is_admin: boolean;
  actions_enabled: boolean;
  local_read_only: boolean;
  providers: Provider[];
  accounts: { id: string; name: string; provider: string }[];
  operators: { id: string; login: string; can_control: boolean }[];
};
type Ad = StatisticsRow & {
  id: string;
  meta_ad_id: string;
  account_id: string;
  provider: "metricflow" | "meta";
  status: string;
  hierarchy: (string | null)[];
  recommendation: { simulation_id: string; status: string } | null;
};
type Action = {
  id: string;
  revision: number;
  status: string;
  display_status: string;
  operation: string;
  created_at: string;
  actor: string;
  provider: string;
  reason: string;
  meta_ad_id: string;
  target_status: string;
  expected_status: string;
  expires_at: string;
  captured: {
    name: string;
    account_name: string;
    status_refreshed_at: string | null;
  };
  preflight: {
    local_allowed: boolean;
    checked_at: string;
    reason_codes: string[];
    blocking_reasons: string[];
  } | null;
  result: string | null;
  events: { event: string; at: string; actor_id: string }[];
};
type Catalog = {
  rows: Ad[];
  total: number;
  next_offset: number | null;
  start: string;
  end: string;
};
const time = (value: string | null) =>
  value ? new Date(value).toLocaleString("ru-RU") : "Неизвестно";

export default function ManualControl({
  settingsOnly = false,
}: {
  settingsOnly?: boolean;
}) {
  const [settings, setSettings] = useState<Settings | null>(null),
    [table, setTable] = useState<Catalog | null>(null),
    [history, setHistory] = useState<Action[]>([]),
    [active, setActive] = useState<Action | null>(null),
    [selected, setSelected] = useState<Ad | null>(null);
  const [account, setAccount] = useState(""),
    [campaign, setCampaign] = useState(""),
    [adset, setAdset] = useState(""),
    [search, setSearch] = useState(""),
    [status, setStatus] = useState(""),
    [reason, setReason] = useState(""),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [busy, setBusy] = useState(false),
    [offset, setOffset] = useState(0);
  const columns = useColumnPreferences("manual_ad");
  useEffect(() => {
    void Promise.all([
      manualRead<Settings>("/settings"),
      manualRead<{ requests: Action[] }>("/requests"),
    ])
      .then(([s, h]) => {
        setSettings(s);
        setHistory(h.requests);
        const key = new URLSearchParams(window.location.search).get("request");
        if (key)
          void manualRead<Action>("/requests/" + key)
            .then(setActive)
            .catch((e) => setError(e.message));
      })
      .catch((e) => setError(e.message));
  }, []);
  useEffect(() => {
    if (settingsOnly) return;
    setTable(null);
    void manualRead<Catalog>(
      "/ads?offset=" +
        offset +
        (account ? "&account_id=" + encodeURIComponent(account) : ""),
    )
      .then(setTable)
      .catch((e) => setError(e.message));
  }, [account, offset, settingsOnly]);
  async function run(fn: () => Promise<void>) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await fn();
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : "Не удалось выполнить локальную операцию",
      );
    } finally {
      setBusy(false);
    }
  }
  async function refreshHistory() {
    setHistory(
      (await manualRead<{ requests: Action[] }>("/requests")).requests,
    );
  }
  async function prepare(operation: "PAUSE_AD" | "ENABLE_AD") {
    if (!selected) return;
    await run(async () => {
      const r = await manualWrite<Action>(
        "/requests",
        {
          entity_id: selected.id,
          account_id: selected.account_id,
          meta_ad_id: selected.meta_ad_id,
          provider: selected.provider,
          operation,
          expected_status: selected.status,
          reason,
          simulation_id: null,
        },
        crypto.randomUUID(),
      );
      setActive(r);
      setNotice("Черновик сохранён. Рекламное объявление не изменено.");
      await refreshHistory();
    });
  }
  async function transition(event: string) {
    if (!active) return;
    await run(async () => {
      const r = await manualWrite<Action>(
        "/requests/" + active.id + "/" + event,
        { revision: active.revision },
      );
      setActive(r);
      setNotice(
        r.status === "SIMULATED"
          ? "Команда проверена в режиме симуляции. Рекламное объявление не изменено."
          : "Состояние команды: " + manualLabel(r.status),
      );
      await refreshHistory();
    });
  }
  let rows = (table?.rows ?? [])
    .filter(
      (r) =>
        (!campaign || r.hierarchy[1] === campaign) &&
        (!adset || r.hierarchy[0] === adset) &&
        (!status || r.status === status) &&
        (!search ||
          [r.name, r.meta_ad_id, r.account_name].some((v) =>
            String(v).toLocaleLowerCase().includes(search.toLocaleLowerCase()),
          )),
    )
    .map((r) => {
      const {
        hierarchy: _hierarchy,
        recommendation: _recommendation,
        ...flat
      } = r;
      return {
        ...flat,
        rule_recommendation: r.recommendation
          ? "Кандидат на отключение · DRY RUN"
          : "Нет сохранённой рекомендации",
        status:
          r.status === "ACTIVE"
            ? "Активен"
            : r.status === "PAUSED"
              ? "Остановлен"
              : r.status,
        effective_status: r.effective_status ?? "Неизвестно",
      };
    });
  const sort = columns.config.sorting;
  if (sort)
    rows = rows.toSorted((a, b) => {
      const x = a[sort.key as keyof typeof a],
        y = b[sort.key as keyof typeof b];
      if (x == null) return 1;
      if (y == null) return -1;
      const n = Number(x),
        m = Number(y),
        difference =
          Number.isFinite(n) && Number.isFinite(m)
            ? n - m
            : String(x).localeCompare(String(y), "ru");
      return sort.direction === "asc" ? difference : -difference;
    });
  const groups = (index: number) =>
    Array.from(
      new Set(
        (table?.rows ?? [])
          .map((r) => r.hierarchy[index])
          .filter((v): v is string => Boolean(v)),
      ),
    );
  return (
    <main className="dashboard manual-surface">
      <header className="topbar">
        <h1>
          {settingsOnly
            ? "Настройки управления рекламой"
            : "Управление рекламой"}
        </h1>
        <SessionBar />
      </header>
      <p className="notice">
        WRITE выключен. Доступна только локальная подготовка и симуляция.
        Подтверждение не отправляет команду провайдеру.
      </p>
      <nav>
        <a href="/manual-control">Объявления и история</a> ·{" "}
        <a href="/settings/manual-control">Настройки управления рекламой</a>
      </nav>
      {error && <p role="alert">{error}</p>}
      {notice && (
        <p role="status" className="notice">
          {notice}
        </p>
      )}
      {settingsOnly && settings && (
        <section aria-label="Безопасность управления">
          <h2>Безопасность управления</h2>
          <p>
            Глобальный WRITE: выключен · ACTIONS_ENABLED:{" "}
            {String(settings.actions_enabled)} · LOCAL READ ONLY:{" "}
            {String(settings.local_read_only)}. Action provider: отключён.
          </p>
          {settings.providers.map((p) => (
            <article key={p.provider}>
              <h3>{p.provider === "metricflow" ? "MetricFlow" : "Meta"}</h3>
              <p>
                Подключение: {p.connected ? p.health : "DISCONNECTED"} · READ
                credentials: {p.read_credentials ? "подключены" : "нет"} ·
                отдельные WRITE credentials:{" "}
                {p.write_credentials ? "настроены, не проверены" : "нет"} ·
                разрешение: {p.required_permission} (не подтверждено).
              </p>
              <p>
                Pause / Enable: {manualLabel(p.operations.PAUSE_AD)} · бюджет и
                ставка: будущая фаза.
              </p>
              <p>
                Последняя проверка READ: {time(p.last_checked_at)} · ошибка:{" "}
                {p.last_error ?? "нет"}. WRITE-проверок и рекламных запросов не
                выполнялось.
              </p>
            </article>
          ))}
          {settings.is_admin && (
            <fieldset>
              <legend>
                Отдельное разрешение OPERATOR на локальные ручные команды
              </legend>
              {settings.operators.map((u) => (
                <label key={u.id}>
                  <input
                    type="checkbox"
                    checked={u.can_control}
                    disabled={busy}
                    onChange={(e) =>
                      void run(async () => {
                        await manualWrite(
                          "/grants",
                          { user_id: u.id, can_edit: e.target.checked },
                          undefined,
                          "PUT",
                        );
                        setSettings(await manualRead<Settings>("/settings"));
                      })
                    }
                  />
                  {u.login}
                </label>
              ))}
            </fieldset>
          )}
          <h3>История локальных проверок</h3>
          {history
            .filter((r) => r.preflight)
            .map((r) => (
              <p key={r.id}>
                {time(r.preflight!.checked_at)} · {r.captured.name} ·{" "}
                {r.provider} · {manualLabel(r.display_status)} ·{" "}
                {r.preflight!.local_allowed
                  ? "Локальная симуляция допустима"
                  : "Локальная симуляция заблокирована"}
              </p>
            ))}
          {!history.some((r) => r.preflight) && (
            <p>Локальных проверок пока нет.</p>
          )}
        </section>
      )}
      {!settingsOnly && (
        <>
          <section aria-label="Объявления">
            <h2>Объявления</h2>
            <p>
              Семь завершённых дней: {table?.start ?? "…"} — {table?.end ?? "…"}{" "}
              · Europe/Moscow; календарные дни кабинета. Неизвестные значения
              отображаются как «—».
            </p>
            <div className="filters">
              <label>
                Кабинет
                <select
                  value={account}
                  onChange={(e) => {
                    setAccount(e.target.value);
                    setOffset(0);
                    setCampaign("");
                    setAdset("");
                    setSelected(null);
                  }}
                >
                  <option value="">Все кабинеты</option>
                  {settings?.accounts.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name} · {a.provider}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Кампания
                <select
                  value={campaign}
                  onChange={(e) => {
                    setCampaign(e.target.value);
                    setAdset("");
                  }}
                >
                  <option value="">Все кампании на странице</option>
                  {groups(1).map((id) => (
                    <option key={id} value={id}>
                      {String(
                        table?.rows.find((r) => r.hierarchy[1] === id)
                          ?.campaign_name ?? id,
                      )}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Группа объявлений
                <select
                  value={adset}
                  onChange={(e) => setAdset(e.target.value)}
                >
                  <option value="">Все группы на странице</option>
                  {groups(0).map((id) => (
                    <option key={id} value={id}>
                      {String(
                        table?.rows.find((r) => r.hierarchy[0] === id)
                          ?.adset_name ?? id,
                      )}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Статус
                <select
                  value={status}
                  onChange={(e) => setStatus(e.target.value)}
                >
                  <option value="">Все статусы</option>
                  <option value="ACTIVE">Активен</option>
                  <option value="PAUSED">Остановлен</option>
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
              <button
                disabled={busy}
                onClick={() =>
                  void run(async () => {
                    setTable(
                      await manualRead<Catalog>(
                        "/ads?offset=" +
                          offset +
                          (account ? "&account_id=" + account : ""),
                      ),
                    );
                  })
                }
              >
                Обновить из БД
              </button>
            </div>
            <ColumnManager scope="manual_ad" controller={columns} rows={rows} />
            <StatisticsTable
              scope="manual_ad"
              rows={rows}
              config={columns.config}
              change={columns.change}
              commit={() => void columns.persist().catch(() => {})}
              disabled={!columns.ready || columns.busy}
              rowActions={(r) => (
                <button
                  onClick={() =>
                    setSelected(table?.rows.find((a) => a.id === r.id) ?? null)
                  }
                >
                  Подготовить команду
                </button>
              )}
              onName={(r) =>
                setSelected(table?.rows.find((a) => a.id === r.id) ?? null)
              }
            />
            <p>
              Всего объявлений: {table?.total ?? "…"} · на странице:{" "}
              {rows.length}. Нажмите название для подготовки команды.
            </p>
            <button
              disabled={offset === 0 || busy}
              onClick={() => setOffset(Math.max(0, offset - 100))}
            >
              Предыдущие
            </button>
            <button
              disabled={table?.next_offset == null || busy}
              onClick={() => setOffset(table!.next_offset!)}
            >
              Следующие
            </button>
            {selected && (
              <article aria-label="Выбранное объявление">
                <h3>{String(selected.name)}</h3>
                <p>
                  Ad ID: {selected.meta_ad_id} · кабинет:{" "}
                  {String(selected.account_name)} · {selected.provider} ·
                  статус: {selected.status} · источник статуса:{" "}
                  {selected.provider} · обновлён:{" "}
                  {time(selected.status_refreshed_at as string | null)}
                </p>
                <label>
                  Причина ручной команды
                  <textarea
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    maxLength={1000}
                  />
                </label>
                <button
                  disabled={
                    !settings?.can_control ||
                    busy ||
                    !reason.trim() ||
                    !["ACTIVE", "PAUSED"].includes(selected.status)
                  }
                  onClick={() => void prepare("PAUSE_AD")}
                >
                  Подготовить отключение
                </button>
                <button
                  disabled={
                    !settings?.can_control ||
                    busy ||
                    !reason.trim() ||
                    !["ACTIVE", "PAUSED"].includes(selected.status)
                  }
                  onClick={() => void prepare("ENABLE_AD")}
                >
                  Подготовить включение
                </button>
                {!settings?.can_control && (
                  <p>Подготовка команд требует отдельного разрешения.</p>
                )}
              </article>
            )}
          </section>
          {active && (
            <section aria-label="Подготовленное действие">
              <h2>Подготовленное действие</h2>
              <h3>{active.captured.name}</h3>
              <p>
                {manualLabel(active.operation)} · {active.provider} · Ad ID:{" "}
                {active.meta_ad_id} · кабинет: {active.captured.account_name}
              </p>
              <p>
                Ожидаемый статус: {active.expected_status} · целевой:{" "}
                {active.target_status} · обновление:{" "}
                {time(active.captured.status_refreshed_at)}
              </p>
              <p>
                Состояние: <strong>{manualLabel(active.display_status)}</strong>{" "}
                · {active.status} · причина: {active.reason}
              </p>
              <p>
                Request ID: {active.id} · срок: {time(active.expires_at)} ·
                проверка: {time(active.preflight?.checked_at ?? null)}
              </p>
              {active.preflight && (
                <>
                  <p>
                    Локальная симуляция:{" "}
                    {active.preflight.local_allowed
                      ? "допустима"
                      : "заблокирована"}{" "}
                    · LIVE: заблокирован.
                  </p>
                  <ul>
                    {active.preflight.reason_codes.map((code) => (
                      <li key={code}>{manualLabel(code)}</li>
                    ))}
                  </ul>
                </>
              )}
              {settings?.can_control &&
                !["SIMULATED", "CANCELLED", "EXPIRED"].includes(
                  active.display_status,
                ) && (
                  <>
                    <button
                      disabled={busy || active.status === "CONFIRMED"}
                      onClick={() => void transition("preflight")}
                    >
                      Проверить команду
                    </button>
                    <button
                      disabled={
                        busy ||
                        active.status !== "BLOCKED" ||
                        !active.preflight?.local_allowed
                      }
                      onClick={() => void transition("confirm")}
                    >
                      Подтвердить намерение для симуляции
                    </button>
                    <button
                      disabled={busy || active.status !== "CONFIRMED"}
                      onClick={() => void transition("simulate")}
                    >
                      Выполнить локальную симуляцию
                    </button>
                    <button
                      disabled={busy}
                      onClick={() => void transition("cancel")}
                    >
                      Отменить команду
                    </button>
                  </>
                )}
              {active.status === "SIMULATED" && (
                <p role="status">
                  Команда проверена в режиме симуляции. Рекламное объявление не
                  изменено.
                </p>
              )}
              <h3>Журнал переходов</h3>
              <ol>
                {active.events.map((e, i) => (
                  <li key={i}>
                    {time(e.at)} · {manualLabel(e.event)} · инициатор:{" "}
                    {e.actor_id}
                  </li>
                ))}
              </ol>
            </section>
          )}
          <section aria-label="История операций">
            <h2>История операций</h2>
            {history.length === 0 && <p>Локальных команд пока нет.</p>}
            {history.map((r) => (
              <article key={r.id}>
                <button
                  onClick={() =>
                    void run(async () =>
                      setActive(await manualRead<Action>("/requests/" + r.id)),
                    )
                  }
                >
                  {r.captured.name} · {manualLabel(r.operation)} ·{" "}
                  {manualLabel(r.display_status)}
                </button>
                <p>
                  {time(r.created_at)} · {r.actor} · {r.provider} ·{" "}
                  {r.result
                    ? manualLabel(r.result)
                    : "Реального исполнения нет"}{" "}
                  · Request ID: {r.id}
                </p>
              </article>
            ))}
          </section>
        </>
      )}
    </main>
  );
}
