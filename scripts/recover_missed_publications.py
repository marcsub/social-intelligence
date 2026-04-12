"""
scripts/recover_missed_publications.py
Recupera publicaciones perdidas reseteando checkpoints y ejecutando detección inmediata.

Uso:
  python scripts/recover_missed_publications.py [slug] [fecha_desde]

Ejemplos:
  python scripts/recover_missed_publications.py roadrunningreview 2026-04-01
  python scripts/recover_missed_publications.py roadrunningreview          # usa 2026-04-01 por defecto

Qué hace:
  1. Muestra los checkpoints actuales de todos los agentes
  2. Resetea el checkpoint de TODOS los agentes a fecha_desde
  3. Ejecuta run_agent() para cada agente inmediatamente
  4. Muestra resumen de publicaciones nuevas detectadas
"""
import sys
import os
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
log = logging.getLogger("recover")

from datetime import datetime, timezone
from sqlalchemy.orm import sessionmaker
from core.settings import get_settings
from models.database import create_db_engine, Medio, LogEjecucion
from core.orchestrator import run_agent, AGENTS

settings = get_settings()
engine   = create_db_engine(settings.db_url)
Session  = sessionmaker(bind=engine)

SLUG       = sys.argv[1] if len(sys.argv) > 1 else "roadrunningreview"
FECHA_STR  = sys.argv[2] if len(sys.argv) > 2 else "2026-04-01"


def reset_checkpoint(db, medio_id: int, agente: str, nueva_fecha: datetime):
    """Borra logs previos y crea uno artificial con fin=nueva_fecha para que el agente
    detecte todo lo publicado DESPUÉS de esa fecha."""
    logs = (
        db.query(LogEjecucion)
        .filter(LogEjecucion.medio_id == medio_id, LogEjecucion.agente == agente)
        .all()
    )
    for l in logs:
        db.delete(l)

    fake = LogEjecucion(
        medio_id=medio_id,
        agente=agente,
        tipo_ejecucion="manual_reset",
        inicio=nueva_fecha,
        fin=nueva_fecha,
        publicaciones_nuevas=0,
        estado="ok",
    )
    db.add(fake)
    db.commit()
    log.info(f"  [{agente}] checkpoint → {nueva_fecha.date()}")


def main():
    try:
        fecha_desde = datetime.strptime(FECHA_STR, "%Y-%m-%d").replace(
            hour=0, minute=0, second=0, tzinfo=timezone.utc
        )
    except ValueError:
        log.error(f"Formato de fecha inválido: '{FECHA_STR}'. Usar YYYY-MM-DD")
        sys.exit(1)

    with Session() as db:
        medio = db.query(Medio).filter(Medio.slug == SLUG).first()
        if not medio:
            log.error(f"Medio '{SLUG}' no encontrado")
            sys.exit(1)

        log.info(f"=== Recuperación de publicaciones para '{SLUG}' ===")
        log.info(f"Fecha desde: {fecha_desde.date()}")

        # 1. Mostrar checkpoints actuales
        log.info("\n--- Checkpoints actuales ---")
        for agente_name in AGENTS:
            last = (
                db.query(LogEjecucion)
                .filter(
                    LogEjecucion.medio_id == medio.id,
                    LogEjecucion.agente == agente_name,
                    LogEjecucion.estado == "ok",
                )
                .order_by(LogEjecucion.fin.desc())
                .first()
            )
            if last and last.fin:
                log.info(f"  [{agente_name}] último OK: {last.fin.strftime('%Y-%m-%d %H:%M UTC')}")
            else:
                log.info(f"  [{agente_name}] sin checkpoint (detectará todo)")

        # 2. Resetear checkpoints
        log.info(f"\n--- Reseteando checkpoints a {fecha_desde.date()} ---")
        for agente_name in AGENTS:
            reset_checkpoint(db, medio.id, agente_name, fecha_desde)

        # 3. Ejecutar detección inmediata para cada agente
        log.info("\n--- Ejecutando detección inmediata ---")
        total_nuevas = 0
        total_actualizadas = 0

        for agente_name in AGENTS:
            log.info(f"\n[{agente_name}] iniciando...")
            try:
                result = run_agent(db, medio, agente_name, tipo="manual_recovery")
                nuevas      = result.get("nuevas", 0)
                actualizadas = result.get("actualizadas", 0)
                total_nuevas       += nuevas
                total_actualizadas += actualizadas
                log.info(f"[{agente_name}] ✓ nuevas={nuevas} actualizadas={actualizadas}")
            except Exception as ex:
                log.error(f"[{agente_name}] ERROR: {ex}")

        # 4. Resumen
        log.info(f"\n=== RESUMEN ===")
        log.info(f"Total publicaciones nuevas detectadas: {total_nuevas}")
        log.info(f"Total métricas actualizadas:           {total_actualizadas}")
        log.info("Recuperación completada.")


if __name__ == "__main__":
    main()
