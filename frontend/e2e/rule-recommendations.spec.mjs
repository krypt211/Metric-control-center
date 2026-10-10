import { expect } from "@playwright/test";
import { test, login, watch } from "./rules-fixtures.mjs";

test.use({ storageState: { cookies: [], origins: [] } });
test.describe.configure({ mode: "serial" });
let rule, run, name;

async function write(page, path, method, body) {
  const csrf = await (await page.request.get("/api/auth/csrf")).json();
  const response = await page.request.fetch("/api/smart-rules" + path, {
    method,
    headers: { "X-CSRF-Token": csrf.csrf_token, Origin: new URL(page.url()).origin },
    data: body,
  });
  expect(response.ok()).toBeTruthy();
  return response.json();
}
async function center(page) {
  await page.goto("/recommendations");
  await expect(
    page.getByRole("heading", { name: "Центр рекомендаций", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Обновить сводку", exact: true }),
  ).toBeEnabled();
}
async function openRun(page) {
  await page
    .getByRole("button", { name: "Открыть результаты: " + name, exact: true })
    .click();
  await expect(page.getByTestId("statistics-table")).toBeVisible();
  await expect(
    page.getByRole("article", { name: "Объяснение решения" }),
  ).toBeVisible();
}

test("real saved simulation, filters, shared columns, immutable recheck and history link", async ({
  page,
  accounts,
}, info) => {
  test.setTimeout(120000);
  await login(page, accounts.users[0]);
  const scopes = await (
    await page.request.get("/api/smart-rules/available-scopes")
  ).json();
  name =
    "Центр рекомендаций — проверка русских названий " + accounts.users[0].id;
  const definition = {
    ...scopes.templates[0],
    name,
    profile_id: accounts.profile.id,
    selection: {
      ...scopes.templates[0].selection,
      account_ids: [accounts.account_id],
    },
  };
  rule = await write(page, "", "POST", definition);
  run = await write(page, `/${rule.id}/simulate`, "POST", {
    version: rule.revision,
  });
  expect(run.total).toBeGreaterThan(0);
  expect(run.rows.every((row) => row.real_action === false)).toBeTruthy();
  let onCenter = false;
  const centerWrites = [];
  page.on("request", (request) => {
    if (
      onCenter &&
      request.method() !== "GET" &&
      new URL(request.url()).pathname.startsWith("/api/smart-rules")
    )
      centerWrites.push(request.url());
  });
  onCenter = true;
  await center(page);
  await openRun(page);
  const first = run.rows[0];
  await page.getByLabel("Поиск объявления").fill(first.external_id ?? first.id);
  await expect(
    page.getByTestId("statistics-table").locator("tbody"),
  ).toContainText(first.name);
  await page.getByLabel("Результат проверки").selectOption("WOULD_PAUSE");
  if (!run.counts.WOULD_PAUSE)
    await expect(
      page.getByText("Нет объявлений по выбранному фильтру.", { exact: true }),
    ).toBeVisible();
  await page.getByLabel("Результат проверки").selectOption("");
  await page.getByLabel("Поиск объявления").fill("");
  await page
    .getByRole("button", { name: "Настроить колонки", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page
    .getByRole("button", { name: "Закрыть настройку колонок", exact: true })
    .click();
  for (const width of [1440, 768, 390]) {
    await page.setViewportSize({ width, height: 900 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth + 1,
      ),
    ).toBeTruthy();
    const wrap = page.locator(".customizable-table-wrap");
    expect(
      await wrap.evaluate((el) => el.scrollWidth > el.clientWidth),
    ).toBeTruthy();
    await wrap.evaluate((el) => {
      el.scrollLeft = 200;
    });
    const delta = await wrap.evaluate((el) =>
      Math.abs(
        el.querySelector("th.identity-column").getBoundingClientRect().left -
          el.getBoundingClientRect().left,
      ),
    );
    expect(delta).toBeLessThanOrEqual(2);
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  onCenter = false;
  await page
    .getByRole("link", { name: "Правило и история: " + name, exact: true })
    .click();
  await expect(page.getByLabel("Открыть правило")).toHaveValue(rule.id);
  await expect(page.getByLabel("Название правила")).toHaveValue(name);
  await page
    .getByLabel("Описание")
    .fill("Изменено после сохранённого результата");
  await page
    .getByRole("button", { name: "Сохранить правило", exact: true })
    .click();
  await expect(page.locator("p.notice[role=status]")).toContainText("версия 2");
  onCenter = true;
  await center(page);
  const card = page
    .getByRole("article")
    .filter({ has: page.getByRole("heading", { name, exact: true }) });
  await expect(card).toContainText("Правило изменилось после проверки");
  await openRun(page);
  await expect(
    page.getByText(
      "Этот результат требует повторной проверки. Сохранённые решения показаны без изменений.",
      { exact: true },
    ),
  ).toBeVisible();
  const saved = await (
    await page.request.get(`/api/smart-rules/simulations/${run.id}`)
  ).json();
  expect(saved).toEqual(run);
  expect(centerWrites).toEqual([]);
  await info.attach("center-read-only-audit", {
    body: Buffer.from(JSON.stringify({ advertisingMutations: centerWrites })),
    contentType: "application/json",
  });
});

test("VIEWER and OPERATOR read same immutable recommendations without rule privileges", async ({
  page,
  accounts,
  audit,
}) => {
  await login(page, accounts.users[2]);
  await center(page);
  await openRun(page);
  await expect(
    page.getByText("Реальное действие: запрещено.", { exact: false }),
  ).toBeVisible();
  const response = await page.request.get("/api/smart-rules/recommendations");
  expect(response.ok()).toBeTruthy();
  expect(response.headers()["cache-control"] ?? "").toContain("no-store");
  const context = await page
    .context()
    .browser()
    .newContext({
      baseURL: process.env.UI_BASE_URL ?? "http://127.0.0.1:3000",
      storageState: { cookies: [], origins: [] },
    });
  try {
    const operator = await context.newPage();
    watch(operator, audit);
    await login(operator, accounts.users[1]);
    await center(operator);
    await openRun(operator);
    await operator.goto(`/rules?rule=${rule.id}`);
    await expect(operator.getByLabel("Название правила")).toBeDisabled();
    await expect(
      operator.getByRole("button", { name: "Проверить правила", exact: true }),
    ).toBeDisabled();
  } finally {
    await context.close();
  }
});

test("browser-only empty/pending page, pagination and long names without invented ad facts", async ({
  page,
  accounts,
}) => {
  await login(page, accounts.users[0]);
  const longName =
    "Ожидает проверки — длинное русское название правила ".repeat(2);
  await page.route("**/api/smart-rules/recommendations?*", (route) => {
    const offset = Number(
      new URL(route.request().url()).searchParams.get("offset"),
    );
    return route.fulfill({
      json: {
        mode: "DRY_RUN",
        real_action: false,
        as_of: new Date().toISOString(),
        rows: offset
          ? []
          : [
              {
                rule_id: "00000000-0000-0000-0000-000000000001",
                name: longName,
                rule_revision: 1,
                simulation_id: null,
                simulation_revision: null,
                created_at: null,
                start: null,
                end: null,
                counts: {},
                total: 0,
                recheck_reasons: ["NOT_EVALUATED"],
                priority: "NOT_EVALUATED",
              },
            ],
        counts: {},
        total_rules: 51,
        offset,
        next_offset: offset ? null : 50,
      },
    });
  });
  await center(page);
  await expect(
    page.getByRole("button", {
      name: "Открыть результаты: " + longName,
      exact: true,
    }),
  ).toBeDisabled();
  await expect(
    page.getByText("Нужна проверка: Проверка ещё не запускалась", {
      exact: true,
    }),
  ).toBeVisible();
  for (const width of [1440, 768, 390]) {
    await page.setViewportSize({ width, height: 900 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth + 1,
      ),
    ).toBeTruthy();
  }
  await page.getByLabel("Поиск правила").fill("Не существует");
  await expect(
    page.getByRole("heading", { name: "Правила не найдены", exact: true }),
  ).toBeVisible();
  await page.getByLabel("Поиск правила").fill("");
  await page
    .getByRole("button", { name: "Следующие наборы", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Предыдущие наборы", exact: true }),
  ).toBeEnabled();
  await page
    .getByRole("button", { name: "Предыдущие наборы", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: longName, exact: true }),
  ).toBeVisible();
});
