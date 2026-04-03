"""
agents/threads_agent.py
Agente Threads: detecta posts del perfil propio via Threads Graph API.
Token: Long-Lived User Token (60 días — renovar mensualmente).

Métricas disponibles via /insights:
  views    → reach
  likes    → likes
  replies  → comments
  reposts  → shares (parcial)
  quotes   → shares (parcial)
"""
import logging
import re
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone
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

BASE_URL = "https://graph.threads.net/v1.0"

# Métricas disponibles en /insights para posts de Threads
POST_METRICS = "views,likes,replies,reposts,quotes"

MEDIA_TYPE_MAP = {
    "TEXT_POST":      TipoEnum.post,
    "IMAGE":          TipoEnum.post,
    "VIDEO":          TipoEnum.video,
    "CAROUSEL_ALBUM": TipoEnum.post,
    "REPOST_FACADE":  TipoEnum.post,
}


# ── Token helpers ─────────────────────────────────────────────────────────────

def _get_token(db: Session, medio_id: int, clave: str) -> Optional[str]:
    t = db.query(TokenCanal).filter(
        TokenCanal.medio_id == medio_id,
        TokenCanal.canal == "threads",
        TokenCanal.clave == clave,
    ).first()
    return decrypt_token(t.valor_cifrado, settings.jwt_secret) if t else None


# ── API helpers ───────────────────────────────────────────────────────────────

def _api_get(path: str, token: str, params: dict = None) -> dict:
    """Llamada GET a Threads Graph API. Lanza excepción si hay error."""
    p = {"access_token": token}
    if params:
        p.update(params)
    url = f"{BASE_URL}{path}?{urllib.parse.urlencode(p)}"
    with urllib.request.urlopen(url, timeout=15) as r:
        data = json.loads(r.read())
    if "error" in data:
        raise RuntimeError(data["error"].get("message", str(data["error"])))
    return data


def _get_post_insights(token: str, post_id: str) -> dict:
    """
    Obtiene métricas de un post via /insights.
    Devuelve dict con keys: reach, likes, comments, shares.
    shares = reposts + quotes
    """
    result = {"reach": 0, "likes": 0, "comments": 0, "shares": 0}
    try:
        data = _api_get(f"/{post_id}/insights", token, {"metric": POST_METRICS})
        raw = {}
        for item in data.get("data", []):
            name  = item.get("name", "")
            value = item.get("values", [{}])[-1].get("value", 0) if item.get("values") else item.get("total_value", {}).get("value", 0)
            raw[name] = int(value or 0)
        result["reach"]    = raw.get("views", 0)
        result["likes"]    = raw.get("likes", 0)
        result["comments"] = raw.get("replies", 0)
        result["shares"]   = raw.get("reposts", 0) + raw.get("quotes", 0)
    except Exception as ex:
        log.warning(f"[Threads] Insights no disponibles para {post_id}: {ex}")
    return result


def _extract_text_parts(text: str) -> tuple[str, str, str]:
    """Extrae texto limpio, hashtags y menciones de un post de Threads."""
    if not text:
        return "", "", ""
    hashtags = " ".join(re.findall(r"#(\w+)", text))
    mentions = " ".join(re.findall(r"@(\w+)", text))
    clean    = re.sub(r"[#@]\w+", "", text).strip()
    return clean, hashtags, mentions


# ── Detección de publicaciones nuevas ────────────────────────────────────────

