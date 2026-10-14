import { expect } from "@playwright/test";
import { test, login } from "./rules-fixtures.mjs";

test.use({ storageState: { cookies: [], origins: [] } });
test.describe.configure({ mode: "serial" });
const states = new Map();
async function signIn(page, user) {
  if (states.has(user.id)) {
    await page.context().addCookies(states.get(user.id).cookies);
    await page.goto("/");
  } else {
    await login(page, user);
    states.set(user.id, await page.context().storageState());
  }
  await expect(page.getByRole("button", { name: "Настройки", exact: true })).toBeEnabled();
}
const primary = (page) => page.getByRole("navigation", { name: "Основные разделы", exact: true });
const popup = (page) => page.getByRole("navigation", { name: "Настройки приложения", exact: true });
async function noOverflow(page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
}
async function settings(page) {
  await page.getByRole("button", { name: "Настройки", exact: true }).click();
  await expect(popup(page)).toBeVisible();
}

test("desktop navigation, settings keyboard order, Escape, Tab and outside click", async ({ page, accounts }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await signIn(page, accounts.users[0]);
  await expect(page.locator(".app-navigation")).toHaveCount(1);
  await expect(primary(page).getByRole("link")).toHaveText(["Обзор", "Объявления", "Правила", "История"]);
  await expect(primary(page).getByRole("link", { name: "Обзор", exact: true })).toHaveAttribute("aria-current", "page");
  await expect(primary(page).getByRole("link", { name: "API и подключения" })).toHaveCount(0);
  const button = page.getByRole("button", { name: "Настройки", exact: true });
  await button.focus(); await page.keyboard.press("ArrowDown");
  await expect(popup(page).getByRole("link", { name: "Экономика" })).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await expect(popup(page).getByRole("link", { name: "Креативы" })).toBeFocused();
  await page.keyboard.press("End");
  await expect(popup(page).getByRole("link", { name: "Администрирование", exact: true })).toBeFocused();
  await page.keyboard.press("Home");
  await expect(popup(page).getByRole("link", { name: "Экономика" })).toBeFocused();
  expect(await page.evaluate(() => getComputedStyle(document.activeElement).outlineStyle)).not.toBe("none");
  await page.keyboard.press("Escape"); await expect(button).toBeFocused();
  await expect(button).toHaveAttribute("aria-expanded", "false");
  await settings(page); await page.keyboard.press("Tab");
  await expect(popup(page).getByRole("link", { name: "Экономика" })).toBeFocused();
  await page.getByRole("heading", { name: "Сегодня", exact: true }).click();
  await expect(popup(page)).toHaveCount(0); await noOverflow(page);
});

test("navigation fits 1440, 1024, 768 and 390 with an unclipped mobile/settings panel", async ({ page, accounts }) => {
  await signIn(page, accounts.users[0]);
  for (const width of [1440, 1024, 768, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    const desktop = width > 1100;
    const toggle = page.getByRole("button", { name: desktop ? "Настройки" : "Меню", exact: true });
    await expect(toggle).toBeVisible();
    await expect(page.locator(".nav-primary")).toBeVisible({ visible: desktop });
    await toggle.click();
    const panel = page.locator(desktop ? "#mcc-settings-panel" : "#mcc-mobile-panel");
    await expect(panel).toBeVisible();
    const box = await panel.boundingBox();
    expect(box.x).toBeGreaterThanOrEqual(0); expect(box.x + box.width).toBeLessThanOrEqual(width);
    const target = panel.getByRole("link", { name: "Экономические профили", exact: true });
    expect(await target.evaluate((element) => { const r = element.getBoundingClientRect(); return element.contains(document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2)); })).toBe(true);
    if (!desktop) {
      await expect(panel.getByRole("link", { name: "Управление", exact: true })).toBeVisible();
      await expect(panel.getByRole("button", { name: "Выйти", exact: true })).toBeVisible();
      await expect(panel).toContainText(accounts.users[0].login);
    }
    await noOverflow(page);
    if (width === 1440 || width === 390) await page.screenshot({ path: `test-results/navigation-${width}.png` });
    await page.keyboard.press("Escape"); await expect(toggle).toBeFocused();
    await expect(panel).toHaveCount(0);
  }
});

