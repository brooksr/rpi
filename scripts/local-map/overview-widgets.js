// Add native Lovelace sections to the generated Overview while preserving its
// favorites, areas and summaries. HA upgrades may change the strategy hook.
import {sunTimes,moonPhase} from './sky.mjs';
const make = (tag, text, cls) => {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (cls) element.className = cls;
  return element;
};
const localTime = value => value ? new Date(value).toLocaleString(undefined, {
  timeZone: 'America/Los_Angeles', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
}) : 'Not checked yet';
const stale = entity => !entity?.attributes.checked_at ||
  Date.now() - new Date(entity.attributes.checked_at).getTime() > 15 * 60 * 1000;

class LocalWarningsCard extends HTMLElement {
  constructor() { super(); this.attachShadow({mode: 'open'}); }
  setConfig(config) { this.config = config; this.toggleAttribute('hide-title', !!config.hide_title); }
  getCardSize() { return 4; }
  getGridOptions() { return {columns: 12, rows: 'auto'}; }
  set hass(hass) {
    const weather = hass.states[this.config?.weather_entity || 'sensor.local_weather_alerts'];
    const power = hass.states[this.config?.power_entity || 'sensor.power_shutoff'];
    if (this.weather === weather && this.power === power && this.rendered) return;
    this.weather = weather; this.power = power; this.rendered = true;
    this.render();
  }
  render() {
    this.shadowRoot.innerHTML = `<style>
      :host{display:block}:host([hide-title]) h2{display:none}ha-card{display:block;padding:18px;color:var(--primary-text-color);background:var(--ha-card-background,var(--card-background-color));border-radius:var(--ha-card-border-radius,12px)}
      h2{font-size:24px;line-height:1.3;margin:0 0 14px;font-weight:600}h3{font-size:19px;margin:0 0 5px;line-height:1.35}p{margin:5px 0;line-height:1.5}
      .notice{padding:12px 14px;border:1px solid #ffb56b;border-left-width:5px;border-radius:8px;margin:10px 0;background:#00000018}
      .power{border-color:#ffb56b}.weather{border-color:#d7a9ff}.unavailable{border-color:#aaa}.clear{font-size:15px;opacity:.85}
      .checked{font-size:12px;opacity:.8;margin-top:14px}.links{display:flex;flex-wrap:wrap;gap:16px;margin-top:14px}
      a{color:var(--primary-text-color);text-decoration:underline;font-size:15px}a:focus-visible,summary:focus-visible{outline:2px solid currentColor;outline-offset:3px}
      details{margin-top:9px}summary{cursor:pointer;font-size:14px}.description{white-space:pre-wrap;font-size:14px;max-height:240px;overflow:auto;padding:8px 0}
    </style><ha-card><h2>Weather & power warnings</h2><div id="notices" aria-live="polite"></div><div class="checked" id="checked"></div><div class="links"><a href="/local-map/conditions">Open local map</a><a href="https://www.sce.com/outages-safety/outage-center/check-outage-status" target="_blank" rel="noopener">SCE outage details ↗</a></div></ha-card>`;
    const container = this.shadowRoot.querySelector('#notices');
    const p = this.power, w = this.weather;
    let warnings = 0;
    if (!p || ['unknown','unavailable'].includes(p.state) || stale(p)) {
      this.notice(container,'Power status unavailable','Check SCE for the current @@PSPS_CIRCUIT@@ status.','unavailable');
    } else if (['under_consideration','power_shutoff'].includes(p.state)) {
      warnings++;
      const item = this.notice(container,p.state==='power_shutoff'?'@@PSPS_CIRCUIT@@ — power shut off':'@@PSPS_CIRCUIT@@ — possible power shutoff',p.state==='power_shutoff'?'SCE lists an active public safety power shutoff.':'SCE is considering a public safety power shutoff.','power');
      for (const event of p.attributes.events || []) {
        if(event.StartDate || event.EndDate)item.append(make('p',`${localTime(event.StartDate)} – ${localTime(event.EndDate)}`));
        if(event.POCNotes)item.append(make('p',event.POCNotes));
        if(event.ERTNotes)item.append(make('p',event.ERTNotes));
      }
    }
    if (!w || !['active','clear'].includes(w.state) || stale(w)) {
      this.notice(container,'Weather warnings unavailable','The weather alert feed is still loading or cannot be reached.','unavailable');
    } else {
      for(const alert of w.attributes.alerts || []) {
        // Expired cached warnings should not be presented as active.
        if(alert.expires && new Date(alert.expires).getTime() <= Date.now())continue;
        warnings++;
        const item=this.notice(container,alert.event || 'Weather warning',alert.headline || '', 'weather');
        if(alert.ends)item.append(make('p',`Until ${localTime(alert.ends)}`));
        if(alert.instruction || alert.description){const details=make('details'),summary=make('summary','Details & instructions');details.append(summary,make('div',[alert.instruction,alert.description].filter(Boolean).join('\n\n'),'description'));item.append(details);}
      }
    }
    if(!warnings && w?.state==='clear' && p?.state==='no_psps_listed' && !stale(p) && !stale(w))container.append(make('p','No active weather or @@PSPS_CIRCUIT@@ shutoff warnings.','clear'));
    else if(!warnings && w?.state==='clear' && !stale(w))container.append(make('p','No active weather warnings.','clear'));
    this.shadowRoot.querySelector('#checked').textContent=`Weather: ${localTime(w?.attributes.checked_at)} · Power: ${localTime(p?.attributes.checked_at)} · Refreshes every 10 minutes`;
  }
  notice(parent,title,text,cls) {const item=make('section',undefined,`notice ${cls}`);item.append(make('h3',title));if(text)item.append(make('p',text));parent.append(item);return item;}
}
if(!customElements.get('local-warnings-card'))customElements.define('local-warnings-card',LocalWarningsCard);

const TILE_STYLE=`:host{display:block}:host([hide-title]) h2{display:none}ha-card{display:block;padding:18px;color:var(--primary-text-color);background:var(--ha-card-background,var(--card-background-color));border-radius:var(--ha-card-border-radius,12px)}
  h2{font-size:24px;margin:0 0 14px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px}
  .item{border:1px solid #ffffff40;border-left:5px solid #9dd3a8;border-radius:8px;padding:12px 14px}.label{font-size:14px;opacity:.85}.value{font-size:22px;font-weight:600;margin:3px 0}.small{font-size:13px;opacity:.85}
  .checked{font-size:12px;opacity:.8;margin-top:14px}a{color:inherit;text-decoration:underline}`;
const band=(value,limits,names)=>names[limits.findIndex(limit=>value<=limit)] ?? names[names.length-1];
const AQI_COLORS=['#9dd3a8','#ffe28a','#ffb56b','#ff7b7b','#d7a9ff','#c97b8f'];
const aqiBand=value=>band(value,[50,100,150,200,300],[0,1,2,3,4,5]);
const AQI_NAMES=['Good','Moderate','Unhealthy for sensitive groups','Unhealthy','Very unhealthy','Hazardous'];
const COMPASS=['N','NE','E','SE','S','SW','W','NW'];

// Best available reading for home: the NWS station's measurement when it is
// under 90 minutes old, else Met.no's model; PurpleAir sensors, else the
// Open-Meteo model for AQI. `source` says which one the value came from.
const fresh=(time,minutes)=>time && Date.now()-new Date(time).getTime()<minutes*60000;
function homeReadings(hass,weatherId){
  const weather=hass.states[weatherId], w=weather?.attributes||{}, nws=hass.states['sensor.nws_observation'], n=nws?.attributes||{};
  const purple=hass.states['sensor.purpleair'], model=hass.states['sensor.local_air_quality'];
  const fahrenheit=(w.temperature_unit||'°F')==='°F', unit=w.temperature_unit||'°F', toUnit=c=>fahrenheit?c*9/5+32:c;
  const observed=fresh(n.timestamp,90) && Number.isFinite(n.temperature?.value);
  const readings={unit,weather,
    temperature:observed?toUnit(n.temperature.value):w.temperature, temperatureSource:observed?'nws':'model',
    humidity:observed&&Number.isFinite(n.relativeHumidity?.value)?n.relativeHumidity.value:w.humidity,
    dewPoint:observed&&Number.isFinite(n.dewpoint?.value)?toUnit(n.dewpoint.value):w.dew_point,
    modelTemperature:w.temperature, observedAt:observed?n.timestamp:null, uv:w.uv_index ?? model?.attributes.uv_index};
  if(purple?.state==='ok' && fresh(purple.attributes.checked_at,90))Object.assign(readings,{aqi:purple.attributes.aqi,pm25:purple.attributes.pm25,aqiSource:'purpleair',aqiSensors:purple.attributes.sensors.length});
  else if(model && Number.isFinite(Number(model.state)))Object.assign(readings,{aqi:Number(model.state),pm25:model.attributes.pm2_5,aqiSource:'model'});
  return readings;
}

// Current conditions for home: observed where possible, modelled otherwise.
class CurrentConditionsCard extends HTMLElement {
  constructor(){super();this.attachShadow({mode:'open'});}
  setConfig(config){this.config=config;this.toggleAttribute('hide-title',!!config.hide_title);}
  getCardSize(){return 4;}
  getGridOptions(){return {columns:12,rows:'auto'};}
  set hass(hass){
    const watched=[this.config.weather_entity,'sensor.local_air_quality','sensor.nws_observation','sensor.purpleair'].map(id=>hass.states[id]);
    if(this.rendered && watched.every((state,i)=>state===this.watched[i]))return;
    this.watched=watched;this.rendered=true;this.hassRef=hass;this.render();
  }
  render(){
    const hass=this.hassRef, r=homeReadings(hass,this.config.weather_entity), w=r.weather?.attributes || {}, purple=hass.states['sensor.purpleair'];
    this.shadowRoot.innerHTML=`<style>${TILE_STYLE}</style><ha-card><h2>Current conditions</h2><div class="grid" id="items"></div><div class="checked" id="checked"></div></ha-card>`;
    const items=this.shadowRoot.querySelector('#items');
    const tile=(label,value,note,color)=>{const item=make('section',undefined,'item');if(color)item.style.borderLeftColor=color;item.append(make('div',label,'label'),make('div',value,'value'));if(note)item.append(make('div',note,'small'));items.append(item);};
    const has=value=>value!==undefined && value!==null && !Number.isNaN(value);
    const condition=r.weather?(hass.formatEntityState?.(r.weather) || r.weather.state.replace(/-/g,' ')):'Unavailable';
    const deg=v=>has(v)?`${Math.round(v)}${r.unit}`:'—';
    tile('Temperature',deg(r.temperature),r.temperatureSource==='nws'?`${condition} · forecast model ${deg(r.modelTemperature)}`:condition);
    tile('Humidity',has(r.humidity)?`${Math.round(r.humidity)}%`:'—',has(r.dewPoint)?`Dew point ${deg(r.dewPoint)}`:'');
    if(has(r.aqi)){
      const level=aqiBand(r.aqi);
      tile('Air quality',`AQI ${Math.round(r.aqi)}`,`${AQI_NAMES[level]}${has(r.pm25)?` · PM2.5 ${r.pm25} µg/m³`:''}${r.aqiSource==='purpleair'?` · ${r.aqiSensors} PurpleAir sensor${r.aqiSensors===1?'':'s'}`:' · model'}`,AQI_COLORS[level]);
    } else tile('Air quality','—','Air quality feeds unavailable','#aaa');
    const uv=r.uv;
    tile('UV index',has(uv)?`${Math.round(uv)}`:'—',has(uv)?band(uv,[2.5,5.5,7.5,10.5],['Low','Moderate','High','Very high','Extreme']):'',has(uv)?band(uv,[2.5,5.5,7.5,10.5],AQI_COLORS):undefined);
    tile('Wind',has(w.wind_speed)?`${Math.round(w.wind_speed)} ${w.wind_speed_unit}`:'—',[has(w.wind_bearing)?`From ${COMPASS[Math.round(w.wind_bearing/45)%8]}`:'',has(w.wind_gust_speed)?`gusts ${Math.round(w.wind_gust_speed)}`:''].filter(Boolean).join(' · '));
    tile('Pressure',has(w.pressure)?`${w.pressure} ${w.pressure_unit}`:'—',has(w.cloud_coverage)?`Cloud cover ${Math.round(w.cloud_coverage)}%`:'');
    const temperatureNote=r.temperatureSource==='nws'?`Observed: NWS Thousand Oaks station, ${localTime(r.observedAt)}`:`Weather: Met.no model, ${localTime(r.weather?.last_updated)}`;
    const airNote=r.aqiSource==='purpleair'?`Air: PurpleAir (EPA-corrected), ${localTime(purple.attributes.checked_at)}`:`Air: Open-Meteo model${purple?.state==='needs_key'?' (add a PurpleAir key for local sensors)':''}`;
    this.shadowRoot.querySelector('#checked').textContent=`${temperatureNote} · ${airNote}`;
  }
}
if(!customElements.get('current-conditions-card'))customElements.define('current-conditions-card',CurrentConditionsCard);

