import re
from functools import wraps
from flask import Blueprint,g,abort,render_template,request,session,redirect,url_for
from werkzeug.security import generate_password_hash
from controllers.web import login_required,action
from controllers.administracion_controller import text
from models import gestion_general as model
from models import mediturno

gestion=Blueprint('gestion',__name__)

def general_required(fn):
    @wraps(fn)
    @login_required('personal')
    def wrapped(*args,**kwargs):
        if g.user['rol']!='ADMINISTRADOR' or not g.user.get('es_admin_general'): abort(403)
        return fn(*args,**kwargs)
    return wrapped

@gestion.get('/gestion/hospitales')
@general_required
def index():
    hospitals,administrators=model.overview()
    selected=request.args.get('hospital',type=int)
    if selected not in [h['id_hospital'] for h in hospitals if h['activo']]: selected=None
    return render_template('gestion_hospitales.html',hospitals=hospitals,administrators=administrators,selected_hospital=selected)

@gestion.post('/gestion/hospitales/administrador')
@general_required
def register():
    def save():
        names,surnames,email=text('nombres',80),text('apellidos',80),text('correo',254)
        password=request.form.get('password','')
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email) or not 10<=len(password)<=128:
            raise mediturno.RuleError('Revisa correo y contraseña (10 a 128 caracteres).')
        model.register_admin(request.form.get('hospital',type=int),names,surnames,email,generate_password_hash(password))
    action(save)
    return redirect(url_for('gestion.index'))

@gestion.post('/gestion/hospitales/seleccionar')
@general_required
def select():
    identity=request.form.get('hospital',type=int)
    hospital,_=mediturno.hospital_data(identity)
    if not hospital: abort(404)
    session['hospital_context']=hospital['id_hospital']
    return redirect(url_for('admin.index'))
