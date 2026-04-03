"""
scripts/reset_checkpoint.py
Resetea el checkpoint del agente web para un medio, permitiendo
re-importar artículos a partir de una fecha concreta.

Uso:
  python scripts/reset_checkpoint.py [slug] [fecha_ISO]

Ejemplos:
  python scripts/reset_checkpoint.py                         # muestra logs actuales
  python scripts/reset_checkpoint.py roadrunningreview       # borra todos los logs web
  python scripts/reset_checkpoint.py roadrunningreview 2025-01-01  # pone checkpoint a esa fecha
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone
from sqlalchemy.orm import sessionmaker
from core.settings import get_settings
from models.database import create_db_engine, Medio, LogEjecucion

settings = get_settings()
engine   = create_db_engine(settings.db_url)
Session  = sessionmaker(bind=engine)

SLUG  = sys.argv[1] if len(sys.argv) > 1 else "roadrunningreview"
FECHA = sys.argv[2] if len(sys.argv) > 2 else None


def main():
    with Session() as db:
        medio = db.query(Medio).filter(Medio.slug == SLUG).first()
        if not medio:
            print(f"Medio '{SLUG}' no encontrado")
            return

        logs = (
            db.query(LogEjecucion)
            .filter(LogEjecucion.medio_id == medio.id, LogEjecucion.agente == "web")
            .order_by(LogEjecucion.inicio.desc())
            .all()
        )

        print(f"\nLogs actuales del agente web para '{SLUG}':")
        for l in logs:
            print(f"  id={l.id}  inicio={l.inicio}  fin={l.fin}  estado={l.estado}  nuevas={l.publicaciones_nuevas}")

        if not FECHA and len(sys.argv) < 2:
            print("\nUso: python scripts/reset_checkpoint.py [slug] [YYYY-MM-DD]")
            print("  Sin fecha → borra todos los logs (próxima ejecución importa todo)")
            print("  Con fecha → ajusta el checkpoint a esa fecha")
            return

        if FECHA:
            # Ajustar checkpoint: poner el fin del último log OK a la fecha indicada
            try:
                nueva_fecha = datetime.strptime(FECHA, "%Y-%m-%d").replace(
                    hour=0, minute=0, second=0, tzinfo=timezone.utc
                )
            except ValueError:
                print(f"Formato de fecha inválido: '{FECHA}'. Usar YYYY-MM-DD")
                return

            # Borrar todos los logs existentes y crear uno artificial con fin=nueva_fecha
            for l in logs:
                db.delete(l)

            fake_log = LogEjecucion(
                medio_id=medio.id,
                agente="web",
                tipo_ejecucion="manual_reset",
                inicio=nueva_fecha,
                fin=nueva_fecha,
                publicaciones_nuevas=0,
                estado="ok",
            )
            db.add(fake_log)
            db.commit()
            print(f"\nCheckpoint ajustado a {nueva_fecha.date()}")
            print(f"La próxima ejecución importará artículos publicados DESPUÉS de {nueva_fecha.date()}")

        else:
            # Borrar todos los logs → sin checkpoint → se importa todo
            confirm = input(f"\nBorrar {len(logs)} log(s) para '{SLUG}'? Esto importará TODOS los artículos del sitemap. [s/N] ")
            if confirm.lower() == "s":
                for l in logs:
                    db.delete(l)
                db.commit()
                print("Logs borrados. La próxima ejecución no tendrá checkpoint.")
            else:
                print("Cancelado.")


if __name__ == "__main__":
    main()