test("ADMIN, OPERATOR and VIEWER menu visibility keeps server permissions", async ({ page, accounts }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  for (const [index, user] of accounts.users.entries()) {
    await page.context().clearCookies(); await signIn(page, user); await settings(page);
    for (const name of ["API и подключения", "Администрирование"]) {
      await expect(popup(page).getByRole("link", { name, exact: true })).toHaveCount(index === 0 ? 1 : 0);
    }
    const response = await page.request.get("/api/admin/providers");
    expect(response.status()).toBe(index === 0 ? 200 : 403);
    await page.keyboard.press("Escape"); await page.setViewportSize({ width: 390, height: 1000 });
    await page.getByRole("button", { name: "Меню", exact: true }).click();
    for (const name of ["API и подключения", "Администрирование"]) {
      await expect(page.locator("#mcc-mobile-panel").getByRole("link", { name, exact: true })).toHaveCount(index === 0 ? 1 : 0);
    }
    await page.keyboard.press("Escape"); await page.setViewportSize({ width: 1440, height: 1000 });
  }
});

test("column settings retain statistics context and saved sets", async ({ page, accounts }) => {
  await signIn(page, accounts.users[0]);
  await page.goto("/?tab=statistics&context=kept");
  await expect(page.getByLabel("Набор колонок")).toBeEnabled();
  const period = page.getByRole("combobox", { name: /^Период/ });
  await period.selectOption("7");
  const originalUrl = page.url(); const preset = await page.getByLabel("Набор колонок").inputValue();
  await settings(page); await popup(page).getByRole("link", { name: "Колонки и наборы", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeVisible(); expect(page.url()).toBe(originalUrl);
  await page.getByRole("button", { name: "Закрыть настройку колонок" }).click();
  await expect(period).toHaveValue("7"); await expect(page.getByLabel("Набор колонок")).toHaveValue(preset);
  await expect(primary(page).getByRole("link", { name: "Объявления", exact: true })).toHaveAttribute("aria-current", "page");
  await page.goto("/?tab=statistics&columns=1&context=kept");
  await expect(page.getByRole("dialog")).toBeVisible();
  expect(new URL(page.url()).searchParams.get("context")).toBe("kept");
  await page.getByRole("button", { name: "Закрыть настройку колонок" }).click();
});

test("economic profile deep link, back/forward and tab switch preserve period", async ({ page, accounts }) => {
  await signIn(page, accounts.users[0]); await page.goto("/economics?context=kept");
  const period = page.getByRole("combobox", { name: "Период экономики", exact: true });
  await period.selectOption("yesterday");
  await settings(page); await popup(page).getByRole("link", { name: "Экономические профили", exact: true }).click();
  await expect(page.getByRole("region", { name: "Экономические профили", exact: true })).toBeVisible();
  expect(new URL(page.url()).searchParams.get("context")).toBe("kept");
  await expect(popup(page)).toHaveCount(0);
  await page.goBack(); await expect(period).toHaveValue("yesterday");
  await page.goForward(); await expect(page.getByRole("region", { name: "Экономические профили", exact: true })).toBeVisible();
  await page.reload(); await expect(page.getByRole("region", { name: "Экономические профили", exact: true })).toBeVisible();
  await page.getByRole("navigation", { name: "Раздел экономики", exact: true }).getByRole("button", { name: "Апрув и назначения", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Назначения профилей", exact: true })).toBeVisible();
});

test("existing rule, recommendations, manual control and connections remain reachable", async ({ page, accounts }) => {
  await signIn(page, accounts.users[0]);
  for (const [label, heading] of [["Правила", "Правила рекламы"], ["Рекомендации", "Центр рекомендаций"], ["Управление", "Управление рекламой"]]) {
    if (label === "Правила") await primary(page).getByRole("link", { name: label, exact: true }).click();
    else { await settings(page); await popup(page).getByRole("link", { name: label, exact: true }).click(); }
    await expect(page.getByRole("heading", { name: heading, exact: true })).toBeVisible();
  }
  await settings(page); await popup(page).getByRole("link", { name: "Безопасность действий", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Настройки управления рекламой", exact: true })).toBeVisible();
  await settings(page); await popup(page).getByRole("link", { name: "API и подключения", exact: true }).click();
  await expect(page).toHaveURL(/\/settings\/connections$/);
  await expect(page.locator(".provider-details")).toContainText(["UNVERIFIED / BLOCKED", "NOT CONNECTED / BLOCKED"]);
  await expect(page.getByRole("heading", { name: "Настройки · API и подключения", exact: true })).toBeVisible();
  await settings(page); await popup(page).getByRole("link", { name: "Администрирование", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Администрирование", exact: true })).toBeVisible();
});

test("mobile logout closes the session with the existing CSRF flow", async ({ page, accounts }) => {
  await signIn(page, accounts.users[0]); await page.setViewportSize({ width: 390, height: 1000 });
  await page.getByRole("button", { name: "Меню", exact: true }).click();
  await page.locator("#mcc-mobile-panel").getByRole("button", { name: "Выйти", exact: true }).click();
  await expect(page).toHaveURL(/\/login$/);
  expect((await page.request.get("/api/auth/me")).status()).toBe(401);
});
