import os

bind='0.0.0.0:'+os.getenv('PORT','10000')
# Los bloqueos de la integración de correo son locales a este único proceso.
workers=1
threads=4
preload_app=False
timeout=120
accesslog='-'
errorlog='-'
# No registrar la cadena de consulta: el retorno OAuth contiene un código privado.
access_log_format='%(h)s %(m)s %(U)s %(s)s %(L)s'
