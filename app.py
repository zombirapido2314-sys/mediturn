import os
from pathlib import Path
from dotenv import load_dotenv
from flask import Flask, render_template
from controllers.web import web
from controllers.administracion_controller import admin
from controllers.correo_controller import correo
from controllers.gestion_controller import gestion
from controllers.espacio_controller import espacio

load_dotenv(Path(__file__).parent / '.env')

def create_app():
    app=Flask(__name__)
    key=os.getenv('SECRET_KEY','')
    if len(key)<32 or key=='reemplazar-por-una-clave-larga-aleatoria':
        raise RuntimeError('Configura SECRET_KEY en .env con una clave aleatoria de al menos 32 caracteres.')
    app.config.update(SECRET_KEY=key,SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE='Lax',
                      SESSION_COOKIE_SECURE=os.getenv('COOKIE_SECURE')=='1',MAX_CONTENT_LENGTH=16384)
    if os.getenv('TRUST_RENDER_PROXY')=='1':
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app=ProxyFix(app.wsgi_app,x_for=1,x_proto=1,x_host=0,x_port=0,x_prefix=0)
    @app.get('/salud')
    def health():
        # Comprueba el proceso sin exponer datos ni abrir conexiones a PostgreSQL.
        return {'estado':'ok'},200,{'Cache-Control':'no-store'}
    app.register_blueprint(web)
    app.register_blueprint(admin)
    app.register_blueprint(correo)
    app.register_blueprint(gestion)
    app.register_blueprint(espacio)
    @app.context_processor
    def identity_context():
        from flask import g
        return {'current_user':getattr(g,'user',None)}
    @app.errorhandler(500)
    def server_error(error):
        return render_template('error.html'),500
    return app

if __name__=='__main__':
    from gmail_alertas import start_local_worker
    from werkzeug.serving import WSGIRequestHandler
    class PrivateOAuthLog(WSGIRequestHandler):
        def log_request(self,code='-',size='-'):
            if self.path.split('?')[0]=='/correo/respuesta':
                self.log('info','"GET /correo/respuesta [OAuth]" %s %s',code,size)
            else:
                super().log_request(code,size)
    application=create_app()
    start_local_worker()
    application.run(host='127.0.0.1',port=5000,debug=False,request_handler=PrivateOAuthLog)
