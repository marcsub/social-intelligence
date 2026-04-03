"""
scripts/migrate_add_sin_datos.py
Añade el valor 'sin_datos' al ENUM estado_metricas en MySQL.

SQLAlchemy's create_all() no modifica columnas ENUM existentes,
por lo que este ALTER TABLE debe ejecutarse una sola vez.

Uso:
    python scripts/migrate_add_sin_datos.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.settings import get_settings
from models.database import create_db_engine

ALTER_SQL = """
ALTER TABLE publicaciones
  MODIFY COLUMN estado_metricas
    ENUM('pendiente','actualizado','error','revisar','fijo','sin_datos')
    NOT NULL DEFAULT 'pendiente';
"""

def main():
    settings = get_settings()
    engine = create_db_engine(settings.db_url)

    with engine.connect() as conn:
        # Verificar el ENUM actual antes de modificar
        result = conn.execute(
            "SELECT COLUMN_TYPE FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() "
            "AND TABLE_NAME = 'publicaciones' "
            "AND COLUMN_NAME = 'estado_metricas'"
        )
        row = result.fetchone()
        if row:
            print(f"ENUM actual: {row[0]}")
            if "sin_datos" in row[0]:
                print("'sin_datos' ya existe en el ENUM — nada que hacer.")
                return

        print("Ejecutando ALTER TABLE...")
        conn.execute(ALTER_SQL)
        conn.commit()
        print("OK: 'sin_datos' añadido al ENUM estado_metricas.")

        # Verificar resultado
        result2 = conn.execute(
            "SELECT COLUMN_TYPE FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() "
            "AND TABLE_NAME = 'publicaciones' "
            "AND COLUMN_NAME = 'estado_metricas'"
        )
        row2 = result2.fetchone()
        print(f"ENUM nuevo: {row2[0] if row2 else '?'}")


if __name__ == "__main__":
    main()
