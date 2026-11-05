"""Gestion institucional: solo el controlador con permiso general la expone."""
from models.database import transaction
from models.mediturno import RuleError

def overview():
    with transaction() as c:
        c.execute('''SELECT h.*,
                     (SELECT count(*) FROM usuarios u JOIN roles r USING(id_rol) WHERE u.id_hospital=h.id_hospital AND u.activo AND r.nombre='ADMINISTRADOR' AND NOT u.es_admin_general) AS administradores,
                     (SELECT count(*) FROM hospital_especialidades he WHERE he.id_hospital=h.id_hospital AND he.activa) AS especialidades,
                     (SELECT count(*) FROM consultorios co WHERE co.id_hospital=h.id_hospital AND co.activo) AS consultorios
                     FROM hospitales h ORDER BY h.nombre''')
        hospitals=c.fetchall()
        c.execute('''SELECT u.id_usuario,u.nombres,u.apellidos,u.correo,u.activo,u.es_admin_general,h.nombre AS hospital
                     FROM usuarios u JOIN roles r USING(id_rol) JOIN hospitales h USING(id_hospital)
                     WHERE r.nombre='ADMINISTRADOR' ORDER BY h.nombre,u.nombres''')
        return hospitals,c.fetchall()

def register_admin(hospital_id,names,surnames,email,password_hash):
    with transaction() as c:
        c.execute('''INSERT INTO usuarios(id_hospital,id_rol,nombres,apellidos,correo,password_hash)
                     SELECT h.id_hospital,r.id_rol,%s,%s,%s,%s FROM hospitales h CROSS JOIN roles r
                     WHERE h.id_hospital=%s AND h.activo AND r.nombre='ADMINISTRADOR' ''',(names,surnames,email,password_hash,hospital_id))
        if c.rowcount!=1: raise RuleError('Selecciona un hospital activo.')
