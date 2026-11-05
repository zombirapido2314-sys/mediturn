import re,secrets
from datetime import datetime
from zoneinfo import ZoneInfo
from functools import wraps
from flask import Blueprint,render_template,request,session,redirect,url_for,flash,abort,g
from werkzeug.security import generate_password_hash,check_password_hash
from psycopg2 import IntegrityError,OperationalError
from models import mediturno as model

web=Blueprint('web',__name__)

@web.before_app_request
def protect():
    session.setdefault('csrf',secrets.token_hex(32))
    if request.method=='POST' and not secrets.compare_digest(session['csrf'],request.form.get('csrf','')):
        abort(400,'Formulario vencido. Recarga la pagina.')

def login_required(kind):
    def decorator(fn):
        @wraps(fn)
        def wrapped(*args,**kwargs):
            user=session.get('user')
            if not user or user['kind']!=kind: return redirect(url_for('web.login'))
            identity=model.valid_identity(kind,user['id'])
            if not identity:
                session.clear()
                return redirect(url_for('web.login'))
            g.user={**user,**(dict(identity) if kind=='personal' else {})}
            if kind=='personal':
                g.user['hospital_origen']=g.user['id_hospital']
            if kind=='personal' and g.user.get('es_admin_general') and g.user['rol']=='ADMINISTRADOR':
                context=session.get('hospital_context')
                if context:
                    hospital,_=model.hospital_data(context)
                    if hospital:
                        g.user['id_hospital']=hospital['id_hospital']
                        g.user['hospital_nombre']=hospital['nombre']
                    else:
                        session.pop('hospital_context',None)
            return fn(*args,**kwargs)
        return wrapped
    return decorator

def action(fn):
    try:
        fn()
        flash('Operacion completada.','ok')
    except model.RuleError as error: flash(str(error),'error')
    except IntegrityError: flash('No se pudo guardar: existe un registro duplicado o el estado ya cambio.','error')

@web.route('/')
def index():
    return redirect(url_for('espacio.home'))

@web.route('/ingresar',methods=['GET','POST'])
def login():
    if request.method=='POST':
        email=request.form.get('correo','').strip()
        password=request.form.get('password','')
        candidates=model.login_candidates(email) if len(email)<=254 and len(password)<=128 else []
        matches=[u for u in candidates if u['activo'] and check_password_hash(u['password_hash'],password)]
        # Si ambas cuentas usan exactamente las mismas credenciales, priorizar
        # personal; una contraseña de paciente nunca autentica una cuenta ajena.
        matches.sort(key=lambda u:u['kind']!='personal')
        if matches:
            user=matches[0]
            kind=user['kind']
            session.clear()
            session['csrf']=secrets.token_hex(32)
            session['user']={k:v for k,v in dict(user).items() if k in ('id','nombres','id_hospital','rol')}
            session['user']['kind']=kind
            return redirect(url_for('espacio.home'))
        flash('Correo o contraseña incorrectos.','error')
    return render_template('auth.html',register=False)

@web.route('/registrarse',methods=['GET','POST'])
def register():
    if request.method=='POST':
        data={k:request.form.get(k,'').strip() for k in ('tipo_documento','numero_documento','nombres','apellidos','correo','alertas')}
        data['numero_documento']=data['numero_documento'].upper()
        patterns={'DNI':r'[0-9]{8}','CE':r'[A-Z0-9]{9,12}','PASAPORTE':r'[A-Z0-9]{6,20}'}
        password=request.form.get('password','')
        valid=(all(1<=len(data[k])<=80 for k in ('nombres','apellidos')) and
               len(data['correo'])<=254 and re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',data['correo']) and
               re.fullmatch(patterns.get(data['tipo_documento'],r'(?!)'),data['numero_documento']) and 10<=len(password)<=128)
        if not valid: flash('Revisa tus datos. La contraseña debe tener entre 10 y 128 caracteres.','error')
        else:
            try:
                model.register(data,generate_password_hash(password))
                flash('Cuenta creada. Ya puedes iniciar sesion.','ok')
                return redirect(url_for('web.login'))
            except IntegrityError: flash('No se pudo crear la cuenta. El documento o correo ya esta registrado; consulta con recepcion.','error')
    return render_template('auth.html',register=True)

