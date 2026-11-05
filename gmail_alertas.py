"""Procesador local de avisos con cuenta remitente por hospital."""
import base64,os,threading
from models.database import transaction
from services import correo_google as gmail
from services.correo_presentacion import build_message

def valid_notice(row):
    if not row['hoy'] or not row['acepta_alertas_correo'] or not row['paciente_activo'] or not row['hospital_activo']:
        return False
    if row['correo_actual']!=row['destinatario']:
        return False
    if row['tipo']=='PROXIMO_TURNO':
        return row['turno_estado']=='EN_ESPERA' and row['delante']<=2
    return row['tipo']=='TURNO_LLAMADO' and row['turno_estado']=='LLAMADO'


def claim(hospital_id):
    with transaction() as c:
        c.execute("""SELECT n.*,t.estado AS turno_estado,t.prefijo,t.numero,t.fecha,
                     t.fecha=(now() AT TIME ZONE 'America/Lima')::date AS hoy,
                     h.nombre AS hospital,h.activo AS hospital_activo,co.nombre AS consultorio,
                     e.nombre AS especialidad,p.correo AS correo_actual,p.acepta_alertas_correo,
                     p.activo AS paciente_activo,
                     (SELECT count(*) FROM turnos q WHERE q.id_hospital=t.id_hospital
                     AND q.id_especialidad=t.id_especialidad AND q.fecha=t.fecha
                     AND q.estado='EN_ESPERA' AND (q.confirmado_en,q.id_turno)<(t.confirmado_en,t.id_turno)) AS delante
                     FROM notificaciones n JOIN turnos t USING(id_turno)
                     JOIN pacientes p USING(id_paciente) JOIN hospitales h ON h.id_hospital=t.id_hospital
                     JOIN especialidades e ON e.id_especialidad=t.id_especialidad
                     LEFT JOIN consultorios co ON co.id_consultorio=t.id_consultorio
                     WHERE n.estado='PENDIENTE' AND t.id_hospital=%s
                     ORDER BY CASE WHEN n.tipo='TURNO_LLAMADO' THEN 0 ELSE 1 END,n.creado_en
                     LIMIT 1 FOR UPDATE OF n SKIP LOCKED""",(hospital_id,))
        row=c.fetchone()
        if row is None:
            return None
        if not valid_notice(row):
            c.execute("UPDATE notificaciones SET estado='OMITIDO',ultimo_error='Aviso no vigente o sin consentimiento actual.' WHERE id_notificacion=%s",(row['id_notificacion'],))
            return False
        # Confirmar ANTES de contactar Gmail: otros procesos no lo enviaran de nuevo.
        c.execute("UPDATE notificaciones SET estado='ENVIANDO',intentos=intentos+1,ultimo_intento_en=clock_timestamp(),ultimo_error=NULL WHERE id_notificacion=%s",(row['id_notificacion'],))
        return dict(row)


def message(row):
    return {'raw':base64.urlsafe_b64encode(build_message(row).as_bytes()).decode('ascii')}


def deliver_one(service,row):
    try:
        # Sin reintentos de envio automaticos: un error de red puede ocurrir despues de enviar.
        result=service.users().messages().send(userId='me',body=message(row)).execute(num_retries=0)
        message_id=result.get('id')
        if not message_id:
            raise ValueError('Respuesta sin identificador')
    except Exception as error:
        # No guardar respuestas completas del proveedor ni credenciales en la BD.
        with transaction() as c:
            c.execute("UPDATE notificaciones SET estado='FALLIDO',ultimo_error=%s WHERE id_notificacion=%s AND estado='ENVIANDO'",('Fallo o resultado incierto ('+type(error).__name__+'). Revisar Enviados antes de reintentar.',row['id_notificacion']))
        print('Gmail: aviso',row['id_notificacion'],'requiere revision; no se reintentara automaticamente.',flush=True)
        return
    with transaction() as c:
        c.execute("UPDATE notificaciones SET estado='ENVIADO',enviado_en=clock_timestamp(),id_mensaje_proveedor=%s,ultimo_error=NULL WHERE id_notificacion=%s AND estado='ENVIANDO'",(message_id,row['id_notificacion']))
    print('Gmail: aviso',row['id_notificacion'],'aceptado por Gmail.',flush=True)


def run_hospital(hospital_id):
    # El bloqueo local impide reemplazar/desconectar la cuenta durante un envio.
    with gmail.lock(hospital_id):
        data=gmail.read(hospital_id)
        if not data.get('credentials'): return
        api=gmail.service(hospital_id)
        try:
            for _ in range(10):
                row=claim(hospital_id)
                if row is None: break
                if row is not False:
                    row['remitente']=data.get('email')
                    deliver_one(api,row)
        finally:
            api.close()

def worker(stop=None):
    stop=stop or threading.Event()
    print('Gmail: conexiones por hospital administradas desde el panel.',flush=True)
    while not stop.is_set():
        try:
            with transaction() as c:
                c.execute('SELECT id_hospital FROM hospitales WHERE activo ORDER BY id_hospital')
                hospitals=c.fetchall()
            for hospital in hospitals:
                try:
                    run_hospital(hospital['id_hospital'])
                except Exception as error:
                    print('Gmail: revisar conexion del hospital',hospital['id_hospital'],type(error).__name__,flush=True)
        except Exception as error:
            print('Gmail: no se pudo consultar avisos.',type(error).__name__,flush=True)
        stop.wait(10)

def start_local_worker():
    if os.getenv('GMAIL_ENABLED','1')=='0': return
    threading.Thread(target=worker,name='mediturno-gmail-hospitales',daemon=True).start()
