// Leaflet 1.9.4 is served locally; all live layers retain their source attribution.
const ROOT = '/local/local-map';
const SCE = 'https://sce-outage-ags.esriemcs.com/arcgis/rest/services/43';
const ICA = 'https://drpep.sce.com/arcgis_server/rest/services/Hosted/ICA_Layer/FeatureServer/0';
const PARCELS = 'https://maps.ventura.org/arcgis/rest/services/SDs/Parcels/MapServer/0';
const FIRE = 'https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/WFIGS_Interagency_Perimeters_Current/FeatureServer/0';
const AQI = 'https://services.arcgis.com/cJ9YHowT8TU7DUyn/arcgis/rest/services/AirNowLatestContoursCombined/FeatureServer/0';
const COLORS = ['#00e400', '#ffff00', '#ff7e00', '#ff0000', '#8f3f97', '#7e001a'];
const escapeSQL = s => String(s).replaceAll("'", "''");
const stamp = value => value ? new Date(value).toLocaleString(undefined, {timeZone: 'America/Los_Angeles'}) : 'Not published';
const node = (tag, text) => { const n = document.createElement(tag); n.textContent = text; return n; };
let leafletReady;
function loadLeaflet() {
  if (window.L) return Promise.resolve(window.L);
  if (!leafletReady) leafletReady = new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = `${ROOT}/vendor/leaflet.js`;
    script.onload = () => resolve(window.L);
    script.onerror = () => { leafletReady = null; script.remove(); reject(new Error('Map library could not load')); };
    document.head.append(script);
  });
  return leafletReady;
}
async function getJSON(url) {
  const response = await fetch(url, {signal: AbortSignal.timeout(22000), cache: 'no-store'});
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const data = await response.json();
  if (data.error) throw new Error(data.error.message || 'Service error');
  return data;
}
async function queryFeatures(url, params, request=getJSON) {
  const features = [];
  for (let offset = 0; offset < 4000; offset += 1000) {
    const p = new URLSearchParams({where: '1=1', outFields: '*', outSR: '4326',
      returnGeometry: 'true', f: 'geojson', geometryPrecision: '5', resultRecordCount: '1000',
      ...params, resultOffset: String(offset)});
    const data = await request(`${url}/query?${p}`);
    if (!Array.isArray(data.features)) throw new Error('Invalid map response');
    features.push(...data.features);
    if (!(data.exceededTransferLimit || data.properties?.exceededTransferLimit)) return {type: 'FeatureCollection', features};
  }
  throw new Error('Too many features — zoom in');
}

