import {test,expect} from "@playwright/test";
import {readFileSync} from "node:fs";
import {execFileSync} from "node:child_process";
import path from "node:path";
const root=path.resolve("..");
let fixture;
test.skip(process.env.INTEGRATION_ACCEPTANCE !== "true", "Requires isolated restored database and mock credential service");
const docker=path.join(process.env.LOCALAPPDATA,"Programs/DockerDesktop/resources/bin/docker.exe");
function inspect(){
 const script=readFileSync(path.join(root,"frontend/e2e/integration_accounts.py"),"utf8");
 return JSON.parse(execFileSync(docker,["compose","-f",path.join(root,".tools/integrations-acceptance.yml"),"exec","-T","backend","python","-","inspect"],{input:script,encoding:"utf8"}));
}
async function login(page,role="admin"){
 await page.context().addCookies([fixture.users.find(u=>u.role===role).cookie]);
 await page.goto("/settings/connections");
 await expect(page.getByRole("heading",{name:/WRITE/,level:3})).toBeVisible();
}
const card=page=>page.getByRole("region",{name:"Ключ управления рекламой WRITE",exact:true});
let before;
test.describe.configure({mode:"serial"});
test.beforeAll(()=>{fixture=JSON.parse(readFileSync(path.join(root,".tools/integrations-fixture-state.json"),"utf8"));before=inspect();});
test("independent encrypted WRITE save, scope check, replace, refresh and delete with real private service",async({page})=>{
 const errors=[],advertising=[];page.on("pageerror",e=>errors.push(e.message));page.on("console",m=>{if(m.type()==="error")errors.push(m.text());});
 page.on("request",r=>{if(!["GET","HEAD","OPTIONS"].includes(r.method())&&/^\/api\/(actions|automation|ai)(\/|$)/.test(new URL(r.url()).pathname))advertising.push(r.url());});
 page.on("dialog",d=>d.accept());await login(page);
 const c=card(page);await expect(c).toContainText("Не настроен");
 const token="mfk_fixture-write-ui-synthetic-123";
 await c.getByLabel("MetricFlow WRITE key",{exact:true}).fill(token);
 await c.getByRole("button",{name:"Сохранить ключ",exact:true}).click();
 await expect(c).toContainText("Сохранён, не проверен");await expect(c.getByLabel("MetricFlow WRITE key",{exact:true})).toHaveValue("");
 expect(inspect().encrypted).toBeTruthy();await page.reload();await expect(card(page)).toContainText("Сохранён, не проверен");
 await expect(page.locator("body")).not.toContainText(token);
 await card(page).getByRole("button",{name:"Проверить подключение WRITE",exact:true}).click();
 await expect(card(page)).toContainText("WRITE scope подтверждён");await expect(card(page)).toContainText("BLOCKED");
 await card(page).getByLabel("MetricFlow WRITE key",{exact:true}).fill("mfk_fixture-read-only-ui-456");
 await card(page).getByRole("button",{name:"Заменить ключ",exact:true}).click();await expect(card(page)).toContainText("Сохранён, не проверен");
 await card(page).getByRole("button",{name:"Проверить подключение WRITE",exact:true}).click();await expect(card(page)).toContainText("У ключа отсутствует campaigns:write");
 await card(page).getByRole("button",{name:"Удалить локальный ключ",exact:true}).click();await expect(card(page)).toContainText("Не настроен");
 const after=inspect();expect(after.read_encrypted).toBe(before.read_encrypted);expect(after.read_revision).toBe(before.read_revision);expect(after.action_executions).toBe(before.action_executions);
 await page.goto("/settings/manual-control");await expect(page.locator("body")).toContainText("LIVE: BLOCKED");
 expect(errors).toEqual([]);expect(advertising).toEqual([]);
});
test("Meta measured mock usage, durable cooldown, request log and network-free estimate",async({page})=>{
 await login(page);await page.getByText("Техническая диагностика Meta (ADMIN)",{exact:true}).click();const meta=page.getByRole("region",{name:"Использование Meta API",exact:true});
 await expect(meta).toContainText("Meta API не подключён");await expect(meta).toContainText("99%");await expect(meta).toContainText("80004");
 const response=await page.request.get("/api/admin/providers/meta/usage");const usage=await response.json();expect(usage.day).toBe(2);expect(usage.incidents).toBe(1);expect(usage.cooldown_until).toBeTruthy();
 await meta.getByRole("button",{name:"Журнал запросов",exact:true}).click();await expect(meta.locator("tbody tr")).toHaveCount(2);
 await meta.getByRole("button",{name:"Прогноз Meta sync",exact:true}).click();await meta.getByLabel("Аккаунтов для прогноза").selectOption("50");await meta.getByLabel("Период прогноза").selectOption("30");await meta.getByRole("button",{name:"Рассчитать без Meta API",exact:true}).click();await expect(meta).toContainText("Estimated:");
 expect((await(await page.request.get("/api/admin/providers/meta/usage")).json()).day).toBe(2);
});
test("VIEWER and OPERATOR cannot provision or reveal the credential",async({page})=>{
 for(const role of ["viewer","operator"]){
  await page.context().clearCookies();await page.context().addCookies([fixture.users.find(u=>u.role===role).cookie]);await page.goto("/");
  const adminRead=await page.request.get("/api/admin/providers/metricflow/write-credentials");expect(adminRead.status()).toBe(403);
  const settings=await(await page.request.get("/api/manual-control/settings")).json();const state=settings.providers.find(p=>p.provider==="metricflow").write_connection;expect(state.token).toBeUndefined();expect(state.encrypted).toBeUndefined();
  const csrf=await(await page.request.get("/api/auth/csrf")).json();const denied=await page.request.post("/api/admin/providers/metricflow/write-credentials/save",{headers:{Origin:"http://127.0.0.1:3001","X-CSRF-Token":csrf.csrf_token},data:{revision:state.revision,token:"mfk_fixture-not-permitted"}});expect(denied.status()).toBe(403);
 }
});

