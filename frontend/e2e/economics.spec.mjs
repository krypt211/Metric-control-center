import { test as base, expect } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
const root = path.resolve(import.meta.dirname, "../..");
const docker =
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
          new URL("./economics_accounts.py", import.meta.url),
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
    const p = new URL(r.url()).pathname;
    if (
      !["GET", "HEAD", "OPTIONS"].includes(r.method()) &&
      /^\/api\/(actions|ai|automation|admin\/providers)(\/|$)/.test(p)
    )
      audit.advertising.push(p);
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
  signedIn: [
    async ({ browser, accounts }, use) => {
      const c = await browser.newContext({
          baseURL: process.env.UI_BASE_URL ?? "http://127.0.0.1:3000",
          storageState: { cookies: [], origins: [] },
        }),
        p = await c.newPage();
      const audit = { errors: [], advertising: [] };
      watch(p, audit);
      await login(p, accounts[0]);
      await use({ state: await c.storageState(), audit });
      await c.close();
    },
    { scope: "worker" },
  ],
  storageState: async ({ signedIn }, use) => use(signedIn.state),
  audit: [
    async ({ page, context, signedIn }, use, testInfo) => {
      const audit = {
        errors: [...signedIn.audit.errors],
        advertising: [...signedIn.audit.advertising],
      };
      watch(page, audit);
      context.on("page", (p) => watch(p, audit));
      await use(audit);
      await testInfo.attach("economics-browser-audit", {
        body: Buffer.from(JSON.stringify(audit)),
        contentType: "application/json",
      });
      expect(audit.errors).toEqual([]);
      expect(audit.advertising).toEqual([]);
    },
    { auto: true },
  ],
});
test.describe.configure({ mode: "serial" });
test.beforeAll(async () => {
  test.setTimeout(120000);
  // Let earlier suites' shared API minute window expire without resetting limits.
  await new Promise((resolve) => setTimeout(resolve, 60000));
});
let profileID = "",
  profileName = "",
  dates = [];
