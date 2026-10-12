export type Target = {
  scope_type: "ACCOUNT" | "CAMPAIGN" | "ADSET" | "AD";
  scope_id: string; account_id: string; provider: "metricflow" | "meta";
  name?: string; external_id?: string; account_name?: string;
  campaign_id?: string | null; adset_id?: string | null;
  effective_start?: string | null; effective_end?: string | null;
};
export type CatalogObject = Target & {id: string; hierarchy_verified: boolean};
export const targetTypes = {ACCOUNT:"кабинеты",CAMPAIGN:"кампании",ADSET:"группы",AD:"объявления"};
export function targetKey(t: Target) {return [t.provider,t.account_id,t.scope_type,t.scope_id].join(":");}
export function mergeTargets(before: Target[], additions: Target[]) {
  return Array.from(new Map([...before,...additions].map(t=>[targetKey(t),catalogTarget(t)])).values());
}
export function matchesSearch(name: string, id: string, query: string) {
  const text=(name+" "+id).toLocaleLowerCase("ru");
  return query.trim().toLocaleLowerCase("ru").split(/\s+/).every(word=>text.includes(word));
}
export function targetSummary(targets: Target[]) {
  return (Object.keys(targetTypes) as Target["scope_type"][]).map(kind=>{
    const count=targets.filter(t=>t.scope_type===kind).length;
    return count ? count+" "+targetTypes[kind] : "";
  }).filter(Boolean).join(" · ") || "Нет назначений";
}


export function targetInput(t: Target): Target {
 return {scope_type:t.scope_type,scope_id:t.scope_id,account_id:t.account_id,provider:t.provider,
  effective_start:t.effective_start??null,effective_end:t.effective_end??null};
}
export function catalogTarget(t: Target): Target {
 return {...targetInput(t),name:t.name,external_id:t.external_id,account_name:t.account_name,
 campaign_id:t.campaign_id,adset_id:t.adset_id};
}
