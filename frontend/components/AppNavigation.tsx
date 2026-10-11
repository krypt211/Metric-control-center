"use client";
import { useEffect, useRef, useState, type KeyboardEvent, type MouseEvent } from "react";
import { isNavigationActive, navigationForRole, navigationHref, navigateWithinPage, settingsCategories, type NavigationItem } from "../lib/navigation";
import { useNavigationLocation } from "../lib/use-page-tab";

type Props = { user: { login: string; role: string } | null; busy: boolean; error: string; logout: () => void };
function Icon({ name }: { name: string }) {
  const paths: Record<string, string> = {
    gear: "M9 3h6l1 3 3 1 2 5-2 5-3 1-1 3H9l-1-3-3-1-2-5 2-5 3-1 1-3 M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0",
    menu: "M4 6h16M4 12h16M4 18h16", down: "m6 9 6 6 6-6",
    table: "M3 4h18v16H3zM3 9h18M9 9v11", chart: "M4 4v16h16M8 15l4-5 4 2 4-6",
    plug: "M8 3v5M16 3v5M6 8h12v3a6 6 0 0 1-12 0zM12 17v4",
    shield: "m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6z",
    users: "M9 8a3 3 0 1 0-6 0 3 3 0 0 0 6 0M2 21v-4a4 4 0 0 1 8 0v4M17 5a3 3 0 0 1 0 6M15 13a4 4 0 0 1 7 4v4",
  };
  return <svg className="nav-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name] ?? paths.table} /></svg>;
}
export default function AppNavigation({ user, busy, error, logout }: Props) {
  const { pathname, search } = useNavigationLocation();
  const [open, setOpen] = useState<"settings" | "mobile" | null>(null);
  const header = useRef<HTMLElement>(null);
  const settingsButton = useRef<HTMLButtonElement>(null);
  const mobileButton = useRef<HTMLButtonElement>(null);
  const focusEdge = useRef<"first" | "last" | null>(null);
  const desktop = navigationForRole(user?.role ?? null);
  const mobile = navigationForRole(user?.role ?? null, true);
  const settings = desktop.filter((entry) => entry.category !== "main");

  useEffect(() => {
    if (!open) return;
    const trigger = open === "settings" ? settingsButton : mobileButton;
    const panel = header.current?.querySelector<HTMLElement>("#mcc-" + open + "-panel");
    if (focusEdge.current) {
      const links = panel?.querySelectorAll<HTMLElement>("a[href],button:not(:disabled)");
      const index = focusEdge.current === "last" ? (links?.length ?? 1) - 1 : 0;
      links?.[index]?.focus(); focusEdge.current = null;
    }
    const pointer = (event: PointerEvent) => {
      if (!panel?.contains(event.target as Node) && !trigger.current?.contains(event.target as Node)) setOpen(null);
    };
    const focus = (event: FocusEvent) => {
      if (!panel?.contains(event.target as Node) && !trigger.current?.contains(event.target as Node)) setOpen(null);
    };
    const escape = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); setOpen(null); trigger.current?.focus(); }
    };
    const resize = () => setOpen(null);
    document.addEventListener("pointerdown", pointer);
    document.addEventListener("focusin", focus);
    document.addEventListener("keydown", escape);
    window.addEventListener("resize", resize);
    return () => {
      document.removeEventListener("pointerdown", pointer);
      document.removeEventListener("focusin", focus);
      document.removeEventListener("keydown", escape);
      window.removeEventListener("resize", resize);
    };
  }, [open]);
  useEffect(() => { setOpen(null); }, [pathname, search]);

  function triggerKey(event: KeyboardEvent<HTMLButtonElement>, target: "settings" | "mobile") {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    event.preventDefault(); focusEdge.current = event.key === "ArrowUp" ? "last" : "first";
    if (open === target) {
      const links = header.current?.querySelectorAll<HTMLElement>("#mcc-" + target + "-panel a[href],#mcc-" + target + "-panel button:not(:disabled)");
      links?.[event.key === "ArrowUp" ? links.length - 1 : 0]?.focus(); focusEdge.current = null;
    } else setOpen(target);
  }
  function panelKey(event: KeyboardEvent<HTMLElement>) {
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
    const links = Array.from(event.currentTarget.querySelectorAll<HTMLElement>("a[href],button:not(:disabled)"));
    const current = links.indexOf(document.activeElement as HTMLElement);
    const next = event.key === "Home" ? 0 : event.key === "End" ? links.length - 1 :
      (current + (event.key === "ArrowDown" ? 1 : -1) + links.length) % links.length;
    event.preventDefault(); links[next]?.focus();
  }
  function follow(event: MouseEvent<HTMLAnchorElement>, entry: NavigationItem) {
    if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    if (entry.id === "columns") {
      const button = document.querySelector<HTMLButtonElement>("[data-open-columns]");
      if (button) { event.preventDefault(); setOpen(null); button.click(); return; }
    }
    const href = navigationHref(entry, pathname, search);
    if (new URL(href, window.location.href).pathname === window.location.pathname) {
      event.preventDefault(); navigateWithinPage(href);
    }
    setOpen(null);
  }
  function link(entry: NavigationItem) {
    const active = isNavigationActive(entry, pathname, search);
    return <a key={entry.id} href={navigationHref(entry, pathname, search)} aria-current={active ? "page" : undefined} onClick={(event) => follow(event, entry)}>{entry.category !== "main" && <Icon name={entry.icon} />}<span>{entry.label}</span></a>;
  }
  function groups(items: NavigationItem[]) {
    return settingsCategories.map((category) => {
      const entries = items.filter((entry) => entry.category === category.id);
      return entries.length ? <div className="nav-settings-group" key={category.id}><p>{category.label}</p>{entries.map(link)}</div> : null;
    });
  }
  function userControls() {
    return <><span className="nav-user" title={user?.login}>{user?.login}<small>{user?.role.toUpperCase()}</small></span><button disabled={busy} onClick={logout}>{busy ? "Выход…" : "Выйти"}</button></>;
  }
  return <header className="topbar app-navigation" ref={header}>
    <a className="brand" href="/?tab=overview" aria-label="MCC — обзор">MCC</a>
    <nav className="nav-primary" aria-label="Основные разделы">{desktop.filter((entry) => entry.category === "main").map(link)}</nav>
    <div className="nav-desktop-actions">
      <button ref={settingsButton} type="button" className={"nav-settings-toggle" + (settings.some((entry) => isNavigationActive(entry, pathname, search)) ? " active" : "")} aria-label="Настройки" aria-expanded={open === "settings"} aria-controls="mcc-settings-panel" disabled={!user} onClick={() => setOpen(open === "settings" ? null : "settings")} onKeyDown={(event) => triggerKey(event, "settings")}><Icon name="gear" />Настройки<Icon name="down" /></button>
      {open === "settings" && <nav id="mcc-settings-panel" className="nav-popup" aria-label="Настройки приложения" onKeyDown={panelKey}>{groups(settings)}</nav>}
      {userControls()}
    </div>
    <button ref={mobileButton} type="button" className="nav-mobile-toggle" aria-label="Меню" aria-expanded={open === "mobile"} aria-controls="mcc-mobile-panel" disabled={!user} onClick={() => setOpen(open === "mobile" ? null : "mobile")} onKeyDown={(event) => triggerKey(event, "mobile")}><Icon name="menu" />Меню</button>
    {open === "mobile" && <nav id="mcc-mobile-panel" className="nav-popup nav-mobile-panel" aria-label="Мобильная навигация" onKeyDown={panelKey}>
      <div className="nav-settings-group"><p>Разделы</p>{mobile.filter((entry) => entry.category === "main").map(link)}</div>
      <h2>Настройки</h2>{groups(mobile)}<div className="nav-mobile-session">{userControls()}</div>
    </nav>}
    {error && <span className="nav-session-error" role="alert">{error}</span>}
  </header>;
}
