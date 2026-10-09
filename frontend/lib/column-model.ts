import {data,metricRegistry,scopeMetrics,type MetricKey,type TableScope} from "./metric-registry";
export type Sorting={key:MetricKey;direction:"asc"|"desc"}|null;
export type ColumnConfig={version:1;columns:{key:MetricKey;width:number}[];widths:Partial<Record<MetricKey,number>>;sorting:Sorting};
export type Preset={id:string;name:string;scope:TableScope;system:boolean;version:number;config:ColumnConfig};
export type Bundle={scope:TableScope;presets:Preset[];preference:{active_id:string;default_id:string;config:ColumnConfig;version:number}};
export function clampWidth(key:MetricKey,width:number){const m=metricRegistry[key];return Math.max(m.minWidth,Math.min(m.maxWidth,Math.round(width)));}
export function systemPresets(scope:TableScope):Preset[]{
  const allowed=new Set(scopeMetrics(scope).map(m=>m.key));
  return Object.entries(data.systems).map(([key,item])=>{
    const keys=["name",...(scope==="rule_ad"&&key==="basic"?data.rules_default:scope.startsWith("eco_")&&key==="basic"?data.economics_default:item.keys).filter(k=>allowed.has(k as MetricKey)&&k!=="name")] as MetricKey[];
    const sort=keys.includes("spend")?"spend":keys.includes("clicks")?"clicks":"name";
    return {id:"system:"+key,name:item.name,scope,system:true,version:0,config:{version:1,columns:keys.map(k=>({key:k,width:metricRegistry[k].defaultWidth})),widths:{},sorting:{key:sort,direction:sort==="name"?"asc":"desc"}}};
  });
}
export function initialBundle(scope:TableScope):Bundle{
  const presets=systemPresets(scope);return {scope,presets,preference:{active_id:presets[0].id,default_id:presets[0].id,config:presets[0].config,version:0}};
}
export function normalizeColumns(config:ColumnConfig,scope:TableScope):ColumnConfig{
  const allowed=new Set(scopeMetrics(scope).map(m=>m.key));const seen=new Set<string>();
  const columns=config.columns.filter(c=>allowed.has(c.key)&&!seen.has(c.key)&&!!seen.add(c.key)).map(c=>({...c,width:clampWidth(c.key,c.width)}));
  const name=columns.find(c=>c.key==="name")??{key:"name" as MetricKey,width:metricRegistry.name.defaultWidth};
  return {...config,version:1,columns:[name,...columns.filter(c=>c.key!=="name")],widths:Object.fromEntries(Object.entries(config.widths??{}).filter(([k])=>allowed.has(k as MetricKey))),sorting:config.sorting&&allowed.has(config.sorting.key)?config.sorting:null};
}
export function setVisible(config:ColumnConfig,key:MetricKey,visible:boolean):ColumnConfig{
  if(key==="name")return config;
  const found=config.columns.find(c=>c.key===key);
  if(visible&&!found)return {...config,columns:[...config.columns,{key,width:config.widths[key]??metricRegistry[key].defaultWidth}]};
  if(!visible&&found)return {...config,columns:config.columns.filter(c=>c.key!==key),widths:{...config.widths,[key]:found.width}};
  return config;
}
export function moveColumn(config:ColumnConfig,source:MetricKey,target:MetricKey):ColumnConfig{
  if(source==="name"||source===target)return config;
  const columns=config.columns.slice();const from=columns.findIndex(c=>c.key===source),to=columns.findIndex(c=>c.key===target);
  if(from<0||to<0)return config;
  const [item]=columns.splice(from,1);columns.splice(Math.max(1,to),0,item);return {...config,columns};
}
export function resizeColumn(config:ColumnConfig,key:MetricKey,width:number):ColumnConfig{
  width=clampWidth(key,width);return {...config,columns:config.columns.map(c=>c.key===key?{...c,width}:c),widths:{...config.widths,[key]:width}};
}
export function resetWidths(config:ColumnConfig):ColumnConfig{return {...config,columns:config.columns.map(c=>({...c,width:metricRegistry[c.key].defaultWidth})),widths:{}};}
export function formatMetric(value:unknown,key:MetricKey,currency:unknown):string{
  if(value===null||value===undefined||value==="")return "—";
  const spec=metricRegistry[key];if(spec.unit==="text")return String(value);
  const n=Number(value);if(!Number.isFinite(n))return "—";
  if(spec.unit==="currency"&&typeof currency==="string"&&/^[A-Z]{3}$/.test(currency)){
    try{return new Intl.NumberFormat("ru-RU",{style:"currency",currency,maximumFractionDigits:spec.precision}).format(n);}catch{/* Unknown currency stays separate. */}
  }
  return new Intl.NumberFormat("ru-RU",{maximumFractionDigits:spec.precision}).format(n)+(spec.unit==="percent"?"%":"");
}
