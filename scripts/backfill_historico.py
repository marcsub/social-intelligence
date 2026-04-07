"""
scripts/backfill_historico.py
Carga histórica de snapshots semanales ISO para publicaciones de 2026.

Uso:
    python scripts/backfill_historico.py --slug roadrunningreview
    python scripts/backfill_historico.py --slug roadrunningreview --canal web
    python scripts/backfill_historico.py --slug roadrunningreview --canal youtube
    python scripts/backfill_historico.py --slug roadrunningreview --canal instagram
    python scripts/backfill_historico.py --slug roadrunningreview --canal facebook
    python scripts/backfill_historico.py --slug roadrunningreview --canal threads
    python scripts/backfill_historico.py --slug roadrunningreview --canal youtube_short
    python scripts/backfill_historico.py --slug roadrunningreview --canal all
    python scripts/backfill_historico.py --slug roadrunningreview --anio 2026 --dry-run

Para web/GA4 y YouTube Analytics:
    Recalcula semana a semana desde enero del año indicado hasta hoy.
    Solo procesa semanas aún no snapshoteadas.

Para Instagram, Facebook, Threads:
    Guarda el valor actual como snapshot de la semana actual.
    Las semanas anteriores se irán completando cada lunes automáticamente.
"""
import sys
import os
import logging
import argparse
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import sessionmaker
from core.settings import get_settings
from models.database import create_db_engine, Medio
from utils.semanas import get_semana_iso, semanas_entre

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
log = logging.getLogger("backfill")

CANALES_DISPONIBLES = ["all", "web", "youtube", "youtube_short", "instagram", "facebook", "threads"]


def main():
    parser = argparse.ArgumentParser(description="Backfill de snapshots semanales ISO")
    parser.add_argument("--slug",    required=True,  help="Slug del medio")
    parser.add_argument("--canal",   default="all",   choices=CANALES_DISPONIBLES)
    parser.add_argument("--anio",    type=int, default=2026)
    parser.add_argument("--dry-run", action="store_true", help="Solo diagnóstico sin cambios")
    args = parser.parse_args()

    settings = get_settings()
    engine = create_db_engine(settings.db_url)
    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as db:
        medio = db.query(Medio).filter(Medio.slug == args.slug).first()
        if not medio:
            log.error(f"Medio '{args.slug}' no encontrado"); sys.exit(1)

        log.info(f"=== Backfill histórico para {medio.slug} | canal={args.canal} | año={args.anio} ===")

        hoy = date.today()
        inicio = date(args.anio, 1, 1)
        semanas = semanas_entre(inicio, hoy)
        log.info(f"Semanas a procesar: {semanas[0]} → {semanas[-1]} ({len(semanas)} semanas)")

        if args.dry_run:
            log.info("Dry-run: sin cambios"); return

        canales = (
            ["web", "youtube", "youtube_short", "instagram", "facebook", "threads"]
            if args.canal == "all"
            else [args.canal]
        )

        # ── Web / GA4 — histórico real semana a semana ────────────────────────
        if "web" in canales:
            from agents import web_agent
            log.info("--- Iniciando backfill web/GA4 ---")
            log.info("GA4 permite rangos históricos → calculando semana a semana...")
            n = web_agent.update_weekly_ga4(db, medio)
            log.info(f"web/GA4 completado: {n} publicaciones procesadas")

        # ── YouTube Analytics — histórico real semana a semana ────────────────
        if "youtube" in canales:
            from agents import youtube_agent
            log.info("--- Iniciando backfill youtube (Analytics API histórico) ---")
            log.info("YouTube Analytics permite rangos históricos → calculando semana a semana...")
            n = youtube_agent.update_weekly_youtube(db, medio)
            log.info(f"youtube completado: {n} publicaciones procesadas")

        # ── YouTube Shorts Analytics — histórico real semana a semana ────────
        if "youtube_short" in canales:
            from agents import youtube_shorts_agent
            log.info("--- Iniciando backfill youtube_short (Analytics API histórico) ---")
            log.info("YouTube Analytics permite rangos históricos → calculando semana a semana...")
            n = youtube_shorts_agent.snapshot_weekly(db, medio)
            log.info(f"youtube_short completado: {n} publicaciones procesadas")

        # ── RRSS — solo snapshot actual ───────────────────────────────────────
        for canal in ["instagram", "facebook", "threads"]:
            if canal not in canales:
                continue
            log.info(f"--- Iniciando backfill {canal} (solo semana actual) ---")
            log.info(f"NOTA: {canal} no tiene API histórica por semana.")
            log.info(f"      Guardando snapshot de la semana actual ({get_semana_iso(hoy)}).")
            log.info(f"      Las semanas anteriores se llenarán automáticamente cada lunes.")
            try:
                if canal == "instagram":
                    from agents import instagram_agent as agent
                elif canal == "facebook":
                    from agents import facebook_agent as agent
                elif canal == "threads":
                    from agents import threads_agent as agent

                n = agent.snapshot_weekly(db, medio)
                log.info(f"{canal} snapshot completado: {n} publicaciones")
            except Exception as ex:
                log.error(f"Error en {canal} snapshot: {ex}")

        log.info("=== Backfill completado ===")


if __name__ == "__main__":
    main()