def detect_new(db: Session, medio: Medio, checkpoint: Optional[datetime]) -> list[Publicacion]:
    """
    Lee el feed de Threads del perfil y detecta posts nuevos.
    Pagina hasta encontrar contenido anterior al checkpoint.
    """
    access_token    = _get_token(db, medio.id, "access_token")
    threads_user_id = _get_token(db, medio.id, "threads_user_id")

    if not access_token or not threads_user_id:
        log.warning(f"[{medio.slug}] Faltan tokens Threads (access_token o threads_user_id)")
        return []

    if checkpoint and checkpoint.tzinfo is None:
        checkpoint = checkpoint.replace(tzinfo=timezone.utc)

    fields  = "id,media_type,text,timestamp,permalink,shortcode"
    config  = medio.config
    umbral  = config.umbral_confianza_marca if config else 80
    nuevas  = []
    next_url = None
    page     = 0
    MAX_PAGES = 20

    while page < MAX_PAGES:
        try:
            if next_url:
                with urllib.request.urlopen(next_url, timeout=15) as r:
                    resp = json.loads(r.read())
            else:
                resp = _api_get(
                    f"/{threads_user_id}/threads",
                    access_token,
                    {"fields": fields, "limit": 25},
                )
        except Exception as ex:
            log.error(f"[{medio.slug}] Error en Threads /threads: {ex}")
            break

        items = resp.get("data", [])
        if not items:
            break

        alcanzado_checkpoint = False
        for item in items:
            media_type = item.get("media_type", "TEXT_POST")
            fecha_str  = item.get("timestamp", "")
            try:
                fecha = datetime.fromisoformat(fecha_str.replace("Z", "+00:00"))
            except Exception:
                fecha = datetime.now(timezone.utc)

            if checkpoint and fecha <= checkpoint:
                alcanzado_checkpoint = True
                break

            post_id = item.get("id")
            if not post_id:
                continue

            existente = db.query(Publicacion).filter(
                Publicacion.medio_id == medio.id,
                Publicacion.id_externo == post_id,
            ).first()
            if existente:
                continue

            text = item.get("text", "") or ""
            clean_text, hashtags, mentions = _extract_text_parts(text)
            permalink = item.get("permalink", f"https://www.threads.net/t/{item.get('shortcode', post_id)}")
            tipo = MEDIA_TYPE_MAP.get(media_type, TipoEnum.post)

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

            insights = _get_post_insights(access_token, post_id)

            pub = Publicacion(
                medio_id=medio.id,
                marca_id=brand.marca_id,
                agencia_id=brand.agencia_id,
                id_externo=post_id,
                canal=CanalEnum.threads,
                tipo=tipo,
                url=permalink,
                titulo=None,
                fecha_publicacion=fecha,
                reach=insights["reach"],
                likes=insights["likes"],
                comments=insights["comments"],
                shares=insights["shares"],
                clicks=0,
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
                shares=pub.shares, comments=pub.comments, clicks=0,
            ))

            nuevas.append(pub)
            log.info(
                f"[{medio.slug}] Nuevo post Threads [{media_type}]: "
                f"{text[:60]!r} — marca: {brand.marca_nombre} ({brand.confianza}%)"
            )

        if alcanzado_checkpoint:
            break

        next_url = resp.get("paging", {}).get("next")
        if not next_url:
            break
        page += 1

    db.commit()
    return nuevas


# ── Actualización de métricas ─────────────────────────────────────────────────

def update_metrics(db: Session, medio: Medio, publicaciones: list[Publicacion]) -> int:
    """
    Actualiza métricas de posts Threads: reach (views), likes, replies, reposts+quotes.
    """
    if not publicaciones:
        return 0

    access_token = _get_token(db, medio.id, "access_token")
    if not access_token:
        log.warning(f"[{medio.slug}] Sin token Threads para actualizar métricas")
        return 0

    actualizadas = 0
    for pub in publicaciones:
        if not pub.id_externo:
            continue
        try:
            insights = _get_post_insights(access_token, pub.id_externo)

            db.add(HistorialMetricas(
                publicacion_id=pub.id,
                reach=insights["reach"],
                likes=insights["likes"],
                shares=insights["shares"],
                comments=insights["comments"],
                clicks=0,
            ))

            pub.reach    = insights["reach"]
            pub.likes    = insights["likes"]
            pub.comments = insights["comments"]
            pub.shares   = insights["shares"]
            pub.ultima_actualizacion = datetime.now(timezone.utc)
            pub.estado_metricas = EstadoMetricasEnum.actualizado
            actualizadas += 1

        except Exception as ex:
            log.error(f"[{medio.slug}] Error actualizando Threads {pub.id_externo}: {ex}")
            pub.estado_metricas = EstadoMetricasEnum.error

    db.commit()
    log.info(f"[{medio.slug}] Threads actualizado: {actualizadas}/{len(publicaciones)}")
    return actualizadas


