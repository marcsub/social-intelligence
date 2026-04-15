"""
agents/facebook_agent.py
Agente Facebook: detecta posts de la página y recoge métricas via
Facebook Graph API (post_impressions_unique, reacciones, shares, comments).
Token: Page Access Token long-lived (no expira si viene de un long-lived user token).
"""
import logging
import re
import json
import urllib.request
import urllib.parse
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

GRAPH = "https://graph.facebook.com/v25.0"


def _parse_ts(s: str) -> datetime:
    """
    Parsea ISO 8601 devuelto por la API de Facebook/Meta.
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

# Meta no proporciona insights para posts con más de 24 meses de antigüedad
INSIGHTS_MAX_AGE_DAYS = 730

# Máximo de intentos fallidos antes de marcar sin_datos
FB_MAX_INTENTOS = 5


# ── Helpers para contador de intentos fallidos (en campo notas) ───────────────

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

def _notas_con_intentos(n: int, motivo: str) -> str:
    return f"{_INTENTOS_PREFIX}{n}|{motivo}"


# ── Token helper ──────────────────────────────────────────────────────────────

def _get_token(db: Session, medio_id: int, clave: str) -> Optional[str]:
    t = db.query(TokenCanal).filter(
        TokenCanal.medio_id == medio_id,
        TokenCanal.canal == "facebook",
        TokenCanal.clave == clave,
    ).first()
    return decrypt_token(t.valor_cifrado, settings.jwt_secret) if t else None


def _graph_get(path: str, token: str, params: dict = None) -> dict:
    """Llamada GET a Graph API."""
    p = {"access_token": token}
    if params:
        p.update(params)
    url = f"{GRAPH}{path}?{urllib.parse.urlencode(p)}"
    with urllib.request.urlopen(url, timeout=8) as r:
        data = json.loads(r.read())
    if "error" in data:
        raise RuntimeError(data["error"].get("message", str(data["error"])))
    return data


def _resolve_page_token(db: Session, medio_id: int, page_id: str) -> str:
    """
    Resuelve el Page Access Token con la siguiente prioridad:

    1. facebook / page_access_token  — token permanente obtenido via authorize_facebook.py
    2. Intercambiar facebook / access_token via /{page_id}?fields=access_token
       (solo funciona si access_token es un user/system token, no otro page token)

    Lanza RuntimeError si ninguno funciona.
    """
    # Prioridad 1: page_access_token dedicado (guardado por authorize_facebook.py)
    page_token = _get_token(db, medio_id, "page_access_token")
    if page_token:
        log.debug(f"[Facebook] Usando page_access_token guardado: {page_token[:20]}…")
        return page_token

    # Prioridad 2: intercambiar el access_token almacenado
    stored_token = _get_token(db, medio_id, "access_token")
    if not stored_token:
        raise RuntimeError("No hay access_token ni page_access_token guardados para Facebook")

    log.debug(f"[Facebook] Intentando exchange con access_token: {stored_token[:20]}… page_id={page_id}")
    try:
        data = _graph_get(f"/{page_id}", stored_token, {"fields": "access_token"})
    except RuntimeError as ex:
        msg = str(ex)
        if "190" in msg or "Invalid OAuth" in msg or "token" in msg.lower():
            log.error(
                f"[Facebook] Token caducado o sin permisos (page_id={page_id}): {msg}\n"
                f"  → Ejecutar: python scripts/authorize_facebook.py --slug <slug>"
            )
        else:
            log.error(f"[Facebook] Error en exchange de token: {msg}")
        raise

    exchanged = data.get("access_token")
    if not exchanged:
        log.error(
            f"[Facebook] El access_token guardado no pudo intercambiarse por un page token. "
            f"Respuesta: {str(data)[:200]}\n"
            f"  → Ejecutar: python scripts/authorize_facebook.py --slug <slug>"
        )
        raise RuntimeError(f"No se obtuvo page_access_token para page_id={page_id}")

    log.debug(f"[Facebook] page_access_token via exchange: {exchanged[:20]}…")
    return exchanged


def _get_post_insights(token: str, post_id: str) -> dict:
    """
    Obtiene métricas de un post de página via Graph API v25.0.
    Devuelve: reach, reactions, shares, comments.

    Cadena de fallbacks para reach (v25.0 / New Pages Experience):
      1. /{post_id}/insights?metric=reach             (v25 naming)
      2. /{post_id}/insights?metric=impressions        (proxy si reach no disponible)
      3. /{post_id}/insights?metric=post_engaged_users (engagement como proxy mínimo)
      4. /{post_id}?fields=insights{name,values}       (campo embebido)
      5. /{post_id}/insights?metric=reach&period=lifetime
    Si todo falla, reach=0 y el caller decide el estado_metricas.
    """
    result = {"reach": 0, "reactions": 0, "shares": 0, "comments": 0}
    reach_source = None

    # Cadena de intentos para reach — post_impressions_unique primero (funciona con page token)
    reach_attempts = [
        ({"metric": "post_impressions_unique"}, "post_impressions_unique"),
        ({"metric": "reach"},                   "reach"),
        ({"metric": "impressions"},             "impressions"),
    ]

    for params, label in reach_attempts:
        try:
            data = _graph_get(f"/{post_id}/insights", token, params)
            for item in data.get("data", []):
                values = item.get("values", [])
                if values:
                    val = values[-1].get("value", 0)
                    if isinstance(val, (int, float)) and int(val) > 0:
                        result["reach"] = int(val)
                        reach_source = f"/insights?{urllib.parse.urlencode(params)}"
            if result["reach"] > 0:
                break
        except Exception as ex:
            log.warning(f"[Facebook] {label} no disponible para {post_id}: {ex}")

    # Fallback final: insights embebidos en el campo del post
    if result["reach"] == 0:
        try:
            data = _graph_get(f"/{post_id}", token, {"fields": "insights{name,values}"})
            for item in data.get("insights", {}).get("data", []):
                values = item.get("values", [])
                if values:
                    val = values[-1].get("value", 0)
                    if isinstance(val, (int, float)) and int(val) > 0:
                        result["reach"] = int(val)
                        reach_source = f"fields=insights{{name,values}} ({item.get('name','')})"
                        break
        except Exception as ex:
            log.warning(f"[Facebook] fallback fields=insights no disponible para {post_id}: {ex}")

    if result["reach"] > 0:
        log.info(f"[Facebook] Post {post_id}: reach={result['reach']} (via {reach_source})")
    else:
        log.warning(f"[Facebook] Post {post_id}: reach=0 — todos los fallbacks fallaron")

    # Reacciones — timeout reducido a 5s; si fallan ambas se continúa con reactions=0
    for metric in ("post_reactions_by_type_total", "post_reactions_like_total"):
        try:
            p = {"access_token": token, "metric": metric}
            url = f"{GRAPH}/{post_id}/insights?{urllib.parse.urlencode(p)}"
            with urllib.request.urlopen(url, timeout=5) as r:
                data = json.loads(r.read())
            if "error" in data:
                raise RuntimeError(data["error"].get("message", str(data["error"])))
            for item in data.get("data", []):
                if item.get("name") == metric:
                    values = item.get("values", [])
                    if values:
                        val = values[-1].get("value", 0)
                        if isinstance(val, dict):
                            result["reactions"] = sum(int(v) for v in val.values())
                        elif isinstance(val, (int, float)):
                            result["reactions"] = int(val)
            if result["reactions"] > 0:
                break
        except Exception as ex:
            log.debug(f"[Facebook] {metric} no disponible para {post_id}: {ex}")

    return result


def _extract_caption_parts(message: str) -> tuple[str, str, str]:
    """Extrae texto limpio, hashtags y menciones de un post de Facebook."""
    if not message:
        return "", "", ""
    hashtags = " ".join(re.findall(r"#(\w+)", message))
    mentions = " ".join(re.findall(r"@(\w+)", message))
    clean    = re.sub(r"[#@]\w+", "", message).strip()
    return clean, hashtags, mentions


# ── Detección de publicaciones nuevas ─────────────────────────────────────────

def detect_new(db: Session, medio: Medio, checkpoint: Optional[datetime]) -> list[Publicacion]:
    """
    Lee los posts de la página de Facebook y detecta publicaciones nuevas.
    """
    page_id = _get_token(db, medio.id, "page_id")
    if not page_id:
        log.warning(f"[{medio.slug}] Falta page_id para Facebook")
        return []

    try:
        access_token = _resolve_page_token(db, medio.id, page_id)
    except Exception as ex:
        log.error(f"[{medio.slug}] No se pudo obtener page_access_token: {ex}")
        return []

    if checkpoint and checkpoint.tzinfo is None:
        checkpoint = checkpoint.replace(tzinfo=timezone.utc)

    config = medio.config
    umbral = config.umbral_confianza_marca if config else 80
    # comments.summary y reactions.summary requieren pages_read_engagement;
    # se obtienen via /insights (post_reactions_by_type_total)
    fields = "id,message,created_time,permalink_url,shares"

    # Parámetro since para filtrar en servidor (UNIX timestamp)
    params: dict = {"fields": fields, "limit": 25}
    if checkpoint:
        params["since"] = int(checkpoint.timestamp())

    nuevas = []
    next_url = None
    page = 0
    MAX_PAGES = 20

    while page < MAX_PAGES:
        try:
            if next_url:
                with urllib.request.urlopen(next_url, timeout=15) as r:
                    resp = json.loads(r.read())
            else:
                resp = _graph_get(f"/{page_id}/posts", access_token, params)
        except Exception as ex:
            log.error(f"[{medio.slug}] Error en Facebook /posts: {ex}")
            break

        items = resp.get("data", [])
        if not items:
            break

        alcanzado_checkpoint = False
        for item in items:
            fecha = _parse_ts(item.get("created_time", ""))

            if checkpoint and fecha <= checkpoint:
                alcanzado_checkpoint = True
                break

            post_id = item["id"]

            existente = db.query(Publicacion).filter(
                Publicacion.medio_id == medio.id,
                Publicacion.canal == CanalEnum.facebook,
                Publicacion.id_externo == post_id,
            ).first()
            if existente:
                continue

            message   = item.get("message", "") or ""
            permalink = item.get("permalink_url", "")
            shares    = item.get("shares", {}).get("count", 0)

            clean_text, hashtags, mentions = _extract_caption_parts(message)

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

            # Reach y reacciones via insights
            # Meta no devuelve insights para posts con > 24 meses de antigüedad
            edad_dias = (datetime.now(timezone.utc) - fecha).days
            if edad_dias > INSIGHTS_MAX_AGE_DAYS:
                insights = {"reach": 0, "reactions": 0, "shares": 0, "comments": 0}
                estado = EstadoMetricasEnum.sin_datos
                notas_reach = f"Post con {edad_dias} días de antigüedad (> 24 meses): Meta no proporciona insights"
                log.info(f"[Facebook] Post {post_id}: sin_datos (antigüedad {edad_dias} días)")
            else:
                insights = _get_post_insights(access_token, post_id)
                reach_val_tmp = insights.get("reach", 0)
                if reach_val_tmp == 0 and estado != EstadoMetricasEnum.revisar:
                    estado = EstadoMetricasEnum.error
                    notas_reach = "reach=0: post_impressions_unique devolvió 0"
                else:
                    notas_reach = brand.razonamiento if estado == EstadoMetricasEnum.revisar else None

            reach_val = insights.get("reach", 0)

            pub = Publicacion(
                medio_id=medio.id,
                marca_id=brand.marca_id,
                agencia_id=brand.agencia_id,
                id_externo=post_id,
                canal=CanalEnum.facebook,
                tipo=TipoEnum.post,
                url=permalink,
                titulo=None,
                texto=message or None,
                fecha_publicacion=fecha,
                reach=reach_val,
                likes=insights.get("reactions", 0),
                comments=0,
                shares=shares,
                estado_metricas=estado,
                confianza_marca=brand.confianza if brand.confianza > 0 else None,
                estado_marca=estado_marca,
                notas=notas_reach,
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
                f"[{medio.slug}] Nuevo post Facebook: {message[:50]!r} "
                f"— marca: {brand.marca_nombre} ({brand.confianza}%)"
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
    Actualiza reach, reacciones, shares y comentarios de posts de Facebook.
    """
    if not publicaciones:
        return 0

    page_id = _get_token(db, medio.id, "page_id")
    if not page_id:
        return 0
    try:
        access_token = _resolve_page_token(db, medio.id, page_id)
    except Exception as ex:
        log.error(f"[{medio.slug}] No se pudo obtener page_access_token para update: {ex}")
        return 0

    actualizadas = 0
    for pub in publicaciones:
        if not pub.id_externo:
            continue
        try:
            # Saltar posts con > 24 meses: Meta no tiene insights para ellos
            if pub.fecha_publicacion:
                edad_dias = (datetime.now(timezone.utc) - pub.fecha_publicacion.replace(tzinfo=timezone.utc)).days
            else:
                edad_dias = 0
            if edad_dias > INSIGHTS_MAX_AGE_DAYS:
                pub.estado_metricas = EstadoMetricasEnum.sin_datos
                pub.notas = f"Post con {edad_dias} días de antigüedad (> 24 meses): Meta no proporciona insights"
                pub.ultima_actualizacion = datetime.now(timezone.utc)
                log.info(f"[{medio.slug}] Post {pub.id_externo}: sin_datos (antigüedad {edad_dias} días)")
                actualizadas += 1
                continue

            # Shares via field (no requiere pages_read_engagement)
            detail = _graph_get(f"/{pub.id_externo}", access_token, {"fields": "shares"})
            shares = detail.get("shares", {}).get("count", pub.shares)

            insights = _get_post_insights(access_token, pub.id_externo)
            reach_val = insights.get("reach", pub.reach)

            db.add(HistorialMetricas(
                publicacion_id=pub.id,
                reach=reach_val,
                likes=insights.get("reactions", pub.likes),
                shares=shares,
                comments=pub.comments,
                clicks=0,
            ))

            pub.reach    = reach_val
            pub.likes    = insights.get("reactions", pub.likes)
            pub.shares   = shares
            pub.ultima_actualizacion = datetime.now(timezone.utc)
            if reach_val == 0:
                if edad_dias > INSIGHTS_MAX_AGE_DAYS:
                    pub.estado_metricas = EstadoMetricasEnum.sin_datos
                    pub.notas = f"reach=0 persistente + antigüedad {edad_dias} días (> 24 meses)"
                    log.info(f"[{medio.slug}] Post {pub.id_externo}: sin_datos (reach=0 + antigüedad)")
                else:
                    pub.estado_metricas = EstadoMetricasEnum.error
                    pub.notas = "reach=0 tras update: post_impressions_unique devolvió 0"
            else:
                pub.estado_metricas = EstadoMetricasEnum.actualizado
            actualizadas += 1

        except Exception as ex:
            intentos = _parse_intentos(pub.notas) + 1
            pub.ultima_actualizacion = datetime.now(timezone.utc)
            if intentos >= FB_MAX_INTENTOS:
                pub.estado_metricas = EstadoMetricasEnum.sin_datos
                pub.notas = _notas_con_intentos(intentos, f"error_persistente: {str(ex)[:120]}")
                log.info(f"[{medio.slug}] Facebook {pub.id_externo}: sin_datos ({intentos} intentos fallidos)")
            else:
                pub.estado_metricas = EstadoMetricasEnum.error
                pub.notas = _notas_con_intentos(intentos, str(ex)[:120])
                log.error(f"[{medio.slug}] Facebook {pub.id_externo}: error ({intentos}/{FB_MAX_INTENTOS}): {ex}")

    db.commit()
    log.info(f"[{medio.slug}] Facebook actualizado: {actualizadas}/{len(publicaciones)}")
    return actualizadas


