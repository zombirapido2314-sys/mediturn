"""Consultas parametrizadas y reglas de la cola."""
from models.database import transaction

class RuleError(Exception):
    pass

def queue_upcoming(c, hospital_id):
    c.execute("""INSERT INTO notificaciones(id_turno,tipo,destinatario)
                 SELECT t.id_turno,'PROXIMO_TURNO',p.correo FROM turnos t JOIN pacientes p USING(id_paciente)
                 WHERE t.id_hospital=%s AND t.fecha=(now() AT TIME ZONE 'America/Lima')::date
                 AND t.estado='EN_ESPERA' AND p.acepta_alertas_correo AND p.activo
                 AND (SELECT count(*) FROM turnos q WHERE q.id_hospital=t.id_hospital
                      AND q.id_especialidad=t.id_especialidad AND q.fecha=t.fecha
                      AND q.estado='EN_ESPERA' AND (q.confirmado_en,q.id_turno)<(t.confirmado_en,t.id_turno))<=2
                 ON CONFLICT(id_turno,tipo) DO NOTHING""",(hospital_id,))

def hospitals():
    with transaction() as c:
        c.execute('SELECT * FROM hospitales WHERE activo ORDER BY nombre')
        return c.fetchall()

def account(kind, email):
    with transaction() as c:
        if kind == 'paciente':
            c.execute('SELECT id_paciente AS id,nombres,password_hash,activo FROM pacientes WHERE lower(correo)=lower(%s) AND password_hash IS NOT NULL', (email,))
        else:
            c.execute('SELECT u.id_usuario AS id,u.nombres,u.password_hash,u.activo,u.id_hospital,r.nombre AS rol FROM usuarios u JOIN roles r USING(id_rol) JOIN hospitales h USING(id_hospital) WHERE lower(u.correo)=lower(%s) AND h.activo', (email,))
        return c.fetchone()

def login_candidates(email):
    """Buscar cuentas sin aceptar el tipo o rol enviados por el navegador."""
    with transaction() as c:
        c.execute('''SELECT u.id_usuario AS id,u.nombres,u.password_hash,
                     (u.activo AND h.activo) AS activo,u.id_hospital,r.nombre AS rol,'personal' AS kind
                     FROM usuarios u JOIN roles r USING(id_rol) JOIN hospitales h USING(id_hospital)
                     WHERE lower(u.correo)=lower(%s)
                     UNION ALL
                     SELECT p.id_paciente AS id,p.nombres,p.password_hash,p.activo,
                     NULL::bigint AS id_hospital,NULL::varchar AS rol,'paciente' AS kind
                     FROM pacientes p WHERE lower(p.correo)=lower(%s) AND p.password_hash IS NOT NULL''',(email,email))
        return c.fetchall()

def valid_identity(kind, identity):
    with transaction() as c:
        if kind == 'paciente':
            c.execute('SELECT id_paciente FROM pacientes WHERE id_paciente=%s AND activo AND password_hash IS NOT NULL',(identity,))
        else:
            c.execute('SELECT u.id_hospital,r.nombre AS rol,u.es_admin_general,h.nombre AS hospital_nombre FROM usuarios u JOIN roles r USING(id_rol) JOIN hospitales h USING(id_hospital) WHERE u.id_usuario=%s AND u.activo AND h.activo',(identity,))
        return c.fetchone()

def register(data, password_hash):
    with transaction() as c:
        c.execute('INSERT INTO pacientes(tipo_documento,numero_documento,nombres,apellidos,correo,password_hash,acepta_alertas_correo) VALUES(%s,%s,%s,%s,%s,%s,%s)',
                  (data['tipo_documento'],data['numero_documento'],data['nombres'],data['apellidos'],data['correo'],password_hash,data.get('alertas')=='si'))

def hospital_data(hospital_id):
    with transaction() as c:
        c.execute('SELECT * FROM hospitales WHERE id_hospital=%s AND activo',(hospital_id,))
        hospital=c.fetchone()
        c.execute('SELECT e.* FROM especialidades e JOIN hospital_especialidades he USING(id_especialidad) WHERE he.id_hospital=%s AND he.activa AND e.activa ORDER BY e.nombre',(hospital_id,))
        return hospital,c.fetchall()

