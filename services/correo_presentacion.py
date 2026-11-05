"""Correos HTML con alternativa de texto y logo incrustado, sin imagenes remotas."""
import os
from datetime import datetime
from pathlib import Path
from email.message import EmailMessage
from email.utils import formataddr,formatdate
from jinja2 import Environment,FileSystemLoader,select_autoescape

ROOT=Path(__file__).resolve().parents[1]
env=Environment(loader=FileSystemLoader(ROOT/'templates'/'emails'),autoescape=select_autoescape(['html']))

def build_message(row):
    test=row['tipo']=='PRUEBA'
    called=row['tipo']=='TURNO_LLAMADO'
    code=f"{row['prefijo']}-{row['numero']:03d}"
    title='Tu correo está conectado' if test else '¡Es tu turno!' if called else 'Tu turno está próximo'
    label='PRUEBA DE CONEXIÓN' if test else 'LLAMADO DE ATENCIÓN' if called else 'PREPÁRATE PARA TU ATENCIÓN'
    date=row['fecha']
    date=date.strftime('%d/%m/%Y') if hasattr(date,'strftime') else str(date)
    if test:
        instruction='La cuenta de este hospital está lista para enviar avisos a los pacientes.'
    elif called:
        instruction='Acércate ahora al consultorio indicado y presenta tu número de turno.'
    elif row['delante']==0:
        instruction='Estás al frente de la cola de espera. Mantente cerca y prepárate para el llamado.'
    else:
        instruction=f"Hay {row['delante']} turno(s) en espera antes de ti. Mantente cerca del área de atención."
    logo=ROOT/'static'/'branding'/'mediturno-informe.png'
    email=EmailMessage()
    email['To']=row['destinatario']
    if row.get('remitente'):email['From']=formataddr(('MediTurno',row['remitente']))
    email['Subject']='MediTurno | Conexión de correo confirmada' if test else f"MediTurno | {'Es tu turno' if called else 'Tu turno está próximo'} | {code}"
    email['Date']=formatdate(localtime=False)
    email['Message-ID']=f"<mediturno-{os.getenv('GMAIL_INSTANCE_ID','local')}-{row['id_notificacion']}@mediturno.invalid>"
    email.set_content(f"{title}\n\nTurno: {code if not test else 'Prueba de conexión'}\nFecha: {date}\nHospital: {row['hospital']}\nEspecialidad: {row['especialidad']}\nConsultorio: {row.get('consultorio') or 'Se indicará al llamar'}\n\n{instruction}\n\nEl orden depende de la llegada confirmada en Recepción, no del número de turno.\n\nDemostración académica de MediTurno S.A.C. No constituye una cita oficial del hospital.\n")
    html=env.get_template('turno.html').render(title=title,label=label,code=code,test=test,called=called,date=date,
            instruction=instruction,hospital=row['hospital'],specialty=row['especialidad'],
            room=row.get('consultorio'),has_logo=logo.is_file())
    email.add_alternative(html,subtype='html')
    if logo.is_file():
        email.get_payload()[-1].add_related(logo.read_bytes(),maintype='image',subtype='png',cid='<mediturno-logo>',filename='mediturno.png',disposition='inline')
    return email
