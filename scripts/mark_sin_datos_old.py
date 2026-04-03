"""
scripts/mark_sin_datos_old.py
Marca sin_datos las publicaciones de Instagram y Facebook con:
  - fecha_publicacion < hace 2 años (730 días)
  - reach = 0
  - estado_metricas NOT IN ('sin_datos', 'fijo')

Uso:
    python scripts/mark_sin_datos_old.py --slug roadrunningreview
    python scripts/mark_sin_datos_old.py --slug roadrunningreview --dry-run
"""
import sys
import os
import argparse
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CUTOFF_DAYS = 730


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug",    required=True)
    parser.add_argument("--dry-run", action="store_true", help="Muestra qué haría sin guardar")
    args = parser.parse_args()

    from sqlalchemy.orm import sessionmaker
    from core.settings import get_settings
    from models.database import (
        create_db_engine, Medio, Publicacion,
        CanalEnum, EstadoMetricasEnum
    )

    settings = get_settings()
    engine = create_db_engine(settings.db_url)
    Session = sessionmaker(bind=engine)

    cutoff = datetime.now(timezone.utc) - timedelta(days=CUTOFF_DAYS)
    canales = [CanalEnum.instagram_post, CanalEnum.facebook]

    with Session() as db:
        medio = db.query(Medio).filter(Medio.slug == args.slug).first()
        if not medio:
            print(f"ERROR: Medio '{args.slug}' no encontrado")
            sys.exit(1)

        print(f"\n{'─'*60}")
        print(f"  mark_sin_datos_old — {medio.nombre} ({args.slug})")
        print(f"  Cutoff: {cutoff.strftime('%Y-%m-%d')} (publicaciones anteriores a esta fecha)")
        print(f"{'─'*60}")

        total_marcadas = 0

        for canal in canales:
            pubs = (
                db.query(Publicacion)
                .filter(
                    Publicacion.medio_id == medio.id,
                    Publicacion.canal == canal,
                    Publicacion.reach == 0,
                    Publicacion.estado_metricas != EstadoMetricasEnum.sin_datos,
                    Publicacion.estado_metricas != EstadoMetricasEnum.fijo,
                    Publicacion.fecha_publicacion < cutoff,
                )
                .all()
            )

            if not pubs:
                print(f"  {canal.value}: 0 candidatas")
                continue

            print(f"  {canal.value}: {len(pubs)} candidatas → marcando sin_datos")

            if not args.dry_run:
                for pub in pubs:
                    pub.estado_metricas = EstadoMetricasEnum.sin_datos
                    pub.notas = f"Marcado sin_datos: reach=0 + antigüedad > {CUTOFF_DAYS} días"
                    pub.ultima_actualizacion = datetime.now(timezone.utc)

            total_marcadas += len(pubs)

        if not args.dry_run and total_marcadas > 0:
            db.commit()

        print(f"\n  Total marcadas sin_datos: {total_marcadas}")
        if args.dry_run:
            print("  (dry-run: ningún cambio guardado)")


if __name__ == "__main__":
    main()
