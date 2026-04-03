"""
scripts/migrate_stories_tracking.py
Añade las columnas hora_snapshot y es_final a historial_metricas
para el tracking preciso de Stories por hora.

Uso:
    python scripts/migrate_stories_tracking.py
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

    stmts = [
        "ALTER TABLE historial_metricas ADD COLUMN es_final BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE historial_metricas ADD COLUMN hora_snapshot DATETIME NULL",
    ]

    with engine.connect() as conn:
        for stmt in stmts:
            col = stmt.split("ADD COLUMN ")[1].split(" ")[0]
            try:
                conn.execute(text(stmt))
                conn.commit()
                print(f"OK: columna '{col}' añadida")
            except Exception as ex:
                if "Duplicate column" in str(ex) or "already exists" in str(ex).lower():
                    print(f"SKIP: columna '{col}' ya existe")
                else:
                    print(f"ERROR en '{col}': {ex}")
                    raise

    print("Migración completada.")


if __name__ == "__main__":
    main()
