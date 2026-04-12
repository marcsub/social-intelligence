"""
agents/instagram_agent.py
Agente Instagram: detecta posts, reels y carruseles del perfil propio
via Instagram Graph API. Recoge métricas via /insights.
Token: System User Token (Business Portfolio) — no expira.

Métricas v21.0 soportadas (impressions y plays deprecados desde v17):
  reach, saved, shares, likes, comments  — válidos para IMAGE/VIDEO/CAROUSEL/REEL
"""
import logging
import re
import json
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone, timedelta
from typing import Optional
from sqlalchemy.orm import Session

from core.brand_id_agent import identify
from core.crypto import decrypt_token
from core.settings import get_settings
from models.database import (
    Medio, Publicacion, TokenCanal, HistorialMetricas,
    CanalEnum, TipoEnum, EstadoMetricasEnum, EstadoMarcaEnum
)

log = logging.getLogger(__name__)
settings = get_settings()

GRAPH = "https://graph.facebook.com/v21.0"


def _parse_ts(s: str) -> datetime:
    """
    Parsea ISO 8601 devuelto por la API de Instagram/Meta.
    Meta devuelve '+0000' (sin dos puntos) que fromisoformat rechaza en Python < 3.11.
    Normaliza a '+00:00' antes de parsear.
    """
    if not s:
        return datetime.now(timezone.utc)
    s = s.replace("Z", "+00:00")
    if len(s) >= 5 and s[-5] in ('+', '-') and ':' not in s[-5:]:
        s = s[:-2] + ':' + s[-2:]
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return datetime.now(timezone.utc)

INSIGHTS_MAX_AGE_DAYS = 730  # Meta no proporciona insights para posts con > 24 meses

# Métricas válidas en v21.0 para posts/carruseles/videos
MEDIA_METRICS = "reach,saved,shares,likes,comments"

# Métricas para Reels: plays deprecado desde API v22.0 — solo reach/engagement
# reach = cuentas únicas que lo vieron (métrica principal)
REEL_METRICS  = "reach,saved,shares,likes,comments"

TIPO_MAP = {
    "IMAGE":          TipoEnum.post,
    "CAROUSEL_ALBUM": TipoEnum.post,
    "VIDEO":          TipoEnum.video,
    "REELS":          TipoEnum.reel,   # Nota: la API devuelve VIDEO, no REELS (ver _get_tipo)
}


def _get_tipo(media_type: str, permalink: str) -> TipoEnum:
    """
    La Instagram Graph API devuelve media_type='VIDEO' tanto para vídeos como para Reels.
    Distinguimos Reels por el permalink ('/reel/' en la URL).
    """
    if media_type == "VIDEO" and "/reel/" in (permalink or ""):
        return TipoEnum.reel
    return TIPO_MAP.get(media_type, TipoEnum.post)


# ── Token helpers ─────────────────────────────────────────────────────────────

def _get_token(db: Session, medio_id: int, clave: str) -> Optional[str]:
    t = db.query(TokenCanal).filter(
        TokenCanal.medio_id == medio_id,
        TokenCanal.canal == "instagram",
        TokenCanal.clave == clave,
    ).first()
    return decrypt_token(t.valor_cifrado, settings.jwt_secret) if t else None



# ── Graph API helpers ─────────────────────────────────────────────────────────

class InsightsExpiredError(Exception):
    """HTTP 400 en /insights: Meta ya no proporciona datos para este post."""


# ── Helpers para contador de intentos fallidos (en campo notas) ───────────────

_INTENTOS_PREFIX = "intentos_fallidos:"

def _parse_intentos(notas) -> int:
    """Extrae el contador de intentos fallidos guardado en notas."""
    if not notas:
        return 0
    for part in str(notas).split("|"):
        if part.startswith(_INTENTOS_PREFIX):
            try:
                return int(part[len(_INTENTOS_PREFIX):])
            except ValueError:
                pass
    return 0

def _notas_con_intentos(n: int, motivo: str) -> str:
    return f"{_INTENTOS_PREFIX}{n}|{motivo}"


def _graph_get(path: str, token: str, params: dict = None) -> dict:
    """Llamada GET a Graph API. Lanza excepción si hay error."""
    p = {"access_token": token}
    if params:
        p.update(params)
    url = f"{GRAPH}{path}?{urllib.parse.urlencode(p)}"
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 400 and "/insights" in path:
            raise InsightsExpiredError(f"HTTP 400 en {path}")
        raise
    if "error" in data:
        raise RuntimeError(data["error"].get("message", str(data["error"])))
    return data


