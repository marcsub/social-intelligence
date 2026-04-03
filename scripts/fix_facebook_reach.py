"""
scripts/fix_facebook_reach.py
Rellena el reach de las publicaciones Facebook existentes usando
update_metrics() del facebook_agent (v25.0).

Uso:
    python scripts/fix_facebook_reach.py --slug roadrunningreview
    python scripts/fix_facebook_reach.py --slug roadrunningreview --batch 25
    python scripts/fix_facebook_reach.py --slug roadrunningreview --only-zeros
    python scripts/fix_facebook_reach.py --slug roadrunningreview --only-zeros --max-retries 5
"""
import sys
import os
import argparse
import logging
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
log = logging.getLogger("fix_facebook_reach")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug",        required=True)
    parser.add_argument("--batch",       type=int, default=50,  help="Posts por lote (default: 50)")
    parser.add_argument("--only-zeros",  action="store_true",   help="Solo procesar publicaciones con reach=0")
    parser.add_argument("--max-retries", type=int, default=3,   help="Reintentos por post con reach=0 (default: 3)")
    args = parser.parse_args()

    from sqlalchemy.orm import sessionmaker
    from core.settings import get_settings
    from models.database import (
        create_db_engine, Medio, Publicacion,
        CanalEnum, EstadoMetricasEnum
    )
    from agents import facebook_agent

    settings = get_settings()
    engine = create_db_engine(settings.db_url)
    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as db:
        medio = db.query(Medio).filter(Medio.slug == args.slug).first()
        if not medio:
            log.error(f"Medio '{args.slug}' no encontrado"); sys.exit(1)

        # Base filter: excluir fijo y sin_datos siempre
        q = (
            db.query(Publicacion)
            .filter(
                Publicacion.medio_id == medio.id,
                Publicacion.canal == CanalEnum.facebook,
                Publicacion.estado_metricas != EstadoMetricasEnum.fijo,
                Publicacion.estado_metricas != EstadoMetricasEnum.sin_datos,
            )
        )

        if args.only_zeros:
            q = q.filter(Publicacion.reach == 0)
            log.info(f"=== fix_facebook_reach --only-zeros — {args.slug} ===")
        else:
            log.info(f"=== fix_facebook_reach — {args.slug} ===")

        pubs = q.order_by(Publicacion.fecha_publicacion.desc()).all()
        total = len(pubs)
        log.info(f"Publicaciones a procesar: {total} (excluyendo fijo/sin_datos)")

        if total == 0:
            log.info("Nada que procesar."); return

        actualizadas = 0
        reach_ok = 0
        reach_cero = 0

        if args.only_zeros:
            # Modo reintento: post a post con hasta max_retries intentos
            for idx, pub in enumerate(pubs, 1):
                log.info(f"[{idx}/{total}] Post {pub.id_externo} (id={pub.id})")
                exito = False
                for intento in range(1, args.max_retries + 1):
                    try:
                        n = facebook_agent.update_metrics(db, medio, [pub])
                        actualizadas += n
                        db.expire_all()
                        pub_recargado = db.query(Publicacion).filter(Publicacion.id == pub.id).first()
                        if pub_recargado and (pub_recargado.reach or 0) > 0:
                            reach_ok += 1
                            log.info(f"  intento {intento}: reach={pub_recargado.reach} ✓")
                            exito = True
                            break
                        else:
                            log.info(f"  intento {intento}: reach=0, reintentando…")
                            if intento < args.max_retries:
                                time.sleep(2)
                    except Exception as ex:
                        log.warning(f"  intento {intento}: error — {ex}")
                        if intento < args.max_retries:
                            time.sleep(2)
                if not exito:
                    reach_cero += 1
                    log.info(f"  → sin reach tras {args.max_retries} intentos")
        else:
            # Modo normal: procesar en lotes
            for i in range(0, total, args.batch):
                lote = pubs[i:i + args.batch]
                log.info(f"Procesando lote {i+1}–{min(i+args.batch, total)} de {total}…")

                n = facebook_agent.update_metrics(db, medio, lote)
                actualizadas += n

                db.expire_all()
                ids_lote = {p.id for p in lote}
                pubs_recargados = db.query(Publicacion).filter(Publicacion.id.in_(ids_lote)).all()
                reach_ok   += sum(1 for p in pubs_recargados if (p.reach or 0) > 0)
                reach_cero += sum(1 for p in pubs_recargados if (p.reach or 0) == 0)

        log.info(
            f"\n=== Resultado ===\n"
            f"  Total procesadas: {total}\n"
            f"  Actualizadas:     {actualizadas}\n"
            f"  reach > 0:        {reach_ok}\n"
            f"  reach = 0:        {reach_cero}"
        )


if __name__ == "__main__":
    main()
