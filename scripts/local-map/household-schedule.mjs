// Our street's verified 2026 city calendar. Keep exceptions rather than
// assuming every sweep occurs on its usual weekday (September is delayed).
export const SWEEP_DAYS_2026 = [[14,28],[11,25],[11,25],[8,22],[13],[10],[8],[12],[10],[14,28],[11,25],[9,23]];
export const SWEEP_SOURCE = 'https://toaks.gov/corecode/storage/uber_resource/uploaded_pdfs/2026%20Residential_Street%20Sweeping%20Schedule_121825_1766106483.pdf';
const DAY = 86400000;
const iso = date => date.toISOString().slice(0,10);
const date = (year,month,day) => new Date(Date.UTC(year,month-1,day));
export function nthWeekday(year,month,weekday,n) {
  const first=date(year,month,1);
  return date(year,month,1+(weekday-first.getUTCDay()+7)%7+7*(n-1));
}
export function holidays(year) {
  const memorial=nthWeekday(year,5,1,5);
  if(memorial.getUTCMonth()!==4)memorial.setUTCDate(memorial.getUTCDate()-7);
  return [date(year,1,1),memorial,date(year,7,4),nthWeekday(year,9,1,1),nthWeekday(year,11,4,4),date(year,12,25)]
    .filter(d=>d.getUTCDay()>0 && d.getUTCDay()<6);
}
// Athens delays only routes on/after a weekday holiday within that same week.
export function holidayShift(serviceDate) {
  const monday=new Date(serviceDate.getTime()-((serviceDate.getUTCDay()+6)%7)*DAY);
  return holidays(serviceDate.getUTCFullYear()).some(h=>h>=monday && h<=serviceDate)?1:0;
}
export function localClock(now=new Date()) {
  const parts=new Intl.DateTimeFormat('en-US',{timeZone:'America/Los_Angeles',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',hourCycle:'h23'}).formatToParts(now);
  const values=Object.fromEntries(parts.map(p=>[p.type,p.value]));
  return {today:`${values.year}-${values.month}-${values.day}`,hour:Number(values.hour)};
}
export function nextTrash(today,hour=0) {
  const start=new Date(`${today}T00:00:00Z`);
  for(let offset=0;offset<15;offset++){
    const nominal=new Date(start.getTime()+offset*DAY);
    if(nominal.getUTCDay()!==2)continue;
    const shifted=holidayShift(nominal), actual=new Date(nominal.getTime()+shifted*DAY);
    if(iso(actual)>today || (iso(actual)===today && hour<19))return {date:iso(actual),holidayDelayed:!!shifted};
  }
  // On a delayed Wednesday, include Tuesday's shifted route until 7 PM.
  throw new Error('No upcoming collection found');
}
export function upcomingTrash(today,hour=0) {
  const previous=new Date(`${today}T00:00:00Z`);previous.setUTCDate(previous.getUTCDate()-1);
  if(previous.getUTCDay()===2 && holidayShift(previous) && hour<19)return {date:today,holidayDelayed:true};
  return nextTrash(today,hour);
}
export function nextSweeps(today,hour=0,count=3) {
  const year=Number(today.slice(0,4)), all=[];
  for(let y=year;y<=year+1;y++)for(let month=1;month<=12;month++){
    if(y===2026){for(const day of SWEEP_DAYS_2026[month-1])all.push({date:iso(date(y,month,day)),verified:true});}
    else {
      for(const week of month>=5 && month<=9?[2]:[2,4]){
        const nominal=nthWeekday(y,month,3,week), shift=holidayShift(nominal);
        all.push({date:iso(new Date(nominal.getTime()+shift*DAY)),verified:false});
      }
    }
  }
  return all.filter(d=>d.date>today || (d.date===today && hour<19)).slice(0,count);
}
export function relativeDay(value,today) {
  const days=Math.round((new Date(`${value}T00:00:00Z`)-new Date(`${today}T00:00:00Z`))/DAY);
  return days===0?'Today':days===1?'Tomorrow':`In ${days} days`;
}
export function formatDay(value) {
  return new Intl.DateTimeFormat('en-US',{timeZone:'UTC',weekday:'long',month:'short',day:'numeric'}).format(new Date(`${value}T00:00:00Z`));
}
