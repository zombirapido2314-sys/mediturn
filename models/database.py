"""Una conexion por operacion; la transaccion confirma o revierte al salir."""
import os
from contextlib import contextmanager
import psycopg2
from psycopg2.extras import RealDictCursor

@contextmanager
def transaction():
    connection = psycopg2.connect(
        host=os.getenv('DB_HOST', 'localhost'), port=os.getenv('DB_PORT', '5432'),
        dbname=os.getenv('DB_NAME', 'mediturno'), user=os.getenv('DB_USER', 'postgres'),
        password=os.getenv('DB_PASSWORD', ''), sslmode=os.getenv('DB_SSLMODE', 'prefer'),
        connect_timeout=5,
    )
    try:
        with connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                yield cursor
    finally:
        connection.close()
