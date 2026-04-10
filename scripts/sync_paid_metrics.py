"""
scripts/sync_paid_metrics.py
Sincronización manual de métricas de promoción pagada desde APIs de Ads.

Uso:
    python scripts/sync_paid_metrics.py --slug roadrunningreview
    python scripts/sync_paid_metrics.py --slug roadrunningreview --canal meta
    python scripts/sync_paid_metrics.py --slug roadrunningreview --canal google
    python scripts/sync_paid_metrics.py --slug roadrunningreview --canal all

Canales soportados:
    meta   — Meta Marketing API (Facebook + Instagram). Requiere ads_read.
    google — Google Ads API v17 (YouTube). Requiere authorize_google_ads.py.
    all    — Todos los canales disponibles.

El script loguea claramente si algún canal no tiene credenciales/permisos
y qué pasos seguir para activarlo.
"""
import sys
import os
import logging
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import sessionmaker
from core.settings import get_settings
from models.database import create_db_engine, Medio

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
log = logging.getLogger("sync_paid_metrics")

CANALES = ["all", "meta", "google"]


def main():
    parser = argparse.ArgumentParser(description="Sync métricas pagadas desde APIs de Ads")
    parser.add_argument("--slug",  required=True, help="Slug del medio")
    parser.add_argument("--canal", default="all", choices=CANALES)
    args = parser.parse_args()

    settings = get_settings()
    engine = create_db_engine(settings.db_url)
    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as db:
        medio = db.query(Medio).filter(Medio.slug == args.slug).first()
        if not medio:
            log.error(f"Medio '{args.slug}' no encontrado"); sys.exit(1)

        log.info(f"=== Sync métricas pagadas para '{medio.slug}' | canal={args.canal} ===")
        total = 0

        if args.canal in ("all", "meta"):
            log.info("--- Iniciando sync Meta Ads (Facebook + Instagram) ---")
            try:
                from agents import meta_ads_agent
                n = meta_ads_agent.sync_paid_metrics(db, medio)
                log.info(f"Meta Ads completado: {n} posts actualizados")
                total += n
            except Exception as ex:
                log.error(f"Error en Meta Ads sync: {ex}")

        if args.canal in ("all", "google"):
            log.info("--- Iniciando sync Google Ads (YouTube) ---")
            try:
                from agents import google_ads_agent
                # Verificar acceso primero
                ok, msg = google_ads_agent.check_access(db, medio.id)
                if not ok:
                    log.warning(f"Google Ads no disponible: {msg}")
                else:
                    n = google_ads_agent.sync_paid_metrics(db, medio)
                    log.info(f"Google Ads completado: {n} vídeos actualizados")
                    total += n
            except Exception as ex:
                log.error(f"Error en Google Ads sync: {ex}")

        log.info(f"=== Sync completado — {total} publicaciones actualizadas con datos pagados ===")

        if total == 0:
            log.info(
                "Sin actualizaciones. Posibles causas:\n"
                "  · Meta: falta permiso 'ads_read' — ver agente meta_ads_agent.py\n"
                "  · Google: credenciales no configuradas — ejecutar authorize_google_ads.py\n"
                "  · No hay campañas activas para este medio en el período"
            )


if __name__ == "__main__":
    main()
