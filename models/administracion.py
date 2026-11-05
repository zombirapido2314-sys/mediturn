"""Gestion del hospital con alcance obligatorio en cada consulta."""
from models.database import transaction
from models.mediturno import RuleError

def data(hospital_id):
    with transaction() as c:
        c.execute('SELECT nombre FROM hospitales WHERE id_hospital=%s',(hospital_id,))
        hospital=c.fetchone()
        c.execute('''SELECT u.id_usuario,u.nombres,u.apellidos,u.correo,u.activo,u.es_admin_general,r.nombre AS rol
                     FROM usuarios u JOIN roles r USING(id_rol) WHERE u.id_hospital=%s ORDER BY u.nombres''',(hospital_id,))
        users=c.fetchall()
        c.execute('''SELECT e.*,coalesce(he.activa,false) AS habilitada FROM especialidades e
                     LEFT JOIN hospital_especialidades he ON he.id_especialidad=e.id_especialidad AND he.id_hospital=%s
                     ORDER BY e.nombre''',(hospital_id,))
        specialties=c.fetchall()
        c.execute('''SELECT co.*,e.nombre AS especialidad FROM consultorios co JOIN especialidades e USING(id_especialidad)
                     WHERE co.id_hospital=%s ORDER BY co.nombre''',(hospital_id,))
        rooms=c.fetchall()
        c.execute('''SELECT a.*,u.nombres,u.apellidos,co.nombre AS consultorio FROM asignaciones_atencion a
                     JOIN usuarios u USING(id_usuario) JOIN consultorios co USING(id_consultorio)
                     WHERE u.id_hospital=%s AND co.id_hospital=%s ORDER BY u.nombres,co.nombre''',(hospital_id,hospital_id))
        assignments=c.fetchall()
        c.execute("SELECT id_rol,nombre FROM roles WHERE nombre IN ('RECEPCION','ATENCION') ORDER BY id_rol")
        return dict(hospital=hospital,users=users,specialties=specialties,rooms=rooms,assignments=assignments,roles=c.fetchall())

def add_user(hospital_id,names,surnames,email,password_hash,role_id):
    with transaction() as c:
        c.execute('''INSERT INTO usuarios(id_hospital,id_rol,nombres,apellidos,correo,password_hash)
                     SELECT %s,id_rol,%s,%s,%s,%s FROM roles WHERE id_rol=%s
                     AND nombre IN ('RECEPCION','ATENCION')''',(hospital_id,names,surnames,email,password_hash,role_id))
        if c.rowcount!=1: raise RuleError('Selecciona un rol valido.')

def toggle_user(hospital_id,actor,user_id,active):
    if user_id==actor: raise RuleError('No puedes desactivar tu propia cuenta.')
    with transaction() as c:
        c.execute('UPDATE usuarios SET activo=%s WHERE id_usuario=%s AND id_hospital=%s AND NOT es_admin_general',(active,user_id,hospital_id))
        if c.rowcount!=1: raise RuleError('Usuario no disponible en tu hospital.')

def set_specialty(hospital_id,specialty_id,active):
    with transaction() as c:
        c.execute('SELECT id_especialidad FROM especialidades WHERE id_especialidad=%s AND activa FOR UPDATE',(specialty_id,))
        if not c.fetchone(): raise RuleError('Especialidad no disponible.')
        c.execute('SELECT id_especialidad FROM hospital_especialidades WHERE id_hospital=%s AND id_especialidad=%s FOR UPDATE',(hospital_id,specialty_id))
        if not active:
            c.execute("SELECT 1 FROM turnos WHERE id_hospital=%s AND id_especialidad=%s AND estado IN ('PENDIENTE_LLEGADA','EN_ESPERA','LLAMADO','EN_ATENCION') LIMIT 1",(hospital_id,specialty_id))
            if c.fetchone(): raise RuleError('Finaliza o cancela los turnos activos antes de deshabilitar la especialidad.')
        c.execute('''INSERT INTO hospital_especialidades(id_hospital,id_especialidad,activa) VALUES(%s,%s,%s)
                     ON CONFLICT(id_hospital,id_especialidad) DO UPDATE SET activa=excluded.activa''',(hospital_id,specialty_id,active))

def add_room(hospital_id,name,specialty_id):
    with transaction() as c:
        c.execute('''INSERT INTO consultorios(id_hospital,nombre,id_especialidad)
                     SELECT %s,%s,he.id_especialidad FROM hospital_especialidades he JOIN especialidades e USING(id_especialidad)
                     WHERE he.id_hospital=%s AND he.id_especialidad=%s AND he.activa AND e.activa''',(hospital_id,name,hospital_id,specialty_id))
        if c.rowcount!=1: raise RuleError('Habilita primero esa especialidad en tu hospital.')

