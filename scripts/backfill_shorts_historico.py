"""
scripts/backfill_shorts_historico.py
Escanea el canal completo de YouTube y detecta todos los Shorts históricos.
Usa paginación completa (sin límite de fecha) para recuperar todos los vídeos.

Uso:
    python scripts/backfill_shorts_historico.py --slug roadrunningreview
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
log = logging.getLogger("backfill_shorts")


def main():
    parser = argparse.ArgumentParser(description="Backfill histórico de YouTube Shorts")
    parser.add_argument("--slug", required=True, help="Slug del medio")
    args = parser.parse_args()

    from sqlalchemy.orm import sessionmaker
    from core.settings import get_settings
    from models.database import create_db_engine, Medio
    from agents import youtube_shorts_agent

    settings = get_settings()
    engine = create_db_engine(settings.db_url)
    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as db:
        medio = db.query(Medio).filter(Medio.slug == args.slug).first()
        if not medio:
            log.error(f"Medio '{args.slug}' no encontrado")
            sys.exit(1)

        log.info(f"=== Backfill Shorts histórico para {medio.slug} ===")
        log.info("Escaneo completo del canal sin límite de fecha — puede tardar varios minutos")

        # checkpoint=None → escaneo completo con paginación
        nuevos = youtube_shorts_agent.detect_new(db, medio, checkpoint=None)

        # El resumen detallado (escaneados/shorts/nuevos) aparece en el log de detect_new.
        # Aquí imprimimos solo el total insertado para confirmación final.
        print(f"\nNuevos insertados: {len(nuevos)}")
        if nuevos:
            for pub in nuevos:
                print(f"  [{pub.fecha_publicacion.date()}] {pub.titulo[:70]}")


if __name__ == "__main__":
    main()
