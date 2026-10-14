const test = require("node:test");
const assert = require("node:assert/strict");
const { existsSync } = require("node:fs");
const path = require("node:path");
const { navigationItems, navigationForRole, isNavigationActive, navigationHref, dashboardTabs, economicsTabs } = require("../.test-build/lib/navigation.js");
const entry = (id) => navigationItems.find((item) => item.id === id);

test("navigation uses unique existing routes and supported tab deep links", () => {
  assert.equal(new Set(navigationItems.map((item) => item.id)).size, navigationItems.length);
  assert.equal(new Set(navigationItems.map((item) => item.route)).size, navigationItems.length);
  for (const item of navigationItems) {
    const url = new URL(item.route, "http://local.test");
    assert.ok(existsSync(path.join(__dirname, "../app", url.pathname, "page.tsx")), item.route);
    const tab = url.searchParams.get("tab");
    if (tab) assert.ok((url.pathname === "/" ? dashboardTabs : economicsTabs).includes(tab));
    assert.ok(item.icon && item.roles.length && item.desktop && item.mobile);
  }
});
test("unknown and missing roles reveal no authenticated navigation", () => {
  for (const role of [null, "", "owner", "ADMIN"]) assert.deepEqual(navigationForRole(role), []);
});
test("desktop and mobile preserve all sections and enforce ADMIN-only settings", () => {
  for (const role of ["viewer", "operator", "admin"]) {
    const desktop = navigationForRole(role).map((item) => item.id);
    assert.deepEqual(navigationForRole(role, true).map((item) => item.id), desktop);
    for (const id of ["overview", "statistics", "economics", "rules", "manual", "recommendations", "creatives", "tracker", "columns", "profiles", "action-safety"]) assert.ok(desktop.includes(id));
    assert.equal(desktop.includes("connections"), role === "admin");
    assert.equal(desktop.includes("admin"), role === "admin");
  }
});
test("active matching separates dashboard tabs and exact settings routes", () => {
  assert.equal(isNavigationActive(entry("overview"), "/", ""), true);
  assert.equal(isNavigationActive(entry("statistics"), "/", "?tab=statistics"), true);
  assert.equal(isNavigationActive(entry("overview"), "/", "?tab=statistics"), false);
  assert.equal(isNavigationActive(entry("profiles"), "/economics", "?tab=profiles"), true);
  assert.equal(isNavigationActive(entry("profiles"), "/economics", ""), false);
  assert.equal(isNavigationActive(entry("manual"), "/settings/manual-control", ""), false);
  assert.equal(isNavigationActive(entry("action-safety"), "/settings/manual-control", ""), true);
  assert.equal(isNavigationActive(entry("columns"), "/", "?tab=statistics"), false);
});
test("same-page deep links preserve unrelated query context", () => {
  const href = navigationHref(entry("profiles"), "/economics", "?tab=stats&account=abc&start=2026-10-01");
  const url = new URL(href, "http://local.test");
  assert.equal(url.searchParams.get("tab"), "profiles");
  assert.equal(url.searchParams.get("account"), "abc");
  assert.equal(url.searchParams.get("start"), "2026-10-01");
  assert.equal(navigationHref(entry("profiles"), "/rules", "?rule=123"), "/economics?tab=profiles");
});

test("primary navigation is focused on the core workflow", () => {
  assert.deepEqual(navigationForRole("admin").filter(x => x.category === "main").map(x=>x.id), ["overview", "statistics", "rules", "history"]);
});
