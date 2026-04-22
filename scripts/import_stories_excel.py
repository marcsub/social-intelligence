"""
scripts/import_stories_excel.py
Importa stories capturadas manualmente desde un Excel + imágenes JPG.

Uso:
    python scripts/import_stories_excel.py --slug trailrunningreview \
        --excel importImage/trail/import.xlsx \
        --images-dir importImage/trail

Excel esperado (columnas A..E):
    ID | Link | Fecha | Reach | Descripcion del texto

- La imagen {ID}.jpg debe existir en --images-dir.
- Se mueve a stories_images/{slug}/{YYYY-MM}/{ID}.jpg (ruta que luego se sube por FTP).
- Se crea Publicacion con canal=instagram_story, tipo=story, estado_metricas=fijo.
- Brand ID: se ejecuta sobre la descripción; si medio no tiene marcas en catálogo → to_review.

Flags:
    --dry-run        No escribe en BD ni mueve ficheros.
    --no-move        No mueve las imágenes, solo inserta metadatos (copia). Útil para rerun.
    --limit N        Solo procesa las N primeras filas.
"""
import argparse
import logging
import os
import shutil
import sys
from datetime import datetime, timezone
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import openpyxl  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from core.brand_id_agent import identify  # noqa: E402
from core.settings import get_settings  # noqa: E402
from models.database import (  # noqa: E402
    create_db_engine, Medio, Publicacion,
    CanalEnum, TipoEnum, EstadoMetricasEnum, EstadoMarcaEnum,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("import_stories")


def _parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True, help="Slug del medio (ej. trailrunningreview)")
    ap.add_argument("--excel", required=True, help="Ruta al fichero .xlsx con los metadatos")
    ap.add_argument("--images-dir", required=True, help="Directorio con los JPG origen")
    ap.add_argument("--stories-root", default="stories_images",
                    help="Carpeta raíz destino (por defecto: stories_images)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-move", action="store_true",
                    help="Copia en vez de mover el JPG (no borra el origen)")
    ap.add_argument("--limit", type=int, default=0, help="Procesar solo las N primeras filas")
    ap.add_argument("--fecha-hasta", default=None,
                    help="Solo importa filas con fecha <= YYYY-MM-DD (evita solapar con capturas API)")
    return ap.parse_args()


def _read_excel(path: str) -> list[dict]:
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.active
    rows = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row or row[0] is None:
            continue
        id_, link, fecha, reach, texto = (list(row) + [None] * 5)[:5]
        rows.append({
            "id": str(int(id_)) if isinstance(id_, (int, float)) else str(id_).strip(),
            "link": (link or "").strip() if isinstance(link, str) else None,
            "fecha": fecha,
            "reach": int(reach) if isinstance(reach, (int, float)) else 0,
            "texto": (texto or "").strip() if texto else "",
        })
    return rows


def _ensure_fecha(fecha) -> datetime:
    """Normaliza la fecha a datetime naive (sin tz) para coincidir con la BD."""
    if isinstance(fecha, datetime):
        return fecha.replace(tzinfo=None) if fecha.tzinfo else fecha
    # Fallback improbable
    return datetime.utcnow()


def _destination_path(stories_root: str, slug: str, fecha: datetime, story_id: str) -> str:
    mes = fecha.strftime("%Y-%m")
    return os.path.join(stories_root, slug, mes, f"{story_id}.jpg")


def _place_image(src: str, dst: str, move: bool, dry_run: bool) -> None:
    if dry_run:
        return
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.exists(dst):
        # Ya está colocada (rerun idempotente)
        if os.path.abspath(src) != os.path.abspath(dst) and move and os.path.exists(src):
            try:
                os.remove(src)
            except OSError:
                pass
        return
    if move:
        shutil.move(src, dst)
    else:
        shutil.copy2(src, dst)


