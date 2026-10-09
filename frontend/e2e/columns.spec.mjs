import {test as base,expect} from "@playwright/test";
import {execFileSync} from "node:child_process";
import {readFileSync} from "node:fs";
import path from "node:path";
import {randomUUID} from "node:crypto";
const root=path.resolve(import.meta.dirname,"../..");
const docker=process.env.DOCKER_EXE??(process.platform==="win32"?path.join(process.env.LOCALAPPDATA,"Programs/DockerDesktop/resources/bin/docker.exe"):"docker");
function fixture(mode,nonce){
 const source=readFileSync(new URL("./accounts.py",import.meta.url),"utf8");
 const args=["compose","--project-directory",root,"--env-file",path.join(root,".env"),"-f",path.join(root,"docker-compose.yml"),"-p","metric-control-center","exec","-T","-e","UI_FIXTURE_MODE="+mode,"-e","UI_FIXTURE_NONCE="+nonce,"backend","python","-c","import sys; exec(sys.stdin.read())"];
 return JSON.parse(execFileSync(docker,args,{input:source,encoding:"utf8",windowsHide:true}));
}
function watchPage(page,audit){
 page.on("pageerror",error=>audit.pageErrors.push(error.message));
 page.on("console",message=>{if(message.type()==="error")audit.consoleErrors.push(message.text());});
 page.on("request",request=>{const url=new URL(request.url());if(!["GET","HEAD","OPTIONS"].includes(request.method())&&/^\/api\/(actions|ai|automation)(\/|$)/.test(url.pathname))audit.advertisingMutations.push({method:request.method(),path:url.pathname});});
}
const test=base.extend({
 signedIn:[async({browser,accounts},use)=>{
  const context=await browser.newContext({baseURL:process.env.UI_BASE_URL??"http://127.0.0.1:3000"});const page=await context.newPage();const audit={consoleErrors:[],pageErrors:[],advertisingMutations:[]};watchPage(page,audit);
  await login(page,accounts[0]);const state=await context.storageState();await context.close();await use({state,audit});
 },{scope:"worker"}],
 storageState:async({signedIn},use)=>{await use(signedIn.state);},
 browserAudit:[async({page,context,signedIn},use,testInfo)=>{
  const audit={consoleErrors:[...signedIn.audit.consoleErrors],pageErrors:[...signedIn.audit.pageErrors],advertisingMutations:[...signedIn.audit.advertisingMutations]};watchPage(page,audit);context.on("page",p=>watchPage(p,audit));
  await use(audit);
  await testInfo.attach("browser-audit",{body:Buffer.from(JSON.stringify(audit)),contentType:"application/json"});
  expect(audit.pageErrors,"Uncaught browser exceptions").toEqual([]);
  expect(audit.consoleErrors,"Browser console errors").toEqual([]);
  expect(audit.advertisingMutations,"Advertising mutation requests forbidden").toEqual([]);
 },{auto:true}],
 accounts:[async({},use)=>{const nonce=randomUUID().replaceAll("-","");try{await use(fixture("create",nonce));}finally{fixture("cleanup",nonce);}}, {scope:"worker"}],
});
async function login(page,user){await page.goto("/login");await page.getByLabel("Логин или email").fill(user.login);await page.getByLabel("Пароль",{exact:true}).fill(user.password);await page.getByRole("button",{name:"Войти",exact:true}).click();await expect(page).toHaveURL(/\/$/);}
async function open(page,section="Статистика"){await page.getByRole("navigation",{name:"Раздел"}).getByRole("button",{name:section,exact:true}).click();await expect(page.getByLabel("Набор колонок")).toBeEnabled();}
async function saved(page){await expect(page.getByLabel("\u041d\u0430\u0431\u043e\u0440 \u043a\u043e\u043b\u043e\u043d\u043e\u043a")).toBeEnabled();await expect(page.locator(".column-save-status")).toContainText(/сохранён|загружены|Сохранено/);await expect(page.locator("main").getByRole("alert")).toHaveCount(0);}
async function settings(page){await page.getByRole("button",{name:"Настроить колонки",exact:true}).click();await expect(page.getByRole("dialog")).toBeVisible();}
async function close(page){await page.getByLabel("Закрыть настройку колонок").click();}
async function bundle(page,scope="account"){const r=await page.request.get("/api/preferences/columns/"+scope);expect(r.ok()).toBeTruthy();return r.json();}
test.beforeEach(async({page})=>{
 await page.goto("/");
 // Only the browser's test table response is synthetic; real private preferences use PostgreSQL.
 await page.route("**/api/stats/table?**",async route=>{
 const url=new URL(route.request().url());const level=url.searchParams.get("level");
 const rows=[{id:"fixture-1",external_id:"test-1",name:"Длинное название рекламной кампании ".repeat(12),level,currency:"USD",timezone:"Europe/Rome",spend:"12",impressions:1000,clicks:10,leads:0,sales:null,ctr:"1",roi:null}];
 await route.fulfill({json:{rows,total:1,next_offset:null}});
 });
 await open(page);
});
test("labels, visibility/search, bounds, keyboard reorder, scope and refresh",async({page})=>{
 await expect(page.getByTestId("column-spend")).toContainText("Расходы");
 await expect(page.getByTestId("statistics-table")).not.toContainText("????");
 await settings(page);await expect(page.getByTestId("column-toggle-name")).toBeDisabled();
 await page.getByTestId("column-toggle-clicks").uncheck();await expect(page.getByTestId("column-clicks")).toHaveCount(0);
 await page.getByTestId("column-toggle-clicks").check();
 await page.getByLabel("Поиск метрик").fill("frequency");await page.getByTestId("column-toggle-frequency").check();await page.getByLabel("Поиск метрик").clear();
 await page.getByLabel("Ширина: spend",{exact:true}).fill("237");
 await page.getByLabel("Вверх: clicks",{exact:true}).click();await close(page);await saved(page);
 const before=(await bundle(page)).preference.config;
 expect(before.columns.find(c=>c.key==="spend").width).toBe(237);expect(before.columns[0].key).toBe("name");
 await page.reload();await open(page);expect((await bundle(page)).preference.config).toEqual(before);
 await page.getByRole("navigation",{name:"Уровень статистики"}).getByRole("button",{name:"Кампании",exact:true}).click();
 await expect(page.getByLabel("Набор колонок")).toBeEnabled();expect((await bundle(page,"campaign")).preference.config).not.toEqual(before);
 await page.getByRole("navigation",{name:"Уровень статистики"}).getByRole("button",{name:"Кабинеты",exact:true}).click();
 await expect(page.getByTestId("column-frequency")).toBeVisible();expect((await bundle(page)).preference.config).toEqual(before);
});
test("real pointer resize, shrink, double-click autofit, drag, sticky name and sort",async({page})=>{
 await page.getByLabel("Набор колонок").selectOption("system:basic");await saved(page);
 const handle=page.getByTestId("resize-name");await handle.scrollIntoViewIfNeeded();let b=await handle.boundingBox();expect(b).toBeTruthy();
 await page.mouse.move(b.x+b.width/2,b.y+b.height/2);await page.mouse.down();await page.mouse.move(b.x+120,b.y+b.height/2,{steps:10});await page.mouse.up();await saved(page);
 let c=(await bundle(page)).preference.config;const wide=c.columns[0].width;expect(wide).toBeGreaterThan(280);
 await handle.scrollIntoViewIfNeeded();b=await handle.boundingBox();await page.mouse.move(b.x+b.width/2,b.y+b.height/2);await page.mouse.down();await page.mouse.move(b.x-90,b.y+b.height/2,{steps:10});await page.mouse.up();await saved(page);
 expect((await bundle(page)).preference.config.columns[0].width).toBeLessThan(wide);
 await handle.dblclick();await saved(page);expect((await bundle(page)).preference.config.columns[0].width).toBe(720);
 // Put an early numeric column before its next sibling: native dragTo emits HTML drag/drop.
 const before=(await bundle(page)).preference.config.columns.map(c=>c.key);
 await page.getByTestId("drag-currency").dragTo(page.getByTestId("column-status"));
 await saved(page);const after=(await bundle(page)).preference.config.columns.map(c=>c.key);expect(after[0]).toBe("name");expect(after).not.toEqual(before);
 await page.getByTestId("column-spend").getByRole("button",{name:/^Расходы/}).click();await saved(page);
 expect((await bundle(page)).preference.config.sorting).toEqual({key:"spend",direction:"asc"});
 const wrap=page.locator(".customizable-table-wrap");await wrap.evaluate(el=>{el.scrollLeft=900;});expect(await wrap.evaluate(el=>el.scrollLeft)).toBeGreaterThan(0);
 expect(await page.getByTestId("column-name").evaluate(el=>getComputedStyle(el).position)).toBe("sticky");
 await page.getByTestId("column-name").locator(".metric-info").focus();await expect(page.getByTestId("column-name").getByRole("tooltip")).toBeVisible();
 await page.setViewportSize({width:390,height:844});await expect(page.getByRole("button",{name:"Настроить колонки",exact:true})).toBeVisible();
 await page.setViewportSize({width:1440,height:900});
});
test("multiple private presets, rename/duplicate/default/delete, login persistence and isolation",async({page,browser,accounts,browserAudit,signedIn})=>{
 await settings(page);await page.getByLabel("Название нового набора").fill("UI-1 первый");await page.getByRole("button",{name:"Создать набор",exact:true}).click();await saved(page);
 await page.getByLabel("Ширина: name",{exact:true}).fill("333");await page.getByRole("dialog").getByRole("button",{name:"Сохранить набор",exact:true}).click();await saved(page);
 page.once("dialog",d=>d.accept("UI-1 переименован"));await page.getByRole("button",{name:"Переименовать",exact:true}).click();await saved(page);
 await page.getByRole("button",{name:"Сделать основным",exact:true}).click();await saved(page);
 const first=(await bundle(page)).preference.active_id;
 page.once("dialog",d=>d.accept("UI-1 копия"));await page.getByRole("button",{name:"Дублировать",exact:true}).click();await saved(page);
 let b=await bundle(page);expect(b.presets.filter(p=>!p.system).length).toBeGreaterThanOrEqual(2);
 const copyId=b.preference.active_id;await close(page);
 await page.getByLabel("\u041d\u0430\u0431\u043e\u0440 \u043a\u043e\u043b\u043e\u043d\u043e\u043a").selectOption(first);await saved(page);expect((await bundle(page)).preference.active_id).toBe(first);
 await page.getByLabel("\u041d\u0430\u0431\u043e\u0440 \u043a\u043e\u043b\u043e\u043d\u043e\u043a").selectOption(copyId);await saved(page);expect((await bundle(page)).preference.active_id).toBe(copyId);await settings(page);
 page.once("dialog",d=>d.accept());await page.getByRole("button",{name:"Удалить набор",exact:true}).click();await saved(page);await close(page);
 const expectedView=(await bundle(page)).preference.config;expect((await bundle(page)).preference.active_id).toBe(first);
 await page.getByRole("button",{name:"Выйти",exact:true}).click();await expect(page).toHaveURL(/\/login$/);await login(page,accounts[0]);signedIn.state=await page.context().storageState();await open(page);
 b=await bundle(page);expect(b.preference.default_id).toBe(first);expect(b.preference.config.columns[0].width).toBe(333);expect(b.preference.config).toEqual(expectedView);
 expect(await page.locator("thead th[data-column]").evaluateAll(nodes=>nodes.map(n=>n.dataset.column))).toEqual(expectedView.columns.map(c=>c.key));
 await expect(page.getByTestId("column-"+expectedView.sorting.key)).toHaveAttribute("aria-sort",expectedView.sorting.direction==="asc"?"ascending":"descending");
 const context=await browser.newContext();const other=await context.newPage();watchPage(other,browserAudit);try{
 await login(other,accounts[1]);const privateB=await bundle(other);expect(privateB.presets.some(p=>p.id===first)).toBeFalsy();
 const token=(await (await other.request.get("/api/auth/csrf")).json()).csrf_token;
 const response=await other.request.delete("/api/preferences/columns/presets/"+first+"?version=1&preference_version="+privateB.preference.version,{headers:{"Origin":"http://127.0.0.1:3000","X-CSRF-Token":token}});
 expect(response.status()).toBe(404);
 }finally{await context.close();}
});
test("all six scopes expose independent column manager and system templates",async({page})=>{
 for(const label of ["Кабинеты","Кампании","Группы","Объявления","Креативы"]){await page.getByRole("navigation",{name:"Уровень статистики"}).getByRole("button",{name:label,exact:true}).click();await expect(page.getByLabel("Набор колонок")).toBeEnabled();}
 for(const section of ["Креативы","Трекер"]){await open(page,section);await settings(page);await expect(page.getByTestId("column-toggle-name")).toBeDisabled();await close(page);}
});
test("long Russian names, independent column widths and narrow viewport layout",async({page})=>{
 await expect(page.locator("tbody .rowlink").first()).toContainText("Длинное название рекламной кампании");
 await expect(page.locator("tbody .rowlink").first()).toHaveAttribute("title",/Длинное название рекламной кампании/);
 for(const width of [1440,768,390]){
  await page.setViewportSize({width,height:900});
  await expect(page.getByTestId("statistics-table")).toBeVisible();
  const metrics=await page.evaluate(()=>{
   const wrap=document.querySelector(".customizable-table-wrap"),name=document.querySelector("tbody td.identity-column");
   const rect=wrap.getBoundingClientRect(),nr=name.getBoundingClientRect();
   return {viewport:innerWidth,documentWidth:document.documentElement.scrollWidth,wrapLeft:rect.left,wrapRight:rect.right,cellWidth:nr.width};
  });
  expect(metrics.documentWidth).toBeLessThanOrEqual(width+1);
  expect(metrics.wrapLeft).toBeGreaterThanOrEqual(0);expect(metrics.wrapRight).toBeLessThanOrEqual(width);
  const wrap=page.locator(".customizable-table-wrap");
  await wrap.evaluate(el=>{el.scrollLeft=1000;});
  const sticky=await page.locator("tbody td.identity-column").first().boundingBox(),wr=await wrap.boundingBox();
  expect(Math.abs(sticky.x-wr.x)).toBeLessThanOrEqual(2);
  await settings(page);
  const dialog=await page.getByRole("dialog").boundingBox();expect(dialog.x).toBeGreaterThanOrEqual(0);expect(dialog.x+dialog.width).toBeLessThanOrEqual(width);
  await close(page);
 }
 await page.setViewportSize({width:1440,height:900});
 await page.locator(".customizable-table-wrap").evaluate(el=>{el.scrollLeft=0;});
 const before=(await bundle(page)).preference.config.columns;
 const resize=page.getByTestId("resize-spend");await resize.scrollIntoViewIfNeeded();const b=await resize.boundingBox();
 await page.mouse.move(b.x+b.width/2,b.y+b.height/2);await page.mouse.down();await page.mouse.move(b.x+75,b.y+b.height/2,{steps:10});await page.mouse.up();await saved(page);
 const grown=(await bundle(page)).preference.config.columns.find(c=>c.key==="spend").width;
 expect(grown).toBeGreaterThan(before.find(c=>c.key==="spend").width);
 await resize.focus();await page.keyboard.press("ArrowRight");await saved(page);
 const after=(await bundle(page)).preference.config.columns;
 expect(after.filter(c=>c.key!=="spend")).toEqual(before.filter(c=>c.key!=="spend"));
});

test("rapid scope navigation flushes unsaved width before restoring the view",async({page})=>{
 await settings(page);await page.getByLabel("Ширина: name",{exact:true}).fill("356");await close(page);
 const nav=page.getByRole("navigation",{name:"Уровень статистики"});
 await nav.getByRole("button",{name:"Кампании",exact:true}).click();
 await nav.getByRole("button",{name:"Кабинеты",exact:true}).click();
 await expect(page.getByLabel("Набор колонок")).toBeEnabled();
 await expect.poll(async()=>((await bundle(page)).preference.config.columns[0].width)).toBe(356);
 await expect(page.getByTestId("resize-name")).toHaveAttribute("aria-valuenow","356");
});