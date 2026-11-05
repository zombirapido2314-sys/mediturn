import re
from functools import wraps
from flask import Blueprint,request,render_template,g,abort,redirect,url_for,flash,jsonify,current_app
from werkzeug.security import generate_password_hash
from controllers.web import login_required,action
from models import administracion as model
from models.mediturno import RuleError
from models import presencial,mediturno
from psycopg2 import IntegrityError
from services import documentos_api
from itsdangerous import URLSafeTimedSerializer,BadSignature

admin=Blueprint('admin',__name__)

def admin_required(fn):
    @wraps(fn)
    @login_required('personal')
    def wrapped(*args,**kwargs):
        if g.user['rol']!='ADMINISTRADOR': abort(403)
        return fn(*args,**kwargs)
    return wrapped

def text(name,maximum):
    value=request.form.get(name,'').strip()
    if not 1<=len(value)<=maximum: raise RuleError('Revisa el campo '+name+'.')
    return value

@admin.get('/administracion')
@admin_required
def index():
    data=model.data(g.user['id_hospital'])
    from services.correo_google import read
    try:
        mail=bool(read(g.user['id_hospital']).get('credentials'))
    except Exception:
        mail=False
    enabled={e['id_especialidad'] for e in data['specialties'] if e['habilitada'] and e['activa']}
    active_rooms={r['id_consultorio']:r for r in data['rooms'] if r['activo'] and r['id_especialidad'] in enabled}
    staff={u['id_usuario'] for u in data['users'] if u['activo'] and u['rol']=='ATENCION'}
    assigned={a['id_usuario'] for a in data['assignments'] if a['activa'] and a['id_consultorio'] in active_rooms}
    stages=[('Especialidades',bool(enabled),'#especialidades'),
            ('Consultorios',bool(enabled) and enabled <= {r['id_especialidad'] for r in active_rooms.values()},'#consultorios'),
            ('Personal',bool(staff),'#personal'),('Asignaciones',bool(staff) and staff<=assigned,'#asignaciones'),
            ('Correo',mail,url_for('correo.index'))]
    progress=[]
    next_found=False
    for label,done,link in stages:
        state='done' if done else 'todo' if next_found else 'next'
        if not done: next_found=True
        progress.append({'label':label,'done':done,'state':state,'link':link})
    return render_template('administracion.html',progress=progress,completed=sum(s['done'] for s in progress),**data)

def save():
    h=g.user['id_hospital']
    operation=request.form.get('operation')
    identity=request.form.get('identity',type=int)
    active=request.form.get('active')=='1'
    if operation=='user':
        names,surnames,email=text('nombres',80),text('apellidos',80),text('correo',254)
        password=request.form.get('password','')
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email) or not 10<=len(password)<=128:
            raise RuleError('Correo invalido o contraseña fuera del rango de 10 a 128 caracteres.')
        model.add_user(h,names,surnames,email,generate_password_hash(password),request.form.get('rol',type=int))
    elif operation=='user_active': model.toggle_user(h,g.user['id'],identity,active)
    elif operation=='specialty': model.set_specialty(h,identity,active)
    elif operation=='new_specialty':
        name,prefix=text('nombre',100),text('prefijo',8).upper()
        if not re.fullmatch('[A-Z]{2,8}',prefix): raise RuleError('El prefijo debe tener entre 2 y 8 letras, sin espacios ni numeros.')
        model.add_specialty(h,name,prefix)
    elif operation=='room': model.add_room(h,text('nombre',80),request.form.get('especialidad',type=int))
    elif operation=='room_active': model.toggle_room(h,identity,active)
    elif operation=='assign': model.assign(h,request.form.get('usuario',type=int),request.form.get('consultorio',type=int))
    elif operation=='unassign': model.remove_assignment(h,identity)
    else: raise RuleError('Operacion no valida.')

@admin.post('/administracion/guardar')
@admin_required
def store():
    action(save)
    return redirect(url_for('admin.index'))

@admin.get('/pacientes')
@login_required('personal')
def patients():
    if g.user['rol'] not in ('ADMINISTRADOR','RECEPCION'): abort(403)
    search=request.args.get('buscar','').strip()[:80]
    return render_template('pacientes.html',patients=model.patients(g.user['id_hospital'],search),search=search)

def reception_required(fn):
    @wraps(fn)
    @login_required('personal')
    def wrapped(*args,**kwargs):
        if g.user['rol'] not in ('ADMINISTRADOR','RECEPCION'): abort(403)
        if g.user.get('hospital_origen',g.user['id_hospital'])!=g.user['id_hospital']: abort(403)
        return fn(*args,**kwargs)
    return wrapped

