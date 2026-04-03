"""
agents/instagram_stories_agent.py
Agente Instagram Stories: captura stories activas y sus métricas.

ESTRATEGIA (ventana 24h):
  - detect_and_update() → ejecuta cada hora en punto
      • Detecta stories nuevas (descarga imagen + Brand ID)
      • Actualiza métricas de las activas (reach, replies, navigation)
      • Marca como 'fijo' las que ya no aparecen en la API (caducadas)
  - capture_final() → ejecuta cada minuto entre :50 y :59
      • Solo actúa si hay stories que caducan en los próximos 10 min
      • Guarda snapshot final con es_final=True
      • Marca como fijo si la story ya caducó entre reintentos

detect_new() se mantiene como wrapper de compatibilidad.
"""
import logging
import os
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

GRAPH = "https://graph.facebook.com/v21.0"

# Métricas de stories v21.0 (disponibles solo 24h)
STORY_METRICS = "reach,replies,navigation"


# ── Token helper ──────────────────────────────────────────────────────────────

def _get_token(db: Session, medio_id: int, clave: str) -> Optional[str]:
    t = db.query(TokenCanal).filter(
        TokenCanal.medio_id == medio_id,
        TokenCanal.canal == "instagram",
        TokenCanal.clave == clave,
    ).first()
    return decrypt_token(t.valor_cifrado, settings.jwt_secret) if t else None


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


# ── Helpers internos ──────────────────────────────────────────────────────────

def _get_story_insights(token: str, story_id: str, raise_on_error: bool = False) -> dict:
    """
    Obtiene métricas de una story. Si raise_on_error=True lanza excepción
    en lugar de devolver ceros (usado por capture_final para distinguir errores).
    """
    result = {"reach": 0, "replies": 0, "navigation": 0}
    try:
        data = _graph_get(f"/{story_id}/insights", token, {"metric": STORY_METRICS})
        for item in data.get("data", []):
            name   = item.get("name", "")
            values = item.get("values", [])
            if values and name in result:
                result[name] = int(values[-1].get("value", 0))
    except Exception as ex:
        log.warning(f"[Stories] Insights no disponibles para story {story_id}: {ex}")
        if raise_on_error:
            raise
    return result


def _download_story_image(medio: Medio, story_id: str, item: dict, fecha: datetime) -> Optional[str]:
    """Descarga la imagen/thumbnail de una story y la guarda localmente."""
    img_url = item.get("media_url") or item.get("thumbnail_url")
    if not img_url:
        return None
    try:
        mes_str  = fecha.strftime("%Y-%m")
        save_dir = os.path.join("stories_images", medio.slug, mes_str)
        os.makedirs(save_dir, exist_ok=True)
        save_path = os.path.join(save_dir, f"{story_id}.jpg")
        req = urllib.request.Request(
            img_url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; SocialIntelligence/1.0)"},
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            with open(save_path, "wb") as f:
                f.write(r.read())
        log.info(f"[{medio.slug}] Story {story_id}: captura guardada en {save_path}")
        return save_path
    except Exception as ex:
        log.warning(f"[{medio.slug}] Story {story_id}: error descargando captura: {ex}")
        return None


def _snapshot_story(db: Session, pub: Publicacion, insights: dict, ahora: datetime, es_final: bool = False):
    """Guarda un snapshot horario en historial_metricas."""
    db.add(HistorialMetricas(
        publicacion_id=pub.id,
        reach=pub.reach, likes=0,
        shares=0, comments=pub.comments, clicks=pub.clicks,
        hora_snapshot=ahora,
        es_final=es_final,
    ))


# ── detect_and_update — ejecuta cada hora ─────────────────────────────────────

