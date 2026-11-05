(()=>{
const dataNode=document.querySelector('#report-data');if(!dataNode)return;
const data=JSON.parse(dataNode.textContent),NS='http://www.w3.org/2000/svg';
const colors={PENDIENTE_LLEGADA:'#829ab7',EN_ESPERA:'#e7ad4c',LLAMADO:'#4d8bc6',EN_ATENCION:'#9774cc',ATENDIDO:'#329a87',AUSENTE:'#bd8175',CANCELADO:'#9ca7ae'};
const states=Object.keys(colors).map(state=>[state,data.states[state]||0]);
let selected=null;
const el=(tag,attributes={},text)=>{const n=document.createElementNS(NS,tag);Object.entries(attributes).forEach(([k,v])=>n.setAttribute(k,v));if(text!==undefined)n.textContent=text;return n;};
const svg=(w,h,label)=>el('svg',{viewBox:`0 0 ${w} ${h}`,role:'img','aria-label':label});
const total=counts=>selected?counts[selected]:Object.values(counts).reduce((a,b)=>a+b,0);
function change(state){selected=selected===state?null:state;render();document.querySelector(`#state-legend button[data-state="${state}"]`)?.focus({preventScroll:true});}
function empty(container){const p=document.createElement('p');p.className='empty-chart';p.textContent='Todavía no hay turnos para este filtro.';container.replaceChildren(p);}
function renderDonut(){
 const holder=document.querySelector('#state-chart');const chart=svg(220,220,'Distribución de turnos por estado');
 const radius=76,length=2*Math.PI*radius;chart.append(el('circle',{cx:110,cy:110,r:radius,fill:'none',stroke:'#edf2f4','stroke-width':24}));
 let offset=0;
 states.forEach(([state,count])=>{if(!count||!data.total)return;const segment=el('circle',{cx:110,cy:110,r:radius,fill:'none',stroke:colors[state],'stroke-width':24,'stroke-dasharray':`${length*count/data.total} ${length}`,'stroke-dashoffset':-offset,transform:'rotate(-90 110 110)',opacity:!selected||selected===state?1:.18,tabindex:0,role:'button','aria-label':`${data.labels[state]}: ${count}`,'aria-pressed':selected===state?'true':'false'});offset+=length*count/data.total;segment.append(el('title',{},`${data.labels[state]}: ${count} turnos`));segment.addEventListener('click',()=>change(state));segment.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();change(state);}});chart.append(segment);});
 chart.append(el('text',{x:110,y:110,'text-anchor':'middle',class:'donut-number'},selected?data.states[selected]:data.total));chart.append(el('text',{x:110,y:134,'text-anchor':'middle',class:'donut-caption'},selected?'seleccionados':'turnos'));holder.replaceChildren(chart);
 const legend=document.querySelector('#state-legend');legend.replaceChildren();states.forEach(([state,count])=>{const b=document.createElement('button');b.type='button';b.dataset.state=state;b.className='legend-button'+(selected===state?' is-selected':'');b.setAttribute('aria-pressed',selected===state?'true':'false');const dot=document.createElement('i');dot.style.background=colors[state];const name=document.createElement('span');name.textContent=data.labels[state];const value=document.createElement('strong');value.textContent=count;b.append(dot,name,value);b.onclick=()=>change(state);legend.append(b);});
}
function renderTrend(){
 const holder=document.querySelector('#trend-chart');if(!data.total){empty(holder);return;}
 const series=data.start===data.end?data.hours:data.days;const single=data.start===data.end;const chart=svg(600,240,single?'Solicitudes por hora':'Turnos por fecha');const points=series.map(d=>total(d.counts)),maximum=Math.max(1,...points),left=38,right=580,top=22,bottom=194;
 const x=i=>points.length===1?310:left+i/(points.length-1)*(right-left),y=v=>bottom-v/maximum*(bottom-top);
 [0,.5,1].forEach(f=>{const yy=y(maximum*f);chart.append(el('line',{x1:left,x2:right,y1:yy,y2:yy,stroke:'#e7eef0','stroke-dasharray':'4 5'}));chart.append(el('text',{x:27,y:yy+4,'text-anchor':'end',class:'axis-label'},Math.round(maximum*f)));});
 const line=points.map((v,i)=>`${x(i)},${y(v)}`).join(' ');chart.append(el('polyline',{points:line,fill:'none',stroke:selected?colors[selected]:'#218c81','stroke-width':3,'stroke-linejoin':'round'}));
 points.forEach((v,i)=>{const label=`${single?series[i].hour:series[i].day}: ${v} turnos`;const p=el('circle',{cx:x(i),cy:y(v),r:4,fill:selected?colors[selected]:'#218c81',tabindex:0,'aria-label':label,class:'trend-point'});p.append(el('title',{},label));chart.append(p);if(i===0||i===points.length-1||i%Math.max(1,Math.ceil(points.length/5))===0)chart.append(el('text',{x:x(i),y:220,'text-anchor':'middle',class:'axis-label'},single?series[i].hour:series[i].day.slice(5).split('-').reverse().join('/')));});holder.replaceChildren(chart);
}
function renderSpecialties(){const holder=document.querySelector('#specialty-chart');const list=data.specialties.map(s=>({...s,value:total(s.counts)})).sort((a,b)=>b.value-a.value);if(!list.length){empty(holder);return;}const max=Math.max(1,...list.map(s=>s.value));holder.replaceChildren();list.forEach(s=>{const row=document.createElement('div');row.className='specialty-row';const label=document.createElement('span');label.textContent=s.name;const track=document.createElement('div');track.className='bar-track';track.tabIndex=0;track.setAttribute('aria-label',`${s.name}: ${s.value} turnos`);track.title=`${s.name}: ${s.value} turnos`;const bar=document.createElement('i');bar.style.width=(s.value/max*100)+'%';bar.style.background=selected?colors[selected]:'#329a87';track.append(bar);const value=document.createElement('strong');value.textContent=s.value;row.append(label,track,value);holder.append(row);});}
function render(){renderDonut();renderTrend();renderSpecialties();document.querySelector('#chart-selection').textContent=selected?`${data.labels[selected]} · ${data.states[selected]} turnos`:'Todos los estados';document.querySelectorAll('[data-report-state]').forEach(row=>row.hidden=!!selected&&row.dataset.reportState!==selected);const a=document.querySelector('#export-report'),url=new URL(a.href);if(selected)url.searchParams.set('estado',selected);else url.searchParams.delete('estado');a.href=url.toString();}
document.querySelector('#reset-chart').onclick=()=>{selected=null;render();};render();
})();
