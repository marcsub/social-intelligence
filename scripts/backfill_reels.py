"""
scripts/backfill_reels.py
Backfill de Reels de Instagram publicados desde 2026-01-01.

Pagina por toda la API /{ig_account_id}/media, filtra REELS con fecha >= 2026-01-01,
inserta en DB si no existe, obtiene métricas con plays+reach.

Uso:
    python scripts/backfill_reels.py --slug roadrunningreview
    python scripts/backfill_reels.py --slug roadrunningreview --dry-run
    python scripts/backfill_reels.py --slug roadrunningreview --anio 2025
"""
import sys
import os
import re
import json
import urllib.request
import urllib.parse
import logging
import argparse
from datetime import datetime, timezone, date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
log = logging.getLogger("backfill_reels")

GRAPH = "https://graph.facebook.com/v21.0"
REEL_METRICS = "plays,reach,saved,shares,likes,comments"


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


def _get_reel_insights(token, media_id):
    result = {"reach": 0, "saved": 0, "shares": 0, "likes": 0, "comments": 0, "plays": 0}
    try:
        data = _graph_get(f"/{media_id}/insights", token, {"metric": REEL_METRICS})
        for item in data.get("data", []):
            name   = item.get("name", "")
            values = item.get("values", [])
            if values and name in result:
                result[name] = int(values[-1].get("value", 0))
        if result["reach"] == 0 and result["plays"] > 0:
            result["reach"] = result["plays"]
    except Exception as ex:
        log.warning(f"Insights no disponibles para reel {media_id}: {ex}")
    return result


def _extract_caption_parts(caption):
    if not caption:
        return "", "", ""
    hashtags  = " ".join(re.findall(r"#(\w+)", caption))
    mentions  = " ".join(re.findall(r"@(\w+)", caption))
    clean     = re.sub(r"[#@]\w+", "", caption).strip()
    return clean, hashtags, mentions