# ── Snapshot semanal ISO ──────────────────────────────────────────────────────

def snapshot_weekly(db: Session, medio: Medio) -> int:
    """
    Snapshot semanal de métricas Threads para publicaciones de 2026+.
    Calcula reach_diff vs la semana anterior.
    Se ejecuta los lunes (job semanal del orquestador).
    """
    from datetime import date as _date
    from utils.semanas import get_semana_iso

    access_token = _get_token(db, medio.id, "access_token")
    if not access_token:
        log.warning(f"[{medio.slug}] Sin token Threads para snapshot_weekly")
        return 0

    hoy          = _date.today()
    semana_actual = get_semana_iso(hoy)
    inicio_2026  = datetime(2026, 1, 1, tzinfo=timezone.utc)

    pubs = (
        db.query(Publicacion)
        .filter(
            Publicacion.medio_id == medio.id,
            Publicacion.canal == CanalEnum.threads,
            Publicacion.estado_metricas != EstadoMetricasEnum.fijo,
            Publicacion.fecha_publicacion >= inicio_2026,
        )
        .all()
    )

    if not pubs:
        log.info(f"[{medio.slug}] snapshot_weekly Threads: sin publicaciones 2026+")
        return 0

    actualizadas = 0
    for pub in pubs:
        if not pub.id_externo:
            continue
        try:
            insights = _get_post_insights(access_token, pub.id_externo)

            reach_actual    = insights["reach"]
            likes_actual    = insights["likes"]
            shares_actual   = insights["shares"]
            comments_actual = insights["comments"]

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
            prev_reach    = prev.reach    if prev else 0
            prev_likes    = prev.likes    if prev else 0
            prev_shares   = prev.shares   if prev else 0
            prev_comments = prev.comments if prev else 0

            reach_diff    = max(0, reach_actual - prev_reach)
            likes_diff    = max(0, likes_actual - prev_likes)
            shares_diff   = max(0, shares_actual - prev_shares)
            comments_diff = max(0, comments_actual - prev_comments)

            existing = (
                db.query(HistorialMetricas)
                .filter(
                    HistorialMetricas.publicacion_id == pub.id,
                    HistorialMetricas.semana_iso == semana_actual,
                )
                .first()
            )
            if existing:
                existing.reach = reach_actual; existing.reach_diff = reach_diff
                existing.likes = likes_actual; existing.likes_diff = likes_diff
                existing.shares = shares_actual; existing.shares_diff = shares_diff
                existing.comments = comments_actual; existing.comments_diff = comments_diff
                existing.fuente = "api"
                existing.fecha_snapshot = datetime.now(timezone.utc)
            else:
                db.add(HistorialMetricas(
                    publicacion_id=pub.id, semana_iso=semana_actual,
                    reach=reach_actual,    reach_diff=reach_diff,
                    likes=likes_actual,    likes_diff=likes_diff,
                    shares=shares_actual,  shares_diff=shares_diff,
                    comments=comments_actual, comments_diff=comments_diff,
                    clicks=0, clicks_diff=0,
                    fuente="api",
                ))

            pub.reach    = reach_actual
            pub.likes    = likes_actual
            pub.comments = comments_actual
            pub.shares   = shares_actual
            pub.ultima_actualizacion = datetime.now(timezone.utc)
            pub.estado_metricas = EstadoMetricasEnum.actualizado
            actualizadas += 1

        except Exception as ex:
            log.error(f"[{medio.slug}] Error snapshot_weekly Threads {pub.id_externo}: {ex}")

    db.commit()
    log.info(f"[{medio.slug}] Threads snapshot_weekly: {actualizadas}/{len(pubs)}")
    return actualizadas