// The three cheapest regular-gas prices Google Places reports within 5 miles.
class GasPricesCard extends HTMLElement {
  constructor(){super();this.attachShadow({mode:'open'});}
  setConfig(config){this.config=config;this.toggleAttribute('hide-title',!!config.hide_title);}
  getCardSize(){return 4;}
  getGridOptions(){return {columns:12,rows:'auto'};}
  set hass(hass){
    const gas=hass.states[this.config?.entity || 'sensor.local_gas_prices'];
    if(this.gas===gas && this.rendered)return;
    this.gas=gas;this.rendered=true;this.render();
  }
  render(){
    const g=this.gas;
    this.shadowRoot.innerHTML=`<style>${TILE_STYLE}.item{display:flex;gap:14px;align-items:center;margin:10px 0;border-left-color:#ffb56b}.price{font-size:26px;font-weight:600;min-width:80px}h3{font-size:19px;margin:0 0 4px}p{margin:3px 0}</style><ha-card><h2>Cheapest gas nearby</h2><div id="items"></div><div class="checked" id="checked"></div></ha-card>`;
    const items=this.shadowRoot.querySelector('#items');
    const message=text=>items.append(make('p',text,'small'));
    const denied=g?.attributes.error?.includes('PERMISSION_DENIED');
    if(denied)message('Google rejected the request. Enable Places API (New) for this key in Google Cloud.');
    else if(!g || g.state==='unavailable' || g.state==='unknown')message(`Gas prices unavailable${g?.attributes.error?` (${g.attributes.error})`:''}.`);
    else if(g.state==='needs_key')message('Add google_places_api_key to Home Assistant secrets.yaml to show gas prices.');
    else if(g.state==='no_prices')message('No nearby stations report regular gas prices to Google right now.');
    for(const station of g?.attributes.stations || []){
      const item=make('section',undefined,'item'), text=make('div'), link=make('a',station.name);
      link.href=`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${station.name} ${station.address||''}`)}&query_place_id=${encodeURIComponent(station.place_id||'')}`;
      link.target='_blank';link.rel='noopener';
      const title=make('h3');title.append(link);
      text.append(title,make('p',station.address||'','small'),make('p',`${station.miles} mi away${station.updated?` · price updated ${localTime(station.updated)}`:''}`,'small'));
      item.append(make('div',`$${station.price.toFixed(2)}`,'price'),text);items.append(item);
    }
    this.shadowRoot.querySelector('#checked').textContent=`Regular unleaded · straight-line distance · Checked ${localTime(g?.attributes.checked_at)} · Refreshes hourly`;
  }
}
if(!customElements.get('gas-prices-card'))customElements.define('gas-prices-card',GasPricesCard);

// High/low predictions joined by half-cosines, the usual tide-table curve.
const tideAt=(tides,time)=>{
  const next=tides.findIndex(t=>t.time>time);
  if(next<1)return null;
  const a=tides[next-1], b=tides[next], f=(time-a.time)/(b.time-a.time);
  return a.v+(b.v-a.v)*(1-Math.cos(Math.PI*f))/2;
};
function tideChart(raw,timeZone){
  const tides=raw.map(t=>({...t,time:Date.parse(t.t)})), now=Date.now(), start=now-3*3600000, end=start+24*3600000;
  const points=[];
  for(let time=start;time<=end;time+=600000){const v=tideAt(tides,time);if(v!==null)points.push([time,v]);}
  if(points.length<2)return null;
  const values=points.map(p=>p[1]), low=Math.min(...values)-0.3, high=Math.max(...values)+0.3;
  const W=320,H=96,x=time=>((time-start)/(end-start)*W).toFixed(1),y=v=>(8+(high-v)/(high-low)*(H-30)).toFixed(1);
  const clock=time=>new Date(time).toLocaleTimeString(undefined,{timeZone,hour:'numeric',minute:'2-digit'});
  const line=points.map(([t,v],i)=>`${i?'L':'M'}${x(t)},${y(v)}`).join('');
  const marks=tides.filter(t=>t.time>=start && t.time<=end).map(t=>`<circle cx="${x(t.time)}" cy="${y(t.v)}" r="3" fill="#9fd3ff"/><text x="${x(t.time)}" y="${t.type==='H'?Number(y(t.v))-6:Number(y(t.v))+14}" text-anchor="middle">${t.type==='H'?'High':'Low'} ${t.v.toFixed(1)} ft</text><text x="${x(t.time)}" y="${H-2}" text-anchor="middle" class="axis">${clock(t.time)}</text>`).join('');
  return `<svg viewBox="0 -4 ${W} ${H+4}" role="img" aria-label="Tide chart for the next 21 hours"><path d="${line}L${x(points.at(-1)[0])},${H-14}L${x(points[0][0])},${H-14}Z" fill="#9fd3ff22"/><path d="${line}" fill="none" stroke="#9fd3ff" stroke-width="2"/><line x1="${x(now)}" x2="${x(now)}" y1="0" y2="${H-14}" stroke="#ffb56b" stroke-dasharray="3 3"/>${marks}</svg>`;
}

// Drive time, temperatures and tides for the beach day trips.
class DaytripCard extends HTMLElement {
  constructor(){super();this.attachShadow({mode:'open'});}
  setConfig(config){this.config=config;this.toggleAttribute('hide-title',!!config.hide_title);}
  getCardSize(){return 6;}
  getGridOptions(){return {columns:12,rows:'auto'};}
  set hass(hass){
    const trip=hass.states[this.config?.entity || 'sensor.daytrip'];
    this.timeZone=hass.config.time_zone;
    if(this.trip===trip && this.rendered)return;
    this.trip=trip;this.rendered=true;this.render();
  }
  connectedCallback(){this.timer=setInterval(()=>this.trip&&this.render(),300000);}
  disconnectedCallback(){clearInterval(this.timer);}
  render(){
    const trip=this.trip, degrees=v=>v===null||v===undefined?'—':`${Math.round(v)}°F`;
    this.shadowRoot.innerHTML=`<style>${TILE_STYLE}.place{border:1px solid #ffffff40;border-left:5px solid #9fd3ff;border-radius:8px;padding:12px 14px;margin:10px 0}
      h3{font-size:19px;margin:0 0 8px}.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.value{font-size:20px}
      svg{display:block;width:100%;height:auto;margin-top:10px;overflow:visible}svg text{fill:var(--primary-text-color);font-size:9px}svg .axis{opacity:.75}svg .now{fill:#ffb56b}</style>
      <ha-card><h2>Daytrip</h2><div id="items"></div><div class="checked" id="checked"></div></ha-card>`;
    const items=this.shadowRoot.querySelector('#items');
    if(!trip || trip.state!=='ok')items.append(make('p','Day trip conditions are unavailable right now.','small'));
    for(const place of trip?.attributes.destinations || []){
      const section=make('section',undefined,'place'), stats=make('div',undefined,'stats');
      const stat=(label,value,note)=>{const cell=make('div');cell.append(make('div',label,'label'),make('div',value,'value'));if(note)cell.append(make('div',note,'small'));stats.append(cell);};
      const driveNote=place.errors?.drive==='needs_key'?'Needs Google key':place.errors?.drive?.includes('PERMISSION_DENIED')?'Enable Routes API':place.drive_miles?`${place.drive_miles} mi, with traffic`:'Unavailable';
      stat('Drive',place.drive_minutes===null?'—':place.drive_minutes>=60?`${Math.floor(place.drive_minutes/60)} h ${place.drive_minutes%60} min`:`${place.drive_minutes} min`,driveNote);
      stat('Air',degrees(place.air_temp),place.air_high===null?'':`High ${degrees(place.air_high)}`);
      stat('Water',degrees(place.water_temp),'Sea surface');
      section.append(make('h3',`${place.name} · ${place.place}`),stats);
      const chart=tideChart(place.tides||[],this.timeZone);
      if(chart){
        const holder=make('div'), tides=place.tides.map(t=>({...t,time:Date.parse(t.t)})), now=Date.now(), next=tides.find(t=>t.time>now), level=tideAt(tides,now);
        const clock=time=>new Date(time).toLocaleTimeString(undefined,{timeZone:this.timeZone,hour:'numeric',minute:'2-digit'});
        holder.innerHTML=chart;
        section.append(holder,make('div',`Now ${level.toFixed(1)} ft, ${next.type==='H'?'rising':'falling'} · ${next.type==='H'?'High':'Low'} ${next.v.toFixed(1)} ft at ${clock(next.time)}`,'small'),
          make('div',`Tides: NOAA ${place.tide_name} predictions, feet above MLLW`,'small'));
      }
      else section.append(make('p','Tide predictions unavailable.','small'));
      items.append(section);
    }
    this.shadowRoot.querySelector('#checked').textContent=`Checked ${localTime(trip?.attributes.checked_at)} · Refreshes every 20 minutes · Temperatures: Open-Meteo`;
  }
}
if(!customElements.get('daytrip-card'))customElements.define('daytrip-card',DaytripCard);

// California ISO grid status, demand against today's peak, and the fuel mix.
const FUELS=[['Solar','currentSolar','#ffe28a'],['Wind','currentWind','#9dd3a8'],['Batteries','currentBatteries','#d7a9ff'],['Hydro','currentLargeHydro','#9fd3ff'],
  ['Geothermal & bio','',"#c9a27b"],['Nuclear','currentNuclear','#ff9fc8'],['Natural gas','currentNaturalGas','#ffb56b'],['Imports','currentImports','#aaaaaa']];
class GridCard extends HTMLElement {
  constructor(){super();this.attachShadow({mode:'open'});}
  setConfig(config){this.config=config;this.toggleAttribute('hide-title',!!config.hide_title);}
  getCardSize(){return 4;}
  getGridOptions(){return {columns:12,rows:'auto'};}
  set hass(hass){
    const grid=hass.states[this.config?.entity || 'sensor.caiso_grid'];
    if(this.grid===grid && this.rendered)return;
    this.grid=grid;this.rendered=true;this.render();
  }
  render(){
    const g=this.grid, a=g?.attributes || {}, gw=v=>Number.isFinite(v)?`${(v/1000).toFixed(1)} GW`:'—';
    this.shadowRoot.innerHTML=`<style>${TILE_STYLE}.bar{display:flex;height:18px;border-radius:5px;overflow:hidden;margin:14px 0 8px}.legend{display:flex;flex-wrap:wrap;gap:6px 14px;font-size:13px}.legend span:before{content:'';display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px;background:var(--c)}</style>
      <ha-card><h2>California grid</h2><div class="grid" id="items"></div><div class="bar" id="bar" role="img"></div><div class="legend" id="legend"></div><div class="checked" id="checked"></div></ha-card>`;
    const items=this.shadowRoot.querySelector('#items');
    const tile=(label,value,note,color)=>{const item=make('section',undefined,'item');if(color)item.style.borderLeftColor=color;item.append(make('div',label,'label'),make('div',value,'value'));if(note)item.append(make('div',note,'small'));items.append(item);};
    const live=g && !['unavailable','unknown'].includes(g.state);
    tile('Grid status',live?g.state:'Unavailable',live&&g.state==='Normal'?'No Flex Alert or emergency':live?'Check CAISO for details':'CAISO feed unreachable',!live?'#aaa':g.state==='Normal'?'#9dd3a8':'#ff7b7b');
    const peakTime=a.todayForecastPeakDemandTS?`${Number(a.todayForecastPeakDemandTS.slice(8,10))%12||12}${Number(a.todayForecastPeakDemandTS.slice(8,10))<12?' AM':' PM'}`:'';
    tile('Demand now',gw(a.CurrentSystemDemand),Number.isFinite(a.todayForecastPeakDemand)?`Peak ${gw(a.todayForecastPeakDemand)}${peakTime?` around ${peakTime}`:''}`:'');
    const supply=FUELS.map(([label,key,color])=>[label,key?a[key]:[a.currentGeothermal,a.currentBiomass,a.currentBiogas,a.currentSmallHydro].reduce((x,y)=>x+(y||0),0),color]).filter(([,v])=>v>0);
    const total=supply.reduce((x,[,v])=>x+v,0);
    tile('Renewables',total&&Number.isFinite(a.currentRenewables)?`${Math.round(a.currentRenewables/total*100)}%`:'—',`Reserve ${gw(a.Current_reserve)}`);
    const bar=this.shadowRoot.querySelector('#bar'), legend=this.shadowRoot.querySelector('#legend');
    bar.setAttribute('aria-label','Current supply by source');
    for(const [label,value,color] of supply){
      const part=make('div');part.style.cssText=`width:${value/total*100}%;background:${color}`;part.title=`${label} ${gw(value)}`;bar.append(part);
      const key=make('span',`${label} ${Math.round(value/total*100)}%`);key.style.setProperty('--c',color);legend.append(key);
    }
    this.shadowRoot.querySelector('#checked').textContent=`CAISO Today's Outlook · ${a.slotDate?`${a.slotDate} Pacific`:'not checked yet'} · Batteries count only while discharging`;
  }
}
if(!customElements.get('grid-card'))customElements.define('grid-card',GridCard);

// US-101 and SR-23 message signs, lane closures and the nearest cameras (Caltrans D7).
const ROUTE_NAMES={'US-101':'101','SR-23':'23'};
class FreewayCard extends HTMLElement {
  constructor(){super();this.attachShadow({mode:'open'});}
  setConfig(config){this.config=config;this.toggleAttribute('hide-title',!!config.hide_title);}
  getCardSize(){return 8;}
  getGridOptions(){return {columns:12,rows:'auto'};}
  set hass(hass){
    const road=hass.states[this.config?.entity || 'sensor.freeway_conditions'];
    if(this.road===road && this.rendered)return;
    this.road=road;this.rendered=true;this.render();
  }
  // Camera stills update about every 2 minutes; reload them on that cadence.
  connectedCallback(){this.timer=setInterval(()=>this.shadowRoot.querySelectorAll('img').forEach(img=>{img.src=`${img.dataset.src}?t=${Date.now()}`;}),120000);}
  disconnectedCallback(){clearInterval(this.timer);}
  render(){
    const r=this.road, a=r?.attributes || {}, errors=a.errors || {};
    this.shadowRoot.innerHTML=`<style>${TILE_STYLE}h3{font-size:17px;margin:16px 0 6px}.item{margin:8px 0}.sign{border-left-color:#ffb56b;font-family:monospace;font-size:15px;line-height:1.4}.in-place{border-left-color:#ff7b7b}.scheduled{border-left-color:#d7a9ff}
      .cams{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}.cams figure{margin:0}.cams img{display:block;width:100%;aspect-ratio:4/3;object-fit:cover;border-radius:6px;background:#00000040}figcaption{font-size:13px;margin-top:4px;opacity:.85}summary{cursor:pointer;font-size:15px;margin:16px 0 6px;font-weight:600}.links{display:flex;flex-wrap:wrap;gap:14px;margin-top:14px}</style>
      <ha-card><h2>Freeways: 101 & 23</h2><div id="items"></div><div class="links"><a href="https://quickmap.dot.ca.gov/" target="_blank" rel="noopener">Caltrans QuickMap ↗</a></div><div class="checked" id="checked"></div></ha-card>`;
    const items=this.shadowRoot.querySelector('#items'), small=text=>items.append(make('p',text,'small'));
    if(!r || r.state!=='ok'){small('Caltrans feeds are unavailable right now.');}
    else {
      const route=c=>`${ROUTE_NAMES[c.route]||c.route} ${c.direction||''}`.trim();
      items.append(make('h3','Message signs'));
      if(errors.signs)small(`Sign feed unavailable (${errors.signs}).`);
      else if(!a.signs.length)small('All message signs on the 101 and 23 are blank.');
      for(const sign of a.signs){const item=make('section',undefined,'item sign');item.append(make('div',`${route(sign)} · ${sign.location}`,'label'));for(const line of sign.message)item.append(make('div',line));items.append(item);}
      const closure=(c,cls)=>{
        const item=make('section',undefined,`item ${cls}`), what=c.type==='Full'?`Full ${c.facility.toLowerCase()} closure`:`Lane${c.lanes.includes(',')?'s':''} ${c.lanes} of ${c.total_lanes} closed`;
        item.append(make('div',`${route(c)} · ${c.from}${c.to?` → ${c.to}`:''}`,'label'),make('div',what,'value'),
          make('div',[c.work,`${localTime(c.start)} – ${c.end?localTime(c.end):'until further notice'}`,c.delay&&c.delay!=='Not Reported'?`Delay ${c.delay}`:''].filter(Boolean).join(' · '),'small'));
        items.append(item);
      };
      items.append(make('h3','Closures in place now'));
      if(errors.closures)small(`Closure feed unavailable (${errors.closures}).`);
      else if(!a.in_place.length)small('No crews reported on scene.');
      a.in_place?.forEach(c=>closure(c,'in-place'));
      if(!errors.closures){
        const details=make('details'), summary=make('summary',`Scheduled now or within 24 hours: ${a.scheduled_count} (not confirmed)`);
        details.append(summary);items.append(details);
        if(!a.scheduled.length)small('None scheduled.');
        a.scheduled.slice(0,5).forEach(c=>closure(c,'scheduled'));
        if(a.scheduled_count>5)small(`+${a.scheduled_count-5} more on QuickMap. Scheduled closures often don't happen.`);
        // Move what was just added into the collapsible list.
        while(details.nextSibling)details.append(details.nextSibling);
      }
      if(a.cameras?.length){
        items.append(make('h3','Cameras near home'));
        const cams=make('div',undefined,'cams');
        for(const cam of a.cameras){
          const figure=make('figure'), link=make('a'), img=make('img');
          img.dataset.src=cam.image;img.src=`${cam.image}?t=${Date.now()}`;img.alt=`${ROUTE_NAMES[cam.route]} at ${cam.name}`;img.loading='lazy';
          link.href=cam.image;link.target='_blank';link.rel='noopener';link.append(img);
          figure.append(link,make('figcaption',`${ROUTE_NAMES[cam.route]} ${cam.direction} · ${cam.name} · ${cam.miles} mi`));cams.append(figure);
        }
        items.append(cams);
      }
    }
    this.shadowRoot.querySelector('#checked').textContent=`Caltrans District 7 · Checked ${localTime(a.checked_at)} · Refreshes every 10 minutes · "In place" means crews logged on scene`;
  }
}
if(!customElements.get('freeway-card'))customElements.define('freeway-card',FreewayCard);

// Active Ventura County Fire and EMS calls; fires first, then nearest.
class FireIncidentsCard extends HTMLElement {
  constructor(){super();this.attachShadow({mode:'open'});}
  setConfig(config){this.config=config;this.toggleAttribute('hide-title',!!config.hide_title);}
  getCardSize(){return 4;}
  getGridOptions(){return {columns:12,rows:'auto'};}
  set hass(hass){
    const fire=hass.states[this.config?.entity || 'sensor.fire_incidents'];
    if(this.fire===fire && this.rendered)return;
    this.fire=fire;this.rendered=true;this.render();
  }
  render(){
    const f=this.fire, a=f?.attributes || {}, limit=this.config?.limit || 3;
    // Feed times are Pacific wall-clock strings (YYYY-MM-DDTHH:MM).
    const clock=value=>{if(!value)return '';const [h,m]=value.slice(11,16).split(':').map(Number);return `${h%12||12}:${String(m).padStart(2,'0')} ${h<12?'AM':'PM'}`;};
    this.shadowRoot.innerHTML=`<style>${TILE_STYLE}.item{margin:6px 0;padding:8px 12px;border-left-color:#9fd3ff}.item.fire{border-left-color:#ff7b7b;background:#ff7b7b18}.value{font-size:16px;margin:0 0 2px}.summary{margin:0 0 4px}</style>
      <ha-card><h2>Active fires</h2><div id="items"></div><div class="links" style="margin-top:12px"><a href="https://fire.venturacounty.gov/pulsepoint-active-calls" target="_blank" rel="noopener">VCFD active calls ↗</a></div><div class="checked" id="checked"></div></ha-card>`;
    const items=this.shadowRoot.querySelector('#items');
    const fires=(a.incidents||[]).filter(i=>i.fire);
    if(!f || !Number.isFinite(Number(f.state))){items.append(make('p','Ventura County Fire incident feed unavailable.','small'));}
    else {
      items.append(make('p',`${a.fires} active fire${a.fires===1?'':'s'} in Ventura County`,'summary'));
      for(const incident of fires.slice(0,limit)){
        const item=make('section',undefined,`item ${incident.fire?'fire':''}`);
        item.append(make('div',`${incident.type} · ${incident.city||''}${incident.miles!==null?` · ${incident.miles} mi`:''}`,'value'),
          make('div',[incident.address,incident.status,incident.responded?`since ${clock(incident.responded)}`:''].filter(Boolean).join(' · '),'small'));
        items.append(item);
      }
      if(fires.length>limit)items.append(make('p',`+${fires.length-limit} more on the VCFD page.`,'small'));
    }
    this.shadowRoot.querySelector('#checked').textContent=`Ventura County Fire Department · Checked ${localTime(a.checked_at)} · Refreshes every 10 minutes`;
  }
}
if(!customElements.get('fire-incidents-card'))customElements.define('fire-incidents-card',FireIncidentsCard);

// Host health: sensor.raspberry_pi is the HA host (read inside the HA container;
// the id predates HA moving off the Pi), sensor.pi_health the Pi when it is
// another machine (pushed by cron). `name` labels the card above its tiles.
class PiHealthCard extends HTMLElement {
  constructor(){super();this.attachShadow({mode:'open'});}
  setConfig(config){this.config=config;this.toggleAttribute('hide-title',!!config.hide_title);}
  getCardSize(){return 3;}
  getGridOptions(){return {columns:12,rows:'auto'};}
  set hass(hass){
    const pi=hass.states[this.config?.entity || 'sensor.raspberry_pi'];
    if(this.pi===pi && this.rendered)return;
    this.pi=pi;this.rendered=true;this.render();
  }
  render(){
    const a=this.pi?.attributes||{}, ok=this.pi?.state==='ok' && fresh(a.checked_at,this.config?.fresh_minutes||65);
    // Thresholds: Pi 3 soft-throttles at 80°C; heavy swap on 1 GB means memory pressure.
    const level=(v,warn,bad)=>v===null||v===undefined?'#aaa':v>=bad?'#ff7b7b':v>=warn?'#ffb56b':'#9dd3a8';
    this.shadowRoot.innerHTML=`<style>${TILE_STYLE}.grid{grid-template-columns:repeat(2,1fr)}.value{font-size:19px}.name{font-weight:600;margin:0 0 10px}</style><ha-card><h2>Device Health</h2><div class="name" id="name"></div><div class="grid" id="items"></div><div class="checked" id="checked"></div></ha-card>`;
    const name=this.shadowRoot.querySelector('#name');
    if(this.config?.name)name.textContent=this.config.name;else name.remove();
    const items=this.shadowRoot.querySelector('#items');
    const tile=(label,value,note,color)=>{const item=make('section',undefined,'item');item.style.borderLeftColor=color;item.append(make('div',label,'label'),make('div',value,'value'));if(note)item.append(make('div',note,'small'));items.append(item);};
    if(!ok){items.append(make('p','Device status unavailable.','small'));return;}
    tile('CPU',`${Math.round(a.cpu_percent)}%`,`Load ${a.load.map(v=>v.toFixed(2)).join(' ')}`,level(a.load[0]/a.cpu_count*100,75,100));
    tile('Temperature',`${Math.round(a.temperature_c)}°C`,a.undervoltage?'Undervoltage detected':a.undervoltage===null?'':'Power OK',a.undervoltage?'#ff7b7b':level(a.temperature_c,70,80));
    const size=mb=>mb>=1024?`${(mb/1024).toFixed(1)} GB`:`${mb} MB`;
    tile('Memory',`${Math.round(a.memory_percent)}%`,`${size(a.memory_available_mb)} free of ${size(a.memory_total_mb)} · swap ${Math.round(a.swap_percent??0)}%`,level(Math.max(a.memory_percent,a.swap_percent??0),70,85));
    tile(a.undervoltage===null?'Disk':'SD card',`${Math.round(a.disk_percent)}%`,`${a.disk_free_gb} GB free${a.database_mb!==null?` · HA database ${a.database_mb} MB`:''}`,level(a.disk_percent,75,90));
    const b=a.battery;
    if(b)tile('Battery',`${b.percent}%`,[b.ac_online===false?'On battery':'On AC',b.health_percent?`health ${b.health_percent}%`:'',b.cycles?`${b.cycles} cycles`:''].filter(Boolean).join(' · '),b.ac_online===false?'#ffb56b':level(100-(b.health_percent??100),50,70));
    const days=Math.floor(a.uptime_hours/24);
    this.shadowRoot.querySelector('#checked').textContent=`${a.host?`${a.host} · `:''}Up ${days?`${days} d `:''}${Math.round(a.uptime_hours%24)} h · Checked ${localTime(a.checked_at)} · every ${this.config?.every||'30 minutes'}`;
  }
}
if(!customElements.get('pi-health-card'))customElements.define('pi-health-card',PiHealthCard);

// Baby care suggestions from today's conditions. General AAP/CDC guidance, not
// medical advice. BabySteps care status joins this when HA can read it.
class BabyCareCard extends HTMLElement {
  constructor(){super();this.attachShadow({mode:'open'});}
  setConfig(config){this.config=config;this.toggleAttribute('hide-title',!!config.hide_title);}
  getCardSize(){return 6;}
  getGridOptions(){return {columns:12,rows:'auto'};}
  set hass(hass){
    this.hassRef=hass;
    const watched=[this.config.weather_entity,'sensor.local_air_quality','sensor.nws_observation','sensor.purpleair','sensor.local_weather_alerts','sensor.fire_incidents','sensor.babysteps_status'].map(id=>hass.states[id]);
    if(!this.forecastAt || Date.now()-this.forecastAt>1800000)this.loadForecast();
    if(this.rendered && watched.every((state,i)=>state===this.watched[i]))return;
    this.watched=watched;this.rendered=true;this.render();
  }
  // Today's high/low and the day's peak UV come from the forecast service.
  async loadForecast(){
    this.forecastAt=Date.now();
    const ask=type=>this.hassRef.callWS({type:'call_service',domain:'weather',service:'get_forecasts',service_data:{type},target:{entity_id:this.config.weather_entity},return_response:true})
      .then(r=>r.response[this.config.weather_entity]?.forecast||[]).catch(()=>[]);
    const [daily,hourly]=await Promise.all([ask('daily'),ask('hourly')]);
    const hourOf=h=>Number(new Intl.DateTimeFormat('en-US',{timeZone:this.hassRef.config.time_zone,hour:'numeric',hourCycle:'h23'}).format(new Date(h.datetime)));
    const next12=hourly.filter(h=>new Date(h.datetime)-Date.now()<12*3600000);
    const night=hourly.filter(h=>new Date(h.datetime)-Date.now()<24*3600000 && (hourOf(h)>=21 || hourOf(h)<7));
    this.forecast={high:daily[0]?.temperature,low:daily[0]?.templow,tonightLow:night.length?Math.min(...night.map(h=>h.temperature)):daily[0]?.templow,
      uvMax:next12.some(h=>h.uv_index!==undefined)?Math.max(...next12.map(h=>h.uv_index??0)):undefined};
    this.render();
  }
  render(){
    const hass=this.hassRef, r=homeReadings(hass,this.config.weather_entity), f=this.forecast||{}, unit=r.unit, deg=v=>`${Math.round(v)}${unit}`;
    const F=v=>v===undefined||v===null?undefined:unit==='°F'?v:v*9/5+32;
    const tips=[];
    const tip=(icon,title,text,level='info')=>tips.push({icon,title,text,level});
    const alerts=(hass.states['sensor.local_weather_alerts']?.attributes.alerts||[]).filter(a=>!a.expires||new Date(a.expires)>Date.now());
    for(const alert of alerts)tip('⚠️',alert.event,'A weather warning is active for home. Plan outings around it; see Weather & power warnings above.','warn');
    const high=F(f.high)??F(r.temperature), low=F(f.tonightLow??f.low);
    if(high>=95)tip('🥵',`Extreme heat (high ${deg(f.high)})`,'Stay indoors in the cool hours of the afternoon. Dress baby in one light layer, feed on demand and watch for fewer wet diapers. Babies under 6 months get fluids from breast milk or formula, not water. Never leave a child in a parked car.','warn');
    else if(high>=85)tip('☀️',`Hot day (high ${deg(f.high)})`,'Light, loose cotton and shade. Offer feeds more often; under 6 months, breast milk or formula is all the fluid they need. Check the car seat for hot buckles, and never leave baby in a parked car.','warn');
    const aqi=r.aqi;
    if(aqi>150)tip('😷',`Unhealthy air (AQI ${Math.round(aqi)})`,'Keep baby indoors with windows closed; run an air purifier if you have one. Infants are a sensitive group.','warn');
    else if(aqi>100)tip('😷',`Air is unhealthy for sensitive groups (AQI ${Math.round(aqi)})`,'Infants count as sensitive. Keep outdoor time short and gentle, and avoid busy roads.','warn');
    const uv=f.uvMax??r.uv;
    if(uv>=3)tip('🧢',`UV peaks at ${Math.round(uv)} today`,'Keep babies under 6 months out of direct sun: shade, a wide-brim hat, light long sleeves. If shade isn\'t possible, a small amount of SPF 15+ on small areas like the face is OK. Older babies: sunscreen 15 minutes before going out.','info');
    const fires=(hass.states['sensor.fire_incidents']?.attributes.incidents||[]).filter(i=>i.fire && i.miles!==null && i.miles<=5);
    if(fires.length)tip('🔥',`Fire call ${fires[0].miles} mi away`,'If you smell smoke, bring baby inside and close windows and doors.','warn');
    if(low<=50)tip('🧣',`Chilly (down to ${deg(f.tonightLow??f.low)})`,'Outdoors, dress baby in one more layer than you\'re wearing, plus a hat. Keep blankets off the car seat harness; put them over the buckled straps instead.','info');
    const pleasant=high>=60 && high<85 && !(aqi>100) && !alerts.length;
    if(pleasant)tip('🚼','Good weather for a walk',uv>=6?'Best before 10 AM or after 4 PM, when UV is lower.':'Comfortable for a stroller walk or time outside in the shade.','good');
    tip('🌙',`Sleep tonight${low!==undefined?` (outside low ${deg(f.tonightLow??f.low)})`:''}`,'Back to sleep, on a firm flat surface with no loose blankets or bumpers; use a sleep sack for warmth. Dress baby in no more than one layer more than you\'d wear indoors, and check the back of the neck: sweaty means too warm.','info');
    const status=hass.states['sensor.babysteps_status'];
    this.shadowRoot.innerHTML=`<style>${TILE_STYLE}.tip{display:flex;gap:12px;align-items:flex-start;border:1px solid #ffffff40;border-left:5px solid #9fd3ff;border-radius:8px;padding:10px 12px;margin:8px 0}.tip.warn{border-left-color:#ffb56b}.tip.good{border-left-color:#9dd3a8}.icon{font-size:22px;line-height:1}h3{font-size:17px;margin:0 0 3px}p{margin:0;font-size:14px;line-height:1.45}.care{margin-bottom:6px}</style>
      <ha-card><h2>Baby care</h2><div id="care" class="care"></div><div id="tips"></div><div class="checked">General guidance from the AAP and CDC, not medical advice. Call your pediatrician with any concerns. <a href="https://www.healthychildren.org/" target="_blank" rel="noopener">HealthyChildren.org ↗</a></div></ha-card>`;
    const care=this.shadowRoot.querySelector('#care');
    if(status?.state==='ok'){
      const a=status.attributes, ago=t=>{if(!t)return '—';const m=Math.round((Date.now()-new Date(t))/60000);return m<60?`${m} min ago`:`${Math.floor(m/60)} h ${m%60} min ago`;};
      care.append(make('p',`${a.child}: fed ${ago(a.lastFeed?.at)} · diaper ${ago(a.lastDiaper?.at)} · ${a.lastSleep&&!a.lastSleep.endedAt?`asleep since ${ago(a.lastSleep.at)}`:`awake since ${ago(a.lastSleep?.endedAt)}`}`,'small'));
    } else care.append(make('p','Feeds, diapers and sleep will show here once Home Assistant is connected to the new BabySteps server.','small'));
    const box=this.shadowRoot.querySelector('#tips');
    for(const t of tips){const row=make('section',undefined,`tip ${t.level}`), body=make('div');row.append(make('div',t.icon,'icon'));body.append(make('h3',t.title),make('p',t.text));row.append(body);box.append(row);}
  }
}
if(!customElements.get('baby-care-card'))customElements.define('baby-care-card',BabyCareCard);

// A family recipe: the same pick all day (seeded by date), with Shuffle.
class RecipeCard extends HTMLElement {
  constructor(){super();this.attachShadow({mode:'open'});}
  setConfig(config){this.config=config;this.toggleAttribute('hide-title',!!config.hide_title);}
  getCardSize(){return 5;}
  getGridOptions(){return {columns:12,rows:'auto'};}
  set hass(_hass){if(!this.loading){this.loading=true;this.load();}}
  async load(){
    try{this.recipes=await (await fetch('/local/recipes/recipes.json',{cache:'no-cache'})).json();}catch{this.recipes=[];}
    const today=new Date().toLocaleDateString('en-CA'), seed=[...today].reduce((h,c)=>(h*31+c.charCodeAt(0))>>>0,7);
    this.index=this.recipes.length?seed%this.recipes.length:0;this.render();
  }
  shuffle(){if(this.recipes.length<2)return;let next;do next=Math.floor(Math.random()*this.recipes.length);while(next===this.index);this.index=next;this.render();}
  open(path){history.pushState(null,'',path);window.dispatchEvent(new CustomEvent('location-changed',{detail:{replace:false}}));}
  render(){
    const recipe=this.recipes?.[this.index];
    this.shadowRoot.innerHTML=`<style>${TILE_STYLE}img{display:block;width:100%;aspect-ratio:2/1;object-fit:cover;border-radius:8px;background:#00000040;cursor:pointer}h3{font-size:22px;margin:12px 0 4px}h3 a{text-decoration:none}.row{display:flex;gap:10px;margin-top:12px;flex-wrap:wrap}
      button{font:inherit;font-size:15px;padding:8px 16px;border-radius:18px;border:1px solid var(--primary-text-color);background:transparent;color:var(--primary-text-color);cursor:pointer}button.primary{background:#ffb56b;color:#000;border-color:#ffb56b}button:focus-visible{outline:2px solid currentColor;outline-offset:2px}</style>
      <ha-card><h2>Recipe of the day</h2><div id="body"></div></ha-card>`;
    const body=this.shadowRoot.querySelector('#body');
    if(!recipe){body.append(make('p','Recipe index unavailable. Reinstall the recipe book.','small'));return;}
    const path=`/family-recipes/${recipe.path}`, img=make('img'), title=make('h3'), link=make('a',recipe.title), row=make('div',undefined,'row');
    img.src=`/local/recipes/${recipe.path}.jpg`;img.alt=`Example photo of ${recipe.title}`;
    link.href=path;title.append(link);
    for(const el of [img,link])el.addEventListener('click',event=>{event.preventDefault();this.open(path);});
    const open=make('button','Open recipe','primary'), again=make('button','Shuffle');
    open.addEventListener('click',()=>this.open(path));again.addEventListener('click',()=>this.shuffle());
    row.append(open,again);
    body.append(img,title,make('div',`Example photo · ${recipe.credit} · ${this.recipes.length} family recipes`,'small'),row);
  }
}
if(!customElements.get('recipe-card'))customElements.define('recipe-card',RecipeCard);

// USGS earthquakes near home in the last 24 hours; shown only when there are any.
class EarthquakeCard extends HTMLElement {
  constructor(){super();this.attachShadow({mode:'open'});}
  setConfig(config){this.config=config;this.toggleAttribute('hide-title',!!config.hide_title);}
  getCardSize(){return 3;}
  getGridOptions(){return {columns:12,rows:'auto'};}
  set hass(hass){
    const quakes=hass.states[this.config?.entity || 'sensor.earthquakes'];
    if(this.quakes===quakes && this.rendered)return;
    this.quakes=quakes;this.rendered=true;this.render();
  }
  render(){
    const a=this.quakes?.attributes||{};
    const ago=t=>{const m=Math.round((Date.now()-new Date(t))/60000);return m<60?`${m} min ago`:m<1440?`${Math.floor(m/60)} h ago`:localTime(t);};
    const color=m=>m>=5?'#ff7b7b':m>=4?'#ffb56b':'#ffe28a';
    this.shadowRoot.innerHTML=`<style>${TILE_STYLE}.item{display:flex;gap:14px;align-items:center;margin:6px 0;padding:8px 12px}.mag{font-size:24px;font-weight:600;min-width:52px}h3{font-size:16px;margin:0 0 2px}a{text-decoration:none}</style>
      <ha-card><h2>Earthquakes</h2><div id="items"></div><div class="checked" id="checked"></div></ha-card>`;
    const items=this.shadowRoot.querySelector('#items');
    for(const q of (a.quakes||[]).slice(0,4)){
      const item=make('section',undefined,'item'), text=make('div'), title=make('h3'), link=make('a',q.place);
      item.style.borderLeftColor=color(q.magnitude);link.href=q.url;link.target='_blank';link.rel='noopener';title.append(link);
      text.append(title,make('div',`${q.miles} mi away · ${ago(q.time)}${q.depth_km!==null?` · ${q.depth_km} km deep`:''}${q.felt?` · ${q.felt} felt reports`:''}`,'small'));
      item.append(make('div',`M${q.magnitude.toFixed(1)}`,'mag'),text);items.append(item);
    }
    this.shadowRoot.querySelector('#checked').textContent=`USGS · M2.5+ within 50 mi · ${a.week_count??'—'} this week · M4.0+ is announced on the tablet`;
  }
}
if(!customElements.get('earthquake-card'))customElements.define('earthquake-card',EarthquakeCard);

// Today's timeline: BabySteps entries, sunrise/sunset and the evening routine.
// Routine times are home-local; bath shows when 3+ days have passed since the last one.
// `end` makes a span (highlighted while under way); `days` limits it to weekdays (0 = Sunday).
const ROUTINE=[
  {time:'05:00',icon:'⏰',text:'Wake up'},
  {time:'05:00',end:'08:30',icon:'👨',text:'Dad time'},
  {time:'08:30',icon:'🍳',text:'Breakfast'},
  {time:'08:30',end:'15:30',icon:'💼',text:'Work time',days:[1,2,3,4,5]},
  {time:'12:30',icon:'🥪',text:'Lunch'},
  {time:'17:30',icon:'🍽️',text:'Dinner'},
  {time:'19:00',icon:'🛁',text:'Bath time',bath:true},
  {time:'19:30',icon:'🐕',text:'Let the dog out'},
  {time:'20:00',icon:'🌙',text:"@@CHILD_NAME@@'s bedtime"},
  {time:'20:30',icon:'🌙',text:"Mom's bedtime"},
  {time:'21:00',icon:'🌙',text:"Dad's bedtime"}];
const BABY_ICONS={feed:'🍼',diaper:'🧷',sleep:'😴',bath:'🛁',pump:'🥛',tummy_time:'🧸',mood:'🙂',note:'📝'};
// A wall-clock time today in `timeZone` as a Date (offset taken at that moment).
function zonedTime(day,clock,timeZone){
  const guess=new Date(`${day}T${clock}:00Z`);
  const parts=Object.fromEntries(new Intl.DateTimeFormat('en-US',{timeZone,hourCycle:'h23',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}).formatToParts(guess).map(p=>[p.type,p.value]));
  const shown=Date.UTC(+parts.year,parts.month-1,+parts.day,+parts.hour,+parts.minute);
  return new Date(guess.getTime()-(shown-guess.getTime()));
}
class TodayCard extends HTMLElement {
  constructor(){super();this.attachShadow({mode:'open'});}
  setConfig(config){this.config=config;this.toggleAttribute('hide-title',!!config.hide_title);}
  getCardSize(){return 10;}
  getGridOptions(){return {columns:12,rows:'auto'};}
  set hass(hass){
    this.place=hass.config;
    const watched=['sensor.babysteps_status','sensor.household_schedule','sensor.vandenberg_launches'].map(id=>hass.states[id]);
    if(this.rendered && watched.every((s,i)=>s===this.watched[i]))return;
    this.watched=watched;this.rendered=true;this.render();
  }
  connectedCallback(){this.timer=setInterval(()=>this.place&&this.render(),60000);}
  disconnectedCallback(){clearInterval(this.timer);}
  rows(day,now,timeZone,clock){
    const [b,house,rockets]=this.watched, a=b?.attributes||{}, h=house?.attributes||{}, connected=b?.state==='ok';
    const sun=sunTimes(day,this.place.latitude,this.place.longitude), rows=[];
    if(sun.firstLight)rows.push({at:sun.firstLight,icon:'🌄',text:'First light',note:'Civil dawn'});
    if(sun.sunrise)rows.push({at:sun.sunrise,icon:'🌅',text:'Sunrise'});
    if(sun.sunset)rows.push({at:sun.sunset,icon:'🌇',text:'Sunset'});
    for(const e of connected?a.events||[]:[])rows.push({at:new Date(e.time),icon:BABY_ICONS[e.type]||'•',text:e.text});
    const weekday=['Sun','Mon','Tue','Wed','Thu','Fri','Sat'].indexOf(new Intl.DateTimeFormat('en-US',{timeZone,weekday:'short'}).format(now));
    for(const r of ROUTINE){
      if(r.days && !r.days.includes(weekday))continue;
      if(r.bath && !(connected && (a.days_since_bath===null || a.days_since_bath>=3)))continue;
      const end=r.end?zonedTime(day,r.end,timeZone):null;
      const note=r.bath?(a.days_since_bath===null?'No bath logged yet':`Last bath ${a.days_since_bath} days ago`):end?`until ${clock(end)}`:'';
      rows.push({at:zonedTime(day,r.time,timeZone),end,icon:r.icon,text:r.text,note,routine:true});
    }
    const dayOf=t=>new Intl.DateTimeFormat('en-CA',{timeZone,year:'numeric',month:'2-digit',day:'2-digit'}).format(t);
    for(const launch of rockets?.attributes.launches||[])if(dayOf(new Date(launch.net))===day)
      rows.push({at:new Date(launch.net),icon:'🚀',text:`${launch.rocket} launch`,note:`${launch.mission} · ${(LAUNCH_VIEWS[launch.view]||LAUNCH_VIEWS.day)[0].toLowerCase()}`,routine:true});
    // The evening before trash day or street sweeping, at sunset (as spoken on the tablet).
    if(sun.sunset && h.trash_tomorrow)rows.push({at:sun.sunset,icon:'🗑️',text:'Take the trash out',note:'Pickup tomorrow',routine:true});
    if(sun.sunset && h.sweep_tomorrow)rows.push({at:sun.sunset,icon:'🧹',text:'Check the driveway',note:'Street sweeping tomorrow, 7 AM–7 PM',routine:true});
    return rows.sort((x,y)=>x.at-y.at);
  }
  render(){
    if(!this.place)return;
    const timeZone=this.place.time_zone, now=new Date();
    const day=new Intl.DateTimeFormat('en-CA',{timeZone,year:'numeric',month:'2-digit',day:'2-digit'}).format(now);
    const clock=d=>d.toLocaleTimeString(undefined,{timeZone,hour:'numeric',minute:'2-digit'});
    const rows=this.rows(day,now,timeZone,clock), [b]=this.watched, a=b?.attributes||{};
    // To scale: 4 AM–10 PM, widened to fit anything earlier or later; PX per minute.
    const PX=0.8, GAP=21, hourOf=clock=>zonedTime(day,clock,timeZone);
    let start=hourOf('04:00'), end=hourOf('22:00');
    for(const r of rows){if(r.at<start)start=new Date(Math.floor(r.at/3600000)*3600000);const last=r.end||r.at;if(last>end)end=new Date(Math.ceil(last/3600000)*3600000);}
    const y=t=>(t-start)/60000*PX, height=y(end)+12;
    this.shadowRoot.innerHTML=`<style>${TILE_STYLE}
      .axis{position:relative;height:${height}px;margin-top:4px}
      .hour{position:absolute;left:0;right:0;border-top:1px solid #ffffff14;font-size:11px;opacity:.6;font-variant-numeric:tabular-nums}
      .hour span{position:absolute;top:-7px;background:var(--ha-card-background,var(--card-background-color));padding-right:4px}
      .span{position:absolute;left:52px;width:6px;border-radius:3px;background:#ffb56b88}.span.active{background:#ffb56b}
      .dot{position:absolute;left:62px;width:7px;height:7px;margin-top:-3.5px;border-radius:50%;background:#9fd3ff}.dot.routine{background:#ffb56b}
      .lead{position:absolute;left:69px;width:12px;border-top:1px solid #ffffff40}
      .label{position:absolute;left:82px;right:0;margin-top:-9px;font-size:14px;line-height:18px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      .label .t{font-variant-numeric:tabular-nums;opacity:.75;margin-right:6px;font-size:12px}.label.routine b{font-weight:600}.note{font-size:12px;opacity:.75;margin-left:6px}
      .past{opacity:.45}.now{position:absolute;left:44px;right:0;border-top:2px solid #ffb56b}.now span{position:absolute;left:0;top:-9px;font-size:11px;color:#ffb56b;background:var(--ha-card-background,var(--card-background-color));padding-right:3px}
      .moon{display:flex;gap:10px;align-items:center;margin-bottom:10px}.moon svg{flex:none;width:34px;height:34px}.moon b{font-size:16px}</style>
      <ha-card><h2>Today</h2><div class="moon" id="moon"></div><div class="axis" id="axis"></div><div class="checked" id="checked"></div></ha-card>`;
    // The moon: lit limb plus a terminator ellipse, mirrored when waning.
    const moon=moonPhase(now.getTime()), r=16, rx=r*Math.abs(1-2*moon.illumination), date=d=>d.toLocaleDateString(undefined,{timeZone,weekday:'short',month:'short',day:'numeric'});
    const moonBox=this.shadowRoot.querySelector('#moon'), text=make('div');
    moonBox.innerHTML=`<svg viewBox="-18 -18 36 36" role="img" aria-label="${moon.name}"><circle r="${r}" fill="#ffffff1a" stroke="#ffffff40"/><path d="M0,${-r} A${r},${r} 0 0 1 0,${r} A${rx},${r} 0 0 ${moon.illumination<0.5?0:1} 0,${-r}Z" fill="#f5e6b8"${moon.waxing?'':' transform="scale(-1,1)"'}/></svg>`;
    text.append(make('b',moon.name),make('span',` · ${Math.round(moon.illumination*100)}% lit · ${moon.nextFull<moon.nextNew?`full ${date(moon.nextFull)}`:`new ${date(moon.nextNew)}`}`,'small'));
    moonBox.append(text);
    const axis=this.shadowRoot.querySelector('#axis'), place=(el,top,h)=>{el.style.top=`${top}px`;if(h!==undefined)el.style.height=`${h}px`;axis.append(el);return el;};
    for(let t=new Date(start);t<=end;t=new Date(t.getTime()+3600000)){
      const line=place(make('div',undefined,'hour'),y(t)), hour=Number(new Intl.DateTimeFormat('en-US',{timeZone,hour:'numeric',hourCycle:'h23'}).format(t));
      if(hour%2===0)line.append(make('span',`${hour%12||12} ${hour<12?'AM':'PM'}`));
    }
    for(const r of rows.filter(r=>r.end))place(make('div',undefined,`span ${r.at<=now&&now<r.end?'active':''}`),y(r.at),y(r.end)-y(r.at));
    // Labels sit at their time; a crowded stretch pushes them down, with a leader line back.
    let next=-Infinity;
    for(const r of rows){
      const at=y(r.at), top=Math.max(at,next), done=(r.end||r.at)<=now;
      next=top+GAP;
      place(make('div',undefined,`dot ${r.routine?'routine':''} ${done?'past':''}`),at);
      if(top-at>1){const lead=place(make('div',undefined,'lead'),at,0);lead.style.height=`${top-at}px`;lead.style.borderLeft='1px solid #ffffff40';lead.style.borderTop='none';lead.style.left='65px';lead.style.width='0';}
      const label=place(make('div',undefined,`label ${r.routine?'routine':''} ${done?'past':''}`),top);
      label.append(make('span',clock(r.at),'t'),make('span',`${r.icon} `),make('b',r.text));
      if(r.note)label.append(make('span',r.note,'note'));
      // Keep the axis tall enough for labels pushed past its end.
      if(next>height)axis.style.height=`${next}px`;
    }
    if(now>=start && now<=end){const line=place(make('div',undefined,'now'),y(now));line.append(make('span',clock(now)));}
    this.shadowRoot.querySelector('#checked').textContent=b?.state==='ok'?`BabySteps: ${a.child?`${a.child}, `:''}${a.event_count} entr${a.event_count===1?'y':'ies'} today · checked ${localTime(a.checked_at)}`:
      b?.state==='not_connected'?'BabySteps: Home Assistant is not connected yet':'BabySteps: unavailable';
  }
}
if(!customElements.get('today-card'))customElements.define('today-card',TodayCard);

// Internet health from sensor.internet (checked from the Pi every 30 minutes),
// with the share of the last 24 hours spent online from HA's history.
class InternetCard extends HTMLElement {
  constructor(){super();this.attachShadow({mode:'open'});}
  setConfig(config){this.config=config;this.toggleAttribute('hide-title',!!config.hide_title);}
  getCardSize(){return 3;}
  getGridOptions(){return {columns:12,rows:'auto'};}
  set hass(hass){
    this.hassRef=hass;
    const net=hass.states[this.config?.entity || 'sensor.internet'];
    if(!this.historyAt || Date.now()-this.historyAt>600000)this.loadHistory();
    if(this.net===net && this.rendered)return;
    this.net=net;this.rendered=true;this.render();
  }
  // Uptime and latency over 24 h / 7 d / 30 d from HA's long-term statistics
  // (hourly means of sensor.internet_uptime and sensor.internet_latency).
  async loadHistory(){
    this.historyAt=Date.now();
    try{
      const ids=['sensor.internet_uptime','sensor.internet_latency'];
      const r=await this.hassRef.callWS({type:'recorder/statistics_during_period',start_time:new Date(Date.now()-30*86400000).toISOString(),statistic_ids:ids,period:'hour',types:['mean']});
      const windows={'24 h':1,'7 d':7,'30 d':30};
      const mean=(id,days)=>{const rows=(r[id]||[]).filter(x=>x.start>=Date.now()-days*86400000 && x.mean!==null);
        return rows.length?{value:rows.reduce((t,x)=>t+x.mean,0)/rows.length,hours:rows.length}:null;};
      this.history=Object.fromEntries(Object.entries(windows).map(([label,days])=>[label,{uptime:mean(ids[0],days),latency:mean(ids[1],days)}]));
    }catch{this.history=null;}
    this.render();
  }
  render(){
    const n=this.net, a=n?.attributes||{}, p=a.ping||{}, d=a.dns||{}, h=this.history;
    const color={online:'#9dd3a8',degraded:'#ffb56b',offline:'#ff7b7b'}[n?.state]||'#aaa';
    const ms=v=>v===null||v===undefined?'—':`${Math.round(v)} ms`;
    const internet=[p.cloudflare,p.google].filter(x=>x?.ms!==null&&x?.ms!==undefined);
    const best=internet.length?Math.min(...internet.map(x=>x.ms)):null, loss=Math.max(p.cloudflare?.loss??100,p.google?.loss??100);
    this.shadowRoot.innerHTML=`<style>${TILE_STYLE}.grid{grid-template-columns:repeat(2,1fr)}.value{font-size:19px}.state{font-size:22px;font-weight:600;text-transform:capitalize}.trend{margin-top:8px;display:grid;gap:4px}.trend-row{display:grid;grid-template-columns:44px 1fr 1fr 1.4fr;gap:6px;align-items:baseline;font-size:14px}</style>
      <ha-card><h2>Internet</h2><div class="item" id="state"></div><div class="grid" id="items" style="margin-top:10px"></div><div class="checked" id="checked"></div></ha-card>`;
    const head=this.shadowRoot.querySelector('#state');head.style.borderLeftColor=color;
    head.append(make('div',n?.state||'Unavailable','state'));
    // Uptime per window, plus latency now against each window's average.
    if(h){
      const table=make('div',undefined,'trend'), pct=v=>v>=99.95?'100%':`${v.toFixed(1)}%`;
      for(const [label,w] of Object.entries(h)){
        const row=make('div',undefined,'trend-row');
        let vs='';
        if(w.latency && best!==null){const diff=best-w.latency.value;vs=Math.abs(diff)<2?'≈ avg':diff>0?`▲ ${Math.round(diff)} ms slower`:`▼ ${Math.round(-diff)} ms faster`;}
        row.append(make('span',label,'label'),make('span',w.uptime?`${pct(w.uptime.value)} up`:'—'),make('span',w.latency?`avg ${Math.round(w.latency.value)} ms`:'—','small'),make('span',vs,'small'));
        table.append(row);
      }
      const hours=h['30 d'].uptime?.hours||0;
      if(hours<30*24)table.append(make('div',`Still collecting: ${hours<24?`${hours} h`:`${Math.floor(hours/24)} days`} of 30 days recorded.`,'small'));
      head.append(table);
    }
    const items=this.shadowRoot.querySelector('#items');
    const tile=(label,value,note,bad)=>{const item=make('section',undefined,'item');item.style.borderLeftColor=bad?'#ffb56b':'#9dd3a8';item.append(make('div',label,'label'),make('div',value,'value'));if(note)item.append(make('div',note,'small'));items.append(item);};
    tile('Internet',ms(best),`${loss>=100?'No reply':`${Math.round(loss)}% loss`} · Cloudflare, Google`,best===null||best>=150||loss>=10);
    tile('Router',ms(p.router?.ms),p.router?.loss?`${Math.round(p.router.loss)}% loss`:'Gateway',p.router?.ms==null);
    tile('DNS',d.pihole?.ok?ms(d.pihole.ms):'Failing',`Pi-hole${d.router?.ok?` · router ${ms(d.router.ms)}`:' · router failing'}`,!d.pihole?.ok||!d.router?.ok);
    tile('Web',a.https?.ok?ms(a.https.ms):'Failing','HTTPS round trip',!a.https?.ok);
    this.shadowRoot.querySelector('#checked').textContent=`Checked from the Pi ${localTime(a.checked_at)} · every 30 minutes`;
  }
}
if(!customElements.get('internet-card'))customElements.define('internet-card',InternetCard);

// Upcoming Vandenberg launches with a firm time, labelled by how they look from home.
const LAUNCH_VIEWS={twilight:['Twilight · best','Dark sky, plume still in sunlight: the glowing "jellyfish". Look west-northwest.','#d7a9ff'],
  night:['Night','A bright point climbing and heading south. Look west-northwest.','#9fd3ff'],
  dusk:['Dusk or dawn','Sky still bright; the plume may be faint.','#ffb56b'],day:['Daytime','Possibly a contrail; hard to spot.','#aaa']};
class LaunchCard extends HTMLElement {
  constructor(){super();this.attachShadow({mode:'open'});}
  setConfig(config){this.config=config;this.toggleAttribute('hide-title',!!config.hide_title);}
  getCardSize(){return 4;}
  getGridOptions(){return {columns:12,rows:'auto'};}
  set hass(hass){
    this.timeZone=hass.config.time_zone;
    const launches=hass.states[this.config?.entity || 'sensor.vandenberg_launches'];
    if(this.launches===launches && this.rendered)return;
    this.launches=launches;this.rendered=true;this.render();
  }
  connectedCallback(){this.timer=setInterval(()=>this.launches&&this.render(),60000);}
  disconnectedCallback(){clearInterval(this.timer);}
  render(){
    const l=this.launches, a=l?.attributes||{}, timeZone=this.timeZone;
    const when=t=>new Date(t).toLocaleString(undefined,{timeZone,weekday:'short',month:'short',day:'numeric',hour:'numeric',minute:'2-digit'});
    const until=t=>{const m=Math.round((new Date(t)-Date.now())/60000);if(m<=0)return 'now';const d=Math.floor(m/1440),h=Math.floor(m%1440/60);return d?`in ${d} d ${h} h`:h?`in ${h} h ${m%60} min`:`in ${m} min`;};
    this.shadowRoot.innerHTML=`<style>${TILE_STYLE}.item{margin:8px 0}.value{font-size:18px}.links{display:flex;gap:14px;margin-top:6px;font-size:14px}.view{font-weight:600}</style>
      <ha-card><h2>Vandenberg launches</h2><div id="items"></div><div class="checked" id="checked"></div></ha-card>`;
    const items=this.shadowRoot.querySelector('#items');
    if(!l || !Number.isFinite(Number(l.state)))items.append(make('p','Launch schedule unavailable.','small'));
    else if(!a.launches?.length)items.append(make('p','No Vandenberg launches with a set time yet.','small'));
    for(const launch of (a.launches||[]).slice(0,3)){
      const [label,tip,color]=LAUNCH_VIEWS[launch.view]||LAUNCH_VIEWS.day, item=make('section',undefined,'item'), links=make('div',undefined,'links');
      item.style.borderLeftColor=color;
      const status=launch.status==='Go'?'':` · ${launch.status==='TBC'?'to be confirmed':launch.status==='TBD'?'time to be set':launch.status}`;
      item.append(make('div',`${when(launch.net)} · ${until(launch.net)}${status}`,'label'),make('div',`${launch.rocket} · ${launch.mission}`,'value'));
      const view=make('div',undefined,'small');view.append(make('span',`${label}. `,'view'),document.createTextNode(tip));item.append(view);
      for(const [text,href] of [['Details ↗',launch.url],['Webcast ↗',launch.webcast]])if(href){const link=make('a',text);link.href=href;link.target='_blank';link.rel='noopener';links.append(link);}
      if(links.childNodes.length)item.append(links);
      items.append(item);
    }
    this.shadowRoot.querySelector('#checked').textContent=`Launch Library 2 · Checked ${localTime(a.checked_at)} · Twilight and night launches are announced on the tablet 10 minutes before (not 9 PM–5 AM)`;
  }
}
if(!customElements.get('launch-card'))customElements.define('launch-card',LaunchCard);

class LocalCalendarCard extends HTMLElement {
  constructor(){super();this.attachShadow({mode:'open'});}
  setConfig(config){
    const url=new URL(config.url);
    if(url.origin!=='https://calendar.google.com')throw new Error('Expected a Google Calendar embed URL');
    this.shadowRoot.innerHTML='<style>:host{display:block}:host([hide-title]) h2{display:none}ha-card{display:block;overflow:hidden;border-radius:var(--ha-card-border-radius,12px)}iframe{display:block;border:0;width:100%;height:calc(100dvh - 125px);min-height:520px;background:white}@media(max-width:600px){iframe{height:calc(100dvh - 120px);min-height:420px}}</style><ha-card><iframe title="Family and local events calendar"></iframe></ha-card>';
    this.shadowRoot.querySelector('iframe').src=url.href;
  }
  set hass(_hass){}
  getCardSize(){return 12;}
}
if(!customElements.get('local-calendar-card'))customElements.define('local-calendar-card',LocalCalendarCard);

// Office window camera (scripts/cameras). The minute snapshot paints at
// once; the live stream fades in over it when video actually plays, and the
// previous day's timelapse plays in place. Media goes through signed media
// source URLs, not /local, which is public.
const CAMERA_MEDIA='media-source://media_source/local/office-camera';
const findDeep=(root,selector)=>{
  const tree=root?.shadowRoot||root;
  if(!tree?.querySelectorAll)return null;
  const match=tree.querySelector(selector);
  if(match)return match;
  for(const element of tree.querySelectorAll('*'))if(element.shadowRoot){const found=findDeep(element,selector);if(found)return found;}
  return null;
};
const findVideo=root=>findDeep(root,'video');
// Full screen for a camera card's picture. iPhone Safari only full-screens a
// <video> itself, so fall back to that.
const toggleFullscreen=frame=>{
  if(document.fullscreenElement)return document.exitFullscreen();
  if(frame.requestFullscreen)return frame.requestFullscreen().catch(()=>{});
  const video=[...frame.querySelectorAll('video:not([hidden])')].pop()||findVideo(frame);
  video?.webkitEnterFullscreen?.();
};
const FULLSCREEN_CSS='.frame:fullscreen{aspect-ratio:auto;width:100vw;height:100vh}.frame:fullscreen .still{object-fit:contain}';
class OfficeCameraCard extends HTMLElement {
  constructor(){super();this.attachShadow({mode:'open'});}
  setConfig(config){this.config={entity:'camera.office_window',...config};}
  getCardSize(){return 5;}
  getGridOptions(){return {columns:12,rows:'auto'};}
  set hass(hass){
    this._hass=hass;
    // The stream's access token rotates with the entity's state object.
    if(this.live){this.live.hass=hass;const state=hass.states[this.config.entity];if(state!==this.live.stateObj)this.live.stateObj=state;}
    if(!this.built){this.built=true;this.build();}
  }
  connectedCallback(){if(this.built)this.start();}
  disconnectedCallback(){clearInterval(this.timer);clearInterval(this.poll);this.timer=this.poll=undefined;}
  build(){
    this.shadowRoot.innerHTML=`<style>
      :host{display:block}[hidden]{display:none!important}
      ha-card{display:block;overflow:hidden;border-radius:var(--ha-card-border-radius,12px);background:var(--ha-card-background,var(--card-background-color))}
      .frame{position:relative;aspect-ratio:16/9;background:#111}
      .frame>*{position:absolute;inset:0;width:100%;height:100%}
      .still{object-fit:cover}
      .live{opacity:0;transition:opacity .4s;cursor:pointer}.live ha-camera-stream{display:block;width:100%;height:100%}
      .frame.playing .live{opacity:1}
      .lapse{object-fit:contain;background:#000;z-index:1}
      .bar{display:flex;align-items:center;gap:8px;padding:8px 12px;color:var(--secondary-text-color);font-size:13px}
      .bar span{flex:1}
      button{font:inherit;color:var(--primary-color);background:none;border:1px solid var(--divider-color);border-radius:16px;padding:4px 12px;cursor:pointer}
      ${FULLSCREEN_CSS}
    </style><ha-card><div class="frame"><img class="still" alt="Office window" hidden><div class="live"></div><video class="lapse" controls muted playsinline hidden></video></div>
      <div class="bar"><span>Office window · loading</span><button class="play" hidden></button><button class="full" title="Full screen">⛶</button></div></ha-card>`;
    this.frame=this.shadowRoot.querySelector('.frame');
    this.still=this.shadowRoot.querySelector('.still');
    this.lapse=this.shadowRoot.querySelector('.lapse');
    this.status=this.shadowRoot.querySelector('.bar span');
    this.play=this.shadowRoot.querySelector('.play');
    this.play.addEventListener('click',()=>this.toggleLapse());
    this.shadowRoot.querySelector('.full').addEventListener('click',()=>toggleFullscreen(this.frame));
    this.lapse.addEventListener('ended',()=>this.toggleLapse(false));
    // HA's own player; it reads its API connection from Lit context, so it has
    // to sit inside this card's tree rather than anywhere on the page.
    this.live=Object.assign(document.createElement('ha-camera-stream'),{hass:this._hass,stateObj:this._hass.states[this.config.entity],muted:true,controls:false,fitMode:'cover'});
    const layer=this.shadowRoot.querySelector('.live');
    layer.append(this.live);
    // Tapping the picture opens the camera's more-info dialog, as picture-entity does.
    layer.addEventListener('click',()=>this.dispatchEvent(new CustomEvent('hass-more-info',{bubbles:true,composed:true,detail:{entityId:this.config.entity}})));
    this.timelapse();
    if(this.isConnected)this.start();
  }
  start(){
    if(this.timer)return;
    this.snapshot();
    this.timer=setInterval(()=>this.snapshot(),60*1000);
    this.poll=setInterval(()=>{
      const video=findVideo(this.live), playing=!!video && video.readyState>=2 && !video.paused;
      this.frame.classList.toggle('playing',playing);
      if(this.lapse.hidden)this.status.textContent=playing?'Office window · live':this.still.hidden?'Office window · connecting':'Office window · snapshot (live view loading)';
    },500);
  }
  async resolve(path){
    const {url}=await this._hass.callWS({type:'media_source/resolve_media',media_content_id:`${CAMERA_MEDIA}/${path}`});
    return this._hass.hassUrl(url);
  }
  async snapshot(){
    try{
      const src=await this.resolve('latest.jpg'), image=new Image();
      image.onload=()=>{this.still.src=src;this.still.hidden=false;};
      image.src=src;
    }catch(_error){/* No snapshot yet; the live layer is all there is. */}
  }
  async timelapse(){
    try{
      const folder=await this._hass.callWS({type:'media_source/browse_media',media_content_id:`${CAMERA_MEDIA}/timelapse`});
      const latest=(folder.children||[]).filter(item=>item.title.endsWith('.mp4')).sort((a,b)=>a.title.localeCompare(b.title)).pop();
      if(!latest)return;
      this.lapseFile=latest.title;
      const day=new Date(`${latest.title.slice(0,10)}T12:00`).toLocaleDateString(undefined,{weekday:'long'});
      this.play.textContent=`▶ ${day}'s timelapse`;
      this.play.hidden=false;
    }catch(_error){/* No timelapse folder yet. */}
  }
  async toggleLapse(show=this.lapse.hidden){
    if(!show){this.lapse.pause();this.lapse.hidden=true;this.play.textContent=this.play.dataset.label;return;}
    this.play.dataset.label=this.play.textContent;
    this.lapse.src=await this.resolve(`timelapse/${this.lapseFile}`);
    this.lapse.hidden=false;
    this.play.textContent='✕ Close timelapse';
    this.status.textContent=`Timelapse · ${this.lapseFile.slice(0,10)}`;
    this.lapse.play().catch(()=>{});
  }
}
if(!customElements.get('office-camera-card'))customElements.define('office-camera-card',OfficeCameraCard);

// Baby monitor on the BabySteps dashboard: the laptop's own webcam and microphone
// (scripts/cameras), live only while the lid is open. Browsers start video muted;
// Listen turns the sound on, which needs that tap anyway. HA's WebRTC player
// receives the audio track but never attaches it, so it plays through <audio>.
class BabyMonitorCard extends HTMLElement {
  constructor(){super();this.attachShadow({mode:'open'});this.listening=false;}
  setConfig(config){this.config={entity:'camera.baby_monitor',lid_entity:'binary_sensor.laptop_lid',...config};}
  getCardSize(){return 6;}
  getGridOptions(){return {columns:12,rows:'auto'};}
  set hass(hass){
    this._hass=hass;
    if(!this.built){this.built=true;this.build();}
    if(this.live){this.live.hass=hass;const state=hass.states[this.config.entity];if(state!==this.live.stateObj)this.live.stateObj=state;}
    const closed=hass.states[this.config.lid_entity]?.state==='off';
    if(closed!==this.closed){this.closed=closed;this.update();}
  }
  connectedCallback(){if(this.built)this.update();}
  disconnectedCallback(){clearInterval(this.poll);this.poll=undefined;this.stop();}
  build(){
    this.shadowRoot.innerHTML=`<style>
      :host{display:block}[hidden]{display:none!important}
      ha-card{display:block;overflow:hidden;border-radius:var(--ha-card-border-radius,12px);background:var(--ha-card-background,var(--card-background-color));color:var(--primary-text-color)}
      .frame{position:relative;aspect-ratio:16/9;background:#111}
      .frame ha-camera-stream{display:block;width:100%;height:100%}
      .off{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:6px;height:100%;padding:0 24px;text-align:center;color:#ccc}
      .off ha-icon{--mdc-icon-size:40px;color:#888}
      .bar{display:flex;align-items:center;gap:8px;padding:8px 12px;color:var(--secondary-text-color);font-size:13px}
      .bar span{flex:1}
      button{font:inherit;color:var(--primary-color);background:none;border:1px solid var(--divider-color);border-radius:16px;padding:4px 12px;cursor:pointer}
      button.on{color:var(--text-primary-color,#fff);background:var(--primary-color);border-color:var(--primary-color)}
      ${FULLSCREEN_CSS}
    </style><ha-card><div class="frame"><div class="off" hidden><ha-icon icon="mdi:laptop-off"></ha-icon><b>Baby monitor is off</b><span>The laptop lid is closed. Open it to watch and listen.</span></div></div>
      <div class="bar"><span>Baby monitor</span><button class="listen" hidden></button><button class="full" title="Full screen" hidden>⛶</button></div><audio></audio></ha-card>`;
    this.frame=this.shadowRoot.querySelector('.frame');
    this.off=this.shadowRoot.querySelector('.off');
    this.status=this.shadowRoot.querySelector('.bar span');
    this.button=this.shadowRoot.querySelector('.listen');
    this.audio=this.shadowRoot.querySelector('audio');
    this.full=this.shadowRoot.querySelector('.full');
    this.full.addEventListener('click',()=>toggleFullscreen(this.frame));
    this.button.addEventListener('click',()=>{this.listening=!this.listening;if(this.live)this.live.muted=!this.listening;this.label();this.sound();});
    this.label();
  }
  label(){
    this.button.textContent=this.listening?'🔊 Listening':'🔇 Listen';
    this.button.classList.toggle('on',this.listening);
  }
  stop(){this.live?.remove();this.live=undefined;this.audio.pause();this.audio.srcObject=null;}
  // Follows reconnects: a new peer connection brings a new audio track.
  sound(){
    if(!this.listening){this.audio.pause();this.audio.srcObject=null;return;}
    const track=findDeep(this.live,'ha-web-rtc-player')?._peerConnection?.getReceivers().find(receiver=>receiver.track.kind==='audio')?.track;
    if(!track||this.audio.srcObject?.getAudioTracks()[0]===track)return;
    this.audio.srcObject=new MediaStream([track]);
    this.audio.play().catch(()=>{});
  }
  update(){
    if(!this.built||!this.isConnected)return;
    this.off.hidden=!this.closed;
    this.button.hidden=this.full.hidden=this.closed;
    if(this.closed){this.stop();clearInterval(this.poll);this.poll=undefined;this.status.textContent='Baby monitor · lid closed';return;}
    if(!this.live){
      // HA's own player; it reads its API connection from Lit context, so it has
      // to sit inside this card's tree.
      this.live=Object.assign(document.createElement('ha-camera-stream'),{hass:this._hass,stateObj:this._hass.states[this.config.entity],muted:!this.listening,controls:false,fitMode:'contain'});
      this.frame.append(this.live);
    }
    if(!this.poll)this.poll=setInterval(()=>{
      const video=findVideo(this.live), playing=!!video && video.readyState>=2 && !video.paused;
      this.status.textContent=playing?`Baby monitor · live${this.listening?'':', sound off'}`:'Baby monitor · connecting';
      this.sound();
    },500);
  }
}
if(!customElements.get('baby-monitor-card'))customElements.define('baby-monitor-card',BabyMonitorCard);

// Sleep timers from the baby monitor analyzer (scripts/cameras/analyzer), via
// sensor.baby_monitor_analysis. Timers tick here every second between the
// sensor's 5-second updates. Detected sleeps can be logged to BabySteps one at
// a time or all at once (script.baby_monitor_log_sleep).
const span=seconds=>{
  if(seconds==null||!isFinite(seconds))return '—';
  const s=Math.max(0,Math.round(seconds)), h=Math.floor(s/3600), m=Math.floor(s%3600/60);
  if(h)return `${h}h ${String(m).padStart(2,'0')}m`;
  if(m>=10)return `${m}m`;
  return m?`${m}m ${String(s%60).padStart(2,'0')}s`:`${s}s`;
};
const since=iso=>iso?(Date.now()-new Date(iso).getTime())/1000:null;
const clockAt=iso=>iso?new Date(iso).toLocaleTimeString(undefined,{hour:'numeric',minute:'2-digit'}):'';
const PAUSED={'lid closed':'Paused · laptop lid closed','monitoring off':'Paused · monitoring is off','no signal':'Paused · no camera signal','restarted':'Starting up'};
const EVENT_TEXT={in_frame:'In crib',settling:'Settling',asleep:'Asleep',woke:'Woke',cry:'Cried',fuss:'Fussed',left:'Out of crib'};
class BabySleepCard extends HTMLElement {
  constructor(){super();this.attachShadow({mode:'open'});}
  setConfig(config){this.config={entity:'sensor.baby_monitor_analysis',...config};this.toggleAttribute('hide-title',!!config.hide_title);}
  getCardSize(){return 7;}
  getGridOptions(){return {columns:12,rows:'auto'};}
  set hass(hass){
    this._hass=hass;
    const entity=hass.states[this.config.entity];
    if(entity===this.entity&&this.rendered)return;
    this.entity=entity;this.rendered=true;this.render();
  }
  connectedCallback(){this.timer=setInterval(()=>this.render(),1000);}
  async logSleep(sleep){
    this.logging.add(sleep.id);this.notes[sleep.id]='';this.render();
    try{
      const {response}=await this._hass.callWS({type:'call_service',domain:'script',service:'baby_monitor_log_sleep',
        service_data:{id:sleep.id,start:sleep.start,end:sleep.end},return_response:true});
      this.notes[sleep.id]=response?.ok?'':(response?.errors||['BabySteps did not save it.']).join(' ');
      if(response?.ok)this.done.add(sleep.id);
      return !!response?.ok;
    }catch(error){this.notes[sleep.id]=error.message||String(error);return false;}
    finally{this.logging.delete(sleep.id);this.render();}
  }
  async logAll(){
    // Oldest first, stopping at the first refusal so its reason stays visible.
    for(const sleep of this.unlogged().reverse())if(!await this.logSleep(sleep))break;
  }
  unlogged(){return (this.entity?.attributes.sleeps||[]).filter(sleep=>!sleep.logged&&!this.done.has(sleep.id));}
  disconnectedCallback(){clearInterval(this.timer);}
  render(){
    if(!this.body){
      this.shadowRoot.innerHTML=`<style>${TILE_STYLE}
        .status{font-size:22px;font-weight:600;margin:0 0 4px}.sub{font-size:13px;opacity:.8;margin:0 0 14px}
        .crying{color:#ff7b7b}.asleep{border-left-color:#8fb5ff}.cry{border-left-color:#ff7b7b}.fuss{border-left-color:#ffb56b}.dim{opacity:.55}
        .bars{display:flex;align-items:flex-end;gap:1px;height:48px;margin:16px 0 4px}.bars div{flex:1;background:#8fb5ff;min-height:1px;border-radius:1px}.bars div.c{background:#ff7b7b}
        .axis{display:flex;justify-content:space-between;font-size:11px;opacity:.7}
        ul{list-style:none;padding:0;margin:14px 0 0;font-size:13px}li{display:flex;gap:10px;padding:3px 0;border-top:1px solid #ffffff1a}li b{min-width:64px;font-weight:500;opacity:.8}
        .sleeps{margin:16px 0 0}.sleeps h3{display:flex;align-items:center;gap:8px;font-size:15px;margin:0 0 6px}.sleeps h3 span{flex:1}
        .sleep{display:flex;align-items:center;gap:10px;padding:6px 0;border-top:1px solid #ffffff1a;font-size:14px}.sleep span{flex:1}.sleep .why{flex-basis:100%;color:#ff7b7b;font-size:12px}
        .sleep{flex-wrap:wrap}.ok{color:#9dd3a8;font-size:13px}
        button{font:inherit;font-size:13px;color:var(--primary-color);background:none;border:1px solid var(--divider-color);border-radius:16px;padding:3px 12px;cursor:pointer}button:disabled{opacity:.5;cursor:default}
      </style><ha-card><h2>Sleep</h2><div id="body"></div></ha-card>`;
      this.body=this.shadowRoot.getElementById('body');
      this.logging=new Set();this.done=new Set();this.notes={};
      this.body.addEventListener('click',event=>{
        const target=event.target.closest('[data-log]');
        if(!target||target.disabled)return;
        if(target.dataset.log==='all')return this.logAll();
        const sleep=(this.entity?.attributes.sleeps||[]).find(item=>item.id===target.dataset.log);
        if(sleep)this.logSleep(sleep);
      });
    }
    const a=this.entity?.attributes;
    if(!a||!this.entity||['unavailable','unknown'].includes(this.entity.state)){this.body.innerHTML='<p class="sub">Sleep tracking is unavailable: the analyzer is not answering.</p>';return;}
    const s=this.entity.state, session=a.session_state;
    let status;
    if(s==='paused')status=PAUSED[a.paused_reason]||'Paused';
    else if(a.crying)status='😢 Crying';
    else if(session==='asleep')status=`😴 Asleep · ${span(since(a.asleep_at))}`;
    else if(session==='settling')status=`🌙 Settling · ${span(since(a.settling_at))}`;
    else if(session==='awake')status=`${a.fussing?'😣 Fussing':'👀 Awake in crib'} · ${span(since(a.awake_since))}`;
    else status='Not in crib';
    const notes=[];
    if(s!=='paused'&&a.video==='dark')notes.push('Too dark to see movement, so falling asleep can’t be spotted; crying still is. A dim night light helps.');
    if(s!=='paused'&&session!=='absent')notes.push(`${a.movements_per_minute} movements in the last minute${a.moving?' · moving now':''}`);
    const last=a.last_sleep, asleep=session==='asleep'&&s!=='paused';
    const tile=(label,value,note,cls='')=>`<section class="item ${cls}"><div class="label">${label}</div><div class="value">${value}</div><div class="small">${note||'&nbsp;'}</div></section>`;
    const tiles=[
      asleep?tile('Asleep for',span(since(a.asleep_at)),`since ${clockAt(a.asleep_at)}`,'asleep')
        :tile('Awake for',last?span(since(last.end)):'—',last?`since sleep ended ${clockAt(last.end)}`:'no sleep seen yet'),
      tile('Took to fall asleep',span(asleep?a.fell_asleep_seconds:last?.fell_asleep_seconds),
        asleep?`settled at ${clockAt(a.asleep_at)}`:last?`before the last sleep`:'',''),
      tile('Last sleep',last?span((new Date(last.end)-new Date(last.start))/1000):'—',last?`${clockAt(last.start)}–${clockAt(last.end)}`:''),
      tile('In crib',a.in_frame_at?span(since(a.in_frame_at)):'—',a.in_frame_at?`since ${clockAt(a.in_frame_at)}`:'not in frame'),
      tile('Last cry',a.crying?'Now':a.last_cry?`${span(since(a.last_cry.end))} ago`:'—',a.last_cry?`lasted ${span(a.last_cry.seconds)} · ${clockAt(a.last_cry.start)}`:'','cry'),
      tile('Last fuss',a.fussing?'Now':a.last_fuss?`${span(since(a.last_fuss.end))} ago`:'—',a.last_fuss?`lasted ${span(a.last_fuss.seconds)} · ${clockAt(a.last_fuss.start)}`:'','fuss'),
    ];
    const minutes=a.minutes||[], peak=Math.max(4,...minutes.map(m=>m[0]));
    const bars=minutes.map(([moves,cry])=>`<div class="${cry?'c':''}" style="height:${Math.round(100*(cry?Math.max(moves,peak*cry/60):moves)/peak)}%" title="${moves} movements${cry?`, ${cry}s crying`:''}"></div>`).join('');
    const pending=this.unlogged(), busy=this.logging.size>0;
    const sleepRows=(a.sleeps||[]).slice(0,8).map(sleep=>{
      const logged=sleep.logged||this.done.has(sleep.id), start=new Date(sleep.start), age=Date.now()-start;
      const day=start.toDateString()===new Date().toDateString()?'':`${start.toLocaleDateString(undefined,age<6*864e5?{weekday:'short'}:{month:'short',day:'numeric'})} `;
      const action=logged?'<span class="ok" style="flex:0">✓ Logged</span>':`<button data-log="${sleep.id}" ${busy?'disabled':''}>${this.logging.has(sleep.id)?'Logging…':'Log'}</button>`;
      return `<div class="sleep"><span>${day}${clockAt(sleep.start)}–${clockAt(sleep.end)} · <b>${span(sleep.seconds)}</b>${sleep.fell_asleep_seconds!=null?` · took ${span(sleep.fell_asleep_seconds)} to settle`:''}</span>${action}${this.notes[sleep.id]&&!logged?`<span class="why">${this.notes[sleep.id]}</span>`:''}</div>`;
    }).join('');
    const sleeps=sleepRows?`<div class="sleeps"><h3><span>Detected sleeps</span>${pending.length?`<button data-log="all" ${busy?'disabled':''}>Log all sleeps (${pending.length})</button>`:''}</h3>${sleepRows}</div>`:'';
    const events=(a.events||[]).slice(-6).reverse().map(e=>`<li><b>${clockAt(e.at)}</b><span>${EVENT_TEXT[e.type]||e.type}${e.fell_asleep_seconds!=null?` · took ${span(e.fell_asleep_seconds)}`:''}${e.slept_seconds!=null?` · slept ${span(e.slept_seconds)}`:''}${e.seconds!=null?` · ${span(e.seconds)}`:''}${e.why&&e.type==='woke'?` · ${e.why}`:''}</span></li>`).join('');
    this.body.innerHTML=`<div class="status ${a.crying?'crying':''}">${status}</div><div class="sub">${notes.join(' · ')||'&nbsp;'}</div>
      <div class="grid ${s==='paused'?'dim':''}">${tiles.join('')}</div>
      <div class="bars" title="Movements per minute, last hour; red is crying">${bars}</div><div class="axis"><span>1 hour ago</span><span>movement · <span style="color:#ff7b7b">crying</span></span><span>now</span></div>
      ${sleeps}
      ${events?`<ul>${events}</ul>`:''}`;
  }
}
if(!customElements.get('baby-sleep-card'))customElements.define('baby-sleep-card',BabySleepCard);

// Register before the built-in Overview strategy is imported. The generated
// result stays native Lovelace, so HA supplies entities, forecasts and layout.
customElements.whenDefined('home-overview-view-strategy').then(() => {
  const Strategy = customElements.get('home-overview-view-strategy');
  if(Strategy.localMapWidgets)return;
  Strategy.localMapWidgets=true;
  const generate=Strategy.generate;
  Strategy.generate=async function(config,hass){
    const view=await generate.call(this,config,hass);
    // Fall back to Met.no's default entity: the strategy can run before states load.
    const weatherId=Object.keys(hass.states).find(id=>id.startsWith('weather.') && !['unavailable','unknown'].includes(hass.states[id].state)) || Object.keys(hass.states).find(id=>id.startsWith('weather.')) || 'weather.forecast_home';
    // Grouped by topic, in phone reading order. The sections view aligns rows,
    // so neighbouring groups are kept to similar heights on two columns.
    const card=(type,extra={})=>({type:`custom:${type}`,...extra,grid_options:{columns:12,rows:'auto'}});
    const group=(heading,icon,cards)=>({type:'grid',cards:[{type:'heading',heading,heading_style:'title',icon},...cards]});
    // Warnings and fires appear only while active (HA card visibility conditions).
    const warningsActive=[{condition:'or',conditions:[{condition:'state',entity:'sensor.local_weather_alerts',state:'active'},
      {condition:'state',entity:'sensor.power_shutoff',state:['under_consideration','power_shutoff']}]}];
    const now=[card('local-warnings-card',{visibility:warningsActive}),card('fire-incidents-card',{visibility:[{condition:'numeric_state',entity:'sensor.fire_incidents',above:0}]}),
      card('earthquake-card',{visibility:[{condition:'numeric_state',entity:'sensor.earthquakes',above:0}]})], today=[card('today-card',{hide_title:true})];
    now.push({type:'conditional',conditions:[{condition:'state',entity:'binary_sensor.cooler_air_outside',state:'on'}],
      card:{type:'markdown',title:'ℹ️ Cooler air outside',content:"Inside: **{{ states('sensor.cooling_indoor_temperature') | float(0) | round(1) }}°F** · Outside: **{{ states('sensor.cooling_outdoor_temperature') | float(0) | round(1) }}°F**. It is cooler outside now.",
        grid_options:{columns:12,rows:'auto'}},grid_options:{columns:12,rows:'auto'}});
    if(weatherId){
      const features=hass.states[weatherId]?.attributes.supported_features ?? 1;
      const forecastType=features & 1 ? 'daily' : features & 2 ? 'hourly' : 'twice_daily';
      now.push(card('current-conditions-card',{weather_entity:weatherId}));
      now.push(card('office-camera-card'));
      now.push({type:'weather-forecast',entity:weatherId,name:'Thousand Oaks',show_current:false,show_forecast:true,forecast_type:forecastType,grid_options:{columns:12,rows:'auto'}});
    }
    const sections=[
      group('Right now','mdi:weather-partly-cloudy',now),
      group('Today','mdi:calendar-today',today),
      group('Baby care','mdi:baby-face-outline',[card('baby-care-card',{weather_entity:weatherId,hide_title:true})]),
      group('Recipe of the day','mdi:silverware-fork-knife',[card('recipe-card',{hide_title:true})]),
      group('Freeways: 101 & 23','mdi:highway',[card('freeway-card',{hide_title:true})]),
      group('Day trip','mdi:beach',[card('daytrip-card',{hide_title:true})]),
      group('Vandenberg launches','mdi:rocket-launch',[card('launch-card',{hide_title:true})]),
      group('Cheapest gas nearby','mdi:gas-station',[card('gas-prices-card',{hide_title:true})]),
      group('California grid','mdi:transmission-tower',[card('grid-card',{hide_title:true})]),
    ];
    // HA's own sections (favorites, areas) join Summaries in the sidebar when it
    // is shown; on one column they stay at the bottom as before.
    const phoneOnly=section=>(section.visibility||[]).some(c=>c.condition==='view_columns' && c.max===1);
    const native=view.sections||[];
    const piHealth=hass.states['sensor.pi_health']?[card('pi-health-card',{hide_title:true,name:'Home Assistant server'}),
      card('pi-health-card',{hide_title:true,entity:'sensor.pi_health',name:'Raspberry Pi · Pi-hole, BabySteps',every:'10 minutes',fresh_minutes:25})]:[card('pi-health-card',{hide_title:true})];
    const pi={type:'grid',cards:[{type:'heading',heading:'Device Health',heading_style:'title',icon:'mdi:server'},...piHealth,
      {type:'heading',heading:'Internet',heading_style:'title',icon:'mdi:web'},card('internet-card',{hide_title:true})]};
    if(!view.sidebar)return {...view,sections:[...sections,...native,pi]};
    const moved=[...native.filter(section=>!phoneOnly(section)),pi];
    return {...view,
      sidebar:{...view.sidebar,sections:[...(view.sidebar.sections||[]),...moved.map(({column_span,...section})=>section)]},
      sections:[...sections,...[...native,pi].map(section=>moved.includes(section)?{...section,visibility:[...(section.visibility||[]),{condition:'view_columns',max:1}]}:section)]};
  };
});
