(()=>{
const header=document.querySelector('main>header');
if(header&&'ResizeObserver' in window)new ResizeObserver(()=>document.documentElement.style.setProperty('--header-height',header.offsetHeight+'px')).observe(header);
const sections=[...document.querySelectorAll('body[data-page="admin.index"] article[id]')];
if(sections.length){
 const key='mediturno-admin-tab-'+(document.body.dataset.hospital||'local');let previous='';try{previous=sessionStorage.getItem(key)||'';}catch{}
 const ids=sections.map(s=>s.id);function select(id){if(!ids.includes(id))id=ids[0];sections.forEach(s=>s.hidden=s.id!==id);document.querySelectorAll('.tabs a[href^="#"]').forEach(a=>{a.classList.toggle('tab-active',a.hash==='#'+id);a.setAttribute('aria-current',a.hash==='#'+id?'true':'false');});try{sessionStorage.setItem(key,id);}catch{}}
 document.querySelectorAll('a[href^="#"]').forEach(a=>{if(ids.includes(a.hash.slice(1)))a.addEventListener('click',()=>select(a.hash.slice(1)));});
 window.addEventListener('hashchange',()=>select(location.hash.slice(1)));select(location.hash.slice(1)||previous);
}
const notices=document.querySelectorAll('.notice');notices.forEach(n=>{const b=document.createElement('button');b.type='button';b.className='dismiss-notice';b.textContent='×';b.setAttribute('aria-label','Cerrar aviso');b.onclick=()=>n.remove();n.append(b);});
})();