def run(args):
    settings = get_settings()
    engine = create_db_engine(settings.db_url)

    excel_path = os.path.abspath(args.excel)
    images_dir = os.path.abspath(args.images_dir)
    stories_root = os.path.abspath(args.stories_root)

    if not os.path.exists(excel_path):
        log.error(f"No existe el Excel: {excel_path}")
        sys.exit(1)
    if not os.path.isdir(images_dir):
        log.error(f"No existe el directorio de imágenes: {images_dir}")
        sys.exit(1)

    rows = _read_excel(excel_path)
    if args.fecha_hasta:
        limite = datetime.strptime(args.fecha_hasta, "%Y-%m-%d")
        # Incluir todo el día: <= 23:59:59
        limite = limite.replace(hour=23, minute=59, second=59)
        antes = len(rows)
        rows = [r for r in rows if _ensure_fecha(r["fecha"]) <= limite]
        log.info(f"Filtrado por fecha_hasta={args.fecha_hasta}: {antes} → {len(rows)}")
    if args.limit:
        rows = rows[: args.limit]
    log.info(f"Filas a procesar: {len(rows)}")

    with Session(engine) as db:
        medio = db.query(Medio).filter(Medio.slug == args.slug).first()
        if not medio:
            log.error(f"Medio no encontrado: slug={args.slug}")
            sys.exit(1)
        log.info(f"Medio: {medio.nombre} (id={medio.id})")

        insertadas = 0
        actualizadas = 0
        saltadas_sin_imagen = 0
        errores = 0

        for r in rows:
            story_id = r["id"]
            src_img = os.path.join(images_dir, f"{story_id}.jpg")
            fecha = _ensure_fecha(r["fecha"])
            dst_img = _destination_path(stories_root, args.slug, fecha, story_id)
            captura_url_rel = os.path.relpath(dst_img, os.getcwd()).replace("\\", "/")

            if not os.path.exists(src_img) and not os.path.exists(dst_img):
                log.warning(f"[{story_id}] Sin imagen origen ni destino → saltada")
                saltadas_sin_imagen += 1
                continue

            try:
                _place_image(src_img, dst_img, move=not args.no_move, dry_run=args.dry_run)
            except Exception as ex:
                log.error(f"[{story_id}] Error colocando imagen: {ex}")
                errores += 1
                continue

            existente = db.query(Publicacion).filter(
                Publicacion.medio_id == medio.id,
                Publicacion.id_externo == story_id,
                Publicacion.canal == CanalEnum.instagram_story,
            ).first()

            brand = identify(
                medio_id=medio.id, db=db,
                caption=r["texto"] or "",
                description=r["texto"] or "",
                url=r["link"] or "",
            )
            umbral = medio.config.umbral_confianza_marca if medio.config else 80
            estado_marca = (
                EstadoMarcaEnum.estimated if brand.marca_id and brand.confianza >= umbral
                else EstadoMarcaEnum.to_review
            )

            url = r["link"] or f"manual://{args.slug}/story/{story_id}"

            if existente:
                # Actualización idempotente (no pisa marca validada manualmente)
                existente.reach = r["reach"] or existente.reach
                existente.texto = r["texto"] or existente.texto
                existente.captura_url = captura_url_rel
                existente.fecha_publicacion = fecha
                if existente.estado_marca != EstadoMarcaEnum.ok:
                    existente.marca_id = brand.marca_id
                    existente.agencia_id = brand.agencia_id
                    existente.confianza_marca = brand.confianza if brand.confianza > 0 else None
                    existente.estado_marca = estado_marca
                existente.estado_metricas = EstadoMetricasEnum.fijo
                existente.ultima_actualizacion = datetime.utcnow()
                actualizadas += 1
            else:
                pub = Publicacion(
                    medio_id=medio.id,
                    marca_id=brand.marca_id,
                    agencia_id=brand.agencia_id,
                    id_externo=story_id,
                    canal=CanalEnum.instagram_story,
                    tipo=TipoEnum.story,
                    url=url,
                    titulo=None,
                    texto=r["texto"] or None,
                    fecha_publicacion=fecha,
                    reach=r["reach"] or 0,
                    likes=0, comments=0, shares=0, clicks=0,
                    estado_metricas=EstadoMetricasEnum.fijo,
                    confianza_marca=brand.confianza if brand.confianza > 0 else None,
                    estado_marca=estado_marca,
                    captura_url=captura_url_rel,
                    notas="import_manual_excel",
                    ultima_actualizacion=datetime.utcnow(),
                )
                db.add(pub)
                insertadas += 1

            log.info(
                f"[{story_id}] {fecha.strftime('%Y-%m-%d')} reach={r['reach']} "
                f"marca={brand.marca_nombre or '?'} conf={brand.confianza} "
                f"→ {'insert' if not existente else 'update'}"
            )

        if args.dry_run:
            log.info("DRY RUN — no se guardan cambios")
            db.rollback()
        else:
            db.commit()

    log.info(
        f"RESUMEN: insertadas={insertadas} actualizadas={actualizadas} "
        f"sin_imagen={saltadas_sin_imagen} errores={errores}"
    )
    log.info(f"Directorio destino de imágenes: {os.path.join(stories_root, args.slug)}")


if __name__ == "__main__":
    run(_parse_args())
