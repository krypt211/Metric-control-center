const {test}=require('node:test');
const assert=require('node:assert/strict');
const React=require('react');
const {renderToStaticMarkup}=require('react-dom/server');
const {dateRange}=require('../.test-build/lib/reporting-period.js');
const Source=require('../.test-build/components/SourceSummary.js').default;
const {QuotaPanel,capabilityStatus}=require('../.test-build/components/ProviderCapabilities.js');
const Table=require('../.test-build/components/StatisticsTable.js').default;
const {systemPresets}=require('../.test-build/lib/column-model.js');
test('reporting dates follow midnight, presets and inclusive boundaries',()=>{
 const now=new Date('2026-10-09T00:30:00Z');
 assert.deepEqual(dateRange('1',now),['2026-10-09','2026-10-09']);
 assert.deepEqual(dateRange('1',now,'America/Los_Angeles'),['2026-10-08','2026-10-08']);
 assert.deepEqual(dateRange('yesterday',now),['2026-10-08','2026-10-08']);
 for(const n of [3,7,14,30]){const [a,b]=dateRange(String(n),now);assert.equal((Date.parse(b)-Date.parse(a))/86400000+1,n);}
 assert.deepEqual(dateRange('1',new Date('2026-10-08T20:59:00Z')),['2026-10-08','2026-10-08']);
});
test('three accounts share one source indicator with localized detailed coverage',()=>{
 const source={provider:'metricflow',updated_at:'2026-10-09T00:30:00Z',mode:'primary',stale:false,connection:'healthy',coverage:'no_data',sync_status:'succeeded'};
 const html=renderToStaticMarkup(React.createElement(Source,{sources:[1,2,3].map(n=>({...source,canonical_id:String(n)}))}));
 assert.equal((html.match(/data-testid="source-summary"/g)||[]).length,1);
 assert.ok(html.includes('Подключён')&&html.includes('данные ещё не поступили'));
 assert.ok(!html.includes('· primary'));
});
test('quota numbers, unknown provider usage and disabled writes are honest',()=>{
 const c={provider:'metricflow',enabled:true,status:'healthy',capabilities:{read:{get_accounts:'verified'}},local_quota:{used:17,limit:800,blocked_until:null},provider_quota:{used:17,limit:20000}};
 const html=renderToStaticMarkup(React.createElement(QuotaPanel,{connection:c}));
 assert.ok(html.includes('17 / 800')&&html.includes('783')&&html.includes('17 / 20000'));
 assert.ok(renderToStaticMarkup(React.createElement(QuotaPanel,{connection:{...c,provider_quota:undefined}})).includes('Неизвестно'));
 assert.equal(capabilityStatus(c,'set_budget'),'Отключено');
 assert.equal(capabilityStatus(c,'get_accounts'),'Доступно и проверено');
 assert.equal(capabilityStatus({...c,enabled:false},'get_accounts'),'Нет подключения');
});
test('catalog row renders null metrics as dash and explains not-started date',()=>{
 const row={id:'one',name:'Кабинет',external_id:'act_1',currency:'USD',timezone:'America/Los_Angeles',status:'ACTIVE',source_provider:'metricflow',has_facts:false,data_status:'not_started',spend:null};
 const html=renderToStaticMarkup(React.createElement(Table,{scope:'account',rows:[row],config:systemPresets('account')[0].config,change:()=>{},commit:()=>{}}));
 assert.ok(html.includes('дата ещё не началась')&&html.includes('act_1')&&html.includes('Активен')&&html.includes('MetricFlow'));
 assert.ok(html.includes('—'));
});