def tickets(patient_id=None, hospital_id=None, room_id=None, specialty_id=None, include_pending=False):
    if patient_id is None and hospital_id is None:
        raise RuleError('La consulta requiere paciente u hospital.')
    if room_id is not None and (hospital_id is None or specialty_id is None):
        raise RuleError('El consultorio requiere hospital y especialidad verificados.')
    with transaction() as c:
        c.execute('''SELECT t.*,e.nombre AS especialidad,h.nombre AS hospital,p.nombres,p.apellidos,
                     co.nombre AS consultorio,
                     (SELECT count(*) FROM turnos q WHERE q.id_hospital=t.id_hospital AND q.id_especialidad=t.id_especialidad AND q.fecha=t.fecha AND q.estado='EN_ESPERA' AND (q.confirmado_en,q.id_turno)<(t.confirmado_en,t.id_turno)) AS delante
                     FROM turnos t JOIN especialidades e USING(id_especialidad)
                     JOIN hospitales h ON h.id_hospital=t.id_hospital JOIN pacientes p USING(id_paciente)
                     LEFT JOIN consultorios co ON co.id_consultorio=t.id_consultorio
                     WHERE (%s::bigint IS NULL OR t.id_paciente=%s)
                     AND (%s::bigint IS NULL OR t.id_hospital=%s)
                     AND (%s::bigint IS NULL OR t.id_consultorio=%s OR
                          (t.id_consultorio IS NULL AND (t.estado='EN_ESPERA' OR (%s AND t.estado='PENDIENTE_LLEGADA')) AND t.id_especialidad=%s))
                     AND (t.fecha=(now() AT TIME ZONE 'America/Lima')::date OR t.estado IN ('PENDIENTE_LLEGADA','EN_ESPERA','LLAMADO','EN_ATENCION'))
                     ORDER BY CASE WHEN t.estado IN ('LLAMADO','EN_ATENCION') THEN 0 WHEN t.estado='EN_ESPERA' THEN 1 WHEN t.estado='PENDIENTE_LLEGADA' THEN 2 ELSE 3 END, t.fecha,coalesce(t.confirmado_en,t.creado_en),t.id_turno''',(patient_id,patient_id,hospital_id,hospital_id,room_id,room_id,include_pending,specialty_id))
        return c.fetchall()

def create_ticket(patient_id,hospital_id,specialty_id,actor=None):
    with transaction() as c:
        return issue_ticket(c,patient_id,hospital_id,specialty_id,actor)

def issue_ticket(c,patient_id,hospital_id,specialty_id,actor=None):
    c.execute('''SELECT e.prefijo FROM hospital_especialidades he JOIN especialidades e USING(id_especialidad)
                 JOIN hospitales h USING(id_hospital) WHERE he.id_hospital=%s AND he.id_especialidad=%s
                 AND he.activa AND e.activa AND h.activo FOR UPDATE OF he''',(hospital_id,specialty_id))
    offer=c.fetchone()
    if not offer: raise RuleError('La especialidad no esta disponible en este hospital.')
    c.execute('SELECT id_paciente FROM pacientes WHERE id_paciente=%s AND activo',(patient_id,))
    if not c.fetchone(): raise RuleError('Paciente no disponible.')
    c.execute('''INSERT INTO turnos(id_paciente,id_hospital,id_especialidad,numero,prefijo,creado_por)
                 SELECT %s,%s,%s,COALESCE(max(numero),0)+1,%s,%s FROM turnos
                 WHERE id_hospital=%s AND id_especialidad=%s AND fecha=(now() AT TIME ZONE 'America/Lima')::date
                 RETURNING id_turno''',(patient_id,hospital_id,specialty_id,offer['prefijo'],actor,hospital_id,specialty_id))
    ticket_id=c.fetchone()['id_turno']
    c.execute("INSERT INTO historial_turnos(id_turno,id_usuario,estado_nuevo) VALUES(%s,%s,'PENDIENTE_LLEGADA')",(ticket_id,actor))

    return ticket_id

