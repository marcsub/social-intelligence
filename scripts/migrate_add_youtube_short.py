"""
scripts/migrate_add_youtube_short.py
Añade 'youtube_short' al ENUM canal y 'short' al ENUM tipo en publicaciones.

Uso:
    python scripts/migrate_add_youtube_short.py
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
        (
            "canal",
            """ALTER TABLE publicaciones MODIFY COLUMN canal ENUM(
                'web','instagram_post','instagram_story','facebook',
                'youtube','youtube_short','x','tiktok','threads','reel'
            ) NOT NULL""",
        ),
        (
            "tipo",
            """ALTER TABLE publicaciones MODIFY COLUMN tipo ENUM(
                'articulo','post','story','reel','video','tweet','short'
            ) NOT NULL""",
        ),
    ]

    with engine.connect() as conn:
        for col, stmt in stmts:
            try:
                conn.execute(text(stmt))
                conn.commit()
                print(f"OK: columna '{col}' actualizada")
            except Exception as ex:
                if "Duplicate" in str(ex) or "already exists" in str(ex).lower():
                    print(f"SKIP: '{col}' ya estaba actualizado")
                else:
                    print(f"ERROR en '{col}': {ex}")
                    raise

    print("Migración completada.")


if __name__ == "__main__":
    main()