def _get_media_insights(token: str, media_id: str, media_type: str = "") -> dict:
    """
    Obtiene métricas de un post/video/reel via /insights.
    Devuelve dict con keys: reach, saved, shares, likes, comments, plays.

    Para REELS usa REEL_METRICS (incluye plays).
    Si reach=0 en Reels, usa plays como fallback de alcance.
    """
    result = {"reach": 0, "saved": 0, "shares": 0, "likes": 0, "comments": 0}
    is_reel = (media_type == "REELS" or media_type == "REEL")
    metrics = REEL_METRICS if is_reel else MEDIA_METRICS
    try:
        data = _graph_get(f"/{media_id}/insights", token, {"metric": metrics})
        for item in data.get("data", []):
            name   = item.get("name", "")
            values = item.get("values", [])
            if values and name in result:
                result[name] = int(values[-1].get("value", 0))
    except InsightsExpiredError:
        raise  # propagar al caller para manejo con contador de intentos
    except Exception as ex:
        log.warning(f"[Instagram] Insights no disponibles para {media_id}: {ex}")
    return result


def _extract_caption_parts(caption: str) -> tuple[str, str, str]:
    """Extrae texto limpio, hashtags y menciones de un caption de Instagram."""
    if not caption:
        return "", "", ""
    hashtags  = " ".join(re.findall(r"#(\w+)", caption))
    mentions  = " ".join(re.findall(r"@(\w+)", caption))
    clean     = re.sub(r"[#@]\w+", "", caption).strip()
    return clean, hashtags, mentions


# ── Detección de publicaciones nuevas ────────────────────────────────────────