def main():
    parser = argparse.ArgumentParser(description="Backfill de Reels de Instagram")
    parser.add_argument("--slug",    required=True, help="Slug del medio")
    parser.add_argument("--anio",    type=int, default=2026, help="Año desde el que backfillear (default: 2026)")
    parser.add_argument("--dry-run", action="store_true", help="Solo diagnóstico, sin insertar")
    args = parser.parse_args()

    from sqlalchemy.orm import sessionmaker
    from core.settings import get_settings
    from core.brand_id_agent import identify
    from core.crypto import encrypt_token
    from models.database import (
        create_db_engine, Medio, Publicacion, HistorialMetricas,
        CanalEnum, TipoEnum, EstadoMetricasEnum, EstadoMarcaEnum
    )

    settings = get_settings()
    engine = create_db_engine(settings.db_url)
    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as db:
        medio = db.query(Medio).filter(Medio.slug == args.slug).first()
        if not medio:
            log.error(f"Medio '{args.slug}' no encontrado"); sys.exit(1)

        access_token  = _get_token(db, medio.id, "access_token")
        ig_account_id = _get_token(db, medio.id, "instagram_account_id")

        if not access_token or not ig_account_id:
            log.error("Faltan tokens Instagram (access_token o instagram_account_id)"); sys.exit(1)

        fecha_inicio = datetime(args.anio, 1, 1, tzinfo=timezone.utc)
        log.info(f"=== Backfill Reels — {args.slug} desde {args.anio}-01-01 ===")

        # Contar tipos disponibles en la cuenta
        log.info("Contando tipos de media en la cuenta...")
        tipos_conteo = {}
        next_url = None
        page_count = 0
        MAX_PAGES_SCAN = 10

        while page_count < MAX_PAGES_SCAN:
            try:
                if next_url:
                    with urllib.request.urlopen(next_url, timeout=15) as r:
                        resp = json.loads(r.read())
                else:
                    resp = _graph_get(
                        f"/{ig_account_id}/media",
                        access_token,
                        {"fields": "id,media_type,timestamp", "limit": 50},
                    )
            except Exception as ex:
                log.error(f"Error al escanear media: {ex}"); break

            for item in resp.get("data", []):
                t = item.get("media_type", "UNKNOWN")
                tipos_conteo[t] = tipos_conteo.get(t, 0) + 1

            next_url = resp.get("paging", {}).get("next")
            if not next_url:
                break
            page_count += 1

        log.info(f"Distribución de media types (primeras {page_count+1} páginas de 50): {tipos_conteo}")
        if tipos_conteo.get("REELS", 0) == 0:
            log.warning("No se encontraron REELS en las primeras páginas. Puede ser problema de permisos o que no hay Reels.")

        # Paginar todo el feed para buscar REELS de 2026+
        campos = "id,media_type,timestamp,permalink,caption,like_count,comments_count"
        config = medio.config
        umbral = config.umbral_confianza_marca if config else 80

        todos_reels = []
        next_url = None
        page = 0
        MAX_PAGES = 50
        alcanzado_inicio = False

        log.info(f"Paginando feed Instagram en busca de REELS desde {args.anio}-01-01...")

        while page < MAX_PAGES and not alcanzado_inicio:
            try:
                if next_url:
                    with urllib.request.urlopen(next_url, timeout=15) as r:
                        resp = json.loads(r.read())
                else:
                    resp = _graph_get(
                        f"/{ig_account_id}/media",
                        access_token,
                        {"fields": campos, "limit": 25},
                    )
            except Exception as ex:
                log.error(f"Error paginando media: {ex}"); break

            items = resp.get("data", [])
            if not items:
                break

            for item in items:
                fecha_str = item.get("timestamp", "")
                try:
                    fecha = datetime.fromisoformat(fecha_str.replace("Z", "+00:00"))
                except Exception:
                    fecha = datetime.now(timezone.utc)

                if fecha < fecha_inicio:
                    alcanzado_inicio = True
                    break

                # La API devuelve media_type='VIDEO' para Reels; detectamos por permalink
                is_reel = (
                    item.get("media_type") == "REELS"
                    or (item.get("media_type") == "VIDEO" and "/reel/" in item.get("permalink", ""))
                )
                if is_reel:
                    todos_reels.append((item, fecha))

            next_url = resp.get("paging", {}).get("next")
            if not next_url:
                break
            page += 1

        log.info(f"Reels encontrados desde {args.anio}-01-01: {len(todos_reels)}")

        if args.dry_run:
            log.info("Dry-run: sin cambios")
            for item, fecha in todos_reels:
                log.info(f"  REEL {item['id']} — {fecha.date()} — {item.get('permalink','')}")
            return

        # Insertar Reels en DB
        insertados = 0
        ya_existian = 0
        errores = 0

        for item, fecha in todos_reels:
            media_id  = item["id"]
            permalink = item.get("permalink", "")
            caption   = item.get("caption", "") or ""
            likes     = int(item.get("like_count", 0) or 0)
            comments  = int(item.get("comments_count", 0) or 0)

            existente = db.query(Publicacion).filter(
                Publicacion.medio_id == medio.id,
                Publicacion.id_externo == media_id,
            ).first()

            if existente:
                ya_existian += 1
                log.debug(f"Reel {media_id} ya existe en DB (id={existente.id})")
                continue

            clean_text, hashtags, mentions = _extract_caption_parts(caption)
            brand = identify(
                medio_id=medio.id,
                db=db,
                caption=clean_text,
                hashtags=hashtags,
                mentions=mentions,
                url=permalink,
            )

            estado = (
                EstadoMetricasEnum.pendiente
                if brand.confianza >= umbral
                else EstadoMetricasEnum.revisar
            )
            estado_marca = (
                EstadoMarcaEnum.estimated
                if brand.marca_id and brand.confianza >= 80
                else EstadoMarcaEnum.to_review
            )

            try:
                insights = _get_reel_insights(access_token, media_id)
            except Exception as ex:
                log.error(f"Error insights para reel {media_id}: {ex}")
                insights = {"reach": 0, "saved": 0, "shares": 0, "likes": 0, "comments": 0, "plays": 0}
                errores += 1

            pub = Publicacion(
                medio_id=medio.id,
                marca_id=brand.marca_id,
                agencia_id=brand.agencia_id,
                id_externo=media_id,
                canal=CanalEnum.instagram_post,
                tipo=TipoEnum.reel,
                url=permalink,
                titulo=None,
                fecha_publicacion=fecha,
                reach=insights.get("reach", 0),
                likes=likes,
                comments=comments,
                shares=insights.get("shares", 0),
                clicks=insights.get("saved", 0),
                estado_metricas=estado,
                confianza_marca=brand.confianza if brand.confianza > 0 else None,
                estado_marca=estado_marca,
                notas=brand.razonamiento if estado == EstadoMetricasEnum.revisar else None,
            )
            db.add(pub)
            db.flush()

            db.add(HistorialMetricas(
                publicacion_id=pub.id,
                reach=pub.reach, likes=pub.likes,
                shares=pub.shares, comments=pub.comments, clicks=pub.clicks,
            ))

            insertados += 1
            log.info(
                f"  Reel insertado: {media_id} | fecha={fecha.date()} "
                f"| reach={pub.reach} | marca={brand.marca_nombre} ({brand.confianza}%)"
            )

        db.commit()

        log.info(
            f"\n=== Backfill Reels completado ===\n"
            f"  Reels encontrados: {len(todos_reels)}\n"
            f"  Insertados:        {insertados}\n"
            f"  Ya existían:       {ya_existian}\n"
            f"  Errores insights:  {errores}"
        )


if __name__ == "__main__":
    main()
