"""Entrada para Render: un proceso Gunicorn, sin preload, con avisos en segundo plano."""
from app import create_app
from gmail_alertas import start_local_worker

app=create_app()
start_local_worker()
