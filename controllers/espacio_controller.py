import csv,io
from datetime import datetime,timedelta,date
from zoneinfo import ZoneInfo
from flask import Blueprint,session,redirect,url_for,render_template,g,abort,request,Response
from controllers.web import login_required
from models import reportes,mediturno

espacio=Blueprint('espacio',__name__)

def today():return datetime.now(ZoneInfo('America/Lima')).date()

def module(title,description,endpoint,icon,color='teal'):
    return dict(title=title,description=description,url=url_for(endpoint),icon=icon,color=color)

@espacio.get('/inicio')
def home():
    user=session.get('user')
    if not user:return redirect(url_for('web.login'))
    return patient_home() if user['kind']=='paciente' else staff_home()

@login_required('paciente')
def patient_home():
    tickets=mediturno.tickets(patient_id=g.user['id'])
    active=[t for t in tickets if t['estado'] in ('PENDIENTE_LLEGADA','EN_ESPERA','LLAMADO','EN_ATENCION')]
    return render_template('inicio.html',modules=[module('Mis turnos','Solicita un turno y sigue tu atención.','web.patient','ticket')],
                           summary=None,active_tickets=active,room=None,personal=False)

@login_required('personal')
def staff_home():
    user=g.user;role=user['rol'];modules=[];summary=None;room=None
    if role not in ('ADMINISTRADOR','RECEPCION','ATENCION'):abort(403)
    if role=='ADMINISTRADOR' and user.get('es_admin_general'):
        modules.append(module('Hospitales','Instituciones y administradores.','gestion.index','hospital','blue'))
    if role in ('ADMINISTRADOR','RECEPCION'):
        summary=reportes.summarize(reportes.grouped(user['id_hospital'],today(),today()),today(),today())
        modules.extend([module('Resumen','Indicadores y gráficos de hoy.','espacio.dashboard','chart','blue'),module('Cola de atención','Llegadas, espera y seguimiento.','web.panel','queue')])
        if user.get('hospital_origen',user['id_hospital'])==user['id_hospital']:
            modules.append(module('Atención presencial','Registra al paciente que acaba de llegar.','admin.walk_in','person','purple'))
        modules.extend([module('Pacientes','Busca registros de este hospital.','admin.patients','users'),module('Reportes','Consulta períodos y descarga resultados.','espacio.reports','report','amber')])
        if role=='ADMINISTRADOR':
            modules.append(module('Configurar hospital','Especialidades, equipo y consultorios.','admin.index','settings','purple'))
            modules.append(module('Correo de avisos','Conecta y prueba la cuenta remitente.','correo.index','mail'))
    else:
        rooms=mediturno.rooms(user)
        if len(rooms)>1:abort(403,'Revisa la asignación del consultorio.')
        room=rooms[0] if rooms else None
        modules=[module('Mi consultorio','Llama, inicia y finaliza la atención.','web.panel','queue')]
    modules.append(module('Pantalla de turnos','Abre la vista para la sala de espera.','web.display','screen','blue'))
    return render_template('inicio.html',modules=modules,summary=summary,active_tickets=[],room=room,personal=True)

def report_access():
    if g.user['rol'] not in ('ADMINISTRADOR','RECEPCION'):abort(403)

def filters(daily=False):
    options=reportes.specialties(g.user['id_hospital'])
    if daily:
        start=end=today()
    else:
        try:
            start=date.fromisoformat(request.args.get('desde',(today()-timedelta(days=29)).isoformat()))
            end=date.fromisoformat(request.args.get('hasta',today().isoformat()))
        except ValueError:abort(400,'Revisa las fechas del período.')
        if end<start or (end-start).days>92:abort(400,'Elige un período de hasta 93 días.')
    raw=request.args.get('especialidad','')
    specialty=request.args.get('especialidad',type=int)
    if raw and specialty not in [s['id_especialidad'] for s in options]:abort(400,'Especialidad no disponible en este hospital.')
    return start,end,specialty,options

def render_report(daily):
    report_access()
    start,end,specialty,options=filters(daily)
    rows=reportes.grouped(g.user['id_hospital'],start,end,specialty)
    summary=reportes.summarize(rows,start,end)
    return render_template('resumen.html',summary=summary,options=options,selected=specialty,daily=daily)

@espacio.get('/resumen')
@login_required('personal')
def dashboard():return render_report(True)

@espacio.get('/reportes')
@login_required('personal')
def reports():return render_report(False)

def csv_cell(value):
    value=str(value)
    return "'"+value if value.lstrip().startswith(('=','+','-','@')) or value.startswith(('\t','\r','\n')) else value

@espacio.get('/reportes/descargar')
@login_required('personal')
def download():
    report_access()
    start,end,specialty,_=filters(False)
    state=request.args.get('estado') or None
    if state and state not in reportes.STATES:abort(400)
    rows=reportes.grouped(g.user['id_hospital'],start,end,specialty,state)
    # Excel reconoce esta indicación aunque Windows use otro separador regional.
    # UTF-8 con BOM conserva las tildes al abrir el archivo directamente.
    output=io.StringIO(newline='')
    output.write('sep=;\r\n')
    writer=csv.writer(output,delimiter=';',lineterminator='\r\n')
    writer.writerow(['Hospital','Fecha del turno','Hora de solicitud (Lima)',
                     'Especialidad','Estado del turno','Cantidad de turnos',
                     'Llegadas confirmadas','Espera promedio (minutos)',
                     'Casos con espera medida','Atención promedio (minutos)',
                     'Casos con atención medida'])
    for r in rows:
        # La coma decimal permite que Excel en español reconozca los promedios.
        wait=(f"{float(r['espera_suma'])/r['espera_n']:.1f}".replace('.',',')
              if r['espera_n'] else '')
        duration=(f"{float(r['atencion_suma'])/r['atencion_n']:.1f}".replace('.',',')
                  if r['atencion_n'] else '')
        writer.writerow([
            csv_cell(g.user['hospital_nombre']),r['fecha'].strftime('%d/%m/%Y'),
            f"{int(r['hora']):02d}:00",csv_cell(r['especialidad']),
            reportes.STATES[r['estado']],r['cantidad'],r['llegadas'],
            wait,r['espera_n'],duration,r['atencion_n']])
    return Response('\ufeff'+output.getvalue(),mimetype='text/csv',headers={'Content-Disposition':f'attachment; filename=mediturno-{start}-{end}.csv','Cache-Control':'private, no-store'})

@espacio.after_request
def private(response):
    response.headers['Cache-Control']='private, no-store'
    return response

@espacio.errorhandler(400)
def invalid_filter(error):
    return render_template('reporte_error.html',message=error.description),400