# ── Snapshot semanal ISO ──────────────────────────────────────────────────────

def snapshot_weekly(db: Session, medio: Medio) -> int:
    """
    Snapshot semanal de métricas Facebook para todas las publicaciones de 2026+.
    """
    from datetime import date as _date
    from utils.semanas import get_semana_iso

    page_id = _get_token(db, medio.id, "page_id")
    if not page_id:
        log.warning(f"[{medio.slug}] Sin page_id Facebook para snapshot_weekly")
        return 0

    try:
        access_token = _resolve_page_token(db, medio.id, page_id)
    except Exception as ex:
        log.error(f"[{medio.slug}] No se pudo obtener page_access_token: {ex}")
        return 0

    hoy = _date.today()
    semana_actual = get_semana_iso(hoy)
    inicio_2026 = datetime(2026, 1, 1, tzinfo=timezone.utc)

    # Solo incluir posts con < 24 meses de antigüedad (Meta no tiene insights más antiguos)
    cutoff_insights = datetime.now(timezone.utc) - timedelta(days=INSIGHTS_MAX_AGE_DAYS)

    pubs = (
        db.query(Publicacion)
        .filter(
            Publicacion.medio_id == medio.id,
            Publicacion.canal == CanalEnum.facebook,
            Publicacion.estado_metricas != EstadoMetricasEnum.fijo,
            Publicacion.estado_metricas != EstadoMetricasEnum.sin_datos,
            Publicacion.fecha_publicacion >= inicio_2026,
            Publicacion.fecha_publicacion >= cutoff_insights,
        )
        .all()
    )

    if not pubs:
        log.info(f"[{medio.slug}] snapshot_weekly Facebook: sin publicaciones 2026+ dentro del límite de 24 meses")
        return 0

    actualizadas = 0
    for pub in pubs:
        if not pub.id_externo:
            continue
        try:
            detail = _graph_get(f"/{pub.id_externo}", access_token, {"fields": "shares"})
            shares_actual = detail.get("shares", {}).get("count", pub.shares)
            insights = _get_post_insights(access_token, pub.id_externo)
            reach_actual    = insights.get("reach", pub.reach)
            likes_actual    = insights.get("reactions", pub.likes)

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
            prev_reach  = prev.reach  if prev else 0
            prev_likes  = prev.likes  if prev else 0
            prev_shares = prev.shares if prev else 0

            reach_diff  = max(0, reach_actual - prev_reach)
            likes_diff  = max(0, likes_actual - prev_likes)
            shares_diff = max(0, shares_actual - prev_shares)

            existing = (
                db.query(HistorialMetricas)
                .filter(HistorialMetricas.publicacion_id == pub.id, HistorialMetricas.semana_iso == semana_actual)
                .first()
            )
            if existing:
                existing.reach = reach_actual; existing.reach_diff = reach_diff
                existing.likes = likes_actual; existing.likes_diff = likes_diff
                existing.shares = shares_actual; existing.shares_diff = shares_diff
                existing.fuente = "api"; existing.fecha_snapshot = datetime.now(timezone.utc)
            else:
                db.add(HistorialMetricas(
                    publicacion_id=pub.id, semana_iso=semana_actual,
                    reach=reach_actual, reach_diff=reach_diff,
                    likes=likes_actual, likes_diff=likes_diff,
                    shares=shares_actual, shares_diff=shares_diff,
                    comments=pub.comments, comments_diff=0,
                    clicks=0, clicks_diff=0, fuente="api",
                    reach_pagado=pub.reach_pagado or 0,
                    inversion_pagada=pub.inversion_pagada,
                ))

            pub.reach = reach_actual; pub.likes = likes_actual; pub.shares = shares_actual
            pub.ultima_actualizacion = datetime.now(timezone.utc)
            pub.estado_metricas = EstadoMetricasEnum.actualizado
            actualizadas += 1

        except Exception as ex:
            log.error(f"[{medio.slug}] Error snapshot_weekly Facebook {pub.id_externo}: {ex}")

    db.commit()
    log.info(f"[{medio.slug}] Facebook snapshot_weekly: {actualizadas}/{len(pubs)}")
    return actualizadas
