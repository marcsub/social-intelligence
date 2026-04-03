"""
scripts/fix_stories_capturas.py
Repara las capturas de stories existentes en la base de datos:

  - Stories con > 24h de antigüedad y sin captura → marca captura_url='expired'
  - Stories recientes (< 24h) sin captura → intenta descargar la imagen
  - Stories con captura_url apuntando a un fichero que no existe → marca 'expired'

Modo --redetect:
  Consulta la API de Instagram para obtener las stories activas en este momento
  e inserta las que no existen aún en la DB, descargando su imagen.

Uso:
    python scripts/fix_stories_capturas.py [--slug roadrunningreview] [--dry-run]
    python scripts/fix_stories_capturas.py --slug roadrunningreview --redetect
    python scripts/fix_stories_capturas.py --slug roadrunningreview --redetect --dry-run
"""
import sys
import os
import argparse
import urllib.request
import urllib.parse
import json
import logging
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

GRAPH = "https://graph.facebook.com/v21.0"
STORY_WINDOW_HOURS = 24
STORY_METRICS = "reach,replies,navigation"


def _get_token(db, medio_id, clave):
    from core.crypto import decrypt_token
    from core.settings import get_settings
    from models.database import TokenCanal
    settings = get_settings()
    t = db.query(TokenCanal).filter(
        TokenCanal.medio_id == medio_id,
        TokenCanal.canal == "instagram",
        TokenCanal.clave == clave,
    ).first()
    return decrypt_token(t.valor_cifrado, settings.jwt_secret) if t else None


def _graph_get(path, token, params=None):
    p = {"access_token": token}
    if params:
        p.update(params)
    url = f"{GRAPH}{path}?{urllib.parse.urlencode(p)}"
    with urllib.request.urlopen(url, timeout=15) as r:
        data = json.loads(r.read())
    if "error" in data:
        raise RuntimeError(data["error"].get("message", str(data["error"])))
    return data


def _download_image(img_url, save_path):
    req = urllib.request.Request(
        img_url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; SocialIntelligence/1.0)"},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        with open(save_path, "wb") as f:
            f.write(r.read())


def _get_story_insights(token, story_id):
    result = {"reach": 0, "replies": 0, "navigation": 0}
    try:
        data = _graph_get(f"/{story_id}/insights", token, {"metric": STORY_METRICS})
        for item in data.get("data", []):
            name = item.get("name", "")
            values = item.get("values", [])
            if values and name in result:
                result[name] = int(values[-1].get("value", 0))
    except Exception as ex:
        log.warning(f"  Insights no disponibles para story {story_id}: {ex}")
    return result


def _prepare_image(item, medio_slug, story_id, fecha, dry_run):
    """
    Descarga la imagen de una story y devuelve la ruta local guardada.
    Retorna None si no hay URL de imagen o falla la descarga.
    """
    img_url = item.get("media_url") or item.get("thumbnail_url")
    if not img_url:
        return None

    mes_str = fecha.strftime("%Y-%m")
    save_dir = os.path.join("stories_images", medio_slug, mes_str)
    save_path = os.path.join(save_dir, f"{story_id}.jpg")

    if dry_run:
        return save_path  # en dry-run indicamos la ruta sin escribir

    try:
        os.makedirs(save_dir, exist_ok=True)
        _download_image(img_url, save_path)
        return save_path
    except Exception as ex:
        log.warning(f"  Error descargando imagen {story_id}: {ex}")
        return None


# ── Modo --redetect ───────────────────────────────────────────────────────────

