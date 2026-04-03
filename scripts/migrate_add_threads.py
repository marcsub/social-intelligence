"""
scripts/migrate_add_threads.py
Añade 'threads' al ENUM canal de la tabla publicaciones.

Ejecutar UNA SOLA VEZ antes de usar el agente Threads:
    python scripts/migrate_add_threads.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.settings import get_settings
from models.database import create_db_engine
from sqlalchemy import text

SQL = """
ALTER TABLE publicaciones
  MODIFY COLUMN canal
    ENUM('web','instagram_post','instagram_story','facebook','x','tiktok','youtube','threads')
    NOT NULL;
"""

def main():
    settings = get_settings()
    engine = create_db_engine(settings.db_url)
    with engine.begin() as conn:
        conn.execute(text(SQL))
    print("Migración completada: 'threads' añadido al ENUM canal.")

if __name__ == "__main__":
    main()
