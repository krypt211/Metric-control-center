export type NavigationRole = "admin" | "operator" | "viewer";
export type NavigationCategory = "main" | "general" | "control" | "system";
export type NavigationItem = {
  id: string;
  label: string;
  route: string;
  icon: string;
  category: NavigationCategory;
  roles: readonly NavigationRole[];
  desktop: boolean;
  mobile: boolean;
  match: { pathname: string; tab?: string } | null;
};
const allRoles: readonly NavigationRole[] = ["admin", "operator", "viewer"];
const item = (
  id: string, label: string, route: string, icon: string,
  category: NavigationCategory = "main", roles = allRoles,
  match: NavigationItem["match"] = { pathname: route.split("?")[0] },
): NavigationItem => ({ id, label, route, icon, category, roles, desktop: true, mobile: true, match });

// Desktop and mobile consume the same registry; all targets already exist.
export const navigationItems: readonly NavigationItem[] = [
  item("overview", "Обзор", "/?tab=overview", "overview", "main", allRoles, { pathname: "/", tab: "overview" }),
  item("statistics", "Объявления", "/?tab=statistics", "table", "main", allRoles, { pathname: "/", tab: "statistics" }),
  item("economics", "Экономика", "/economics", "chart", "general"),
  item("rules", "Правила", "/rules", "rules"),
  item("history", "История", "/manual-control#history", "list"),
  item("manual", "Управление", "/manual-control", "shield", "control", allRoles, null),
  item("recommendations", "Рекомендации", "/recommendations", "list", "control"),
  item("creatives", "Креативы", "/?tab=creatives", "image", "general", allRoles, { pathname: "/", tab: "creatives" }),
  item("tracker", "Трекер", "/?tab=tracker", "chart", "general", allRoles, { pathname: "/", tab: "tracker" }),
  item("columns", "Колонки и наборы", "/?tab=statistics&columns=1", "table", "general", allRoles, null),
  item("profiles", "Экономические профили", "/economics?tab=profiles", "chart", "general", allRoles, { pathname: "/economics", tab: "profiles" }),
  item("connections", "API и подключения", "/settings/connections", "plug", "general", ["admin"]),
  item("action-safety", "Безопасность действий", "/settings/manual-control", "shield", "control"),
  item("admin", "Администрирование", "/admin", "users", "system", ["admin"]),
];
export const settingsCategories = [
  { id: "general", label: "Общие" },
  { id: "control", label: "Управление" },
  { id: "system", label: "Система" },
] as const;
export const dashboardTabs = ["overview", "statistics", "creatives", "tracker", "recommendations", "copilot", "rules", "audit"] as const;
export const economicsTabs = ["stats", "profiles", "approval"] as const;
export const legacyDashboardTabs = [
  { id: "recommendations", label: "Рекомендации" },
  { id: "copilot", label: "AI Copilot" },
  { id: "rules", label: "Правила" },
  { id: "audit", label: "Журнал" },
] as const;
export const navigationEvent = "mcc:navigation";

export function navigationForRole(role: string | null, mobile = false): NavigationItem[] {
  return navigationItems.filter((entry) =>
    entry.roles.some((allowed) => allowed === role) && (mobile ? entry.mobile : entry.desktop),
  );
}
export function isNavigationActive(entry: NavigationItem, pathname: string, search: string): boolean {
  if (!entry.match || entry.match.pathname !== pathname) return false;
  const tab = new URLSearchParams(search).get("tab") ?? (pathname === "/" ? "overview" : "stats");
  return !entry.match.tab || entry.match.tab === tab;
}
export function navigationHref(entry: NavigationItem, pathname: string, search: string): string {
  const target = new URL(entry.route, "http://navigation.local");
  if (target.pathname !== pathname || !target.search) return entry.route;
  const params = new URLSearchParams(search);
  target.searchParams.forEach((value, key) => params.set(key, value));
  return pathname + "?" + params.toString();
}
export function navigateWithinPage(href: string): void {
  window.history.pushState(window.history.state, "", href);
  window.dispatchEvent(new Event(navigationEvent));
}