class LocalMapCard extends HTMLElement {
  constructor() {
    super(); this.attachShadow({mode: 'open'}); this.layers = new Map(); this.requests = new Map();
  }
  setConfig(config) { this.config = {...config}; if (this.isConnected) this.start(); }
  set hass(hass) { this._hass = hass; if (this.map) this.updateStatus(); }
  getCardSize() { return 12; }
  connectedCallback() { if (this.config) this.start(); }
  disconnectedCallback() {
    clearInterval(this.timer); clearTimeout(this.moveTimer); this.observer?.disconnect();
    for (const [key, value] of this.requests) this.requests.set(key, value + 1);
    this.map?.remove(); this.map = null; this.layers.clear();
  }
  async start() {
    if (this.map || this.starting) return;
    this.starting = true;
    this.shadowRoot.innerHTML = `
      <link rel="stylesheet" href="${ROOT}/vendor/leaflet.css">
      <style>
        :host{display:block;height:100%;min-height:0;min-width:0;color:var(--primary-text-color,#f4f0e9);container:local-map / inline-size}
        *{box-sizing:border-box}ha-card{display:flex;flex-direction:column;height:100%;min-height:0;background:var(--ha-card-background,var(--card-background-color,#12161c));overflow:hidden}
        header{display:flex;flex:none;gap:20px;align-items:center;justify-content:space-between;padding:20px 24px;border-bottom:1px solid #ffffff24}
        h1{font-size:28px;margin:0;font-weight:600} .eyebrow{color:var(--primary-color,#ffb56b);font-size:13px;letter-spacing:2px;margin-bottom:4px}
        button,select{font:inherit;color:inherit;background:var(--secondary-background-color,#20232b);border:1px solid #ffffff35;border-radius:8px;padding:9px 12px;cursor:pointer}
        button:focus-visible,select:focus-visible,input:focus-visible{outline:3px solid #ffb56b;outline-offset:2px}
        .layout{position:relative;display:grid;grid-template-columns:300px minmax(0,1fr);flex:1;min-height:0;min-width:0}aside{min-height:0;padding:20px;overflow:auto;overscroll-behavior:contain}
        .map{height:100%;min-height:0;min-width:0;background:#202731;isolation:isolate}
        .status{padding:14px;border:1px solid #ffffff30;border-radius:10px;margin-bottom:18px;line-height:1.5}
        .status.alert{border-color:#ffb56b;background:#ffb56b14}.status h2{font-size:18px;margin:0 0 5px}.status p{margin:6px 0;font-size:14px}
        .small{font-size:12px;color:var(--secondary-text-color,#b3b8c4)} .toolbar{display:flex;gap:8px;flex-wrap:wrap}
        label{display:flex;gap:10px;align-items:center;min-height:44px;padding:9px 0;font-size:15px;cursor:pointer}input{width:20px;height:20px;accent-color:#ffb56b;flex:none}
        label small{display:block;font-size:11px;margin-top:3px;color:var(--secondary-text-color,#aaa)}select{width:100%;margin:8px 0 12px}
        h3{font-size:13px;letter-spacing:1.2px;text-transform:uppercase;margin:22px 0 8px;color:var(--primary-color,#ffb56b)}
        a{color:var(--primary-color,#ffb56b)}footer{flex:none;max-height:25%;overflow:auto;padding:8px 24px;border-top:1px solid #ffffff24;font-size:12px;line-height:1.6;overscroll-behavior:contain}footer summary{cursor:pointer;min-height:28px;display:flex;align-items:center}footer summary::before{content:'▸';margin-right:7px}footer details[open] summary::before{content:'▾'}footer p{margin:6px 0}
        .leaflet-container{font-family:Arial,sans-serif;color:#111}.leaflet-popup-content{max-height:260px;overflow:auto}.leaflet-popup-content p{margin:6px 0}
        .legend{display:flex;flex-wrap:wrap;gap:7px;font-size:11px}.legend span{display:flex;gap:4px;align-items:center}.legend i{width:9px;height:9px;border-radius:50%}
        .leaflet-bottom.leaflet-right{max-width:calc(100% - 12px)}.leaflet-control-attribution{white-space:normal;overflow-wrap:anywhere;font-size:10px;line-height:1.35}.leaflet-control-attribution a{color:#075d97}.feed-error{color:#ffa58d}
        #layers,.options-header,#mobile-power-summary{display:none}
        @container local-map (max-width:750px){
          header{padding:10px 14px;align-items:start;gap:10px;flex-wrap:wrap}header>div:first-child{flex:1 1 100%}h1{font-size:24px}.eyebrow{display:none}
          .toolbar{width:100%;display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}.toolbar button{min-height:44px;padding:8px}#layers{display:block;font-weight:600}
          #mobile-power-summary{display:block;margin-top:4px;font-size:13px}#mobile-power-summary.alert{color:#ffc586}
          .layout{display:block}.map{width:100%;height:100%}
          aside{display:none;position:absolute;inset:0;z-index:1000;padding:0 16px max(16px,env(safe-area-inset-bottom));background:var(--ha-card-background,var(--card-background-color,#12161c))}
          .layout.controls-open aside{display:block}.layout.controls-open .map{visibility:hidden}
          .options-header{position:sticky;top:0;z-index:1;display:flex;justify-content:space-between;align-items:center;padding:12px 0;margin-bottom:12px;background:inherit;border-bottom:1px solid #ffffff30}.options-header strong{font-size:20px}.options-header button{min-height:44px}
          footer{padding:6px 14px;padding-bottom:max(6px,env(safe-area-inset-bottom))}
        }
      </style>
      <ha-card><header><div><div class="eyebrow">LOCAL CONDITIONS</div><h1></h1><div class="small">Ventura County · SCE @@PSPS_CIRCUIT@@</div><div id="mobile-power-summary" aria-live="polite">Checking circuit status…</div></div>
        <div class="toolbar"><button id="layers" aria-controls="map-options" aria-expanded="false">Layers</button><button id="home">Home</button><button id="region">Region</button><button id="refresh">Refresh</button></div></header>
        <div class="layout"><aside id="map-options" aria-label="Overlay options"><div class="options-header"><strong>Overlay options</strong><button id="close-options" aria-label="Close overlay options">Show map</button></div><section class="status" aria-live="polite"><h2 id="power-title">Checking @@PSPS_CIRCUIT@@…</h2><div id="power-details"></div></section>
        <label for="basemap">Base map</label><select id="basemap"><option value="topo">USGS topographic</option><option value="streets">Street map</option><option value="satellite">Satellite imagery</option></select>
        <div id="toggles"></div><h3>Air quality categories</h3><div class="legend" id="aqi-legend"></div>
        <h3>Radar reflectivity</h3><div class="small">Green: lighter · Yellow/red: stronger returns. Radar is precipitation reflectivity, not a rainfall forecast.</div>
        <h3>Official information</h3><p><a href="https://www.sce.com/outages-safety/outage-center/check-outage-status" target="_blank" rel="noopener">SCE outage map ↗</a></p>
        <p><a href="https://www.sce.com/outages-safety/outage-center/get-alerts" target="_blank" rel="noopener">SCE text/email alerts ↗</a></p>
        <p><a href="https://fire.airnow.gov/" target="_blank" rel="noopener">AirNow fire & smoke map ↗</a></p>
        <div id="weather-details" class="small"></div></aside><div class="map" aria-label="Local conditions map"></div></div>
        <footer><details><summary>Map notes & data freshness</summary><p>PSPS status polls every 10 minutes. Layer times show when feeds were checked; source observations may be older. Parcel lines are reference data. Circuit lines show SCE planning geometry; shutoff areas show SCE event footprints. Nearby outage markers do not confirm an outage at home. Fire perimeters may lag events.</p></details></footer>
      </ha-card>`;
    this.shadowRoot.querySelector('h1').textContent = this.config.title || 'Local Map';
    try {
      this.L = await loadLeaflet(); if (!this.isConnected) return;
      this.home = [Number(this.config.latitude), Number(this.config.longitude)];
      this.map = this.L.map(this.shadowRoot.querySelector('.map'), {zoomControl: true, scrollWheelZoom: true}).setView(this.home, this.config.zoom || 13);
      this.setBase('topo');
      this.L.circleMarker(this.home, {radius:8,color:'#fff',weight:3,fillColor:'#ff9c55',fillOpacity:1}).addTo(this.map).bindTooltip('Home', {permanent:true,direction:'right'});
      this.L.control.scale({imperial:true,metric:true}).addTo(this.map);
      this.shadowRoot.querySelector('#basemap').onchange = e => this.setBase(e.target.value);
      this.shadowRoot.querySelector('#home').onclick = () => this.map.setView(this.home, 17);
      this.shadowRoot.querySelector('#region').onclick = () => this.map.setView(this.home, 10);
      this.shadowRoot.querySelector('#refresh').onclick = () => this.refresh(true);
      this.shadowRoot.querySelector('#layers').onclick = () => this.setControlsOpen(!this.shadowRoot.querySelector('.layout').classList.contains('controls-open'));
      this.shadowRoot.querySelector('#close-options').onclick = () => this.setControlsOpen(false,true);
      this.shadowRoot.onkeydown = event => {if(event.key==='Escape'){this.setControlsOpen(false,true);}};
      this.definitions = [
        {id:'circuit',name:'@@PSPS_CIRCUIT@@ circuit lines',group:'Power',on:true,color:'#bb9eff',source:'SCE',url:ICA,params:{where:`UPPER(circuit_name) LIKE '${escapeSQL(this.config.circuit || '@@PSPS_CIRCUIT@@')}%'`,outFields:'circuit_name,substation_name'},static:true},
        {id:'psps',name:'SCE shutoff areas',on:true,color:'#ffb347',source:'SCE',special:'psps'},
        {id:'outages',name:'Nearby current outages',on:true,color:'#ff6b6b',source:'SCE',url:`${SCE}/outage/MapServer/0`,params:{where:"UPPER(Status) <> 'RESTORED'"}},
        {id:'scheduled',name:'Nearby scheduled outages',color:'#89b9ff',source:'SCE',url:`${SCE}/outage/MapServer/1`},
        {id:'fires',name:'Wildfire perimeters',group:'Weather & environment',on:true,color:'#ff554b',source:'NIFC',url:FIRE,params:{outFields:'poly_IncidentName,poly_DateCurrent,attr_PercentContained,attr_IncidentTypeCategory',where:"attr_IncidentTypeCategory = 'WF'",maxAllowableOffset:'0.001'}},
        {id:'radar',name:'Weather radar',source:'NOAA',special:'radar'},
        {id:'weather',name:'Weather warnings',source:'NWS',special:'weather'},
        {id:'aqi',name:'Air quality (AQI)',source:'EPA AirNow',url:AQI,params:{outFields:'gridcode,Timestamp',maxAllowableOffset:'0.001'}},
        {id:'parcels',name:'Property boundaries',group:'Land',color:'#66d5dc',source:'Ventura County',url:PARCELS,minZoom:16,params:{outFields:'APN,SITUS'}},
        {id:'terrain',name:'Terrain shaded relief',source:'USGS',special:'terrain'},
      ];
      const toggles = this.shadowRoot.querySelector('#toggles');
      for (const d of this.definitions) {
        if (d.group) toggles.append(node('h3',d.group));
        const label=document.createElement('label'), input=document.createElement('input'), text=document.createElement('span');
        input.type='checkbox'; input.checked=!!d.on; input.id=`toggle-${d.id}`; text.append(node('span',d.name));
        d.status = node('small',d.on ? 'Loading…' : d.minZoom ? 'Zoom to street level to see parcels' : d.source); text.append(d.status);label.append(input,text);toggles.append(label);
        input.onchange=()=>{ d.on=input.checked; if(d.on)this.loadLayer(d);else{this.requests.set(d.id,(this.requests.get(d.id)||0)+1);this.layers.get(d.id)?.remove();this.layers.delete(d.id);this.feedStatus(d,d.source);} };
      }
      ['Good','Moderate','Sensitive groups','Unhealthy','Very unhealthy','Hazardous'].forEach((text,i)=>{const item=node('span',text),swatch=document.createElement('i');swatch.style.background=COLORS[i];item.prepend(swatch);this.shadowRoot.querySelector('#aqi-legend').append(item);});
      this.map.on('moveend',()=>{clearTimeout(this.moveTimer);this.moveTimer=setTimeout(()=>this.refresh(false),500);});
      this.observer=new ResizeObserver(()=>this.map?.invalidateSize()); this.observer.observe(this.shadowRoot.querySelector('.map'));
      this.timer=setInterval(()=>this.refresh(true),300000);
      this.refresh(true); this.updateStatus();
    } catch(error) { this.shadowRoot.querySelector('#power-title').textContent=error.message; }
    finally {this.starting=false;}
  }
  setControlsOpen(open,returnFocus=false) {
    this.shadowRoot.querySelector('.layout').classList.toggle('controls-open',open);
    this.shadowRoot.querySelector('#layers').setAttribute('aria-expanded',String(open));
    if(open){this.shadowRoot.querySelector('#map-options').scrollTop=0;this.shadowRoot.querySelector('#close-options').focus({preventScroll:true});}
    else {if(returnFocus)this.shadowRoot.querySelector('#layers').focus({preventScroll:true});requestAnimationFrame(()=>this.map?.invalidateSize());}
  }
  setBase(name) {
    this.base?.remove();
    const sources={
      streets:['https://services.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}','Esri, HERE, Garmin, USGS, OpenStreetMap contributors'],
      topo:['https://basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer/tile/{z}/{y}/{x}','USGS The National Map'],
      satellite:['https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}','Esri, Maxar, Earthstar Geographics'],
    };
    const [url,attribution]=sources[name];
    this.base=this.L.tileLayer(url,{attribution,maxZoom:19,maxNativeZoom:name==='topo'?16:19}).addTo(this.map);
    this.base.on('tileerror',()=>{this.baseError=true;this.shadowRoot.querySelector('.map').setAttribute('aria-label','Map: some base-map tiles could not load');});
    this.base.setZIndex(0);
  }
  feedStatus(d,text,error=false) {d.status.textContent=text;d.status.classList.toggle('feed-error',error);}
  envelope() {const b=this.map.getBounds();return JSON.stringify({xmin:b.getWest(),ymin:b.getSouth(),xmax:b.getEast(),ymax:b.getNorth(),spatialReference:{wkid:4326}});}
  async request(url) {
    if (!url.startsWith(SCE)) return getJSON(url);
    if (!this._hass?.callApi) throw new Error('Home Assistant connection unavailable');
    const parsed=new URL(url), path=parsed.pathname;
    const layer=path.includes('/psps/')?`psps${path.includes('/0/')?'0':'1'}`:path.includes('/0/')?'outages':'scheduled';
    return this._hass.callApi('GET',`local_map/${layer}${parsed.search}`);
  }
  async loadLayer(d,force=false) {
    if (!this.map || !d.on || (d.static && this.layers.has(d.id) && !force)) return;
    if (d.minZoom && this.map.getZoom()<d.minZoom) {this.requests.set(d.id,(this.requests.get(d.id)||0)+1);this.layers.get(d.id)?.remove();this.layers.delete(d.id);this.feedStatus(d,'Zoom in to level 16 for parcels');return;}
    const version=(this.requests.get(d.id)||0)+1;this.requests.set(d.id,version);
    const current=()=>this.map && d.on && this.requests.get(d.id)===version;
    this.feedStatus(d,`${d.source} · Loading…`);
    try {
      let layer;
      if (d.special==='radar') {
        layer=this.L.tileLayer.wms('https://opengeo.ncep.noaa.gov/geoserver/conus/conus_bref_qcd/ows', {layers:'conus_bref_qcd',format:'image/png',transparent:true,opacity:0.6,attribution:'NOAA/NWS radar',version:'1.3.0',_refresh:force?Date.now():''});
      } else if (d.special==='terrain') {
        layer=this.L.tileLayer('https://basemap.nationalmap.gov/arcgis/rest/services/USGSShadedReliefOnly/MapServer/tile/{z}/{y}/{x}',{opacity:0.4,attribution:'USGS shaded relief',maxNativeZoom:15,maxZoom:19});
      } else {
        const extent = {geometry:this.envelope(),geometryType:'esriGeometryEnvelope',inSR:'4326',spatialRel:'esriSpatialRelIntersects'};
        let data;
        if(d.special==='psps'){
          const results=await Promise.all([0,1].map(n=>queryFeatures(`${SCE}/psps/MapServer/${n}`,{...extent,outFields:'CIRCUIT_NAME,PSPS,StartDate,EndDate,ERT,POCNotes,ERTNotes,PSPS_Details'},url=>this.request(url))));
          data={type:'FeatureCollection',features:results.flatMap(r=>r.features)};
        } else if(d.special==='weather') {
          data=await getJSON(`https://api.weather.gov/alerts/active?point=${this.home[0]},${this.home[1]}`);
          const details=this.shadowRoot.querySelector('#weather-details');
          if(current()){details.replaceChildren(node('strong',`${data.features.length} weather alerts for home`));for(const f of data.features)details.append(node('p',f.properties.headline || f.properties.event));}
        } else data=await queryFeatures(d.url,{...(d.static?{}:extent),...d.params},url=>this.request(url));
        if(!current())return;
        layer=this.L.geoJSON(data,{
          attribution:d.source,
          style:f=>({color:d.id==='aqi'?COLORS[Math.min(5,Math.max(0,Number(f.properties.gridcode)-1))]:d.color||'#ffb347',weight:d.id==='circuit'?3:2,fillOpacity:d.id==='aqi'?0.28:d.id==='parcels'?0.02:0.15}),
          pointToLayer:(_f,ll)=>this.L.circleMarker(ll,{radius:7,color:d.color||'#ffb347',fillOpacity:0.8}),
          onEachFeature:(f,l)=>l.bindPopup(this.popup(d,f.properties)),
        });
        this.feedStatus(d,`${data.features.length} features · checked ${new Date().toLocaleTimeString()}`);
      }
      if(!current())return;
      this.layers.get(d.id)?.remove(); this.layers.set(d.id,layer);layer.addTo(this.map);
      if(d.special==='radar'||d.special==='terrain'){
        let failed=false;
        layer.on('tileerror',()=>{failed=true;this.feedStatus(d,`${d.source} · tiles unavailable`,true);});
        layer.on('load',()=>{if(!failed)this.feedStatus(d,`${d.source} · checked ${new Date().toLocaleTimeString()}`);});
      }
    } catch(error) {if(current())this.feedStatus(d,`${this.layers.has(d.id)?'Previous data · ':''}Feed unavailable: ${error.message}`,true);}
  }
  popup(d,p) {
    const box=document.createElement('div');box.append(node('strong',d.name));
    const fields={circuit:['circuit_name','substation_name'],psps:['CIRCUIT_NAME','PSPS','StartDate','EndDate','ERT','POCNotes','ERTNotes'],parcels:['APN','SITUS'],fires:['poly_IncidentName','attr_PercentContained','poly_DateCurrent'],aqi:['gridcode','Timestamp'],weather:['headline','expires']};
    const names=fields[d.id]||['OanNo','MemoCauseCdDesc','CrewStatusCdDesc','NoOfAffectedCust_Inci','OutageStartDateTime','ERT','Status'];
    const labels={circuit_name:'Circuit',CIRCUIT_NAME:'Circuit',substation_name:'Substation',PSPS:'Shutoff status',StartDate:'Window begins',EndDate:'Window ends',ERT:'Expected restoration',POCNotes:'Shutoff notes',ERTNotes:'Restoration notes',APN:'Parcel number',SITUS:'Address',poly_IncidentName:'Fire',attr_PercentContained:'Contained (%)',poly_DateCurrent:'Perimeter updated',gridcode:'AQI category',Timestamp:'Observation time',headline:'Warning',expires:'Expires',OanNo:'Outage number',MemoCauseCdDesc:'Cause',CrewStatusCdDesc:'Crew status',NoOfAffectedCust_Inci:'Affected customers',OutageStartDateTime:'Outage began',Status:'Status'};
    for(const key of names){if(p[key]===null||p[key]===undefined)continue;let value=p[key];if(['StartDate','EndDate','ERT','OutageStartDateTime','poly_DateCurrent','Timestamp','expires'].includes(key))value=stamp(value);if(key==='gridcode')value=['Good','Moderate','Unhealthy for sensitive groups','Unhealthy','Very unhealthy','Hazardous'][Number(value)-1]||value;box.append(node('p',`${labels[key]||key}: ${value}`));}
    return box;
  }
  refresh(force) {
    this.definitions?.filter(d=>d.on).forEach(d=>{if(!force && ['radar','terrain','weather'].includes(d.special))return;this.loadLayer(d,force);});
    if(force&&this._hass?.states[this.config.status_entity||'sensor.power_shutoff'])this._hass.callService('homeassistant','update_entity',{entity_id:this.config.status_entity||'sensor.power_shutoff'}).catch(()=>{});
    this.updateStatus();
  }
  updateStatus() {
    const entity=this._hass?.states[this.config.status_entity||'sensor.power_shutoff'];
    const title=this.shadowRoot.querySelector('#power-title'),details=this.shadowRoot.querySelector('#power-details');if(!title)return;
    const labels={under_consideration:'PSPS under consideration',power_shutoff:'SCE lists power shut off',no_psps_listed:'No PSPS currently listed',unavailable:'SCE feed unavailable',unknown:'Waiting for SCE feed'};
    title.textContent=labels[entity?.state]||'Waiting for SCE feed';
    const stale=entity?.attributes.checked_at && Date.now()-new Date(entity.attributes.checked_at).getTime()>900000;
    if(stale)title.textContent='SCE status is stale';
    const mobileSummary=this.shadowRoot.querySelector('#mobile-power-summary');
    mobileSummary.textContent=title.textContent;
    mobileSummary.classList.toggle('alert',stale||['under_consideration','power_shutoff','unavailable'].includes(entity?.state));
    this.shadowRoot.querySelector('.status').classList.toggle('alert',stale||['under_consideration','power_shutoff','unavailable'].includes(entity?.state));
    details.replaceChildren(node('p',`Circuit: ${this.config.circuit||'@@PSPS_CIRCUIT@@'}`));
    for(const event of entity?.attributes.events||[]){details.append(node('p',`${event.PSPS || event.PSPS_Details || 'PSPS event'} · ${stamp(event.StartDate)} – ${stamp(event.EndDate)}`));if(event.POCNotes)details.append(node('p',event.POCNotes));if(event.ERTNotes)details.append(node('p',event.ERTNotes));}
    details.append(node('div',`Checked: ${stamp(entity?.attributes.checked_at)}`));
    if(entity?.state==='unavailable'||stale)details.append(node('p','Check the official SCE map for current status.'));
  }
}
if(!customElements.get('local-map-card'))customElements.define('local-map-card',LocalMapCard);
window.customCards=window.customCards||[];
window.customCards.push({type:'local-map-card',name:'Local Map',description:'Local weather, wildfire, AQI, parcels and SCE circuit status'});
