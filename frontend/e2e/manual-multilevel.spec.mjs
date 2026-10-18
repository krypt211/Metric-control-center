import {expect} from "@playwright/test";
import {test, login} from "./rules-fixtures.mjs";

test.use({storageState:{cookies:[],origins:[]}});
test("browser-only mock rehearses all six status intents without storing commands", async ({page, accounts}) => {
  test.setTimeout(120000);
  page.setDefaultTimeout(15000);
  await login(page, accounts.users[0]);
  const settings = await (await page.request.get("/api/manual-control/settings")).json();
  const account = settings.accounts.find(value => value.provider === "metricflow");
  expect(account).toBeTruthy();
  const realBefore = await (await page.request.get("/api/manual-control/requests")).json();
  let intent = "PAUSE", record = null;
  const sent = [];
  const rowFor = level => ({
    id:"00000000-0000-4000-8000-" + String(["ad","adset","campaign"].indexOf(level)+1).padStart(12,"0"),
    name:"Browser-only synthetic " + level, entity_level:level, provider:"metricflow", source_provider:"metricflow",
    meta_ad_id:"999000000" + String(["ad","adset","campaign"].indexOf(level)+1),
    external_id:"999000000" + String(["ad","adset","campaign"].indexOf(level)+1),
    account_id:account.id, account_name:account.name, currency:"USD", timezone:"Europe/Moscow",
    status:intent === "PAUSE" ? "ACTIVE" : "PAUSED", status_refreshed_at:new Date().toISOString(),
    hierarchy:[null,null], recommendation:null,
  });
  await page.route(url => url.pathname === "/api/manual-control/ads", async route => {
    const row = rowFor(new URL(route.request().url()).searchParams.get("level") ?? "ad");
    await route.fulfill({json:{rows:[row],total:1,next_offset:null,start:"2026-10-11",end:"2026-10-17"}});
  });
  await page.route(url => url.pathname.startsWith("/api/manual-control/requests"), async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    if (request.method() === "GET") return route.fulfill({json:{requests:record?[record]:[]}});
    const body = request.postDataJSON();
    if (path === "/api/manual-control/requests") {
      const level = body.entity_level, row = rowFor(level);
      expect(body.operation).toBe(intent + "_" + level.toUpperCase());
      expect(body.external_id ?? body.meta_ad_id).toBe(row.meta_ad_id);
      expect(body.entity_id).toBe(row.id);
      sent.push(body.operation);
      record = {id:row.id,revision:1,status:"DRAFT",display_status:"DRAFT",operation:body.operation,
        created_at:new Date().toISOString(),actor:"browser mock",provider:"metricflow",reason:body.reason,
        meta_ad_id:row.meta_ad_id,expected_status:row.status,target_status:intent === "PAUSE"?"PAUSED":"ACTIVE",
        expires_at:new Date(Date.now()+600000).toISOString(),captured:{name:row.name,account_name:row.account_name,status_refreshed_at:row.status_refreshed_at},
        preflight:null,result:null,events:[]};
    } else {
      expect(body.revision).toBe(record.revision);
      const event = path.split("/").at(-1);
      expect(["preflight","confirm","simulate"]).toContain(event);
      record = {...record,revision:record.revision+1,status:{preflight:"BLOCKED",confirm:"CONFIRMED",simulate:"SIMULATED"}[event],
        preflight:{local_allowed:true,checked_at:new Date().toISOString(),reason_codes:["WRITE_DISABLED"],blocking_reasons:[]},
        result:event === "simulate"?"LOCAL_SIMULATION_ONLY":null};
      record.display_status = record.status;
    }
    return route.fulfill({status:path.endsWith("/requests")?201:200,json:record});
  });
  for (const level of ["campaign","adset","ad"]) {
    for (intent of ["PAUSE","ENABLE"]) {
      record = null;
      await page.goto("/manual-control");
      await expect(page.getByLabel("Набор колонок")).toBeEnabled();
      await page.getByLabel("Уровень управления", {exact:true}).selectOption(level);
      await page.getByLabel("Кабинет", {exact:true}).click();
      await page.getByRole("combobox", {name:"Поиск: Кабинет", exact:true}).fill(account.id);
      await page.getByRole("listbox", {name:"Кабинет результаты", exact:true}).getByRole("option").first().click();
      const row = rowFor(level);
      const shownRow = page.locator("tbody tr").filter({hasText:row.meta_ad_id});
      await shownRow.locator("td.selection-column").getByRole("checkbox").check();
      await page.getByRole("button", {name:level === "ad"?"Открыть выбранное объявление":"Открыть выбранный объект",exact:true}).click();
      const panel = page.getByRole("article", {name:level === "ad"?"Выбранное объявление":"Выбранный объект",exact:true});
      await panel.getByLabel("Причина ручной команды").fill("Browser mock only, no advertising request");
      await panel.getByRole("button", {name:intent === "PAUSE"?"Подготовить отключение":"Подготовить включение",exact:true}).click();
      const draft = page.getByRole("region", {name:"Подготовленное действие",exact:true});
      await expect(draft).toContainText("DRAFT");
      await draft.getByRole("button", {name:"Проверить команду",exact:true}).click();
      await expect(draft).toContainText("LIVE: заблокирован");
      await draft.getByRole("button", {name:"Подтвердить намерение для симуляции",exact:true}).click();
      await draft.getByRole("button", {name:"Выполнить локальную симуляцию",exact:true}).click();
      await expect(draft).toContainText("SIMULATED");
    }
  }
  expect(sent).toEqual(["PAUSE_CAMPAIGN","ENABLE_CAMPAIGN","PAUSE_ADSET","ENABLE_ADSET","PAUSE_AD","ENABLE_AD"]);
  expect((await (await page.request.get("/api/manual-control/requests")).json()).requests).toEqual(realBefore.requests);
});
