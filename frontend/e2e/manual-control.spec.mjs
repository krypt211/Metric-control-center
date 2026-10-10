import { expect } from "@playwright/test";
import { test, login, watch } from "./rules-fixtures.mjs";
test.use({ storageState: { cookies: [], origins: [] } });
test.describe.configure({ mode: "serial" });

async function open(page) {
  await page.goto("/manual-control");
  await expect(
    page.getByRole("heading", { name: "Управление рекламой", exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("Набор колонок")).toBeEnabled();
}
async function apiWrite(page, path, body, key) {
  const csrf = await (await page.request.get("/api/auth/csrf")).json();
  return page.request.post("/api/manual-control" + path, {
    headers: {
      Origin: new URL(page.url()).origin,
      "X-CSRF-Token": csrf.csrf_token,
      ...(key ? { "Idempotency-Key": key } : {}),
    },
    data: body,
  });
}
async function choose(page, ad) {
  await page.getByLabel("Кабинет", { exact: true }).selectOption(ad.account_id);
  await page
    .getByLabel("Поиск объявления", { exact: true })
    .fill(ad.meta_ad_id);
  const row = page.locator("tbody tr").filter({ hasText: ad.meta_ad_id });
  await expect(row).toHaveCount(1);
  await row.locator(".rowlink").click();
  await expect(
    page.getByRole("article", { name: "Выбранное объявление" }),
  ).toBeVisible();
}
let freshAd;
test("manual catalog, status, pause and enable drafts, local confirmation, simulation, audit and persistence", async ({
  page,
  accounts,
  audit,
}) => {
  test.setTimeout(120000);
  await login(page, accounts.users[0]);
  await open(page);
  const settings = await (
    await page.request.get("/api/manual-control/settings")
  ).json();
  for (const account of settings.accounts) {
    const table = await (
      await page.request.get("/api/manual-control/ads?account_id=" + account.id)
    ).json();
    freshAd = table.rows?.find(
      (a) =>
        ["ACTIVE", "PAUSED"].includes(a.status) &&
        Date.now() - Date.parse(a.status_refreshed_at) < 12 * 60 * 1000 &&
        a.hierarchy_confirmed &&
        a.account_confirmed,
    );
    if (freshAd) break;
  }
  expect(
    freshAd,
    "A fresh verified real AD is required; no status facts are fabricated",
  ).toBeTruthy();
  await choose(page, freshAd);
  const action = freshAd.status === "ACTIVE" ? "отключение" : "включение";
  await page
    .getByLabel("Причина ручной команды")
    .fill("Приёмка Phase 4: локальная симуляция, без рекламного WRITE");
  await page
    .getByRole("button", { name: "Подготовить " + action, exact: true })
    .click();
  const draft = page.getByRole("region", { name: "Подготовленное действие" });
  await expect(draft).toContainText("DRAFT");
  await draft
    .getByRole("button", { name: "Проверить команду", exact: true })
    .click();
  await expect(draft).toContainText("Локальная симуляция: допустима");
  await expect(draft).toContainText("LIVE: заблокирован");
  await draft
    .getByRole("button", { name: "Подтвердить намерение для симуляции" })
    .click();
  await expect(draft).toContainText("CONFIRMED");
  await draft
    .getByRole("button", { name: "Выполнить локальную симуляцию" })
    .click();
  await expect(draft).toContainText("SIMULATED");
  await expect(draft).toContainText("Рекламное объявление не изменено");
  await expect(draft).not.toContainText("SUCCEEDED");
  const history = await (
    await page.request.get("/api/manual-control/requests")
  ).json();
  const saved = history.requests.find(
    (r) => r.actor === accounts.users[0].login && r.status === "SIMULATED",
  );
  expect(saved).toBeTruthy();
  await page.reload();
  await expect(
    page.getByRole("region", { name: "История операций" }),
  ).toContainText(freshAd.name);
  await page.getByRole("button", { name: "Выйти", exact: true }).click();
  await expect(page).toHaveURL(/\/login$/);
  await login(page, accounts.users[0]);
  await open(page);
  await expect(
    page.getByRole("region", { name: "История операций" }),
  ).toContainText("Локальная симуляция");
  const after = await (
    await page.request.get(
      "/api/manual-control/ads?account_id=" + freshAd.account_id,
    )
  ).json();
  expect(after.rows.find((a) => a.id === freshAd.id).status).toBe(
    freshAd.status,
  );
  await choose(page, freshAd);
  await page
    .getByLabel("Причина ручной команды")
    .fill("Проверка отмены второй локальной команды");
  await page
    .getByRole("button", {
      name:
        "Подготовить " + (action === "отключение" ? "включение" : "отключение"),
      exact: true,
    })
    .click();
  await page
    .getByRole("region", { name: "Подготовленное действие" })
    .getByRole("button", { name: "Отменить команду" })
    .click();
  await expect(
    page.getByRole("region", { name: "Подготовленное действие" }),
  ).toContainText("CANCELLED");
});

test("separate OPERATOR grant, VIEWER read-only and server denials", async ({
  page,
  browser,
  accounts,
  audit,
}) => {
  await login(page, accounts.users[0]);
  await page.goto("/settings/manual-control");
  const grant = page.getByRole("checkbox", { name: accounts.users[1].login });
  await grant.click();
  await expect(grant).toBeChecked();
  const context = await browser.newContext({
    storageState: { cookies: [], origins: [] },
  });
  const operator = await context.newPage();
  watch(operator, audit);
  await login(operator, accounts.users[1]);
  await open(operator);
  expect(
    (await (await operator.request.get("/api/manual-control/settings")).json())
      .can_control,
  ).toBe(true);
  const response = await apiWrite(
    operator,
    "/requests",
    {
      entity_id: freshAd.id,
      account_id: freshAd.account_id,
      meta_ad_id: freshAd.meta_ad_id,
      provider: freshAd.provider,
      operation: "PAUSE_AD",
      expected_status: freshAd.status,
      reason: "Изолированная проверка разрешения оператора",
    },
    "operator-one",
  );
  expect(response.status()).toBe(201);
  const row = await response.json();
  expect(
    (
      await apiWrite(operator, "/requests/" + row.id + "/cancel", {
        revision: row.revision,
      })
    ).ok(),
  ).toBe(true);
  await context.close();
  await grant.click();
  await expect(grant).not.toBeChecked();
  const viewerContext = await browser.newContext({
      storageState: { cookies: [], origins: [] },
    }),
    viewer = await viewerContext.newPage();
  watch(viewer, audit);
  await login(viewer, accounts.users[2]);
  await open(viewer);
  await choose(viewer, freshAd);
  await viewer.getByLabel("Причина ручной команды").fill("Проверка VIEWER");
  await expect(
    viewer.getByRole("button", { name: "Подготовить отключение", exact: true }),
  ).toBeDisabled();
  expect(
    (
      await apiWrite(
        viewer,
        "/requests",
        {
          entity_id: freshAd.id,
          account_id: freshAd.account_id,
          meta_ad_id: freshAd.meta_ad_id,
          provider: freshAd.provider,
          operation: "PAUSE_AD",
          expected_status: freshAd.status,
          reason: "Проверка запрета VIEWER",
        },
        "viewer-one",
      )
    ).status(),
  ).toBe(403);
  await viewerContext.close();
});

test("columns, horizontal scrolling, sticky name, responsive layout and safety settings", async ({
  page,
  accounts,
}) => {
  await login(page, accounts.users[0]);
  await open(page);
  const wrap = page.locator(".customizable-table-wrap");
  await expect(wrap).toBeVisible();
  expect(await wrap.evaluate((e) => e.scrollWidth > e.clientWidth)).toBe(true);
  expect(
    await page
      .locator("th.identity-column")
      .evaluate((e) => getComputedStyle(e).position),
  ).toBe("sticky");
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(
    page.getByRole("heading", { name: "Управление рекламой", exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth + 2,
    ),
  ).toBe(true);
  await page.goto("/settings/manual-control");
  await expect(
    page.getByRole("region", { name: "Безопасность управления" }),
  ).toContainText("LOCAL READ ONLY: true");
  await expect(
    page.getByRole("region", { name: "Безопасность управления" }),
  ).toContainText("DISCONNECTED");
  await expect(
    page.getByRole("region", { name: "Безопасность управления" }),
  ).toContainText("не проверен");
});
