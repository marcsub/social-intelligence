"""
scripts/migrate_add_publicacion_marcas.py
Crea la tabla publicacion_marcas y la puebla con los marca_id existentes.

Uso:
    python scripts/migrate_add_publicacion_marcas.py
    python scripts/migrate_add_publicacion_marcas.py --dry-run
"""
import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    from sqlalchemy import text
    from sqlalchemy.orm import sessionmaker
    from core.settings import get_settings
    from models.database import create_db_engine, Publicacion, PublicacionMarca

    settings = get_settings()
    engine = create_db_engine(settings.db_url)
    Session = sessionmaker(bind=engine)

    # Crear tabla si no existe
    ddl = """
    CREATE TABLE IF NOT EXISTS publicacion_marcas (
        id              INT AUTO_INCREMENT PRIMARY KEY,
        publicacion_id  INT NOT NULL,
        marca_id        INT NOT NULL,
        es_principal    BOOLEAN NOT NULL DEFAULT TRUE,
        UNIQUE KEY uq_pub_marca (publicacion_id, marca_id),
        KEY ix_pub_marcas_pub (publicacion_id),
        CONSTRAINT fk_pm_pub  FOREIGN KEY (publicacion_id) REFERENCES publicaciones(id) ON DELETE CASCADE,
        CONSTRAINT fk_pm_marca FOREIGN KEY (marca_id)       REFERENCES marcas(id)        ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """

    if args.dry_run:
        print("[dry-run] Omitiría: CREATE TABLE IF NOT EXISTS publicacion_marcas ...")
    else:
        with engine.connect() as conn:
            conn.execute(text(ddl))
            conn.commit()
        print("Tabla publicacion_marcas creada (o ya existía).")

    # Poblar desde publicaciones.marca_id
    with Session() as db:
        # Publicaciones con marca_id que aún no tienen fila en publicacion_marcas
        candidates = (
            db.query(Publicacion)
            .filter(Publicacion.marca_id.isnot(None))
            .all()
        )

        existing_pub_ids = set(
            r.publicacion_id
            for r in db.query(PublicacionMarca.publicacion_id).all()
        )

        to_insert = [p for p in candidates if p.id not in existing_pub_ids]

        print(f"Publicaciones con marca_id: {len(candidates)}")
        print(f"Ya en publicacion_marcas:   {len(existing_pub_ids)}")
        print(f"A insertar:                 {len(to_insert)}")

        if args.dry_run:
            print("[dry-run] No se insertará nada.")
            return

        batch = 0
        for p in to_insert:
            db.add(PublicacionMarca(
                publicacion_id=p.id,
                marca_id=p.marca_id,
                es_principal=True,
            ))
            batch += 1
            if batch % 500 == 0:
                db.commit()
                print(f"  {batch} insertadas...")

        db.commit()
        print(f"Migración completada: {batch} filas insertadas en publicacion_marcas.")


if __name__ == "__main__":
    main()
