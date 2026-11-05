"""Reportes agregados sin nombres, documentos o correos de pacientes."""
from datetime import timedelta
from models.database import transaction

STATES={'PENDIENTE_LLEGADA':'Por llegar','EN_ESPERA':'En espera','LLAMADO':'Llamados','EN_ATENCION':'En atención','ATENDIDO':'Atendidos','AUSENTE':'Ausentes','CANCELADO':'Cancelados'}

def specialties(hospital_id):
    with transaction() as c:
        c.execute('''SELECT e.id_especialidad,e.nombre FROM especialidades e WHERE
                     EXISTS(SELECT 1 FROM hospital_especialidades he WHERE he.id_hospital=%s AND he.id_especialidad=e.id_especialidad)
                     OR EXISTS(SELECT 1 FROM turnos t WHERE t.id_hospital=%s AND t.id_especialidad=e.id_especialidad)
                     ORDER BY e.nombre''',(hospital_id,hospital_id))
        return c.fetchall()

def grouped(hospital_id,start,end,specialty_id=None,state=None):
    with transaction() as c:
        c.execute('''SELECT t.fecha,extract(hour FROM (t.creado_en AT TIME ZONE 'America/Lima'))::integer AS hora,
                     t.id_especialidad,e.nombre AS especialidad,t.estado,count(*) AS cantidad,
                     count(*) FILTER(WHERE t.confirmado_por IS NOT NULL) AS llegadas,
                     coalesce(sum(extract(epoch FROM (t.inicio_atencion_en-t.confirmado_en))/60.0)
                         FILTER(WHERE t.confirmado_por IS NOT NULL AND t.inicio_atencion_en>=t.confirmado_en),0) AS espera_suma,
                     count(*) FILTER(WHERE t.confirmado_por IS NOT NULL AND t.inicio_atencion_en>=t.confirmado_en) AS espera_n,
                     coalesce(sum(extract(epoch FROM (t.finalizado_en-t.inicio_atencion_en))/60.0)
                         FILTER(WHERE t.estado='ATENDIDO' AND t.finalizado_en>=t.inicio_atencion_en),0) AS atencion_suma,
                     count(*) FILTER(WHERE t.estado='ATENDIDO' AND t.finalizado_en>=t.inicio_atencion_en) AS atencion_n
                     FROM turnos t JOIN especialidades e USING(id_especialidad)
                     WHERE t.id_hospital=%s AND t.fecha BETWEEN %s AND %s
                     AND (%s::bigint IS NULL OR t.id_especialidad=%s)
                     AND (%s::text IS NULL OR t.estado=%s)
                     GROUP BY t.fecha,t.id_especialidad,e.nombre,t.estado,extract(hour FROM (t.creado_en AT TIME ZONE 'America/Lima'))::integer
                     ORDER BY t.fecha,hora,e.nombre,t.estado''',(hospital_id,start,end,specialty_id,specialty_id,state,state))
        return c.fetchall()

def summarize(rows,start,end):
    states={key:0 for key in STATES}
    days={}
    current=start
    while current<=end:
        days[current.isoformat()]={key:0 for key in STATES}
        current+=timedelta(days=1)
    specialties_map={}
    hours={f'{i:02d}:00':{key:0 for key in STATES} for i in range(24)}
    arrivals=wait_n=duration_n=0
    wait_sum=duration_sum=0.0
    for row in rows:
        state=row['estado'];count=int(row['cantidad'])
        states[state]+=count
        day=row['fecha'].isoformat()
        days[day][state]+=count
        if row.get('hora') is not None:hours[f"{int(row['hora']):02d}:00"][state]+=count
        key=str(row['id_especialidad'])
        entry=specialties_map.setdefault(key,{'id':key,'name':row['especialidad'],'counts':{s:0 for s in STATES}})
        entry['counts'][state]+=count
        arrivals+=int(row['llegadas'])
        wait_n+=int(row['espera_n']);wait_sum+=float(row['espera_suma'])
        duration_n+=int(row['atencion_n']);duration_sum+=float(row['atencion_suma'])
    return dict(total=sum(states.values()),arrivals=arrivals,states=states,labels=STATES,
                wait_avg=round(wait_sum/wait_n,1) if wait_n else None,wait_n=wait_n,
                duration_avg=round(duration_sum/duration_n,1) if duration_n else None,duration_n=duration_n,
                days=[{'day':day,'counts':counts} for day,counts in days.items()],
                hours=[{'hour':hour,'counts':counts} for hour,counts in hours.items()],
                specialties=list(specialties_map.values()),start=start.isoformat(),end=end.isoformat())
