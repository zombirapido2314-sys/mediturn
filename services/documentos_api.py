"""Adaptacion de documentos_api.py de MACCEL para DNI en MediTurno."""
import hashlib
import json
import os
import re
import sqlite3
import time
from contextlib import closing
from pathlib import Path
import requests
from flask import current_app

class QueryError(Exception):
    def __init__(self,message,status=503):
        super().__init__(message)
        self.status=status

def token():
    if os.getenv('MEDITURNO_APISPERU',os.getenv('MACCEL_APISPERU','1'))!='1':
        raise QueryError('La consulta automatica esta desactivada. Puedes completar los datos manualmente.')
    value=(os.getenv('MEDITURNO_APISPERU_TOKEN','') or os.getenv('MACCEL_APISPERU_TOKEN','')).strip()
    filename=os.getenv('MEDITURNO_APISPERU_JSON','').strip()
    if not value and filename:
        try:
            file=Path(filename)
            if not file.is_absolute():file=Path(current_app.root_path)/file
            if file.stat().st_size>16000:raise ValueError('Archivo demasiado grande')
            data=json.loads(file.read_text(encoding='utf-8-sig'))
            if isinstance(data,dict):
                value=next((data[k] for k in ('token','apisperu_token','access_token','APISPERU_TOKEN') if isinstance(data.get(k),str) and data[k].strip()),'')
        except (OSError,ValueError):
            value=''
    if not isinstance(value,str) or not value.strip() or len(value)>8000 or any(c.isspace() for c in value):
        raise QueryError('Falta configurar el token de APIS Peru. Puedes completar los datos manualmente.')
    return value.strip()

def configured():
    try:
        token();return True
    except QueryError:return False

def limit(user_id,hospital_id):
    # Adaptado de MACCEL: cuotas compartidas entre procesos sin guardar DNI ni token.
    file=Path(current_app.root_path)/'.private'/'consultas-dni.sqlite3'
    now=time.time()
    keys=[(f'usuario:{user_id}',10),(f'hospital:{hospital_id}',30),('global',60)]
    keys=[(hashlib.sha256(k.encode()).hexdigest(),n) for k,n in keys]
    try:
        file.parent.mkdir(parents=True,exist_ok=True)
        with closing(sqlite3.connect(file,timeout=2)) as db,db:
            db.execute('CREATE TABLE IF NOT EXISTS consultas(clave TEXT NOT NULL,fecha REAL NOT NULL)')
            db.execute('CREATE INDEX IF NOT EXISTS consultas_clave_fecha ON consultas(clave,fecha)')
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM consultas WHERE fecha<?',(now-60,))
            for key,maximum in keys:
                if db.execute('SELECT count(*) FROM consultas WHERE clave=?',(key,)).fetchone()[0]>=maximum:
                    raise QueryError('Has realizado varias consultas. Espera un minuto o ingresa los datos manualmente.',429)
            db.executemany('INSERT INTO consultas VALUES(?,?)',[(key,now) for key,_ in keys])
    except (OSError,sqlite3.Error):
        raise QueryError('La consulta automatica no esta disponible. Ingresa los datos manualmente.') from None

def lookup(dni):
    if not re.fullmatch('[0-9]{8}',dni):raise QueryError('El DNI debe tener ocho digitos.',422)
    secret=token()
    try:
        response=requests.get('https://dniruc.apisperu.com/api/v1/dni/'+dni,
                              params={'token':secret},headers={'Accept':'application/json'},
                              timeout=(3,8),allow_redirects=False)
        if response.status_code==404:raise QueryError('DNI no encontrado. Verifica el documento o completa los datos manualmente.',404)
        if response.status_code in (401,403):raise QueryError('APIS Peru rechazo la autorizacion. Revisa el token; puedes continuar manualmente.')
        if response.status_code==429:raise QueryError('Se alcanzo el limite del servicio. Puedes continuar manualmente.',429)
        if response.status_code!=200:raise QueryError('APIS Peru no respondio correctamente. Puedes continuar manualmente.')
        data=response.json()
        if not isinstance(data,dict) or str(data.get('dni',''))!=dni:
            raise QueryError('No se recibieron datos validos para ese DNI. Puedes continuar manualmente.',404)
        fields=[data.get(k,'') for k in ('nombres','apellidoPaterno','apellidoMaterno')]
        if any(not isinstance(v,str) for v in fields):raise QueryError('El servicio devolvio datos incompletos.')
        result={'nombres':fields[0].strip(),'apellidos':' '.join(v.strip() for v in fields[1:] if v.strip())}
        if any(not 1<=len(v)<=80 or any(ord(c)<32 for c in v) for v in result.values()):
            raise QueryError('El servicio devolvio datos incompletos o demasiado largos. Verifica el documento manualmente.')
        return result
    except (requests.RequestException,ValueError):
        # La URL del error puede contener el token: no imprimir ni devolver excepciones.
        raise QueryError('No pudimos conectar con APIS Peru. Puedes completar los datos manualmente.') from None
