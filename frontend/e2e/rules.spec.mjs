import { test as base, expect } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
const root = path.resolve(import.meta.dirname, "../.."),
  docker =
    process.env.DOCKER_EXE ??
    path.join(
      process.env.LOCALAPPDATA,
      "Programs/DockerDesktop/resources/bin/docker.exe",
    );
function fixture(mode, nonce) {
  return JSON.parse(
    execFileSync(
      docker,
      [
        "compose",
        "--project-directory",
        root,
        "--env-file",
        path.join(root, ".env"),
        "-f",
        path.join(root, "docker-compose.yml"),
        "-p",
        "metric-control-center",
        "exec",
        "-T",
        "-e",
        "UI_FIXTURE_MODE=" + mode,
        "-e",
        "UI_FIXTURE_NONCE=" + nonce,
        "backend",
        "python",
        "-c",
        "import sys;exec(sys.stdin.read())",
      ],
      {
        input: readFileSync(
          new URL("./rules_accounts.py", import.meta.url),
          "utf8",
        ),
        encoding: "utf8",
        windowsHide: true,
      },
    ),
  );
}
async function login(page, user) {
  await page.goto("/login");
  await page.getByLabel("Логин или email").fill(user.login);
  await page.getByLabel("Пароль", { exact: true }).fill(user.password);
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
}
function watch(page, audit) {
  page.on("console", (m) => {
    if (m.type() === "error") audit.errors.push(m.text());
  });
  page.on("pageerror", (e) => audit.errors.push(e.message));
  page.on("request", (r) => {
    if (
      !["GET", "HEAD", "OPTIONS"].includes(r.method()) &&
      /^\/api\/(actions|ai|automation)(\/|$)/.test(new URL(r.url()).pathname)
    )
      audit.advertising.push(r.url());
  });
}
const test = base.extend({
  accounts: [
    async ({}, use) => {
      const nonce = randomUUID().replaceAll("-", "");
      try {
        await use(fixture("create", nonce));
      } finally {
        fixture("cleanup", nonce);
      }
    },
    { scope: "worker" },
  ],
  audit: [
    async ({ page, context }, use, info) => {
      const audit = { errors: [], advertising: [] };
      watch(page, audit);
      context.on("page", (p) => watch(p, audit));
      await use(audit);
      await info.attach("rule-browser-audit", {
        body: Buffer.from(JSON.stringify(audit)),
        contentType: "application/json",
      });
      expect(audit.errors).toEqual([]);
      expect(audit.advertising).toEqual([]);
    },
    { auto: true },
  ],
});
test.use({ storageState: { cookies: [], origins: [] } });
test.describe.configure({ mode: "serial" });
let ruleID = "",
  name = "",
  firstSimulation;