def detect_new(db: Session, medio: Medio, checkpoint: Optional[datetime]) -> list[Publicacion]:
    """
    Lee el feed de Instagram del perfil propio y detecta posts nuevos.
    Pagina hacia atrás hasta encontrar contenido anterior al checkpoint.
    """
    access_token = _get_token(db, medio.id, "access_token")
    ig_account_id = _get_token(db, medio.id, "instagram_account_id")

    if not access_token or not ig_account_id:
        log.warning(f"[{medio.slug}] Faltan tokens Instagram (access_token o instagram_account_id)")
        return []

    # Normalizar checkpoint a UTC
    if checkpoint and checkpoint.tzinfo is None:
        checkpoint = checkpoint.replace(tzinfo=timezone.utc)

    fields = "id,media_type,timestamp,permalink,caption,like_count,comments_count"
    config = medio.config
    umbral = config.umbral_confianza_marca if config else 80

    nuevas = []
    next_url = None
    page = 0
    MAX_PAGES = 20  # seguridad contra loops infinitos

    while page < MAX_PAGES:
        try:
            if next_url:
                # Seguir paginación con URL completa del cursor
                with urllib.request.urlopen(next_url, timeout=15) as r:
                    resp = json.loads(r.read())
            else:
                resp = _graph_get(
                    f"/{ig_account_id}/media",
                    access_token,
                    {"fields": fields, "limit": 25},
                )
        except Exception as ex:
            log.error(f"[{medio.slug}] Error en Instagram /media: {ex}")
            break

        items = resp.get("data", [])
        if not items:
            break

        alcanzado_checkpoint = False
        for item in items:
            media_type = item.get("media_type", "")
            permalink  = item.get("permalink", "")
            if media_type not in TIPO_MAP:
                continue  # ignorar STORIES (tienen su propio agente)

            fecha = _parse_ts(item.get("timestamp", ""))

            # Parar cuando llegamos a contenido anterior al checkpoint
            if checkpoint and fecha <= checkpoint:
                alcanzado_checkpoint = True
                break

            media_id = item["id"]

            # Evitar duplicados
            existente = db.query(Publicacion).filter(
                Publicacion.medio_id == medio.id,
                Publicacion.id_externo == media_id,
            ).first()
            if existente:
                continue

            caption = item.get("caption", "") or ""
            clean_text, hashtags, mentions = _extract_caption_parts(caption)
            permalink = item.get("permalink", "")
            likes    = int(item.get("like_count", 0) or 0)
            comments = int(item.get("comments_count", 0) or 0)

            # Brand ID
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

            # Métricas iniciales via insights (Reels: permalink /reel/ → usa REEL_METRICS)
            _tipo = _get_tipo(media_type, permalink)
            _mt_for_insights = "REELS" if _tipo == TipoEnum.reel else media_type
            try:
                insights = _get_media_insights(access_token, media_id, _mt_for_insights)
            except Exception as _ie:
                log.warning(f"[{medio.slug}] Insights fallaron al detectar {media_id}: {_ie} — se guarda con métricas 0")
                insights = {"reach": 0, "saved": 0, "shares": 0, "likes": 0, "comments": 0}

            pub = Publicacion(
                medio_id=medio.id,
                marca_id=brand.marca_id,
                agencia_id=brand.agencia_id,
                id_externo=media_id,
                canal=CanalEnum.instagram_post,
                tipo=_get_tipo(media_type, permalink),
                url=permalink,
                titulo=None,  # Instagram no tiene títulos
                texto=caption or None,
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

            nuevas.append(pub)
            log.info(
                f"[{medio.slug}] Nueva pub Instagram [{media_type}]: "
                f"{caption[:50]!r} — marca: {brand.marca_nombre} ({brand.confianza}%)"
            )

        if alcanzado_checkpoint:
            break

        # Siguiente página
        next_url = resp.get("paging", {}).get("next")
        if not next_url:
            break
        page += 1

    db.commit()
    return nuevas


# ── Actualización de métricas ─────────────────────────────────────────────────

def update_metrics(db: Session, medio: Medio, publicaciones: list[Publicacion]) -> int:
    """
    Actualiza métricas de posts Instagram: reach, likes, comments, shares, saved.
    """
    if not publicaciones:
        return 0

    access_token = _get_token(db, medio.id, "access_token")
    if not access_token:
        log.warning(f"[{medio.slug}] Sin token Instagram para actualizar métricas")
        return 0

    actualizadas = 0
    for pub in publicaciones:
        if not pub.id_externo:
            continue
        try:
            media_type = "REELS" if pub.tipo == TipoEnum.reel else ""
            insights = _get_media_insights(access_token, pub.id_externo, media_type)

            # Refrescar like/comment count desde la API (más fresco que insights)
            try:
                detail = _graph_get(
                    f"/{pub.id_externo}",
                    access_token,
                    {"fields": "like_count,comments_count"},
                )
                likes    = int(detail.get("like_count", pub.likes) or pub.likes)
                comments = int(detail.get("comments_count", pub.comments) or pub.comments)
            except Exception:
                likes, comments = pub.likes, pub.comments

            db.add(HistorialMetricas(
                publicacion_id=pub.id,
                reach=insights.get("reach", pub.reach),
                likes=likes,
                shares=insights.get("shares", pub.shares),
                comments=comments,
                clicks=insights.get("saved", pub.clicks),
            ))

            pub.reach    = insights.get("reach", pub.reach)
            pub.likes    = likes
            pub.comments = comments
            pub.shares   = insights.get("shares", pub.shares)
            pub.clicks   = insights.get("saved", pub.clicks)
            pub.ultima_actualizacion = datetime.now(timezone.utc)
            pub.estado_metricas = EstadoMetricasEnum.actualizado
            actualizadas += 1

        except InsightsExpiredError:
            intentos = _parse_intentos(pub.notas) + 1
            pub.ultima_actualizacion = datetime.now(timezone.utc)
            if intentos >= 3:
                pub.estado_metricas = EstadoMetricasEnum.sin_datos
                pub.notas = _notas_con_intentos(intentos, "insights_400: 3 intentos fallidos — post colaborativo, eliminado o sin permisos")
                log.info(f"[{medio.slug}] Instagram {pub.id_externo}: sin_datos ({intentos} intentos 400)")
                actualizadas += 1
            else:
                pub.estado_metricas = EstadoMetricasEnum.error
                pub.notas = _notas_con_intentos(intentos, f"insights_400: intento {intentos}/3")
                log.warning(f"[{medio.slug}] Instagram {pub.id_externo}: 400 en insights ({intentos}/3)")

        except Exception as ex:
            log.error(f"[{medio.slug}] Error actualizando Instagram {pub.id_externo}: {ex}")
            pub.estado_metricas = EstadoMetricasEnum.error

    db.commit()
    log.info(f"[{medio.slug}] Instagram actualizado: {actualizadas}/{len(publicaciones)}")
    return actualizadas


# ── Snapshot semanal ISO ──────────────────────────────────────────────────────

def snapshot_weekly(db: Session, medio: Medio) -> int:
    """
    Snapshot semanal de métricas Instagram para todas las publicaciones de 2026+.
    Calcula reach_diff vs la semana anterior y actualiza el acumulado.
    Se ejecuta los lunes por la noche (job semanal del orquestador).
    """
    from datetime import date as _date
    from utils.semanas import get_semana_iso

    access_token = _get_token(db, medio.id, "access_token")
    if not access_token:
        log.warning(f"[{medio.slug}] Sin token Instagram para snapshot_weekly")
        return 0

    hoy = _date.today()
    semana_actual = get_semana_iso(hoy)
    inicio_2026 = datetime(2026, 1, 1, tzinfo=timezone.utc)

    pubs = (
        db.query(Publicacion)
        .filter(
            Publicacion.medio_id == medio.id,
            Publicacion.canal == CanalEnum.instagram_post,
            Publicacion.estado_metricas.notin_([
                EstadoMetricasEnum.fijo,
                EstadoMetricasEnum.sin_datos,
                EstadoMetricasEnum.error,
            ]),
            Publicacion.fecha_publicacion >= inicio_2026,
        )
        .all()
    )

    if not pubs:
        log.info(f"[{medio.slug}] snapshot_weekly Instagram: sin publicaciones 2026+")
        return 0

    actualizadas = 0
    for pub in pubs:
        if not pub.id_externo:
            continue
        try:
            media_type = "REELS" if pub.tipo == TipoEnum.reel else ""
            insights = _get_media_insights(access_token, pub.id_externo, media_type)
            try:
                detail = _graph_get(f"/{pub.id_externo}", access_token, {"fields": "like_count,comments_count"})
                likes    = int(detail.get("like_count", pub.likes) or pub.likes)
                comments = int(detail.get("comments_count", pub.comments) or pub.comments)
            except Exception:
                likes, comments = pub.likes, pub.comments

            reach_actual   = insights.get("reach", pub.reach)
            shares_actual  = insights.get("shares", pub.shares)
            clicks_actual  = insights.get("saved", pub.clicks)

            # Semana anterior
            prev = (
                db.query(HistorialMetricas)
                .filter(
                    HistorialMetricas.publicacion_id == pub.id,
                    HistorialMetricas.semana_iso.isnot(None),
                    HistorialMetricas.semana_iso < semana_actual,
                )
                .order_by(HistorialMetricas.semana_iso.desc())
                .first()
            )
            prev_reach   = prev.reach   if prev else 0
            prev_likes   = prev.likes   if prev else 0
            prev_shares  = prev.shares  if prev else 0
            prev_comments = prev.comments if prev else 0

            reach_diff   = max(0, reach_actual - prev_reach)
            likes_diff   = max(0, likes - prev_likes)
            shares_diff  = max(0, shares_actual - prev_shares)
            comments_diff = max(0, comments - prev_comments)

            # Upsert semana actual
            existing = (
                db.query(HistorialMetricas)
                .filter(HistorialMetricas.publicacion_id == pub.id, HistorialMetricas.semana_iso == semana_actual)
                .first()
            )
            if existing:
                existing.reach = reach_actual; existing.reach_diff = reach_diff
                existing.likes = likes; existing.likes_diff = likes_diff
                existing.shares = shares_actual; existing.shares_diff = shares_diff
                existing.comments = comments; existing.comments_diff = comments_diff
                existing.clicks = clicks_actual; existing.fuente = "api"
                existing.fecha_snapshot = datetime.now(timezone.utc)
            else:
                db.add(HistorialMetricas(
                    publicacion_id=pub.id, semana_iso=semana_actual,
                    reach=reach_actual, reach_diff=reach_diff,
                    likes=likes, likes_diff=likes_diff,
                    shares=shares_actual, shares_diff=shares_diff,
                    comments=comments, comments_diff=comments_diff,
                    clicks=clicks_actual, clicks_diff=0,
                    fuente="api",
                    reach_pagado=pub.reach_pagado or 0,
                    inversion_pagada=pub.inversion_pagada,
                ))

            pub.reach = reach_actual; pub.likes = likes
            pub.comments = comments; pub.shares = shares_actual; pub.clicks = clicks_actual
            pub.ultima_actualizacion = datetime.now(timezone.utc)
            pub.estado_metricas = EstadoMetricasEnum.actualizado
            actualizadas += 1

        except InsightsExpiredError:
            intentos = _parse_intentos(pub.notas) + 1
            pub.ultima_actualizacion = datetime.now(timezone.utc)
            if intentos >= 3:
                pub.estado_metricas = EstadoMetricasEnum.sin_datos
                pub.notas = _notas_con_intentos(intentos, "insights_400: 3 intentos fallidos — post colaborativo, eliminado o sin permisos")
                log.info(f"[{medio.slug}] snapshot_weekly Instagram {pub.id_externo}: sin_datos ({intentos} intentos 400)")
            else:
                pub.estado_metricas = EstadoMetricasEnum.error
                pub.notas = _notas_con_intentos(intentos, f"insights_400: intento {intentos}/3")
                log.warning(f"[{medio.slug}] snapshot_weekly Instagram {pub.id_externo}: 400 en insights ({intentos}/3)")

        except Exception as ex:
            log.error(f"[{medio.slug}] Error snapshot_weekly Instagram {pub.id_externo}: {ex}")

    db.commit()
    log.info(f"[{medio.slug}] Instagram snapshot_weekly: {actualizadas}/{len(pubs)}")
    return actualizadas