def detect_and_update(db: Session, medio: Medio) -> list[Publicacion]:
    """
    Ejecuta cada hora en punto:
    1. Obtiene stories activas de la API
    2. Stories nuevas: inserta en DB, descarga imagen, obtiene métricas
    3. Stories activas ya conocidas: actualiza métricas + snapshot horario
    4. Stories en DB que ya no aparecen en API: marca estado='fijo'
    """
    access_token  = _get_token(db, medio.id, "access_token")
    ig_account_id = _get_token(db, medio.id, "instagram_account_id")

    if not access_token or not ig_account_id:
        log.warning(f"[{medio.slug}] Faltan tokens Instagram para stories")
        return []

    fields = "id,media_type,timestamp,permalink,media_url,thumbnail_url"
    try:
        resp = _graph_get(f"/{ig_account_id}/stories", access_token, {"fields": fields})
    except Exception as ex:
        log.error(f"[{medio.slug}] Error obteniendo stories: {ex}")
        return []

    api_items = resp.get("data", [])
    api_ids   = {item["id"] for item in api_items if item.get("id")}
    ahora     = datetime.now(timezone.utc)
    config    = medio.config
    umbral    = config.umbral_confianza_marca if config else 80
    nuevas    = []

    for item in api_items:
        story_id = item.get("id")
        if not story_id:
            continue

        existente = db.query(Publicacion).filter(
            Publicacion.medio_id == medio.id,
            Publicacion.id_externo == story_id,
        ).first()

        if not existente:
            # ── Story nueva: insertar ───────────────────────────────────────
            fecha_str = item.get("timestamp", "")
            try:
                fecha = datetime.fromisoformat(fecha_str.replace("Z", "+00:00"))
            except Exception:
                fecha = ahora

            permalink  = item.get("permalink", f"https://www.instagram.com/stories/{ig_account_id}/{story_id}/")
            captura_url = _download_story_image(medio, story_id, item, fecha)

            brand = identify(medio_id=medio.id, db=db, url=permalink)
            insights = _get_story_insights(access_token, story_id)

            estado_marca = (
                EstadoMarcaEnum.estimated if brand.marca_id and brand.confianza >= 80
                else EstadoMarcaEnum.to_review
            )

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
                estado_metricas=EstadoMetricasEnum.actualizado,  # se actualiza cada hora
                confianza_marca=brand.confianza if brand.confianza > 0 else None,
                estado_marca=estado_marca,
                captura_url=captura_url,
                notas=f"navigation={insights['navigation']}",
                ultima_actualizacion=ahora,
            )
            db.add(pub)
            db.flush()
            _snapshot_story(db, pub, insights, ahora)

            nuevas.append(pub)
            log.info(
                f"[{medio.slug}] Story nueva {story_id}: "
                f"reach={pub.reach} replies={pub.comments} marca={brand.marca_nombre or '?'}"
            )

        elif existente.estado_metricas != EstadoMetricasEnum.fijo:
            # ── Story activa: actualizar métricas + snapshot ────────────────
            insights = _get_story_insights(access_token, story_id)
            existente.reach    = insights.get("reach", existente.reach)
            existente.comments = insights.get("replies", existente.comments)
            existente.clicks   = insights.get("navigation", existente.clicks)
            existente.notas    = f"navigation={existente.clicks}"
            existente.ultima_actualizacion = ahora
            _snapshot_story(db, existente, insights, ahora)
            log.info(f"[{medio.slug}] Story {story_id}: reach={existente.reach} replies={existente.comments}")

    # Marcar como 'fijo' las stories en DB que ya no están en la API (caducadas)
    activas_en_db = (
        db.query(Publicacion)
        .filter(
            Publicacion.medio_id == medio.id,
            Publicacion.canal == CanalEnum.instagram_story,
            Publicacion.estado_metricas != EstadoMetricasEnum.fijo,
        )
        .all()
    )
    for pub in activas_en_db:
        if pub.id_externo not in api_ids:
            pub.estado_metricas = EstadoMetricasEnum.fijo
            log.info(f"[{medio.slug}] Story {pub.id_externo}: caducada → fijo (reach={pub.reach})")

    db.commit()
    log.info(f"[{medio.slug}] detect_and_update: {len(nuevas)} nuevas capturadas")
    return nuevas


