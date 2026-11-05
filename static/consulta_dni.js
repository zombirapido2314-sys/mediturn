(()=>{
const button=document.querySelector('#consultar-dni');
if(!button)return;
const form=document.querySelector('#registro-presencial');
const status=document.querySelector('#estado-dni');
const verification=form.elements.verificacion_dni;
button.addEventListener('click',async()=>{
 button.disabled=true;status.textContent='Consultando DNI en APIS Perú…';
 try{
  const response=await fetch(button.dataset.url,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams({csrf:form.elements.csrf.value,numero_documento:form.elements.numero_documento.value})});
  if(!(response.headers.get('Content-Type')||'').includes('application/json'))throw new Error('La sesión venció o la consulta no está disponible. Recarga la página.');
  const payload=await response.json();
  if(!response.ok||!payload.ok)throw new Error(payload.message||'No se pudo consultar. Puedes continuar manualmente.');
  form.elements.nombres.value=payload.data.nombres;
  form.elements.apellidos.value=payload.data.apellidos;
  form.elements.nombres.readOnly=true;form.elements.apellidos.readOnly=true;
  verification.value=payload.verification;
  status.textContent='Datos recibidos de APIS Perú. Verifica la identidad de la persona presente.';
 }catch(error){status.textContent=error.message||'No se pudo consultar. Puedes continuar manualmente.';}
 finally{button.disabled=false;}
});
document.querySelector('#ingreso-manual').addEventListener('click',()=>{
 verification.value='';form.elements.nombres.readOnly=false;form.elements.apellidos.readOnly=false;
 status.textContent='Ingreso manual seleccionado. Verifica los datos con el documento presentado.';
 form.elements.nombres.focus();
});
})();
