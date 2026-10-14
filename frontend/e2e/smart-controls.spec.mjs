import {expect} from "@playwright/test";
import {test,login} from "./rules-fixtures.mjs";

test.use({storageState:{cookies:[],origins:[]}});
test("core controls save PAUSE ENABLE NOTIFY, scheduler activation remains DRY RUN",async({page,accounts})=>{
  test.setTimeout(120000);
  await login(page,accounts.users[0]);await page.goto("/rules");
  await expect(page.getByRole("combobox",{name:"Действие правила",exact:true})).toHaveValue("PAUSE_AD");
  await page.getByLabel("Название правила",{exact:true}).fill("Smart core browser acceptance");
  await page.getByRole("combobox",{name:"Экономический профиль",exact:true}).selectOption(accounts.profile.id);
  await page.getByRole("combobox",{name:"Действие правила",exact:true}).selectOption("ENABLE_AD");
  await expect(page.getByLabel(/Разрешить проверку повторного включения/)).not.toBeChecked();
  await page.getByRole("combobox",{name:"Условие 1",exact:true}).selectOption("CPL_AT_OR_BELOW_LIMIT");
  await page.getByLabel("Приоритет правила",{exact:true}).fill("10");
  await page.getByLabel("Cooldown, секунд",{exact:true}).fill("3600");
  await page.getByLabel(/Проверять правило каждые 30 минут/).check();
  await page.getByRole("button",{name:"Сохранить правило",exact:true}).click();
  await expect(page.getByText(/Правило сохранено/).first()).toBeVisible();
  let rules=await (await page.request.get("/api/smart-rules")).json();
  let rule=rules.rules.find(r=>r.definition.name==="Smart core browser acceptance");
  expect(rule.definition).toMatchObject({action:"ENABLE_AD",enabled:true,allow_reenable:false,priority:10,cooldown_seconds:3600,mode:"DRY_RUN"});
  const response=page.waitForResponse(r=>r.url().endsWith("/simulate") && r.request().method()==="POST");
  await page.getByRole("button",{name:"Проверить правила",exact:true}).click();
  const simulation=await (await response).json();
  expect(simulation.mode).toBe("DRY_RUN");expect(simulation.action_eligibility).toBe(false);
  expect(simulation.counts.WOULD_ENABLE ?? 0).toBe(0);
  await expect(page.locator("p.notice[role=status]")).toContainText("DRY RUN завершён");
  await expect(page.getByRole("button",{name:"Подготовить включение",exact:true})).toHaveCount(0);
  await page.getByRole("combobox",{name:"Действие правила",exact:true}).selectOption("NOTIFY_ONLY");
  await page.getByLabel(/Проверять правило каждые 30 минут/).uncheck();
  await page.getByRole("button",{name:"Сохранить правило",exact:true}).click();
  await expect(page.getByText(/Правило сохранено/).first()).toBeVisible();
  rules=await (await page.request.get("/api/smart-rules")).json();rule=rules.rules.find(r=>r.id===rule.id);
  expect(rule.definition.action).toBe("NOTIFY_ONLY");expect(rule.definition.enabled).toBe(false);
  expect(rule.next_evaluation_at).toBe(null);
});

test("profile timezone is explicit and persisted without changing payout formulas",async({page,accounts})=>{
  await login(page,accounts.users[0]);await page.goto("/economics?tab=profiles");
  await expect(page.getByLabel("Timezone профиля",{exact:true})).toBeVisible();
  await page.getByLabel("Редактируемый профиль",{exact:true}).selectOption(accounts.profile.id);
  await page.getByLabel("Timezone профиля",{exact:true}).fill("America/Los_Angeles");
  await expect(page.getByLabel("Timezone профиля",{exact:true})).toHaveValue("America/Los_Angeles");
  await page.getByRole("button",{name:"Сохранить профиль",exact:true}).click();
  await expect.poll(async()=> (await (await page.request.get("/api/smart-rules/available-scopes")).json()).profiles.find(p=>p.id===accounts.profile.id)?.timezone).toBe("America/Los_Angeles");
  await page.reload();await page.getByLabel("Редактируемый профиль",{exact:true}).selectOption(accounts.profile.id);
  await expect(page.getByLabel("Timezone профиля",{exact:true})).toHaveValue("America/Los_Angeles");
  await expect(page.getByLabel("Выплата за апрув",{exact:true})).toHaveValue("16");
});