@web.post('/salir')
def logout():
    session.clear()
    return redirect(url_for('web.login'))

@web.get('/paciente')
@login_required('paciente')
def patient():
    hospitals=model.hospitals()
    hospital_id=request.args.get('hospital',type=int)
    hospital,specialties=model.hospital_data(hospital_id) if hospital_id else (None,[])
    return render_template('patient.html',hospitals=hospitals,hospital=hospital,specialties=specialties,tickets=model.tickets(patient_id=g.user['id']))

@web.post('/paciente/turno')
@login_required('paciente')
def request_ticket():
    hospital_id=request.form.get('hospital',type=int)
    action(lambda:model.create_ticket(g.user['id'],hospital_id,request.form.get('especialidad',type=int)))
    return redirect(url_for('web.patient',hospital=hospital_id))

@web.get('/panel')
@login_required('personal')
def panel():
    available,selected=panel_scope()
    rows=scoped_tickets(selected)
    zone=ZoneInfo('America/Lima')
    today=datetime.now(zone).date()
    for ticket in rows:
        arrival=ticket.get('confirmado_en')
        ticket['hora_llegada']=arrival.astimezone(zone).strftime('%H:%M:%S') if arrival else None
        ticket['es_hoy']=ticket['fecha']==today
    hospital,_=model.hospital_data(g.user['id_hospital'])
    can_operate=g.user.get('hospital_origen',g.user['id_hospital'])==g.user['id_hospital']
    return render_template('panel.html',tickets=rows,rooms=available,selected=selected,user=g.user,hospital=hospital,can_operate=can_operate)

def panel_scope():
    if g.user['rol'] not in ('ADMINISTRADOR','RECEPCION','ATENCION'): abort(403)
    available=model.rooms(g.user)
    raw=request.args.get('consultorio','')
    requested=request.args.get('consultorio',type=int)
    if raw and (requested is None or requested<=0): abort(400)
    if g.user['rol']=='ATENCION':
        if len(available)>1: abort(403,'Revisa las asignaciones: solo se permite un consultorio activo.')
        selected=available[0] if available else None
        if raw and (not selected or selected['id_consultorio']!=requested): abort(403)
    else:
        selected=next((r for r in available if r['id_consultorio']==requested),None)
        if raw and not selected: abort(403)
    return available,selected

def scoped_tickets(selected):
    if g.user['rol']=='ATENCION' and selected is None:
        return []
    return model.tickets(hospital_id=g.user['id_hospital'],
                         room_id=selected['id_consultorio'] if selected else None,
                         specialty_id=selected['id_especialidad'] if selected else None,
                         include_pending=g.user['rol'] in ('ADMINISTRADOR','RECEPCION'))

def panel_redirect(room_id):
    return redirect(url_for('web.panel',consultorio=room_id))

@web.post('/panel/llamar')
@login_required('personal')
def call():
    if g.user['rol'] not in ('ADMINISTRADOR','ATENCION'): abort(403)
    room_id=request.form.get('consultorio',type=int)
    action(lambda:model.call_next(g.user,room_id))
    return panel_redirect(room_id)

@web.post('/panel/estado')
@login_required('personal')
def status():
    action(lambda:model.change_status(g.user,request.form.get('turno',type=int),request.form.get('estado')))
    return panel_redirect(request.form.get('vista_consultorio',type=int))

@web.post('/panel/confirmar-llegada')
@login_required('personal')
def confirm_arrival():
    if g.user['rol'] not in ('ADMINISTRADOR','RECEPCION'): abort(403)
    action(lambda:model.confirm_arrival(g.user,request.form.get('turno',type=int)))
    return panel_redirect(request.form.get('vista_consultorio',type=int))

@web.get('/pantalla')
@login_required('personal')
def display():
    _,selected=panel_scope()
    hospital,_=model.hospital_data(g.user['id_hospital'])
    return render_template('display.html',hospital=hospital,tickets=scoped_tickets(selected))

@web.app_errorhandler(OperationalError)
def database_error(error):
    return render_template('error.html'),503
