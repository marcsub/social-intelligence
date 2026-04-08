"""
scripts/fix_story_images.py
Repara stories de tipo VIDEO cuya captura_url apunta a un fichero MP4
en lugar de una imagen JPEG (thumbnail).

Detecta el tipo de fichero por los primeros bytes (magic bytes) y si es
un vídeo MP4 intenta descargar el thumbnail_url desde la API de Instagram.

Uso:
    python scripts/fix_story_images.py --slug roadrunningreview
    python scripts/fix_story_images.py --slug roadrunningreview --dry-run
"""
import sys
import os
import logging
import argparse
import urllib.request
import urllib.parse
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
log = logging.getLogger("fix_story_images")

GRAPH = "https://graph.facebook.com/v21.0"

# Magic bytes para detectar tipo de fichero
_MP4_MAGIC = [
    b"ftyp",      # ISO Base Media (offset 4)
    b"\x00\x00\x00\x18ftyp",
    b"\x00\x00\x00\x1cftyp",
    b"\x00\x00\x00 ftyp",
]
_JPEG_MAGIC = b"\xff\xd8\xff"
_PNG_MAGIC  = b"\x89PNG"


def _is_video_file(path: str) -> bool:
    """Devuelve True si el fichero parece un vídeo MP4 (por magic bytes)."""
    try:
        with open(path, "rb") as f:
            header = f.read(12)
        # JPEG / PNG → es imagen
        if header[:3] == _JPEG_MAGIC or header[:4] == _PNG_MAGIC:
            return False
        # ftyp en offset 4 → MP4/MOV
        if len(header) >= 8 and header[4:8] == b"ftyp":
            return True
        # Otros casos que no son imagen conocida → tratar como vídeo
        if header[:3] != _JPEG_MAGIC and header[:4] != _PNG_MAGIC:
            return True
        return False
    except Exception:
        return False


def _graph_get(path: str, token: str, params: dict = None) -> dict:
    p = {"access_token": token}
    if params:
        p.update(params)
    url = f"{GRAPH}{path}?{urllib.parse.urlencode(p)}"
    with urllib.request.urlopen(url, timeout=15) as r:
        data = json.loads(r.read())
    if "error" in data:
        raise RuntimeError(data["error"].get("message", str(data["error"])))
    return data


def _download(url: str, save_path: str) -> None:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; SocialIntelligence/1.0)"},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        with open(save_path, "wb") as f:
            f.write(r.read())


def main():
    parser = argparse.ArgumentParser(description="Fix story images: reemplaza MP4 por thumbnail")
    parser.add_argument("--slug",    required=True, help="Slug del medio")
    parser.add_argument("--dry-run", action="store_true", help="Solo diagnóstico, sin modificar")
    args = parser.parse_args()

    from sqlalchemy.orm import sessionmaker
    from core.settings import get_settings
    from core.crypto import decrypt_token
    from models.database import create_db_engine, Medio, Publicacion, TokenCanal, CanalEnum

    settings = get_settings()
    engine = create_db_engine(settings.db_url)
    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as db:
        medio = db.query(Medio).filter(Medio.slug == args.slug).first()
        if not medio:
            log.error(f"Medio '{args.slug}' no encontrado")
            sys.exit(1)

        # Token de Instagram
        t = db.query(TokenCanal).filter(
            TokenCanal.medio_id == medio.id,
            TokenCanal.canal == "instagram",
            TokenCanal.clave == "access_token",
        ).first()
        access_token = decrypt_token(t.valor_cifrado, settings.jwt_secret) if t else None
        if not access_token:
            log.error("Sin access_token de Instagram — necesario para obtener thumbnail_url")
            sys.exit(1)

        # Stories con captura en disco
        stories = (
            db.query(Publicacion)
            .filter(
                Publicacion.medio_id == medio.id,
                Publicacion.canal == CanalEnum.instagram_story,
                Publicacion.captura_url.isnot(None),
                Publicacion.captura_url != "expired",
            )
            .order_by(Publicacion.fecha_publicacion.desc())
            .all()
        )

        log.info(f"Stories con captura_url: {len(stories)}")

        revisadas = 0
        reemplazadas = 0
        errores = 0

        for pub in stories:
            path = pub.captura_url
            story_id = pub.id_externo

            if not os.path.exists(path):
                log.debug(f"Story {story_id}: fichero no encontrado en disco ({path}) — omitido")
                continue

            revisadas += 1

            if not _is_video_file(path):
                log.debug(f"Story {story_id}: es imagen, OK")
                continue

            log.info(f"Story {story_id}: fichero es vídeo MP4 — reemplazando por thumbnail...")

            if args.dry_run:
                log.info(f"Story {story_id}: [dry-run] se reemplazaría {path}")
                reemplazadas += 1
                continue

            # Obtener thumbnail_url desde la API
            try:
                data = _graph_get(
                    f"/{story_id}",
                    access_token,
                    {"fields": "id,thumbnail_url,media_url,media_type"},
                )
                thumbnail_url = data.get("thumbnail_url")
                if not thumbnail_url:
                    log.warning(
                        f"Story {story_id}: sin thumbnail_url en API "
                        f"(media_type={data.get('media_type')}) — omitido"
                    )
                    errores += 1
                    continue

                _download(thumbnail_url, path)
                log.info(f"Story {story_id}: reemplazada imagen de vídeo por thumbnail → {path}")
                reemplazadas += 1

            except Exception as ex:
                log.error(f"Story {story_id}: error al reemplazar — {ex}")
                errores += 1

        if not args.dry_run:
            db.commit()

        print(
            f"\nRevisadas: {revisadas} | "
            f"Reemplazadas: {reemplazadas} | "
            f"Errores: {errores}"
        )
        if args.dry_run:
            print("(dry-run: sin cambios en disco ni en DB)")


if __name__ == "__main__":
    main()
