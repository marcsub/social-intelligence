"""
scripts/fix_2026.py
Diagnóstico y corrección del problema de publicaciones 2026 no detectadas.

Síntoma: el checkpoint del agente web/youtube puede estar en una fecha reciente
(e.g. 2026-01-15), filtrando artículos que tienen lastmod == fecha de publicación
anterior a ese checkpoint.

Uso:
    python scripts/fix_2026.py --slug roadrunningreview [--agente web] [--dry-run]
    python scripts/fix_2026.py --slug roadrunningreview --reset   # limpia checkpoints
"""
import sys
import os
import logging
import argparse
from datetime import datetime, timezone

# Añadir el directorio raíz al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import sessionmaker
from core.settings import get_settings
from models.database import create_db_engine, Medio, LogEjecucion

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s"
)
log = logging.getLogger("fix_2026")


def main():
    parser = argparse.ArgumentParser(description="Fix publicaciones 2026 no detectadas")
    parser.add_argument("--slug", required=True, help="Slug del medio")
    parser.add_argument("--agente", default=None, help="Agente específico (web, youtube). Por defecto: ambos")
    parser.add_argument("--dry-run", action="store_true", help="Solo diagnóstico, sin cambios")
    parser.add_argument("--reset", action="store_true", help="Limpia los checkpoints para forzar re-detección")
    parser.add_argument("--run-detect", action="store_true", help="Ejecuta detect_new() tras limpiar checkpoints")
    args = parser.parse_args()

    settings = get_settings()
    engine = create_db_engine(settings.db_url)
    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as db:
        medio = db.query(Medio).filter(Medio.slug == args.slug).first()
        if not medio:
            log.error(f"Medio '{args.slug}' no encontrado")
            sys.exit(1)

        log.info(f"=== Diagnóstico para medio: {medio.slug} ===")

        agentes = [args.agente] if args.agente else ["web", "youtube"]

        # ── 1. Diagnóstico: checkpoints actuales ─────────────────────────────
        for agente in agentes:
            last_ok = (
                db.query(LogEjecucion)
                .filter(
                    LogEjecucion.medio_id == medio.id,
                    LogEjecucion.agente == agente,
                    LogEjecucion.estado == "ok",
                )
                .order_by(LogEjecucion.fin.desc())
                .first()
            )
            if last_ok:
                fin = last_ok.fin
                if fin and fin.tzinfo is None:
                    fin = fin.replace(tzinfo=timezone.utc)
                log.info(f"  [{agente}] Último checkpoint (ok): {fin} — log_id={last_ok.id}")
                if fin and fin.year >= 2026 and fin.month >= 1:
                    log.warning(
                        f"  [{agente}] ⚠️  Checkpoint en 2026 ({fin.date()}) — "
                        "podría estar filtrando artículos recientes con lastmod anterior"
                    )
            else:
                log.info(f"  [{agente}] Sin checkpoint — primera ejecución")

        # ── 2. Contar publicaciones existentes en 2026 ────────────────────────
        from models.database import Publicacion, CanalEnum
        canal_map = {"web": CanalEnum.web, "youtube": CanalEnum.youtube}
        inicio_2026 = datetime(2026, 1, 1, tzinfo=timezone.utc)

        for agente in agentes:
            canal = canal_map.get(agente)
            if not canal:
                continue
            count_2026 = (
                db.query(Publicacion)
                .filter(
                    Publicacion.medio_id == medio.id,
                    Publicacion.canal == canal,
                    Publicacion.fecha_publicacion >= inicio_2026,
                )
                .count()
            )
            total = (
                db.query(Publicacion)
                .filter(Publicacion.medio_id == medio.id, Publicacion.canal == canal)
                .count()
            )
            log.info(f"  [{agente}] Publicaciones totales: {total} | de 2026 en adelante: {count_2026}")

        if args.dry_run:
            log.info("=== Dry-run: sin cambios ===")
            return

        # ── 3. Reset de checkpoints ───────────────────────────────────────────
        if args.reset:
            for agente in agentes:
                deleted = (
                    db.query(LogEjecucion)
                    .filter(
                        LogEjecucion.medio_id == medio.id,
                        LogEjecucion.agente == agente,
                        LogEjecucion.estado == "ok",
                    )
                    .delete()
                )
                log.info(f"  [{agente}] Checkpoints eliminados: {deleted} registros de log")
            db.commit()
            log.info("=== Checkpoints limpiados. En la próxima ejecución se usará fallback de 365 días ===")

        # ── 4. Ejecutar detect_new() manualmente ─────────────────────────────
        if args.run_detect:
            from agents import web_agent, youtube_agent
            agent_map = {"web": web_agent, "youtube": youtube_agent}

            for agente in agentes:
                agent = agent_map.get(agente)
                if not agent:
                    continue
                log.info(f"  [{agente}] Ejecutando detect_new() con checkpoint=None...")
                try:
                    nuevas = agent.detect_new(db, medio, checkpoint=None)
                    log.info(f"  [{agente}] detect_new() completado: {len(nuevas)} nuevas publicaciones")
                except Exception as ex:
                    log.error(f"  [{agente}] Error en detect_new(): {ex}")


if __name__ == "__main__":
    main()