# ── capture_final — ejecuta cada minuto entre :50 y :59 ──────────────────────

def capture_final(db: Session, medio: Medio) -> int:
    """
    Captura final agresiva para stories que caducan en los próximos 10 minutos.
    Se ejecuta cada minuto entre :50 y :59 de cada hora.
    - Si la API responde: guarda snapshot con es_final=True
    - Si la story ya caducó: marca estado='fijo' con los datos que tengamos
    - Si falla por otro motivo: el scheduler reintentará en 1 minuto
    """
    access_token = _get_token(db, medio.id, "access_token")
    if not access_token:
        log.warning(f"[{medio.slug}] Sin token Instagram para capture_final")
        return 0

    ahora = datetime.now(timezone.utc)
    # Stories que caducan en los próximos 10 minutos:
    # publicadas hace entre 23h50min y 24h exactas
    limite_inf = ahora - timedelta(hours=24)              # ya expiradas (excluir)
    limite_sup = ahora - timedelta(hours=23, minutes=50)  # caducan en < 10 min

    proximas = (
        db.query(Publicacion)
        .filter(
            Publicacion.medio_id == medio.id,
            Publicacion.canal == CanalEnum.instagram_story,
            Publicacion.estado_metricas != EstadoMetricasEnum.fijo,
            Publicacion.fecha_publicacion > limite_inf,
            Publicacion.fecha_publicacion <= limite_sup,
        )
        .all()
    )

    if not proximas:
        return 0

    log.info(f"[{medio.slug}] capture_final: {len(proximas)} stories a punto de caducar")
    capturadas = 0

    for pub in proximas:
        if not pub.id_externo:
            continue
        try:
            insights = _get_story_insights(access_token, pub.id_externo, raise_on_error=True)

            # Usar el máximo entre la API y lo que ya teníamos (la API puede dar 0 al final)
            reach_final    = max(insights.get("reach", 0),      pub.reach)
            comments_final = max(insights.get("replies", 0),    pub.comments)
            clicks_final   = max(insights.get("navigation", 0), pub.clicks)

            pub.reach    = reach_final
            pub.comments = comments_final
            pub.clicks   = clicks_final
            pub.notas    = f"navigation={clicks_final}|es_final"
            pub.ultima_actualizacion = ahora

            _snapshot_story(db, pub, insights, ahora, es_final=True)
            capturadas += 1
            log.info(f"[{medio.slug}] Story {pub.id_externo}: captura final OK reach={reach_final}")

        except Exception as ex:
            log.warning(f"[{medio.slug}] Story {pub.id_externo}: fallo en captura final — {ex}")
            # Si ya pasaron 24h, marcar como fijo con los datos actuales
            if pub.fecha_publicacion:
                fp = pub.fecha_publicacion
                if fp.tzinfo is None:
                    fp = fp.replace(tzinfo=timezone.utc)
                if (ahora - fp).total_seconds() >= 86400:
                    pub.estado_metricas = EstadoMetricasEnum.fijo
                    log.info(f"[{medio.slug}] Story {pub.id_externo}: marcada fijo (>24h, error en insights)")

    db.commit()
    log.info(f"[{medio.slug}] capture_final: {capturadas}/{len(proximas)} capturadas")
    return capturadas


# ── detect_new — wrapper de compatibilidad ────────────────────────────────────

def detect_new(db: Session, medio: Medio, checkpoint: Optional[datetime]) -> list[Publicacion]:
    """
    Wrapper de compatibilidad. checkpoint ignorado (stories siempre de las últimas 24h).
    Llama a detect_and_update().
    """
    return detect_and_update(db, medio)


def update_metrics(db: Session, medio: Medio, publicaciones: list[Publicacion]) -> int:
    """Stories se gestionan via detect_and_update() y capture_final(). Siempre devuelve 0."""
    return 0
