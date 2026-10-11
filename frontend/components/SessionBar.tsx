"use client";
import { useEffect, useState } from "react";
import { flushColumnPreferences, serializeAuthenticatedWrite } from "../lib/use-column-preferences";
import AppNavigation from "./AppNavigation";
export default function SessionBar() {
  const [user, setUser] = useState<{ login: string; role: string } | null>(null);
  const [error, setError] = useState(""), [busy, setBusy] = useState(false);
  useEffect(() => {
    const abort = new AbortController();
    void fetch("/api/auth/me", { cache: "no-store", signal: abort.signal }).then(async (response) => {
      if (response.status === 401) { window.location.assign("/login"); return; }
      if (response.ok) setUser((await response.json()).user);
      else throw new Error();
    }).catch(() => { if (!abort.signal.aborted) setError("Не удалось загрузить сессию. Обновите страницу."); });
    return () => abort.abort();
  }, []);
  async function logout() {
    setBusy(true);
    try {
      try { await flushColumnPreferences(); }
      catch { if (!window.confirm("Настройки колонок не сохранены. Всё равно выйти?")) return; }
      const response = await serializeAuthenticatedWrite(async () => {
        const csrf = await fetch("/api/auth/csrf", { cache: "no-store" });
        if (!csrf.ok) throw new Error();
        return fetch("/api/auth/logout", { method: "POST", headers: { "X-CSRF-Token": (await csrf.json()).csrf_token } });
      });
      if (response.ok || response.status === 401) window.location.assign("/login");
      else throw new Error();
    } catch { setError("Не удалось завершить сессию. Повторите выход."); }
    finally { setBusy(false); }
  }
  return <AppNavigation user={user} busy={busy} error={error} logout={() => void logout()} />;
}
