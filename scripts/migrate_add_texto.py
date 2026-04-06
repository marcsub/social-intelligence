"""
scripts/migrate_add_texto.py
Añade la columna texto TEXT NULL a la tabla publicaciones.

Uso:
    python scripts/migrate_add_texto.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    from sqlalchemy import text
    from core.settings import get_settings
    from models.database import create_db_engine

    settings = get_settings()
    engine = create_db_engine(settings.db_url)

    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE publicaciones ADD COLUMN texto TEXT NULL"))
            conn.commit()
            print("OK: columna 'texto' añadida a publicaciones")
        except Exception as ex:
            if "Duplicate column" in str(ex) or "already exists" in str(ex).lower():
                print("SKIP: columna 'texto' ya existe")
            else:
                print(f"ERROR: {ex}")
                raise

    print("Migración completada.")


if __name__ == "__main__":
    main()
