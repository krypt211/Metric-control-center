"use client";
import {useEffect,useRef,useState} from "react";
import {categories,labelFor,scopeMetrics,type TableScope} from "../lib/metric-registry";
import {moveColumn,resizeColumn,resetWidths,setVisible} from "../lib/column-model";
import type {ColumnController} from "../lib/use-column-preferences";
export default function ColumnManager({scope,controller:c,rows}:{scope:TableScope;controller:ColumnController;rows:Record<string,unknown>[]}){
 const [open,setOpen]=useState(false),[search,setSearch]=useState(""),[name,setName]=useState("");
 const dialog=useRef<HTMLDialogElement>(null);
 useEffect(()=>{if(open)dialog.current?.showModal();},[open]);
 const metrics=scopeMetrics(scope),disabled=!c.ready||c.busy;
 return <>
 <div className="column-toolbar">
 <label>Набор колонок:<select aria-label="Набор колонок" value={c.bundle.preference.active_id} disabled={disabled} onChange={e=>{if(e.target.value.startsWith("command:"))setOpen(true);else c.activate(e.target.value);}}>
 <optgroup label="Системные">{c.bundle.presets.filter(p=>p.system).map(p=><option key={p.id} value={p.id}>{p.name}{p.id===c.bundle.preference.default_id?" ★":""}</option>)}</optgroup>
 <optgroup label="Мои наборы">{c.bundle.presets.filter(p=>!p.system).map(p=><option key={p.id} value={p.id}>{p.name}{p.id===c.bundle.preference.default_id?" ★":""}</option>)}</optgroup>
 <option value="command:create">Создать набор…</option><option value="command:manage">Управление наборами…</option>
 </select></label>
 <button onClick={()=>setOpen(true)}>Настроить колонки</button>
 <button disabled={disabled||!c.modified} onClick={()=>c.save()}>{c.active.system?"Сохранить как мой набор":"Сохранить набор"}</button>
 <span role="status" className="column-save-status">{c.modified?"Набор изменён · ":""}{c.status}</span>
 </div>
 {c.error&&<div className="notice error" role="alert">{c.error} <button onClick={()=>void c.reload()}>Загрузить серверные настройки</button></div>}
 {open&&<dialog ref={dialog} className="column-dialog" onCancel={()=>setOpen(false)}>
 <div className="column-dialog-title"><h2>Настроить колонки</h2><button aria-label="Закрыть настройку колонок" onClick={()=>{dialog.current?.close();setOpen(false);}}>Закрыть</button></div>
 <p className="subtitle">Название всегда остаётся первым. Рабочий вид сохраняется автоматически; «Сохранить набор» обновляет собственный шаблон.</p>
 <div className="preset-actions">
 <input aria-label="Название нового набора" placeholder="Название нового набора" maxLength={80} value={name} onChange={e=>setName(e.target.value)}/>
 <button disabled={disabled||!name.trim()} onClick={()=>{c.create(name.trim());setName("");}}>Создать набор</button>
 <button disabled={disabled} onClick={()=>{const label=window.prompt("Название нового набора",c.active.name+" — мой");if(label?.trim())c.create(label.trim());}}>Сохранить как новый</button>
 <button disabled={disabled||c.active.system} onClick={()=>{const label=window.prompt("Новое название",c.active.name);if(label?.trim())c.save(label.trim());}}>Переименовать</button>
 <button disabled={disabled} onClick={()=>c.duplicate(c.active)}>Дублировать</button>
 <button disabled={disabled||c.active.system} onClick={c.remove}>Удалить набор</button>
 <button disabled={disabled||c.bundle.preference.default_id===c.active.id} onClick={c.makeDefault}>Сделать основным</button>
 <button disabled={disabled} onClick={()=>c.activate(c.active.id)}>Восстановить настройки набора</button>
 <button disabled={disabled} onClick={()=>c.activate("system:basic")}>Стандартный набор</button>
 <button disabled={disabled} onClick={()=>c.change(resetWidths)}>Сбросить ширину колонок</button>
 </div>
 <label className="metric-search">Поиск метрик<input type="search" value={search} onChange={e=>setSearch(e.target.value)} placeholder="Название, ключ или описание"/></label>
 <div className="column-dialog-grid"><div>{Object.entries(categories).map(([category,label])=>{
 const group=metrics.filter(m=>m.category===category&&[labelFor(m,scope),m.key,m.description].join(" ").toLocaleLowerCase("ru").includes(search.toLocaleLowerCase("ru")));
 if(!group.length)return null;
 return <fieldset key={category}><legend>{label}</legend>
 <div className="category-buttons"><button disabled={disabled} onClick={()=>c.change(cfg=>group.reduce((next,m)=>setVisible(next,m.key,true),cfg))}>Выбрать группу</button><button disabled={disabled} onClick={()=>c.change(cfg=>group.reduce((next,m)=>setVisible(next,m.key,false),cfg))}>Скрыть группу</button></div>
 {group.map(m=><label className="metric-choice" key={m.key} title={m.description}>
 <input type="checkbox" data-testid={"column-toggle-"+m.key} checked={c.config.columns.some(col=>col.key===m.key)} disabled={disabled||!!m.required} onChange={e=>c.change(cfg=>setVisible(cfg,m.key,e.target.checked))}/>
 <span>{labelFor(m,scope)} <small>{m.technicalName}</small>{m.availability==="conditional"&&!rows.some(row=>row[m.key]!==null&&row[m.key]!==undefined)&&<em>Нет данных</em>}<small>{m.description}</small></span>
 </label>)}</fieldset>;
 })}</div><div><h3>Порядок и ширина</h3><ol className="column-order">
 {c.config.columns.map((col,index)=>{const spec=metrics.find(m=>m.key===col.key)!;return <li key={col.key}><span>{labelFor(spec,scope)}</span><div>
 <button aria-label={"Вверх: "+col.key} disabled={disabled||index<=1} onClick={()=>c.change(cfg=>moveColumn(cfg,col.key,cfg.columns[index-1].key))}>↑</button>
 <button aria-label={"Вниз: "+col.key} disabled={disabled||index===0||index===c.config.columns.length-1} onClick={()=>c.change(cfg=>moveColumn(cfg,col.key,cfg.columns[index+1].key))}>↓</button>
 <input aria-label={"Ширина: "+col.key} type="number" min={spec.minWidth} max={spec.maxWidth} value={col.width} disabled={disabled} onChange={e=>{if(e.target.value)c.change(cfg=>resizeColumn(cfg,col.key,Number(e.target.value)));}}/><span>px</span>
 </div></li>;})}
 </ol><p className="subtitle">Заголовок сортирует; ⋮⋮ переносит колонку; правая граница меняет ширину. Двойной клик подбирает ширину по текущей странице.</p></div></div>
 <div className="column-dialog-footer"><span role="status">{c.status}</span><button disabled={disabled} onClick={()=>c.save()}>{c.active.system?"Сохранить как мой набор":"Сохранить набор"}</button></div>
 </dialog>}
 </>;
}