async function settings(page) {
  const r = await page.request.get("/api/economics/settings");
  expect(r.ok()).toBeTruthy();
  return r.json();
}
async function open(page, tab = "Финансовая статистика") {
  await page.goto("/economics");
  await expect(
    page.getByRole("heading", { name: "Экономика рекламы", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("navigation", { name: "Раздел экономики" })
    .getByRole("button", { name: tab, exact: true })
    .click();
}
async function saved(page) {
  await expect(page.getByLabel("Набор колонок")).toBeEnabled();
  await expect(page.locator(".column-save-status")).toContainText(
    /сохранён|загружены|Сохранено/,
  );
}

test("profiles: Decimal targets, validation, edit/copy/delete/restore, reload and account assignment", async ({
  page,
  accounts,
}) => {
  test.setTimeout(120000);
  profileName =
    "Приёмка экономики — длинное русское название " + accounts[0].id;
  await open(page);
  expect(await page.getByLabel("Период экономики").inputValue()).toBe(
    "closed7",
  );
  dates = [
    await page.getByLabel("Дата начала", { exact: true }).inputValue(),
    await page.getByLabel("Дата окончания", { exact: true }).inputValue(),
  ];
  expect((Date.parse(dates[1]) - Date.parse(dates[0])) / 86400000).toBe(6);
  await page
    .getByRole("navigation", { name: "Раздел экономики" })
    .getByRole("button", { name: "Профили", exact: true })
    .click();
  await page.getByLabel("Название профиля", { exact: true }).fill(profileName);
  await page.getByLabel("Выплата за апрув", { exact: true }).fill("16");
  await page.getByLabel("Целевой ROI, %", { exact: true }).fill("20");
  await page
    .getByRole("button", { name: "Рассчитать ориентиры", exact: true })
    .click();
  await expect(
    page.getByTestId("economics-preview").locator(".card").first(),
  ).toContainText("4,00");
  await page.getByLabel("Целевой ROI, %", { exact: true }).fill("-100");
  await page
    .getByRole("button", { name: "Рассчитать ориентиры", exact: true })
    .click();
  await expect(page.locator("main").getByRole("alert")).toContainText(
    "больше −100",
  );
  await page.getByLabel("Целевой ROI, %", { exact: true }).fill("20");
  await page
    .getByRole("button", { name: "Сохранить профиль", exact: true })
    .click();
  await expect
    .poll(async () => {
      const p = (await settings(page)).profiles.find(
        (p) => p.name === profileName,
      );
      profileID = p?.id ?? "";
      return p?.version;
    })
    .toBe(1);
  await page.getByLabel("Плановый апрув, %", { exact: true }).fill("50");
  await page
    .getByRole("button", { name: "Рассчитать ориентиры", exact: true })
    .click();
  await expect(
    page.getByTestId("economics-preview").locator(".card").first(),
  ).toContainText("6,67");
  await page
    .getByRole("button", { name: "Сохранить профиль", exact: true })
    .click();
  await expect
    .poll(
      async () =>
        (await settings(page)).profiles.find((p) => p.id === profileID)
          ?.version,
    )
    .toBe(2);
  await open(page, "Профили");
  await page.getByLabel("Редактируемый профиль").selectOption(profileID);
  await expect(
    page.getByLabel("Плановый апрув, %", { exact: true }),
  ).toHaveValue("50");
  await page
    .getByRole("button", { name: "Копировать профиль", exact: true })
    .click();
  await expect
    .poll(
      async () =>
        (await settings(page)).profiles.filter((p) =>
          p.name.startsWith(profileName.slice(0, 108)),
        ).length,
    )
    .toBe(2);
  await page.getByLabel("Редактируемый профиль").selectOption(profileID);
  page.once("dialog", (d) => d.accept());
  await page
    .getByRole("button", { name: "Удалить профиль", exact: true })
    .click();
  await expect
    .poll(
      async () =>
        (await settings(page)).profiles.find((p) => p.id === profileID)
          ?.deleted,
    )
    .toBe(true);
  await page
    .getByText("История и восстановление профиля", { exact: true })
    .click();
  await expect(
    page.getByLabel("Версия для восстановления").locator("option"),
  ).toHaveCount(3);
  await page.getByLabel("Версия для восстановления").selectOption("1");
  await page
    .getByRole("button", { name: "Восстановить версию", exact: true })
    .click();
  await expect
    .poll(
      async () =>
        (await settings(page)).profiles.find((p) => p.id === profileID)
          ?.version,
    )
    .toBe(4);
  await expect(
    page.getByLabel("Плановый апрув, %", { exact: true }),
  ).toHaveValue("30");
  await page
    .getByRole("navigation", { name: "Раздел экономики" })
    .getByRole("button", { name: "Апрув и назначения", exact: true })
    .click();
  await page.getByLabel("Профиль для назначения").selectOption(profileID);
  const options = (await settings(page)).options.options.account;
  expect(options.length).toBeGreaterThan(0);
  await page.getByLabel("Назначение: объект").selectOption(options[0].id);
  await page
    .getByRole("button", { name: "Назначить профиль", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText("Назначение сохранено");
  await open(page);
  await saved(page);
  const r = await page.request.get(
    "/api/economics/evaluate?start=" +
      dates[0] +
      "&end=" +
      dates[1] +
      "&level=account",
  );
  expect(r.ok()).toBeTruthy();
  const row = (await r.json()).rows.find((r) => r.id === options[0].id);
  expect(row.profile_id).toBe(profileID);
  expect(row.actions_enabled).toBe(false);
  expect(row.actual_roi).toBeNull();
});

test("manual cohort: separate counts, same-cohort revision, group forecast and zero invented actual ROI", async ({
  page,
}) => {
  await open(page, "Апрув и назначения");
  await page
    .getByRole("combobox", { name: "Профиль когорты", exact: true })
    .selectOption(profileID);
  await page.getByLabel("Когорта", { exact: true }).fill("Приёмка — неделя 1");
  await page.getByLabel("Approved — одобрено").fill("10");
  await page.getByLabel("Rejected — отклонено").fill("20");
  await page.getByLabel("Pending — в ожидании").fill("5");
  await page
    .getByLabel("Комментарий")
    .fill(
      "Временная тестовая когорта. Не относится к реальным рекламным продажам.",
    );
  await page
    .getByRole("button", { name: "Сохранить когорту", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText("Когорта сохранена");
  let obs = (await settings(page)).observations.find(
    (o) => o.profile_id === profileID,
  );
  expect([obs.approved, obs.rejected, obs.pending, obs.version]).toEqual([
    10, 20, 5, 1,
  ]);
  await page.getByLabel("Approved — одобрено").fill("15");
  await page.getByLabel("Pending — в ожидании").fill("0");
  await page
    .getByRole("button", { name: "Сохранить когорту", exact: true })
    .click();
  await expect
    .poll(
      async () =>
        (await settings(page)).observations.find(
          (o) => o.profile_id === profileID,
        )?.version,
    )
    .toBe(2);
  await open(page, "Апрув и назначения");
  const row = page
    .getByTestId("approval-observations")
    .locator("tbody tr")
    .filter({ hasText: "Приёмка — неделя 1" });
  await row.getByRole("button", { name: "Уточнить когорту" }).click();
  await expect(page.getByLabel("Approved — одобрено")).toHaveValue("15");
  await expect(page.getByLabel("Когорта", { exact: true })).toBeDisabled();
  const r = await page.request.get(
    `/api/economics/evaluate?start=${dates[0]}&end=${dates[1]}&profile_id=${profileID}&level=ad`,
  );
  expect(r.ok()).toBeTruthy();
  const result = await r.json();
  expect(result.rows.length).toBeGreaterThan(0);
  for (const r of result.rows) {
    expect(r.actual_roi).toBeNull();
    expect(r.actual_revenue).toBeNull();
    expect(r.approved_sales).toBeNull();
    expect(r.eligible_for_rule_evaluation).toBe(false);
    expect(r.actions_enabled).toBe(false);
  }
});

test("columns: financial metrics, mouse drag/resize/autofit, custom presets, login persistence and responsive", async ({
  page,
  accounts,
  signedIn,
}, testInfo) => {
  test.setTimeout(120000);
  await open(page);
  await page.getByLabel("Профиль оценки").selectOption(profileID);
  await saved(page);
  await page
    .getByRole("button", { name: "Настроить колонки", exact: true })
    .click();
  await page.getByTestId("column-toggle-approved_sales").check();
  await page.getByTestId("column-toggle-meta_purchases").check();
  await page.getByTestId("column-toggle-tracker_sales").check();
  await page
    .getByLabel("Название нового набора")
    .fill("Моя экономика — приёмка");
  await page
    .getByRole("button", { name: "Создать набор", exact: true })
    .click();
  await page.getByLabel("Закрыть настройку колонок").click();
  await saved(page);
  await expect(page.getByLabel("Набор колонок")).toHaveValue(/^[a-f0-9-]{36}$/);
  await page.locator(".customizable-table-wrap").evaluate((el) => {
    el.scrollLeft = 0;
  });
  await page.evaluate(() => {
    window.__economicsDrag = [];
    for (const type of ["dragstart", "dragover", "drop", "dragend"]) {
      document.addEventListener(type, (e) => {
        window.__economicsDrag.push({
          type,
          column: e.target
            .closest("[data-column]")
            ?.getAttribute("data-column"),
          x: e.clientX,
          y: e.clientY,
        });
      });
    }
  });
  await page.getByTestId("drag-spend").hover();
  const dropBox = await page.getByTestId("column-profile_name").boundingBox();
  await page.mouse.down();
  await page.mouse.move(dropBox.x + 30, dropBox.y + 15, { steps: 10 });
  await page.mouse.move(dropBox.x + 31, dropBox.y + 16);
  await page.mouse.up();
  try {
    await expect(page.locator("thead th[data-column]").nth(1)).toHaveAttribute(
      "data-column",
      "spend",
    );
  } catch (error) {
    await testInfo.attach("native-drag-events", {
      body: Buffer.from(
        JSON.stringify(
          await page.evaluate(() => ({
            events: window.__economicsDrag,
            columns: Array.from(
              document.querySelectorAll("thead th[data-column]"),
            ).map((e) => ({
              column: e.getAttribute("data-column"),
              x: e.getBoundingClientRect().x,
              width: e.getBoundingClientRect().width,
            })),
          })),
        ),
      ),
      contentType: "application/json",
    });
    throw error;
  }
  await saved(page);
  await page.getByTestId("resize-name").scrollIntoViewIfNeeded();
  const box = await page.getByTestId("resize-name").boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + 85, box.y + box.height / 2, { steps: 12 });
  await page.mouse.up();
  await saved(page);
  await page.getByTestId("resize-target_cpl").scrollIntoViewIfNeeded();
  await page.getByTestId("resize-target_cpl").dblclick();
  await saved(page);
  const snapshot = (
    await (
      await page.request.get("/api/preferences/columns/eco_account")
    ).json()
  ).preference.config;
  expect(snapshot.columns[1].key).toBe("spend");
  expect(snapshot.columns.find((c) => c.key === "name").width).toBeGreaterThan(
    280,
  );
  expect(snapshot.columns.some((c) => c.key === "approved_sales")).toBe(true);
  await page.getByTestId("column-target_cpl").locator(".sort-heading").click();
  await saved(page);
  const before = (
    await (
      await page.request.get("/api/preferences/columns/eco_account")
    ).json()
  ).preference.config;
  await page.getByRole("button", { name: "Выйти", exact: true }).click();
  await expect(page).toHaveURL(/\/login$/);
  await login(page, accounts[0]);
  signedIn.state = await page.context().storageState();
  await open(page);
  await saved(page);
  const after = (
    await (
      await page.request.get("/api/preferences/columns/eco_account")
    ).json()
  ).preference.config;
  expect(after).toEqual(before);
  await expect(page.getByLabel("Набор колонок")).toHaveValue(/^[a-f0-9-]{36}$/);
  for (const width of [1440, 768, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await expect(
      page.getByRole("heading", { name: "Экономика рекламы", exact: true }),
    ).toBeVisible();
    try {
      await expect
        .poll(
          () =>
            page.evaluate(
              () =>
                document.documentElement.scrollWidth <= window.innerWidth + 1,
            ),
          { message: `No page overflow at ${width}px after layout settles` },
        )
        .toBe(true);
    } catch (error) {
      await testInfo.attach("layout-overflow", {
        body: Buffer.from(
          JSON.stringify(
            await page.evaluate(() => ({
              width: innerWidth,
              scroll: document.documentElement.scrollWidth,
              surfaces: Array.from(
                document.querySelectorAll(
                  "html,body,main,.economics-surface,.tablewrap,section",
                ),
              ).map((e) => ({
                tag: e.tagName,
                cls: e.className,
                width: e.getBoundingClientRect().width,
                x: e.getBoundingClientRect().x,
                right: e.getBoundingClientRect().right,
                scroll: e.scrollWidth,
                client: e.clientWidth,
                contain: getComputedStyle(e).contain,
                overflow: getComputedStyle(e).overflowX,
              })),
              overflowingCells: Array.from(
                document.querySelectorAll(
                  ".customizable-table th,.customizable-table td",
                ),
              )
                .map((e) => ({
                  tag: e.tagName,
                  col: e.getAttribute("data-column"),
                  x: e.getBoundingClientRect().x,
                  right: e.getBoundingClientRect().right,
                  width: e.getBoundingClientRect().width,
                  position: getComputedStyle(e).position,
                }))
                .filter((e) => e.right > innerWidth + 1)
                .slice(0, 25),
              elements: Array.from(document.querySelectorAll("body *"))
                .filter(
                  (e) => !e.closest(".customizable-table-wrap,.tablewrap"),
                )
                .map((e) => ({
                  tag: e.tagName,
                  cls: e.className,
                  text: e.textContent.slice(0, 120),
                  x: e.getBoundingClientRect().x,
                  right: e.getBoundingClientRect().right,
                  width: e.getBoundingClientRect().width,
                  overflow: getComputedStyle(e).overflowX,
                }))
                .filter((e) => e.right > innerWidth + 1 || e.x < 0),
            })),
          ),
        ),
        contentType: "application/json",
      });
      throw error;
    }
    const wrap = page.locator(".customizable-table-wrap");
    const beforeX = (
      await page.locator("td.identity-column").first().boundingBox()
    ).x;
    await wrap.evaluate((el) => {
      el.scrollLeft = 600;
    });
    expect(await wrap.evaluate((el) => el.scrollLeft)).toBeGreaterThan(0);
    const afterX = (
      await page.locator("td.identity-column").first().boundingBox()
    ).x;
    expect(Math.abs(afterX - beforeX)).toBeLessThanOrEqual(1);
    expect(
      await page
        .locator("td.identity-column")
        .first()
        .evaluate((el) => getComputedStyle(el).position),
    ).toBe("sticky");
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
  await saved(page);
  await expect(page.getByLabel("Набор колонок")).toHaveValue("system:basic");
});

test("permissions: VIEWER read only, OPERATOR requires explicit ADMIN grant", async ({
  page,
  browser,
  accounts,
  audit,
}) => {
  test.setTimeout(120000);
  await open(page, "Апрув и назначения");
  const checkbox = page.getByLabel(
    accounts[1].login + ": редактирование экономики",
    { exact: true },
  );
  await expect(checkbox).not.toBeChecked();
  const operatorContext = await browser.newContext({
      baseURL: process.env.UI_BASE_URL ?? "http://127.0.0.1:3000",
      storageState: { cookies: [], origins: [] },
    }),
    operatorPage = await operatorContext.newPage();
  watch(operatorPage, audit);
  await login(operatorPage, accounts[1]);
  await open(operatorPage, "Профили");
  await expect(
    operatorPage.getByRole("button", {
      name: "Сохранить профиль",
      exact: true,
    }),
  ).toBeDisabled();
  const viewerContext = await browser.newContext({
      baseURL: process.env.UI_BASE_URL ?? "http://127.0.0.1:3000",
      storageState: { cookies: [], origins: [] },
    }),
    viewerPage = await viewerContext.newPage();
  watch(viewerPage, audit);
  await login(viewerPage, accounts[2]);
  await open(viewerPage, "Профили");
  await expect(
    viewerPage.getByRole("button", { name: "Сохранить профиль", exact: true }),
  ).toBeDisabled();
  await viewerContext.close();
  await checkbox.click();
  await expect(checkbox).toBeChecked();
  await expect(page.getByRole("status")).toContainText("Доступ обновлён");
  await open(operatorPage, "Профили");
  await expect(
    operatorPage.getByRole("button", {
      name: "Сохранить профиль",
      exact: true,
    }),
  ).toBeEnabled();
  await checkbox.click();
  await expect(checkbox).not.toBeChecked();
  await expect(page.getByRole("status")).toContainText("Доступ обновлён");
  await open(operatorPage, "Профили");
  await expect(
    operatorPage.getByRole("button", {
      name: "Сохранить профиль",
      exact: true,
    }),
  ).toBeDisabled();
  await operatorContext.close();
});
