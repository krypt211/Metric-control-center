const {test}=require("node:test");
const assert=require("node:assert/strict");
const React=require("react");
const {renderToStaticMarkup}=require("react-dom/server");
const m=require("../.test-build/lib/column-model.js");
const {metricRegistry,scopeNames,labelFor}=require("../.test-build/lib/metric-registry.js");
const Table=require("../.test-build/components/StatisticsTable.js").default;
const clone=x=>JSON.parse(JSON.stringify(x));
const base=()=>clone(m.systemPresets("ad")[0].config);
test("six immutable templates for each scope, required identity first",()=>{
 for(const scope of Object.keys(scopeNames)){const presets=m.systemPresets(scope);assert.equal(presets.length,6);
 for(const p of presets){assert.equal(p.system,true);assert.equal(p.config.columns[0].key,"name");
 assert.equal(new Set(p.config.columns.map(c=>c.key)).size,p.config.columns.length);
 for(const c of p.config.columns){assert.ok(metricRegistry[c.key].scopes.includes(scope));assert.ok(c.width>=metricRegistry[c.key].minWidth);}}
 }});
test("mandatory name cannot be hidden or dragged",()=>{const c=base();assert.equal(m.setVisible(c,"name",false),c);assert.equal(m.moveColumn(c,"name","spend"),c);});
test("hide/show restores saved width without affecting siblings",()=>{const c=m.resizeColumn(base(),"spend",237);
 const hidden=m.setVisible(c,"spend",false);assert.ok(!hidden.columns.some(x=>x.key==="spend"));assert.equal(hidden.widths.spend,237);
 assert.equal(m.setVisible(hidden,"spend",true).columns.at(-1).width,237);assert.deepEqual(c.columns.filter(x=>x.key!=="spend"),hidden.columns);});
test("new hidden metric can be added exactly once",()=>{const c=m.setVisible(base(),"frequency",true);assert.equal(m.setVisible(c,"frequency",true),c);assert.ok(c.columns.some(x=>x.key==="frequency"));});
test("drag reorders every sibling consistently, name stays first",()=>{const c=base(),source=c.columns.at(-1).key;
 const changed=m.moveColumn(c,source,c.columns[1].key);assert.equal(changed.columns[0].key,"name");assert.equal(changed.columns[1].key,source);
 assert.deepEqual(new Set(changed.columns.map(x=>x.key)),new Set(c.columns.map(x=>x.key)));assert.notDeepEqual(changed.columns,c.columns);});
test("moving to identity inserts after identity",()=>{const c=base(),key=c.columns.at(-1).key;assert.equal(m.moveColumn(c,key,"name").columns[1].key,key);});
test("resize clamps minimum, maximum and rounds; only one column changes",()=>{
 for(const [key,min,max] of [["spend",80,600],["name",180,720]]){let c=base();
 assert.equal(m.resizeColumn(c,key,-100).columns.find(x=>x.key===key).width,min);
 assert.equal(m.resizeColumn(c,key,9999).columns.find(x=>x.key===key).width,max);
 assert.equal(m.resizeColumn(c,key,200.4).columns.find(x=>x.key===key).width,200);
 assert.deepEqual(m.resizeColumn(c,key,210).columns.filter(x=>x.key!==key),c.columns.filter(x=>x.key!==key));}});
test("reset widths keeps visibility, order and sort",()=>{const c=m.moveColumn(m.resizeColumn(base(),"name",500),"roi","spend");const reset=m.resetWidths(c);
 assert.deepEqual(reset.columns.map(x=>x.key),c.columns.map(x=>x.key));assert.deepEqual(reset.sorting,c.sorting);
 for(const col of reset.columns)assert.equal(col.width,metricRegistry[col.key].defaultWidth);assert.deepEqual(reset.widths,{});});
test("registry evolution never injects new columns or resets saved widths",()=>{const c=m.resizeColumn(base(),"name",499);assert.deepEqual(m.normalizeColumns(c,"ad"),c);
 const retired=clone(c);retired.columns.push({key:"retired_event",width:160});assert.deepEqual(m.normalizeColumns(retired,"ad"),c);});
test("null and missing values stay unknown, zero remains a number",()=>{for(const v of [null,undefined,"",NaN,Infinity])assert.equal(m.formatMetric(v,"spend","USD"),"—");
 assert.ok(m.formatMetric(0,"spend","USD").includes("0"));assert.equal(m.formatMetric(null,"clicks",null),"—");});
test("percent and counts retain registry semantics",()=>{assert.equal(m.formatMetric("12.34","ctr",null),"12,34%");
 assert.equal(m.formatMetric(2,"leads",null),"2");assert.equal(m.formatMetric("ACTIVE","status",null),"ACTIVE");});
test("all labels and descriptions are real UTF-8; keys stay provider keys",()=>{for(const [key,spec] of Object.entries(metricRegistry)){
 assert.equal(key,spec.key);assert.ok(!spec.label.includes("??"));assert.ok(!spec.description.includes("�"));assert.ok(spec.description.length>5);}
 assert.equal(metricRegistry.reach.label,"Охват");assert.ok(labelFor(metricRegistry.clicks,"tracker").includes("трекера"));});
test("rendered headers and cells match keys, fixed widths, NULL marker and long name",()=>{const c=base();const html=renderToStaticMarkup(React.createElement(Table,{scope:"ad",config:c,rows:[{id:"fixture",name:"Очень длинное название кампании ".repeat(12),spend:null,currency:"USD",timezone:"Europe/Rome"}],change:()=>{},commit:()=>{}}));
 assert.ok(html.includes("Расходы"));assert.ok(!html.includes("????"));assert.ok(html.includes("—"));
 assert.ok(html.includes('data-column="spend"'));assert.ok(html.includes('class="identity-column'));assert.ok(html.includes("width:280px"));
 assert.ok(html.includes("Очень длинное название кампании"));assert.ok(html.includes('role="separator"'));});