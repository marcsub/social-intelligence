"""
scripts/fix_shorts_metrics.py
Actualiza las métricas (views, likes, comments) de los Shorts sin métricas.

Selecciona publicaciones con canal='youtube_short' y reach=0 o NULL,
llama a YouTube Data API y actualiza la DB.

Uso:
    python scripts/fix_shorts_metrics.py --slug roadrunningreview
    python scripts/fix_shorts_metrics.py --slug roadrunningreview --dry-run
"""
import sys
import os
import logging
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
log = logging.getLogger("fix_shorts_metrics")


def main():
    parser = argparse.ArgumentParser(description="Fix métricas de YouTube Shorts con reach=0")
    parser.add_argument("--slug",    required=True, help="Slug del medio")
    parser.add_argument("--dry-run", action="store_true", help="Solo diagnóstico, sin actualizar")
    args = parser.parse_args()

    from sqlalchemy import or_
    from sqlalchemy.orm import sessionmaker
    from googleapiclient.discovery import build

    from core.settings import get_settings
    from models.database import (
        create_db_engine, Medio, Publicacion, HistorialMetricas,
        CanalEnum, EstadoMetricasEnum,
    )
    from agents.youtube_agent import _build_credentials
    from agents.youtube_shorts_agent import _get_video_details

    settings = get_settings()
    engine = create_db_engine(settings.db_url)
    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as db:
        medio = db.query(Medio).filter(Medio.slug == args.slug).first()
        if not medio:
            log.error(f"Medio '{args.slug}' no encontrado")
            sys.exit(1)

        # Shorts sin métricas
        pubs = (
            db.query(Publicacion)
            .filter(
                Publicacion.medio_id == medio.id,
                Publicacion.canal == CanalEnum.youtube_short,
                or_(Publicacion.reach == 0, Publicacion.reach.is_(None)),
            )
            .all()
        )

        log.info(f"Shorts con reach=0/NULL: {len(pubs)}")
        if not pubs:
            print("Nada que actualizar.")
            return

        if args.dry_run:
            for p in pubs:
                log.info(f"  [dry-run] {p.id_externo} — {p.titulo[:60]}")
            print(f"Dry-run: {len(pubs)} Shorts serían procesados.")
            return

        # Credenciales y cliente YouTube
        creds = _build_credentials(db, medio.id)
        if not creds:
            log.error("Sin credenciales YouTube — abortando")
            sys.exit(1)

        yt = build("youtube", "v3", credentials=creds, cache_discovery=False)

        # Obtener detalles en una sola llamada batch (hasta 50 por llamada)
        from datetime import datetime, timezone
        BATCH = 50
        actualizadas = 0
        ahora = datetime.now(timezone.utc)

        for i in range(0, len(pubs), BATCH):
            batch_pubs = pubs[i:i + BATCH]
            video_ids = [p.id_externo for p in batch_pubs if p.id_externo]
            details = _get_video_details(yt, video_ids)

            for pub in batch_pubs:
                if not pub.id_externo:
                    continue
                stats = details.get(pub.id_externo)
                if stats is None:
                    log.warning(f"Short {pub.id_externo}: no encontrado en API — omitido")
                    continue

                views    = stats["views"]
                likes    = stats["likes"]
                comments = stats["comments"]
                log.info(f"Short {pub.id_externo}: views={views} likes={likes} comments={comments}")

                pub.reach    = views
                pub.likes    = likes
                pub.comments = comments
                pub.ultima_actualizacion = ahora
                pub.estado_metricas = EstadoMetricasEnum.actualizado

                db.add(HistorialMetricas(
                    publicacion_id=pub.id,
                    reach=views, likes=likes,
                    shares=0, comments=comments, clicks=0,
                ))
                actualizadas += 1

        db.commit()
        print(f"Actualizadas: {actualizadas}")


if __name__ == "__main__":
    main()