def redetect_stories(db, medio, dry_run):
    """
    Consulta la API de Instagram para stories activas, inserta las nuevas
    y descarga imágenes de las que faltan.
    """
    from models.database import (
        Publicacion, HistorialMetricas,
        CanalEnum, TipoEnum, EstadoMetricasEnum, EstadoMarcaEnum
    )
    from core.brand_id_agent import identify

    access_token  = _get_token(db, medio.id, "access_token")
    ig_account_id = _get_token(db, medio.id, "instagram_account_id")

    if not access_token or not ig_account_id:
        print("  ERROR: faltan tokens Instagram (access_token / instagram_account_id)")
        return

    # 1. Obtener stories activas de la API
    fields = "id,media_type,media_url,thumbnail_url,timestamp,permalink,caption"
    try:
        resp = _graph_get(f"/{ig_account_id}/stories", access_token, {"fields": fields})
    except Exception as ex:
        print(f"  ERROR llamando a la API: {ex}")
        return

    api_stories = resp.get("data", [])
    print(f"  Stories activas en API: {len(api_stories)}")

    if not api_stories:
        print("  Sin stories activas en este momento.")
        return

    nuevas = 0
    imagenes_descargadas = 0

    for item in api_stories:
        story_id = item.get("id")
        if not story_id:
            continue

        # Parsear fecha
        fecha_str = item.get("timestamp", "")
        try:
            fecha = datetime.fromisoformat(fecha_str.replace("Z", "+00:00"))
        except Exception:
            fecha = datetime.now(timezone.utc)

        permalink = item.get("permalink") or (
            f"https://www.instagram.com/stories/{ig_account_id}/{story_id}/"
        )
        caption = item.get("caption", "") or ""

        # 2a. Verificar si ya existe en publicaciones
        existente = db.query(Publicacion).filter(
            Publicacion.medio_id == medio.id,
            Publicacion.id_externo == story_id,
        ).first()

        if existente:
            # 2c. Existe pero sin imagen: descargar y actualizar
            if not existente.captura_url or existente.captura_url == "expired":
                save_path = _prepare_image(item, medio.slug, story_id, fecha, dry_run)
                if save_path:
                    if not dry_run:
                        existente.captura_url = save_path
                    print(f"  Story {story_id}: ya existía, imagen actualizada → {save_path}")
                    imagenes_descargadas += 1
                else:
                    print(f"  Story {story_id}: ya existía, sin imagen disponible")
            else:
                print(f"  Story {story_id}: ya existía con captura OK ({existente.captura_url})")
            continue

        # 2b. No existe: insertar como publicación nueva
        print(f"  Story {story_id}: nueva (publicada {fecha.strftime('%H:%M UTC')})")

        # Brand ID usando caption o permalink
        brand = identify(
            medio_id=medio.id,
            db=db,
            url=permalink,
            caption=caption if caption else "",
        )

        # Métricas — ventana 24h CRÍTICA
        insights = _get_story_insights(access_token, story_id)

        estado_marca = (
            EstadoMarcaEnum.estimated
            if brand.marca_id and brand.confianza >= 80
            else EstadoMarcaEnum.to_review
        )

        # Descargar imagen
        save_path = _prepare_image(item, medio.slug, story_id, fecha, dry_run)
        if save_path:
            imagenes_descargadas += 1
            print(f"    imagen → {save_path}")
        else:
            print(f"    sin imagen disponible")

        if not dry_run:
            pub = Publicacion(
                medio_id=medio.id,
                marca_id=brand.marca_id,
                agencia_id=brand.agencia_id,
                id_externo=story_id,
                canal=CanalEnum.instagram_story,
                tipo=TipoEnum.story,
                url=permalink,
                titulo=None,
                fecha_publicacion=fecha,
                reach=insights.get("reach", 0),
                likes=0,
                comments=insights.get("replies", 0),
                shares=0,
                clicks=insights.get("navigation", 0),
                estado_metricas=EstadoMetricasEnum.fijo,
                confianza_marca=brand.confianza if brand.confianza > 0 else None,
                estado_marca=estado_marca,
                captura_url=save_path,
                notas=f"navigation={insights['navigation']}",
            )
            db.add(pub)
            db.flush()

            db.add(HistorialMetricas(
                publicacion_id=pub.id,
                reach=pub.reach, likes=0,
                shares=0, comments=pub.comments, clicks=pub.clicks,
            ))

        print(
            f"    reach={insights['reach']} replies={insights['replies']} "
            f"marca={brand.marca_nombre or '?'} confianza={brand.confianza}%"
        )
        nuevas += 1

    if not dry_run:
        db.commit()

    print(f"\n  Resumen {medio.slug}:")
    print(f"    Stories activas en API:  {len(api_stories)}")
    print(f"    Nuevas insertadas:       {nuevas}")
    print(f"    Imágenes descargadas:    {imagenes_descargadas}")
    if dry_run:
        print("  (dry-run: ningún cambio guardado)")


# ── Modo normal (reparar capturas existentes) ─────────────────────────────────

