import unicodedata
from models.database import transaction
from models.mediturno import RuleError,issue_ticket,confirm_arrival_in_transaction

def normalize(value):
    return ' '.join(unicodedata.normalize('NFKC',value).casefold().split())

def find_patient(hospital_id,kind,document):
    with transaction() as c:
        c.execute('''SELECT p.id_paciente,p.nombres,p.apellidos,p.correo,p.activo,p.acepta_alertas_correo
                     FROM pacientes p WHERE p.tipo_documento=%s AND p.numero_documento=%s
                     AND EXISTS(SELECT 1 FROM turnos t WHERE t.id_paciente=p.id_paciente AND t.id_hospital=%s)''',(kind,document,hospital_id))
        return c.fetchone()

def enroll(user,data,specialty_id):
    with transaction() as c:
        c.execute('''SELECT r.nombre AS rol FROM usuarios u JOIN roles r USING(id_rol)
                     JOIN hospitales h USING(id_hospital) WHERE u.id_usuario=%s AND u.id_hospital=%s
                     AND u.activo AND h.activo FOR SHARE OF u''',(user['id'],user['id_hospital']))
        identity=c.fetchone()
        if not identity or identity['rol'] not in ('ADMINISTRADOR','RECEPCION'):
            raise RuleError('Solo recepcion o el administrador de este hospital puede registrar atencion presencial.')
        c.execute('''SELECT id_paciente,nombres,apellidos,activo FROM pacientes
                     WHERE tipo_documento=%s AND numero_documento=%s FOR UPDATE''',(data['tipo_documento'],data['numero_documento']))
        patient=c.fetchone()
        if patient:
            if not patient['activo'] or normalize(patient['nombres'])!=normalize(data['nombres']) or normalize(patient['apellidos'])!=normalize(data['apellidos']):
                raise RuleError('No se puede registrar con estos datos. Verifica la identidad y el documento del paciente.')
            patient_id=patient['id_paciente']
            # No cambiar datos de acceso, correo ni consentimiento existentes.
        else:
            c.execute('''INSERT INTO pacientes(tipo_documento,numero_documento,nombres,apellidos,correo,acepta_alertas_correo)
                         VALUES(%s,%s,%s,%s,%s,%s) RETURNING id_paciente''',
                      (data['tipo_documento'],data['numero_documento'],data['nombres'],data['apellidos'],data['correo'] or None,data['alertas']))
            patient_id=c.fetchone()['id_paciente']
        c.execute('''SELECT 1 FROM hospital_especialidades he JOIN especialidades e USING(id_especialidad)
                     WHERE he.id_hospital=%s AND he.id_especialidad=%s AND he.activa AND e.activa FOR UPDATE OF he''',(user['id_hospital'],specialty_id))
        if not c.fetchone(): raise RuleError('Especialidad no disponible en este hospital.')
        c.execute('''SELECT id_turno,estado FROM turnos WHERE id_paciente=%s AND id_hospital=%s AND id_especialidad=%s
                     AND fecha=(now() AT TIME ZONE 'America/Lima')::date
                     AND estado IN ('PENDIENTE_LLEGADA','EN_ESPERA','LLAMADO','EN_ATENCION') FOR UPDATE''',(patient_id,user['id_hospital'],specialty_id))
        active=c.fetchone()
        if active and active['estado']!='PENDIENTE_LLEGADA':
            raise RuleError('El paciente ya tiene un turno activo para esta especialidad. Consulta la cola.')
        identity=active['id_turno'] if active else issue_ticket(c,patient_id,user['id_hospital'],specialty_id,user['id'])
        confirm_arrival_in_transaction(c,user,identity)
        c.execute('SELECT prefijo,numero FROM turnos WHERE id_turno=%s AND id_hospital=%s',(identity,user['id_hospital']))
        row=c.fetchone()
        return f"{row['prefijo']}-{row['numero']:03d}"