def rooms(user):
    with transaction() as c:
        c.execute('''SELECT co.* FROM consultorios co JOIN hospital_especialidades he USING(id_hospital,id_especialidad)
                     JOIN especialidades e USING(id_especialidad) WHERE co.id_hospital=%s AND co.activo
                     AND he.activa AND e.activa AND (%s IN ('ADMINISTRADOR','RECEPCION') OR EXISTS (
                     SELECT 1 FROM asignaciones_atencion a WHERE a.id_consultorio=co.id_consultorio AND a.id_usuario=%s AND a.activa))
                     ORDER BY co.nombre''',(user['id_hospital'],user['rol'],user['id']))
        return c.fetchall()

def authorize_attention(c,user,room_id):
    # Bloquear al empleado mientras se valida y ejecuta la accion: una retirada
    # concurrente de asignacion no debe permitir operar el consultorio anterior.
    c.execute('''SELECT r.nombre AS rol FROM usuarios u JOIN roles r USING(id_rol)
                 WHERE u.id_usuario=%s AND u.id_hospital=%s AND u.activo FOR SHARE OF u''',(user['id'],user['id_hospital']))
    identity=c.fetchone()
    if not identity or identity['rol'] not in ('ADMINISTRADOR','ATENCION'):
        raise RuleError('Accion no autorizada.')
    if identity['rol']=='ATENCION':
        c.execute('''SELECT id_consultorio FROM asignaciones_atencion
                     WHERE id_usuario=%s AND id_hospital=%s AND activa FOR SHARE''',(user['id'],user['id_hospital']))
        assigned=c.fetchall()
        if len(assigned)!=1 or assigned[0]['id_consultorio']!=room_id:
            raise RuleError('Solo puedes atender tu consultorio asignado.')

def call_next(user,room_id):
    with transaction() as c:
        authorize_attention(c,user,room_id)
        c.execute('SELECT * FROM consultorios WHERE id_consultorio=%s AND id_hospital=%s AND activo FOR UPDATE',(room_id,user['id_hospital']))
        room=c.fetchone()
        if not room: raise RuleError('Consultorio no disponible.')
        c.execute('''SELECT 1 FROM hospital_especialidades he JOIN especialidades e USING(id_especialidad)
                     WHERE he.id_hospital=%s AND he.id_especialidad=%s AND he.activa AND e.activa FOR SHARE OF he''',(user['id_hospital'],room['id_especialidad']))
        if not c.fetchone(): raise RuleError('Especialidad no disponible.')
        c.execute("SELECT id_turno FROM turnos WHERE id_consultorio=%s AND estado IN ('LLAMADO','EN_ATENCION')",(room_id,))
        if c.fetchone(): raise RuleError('Finaliza el turno actual antes de llamar al siguiente.')
        c.execute("""SELECT * FROM turnos WHERE id_hospital=%s AND id_especialidad=%s
                     AND fecha=(now() AT TIME ZONE 'America/Lima')::date AND estado='EN_ESPERA' AND confirmado_en IS NOT NULL
                     ORDER BY confirmado_en,id_turno LIMIT 1 FOR UPDATE SKIP LOCKED""",(user['id_hospital'],room['id_especialidad']))
        ticket=c.fetchone()
        if not ticket: raise RuleError('No hay turnos en espera para este consultorio.')
        c.execute("UPDATE turnos SET estado='LLAMADO',id_consultorio=%s,llamado_por=%s,llamado_en=clock_timestamp() WHERE id_turno=%s",(room_id,user['id'],ticket['id_turno']))
        c.execute("INSERT INTO historial_turnos(id_turno,id_usuario,estado_anterior,estado_nuevo) VALUES(%s,%s,'EN_ESPERA','LLAMADO')",(ticket['id_turno'],user['id']))
        c.execute("""INSERT INTO notificaciones(id_turno,tipo,destinatario)
                     SELECT %s,'TURNO_LLAMADO',correo FROM pacientes WHERE id_paciente=%s AND acepta_alertas_correo
                     ON CONFLICT(id_turno,tipo) DO NOTHING""",(ticket['id_turno'],ticket['id_paciente']))
        queue_upcoming(c,user['id_hospital'])

