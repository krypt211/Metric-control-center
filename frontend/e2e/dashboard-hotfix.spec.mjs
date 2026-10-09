import {test,expect} from '@playwright/test';
import {execFileSync} from 'node:child_process';
import {readFileSync} from 'node:fs';
import path from 'node:path';
import {randomUUID} from 'node:crypto';
const root=path.resolve(import.meta.dirname,'../..');
const docker=process.env.DOCKER_EXE??path.join(process.env.LOCALAPPDATA,'Programs/DockerDesktop/resources/bin/docker.exe');
function fixture(mode,nonce){return JSON.parse(execFileSync(docker,['compose','--project-directory',root,'--env-file',path.join(root,'.env'),'-f',path.join(root,'docker-compose.yml'),'-p','metric-control-center','exec','-T','-e','UI_FIXTURE_MODE='+mode,'-e','UI_FIXTURE_NONCE='+nonce,'backend','python','-c','import sys;exec(sys.stdin.read())'],{input:readFileSync(new URL('./provider_accounts.py',import.meta.url),'utf8'),encoding:'utf8',windowsHide:true}));}
test('real PostgreSQL hotfix: periods, catalog, hierarchy, proxy, provenance and readable connections',async({page},testInfo)=>{
 test.setTimeout(120000);
 const nonce=randomUUID().replaceAll('-','');const errors=[],advertising=[],periods=[];let browserTimezone='';
 page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});page.on('pageerror',e=>errors.push(e.message));
 page.on('request',r=>{const u=new URL(r.url());if(!['GET','HEAD','OPTIONS'].includes(r.method())&&/^\/api\/(actions|ai|automation)(\/|$)/.test(u.pathname))advertising.push(u.pathname);});
 try{
  const [user]=fixture('create',nonce);
  await page.goto('/login');await page.getByLabel('Логин или email').fill(user.login);await page.getByLabel('Пароль',{exact:true}).fill(user.password);await page.getByRole('button',{name:'Войти',exact:true}).click();await expect(page).toHaveURL(/\/$/);
  await expect(page.getByTestId('source-summary')).toHaveCount(1);
  browserTimezone=await page.evaluate(()=>Intl.DateTimeFormat().resolvedOptions().timeZone);
  await page.getByRole('navigation',{name:'Раздел'}).getByRole('button',{name:'Статистика',exact:true}).click();
  await expect(page.getByLabel('Набор колонок')).toBeEnabled();
  const catalogResponse=await page.request.get('/api/stats/filters');expect(catalogResponse.ok()).toBeTruthy();
  const catalog=(await catalogResponse.json()).options.account;
  const expectedIds=catalog.map(a=>a.id).sort();
  expect(expectedIds.length).toBeGreaterThan(0);expect(new Set(expectedIds).size).toBe(expectedIds.length);
  const period=page.getByRole('combobox',{name:/^Период/});
  for(const value of ['1','yesterday','3','7','14','30']){
   const today=new Intl.DateTimeFormat('en-CA',{timeZone:'Europe/Moscow',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
   const shift=n=>new Date(Date.parse(today+'T12:00:00Z')-n*86400000).toISOString().slice(0,10);
   const expectedStart=value==='yesterday'?shift(1):shift(Number(value)-1),expectedEnd=value==='yesterday'?shift(1):today;
   const response=page.waitForResponse(r=>{const u=new URL(r.url());return u.pathname==='/api/stats/table'&&u.searchParams.get('start')===expectedStart&&u.searchParams.get('end')===expectedEnd&&r.status()===200;});
   await period.selectOption(value);
   if(value==='1')await page.getByRole('button',{name:'Обновить',exact:true}).click();
   const r=await response;const body=await r.json();const u=new URL(r.url());
   expect(body.rows.map(x=>x.id).sort()).toEqual(expectedIds);expect(new Set(body.rows.map(x=>x.id)).size).toBe(expectedIds.length);
   periods.push({preset:value,start:u.searchParams.get('start'),end:u.searchParams.get('end'),accounts:body.total,spend:body.rows.map(x=>({id:x.id,spend:x.spend,has_facts:x.has_facts}))});
   await expect(page.getByTestId('source-summary')).toHaveCount(1);
  }
  const laDay=new Intl.DateTimeFormat('en-CA',{timeZone:'America/Los_Angeles',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
  const future=new Date(Date.parse(laDay+'T12:00:00Z')+86400000).toISOString().slice(0,10);
  await period.selectOption('custom');await page.locator('input[type=date]').nth(0).fill(future);
  const custom=page.waitForResponse(r=>r.url().includes('/api/stats/table?')&&new URL(r.url()).searchParams.get('end')===future&&r.status()===200);
  await page.locator('input[type=date]').nth(1).fill(future);await page.getByRole('button',{name:'Обновить',exact:true}).click();await custom;
  const params=`start=${future}&end=${future}&level=account`;
  const backend=await page.request.get('http://127.0.0.1:8000/api/stats/table?'+params);const proxy=await page.request.get('/api/stats/table?'+params);expect(backend.ok()).toBeTruthy();expect(proxy.ok()).toBeTruthy();
  const b=await backend.json(),p=await proxy.json();expect(p.rows.map(x=>({id:x.id,spend:x.spend}))).toEqual(b.rows.map(x=>({id:x.id,spend:x.spend})));expect(p.rows.map(x=>x.id).sort()).toEqual(expectedIds);expect(p.total).toBe(expectedIds.length);
  await expect(page.getByTestId('statistics-table')).toContainText('America/Los_Angeles');
  await expect(page.getByTestId('statistics-table')).toContainText('Выбранная дата ещё не началась');
  await page.locator('input[type=date]').nth(0).fill('2026-10-08');await page.locator('input[type=date]').nth(1).fill('2026-10-08');
  for(const [label,level] of [['Кампании','campaign'],['Группы','adset'],['Объявления','ad']]){
   const response=page.waitForResponse(r=>r.url().includes('/api/stats/table?')&&new URL(r.url()).searchParams.get('level')===level&&r.status()===200);
   await page.getByRole('navigation',{name:'Уровень статистики'}).getByRole('button',{name:label,exact:true}).click();expect((await (await response).json()).total).toBeGreaterThan(0);
  }
  await expect(page.getByLabel('Набор колонок')).toBeEnabled();
  await page.goto('/settings/connections');await page.getByText('Доступные возможности и API quota',{exact:true}).click();
  await expect(page.getByRole('columnheader',{name:'Возможность',exact:true})).toBeVisible();
  await expect(page.getByLabel('Квота MetricFlow')).toContainText('/ 800');
  await expect(page.getByLabel('Квота MetricFlow')).toContainText('/ 20000');
  await expect(page.getByLabel('Квота MetricFlow')).toContainText('Осталось по локальному лимиту:');
  const technical=page.locator('details').filter({has:page.getByText('Технические подробности',{exact:true})});expect(await technical.getAttribute('open')).toBeNull();
  expect(await page.locator('pre:visible').count()).toBe(0);
  expect((await page.locator('body').innerText()).includes('????')).toBeFalsy();
  for(const width of [1440,768,390]){await page.setViewportSize({width,height:850});await expect(page.getByRole('heading',{name:'Настройки · API и подключения',exact:true})).toBeVisible();}
  await testInfo.attach('hotfix-browser-audit',{body:Buffer.from(JSON.stringify({errors,advertising,periods,browserTimezone,backend_proxy:'PASS'})),contentType:'application/json'});
  expect(errors).toEqual([]);expect(advertising).toEqual([]);
 }finally{fixture('cleanup',nonce);}
});