def document_valid(kind,document):
    pattern={'DNI':r'[0-9]{8}','CE':r'[A-Z0-9]{9,12}','PASAPORTE':r'[A-Z0-9]{6,20}'}.get(kind,r'(?!)')
    return bool(re.fullmatch(pattern,document))

@admin.route('/recepcion/presencial',methods=['GET','POST'])
@reception_required
def walk_in():
    values=request.form if request.method=='POST' else request.args
    kind=values.get('tipo_documento','DNI')
    document=values.get('numero_documento','').strip().upper()
    patient=None
    data={k:values.get(k,'').strip() for k in ('nombres','apellidos','correo')}
    verification=request.form.get('verificacion_dni','') if request.method=='POST' else ''
    verification_error=False
    if verification:
        try:
            record=dni_signer().loads(verification,max_age=900)
            if (record['user']!=g.user['id'] or record['hospital']!=g.user['id_hospital'] or
                kind!='DNI' or record['dni']!=document or any(presencial.normalize(data[k])!=presencial.normalize(record[k]) for k in ('nombres','apellidos'))):
                raise ValueError('Datos alterados')
        except (BadSignature,ValueError,KeyError,TypeError):
            flash('La consulta de DNI vencio o los datos cambiaron. Consulta nuevamente o usa ingreso manual.','error')
            verification_error=True
    if document and document_valid(kind,document):
        patient=presencial.find_patient(g.user['id_hospital'],kind,document)
        if patient and request.method=='GET':
            data={k:patient[k] or '' for k in ('nombres','apellidos','correo')}
    elif document or request.method=='POST':
        flash('Revisa el tipo y numero de documento.','error')
        document=''
    if request.method=='POST' and document and not verification_error:
        specialty=request.form.get('especialidad',type=int)
        consent=request.form.get('alertas')=='si'
        email_ok=not data['correo'] or (len(data['correo'])<=254 and re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',data['correo']))
        if not all(1<=len(data[k])<=80 for k in ('nombres','apellidos')) or not email_ok or (consent and not data['correo']) or not specialty or request.form.get('presente')!='si':
            flash('Completa los datos, la especialidad y la confirmacion de identidad/presencia. El consentimiento requiere correo.','error')
        else:
            try:
                code=presencial.enroll(g.user,{**data,'tipo_documento':kind,'numero_documento':document,'alertas':consent},specialty)
                flash('Turno '+code+' registrado con llegada confirmada. El paciente ya esta en la cola.','ok')
                return redirect(url_for('web.panel'))
            except RuleError as error: flash(str(error),'error')
            except IntegrityError: flash('No se pudo guardar por un registro duplicado. Busca nuevamente al paciente y consulta sus turnos.','error')
    hospital,specialties=mediturno.hospital_data(g.user['id_hospital'])
    return render_template('presencial.html',patient=patient,data=data,kind=kind,document=document,hospital=hospital,specialties=specialties,
                           verification=verification if not verification_error else '',api_configured=documentos_api.configured())

def dni_signer():
    return URLSafeTimedSerializer(current_app.secret_key,salt='mediturno-dni-presencial-v1')

@admin.post('/recepcion/consultar-dni')
@reception_required
def consult_dni():
    def reply(data,status=200):
        response=jsonify(data)
        response.headers['Cache-Control']='private, no-store'
        response.headers['X-Content-Type-Options']='nosniff'
        return response,status
    number=request.form.get('numero_documento','').strip()
    if not re.fullmatch('[0-9]{8}',number):return reply({'ok':False,'message':'Ingresa un DNI de ocho digitos.'},422)
    try:
        # No enviar a terceros un DNI si ya hay datos del paciente en este hospital.
        if presencial.find_patient(g.user['id_hospital'],'DNI',number):
            return reply({'ok':False,'message':'El paciente ya figura en este hospital. Usa Buscar paciente.'},409)
        documentos_api.token()
        documentos_api.limit(g.user['id'],g.user['id_hospital'])
        data=documentos_api.lookup(number)
        signed=dni_signer().dumps({'user':g.user['id'],'hospital':g.user['id_hospital'],'dni':number,**data})
        return reply({'ok':True,'data':data,'verification':signed})
    except documentos_api.QueryError as error:
        return reply({'ok':False,'message':str(error)},error.status)
