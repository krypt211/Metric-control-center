"use client";
import { useCallback, useEffect, useState } from "react";
import { navigationEvent, navigateWithinPage } from "./navigation";

export function useNavigationLocation() {
  const [location, setLocation] = useState({ pathname: "", search: "" });
  useEffect(() => {
    const update = () => setLocation({ pathname: window.location.pathname, search: window.location.search });
    update();
    window.addEventListener("popstate", update);
    window.addEventListener(navigationEvent, update);
    return () => {
      window.removeEventListener("popstate", update);
      window.removeEventListener(navigationEvent, update);
    };
  }, []);
  return location;
}
export function usePageTab(allowed: readonly string[], fallback: string): [string, (tab: string) => void] {
  const [tab, setTab] = useState(fallback);
  useEffect(() => {
    const update = () => {
      const value = new URLSearchParams(window.location.search).get("tab");
      setTab(value && allowed.includes(value) ? value : fallback);
    };
    update();
    window.addEventListener("popstate", update);
    window.addEventListener(navigationEvent, update);
    return () => {
      window.removeEventListener("popstate", update);
      window.removeEventListener(navigationEvent, update);
    };
  }, [allowed, fallback]);
  const change = useCallback((value: string) => {
    if (!allowed.includes(value)) return;
    const url = new URL(window.location.href);
    url.searchParams.set("tab", value);
    navigateWithinPage(url.pathname + url.search + url.hash);
  }, [allowed]);
  return [tab, change];
}
