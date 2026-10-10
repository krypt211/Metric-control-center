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
  const account = page.getByRole("combobox", { name: "Кабинет", exact: true });
  if ((await account.inputValue()) !== ad.account_id) {
    const response = page.waitForResponse((r) =>
      r.url().includes("/api/manual-control/ads?offset=0") &&
      r.url().includes("account_id=" + ad.account_id) && r.ok(),
    );
    await account.selectOption(ad.account_id);
    await response;
  }
  const offset = ad.catalog_offset ?? 0;
  for (let current = 0; current < offset; current += 100) {
    const response = page.waitForResponse((r) =>
      r.url().includes("/api/manual-control/ads?offset=" + (current + 100)) &&
      r.ok(),
    );
    await page.getByRole("button", { name: "Следующие", exact: true }).click();
    await response;
  }
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
let freshAd, adminState, ruleFixture;

async function restoreAdmin(page, user) {
  if (!adminState) {
    await login(page, user);
    adminState = await page.context().storageState();
  } else {
    await page.context().addCookies(adminState.cookies);
  }
}

async function catalogPages(page, accountId) {
  const rows = [];
  let offset = 0;
  do {
    const response = await page.request.get(
      `/api/manual-control/ads?account_id=${accountId}&offset=${offset}`,
    );
    expect(response.ok()).toBe(true);
    const table = await response.json();
    rows.push(...table.rows.map((row) => ({ ...row, catalog_offset: offset })));
    offset = table.next_offset;
  } while (offset !== null);
  return rows;
}
test("manual catalog, status, pause and enable drafts, local confirmation, simulation, audit and persistence", async ({
  page,
  accounts,
  audit,
}) => {
  test.setTimeout(120000);
  await login(page, accounts.users[0]);
  let releaseInitial, initialReady;
  const release = new Promise((resolve) => { releaseInitial = resolve; });
  const ready = new Promise((resolve) => { initialReady = resolve; });
  await page.route("**/api/manual-control/ads?offset=0", async (route) => {
    const response = await route.fetch();
    initialReady();
    await release;
    await route.fulfill({ response });
  });
  await open(page);
  const settings = await (
    await page.request.get("/api/manual-control/settings")
  ).json();
  for (const account of settings.accounts) {
    if (account.provider !== "metricflow") continue;
    const rows = await catalogPages(page, account.id);
    freshAd = rows.find(
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
  await ready;
  await choose(page, freshAd);
  const lateResponse = page.waitForResponse((r) =>
    new URL(r.url()).pathname === "/api/manual-control/ads" &&
    !new URL(r.url()).searchParams.has("account_id"),
  );
  releaseInitial();
  await lateResponse;
  await page.evaluate(() => new Promise((resolve) =>
    requestAnimationFrame(() => requestAnimationFrame(resolve)),
  ));
  await expect(page.locator("tbody tr").filter({ hasText: freshAd.meta_ad_id })).toHaveCount(1);
  await page.unroute("**/api/manual-control/ads?offset=0");
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
  adminState = await page.context().storageState();
  await open(page);
  await expect(
    page.getByRole("region", { name: "История операций" }),
  ).toContainText("Локальная симуляция");
  const after = await catalogPages(page, freshAd.account_id);
  expect(after.find((a) => a.id === freshAd.id).status).toBe(
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
  await page.context().addCookies(adminState.cookies);
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
  await restoreAdmin(page, accounts.users[0]);
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
  ).toContainText("Не проверено");
});

test("real saved rule decisions permit only eligible WOULD_PAUSE drafts", async ({
  page, accounts,
}) => {
  await restoreAdmin(page, accounts.users[0]);
  await page.goto("/rules");
  const csrf = await (await page.request.get("/api/auth/csrf")).json();
  const headers = {
    Origin: new URL(page.url()).origin, "X-CSRF-Token": csrf.csrf_token,
  };
  const created = await page.request.post("/api/smart-rules", {
    headers,
    data: {
      name: "Приёмка ручного перехода из DRY RUN",
      profile_id: accounts.profile.id,
      selection: { account_ids: [accounts.account_id], provider: "metricflow" },
      thresholds: { minimum_spend: "0", minimum_leads: 0,
        minimum_approved_sales: 0, minimum_observed_purchases: 0,
        minimum_processed: 0, minimum_data_age_hours: 0, maturation_hours: 0 },
      expression: { kind: "group", operator: "AND", children: [
        { kind: "condition", type: "SPEND_THRESHOLD", limit: "custom", value: "0" },
      ] },
    },
  });
  expect(created.status()).toBe(201);
  const rule = await created.json();
  const simulated = await page.request.post(`/api/smart-rules/${rule.id}/simulate`, {
    headers, data: { version: rule.revision },
  });
  const simulation = await simulated.json();
  expect(simulated.ok(), JSON.stringify(simulation.detail ?? null)).toBe(true);
  ruleFixture = { rule, simulation };
  const candidate = simulation.rows.find((row) =>
    row.status === "WOULD_PAUSE" && ["ACTIVE", "PAUSED"].includes(row.ad_status),
  );
  const card = candidate ?? simulation.rows.find((row) => row.status !== "WOULD_PAUSE");
  expect(card, "A real saved decision is required; no result is fabricated").toBeTruthy();
  await page.goto("/rules?rule=" + rule.id);
  await page.getByRole("button", { name: /Открыть проверку/ }).first().click();
  await page.getByLabel("Поиск объявления", { exact: true }).fill(card.external_id);
  await page.locator("tbody .rowlink").first().click();
  if (!candidate) {
    await expect(page.getByRole("article", { name: "Объяснение решения" })
      .getByRole("button", { name: "Подготовить отключение", exact: true })).toHaveCount(0);
    const before = await (await page.request.get("/api/manual-control/requests")).json();
    const denied = await apiWrite(page, "/from-rule", {
      simulation_id: simulation.id, entity_id: card.id,
    }, "non-eligible-rule");
    expect(denied.status()).toBe(422);
    const after = await (await page.request.get("/api/manual-control/requests")).json();
    expect(after.requests).toEqual(before.requests);
    return;
  }
  await page.getByRole("article", { name: "Объяснение решения" })
    .getByRole("button", { name: "Подготовить отключение", exact: true }).click();
  await expect(page).toHaveURL(/\/manual-control\?request=/);
  const draft = page.getByRole("region", { name: "Подготовленное действие" });
  await expect(draft).toContainText("DRAFT");
  const requestID = new URL(page.url()).searchParams.get("request");
  const saved = await (await page.request.get("/api/manual-control/requests/" + requestID)).json();
  expect(saved.rule_source.simulation_id).toBe(simulation.id);
  expect(saved.rule_source.rule_revision).toBe(simulation.rule_revision);
  expect(saved.rule_source.reasons).toEqual(candidate.reason_codes);
  await draft.getByRole("button", { name: "Отменить команду" }).click();
  await expect(draft).toContainText("CANCELLED");
});

test("browser-only mock verifies WOULD_PAUSE prepare button and draft navigation", async ({ page, accounts }) => {
  await restoreAdmin(page, accounts.users[0]);
  await page.goto("/rules?rule=" + ruleFixture.rule.id);
  const history = await (await page.request.get("/api/manual-control/requests")).json();
  const base = history.requests.find((request) => request.actor === accounts.users[0].login);
  expect(base).toBeTruthy();
  const id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
  const mockCard = {
    ...(ruleFixture.simulation.rows.find((row) => row.external_id === freshAd.meta_ad_id) ??
      ruleFixture.simulation.rows.find((row) => row.ad_status === "ACTIVE")),
    name: "Изолированный browser mock — не рекламная команда",
    status: "WOULD_PAUSE", reason_codes: [],
  };
  const mockDraft = {
    ...base, id, status: "DRAFT", display_status: "DRAFT", revision: 1,
    operation: "PAUSE_AD", target_status: "PAUSED", result: null, preflight: null, events: [],
    captured: { ...base.captured, name: mockCard.name },
  };
  // These two responses exist only inside this browser test. Neither the saved
  // decision nor an AD fact/request is edited in PostgreSQL.
  await page.route("**/api/smart-rules/simulations/" + ruleFixture.simulation.id,
    (route) => route.fulfill({ json: { ...ruleFixture.simulation, rows: [mockCard], total: 1 } }));
  const calls = [];
  await page.route("**/api/manual-control/from-rule", async (route) => {
    calls.push({ method: route.request().method(), body: route.request().postDataJSON() });
    await route.fulfill({ status: 201, json: mockDraft });
  });
  await page.route("**/api/manual-control/requests/" + id,
    (route) => route.fulfill({ json: mockDraft }));
  await page.getByRole("button", { name: /Открыть проверку/ }).first().click();
  await page.getByRole("article", { name: "Объяснение решения" })
    .getByRole("button", { name: "Подготовить отключение", exact: true }).click();
  await expect(page).toHaveURL(new RegExp("/manual-control\\?request=" + id));
  await expect(page.getByRole("region", { name: "Подготовленное действие" })).toContainText(mockCard.name);
  expect(calls).toEqual([{ method: "POST", body: {
    simulation_id: ruleFixture.simulation.id, entity_id: mockCard.id,
  } }]);
  const real = await (await page.request.get("/api/smart-rules/simulations/" + ruleFixture.simulation.id)).json();
  expect(real.rows).toEqual(ruleFixture.simulation.rows);
  expect((await (await page.request.get("/api/manual-control/requests")).json())
    .requests.some((request) => request.id === id)).toBe(false);
});
