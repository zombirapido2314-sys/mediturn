import base64
import json
import secrets
from services.correo_presentacion import build_message
from datetime import datetime
from zoneinfo import ZoneInfo
import uuid
from urllib.parse import urlsplit
from flask import Blueprint,render_template,request,redirect,url_for,flash,g,session,abort
from controllers.administracion_controller import admin_required
from services import correo_google as gmail

correo=Blueprint('correo',__name__)

@correo.after_request
def private_response(response):
    response.headers['Cache-Control']='no-store'
    response.headers['Referrer-Policy']='no-referrer'
    return response

def home(): return redirect(url_for('correo.index'))

@correo.get('/administracion/correo')
@admin_required
def index():
    try:
        data=gmail.read(g.user['id_hospital'])
        return render_template('correo.html',connected=bool(data.get('credentials')),email=data.get('email'),configured=bool(data.get('config')),callback=gmail.redirect_uri())
    except Exception:
        flash('No se pudo leer la configuracion. Verifica dependencias y que SECRET_KEY no haya cambiado.','error')
        return render_template('correo.html',connected=False,email=None,configured=False,callback=gmail.redirect_uri()),503

@correo.post('/administracion/correo/configurar')
@admin_required
def configure():
    file=request.files.get('credenciales')
    try:
        if not file: raise ValueError('Selecciona el JSON de Aplicacion web.')
        config=gmail.validate_config(json.loads(file.read(12000).decode('utf-8-sig')))
        with gmail.lock(g.user['id_hospital']):
            gmail.write(g.user['id_hospital'],{'config':config})
        session.pop('gmail_state',None)
        flash('JSON web guardado. Ahora conecta la cuenta de Google.','ok')
    except ValueError as error: flash(str(error) if not isinstance(error,json.JSONDecodeError) else 'El archivo no contiene un JSON valido.','error')
    except Exception: flash('No se pudo guardar la configuracion de correo.','error')
    return home()

@correo.post('/administracion/correo/conectar')
@admin_required
def connect():
    try:
        uri=urlsplit(gmail.redirect_uri())
        if request.host_url.rstrip('/')!=f'{uri.scheme}://{uri.netloc}':
            flash('Abre MediTurno desde '+f'{uri.scheme}://{uri.netloc}'+' para conectar Google.','error')
            return home()
        url,state=gmail.begin(g.user['id_hospital'],g.user['id'])
        session['gmail_state']={'state':state,'hospital':g.user['id_hospital']}
        return redirect(url)
    except Exception: flash('No se pudo iniciar Google. Carga el JSON web y revisa las dependencias.','error')
    return home()

@correo.get('/correo/respuesta')
@admin_required
def callback():
    saved=session.pop('gmail_state',{})
    state=request.args.get('state','')
    if saved.get('hospital')!=g.user['id_hospital'] or not state or not secrets.compare_digest(saved.get('state',''),state):
        abort(400,'Autorizacion no valida. Vuelve al panel y conecta nuevamente.')
    if request.args.get('error'):
        flash('Google no concedio la autorizacion. Puedes intentarlo nuevamente.','error')
        return home()
    try:
        gmail.complete(g.user['id_hospital'],g.user['id'],state,request.args.get('code',''))
        flash('Cuenta de Google conectada a tu hospital. Los avisos se enviaran automaticamente.','ok')
    except Exception:
        flash('No se pudo completar Google. Revisa Gmail API, usuario de prueba, URL de retorno y permisos; vuelve a conectar.','error')
    return home()

@correo.post('/administracion/correo/desconectar')
@admin_required
def disconnect():
    try:
        gmail.disconnect(g.user['id_hospital'])
        session.pop('gmail_state',None)
        flash('Cuenta desconectada de este hospital. Se detuvo el envio desde esta instalacion.','ok')
    except Exception: flash('No se pudo desconectar. Revisa la configuracion privada.','error')
    return home()

@correo.post('/administracion/correo/prueba')
@admin_required
def test():
    api=None
    try:
        with gmail.lock(g.user['id_hospital']):
            data=gmail.read(g.user['id_hospital'])
            if not data.get('credentials'): raise ValueError('Sin conexion')
            api=gmail.service(g.user['id_hospital'])
            message=build_message(dict(tipo='PRUEBA',prefijo='DEMO',numero=0,fecha=datetime.now(ZoneInfo('America/Lima')).date(),
                hospital=g.user.get('hospital_nombre','Hospital actual'),especialidad='Conexión de avisos',consultorio=None,
                destinatario=data['email'],remitente=data['email'],id_notificacion='prueba-'+uuid.uuid4().hex,delante=0))
            api.users().messages().send(userId='me',body={'raw':base64.urlsafe_b64encode(message.as_bytes()).decode()}).execute(num_retries=0)
        flash('Gmail acepto el correo de prueba dirigido a la misma cuenta conectada.','ok')
    except Exception: flash('Envio fallido o incierto. Revisa Enviados y la autorizacion antes de repetir.','error')
    finally:
        if api: api.close()
    return home()
