import data from "./metric-registry.json";
export type TableScope=keyof typeof data.scopes;
export type MetricKey=keyof typeof data.metrics;
export type MetricDefinition={key:MetricKey;label:string;technicalName:string;description:string;unit:"text"|"count"|"number"|"currency"|"percent";category:keyof typeof data.categories;available:boolean;scopes:TableScope[];defaultWidth:number;minWidth:number;maxWidth:number;precision:number;availability:"supported"|"conditional";required?:boolean};
export const metricRegistry=data.metrics as unknown as Record<MetricKey,MetricDefinition>;
export const scopeNames=data.scopes;
export const categories=data.categories;
export function scopeMetrics(scope:TableScope){return Object.values(metricRegistry).filter(m=>m.scopes.includes(scope));}
export function labelFor(metric:MetricDefinition,scope:TableScope){
  if(scope==="tracker"&&["clicks","unique_clicks","leads","sales","conversions"].includes(metric.key))return metric.label+" трекера";
  if(scope==="creative"&&["leads","sales","conversions"].includes(metric.key))return metric.label+" Meta";
  return metric.label;
}
export {data};
