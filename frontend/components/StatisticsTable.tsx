"use client";
import {useEffect,useRef,useState} from "react";
import {labelFor,metricRegistry,type MetricKey,type TableScope} from "../lib/metric-registry";
import {formatMetric,moveColumn,resizeColumn,type ColumnConfig} from "../lib/column-model";
export type StatisticsRow=Record<string,string|number|boolean|null|undefined>;
export default function StatisticsTable({scope,rows,config,change,commit,disabled=false,onName,selection}:{scope:TableScope;rows:StatisticsRow[];config:ColumnConfig;change:(fn:(c:ColumnConfig)=>ColumnConfig,defer?:boolean)=>void;commit:()=>void;disabled?:boolean;onName?:(row:StatisticsRow)=>void;selection?:{selected:(row:StatisticsRow)=>boolean;toggle:(row:StatisticsRow,checked:boolean)=>void;disabled:(row:StatisticsRow)=>boolean}}){
 const wrap=useRef<HTMLDivElement>(null),dragging=useRef<MetricKey|null>(null),speed=useRef(0),frame=useRef(0);
 const resizing=useRef<{key:MetricKey;start:number;width:number}|null>(null);
 const [target,setTarget]=useState<MetricKey|null>(null),[isResizing,setResizing]=useState(false);
 useEffect(()=>()=>cancelAnimationFrame(frame.current),[]);
 function stopDrag(){dragging.current=null;speed.current=0;cancelAnimationFrame(frame.current);setTarget(null);}
 function scroll(){if(!dragging.current)return;if(wrap.current)wrap.current.scrollLeft+=speed.current;frame.current=requestAnimationFrame(scroll);}
 function autoFit(key:MetricKey){
 if(disabled)return;const ctx=document.createElement("canvas").getContext("2d");if(!ctx)return;
 ctx.font=getComputedStyle(wrap.current!).font;
 const cells=wrap.current!.querySelectorAll('[data-column="'+key+'"]');
 change(c=>resizeColumn(c,key,Math.max(...Array.from(cells).map(cell=>ctx.measureText(cell.textContent??"").width+64))));
 }
 const total=config.columns.reduce((sum,c)=>sum+c.width,0)+(selection?52:0);
 return <div className={"tablewrap customizable-table-wrap"+(isResizing?" is-resizing":"")} ref={wrap} onDragOver={e=>{
 if(!dragging.current)return;e.preventDefault();const rect=wrap.current!.getBoundingClientRect();speed.current=e.clientX<rect.left+60?-9:e.clientX>rect.right-60?9:0;
 }}>
 <table className="customizable-table" style={{width:total,minWidth:total}} data-testid="statistics-table">
 <colgroup>{selection&&<col style={{width:52}}/>}{config.columns.map(c=><col key={c.key} style={{width:c.width}}/>)}</colgroup>
 <thead><tr>{selection&&<th className="selection-column">Выбор</th>}{config.columns.map(col=>{
 const spec=metricRegistry[col.key],sort=config.sorting;
 return <th key={col.key} data-column={col.key} data-testid={"column-"+col.key} className={(col.key==="name"?"identity-column ":"")+(target===col.key?"drag-target":"")} style={{left:col.key==="name"&&selection?52:undefined}} aria-sort={sort?.key===col.key?(sort.direction==="asc"?"ascending":"descending"):"none"}
 onDragOver={e=>{if(dragging.current){e.preventDefault();setTarget(col.key);}}}
 onDrop={e=>{e.preventDefault();if(dragging.current)change(c=>moveColumn(c,dragging.current!,col.key));stopDrag();}}>
 <div className="column-heading">
 {col.key!=="name"&&<button type="button" className="drag-handle" aria-label={"Переместить: "+labelFor(spec,scope)} data-testid={"drag-"+col.key} disabled={disabled} draggable={!disabled}
 onDragStart={e=>{if(resizing.current){e.preventDefault();return;}dragging.current=col.key;e.dataTransfer.setData("text/plain",col.key);e.dataTransfer.effectAllowed="move";frame.current=requestAnimationFrame(scroll);}} onDragEnd={stopDrag}>⋮⋮</button>}
 <button className="sort-heading" title={spec.description} disabled={disabled} onClick={()=>change(c=>({...c,sorting:{key:col.key,direction:c.sorting?.key===col.key&&c.sorting.direction==="desc"?"asc":"desc"}}))}>
 {labelFor(spec,scope)} {sort?.key===col.key?(sort.direction==="asc"?"↑":"↓"):""}
 </button><span className="metric-info" tabIndex={0} aria-label={spec.description}>ⓘ<span role="tooltip">{spec.description}</span></span>
 </div>
 <div className="resize-handle" role="separator" aria-orientation="vertical" aria-label={"Изменить ширину: "+labelFor(spec,scope)} data-testid={"resize-"+col.key} tabIndex={0} aria-valuemin={spec.minWidth} aria-valuemax={spec.maxWidth} aria-valuenow={col.width}
 onPointerDown={e=>{if(disabled||e.button!==0)return;e.preventDefault();e.stopPropagation();stopDrag();resizing.current={key:col.key,start:e.clientX,width:col.width};e.currentTarget.setPointerCapture(e.pointerId);setResizing(true);}}
 onPointerMove={e=>{const state=resizing.current;if(state?.key===col.key)change(c=>resizeColumn(c,col.key,state.width+e.clientX-state.start),true);}}
 onPointerUp={e=>{if(!resizing.current)return;e.preventDefault();e.stopPropagation();resizing.current=null;setResizing(false);if(e.currentTarget.hasPointerCapture(e.pointerId))e.currentTarget.releasePointerCapture(e.pointerId);commit();}}
 onPointerCancel={()=>{resizing.current=null;setResizing(false);commit();}}
 onDoubleClick={e=>{e.stopPropagation();autoFit(col.key);}}
 onKeyDown={e=>{if(!disabled&&(e.key==="ArrowLeft"||e.key==="ArrowRight")){e.preventDefault();change(c=>resizeColumn(c,col.key,col.width+(e.key==="ArrowRight"?10:-10)));}}}/>
 </th>;
 })}</tr></thead>
 <tbody>{rows.map((row,index)=><tr key={String(row.id)+"-"+row.currency+"-"+row.timezone+"-"+index}>
 {selection&&<td className="selection-column"><input type="checkbox" aria-label={"Выбрать "+row.name} checked={selection.selected(row)} disabled={selection.disabled(row)} onChange={e=>selection.toggle(row,e.target.checked)}/></td>}
 {config.columns.map(col=><td key={col.key} data-column={col.key} className={col.key==="name"?"identity-column":metricRegistry[col.key].unit==="text"?"text-column":"numeric-column"} style={{left:col.key==="name"&&selection?52:undefined}}>
 {col.key==="name"?<><button className="rowlink" onClick={()=>onName?.(row)} title={String(row.name??row.account_name??"—")}>
 {typeof row.thumbnail_url==="string"&&/^https?:\/\//.test(row.thumbnail_url)&&<img src={row.thumbnail_url} alt="" className="thumb" loading="lazy" referrerPolicy="no-referrer"/>}{String(row.name??row.account_name??"—")}
 </button><small>{scope==="tracker"?[row.account_name,row.date].filter(Boolean).join(" · "):row.timezone}</small>
{scope==="account"&&<><small>{String(row.external_id??"")} · {String(row.currency??"")} · {row.status==="ACTIVE"?"Активен":row.status==="PAUSED"?"Остановлен":String(row.status??"Статус неизвестен")} · {row.source_provider==="meta"?"Meta":"MetricFlow"}</small>{row.has_facts===false&&<small className="missing-data">{row.data_status==="not_started"?"Выбранная дата ещё не началась в timezone кабинета":row.data_status==="not_synced"?"Нет подтверждённой синхронизации периода":"Нет данных за выбранный период"}</small>}</>}
</>:<span title={formatMetric(row[col.key],col.key,row.currency)}>{formatMetric(row[col.key],col.key,row.currency)}</span>}
 </td>)}
 </tr>)}{!rows.length&&<tr><td colSpan={config.columns.length+(selection?1:0)} className="empty-cell">Нет сохранённых данных по выбранным фильтрам</td></tr>}</tbody>
 </table>
 </div>;
}