test("Meta queue monitoring and confirmed pending cancellation send no HTTP",async({page})=>{
 await login(page);await page.getByText("Техническая диагностика Meta (ADMIN)",{exact:true}).click();const q=page.getByRole("region",{name:"Очередь Meta READ",exact:true});
 await expect(q).toContainText("JOB_TTL_EXPIRED");await expect(q).toContainText("META_RATE_LIMIT");
 const before=await(await page.request.get("/api/admin/providers/meta/usage")).json();expect(before.queue.pending).toBe(1);
 await q.getByRole("button",{name:"Отменить READ-задачу",exact:true}).click();await expect(q.getByRole("button",{name:"Отменить READ-задачу",exact:true})).toHaveCount(0);
 const after=await(await page.request.get("/api/admin/providers/meta/usage")).json();expect(after.queue.pending).toBe(0);expect(after.queue.cancelled).toBe(2);expect(after.day).toBe(before.day);
});
for(const width of [1440,1024,768,390])test("responsive connections "+width,async({page})=>{
 await page.setViewportSize({width,height:900});await login(page);await expect(card(page)).toContainText("BLOCKED");
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBeTruthy();await page.screenshot({path:"test-results/integrations-"+width+".png",fullPage:true});
});

test("retired pilot has no active UI or automatic Meta request",async({page})=>{
 await login(page);
 const prior=inspect();
 await expect(page.getByRole("region",{name:"Тестовое READ-подключение",exact:true})).toHaveCount(0);
 await expect(page.locator("body")).toContainText("30 минут");
 await page.getByText("Техническая диагностика Meta (ADMIN)",{exact:true}).click();
 await expect(page.getByRole("region",{name:"Использование Meta API",exact:true})).toBeVisible();
 expect(inspect().meta_attempts).toBe(prior.meta_attempts);
 expect(inspect().action_executions).toBe(prior.action_executions);
});
