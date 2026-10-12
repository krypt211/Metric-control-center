import {expect} from "@playwright/test";
import {test,login} from "./rules-fixtures.mjs";
test.use({storageState:{cookies:[],origins:[]}});
test.describe.configure({mode:"serial"});
let ruleID, selection=[];
async function open(page,accounts){
 await login(page,accounts.users[0]);await page.goto("/rules");
 await expect(page.getByLabel("Название правила")).toBeEnabled();
}
function picker(page){return page.getByRole("region",{name:"Выбор объектов правила"}).last();}
async function rows(page){
 await expect(picker(page).locator("tbody tr").first()).toBeVisible();
 return picker(page).locator("tbody tr");
}
async function chooseType(page,kind){
 await picker(page).getByRole("button",{name:kind,exact:true}).click();
 await rows(page);
}
async function write(page,path,body){
 const csrf=await(await page.request.get("/api/auth/csrf")).json();
 const response=await page.request.post("/api/smart-rules"+path,{headers:{Origin:new URL(page.url()).origin,"X-CSRF-Token":csrf.csrf_token},data:body});
 expect(response.ok()).toBeTruthy();return response.json();
}
test("full catalog search, cross-page mixed selection, page header and explicit all-results confirmation",async({page,accounts,audit})=>{
 await open(page,accounts);
 const p=picker(page);await rows(page);
 const firstName=await p.locator("tbody tr").first().locator("td").nth(1).innerText();
 await p.locator("tbody tr").first().getByRole("checkbox").check();
 await expect(p.getByRole("status").filter({hasText:"Выбрано:"})).toContainText("Выбрано: 1");
 await p.getByLabel("Поиск объектов",{exact:true}).fill("definitely-no-such-object-987");
 await expect(p.getByText("Ничего не найдено",{exact:true})).toBeVisible();
 await expect(p.getByRole("status").filter({hasText:"Выбрано:"})).toContainText("Выбрано: 1");
 await p.getByRole("button",{name:"Очистить поиск объектов",exact:true}).click();await rows(page);
 await expect(p.locator("tbody tr").filter({hasText:firstName}).getByRole("checkbox")).toBeChecked();
 if(await p.getByRole("button",{name:"Следующая страница",exact:true}).isEnabled()){
  await p.getByRole("button",{name:"Следующая страница",exact:true}).click();await rows(page);
  await p.locator("tbody tr").first().getByRole("checkbox").check();
  await expect(p.getByRole("status").filter({hasText:"Выбрано:"})).toContainText("Выбрано: 2");
  await p.getByRole("button",{name:"Предыдущая страница",exact:true}).click();await rows(page);
 }
 await p.getByRole("checkbox",{name:"Выбрать текущую страницу",exact:true}).check();
 await expect(p.locator("tbody input[type=checkbox]:checked")).toHaveCount(await p.locator("tbody tr").count());
 await p.getByRole("button",{name:"Очистить выбор",exact:true}).click();
 const response=await page.request.get("/api/smart-rules/catalog/search?kind=campaign&limit=1");const campaign=(await response.json()).rows[0];
 await p.getByLabel("Поиск объектов",{exact:true}).fill(campaign.external_id);
 await expect(p.locator("tbody tr").first()).toContainText(campaign.external_id);
 await p.getByRole("button",{name:/Выбрать все найденные/}).click();
 await expect(p.getByRole("dialog",{name:"Подтверждение полного выбора"})).toBeVisible();
 await p.getByRole("button",{name:"Подтвердить весь результат",exact:true}).click();
 await expect(p.getByRole("status").filter({hasText:"Выбрано:"})).toContainText("Выбрано:");
 await p.getByRole("button",{name:"Очистить поиск объектов",exact:true}).click();
 await chooseType(page,"группы");await p.locator("tbody tr").first().getByRole("checkbox").check();
 await chooseType(page,"объявления");await p.locator("tbody tr").first().getByRole("checkbox").check();
 await p.getByRole("button",{name:"Просмотреть выбранное",exact:true}).click();
 await expect(p.locator(".selected-targets")).toContainText("CAMPAIGN");
 await expect(p.locator(".selected-targets")).toContainText("ADSET");
 await expect(p.locator(".selected-targets")).toContainText("AD");
 await page.getByLabel("Название правила").fill("Phase 3.1 "+accounts.users[0].id);
 await page.getByRole("combobox",{name:"Экономический профиль",exact:true}).selectOption(accounts.profile.id);
 await page.getByRole("button",{name:"Сохранить правило",exact:true}).click();
 await expect(page.locator("p.notice[role=status]")).toContainText("Правило сохранено");
 ruleID=await page.getByLabel("Открыть правило").inputValue();
 const actions=page.getByRole("region",{name:"Массовые назначения"});
 await actions.getByRole("button",{name:"Назначить правило выбранным",exact:true}).click();
 const dialog=actions.getByRole("dialog",{name:"Массовое назначение правила"});
 await dialog.getByRole("button",{name:"Правило для выбранных",exact:true}).click();
 await expect(dialog.getByRole("option").filter({hasText:"Phase 3.1"})).toHaveCount(1);
 await dialog.getByRole("combobox",{name:"Поиск: Правило для выбранных",exact:true}).press("Escape");
 await dialog.getByRole("button",{name:"Отменить",exact:true}).click();
 const rule=await(await page.request.get("/api/smart-rules/"+ruleID)).json();selection=rule.definition.selection.targets;
 expect(selection.length).toBeGreaterThanOrEqual(3);
 await page.reload();await page.getByLabel("Открыть правило").selectOption(ruleID);
 await expect(p.getByRole("status").filter({hasText:"Выбрано:"})).toContainText("Выбрано: "+selection.length);
});
test("bulk existing assignment, remove only direct origin, selected dry run and immutable history",async({page,accounts,audit})=>{
 await open(page,accounts);await page.getByLabel("Открыть правило").selectOption(ruleID);
 const actions=page.getByRole("region",{name:"Массовые назначения"});
 await actions.getByRole("button",{name:"Назначить правило выбранным",exact:true}).click();
 const dialog=actions.getByRole("dialog",{name:"Массовое назначение правила"});
 await dialog.getByRole("button",{name:"Правило для выбранных",exact:true}).click();
 await dialog.getByRole("combobox",{name:"Поиск: Правило для выбранных",exact:true}).fill("Phase 3.1");
 await dialog.getByRole("option").first().click();
 const save=page.waitForResponse(r=>r.url().endsWith("/assignments/bulk")&&r.request().method()==="POST");
 await dialog.getByRole("button",{name:"Сохранить назначения",exact:true}).click();const saved=await(await save).json();
 expect(saved.definition.selection.targets.length).toBe(selection.length);
 // Refresh the constructor from PostgreSQL after a bulk revision change.
 await page.reload();await page.getByLabel("Открыть правило").selectOption(ruleID);
 const fresh=await(await page.request.get("/api/smart-rules/"+ruleID)).json();
 const removed=await write(page,"/"+ruleID+"/assignments/bulk",{revision:fresh.revision,operation:"remove",targets:[selection.find(t=>t.scope_type==="AD")]});
 expect(removed.definition.selection.targets.some(t=>t.scope_type==="CAMPAIGN")).toBeTruthy();
 expect(removed.definition.selection.targets.length).toBe(selection.length-1);
 const result=await write(page,"/"+ruleID+"/simulate-selected",{revision:removed.revision,targets:[selection.find(t=>t.scope_type==="CAMPAIGN")]});
 expect(result.action_eligibility).toBe(false);
 expect(new Set(result.rows.map(r=>[r.source_provider,r.account_id,r.id].join(":"))).size).toBe(result.total);
 expect(result.rows.every(r=>r.real_action===false&&r.target_provenance.length===1)).toBeTruthy();
 const history=await(await page.request.get("/api/smart-rules/"+ruleID+"/history")).json();
 expect(history.simulations.some(s=>s.id===result.id)).toBeTruthy();expect(history.versions.length).toBeGreaterThanOrEqual(3);
});
test("four searchable dropdowns and keyboard navigation retain single and multi behavior",async({page,accounts,audit})=>{
 await open(page,accounts);
 const p=picker(page);
 const ad=(await(await page.request.get("/api/smart-rules/catalog/search?kind=ad&limit=1")).json()).rows[0];
 const ids=[ad.account_id,ad.campaign_id,ad.adset_id,ad.id];let index=0;
 for(const label of ["Кабинеты фильтр","Кампании фильтр","Группы фильтр","Объявления выбор"]){
  await p.getByRole("button",{name:label,exact:true}).click();
  const search=p.getByRole("combobox",{name:"Поиск: "+label,exact:true});await expect(search).toBeFocused();
  await expect(p.getByRole("option").first()).toBeVisible();
  const id=ids[index++];
  await search.fill(id);await expect(p.getByRole("option").first()).toBeVisible();
  await search.press("ArrowDown");await search.press("ArrowUp");await search.press("Enter");
  await expect(search).toBeVisible();await search.press("Escape");await expect(search).not.toBeVisible();
 }
 await expect(p.getByRole("status").filter({hasText:"Выбрано:"})).toContainText("Выбрано: 1");
});
for(const width of [1440,1024,768,390]){
 test("responsive target picker "+width,async({page,accounts,audit})=>{
  await page.setViewportSize({width,height:900});await open(page,accounts);await rows(page);
  await picker(page).locator("tbody tr").first().getByRole("checkbox").check();
  await picker(page).getByRole("button",{name:"Просмотреть выбранное",exact:true}).click();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1)).toBeTruthy();
  await picker(page).getByRole("button",{name:"Кабинеты фильтр",exact:true}).click();
  await expect(picker(page).getByRole("combobox",{name:"Поиск: Кабинеты фильтр",exact:true})).toBeFocused();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1)).toBeTruthy();
  await page.screenshot({path:"test-results/targets-"+width+".png",fullPage:true});
 });
}
