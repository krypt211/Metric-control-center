import {test,expect} from "@playwright/test";
import {execFileSync} from "node:child_process";
import {readFileSync} from "node:fs";
import path from "node:path";
import {randomUUID} from "node:crypto";
const root=path.resolve(import.meta.dirname,"../..");
const docker=process.env.DOCKER_EXE??path.join(process.env.LOCALAPPDATA,"Programs/DockerDesktop/resources/bin/docker.exe");
function fixture(mode,nonce){
 const args=["compose","--project-directory",root,"--env-file",path.join(root,".env"),"-f",path.join(root,"docker-compose.yml"),"-p","metric-control-center","exec","-T","-e","UI_FIXTURE_MODE="+mode,"-e","UI_FIXTURE_NONCE="+nonce,"backend","python","-c","import sys;exec(sys.stdin.read())"];
 return JSON.parse(execFileSync(docker,args,{input:readFileSync(new URL("./provider_accounts.py",import.meta.url),"utf8"),encoding:"utf8",windowsHide:true}));
}
test("ADMIN connections READ smoke: cards, diagnostics, masked inputs, responsive and no advertising writes",async({page},testInfo)=>{
 test.setTimeout(120000);
 const nonce=randomUUID().replaceAll("-","");const errors=[],advertising=[],providerMutations=[];
 page.on("console",m=>{if(m.type()==="error")errors.push(m.text());});page.on("pageerror",e=>errors.push(e.message));
 page.on("request",r=>{const p=new URL(r.url()).pathname;if(!["GET","HEAD","OPTIONS"].includes(r.method())){if(/^\/api\/(actions|ai|automation)(\/|$)/.test(p))advertising.push(p);if(p.startsWith("/api/admin/providers"))providerMutations.push(p);}});
 try{
  const [user,viewer]=fixture("create",nonce);
  await page.goto("/login");await page.getByLabel("Логин или email").fill(user.login);await page.getByLabel("Пароль",{exact:true}).fill(user.password);await page.getByRole("button",{name:"Войти",exact:true}).click();await expect(page).toHaveURL(/\/$/);
  await page.getByRole("link",{name:"API и подключения",exact:true}).click();await expect(page.getByRole("heading",{name:"Настройки · API и подключения"})).toBeVisible();
  await expect(page.getByRole("heading",{name:"Meta Marketing API",exact:true})).toBeVisible();await expect(page.getByRole("heading",{name:"MetricFlow API",exact:true})).toBeVisible();
  const mf=page.locator(".provider-cards > section").filter({has:page.getByRole("heading",{name:"MetricFlow API",exact:true})});
  await mf.getByRole("button",{name:"Проверить соединение",exact:true}).click();
  await expect.poll(async()=>{
   const r=await page.request.get("/api/admin/providers");expect(r.ok()).toBeTruthy();
   return (await r.json()).jobs.find(j=>j.provider==="metricflow"&&j.kind==="health")?.status;
  },{timeout:70000}).toBe("succeeded");
  await page.getByRole("button",{name:"Обновить подключения",exact:true}).click();
  const meta=page.locator(".provider-cards > section").filter({has:page.getByRole("heading",{name:"Meta Marketing API",exact:true})});
  await meta.locator("summary").filter({hasText:"Подключить или обновить credentials"}).click();
  await expect(meta.getByLabel("Meta access token")).toHaveAttribute("type","password");await expect(meta.getByLabel("Meta App Secret")).toHaveAttribute("type","password");
  await expect(meta.getByLabel("Meta access token")).toHaveValue("");await expect(meta.getByLabel("Meta App Secret")).toHaveValue("");
  await expect(page.getByRole("combobox",{name:"Основной источник",exact:true})).toHaveValue("metricflow");
  await page.getByRole("button",{name:"Сохранить источники",exact:true}).click();
  await expect(page.getByRole("status")).toContainText("Настройки сохранены");
  const scope=page.getByRole("combobox",{name:"Настройка для",exact:true});const account=await scope.locator("option").nth(1).getAttribute("value");
  expect(account).toBeTruthy();await scope.selectOption(account);
  await page.getByRole("button",{name:"Сохранить источники",exact:true}).click();
  await expect(page.getByRole("button",{name:"Использовать общие настройки",exact:true})).toBeVisible();
  await page.reload();await expect(page.getByRole("heading",{name:"Meta Marketing API",exact:true})).toBeVisible();
  await page.getByRole("combobox",{name:"Настройка для",exact:true}).selectOption(account);
  await page.getByRole("button",{name:"Использовать общие настройки",exact:true}).click();
  await expect(page.getByRole("button",{name:"Использовать общие настройки",exact:true})).toHaveCount(0);
  const viewContext=await page.context().browser().newContext({baseURL:process.env.UI_BASE_URL??"http://127.0.0.1:3000"});
  try{
   const v=await viewContext.newPage();v.on("console",m=>{if(m.type()==="error")errors.push(m.text());});v.on("pageerror",e=>errors.push(e.message));
   await v.goto("/login");await v.getByLabel("Логин или email").fill(viewer.login);await v.getByLabel("Пароль",{exact:true}).fill(viewer.password);await v.getByRole("button",{name:"Войти",exact:true}).click();await expect(v).toHaveURL(/\/$/);
   await expect(v.getByRole("link",{name:"API и подключения",exact:true})).toHaveCount(0);
   expect((await viewContext.request.get("/api/admin/providers")).status()).toBe(403);
  }finally{await viewContext.close();}
  await page.getByRole("button",{name:"Сравнить источники",exact:true}).click();await expect(page.getByText("Расхождения показаны без автоматической корректировки.",{exact:false})).toBeVisible();
  for(const width of [1440,768,390]){
   await page.setViewportSize({width,height:900});await expect(page.getByRole("heading",{name:"Настройки · API и подключения"})).toBeVisible();
   expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBeTruthy();
  }
  await testInfo.attach("provider-browser-audit",{body:Buffer.from(JSON.stringify({errors,advertising,providerMutations})),contentType:"application/json"});
  expect(errors).toEqual([]);expect(advertising).toEqual([]);expect(providerMutations).toHaveLength(4);expect(providerMutations.slice(0,3)).toEqual(["/api/admin/providers/metricflow/check","/api/admin/providers/routing","/api/admin/providers/routing"]);
 }finally{fixture("cleanup",nonce);}
});