def change_status(user,ticket_id,new):
    with transaction() as c:
        c.execute('SELECT id_usuario FROM usuarios WHERE id_usuario=%s AND id_hospital=%s AND activo FOR SHARE',(user['id'],user['id_hospital']))
        if not c.fetchone(): raise RuleError('Usuario no disponible.')
        c.execute('SELECT * FROM turnos WHERE id_turno=%s AND id_hospital=%s FOR UPDATE',(ticket_id,user['id_hospital']))
        ticket=c.fetchone()
        if not ticket: raise RuleError('Turno no disponible.')
        if new=='CANCELADO':
            if user['rol'] not in ('ADMINISTRADOR','RECEPCION'): raise RuleError('Accion no autorizada.')
        else:
            authorize_attention(c,user,ticket['id_consultorio'])
        if new not in {'PENDIENTE_LLEGADA':['CANCELADO'],'EN_ESPERA':['CANCELADO'],'LLAMADO':['EN_ATENCION','AUSENTE'],'EN_ATENCION':['ATENDIDO']}.get(ticket['estado'],[]):
            raise RuleError('El turno ya cambio o la transicion no es valida.')
        c.execute('''UPDATE turnos SET estado=%s,
                     inicio_atencion_en=CASE WHEN %s='EN_ATENCION' THEN clock_timestamp() ELSE inicio_atencion_en END,
                     finalizado_en=CASE WHEN %s IN ('CANCELADO','AUSENTE','ATENDIDO') THEN clock_timestamp() ELSE finalizado_en END
                     WHERE id_turno=%s''',(new,new,new,ticket_id))
        c.execute('INSERT INTO historial_turnos(id_turno,id_usuario,estado_anterior,estado_nuevo) VALUES(%s,%s,%s,%s)',(ticket_id,user['id'],ticket['estado'],new))
        queue_upcoming(c,user['id_hospital'])

def confirm_arrival(user,ticket_id):
    with transaction() as c:
        return confirm_arrival_in_transaction(c,user,ticket_id)

def confirm_arrival_in_transaction(c,user,ticket_id):
    c.execute('''SELECT r.nombre AS rol FROM usuarios u JOIN roles r USING(id_rol)
                 WHERE u.id_usuario=%s AND u.id_hospital=%s AND u.activo FOR SHARE OF u''',(user['id'],user['id_hospital']))
    identity=c.fetchone()
    if not identity or identity['rol'] not in ('ADMINISTRADOR','RECEPCION'):
        raise RuleError('Solo recepcion o el administrador de este hospital puede confirmar la llegada.')
    # Leer el alcance antes de bloquear la cola; no se obtiene un turno ajeno.
    c.execute('SELECT t.id_especialidad FROM turnos t JOIN pacientes p USING(id_paciente) WHERE t.id_turno=%s AND t.id_hospital=%s AND p.activo',(ticket_id,user['id_hospital']))
    candidate=c.fetchone()
    if not candidate: raise RuleError('Turno no disponible en tu hospital.')
    c.execute('''SELECT 1 FROM hospital_especialidades he JOIN especialidades e USING(id_especialidad)
                 JOIN hospitales h USING(id_hospital) WHERE he.id_hospital=%s AND he.id_especialidad=%s
                 AND he.activa AND e.activa AND h.activo FOR UPDATE OF he''',(user['id_hospital'],candidate['id_especialidad']))
    if not c.fetchone(): raise RuleError('La especialidad no esta habilitada.')
    c.execute('''SELECT estado,fecha=(now() AT TIME ZONE 'America/Lima')::date AS hoy
                 FROM turnos WHERE id_turno=%s AND id_hospital=%s FOR UPDATE''',(ticket_id,user['id_hospital']))
    ticket=c.fetchone()
    if not ticket or ticket['estado']!='PENDIENTE_LLEGADA':
        raise RuleError('Este turno ya fue confirmado o cambio de estado.')
    if not ticket['hoy']: raise RuleError('Solo se confirma la llegada de turnos de hoy. Cancela el anterior y solicita uno nuevo.')
    c.execute('''UPDATE turnos SET estado='EN_ESPERA',confirmado_en=clock_timestamp(),confirmado_por=%s
                 WHERE id_turno=%s AND id_hospital=%s''',(user['id'],ticket_id,user['id_hospital']))
    c.execute("INSERT INTO historial_turnos(id_turno,id_usuario,estado_anterior,estado_nuevo) VALUES(%s,%s,'PENDIENTE_LLEGADA','EN_ESPERA')",(ticket_id,user['id']))
    queue_upcoming(c,user['id_hospital'])