async function open(page) {
  await page.goto("/rules");
  await expect(
    page.getByRole("heading", { name: "Правила рекламы", exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("Открыть правило")).toBeEnabled();
}
async function savedColumns(page) {
  await expect(page.getByLabel("Набор колонок")).toBeEnabled();
  await expect(page.locator(".column-save-status")).toContainText(
    /сохранён|загружены|Сохранено/,
  );
}
async function simulate(page) {
  const promise = page.waitForResponse(
    (r) => r.url().endsWith("/simulate") && r.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Проверить правила", exact: true })
    .click();
  const response = await promise;
  expect(response.ok()).toBeTruthy();
  const result = await response.json();
  await expect(page.locator("p.notice[role=status]")).toContainText(
    "DRY RUN завершён",
  );
  return result;
}
test("rule lifecycle: real local simulation, profile, accounts, ROI/CPL, AND/OR, revisions and immutable history", async ({
  page,
  accounts,
}) => {
  test.setTimeout(120000);
  await login(page, accounts.users[0]);
  await page
    .getByRole("link", { name: "Правила рекламы", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Правила рекламы", exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("Название правила")).toBeEnabled();
  name =
    "Приёмка правил — очень длинное русское название " + accounts.users[0].id;
  await page.getByLabel("Название правила").fill(name);
  await page
    .getByRole("combobox", { name: "Экономический профиль", exact: true })
    .selectOption(accounts.profile.id);
  const scopes = await (
    await page.request.get("/api/smart-rules/available-scopes")
  ).json();
  const account = scopes.options.account.find(
    (a) => a.id === accounts.account_id,
  );
  expect(account).toBeTruthy();
  await page
    .getByRole("group", { name: /Рекламные аккаунты/ })
    .getByRole("checkbox", { name: account.name, exact: true })
    .click();
  await page.getByLabel("Период оценки").selectOption("last_7");
  await page
    .getByRole("button", { name: "Добавить условие", exact: true })
    .click();
  await page
    .getByRole("combobox", { name: "Условие 2", exact: true })
    .selectOption("ROI_BELOW_MINIMUM");
  await page
    .getByRole("combobox", { name: "Источник метрики", exact: true })
    .selectOption("estimated");
  await page
    .getByLabel("Оператор группы 1", { exact: true })
    .selectOption("OR");
  await page
    .getByLabel("Оператор группы 1", { exact: true })
    .selectOption("AND");
  await page.getByLabel("Минимум лидов", { exact: true }).fill("5");
  await page
    .getByLabel("Минимум подтверждённых продаж", { exact: true })
    .fill("1");
  await page
    .getByRole("button", { name: "Сохранить правило", exact: true })
    .click();
  await expect(page.locator("p.notice[role=status]")).toContainText(
    "Правило сохранено",
  );
  ruleID = await page.getByLabel("Открыть правило").inputValue();
  await page.reload();
  await page.getByLabel("Открыть правило").selectOption(ruleID);
  await expect(page.getByLabel("Название правила")).toHaveValue(name);
  await expect(page.getByLabel("Минимум лидов", { exact: true })).toHaveValue(
    "5",
  );
  firstSimulation = await simulate(page);
  expect(firstSimulation.total).toBeGreaterThan(0);
  for (const r of firstSimulation.rows) {
    expect(r.real_action).toBe(false);
    expect(r.action_eligibility).toBe(false);
    expect(r.approved_sales ?? null).toBeNull();
    expect(r.actual_roi ?? null).toBeNull();
  }
  await expect(
    page.getByRole("article", { name: "Объяснение решения" }),
  ).toBeVisible();
  await page.getByLabel("Результат проверки").selectOption("WOULD_PAUSE");
  await expect(
    page.getByTestId("statistics-table").locator("tbody"),
  ).toContainText(
    firstSimulation.counts.WOULD_PAUSE ? "" : "Нет сохранённых данных",
  );
  await page.getByLabel("Результат проверки").selectOption("");
  await page
    .getByRole("button", { name: "Дублировать правило", exact: true })
    .click();
  await expect(page.locator("p.notice[role=status]")).toContainText(
    "Копия создана",
  );
  await page.getByLabel("Название правила").fill(name + " копия");
  await page
    .getByRole("button", { name: "Сохранить правило", exact: true })
    .click();
  await expect(page.locator("p.notice[role=status]")).toContainText(
    "сохранено",
  );
  await page
    .getByRole("button", { name: "Архивировать правило", exact: true })
    .click();
  await expect(page.locator("p.notice[role=status]")).toContainText(
    "архивировано",
  );
  await expect(
    page.getByRole("button", { name: "Проверить правила", exact: true }),
  ).toBeDisabled();
  await page
    .getByRole("button", { name: "Восстановить правило", exact: true })
    .click();
  await expect(page.locator("p.notice[role=status]")).toContainText(
    "восстановлено",
  );
  await page
    .getByRole("button", { name: "Вернуться к версии 1", exact: true })
    .click();
  await expect(page.locator("p.notice[role=status]")).toContainText(
    "новой версией",
  );
  await page.getByLabel("Открыть правило").selectOption(ruleID);
  const historical = await (
    await page.request.get("/api/smart-rules/simulations/" + firstSimulation.id)
  ).json();
  expect(historical.rows).toEqual(firstSimulation.rows);
  expect(historical.rule_revision).toBe(1);
  await page
    .getByRole("button", { name: /Открыть проверку/ })
    .first()
    .click();
  await expect(
    page.getByRole("article", { name: "Объяснение решения" }),
  ).toBeVisible();
});
test("rule columns: mouse drag, resize/autofit, add/hide, presets, logout persistence and responsive", async ({
  page,
  accounts,
}) => {
  test.setTimeout(120000);
  await login(page, accounts.users[0]);
  await open(page);
  await page.getByLabel("Открыть правило").selectOption(ruleID);
  await simulate(page);
  await savedColumns(page);
  await page
    .getByRole("button", { name: "Настроить колонки", exact: true })
    .click();
  await page.getByTestId("column-toggle-approved_sales").check();
  await page.getByTestId("column-toggle-actual_roi").uncheck();
  await page
    .getByLabel("Название нового набора")
    .fill("Мои правила — длинное русское название");
  await page
    .getByRole("button", { name: "Создать набор", exact: true })
    .click();
  await page.getByLabel("Закрыть настройку колонок").click();
  await savedColumns(page);
  await page.locator(".customizable-table-wrap").evaluate((el) => {
    el.scrollLeft = 0;
  });
  const target = await page.getByTestId("column-spend").boundingBox();
  await page.getByTestId("drag-leads").hover();
  await page.mouse.down();
  await page.mouse.move(target.x + 30, target.y + 15, { steps: 10 });
  await page.mouse.move(target.x + 31, target.y + 16);
  await page.mouse.up();
  await expect(page.locator("thead th[data-column]").nth(1)).toHaveAttribute(
    "data-column",
    "leads",
  );
  await savedColumns(page);
  const resize = await page.getByTestId("resize-name").boundingBox();
  await page.mouse.move(resize.x + 4, resize.y + 15);
  await page.mouse.down();
  await page.mouse.move(resize.x + 85, resize.y + 15, { steps: 12 });
  await page.mouse.up();
  await savedColumns(page);
  await page.getByTestId("resize-maximum_cpl").scrollIntoViewIfNeeded();
  await page.getByTestId("resize-maximum_cpl").dblclick();
  await savedColumns(page);
  await page.getByTestId("column-maximum_cpl").locator(".sort-heading").click();
  await savedColumns(page);
  const before = (
    await (await page.request.get("/api/preferences/columns/rule_ad")).json()
  ).preference;
  expect(before.config.columns[1].key).toBe("leads");
  expect(before.config.columns.some((c) => c.key === "approved_sales")).toBe(
    true,
  );
  expect(before.config.columns.some((c) => c.key === "actual_roi")).toBe(false);
  await page.getByRole("button", { name: "Выйти", exact: true }).click();
  await expect(page).toHaveURL(/\/login$/);
  await login(page, accounts.users[0]);
  await open(page);
  await page.getByLabel("Открыть правило").selectOption(ruleID);
  await simulate(page);
  await savedColumns(page);
  const after = (
    await (await page.request.get("/api/preferences/columns/rule_ad")).json()
  ).preference;
  expect(after.config).toEqual(before.config);
  expect(after.active_id).toEqual(before.active_id);
  for (const width of [1440, 768, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await expect
      .poll(() =>
        page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth + 1,
        ),
      )
      .toBe(true);
    const wrap = page.locator(".customizable-table-wrap");
    await wrap.evaluate((el) => {
      el.scrollLeft = 0;
    });
    const x = (await page.getByTestId("column-name").boundingBox()).x;
    await wrap.evaluate((el) => {
      el.scrollLeft = 600;
    });
    expect(await wrap.evaluate((el) => el.scrollLeft)).toBeGreaterThan(0);
    expect(
      Math.abs((await page.getByTestId("column-name").boundingBox()).x - x),
    ).toBeLessThanOrEqual(1);
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  await page
    .getByRole("button", { name: "Настроить колонки", exact: true })
    .click();
  page.once("dialog", (d) => d.accept());
  await page
    .getByRole("button", { name: "Удалить набор", exact: true })
    .click();
  await page.getByLabel("Закрыть настройку колонок").click();
  await savedColumns(page);
  await expect(page.getByLabel("Набор колонок")).toHaveValue(/^system:/);
});
test("rule permissions: viewer/operator read only, explicit grant, revoke, workspace and CSRF", async ({
  page,
  browser,
  accounts,
  audit,
}) => {
  test.setTimeout(120000);
  await login(page, accounts.users[0]);
  await open(page);
  const operator = await browser.newContext({
      baseURL: process.env.UI_BASE_URL ?? "http://127.0.0.1:3000",
      storageState: { cookies: [], origins: [] },
    }),
    viewer = await browser.newContext({
      baseURL: process.env.UI_BASE_URL ?? "http://127.0.0.1:3000",
      storageState: { cookies: [], origins: [] },
    });
  try {
    const op = await operator.newPage(),
      view = await viewer.newPage();
    watch(op, audit);
    watch(view, audit);
    await login(op, accounts.users[1]);
    await open(op);
    await login(view, accounts.users[2]);
    await open(view);
    await expect(op.getByLabel("Название правила")).toBeDisabled();
    await expect(view.getByLabel("Название правила")).toBeDisabled();
    const grant = page.getByRole("checkbox", {
      name: accounts.users[1].login,
      exact: true,
    });
    await grant.click();
    await expect(grant).toBeChecked();
    await expect(page.locator("p.notice[role=status]")).toContainText(
      "Права оператора обновлены",
    );
    await op.reload();
    await expect(op.getByLabel("Название правила")).toBeEnabled();
    await grant.click();
    await expect(grant).not.toBeChecked();
    await expect(page.locator("p.notice[role=status]")).toContainText(
      "Права оператора обновлены",
    );
    await op.reload();
    await expect(op.getByLabel("Название правила")).toBeDisabled();
    const denied = await view.request.post("/api/smart-rules", { data: {} });
    expect(denied.status()).toBe(403);
  } finally {
    await operator.close();
    await viewer.close();
  }
});
