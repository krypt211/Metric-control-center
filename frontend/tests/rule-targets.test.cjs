const {test}=require("node:test");
const assert=require("node:assert/strict");
const {matchesSearch,mergeTargets,targetKey,targetSummary}=require("../.test-build/lib/rule-targets");
test("Unicode AND search is insensitive to case and word order",()=>{
 assert(matchesSearch("Italy Adenofrin Кампания 01","12345","aden italy"));
 assert(matchesSearch("Кампания Тест","12345","камп ТЕСТ"));
 assert(matchesSearch("Italy Adenofrin","12345","123"));
 assert(!matchesSearch("Italy","12345","italy absent"));
});
test("Mixed targets preserve selection across search/pages and deterministic identity",()=>{
 const t={scope_type:"CAMPAIGN",scope_id:"c",account_id:"a",provider:"metricflow"};
 const ad={...t,scope_type:"AD",scope_id:"d"};
 const result=mergeTargets([t],[t,ad]);
 assert.equal(result.length,2);assert.notEqual(targetKey(t),targetKey({...t,provider:"meta"}));
 assert.match(targetSummary(result),/1 кампании.*1 объявления/);
});