def toggle_room(hospital_id,room_id,active):
    with transaction() as c:
        c.execute('SELECT id_consultorio FROM consultorios WHERE id_consultorio=%s AND id_hospital=%s FOR UPDATE',(room_id,hospital_id))
        if not c.fetchone(): raise RuleError('Consultorio no disponible.')
        c.execute("SELECT 1 FROM turnos WHERE id_consultorio=%s AND estado IN ('LLAMADO','EN_ATENCION') LIMIT 1",(room_id,))
        if not active and c.fetchone(): raise RuleError('Finaliza la atencion antes de desactivar el consultorio.')
        c.execute('UPDATE consultorios SET activo=%s WHERE id_consultorio=%s',(active,room_id))

def assign(hospital_id,user_id,room_id):
    with transaction() as c:
        c.execute('''SELECT u.id_usuario FROM usuarios u JOIN roles r USING(id_rol)
                     WHERE u.id_usuario=%s AND u.id_hospital=%s AND u.activo AND r.nombre='ATENCION' FOR UPDATE OF u''',(user_id,hospital_id))
        if not c.fetchone(): raise RuleError('Elige personal de atencion activo de tu hospital.')
        c.execute('SELECT id_consultorio FROM asignaciones_atencion WHERE id_usuario=%s AND activa',(user_id,))
        assigned=c.fetchall()
        if any(a['id_consultorio']!=room_id for a in assigned):
            raise RuleError('Este empleado ya tiene un consultorio. Retira su asignacion actual antes de cambiarlo.')
        c.execute('''INSERT INTO asignaciones_atencion(id_usuario,id_consultorio,id_hospital)
                     SELECT u.id_usuario,co.id_consultorio,u.id_hospital FROM usuarios u JOIN roles r USING(id_rol)
                     CROSS JOIN consultorios co WHERE u.id_usuario=%s AND co.id_consultorio=%s
                     AND u.id_hospital=%s AND co.id_hospital=%s AND u.activo AND co.activo AND r.nombre='ATENCION'
                     ON CONFLICT(id_usuario,id_consultorio) DO UPDATE SET activa=true''',(user_id,room_id,hospital_id,hospital_id))
        if c.rowcount!=1: raise RuleError('Elige personal de atencion y un consultorio activos de tu hospital.')

def remove_assignment(hospital_id,assignment_id):
    with transaction() as c:
        c.execute('''SELECT u.id_usuario FROM usuarios u JOIN asignaciones_atencion a USING(id_usuario)
                     WHERE a.id_asignacion=%s AND u.id_hospital=%s FOR UPDATE OF u''',(assignment_id,hospital_id))
        employee=c.fetchone()
        if not employee: raise RuleError('Asignacion no disponible.')
        c.execute("SELECT 1 FROM turnos WHERE llamado_por=%s AND id_hospital=%s AND estado IN ('LLAMADO','EN_ATENCION') LIMIT 1",(employee['id_usuario'],hospital_id))
        if c.fetchone(): raise RuleError('Finaliza la atencion de ese empleado antes de retirar su asignacion.')
        c.execute('''UPDATE asignaciones_atencion a SET activa=false FROM usuarios u,consultorios co
                     WHERE a.id_usuario=u.id_usuario AND a.id_consultorio=co.id_consultorio
                     AND a.id_asignacion=%s AND u.id_hospital=%s AND co.id_hospital=%s''',(assignment_id,hospital_id,hospital_id))
        if c.rowcount!=1: raise RuleError('Asignacion no disponible.')

def patients(hospital_id,search):
    with transaction() as c:
        c.execute('''SELECT p.id_paciente,p.tipo_documento,p.numero_documento,p.nombres,p.apellidos,p.correo,
                     count(t.id_turno) AS total_turnos,max(t.fecha) AS ultimo_turno
                     FROM pacientes p JOIN turnos t USING(id_paciente) WHERE t.id_hospital=%s
                     AND (%s='' OR p.numero_documento=%s OR p.nombres ILIKE %s OR p.apellidos ILIKE %s)
                     GROUP BY p.id_paciente ORDER BY max(t.fecha) DESC,p.apellidos LIMIT 100''',
                  (hospital_id,search,search,'%'+search+'%','%'+search+'%'))
        return c.fetchall()

def add_specialty(hospital_id,name,prefix):
    with transaction() as c:
        c.execute('''INSERT INTO especialidades(nombre,prefijo) VALUES(%s,%s)
                     ON CONFLICT DO NOTHING RETURNING id_especialidad''',(name,prefix))
        row=c.fetchone()
        if not row:
            c.execute('''SELECT id_especialidad FROM especialidades WHERE lower(btrim(nombre))=lower(btrim(%s))
                         AND prefijo=%s AND activa''',(name,prefix))
            row=c.fetchone()
        if not row: raise RuleError('El nombre o prefijo ya se usa en otra especialidad. Revisa el catalogo.')
        c.execute('''INSERT INTO hospital_especialidades(id_hospital,id_especialidad,activa) VALUES(%s,%s,true)
                     ON CONFLICT(id_hospital,id_especialidad) DO UPDATE SET activa=true''',(hospital_id,row['id_especialidad']))
