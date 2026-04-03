"""
scripts/validate_semanal.py
Diagnóstico del histórico semanal en historial_metricas.

Muestra por canal:
  - Publicaciones con al menos un snapshot semanal
  - Total de semanas distintas con datos
  - SUM(reach_diff) total (verificación de coherencia)
  - Últimas 4 semanas con reach_diff desglosado por canal
  - ALERTA si reach_diff = 0 en todas las semanas (backfill no funcionó)

Uso:
    python scripts/validate_semanal.py --slug roadrunningreview
    python scripts/validate_semanal.py --slug roadrunningreview --semanas 8
"""
import sys
import os
import argparse
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug",    required=True)
    parser.add_argument("--semanas", type=int, default=4, help="Semanas recientes a mostrar (default: 4)")
    args = parser.parse_args()

    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import func
    from core.settings import get_settings
    from models.database import (
        create_db_engine, Medio, Publicacion, HistorialMetricas,
        CanalEnum, EstadoMetricasEnum
    )

    settings = get_settings()
    engine = create_db_engine(settings.db_url)
    Session = sessionmaker(bind=engine)

    W = 72
    CANALES = ["web", "youtube", "instagram_post", "facebook", "threads"]

    with Session() as db:
        medio = db.query(Medio).filter(Medio.slug == args.slug).first()
        if not medio:
            print(f"ERROR: Medio '{args.slug}' no encontrado")
            sys.exit(1)

        print(f"\n{'─'*W}")
        print(f"  validate_semanal — {medio.nombre} ({args.slug})")
        print(f"{'─'*W}\n")

        # ── Por canal: resumen de cobertura ───────────────────────────────────
        print(f"  {'Canal':<20} {'Pubs con snaps':<16} {'Semanas':<10} {'reach_diff total':>18}  Estado")
        print(f"  {'─'*20} {'─'*16} {'─'*10} {'─'*18}  {'─'*12}")

        alertas = []
        for canal_str in CANALES:
            try:
                canal_enum = CanalEnum(canal_str)
            except ValueError:
                continue

            rows = (
                db.query(
                    HistorialMetricas.publicacion_id,
                    HistorialMetricas.semana_iso,
                    HistorialMetricas.reach_diff,
                )
                .join(Publicacion, HistorialMetricas.publicacion_id == Publicacion.id)
                .filter(
                    Publicacion.medio_id == medio.id,
                    Publicacion.canal == canal_enum,
                    HistorialMetricas.semana_iso.isnot(None),
                )
                .all()
            )

            if not rows:
                print(f"  {canal_str:<20} {'—':<16} {'—':<10} {'—':>18}  sin datos")
                continue

            pubs_con_snaps = len({r.publicacion_id for r in rows})
            semanas_con_datos = len({r.semana_iso for r in rows})
            total_diff = sum(r.reach_diff or 0 for r in rows)

            all_zero = total_diff == 0
            estado = "⚠ reach_diff=0 — backfill pendiente" if all_zero else "OK"
            if all_zero:
                alertas.append(canal_str)

            print(f"  {canal_str:<20} {pubs_con_snaps:<16} {semanas_con_datos:<10} {total_diff:>18,}  {estado}")

        # ── Últimas N semanas: reach_diff por canal ───────────────────────────
        print(f"\n  Últimas {args.semanas} semanas con reach_diff por canal:\n")

        # Obtener las últimas N semanas que tienen datos en cualquier canal
        all_semanas_rows = (
            db.query(HistorialMetricas.semana_iso)
            .join(Publicacion, HistorialMetricas.publicacion_id == Publicacion.id)
            .filter(
                Publicacion.medio_id == medio.id,
                HistorialMetricas.semana_iso.isnot(None),
            )
            .distinct()
            .order_by(HistorialMetricas.semana_iso.desc())
            .limit(args.semanas)
            .all()
        )
        semanas_recientes = sorted([r.semana_iso for r in all_semanas_rows])

        if not semanas_recientes:
            print("  Sin snapshots semanales en historial_metricas.")
        else:
            # Cabecera
            semana_cols = "  ".join(f"{s:<10}" for s in semanas_recientes)
            print(f"  {'Canal':<20}  {semana_cols}")
            print(f"  {'─'*20}  " + "  ".join("─"*10 for _ in semanas_recientes))

            for canal_str in CANALES:
                try:
                    canal_enum = CanalEnum(canal_str)
                except ValueError:
                    continue

                # reach_diff por semana para este canal
                rows = (
                    db.query(
                        HistorialMetricas.semana_iso,
                        func.coalesce(func.sum(HistorialMetricas.reach_diff), 0).label("diff"),
                    )
                    .join(Publicacion, HistorialMetricas.publicacion_id == Publicacion.id)
                    .filter(
                        Publicacion.medio_id == medio.id,
                        Publicacion.canal == canal_enum,
                        HistorialMetricas.semana_iso.in_(semanas_recientes),
                    )
                    .group_by(HistorialMetricas.semana_iso)
                    .all()
                )
                diff_por_semana = {r.semana_iso: int(r.diff) for r in rows}

                cols = "  ".join(
                    f"{diff_por_semana.get(s, 0):>10,}" for s in semanas_recientes
                )
                print(f"  {canal_str:<20}  {cols}")

        # ── Alertas ───────────────────────────────────────────────────────────
        if alertas:
            print(f"\n  ⚠  ALERTAS — canales con reach_diff=0 en todas las semanas:")
            for c in alertas:
                print(f"     • {c}: ejecutar `python scripts/backfill_historico.py --slug {args.slug} --canal {c.replace('_post','').replace('instagram','instagram')}`")
        else:
            print(f"\n  ✓  Todos los canales con datos tienen reach_diff > 0")

        print(f"\n{'─'*W}\n")


if __name__ == "__main__":
    main()
