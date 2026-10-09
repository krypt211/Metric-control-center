import {dateRange} from "./reporting-period";
import type {StatisticsRow} from "../components/StatisticsTable";
export type Level = "account" | "campaign" | "adset" | "ad";
export type Profile = {
 id?: string; version?: number; deleted?: boolean; name: string; offer: string; geo: string;
 payout: string; currency: string; target_roi: string; minimum_roi: string;
 planned_approval_rate: string; lead_source: "meta" | "tracker"; minimum_leads: number;
 minimum_sales: number; sale_threshold_type: "approved" | "observed" | "estimated";
 minimum_processed: number; maturation_hours: number; actual_approval_policy: "planned" | "mature_actual";
};
export const emptyProfile: Profile = {name:"",offer:"",geo:"",payout:"30",currency:"USD",target_roi:"100",minimum_roi:"0",planned_approval_rate:"0.3",lead_source:"meta",minimum_leads:10,minimum_sales:2,sale_threshold_type:"approved",minimum_processed:30,maturation_hours:72,actual_approval_policy:"planned"};
export function profileCommand(p: Profile) {
 return Object.fromEntries(Object.keys(emptyProfile).map(key => [key,p[key as keyof Profile]]));
}
// Decimal shifts preserve input precision; monetary calculations stay on the server.
export function percentToRate(input: string): string {
 if (!/^\d{1,3}(\.\d{1,6})?$/.test(input) || Number(input)>100) throw new Error("Апрув должен быть от 0 до 100%, до 6 знаков после запятой.");
 const [whole,fraction=""] = input.split(".");
 const digits=whole.padStart(3,"0");
 return (digits.slice(0,-2)+"."+digits.slice(-2)+fraction).replace(/0+$/,"").replace(/\.$/,"");
}
export function rateToPercent(input: string): string {
 const [whole,fraction=""] = input.split(".");
 const padded=fraction.padEnd(2,"0");
 const integer=(whole+padded.slice(0,2)).replace(/^0+(?=\d)/,"");
 const rest=padded.slice(2).replace(/0+$/,"");
 return integer+(rest?"."+rest:"");
}
export function economicRange(preset: string, now: Date = new Date()): [string,string] {
 if (preset!=="closed7") return dateRange(preset,now);
 const end=dateRange("yesterday",now)[0];
 return [new Date(Date.parse(end+"T00:00:00Z")-6*86400000).toISOString().slice(0,10),end];
}
export const labels: Record<string,string> = {
 ACTUAL_VERIFIED:"Проверенные данные источника",ACTUAL_MANUAL:"Ручное подтверждение",ESTIMATED:"Прогноз",UNKNOWN:"Недостаточно данных",
 PLANNED:"Плановый",GROUP_MANUAL:"Ручной апрув группы (прогноз)",MATURE:"Зрелые",IMMATURE:"Ожидают созревания",
 TARGET_MET:"Цель достигнута",WITHIN_MINIMUM:"В пределах минимума",BELOW_MINIMUM:"Ниже минимума",AWAITING_CONFIRMATION:"Ожидаем подтверждения",INSUFFICIENT_DATA:"Недостаточная выборка",INCOMPATIBLE:"Несовместимые данные",
 OBSERVATION_WINDOW_MISMATCH:"Когорта выходит за границы периода",COHORT_BASE_MISMATCH:"Число решений не совпадает с лидами выбранного источника",ATTRIBUTION_UNCONFIRMED:"Атрибуция не подтверждена",INHERITED_GROUP_ESTIMATE:"Апрув группы используется только для прогноза",REVENUE_NOT_CONFIRMED:"Оплата апрувов не подтверждена",AMBIGUOUS_ASSIGNMENT:"Несколько подходящих профилей — выберите один",ECONOMICS_OBSERVATION_PROFILE_MISMATCH:"Валюта или источник лидов не совпадают с профилем",ECONOMICS_OBSERVATION_OVERLAP:"Когорты пересекаются. Уточните существующую когорту или исправьте даты.",APPROVAL_UNKNOWN:"Ручной апрув не задан",EDIT_GRANT:"Доступ к редактированию изменён",ACTUAL_APPROVAL_INSUFFICIENT:"Недостаточно зрелых решений для фактического апрува",ACTUAL_REVENUE_UNCONFIRMED:"Выручка не подтверждена",UNKNOWN_FACTS:"Нет подтверждённых расходов или лидов",ZERO_SPEND:"Расход равен нулю",INSUFFICIENT_SAMPLE:"Не достигнут порог лидов или продаж",IMMATURE_DATA:"Не истёк срок созревания или есть Pending",SOURCE_STALE:"Источник требует обновления",OBSERVATION_SOURCE_MISMATCH:"Источник или атрибуция когорты не совпадают",OBSERVATION_COVERAGE_INCOMPLETE:"Когорты не покрывают весь период",NO_PROFILE_ASSIGNED:"Профиль не назначен",SELECTED_PREVIEW:"Предпросмотр выбранного профиля",CURRENCY_MISMATCH:"Валюты не совпадают",GROUP_APPROVAL_FORECAST_ONLY:"Апрув группы применяется только к прогнозу",
 PROFILE_CREATE:"Профиль создан",PROFILE_UPDATE:"Профиль изменён",PROFILE_DELETE:"Профиль удалён",PROFILE_RESTORE:"Профиль восстановлен",ASSIGNMENT_CREATE:"Профиль назначен",ASSIGNMENT_REMOVE:"Назначение снято",OBSERVATION_CREATE:"Когорта создана",OBSERVATION_UPDATE:"Когорта уточнена",GRANT_UPDATE:"Доступ изменён",
 ECONOMICS_VERSION_CONFLICT:"Запись изменена в другой вкладке. Обновите данные и повторите изменение.",ECONOMICS_COHORT_OVERLAP:"Когорты этого профиля и уровня пересекаются. Исправьте даты или уточните существующую когорту.",ECONOMICS_ASSIGNMENT_OVERLAP:"Для этого уровня уже есть назначение в выбранном периоде.",ECONOMICS_EDIT_REQUIRED:"Редактирование не разрешено.",ECONOMICS_CURRENCY_MISMATCH:"Валюта когорты должна совпадать с профилем.",ECONOMICS_LEAD_SOURCE_MISMATCH:"Источник лидов должен совпадать с профилем."
};
export const levelNames: Record<Level|string,string>={account:"Кабинеты",campaign:"Кампании",adset:"Группы объявлений",ad:"Объявления",profile:"Группа профиля"};
export function localized(value: unknown): string {return labels[String(value)]??String(value??"—");}
export function economicRow(raw: Record<string,unknown>): StatisticsRow {
 const row: StatisticsRow={};
 for (const [key,value] of Object.entries(raw)) if (value===null || ["string","number","boolean"].includes(typeof value)) row[key]=value as StatisticsRow[string];
 for (const key of ["economics_status","economics_data_quality","approval_source","maturity_status"]) row[key]=localized(raw[key]);
 row.economics_reasons=Array.isArray(raw.reason_codes)?raw.reason_codes.map(localized).join("; "):null;
 row.last_updated=raw.last_updated?new Date(String(raw.last_updated)).toLocaleString("ru-RU"):null;
 row.late_event_changes=raw.event_changes&&Object.keys(raw.event_changes as object).length?Object.entries(raw.event_changes as Record<string,{delta:number}>).map(([k,v])=>`${k}: ${v.delta>0?"+":""}${v.delta}`).join("; "):null;
 return row;
}