def fix_capturas(db, medio, dry_run):
    """
    Revisa las stories ya en la DB y repara capturas rotas o expiradas.
    """
    from models.database import Publicacion, CanalEnum

    stories = (
        db.query(Publicacion)
        .filter(
            Publicacion.medio_id == medio.id,
            Publicacion.canal == CanalEnum.instagram_story,
        )
        .order_by(Publicacion.fecha_publicacion.desc())
        .all()
    )

    if not stories:
        print("  Sin stories en la DB.")
        return

    access_token = _get_token(db, medio.id, "access_token")

    now = datetime.now(timezone.utc)
    expired_count = 0
    downloaded = 0
    skipped = 0
    already_ok = 0

    for pub in stories:
        story_id = pub.id_externo
        fecha = pub.fecha_publicacion
        if fecha.tzinfo is None:
            fecha = fecha.replace(tzinfo=timezone.utc)
        age_hours = (now - fecha).total_seconds() / 3600

        # Captura ya tiene fichero válido en disco
        if pub.captura_url and pub.captura_url != "expired":
            if os.path.exists(pub.captura_url):
                already_ok += 1
                log.debug(f"  [{story_id}] captura OK: {pub.captura_url}")
                continue
            else:
                log.info(f"  [{story_id}] fichero no encontrado: {pub.captura_url} → marcando expired")

        # Story expirada (>24h): marcar como expired sin intentar descarga
        if age_hours > STORY_WINDOW_HOURS:
            print(f"  [{story_id}] {age_hours:.0f}h → EXPIRED")
            if not dry_run:
                pub.captura_url = "expired"
            expired_count += 1
            continue

        # Story reciente: intentar descargar desde la API
        if not access_token:
            print(f"  [{story_id}] {age_hours:.1f}h — sin token, saltando")
            skipped += 1
            continue

        print(f"  [{story_id}] {age_hours:.1f}h → intentando descarga...")
        try:
            story_data = _graph_get(
                f"/{story_id}",
                access_token,
                {"fields": "id,media_url,thumbnail_url,timestamp"},
            )
            img_url = story_data.get("media_url") or story_data.get("thumbnail_url")
            if not img_url:
                print(f"    → sin media_url ni thumbnail_url (probablemente ya expiró en Meta)")
                if not dry_run:
                    pub.captura_url = "expired"
                expired_count += 1
                continue

            mes_str = fecha.strftime("%Y-%m")
            save_dir = os.path.join("stories_images", medio.slug, mes_str)
            save_path = os.path.join(save_dir, f"{story_id}.jpg")

            if not dry_run:
                os.makedirs(save_dir, exist_ok=True)
                _download_image(img_url, save_path)
                pub.captura_url = save_path
            print(f"    → guardada en {save_path}")
            downloaded += 1

        except Exception as ex:
            print(f"    → ERROR: {ex}")
            if not dry_run:
                pub.captura_url = "expired"
            expired_count += 1

    if not dry_run:
        db.commit()

    print(f"\n  Resumen {medio.slug}:")
    print(f"    Ya OK:            {already_ok}")
    print(f"    Descargadas:      {downloaded}")
    print(f"    Marcadas expired: {expired_count}")
    print(f"    Saltadas:         {skipped}")
    if dry_run:
        print("  (dry-run: ningún cambio guardado)")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug",     default=None, help="Slug del medio (omitir = todos)")
    parser.add_argument("--dry-run",  action="store_true", help="Muestra qué haría sin guardar")
    parser.add_argument("--redetect", action="store_true",
                        help="Consulta la API y añade stories activas no registradas en la DB")
    args = parser.parse_args()

    from sqlalchemy.orm import sessionmaker
    from core.settings import get_settings
    from models.database import create_db_engine, init_db, Medio

    settings = get_settings()
    engine = create_db_engine(settings.db_url)
    init_db(engine)
    Session = sessionmaker(bind=engine)

    with Session() as db:
        q = db.query(Medio).filter(Medio.activo == True)
        if args.slug:
            q = q.filter(Medio.slug == args.slug)
        medios = q.all()

        if not medios:
            print("No se encontraron medios.")
            sys.exit(1)

        for medio in medios:
            print(f"\n{'─'*60}")
            print(f"  Medio: {medio.nombre} ({medio.slug})")
            print(f"{'─'*60}")

            if args.redetect:
                redetect_stories(db, medio, args.dry_run)
            else:
                fix_capturas(db, medio, args.dry_run)


if __name__ == "__main__":
    main()
