"""Credenciales privadas separadas por hospital; nunca van a la sesion del navegador."""
import base64
import hashlib
import json
import os
import secrets
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]
SCOPES=['openid','https://www.googleapis.com/auth/userinfo.email','https://www.googleapis.com/auth/gmail.send']
_locks={}
_guard=threading.Lock()

def lock(hospital_id):
    with _guard:
        return _locks.setdefault(int(hospital_id),threading.RLock())

def path(hospital_id):
    identity=int(hospital_id)
    if identity<=0: raise ValueError('Hospital invalido')
    return ROOT/'.private'/'gmail'/f'{identity}.enc'

def cipher():
    from cryptography.fernet import Fernet
    secret=os.environ.get('SECRET_KEY','')
    if len(secret)<32: raise ValueError('Falta SECRET_KEY')
    key=hashlib.sha256(('mediturno-gmail-v1:'+secret).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))

def read(hospital_id):
    with lock(hospital_id):
        if os.getenv('GMAIL_STORAGE','files')=='postgres':
            from models.database import transaction
            with transaction() as c:
                c.execute('SELECT contenido_cifrado FROM configuraciones_correo WHERE id_hospital=%s',
                          (int(hospital_id),))
                row=c.fetchone()
            return json.loads(cipher().decrypt(row['contenido_cifrado'].encode())) if row else {}
        file=path(hospital_id)
        return json.loads(cipher().decrypt(file.read_bytes())) if file.exists() else {}

def write(hospital_id,data):
    with lock(hospital_id):
        if os.getenv('GMAIL_STORAGE','files')=='postgres':
            from models.database import transaction
            encrypted=cipher().encrypt(json.dumps(data).encode()).decode()
            with transaction() as c:
                c.execute('''INSERT INTO configuraciones_correo(id_hospital,contenido_cifrado)
                             VALUES(%s,%s) ON CONFLICT(id_hospital) DO UPDATE
                             SET contenido_cifrado=excluded.contenido_cifrado,actualizado_en=now()''',
                          (int(hospital_id),encrypted))
            return
        file=path(hospital_id)
        file.parent.mkdir(parents=True,exist_ok=True)
        temporary=file.with_suffix('.'+secrets.token_hex(8)+'.tmp')
        try:
            temporary.write_bytes(cipher().encrypt(json.dumps(data).encode()))
            temporary.replace(file)
        finally:
            temporary.unlink(missing_ok=True)

def validate_config(data):
    web=data.get('web') if isinstance(data,dict) else None
    if not isinstance(web,dict):
        raise ValueError('Carga el JSON de Aplicacion web; el de escritorio no sirve para este panel.')
    client=web.get('client_id','')
    secret=web.get('client_secret','')
    if not isinstance(client,str) or not client.endswith('.apps.googleusercontent.com') or len(client)>300:
        raise ValueError('Identificador de cliente Google invalido.')
    if not isinstance(secret,str) or not 10<=len(secret)<=500:
        raise ValueError('Credencial de cliente invalida.')
    # No confiar en endpoints subidos: solo endpoints oficiales de Google.
    if web.get('auth_uri') not in ('https://accounts.google.com/o/oauth2/auth','https://accounts.google.com/o/oauth2/v2/auth'):
        raise ValueError('Endpoint de autorizacion invalido.')
    if web.get('token_uri') not in ('https://oauth2.googleapis.com/token','https://accounts.google.com/o/oauth2/token'):
        raise ValueError('Endpoint de token invalido.')
    return {'web':{k:web[k] for k in ('client_id','client_secret','auth_uri','token_uri')}}

def redirect_uri():
    uri=os.getenv('GMAIL_REDIRECT_URI','http://127.0.0.1:5000/correo/respuesta')
    parsed=urlsplit(uri)
    if parsed.path!='/correo/respuesta' or parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise ValueError('GMAIL_REDIRECT_URI invalida.')
    if parsed.scheme!='https' and not (parsed.scheme=='http' and parsed.hostname in ('localhost','127.0.0.1')):
        raise ValueError('La direccion de retorno requiere HTTPS, salvo en localhost.')
    return uri

def make_flow(data,**kwargs):
    from google_auth_oauthlib.flow import Flow
    return Flow.from_client_config(data['config'],scopes=SCOPES,redirect_uri=redirect_uri(),**kwargs)

def begin(hospital_id,user_id):
    with lock(hospital_id):
        data=read(hospital_id)
        if not data.get('config'): raise ValueError('Carga primero el JSON web.')
        verifier=secrets.token_urlsafe(64)
        nonce=secrets.token_urlsafe(32)
        flow=make_flow(data,code_verifier=verifier,autogenerate_code_verifier=False)
        url,state=flow.authorization_url(access_type='offline',prompt='consent select_account',nonce=nonce)
        data['pending']={'state':state,'verifier':verifier,'nonce':nonce,'user':user_id,'created':time.time()}
        write(hospital_id,data)
        return url,state

def complete(hospital_id,user_id,state,code):
    from google.oauth2 import id_token
    from google.auth.transport.requests import Request
    with lock(hospital_id):
        data=read(hospital_id)
        pending=data.get('pending',{})
        if (not state or not secrets.compare_digest(str(pending.get('state','')),str(state)) or
            pending.get('user')!=user_id or time.time()-pending.get('created',0)>600):
            raise ValueError('Autorizacion vencida o no valida. Conecta nuevamente.')
        # Consumir el state antes del intercambio; callback repetido no es valido.
        data.pop('pending',None)
        write(hospital_id,data)
        flow=make_flow(data,state=state,code_verifier=pending['verifier'],autogenerate_code_verifier=False)
        flow.fetch_token(code=code,timeout=20)
        info=id_token.verify_oauth2_token(flow.oauth2session.token.get('id_token',''),Request(),data['config']['web']['client_id'])
        if not secrets.compare_digest(str(info.get('nonce','')),pending['nonce']) or info.get('email_verified') is not True:
            raise ValueError('No se pudo verificar la cuenta autorizada.')
        granted=flow.oauth2session.token.get('scope','')
        granted=granted.split() if isinstance(granted,str) else granted
        if 'https://www.googleapis.com/auth/gmail.send' not in granted:
            raise ValueError('Debes conceder el permiso para enviar correos.')
        credentials=json.loads(flow.credentials.to_json())
        if not credentials.get('refresh_token'):
            raise ValueError('Google no entrego acceso sin conexion; vuelve a conectar y aceptar.')
        email=info.get('email','')
        if not isinstance(email,str) or '@' not in email or '\n' in email or '\r' in email:
            raise ValueError('Correo autorizado invalido.')
        data.update(credentials=credentials,email=email,connected_at=time.time())
        write(hospital_id,data)
        return email

def service(hospital_id):
    import httplib2
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_httplib2 import AuthorizedHttp
    from googleapiclient.discovery import build
    data=read(hospital_id)
    if not data.get('credentials'): raise ValueError('Hospital sin Gmail conectado.')
    creds=Credentials.from_authorized_user_info(data['credentials'],SCOPES)
    if not creds.valid:
        creds.refresh(Request())
        data['credentials']=json.loads(creds.to_json())
        write(hospital_id,data)
    return build('gmail','v1',http=AuthorizedHttp(creds,http=httplib2.Http(timeout=20)),cache_discovery=False)

def disconnect(hospital_id):
    # Desconexion local por hospital; no revocar todo el proyecto Google compartido.
    with lock(hospital_id):
        data=read(hospital_id)
        write(hospital_id,{'config':data['config']} if data.get('config') else {})
