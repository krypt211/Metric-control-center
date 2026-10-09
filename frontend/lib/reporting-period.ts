export function dateRange(preset:string,now:Date=new Date(),zone:string='Europe/Moscow'):[string,string]{
 const parts=new Intl.DateTimeFormat('en-CA',{timeZone:zone,year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(now);
 const get=(type:string)=>parts.find(p=>p.type===type)!.value;
 const today=`${get('year')}-${get('month')}-${get('day')}`;
 const day=new Date(`${today}T12:00:00Z`);
 const shift=(n:number)=>new Date(day.getTime()-n*86400000).toISOString().slice(0,10);
 if(preset==='yesterday')return [shift(1),shift(1)];
 return [shift(Math.max(0,Number(preset)-1)),today];
}