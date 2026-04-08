"""
scripts/fix_web_fechas.py
Corrige fecha_publicacion de artículos web obteniendo datePublished del HTML.

Por defecto procesa publicaciones cuya fecha es sospechosa (fecha compartida
por muchos artículos, síntoma de haber usado lastmod en lugar de datePublished).
Con --all procesa todas las publicaciones web sin filtrar.

Uso:
    python scripts/fix_web_fechas.py --slug roadrunningreview
    python scripts/fix_web_fechas.py --slug roadrunningreview --all
    python scripts/fix_web_fechas.py --slug roadrunningreview --dry-run
"""
import sys
import os
import re
import logging
import argparse
from datetime import datetime, timezone
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
log = logging.getLogger("fix_web_fechas")

# Umbral: una fecha es "sospechosa" si la comparten >= N publicaciones
UMBRAL_SOSPECHOSA = 3


def _fetch_date_published(url: str) -> datetime | None:
    """Descarga el HTML del artículo y extrae datePublished del JSON-LD."""
    import httpx
    try:
        with httpx.Client(timeout=5, follow_redirects=True) as client:
            resp = client.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; SocialIntelligence/1.0)"},
            )
            html = resp.text
        match = re.search(r'"datePublished"\s*:\s*"(\d{4}-\d{2}-\d{2})', html)
        if match:
            return datetime.strptime(match.group(1), "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except Exception as ex:
        log.debug(f"  {url}: error GET — {ex}")
    return None


def main():
    parser = argparse.ArgumentParser(description="Fix fechas de publicaciones web")
    parser.add_argument("--slug",    required=True, help="Slug del medio")
    parser.add_argument("--all",     action="store_true", help="Procesar todas, no solo las sospechosas")
    parser.add_argument("--dry-run", action="store_true", help="Solo diagnóstico, sin actualizar DB")
    args = parser.parse_args()

    from sqlalchemy.orm import sessionmaker
    from core.settings import get_settings
    from models.database import create_db_engine, Medio, Publicacion, CanalEnum

    settings = get_settings()
    engine = create_db_engine(settings.db_url)
    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as db:
        medio = db.query(Medio).filter(Medio.slug == args.slug).first()
        if not medio:
            log.error(f"Medio '{args.slug}' no encontrado")
            sys.exit(1)

        # Cargar todas las publicaciones web (excluyendo secundarias con sufijo _N)
        todas = (
            db.query(Publicacion)
            .filter(
                Publicacion.medio_id == medio.id,
                Publicacion.canal == CanalEnum.web,
            )
            .order_by(Publicacion.fecha_publicacion.desc())
            .all()
        )

        log.info(f"Total publicaciones web: {len(todas)}")

        if args.all:
            a_procesar = todas
            log.info("Modo --all: procesando todas las publicaciones")
        else:
            # Detectar fechas sospechosas (compartidas por >= UMBRAL_SOSPECHOSA pubs)
            fecha_counter: Counter = Counter()
            for pub in todas:
                if pub.fecha_publicacion:
                    fecha_counter[pub.fecha_publicacion.date()] += 1

            fechas_sospechosas = {
                f for f, n in fecha_counter.items() if n >= UMBRAL_SOSPECHOSA
            }
            log.info(
                f"Fechas sospechosas (>= {UMBRAL_SOSPECHOSA} pubs): "
                f"{sorted(fechas_sospechosas, reverse=True)}"
            )

            a_procesar = [
                p for p in todas
                if p.fecha_publicacion and p.fecha_publicacion.date() in fechas_sospechosas
            ]
            log.info(f"Publicaciones a revisar: {len(a_procesar)}")

        if not a_procesar:
            print("Nada que procesar.")
            return

        actualizadas = 0
        sin_fecha = 0
        iguales = 0
        errores = 0

        for pub in a_procesar:
            # Omitir publicaciones secundarias (id_externo con sufijo _marcaid)
            if pub.id_externo and "_" in pub.id_externo and not pub.id_externo.replace("_", "").isalnum():
                continue

            fecha_nueva = _fetch_date_published(pub.url)

            if fecha_nueva is None:
                log.debug(f"  {pub.url[:70]}: sin datePublished — omitido")
                sin_fecha += 1
                continue

            fecha_actual = pub.fecha_publicacion
            if fecha_actual and fecha_actual.tzinfo is None:
                fecha_actual = fecha_actual.replace(tzinfo=timezone.utc)

            if fecha_actual and fecha_actual.date() == fecha_nueva.date():
                log.debug(f"  {pub.url[:70]}: fecha ya correcta ({fecha_nueva.date()})")
                iguales += 1
                continue

            log.info(
                f"Actualizada {pub.url[:70]}: "
                f"{fecha_actual.date() if fecha_actual else 'NULL'} → {fecha_nueva.date()}"
            )

            if not args.dry_run:
                pub.fecha_publicacion = fecha_nueva
            actualizadas += 1

        if not args.dry_run:
            db.commit()

        print(
            f"\nActualizadas: {actualizadas} | "
            f"Ya correctas: {iguales} | "
            f"Sin datePublished: {sin_fecha}"
        )
        if args.dry_run:
            print("(dry-run: sin cambios en DB)")


if __name__ == "__main__":
    main()
