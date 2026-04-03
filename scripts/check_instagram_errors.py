"""
scripts/check_instagram_errors.py
Muestra diagnóstico de posts Instagram con estado_metricas='error':

  - Total posts en error
  - Cuántos llevan >= N intentos fallidos (por defecto 3)
  - IDs específicos para investigar manualmente en Instagram
  - Breakdown por tipo (post, reel, video)

Uso:
    python scripts/check_instagram_errors.py --slug roadrunningreview
    python scripts/check_instagram_errors.py --slug roadrunningreview --min-intentos 2
"""
import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_INTENTOS_PREFIX = "intentos_fallidos:"

def _parse_intentos(notas) -> int:
    if not notas:
        return 0
    for part in str(notas).split("|"):
        if part.startswith(_INTENTOS_PREFIX):
            try:
                return int(part[len(_INTENTOS_PREFIX):])
            except ValueError:
                pass
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug",         required=True)
    parser.add_argument("--min-intentos", type=int, default=3,
                        help="Umbral de intentos fallidos para destacar (default: 3)")
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

    with Session() as db:
        medio = db.query(Medio).filter(Medio.slug == args.slug).first()
        if not medio:
            print(f"ERROR: Medio '{args.slug}' no encontrado")
            sys.exit(1)

        # Todos los posts Instagram en error
        errors = (
            db.query(Publicacion)
            .filter(
                Publicacion.medio_id == medio.id,
                Publicacion.canal == CanalEnum.instagram_post,
                Publicacion.estado_metricas == EstadoMetricasEnum.error,
            )
            .order_by(Publicacion.fecha_publicacion.desc())
            .all()
        )

        print(f"\n{'─'*70}")
        print(f"  check_instagram_errors — {medio.nombre} ({args.slug})")
        print(f"{'─'*70}")
        print(f"\n  Total posts Instagram con estado=error: {len(errors)}")

        if not errors:
            print("  Nada que revisar.")
            return

        # Clasificar por intentos
        sin_contador  = [p for p in errors if _parse_intentos(p.notas) == 0]
        con_contador  = [p for p in errors if _parse_intentos(p.notas) > 0]
        umbral_alto   = [p for p in errors if _parse_intentos(p.notas) >= args.min_intentos]

        print(f"  Sin contador de intentos aún: {len(sin_contador)}")
        print(f"  Con al menos 1 intento fallido: {len(con_contador)}")
        print(f"  Con >= {args.min_intentos} intentos fallidos: {len(umbral_alto)}")

        # Breakdown por tipo
        from collections import Counter
        tipos = Counter(p.tipo.value if p.tipo else "?" for p in errors)
        print(f"\n  Por tipo:")
        for tipo, n in sorted(tipos.items(), key=lambda x: -x[1]):
            print(f"    {tipo:<20} {n}")

        # Posts con >= min_intentos: listado detallado para investigar
        if umbral_alto:
            print(f"\n  Posts con >= {args.min_intentos} intentos fallidos (para investigar manualmente):")
            print(f"  {'ID externo':<25} {'Fecha pub':<12} {'Tipo':<10} {'Intentos':<10} Notas")
            print(f"  {'─'*25} {'─'*12} {'─'*10} {'─'*10} {'─'*25}")
            for p in sorted(umbral_alto, key=lambda x: _parse_intentos(x.notas), reverse=True):
                intentos = _parse_intentos(p.notas)
                fecha_str = p.fecha_publicacion.strftime("%Y-%m-%d") if p.fecha_publicacion else "?"
                tipo_str  = p.tipo.value if p.tipo else "?"
                notas_str = (p.notas or "")[:60]
                print(f"  {p.id_externo:<25} {fecha_str:<12} {tipo_str:<10} {intentos:<10} {notas_str}")

            print(f"\n  URLs para verificar en Instagram:")
            for p in umbral_alto:
                print(f"    {p.url or f'https://www.instagram.com/p/{p.id_externo}/'}")

        # Posts sin contador: primera vez que falla, no urgente
        if sin_contador:
            print(f"\n  Posts con 0 intentos registrados (primer error o pre-contador):")
            print(f"  {'ID externo':<25} {'Fecha pub':<12} {'Tipo':<10} Notas")
            print(f"  {'─'*25} {'─'*12} {'─'*10} {'─'*30}")
            for p in sin_contador[:20]:  # mostrar máximo 20
                fecha_str = p.fecha_publicacion.strftime("%Y-%m-%d") if p.fecha_publicacion else "?"
                tipo_str  = p.tipo.value if p.tipo else "?"
                notas_str = (p.notas or "sin notas")[:50]
                print(f"  {p.id_externo:<25} {fecha_str:<12} {tipo_str:<10} {notas_str}")
            if len(sin_contador) > 20:
                print(f"  ... y {len(sin_contador)-20} más")

        print(f"\n  {'─'*70}")
        print(f"  Acción recomendada:")
        if umbral_alto:
            print(f"    - Revisar manualmente los {len(umbral_alto)} posts de arriba en Instagram")
            print(f"    - Si han sido eliminados o son colaborativos: marcarlos manualmente como sin_datos")
            print(f"    - El próximo ciclo del orquestador los marcará sin_datos automáticamente")
        if sin_contador:
            print(f"    - Los {len(sin_contador)} posts sin contador se reintentarán en el próximo ciclo")
        print()


if __name__ == "__main__":
    main()
