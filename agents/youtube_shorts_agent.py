"""
agents/youtube_shorts_agent.py
Agente YouTube Shorts: detecta y actualiza métricas de Shorts del canal propio.
Reutiliza las credenciales OAuth2 configuradas para el canal de YouTube.

Criterio de detección de Shorts:
  1. Principal: duración <= 60 segundos (contentDetails.duration, ISO 8601)
  2. Fallback (si duration no disponible): título contiene '#Shorts' o '#shorts'
Las métricas de Shorts son poco fiables en las primeras 48h — update_metrics
solo procesa publicaciones con más de 48h de antigüedad.
"""
import logging
import re
from datetime import datetime, timedelta, timezone, date as _date
from typing import Optional
from sqlalchemy.orm import Session
from googleapiclient.discovery import build

from core.brand_id_agent import identify
from core.settings import get_settings
from models.database import (
    Medio, Publicacion, HistorialMetricas,
    CanalEnum, TipoEnum, EstadoMetricasEnum, EstadoMarcaEnum
)
from agents.youtube_agent import (
    _build_credentials, _get_analytics_week,
)

log = logging.getLogger(__name__)
settings = get_settings()

# Duración máxima para considerar un vídeo como Short (segundos)
SHORTS_MAX_SECONDS = 60

# Los Shorts < 48h tienen métricas poco fiables
SHORTS_MIN_AGE_HOURS = 48


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_duration(iso: str) -> int:
    """Convierte duración ISO 8601 (PT1M3S) a segundos."""
    if not iso:
        return 0
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso)
    if not m:
        return 0
    return int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60 + int(m.group(3) or 0)


def _get_video_details(yt, video_ids: list[str]) -> dict:
    """
    Obtiene estadísticas, snippet, contentDetails de una lista de vídeos.
    Devuelve dict {video_id: {views, likes, comments, tags, duration_s}}.
    No filtra por duración — el filtrado se hace en detect_new().
    """
    if not video_ids:
        return {}
    try:
        resp = yt.videos().list(
            part="statistics,snippet,contentDetails",
            id=",".join(video_ids),
        ).execute()
        result = {}
        for item in resp.get("items", []):
            vid = item["id"]
            duration_iso = item.get("contentDetails", {}).get("duration", "")
            stats = item.get("statistics", {})
            snippet = item.get("snippet", {})
            result[vid] = {
                "views":      int(stats.get("viewCount", 0)),
                "likes":      int(stats.get("likeCount", 0)),
                "comments":   int(stats.get("commentCount", 0)),
                "tags":       snippet.get("tags", []),
                "duration_s": _parse_duration(duration_iso),
                "duration_iso": duration_iso,
            }
        return result
    except Exception as ex:
        log.error(f"[YouTube Shorts] Error obteniendo detalles de vídeos: {ex}")
        return {}


def _get_shorts_details(yt, video_ids: list[str]) -> dict:
    """
    Obtiene estadísticas para vídeos ya confirmados como Shorts (en update_metrics).
    Igual que _get_video_details pero sin el campo duration_s en el resultado.
    """
    details = _get_video_details(yt, video_ids)
    return {
        vid: {k: v for k, v in data.items() if k not in ("duration_s", "duration_iso")}
        for vid, data in details.items()
    }


# ── Detección de Shorts nuevos ────────────────────────────────────────────────

def detect_new(db: Session, medio: Medio, checkpoint: Optional[datetime]) -> list[Publicacion]:
    """
    Detecta Shorts nuevos publicados en el canal desde el checkpoint.
    Verificación en dos pasos:
      1. HTTP HEAD a /shorts/{id} — 200 = Short, 303 = vídeo normal
      2. Fallback: duración <= 62s si el HEAD falla
    """
    config = medio.config
    if not config or not config.youtube_channel_id:
        log.warning(f"[{medio.slug}] youtube_channel_id no configurado")
        return []

    creds = _build_credentials(db, medio.id)
    if not creds:
        return []

    try:
        yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    except Exception as ex:
        log.error(f"[{medio.slug}] Error construyendo cliente YouTube: {ex}")
        return []

    if checkpoint:
        cp = checkpoint if checkpoint.tzinfo else checkpoint.replace(tzinfo=timezone.utc)
        published_after = cp.strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        published_after = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")

    log.info(f"[{medio.slug}] Search API: iniciando búsqueda de vídeos (publishedAfter={published_after})...")
    try:
        resp = yt.search().list(
            part="id,snippet",
            channelId=config.youtube_channel_id,
            type="video",
            order="date",
            publishedAfter=published_after,
            maxResults=50,
        ).execute()
    except Exception as ex:
        log.error(f"[{medio.slug}] Error en YouTube Shorts search: {ex}")
        return []

    items = resp.get("items", [])
    log.info(f"[{medio.slug}] Search API: {len(items)} vídeos en respuesta raw")
    for item in items:
        log.info(f"[{medio.slug}]   video_id={item['id']['videoId']} title={item['snippet']['title'][:50]}")
    if not items:
        return []

    video_ids = [i["id"]["videoId"] for i in items if i.get("id", {}).get("videoId")]

    # Obtener detalles de todos los vídeos
    all_details = _get_video_details(yt, video_ids)
    log.info(f"[{medio.slug}] videos.list: {len(all_details)} detalles obtenidos")
    for vid_id, details in all_details.items():
        log.info(f"[{medio.slug}]   {vid_id}: duration_s={details.get('duration_s')} duration_iso={details.get('duration_iso')}")

    # Determinar cuáles son Shorts
    # Criterio principal: duración <= 60s
    # Criterio secundario (si duration no disponible): título contiene #Shorts
    confirmed_shorts: set[str] = set()
    for item in items:
        vid_id = item.get("id", {}).get("videoId")
        if not vid_id:
            continue
        detail = all_details.get(vid_id)
        titulo_search = item.get("snippet", {}).get("title", "")

        if not detail:
            log.info(f"[{medio.slug}] Verificando vídeo {vid_id}: sin datos de API — omitido")
            continue

        duration_s = detail["duration_s"]
        duration_iso = detail["duration_iso"]
        log.info(f"[{medio.slug}] Verificando vídeo {vid_id}: duración={duration_s}s ({duration_iso})")

        if duration_iso:
            # Criterio principal: duración
            if duration_s <= SHORTS_MAX_SECONDS:
                log.info(f"[{medio.slug}] Short confirmado: {vid_id} ({duration_s}s <= {SHORTS_MAX_SECONDS}s)")
                confirmed_shorts.add(vid_id)
            else:
                log.info(f"[{medio.slug}] No es Short: {vid_id} ({duration_s}s > {SHORTS_MAX_SECONDS}s)")
        else:
            # Fallback: título contiene #Shorts
            has_hashtag = "#shorts" in titulo_search.lower()
            if has_hashtag:
                log.info(f"[{medio.slug}] Short confirmado (#Shorts en título): {vid_id}")
                confirmed_shorts.add(vid_id)
            else:
                log.info(f"[{medio.slug}] No es Short (sin duración ni #Shorts): {vid_id}")

    if not confirmed_shorts:
        log.info(f"[{medio.slug}] Ningún Short nuevo confirmado")
        return []

    umbral = config.umbral_confianza_marca if config else 80
    nuevas = []

    for item in items:
        video_id = item.get("id", {}).get("videoId")
        if not video_id or video_id not in confirmed_shorts:
            continue

        # Evitar duplicados — filtrar solo canal youtube_short
        # (el mismo video_id puede existir como canal='youtube' si fue detectado antes como vídeo normal)
        existe_short = db.query(Publicacion).filter(
            Publicacion.medio_id == medio.id,
            Publicacion.canal == CanalEnum.youtube_short,
            Publicacion.id_externo == video_id,
        ).first()
        existe_youtube = db.query(Publicacion).filter(
            Publicacion.medio_id == medio.id,
            Publicacion.canal == CanalEnum.youtube,
            Publicacion.id_externo == video_id,
        ).first()
        log.info(
            f"[{medio.slug}] Verificando duplicado {video_id}: "
            f"existe en youtube={bool(existe_youtube)}, existe en youtube_short={bool(existe_short)}"
        )
        if existe_short:
            continue

        snippet = item.get("snippet", {})
        titulo = snippet.get("title", "")
        descripcion = snippet.get("description", "")[:500]
        tags_raw = all_details[video_id].get("tags", [])
        tags = " ".join(tags_raw)
        fecha_str = snippet.get("publishedAt", "")

        try:
            fecha = datetime.fromisoformat(fecha_str.replace("Z", "+00:00"))
        except Exception:
            fecha = datetime.now(timezone.utc)

        url = f"https://www.youtube.com/shorts/{video_id}"

        brand = identify(
            medio_id=medio.id,
            db=db,
            title=titulo,
            description=descripcion,
            hashtags=tags,
            url=url,
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

        stats = all_details[video_id]
        pub = Publicacion(
            medio_id=medio.id,
            marca_id=brand.marca_id,
            agencia_id=brand.agencia_id,
            id_externo=video_id,
            canal=CanalEnum.youtube_short,
            tipo=TipoEnum.short,
            url=url,
            titulo=titulo,
            texto=descripcion or None,
            fecha_publicacion=fecha,
            reach=stats["views"],
            likes=stats["likes"],
            comments=stats["comments"],
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
            shares=0, comments=pub.comments, clicks=0,
        ))

        nuevas.append(pub)
        log.info(
            f"[{medio.slug}] Nuevo Short: {titulo[:60]} "
            f"— marca: {brand.marca_nombre} ({brand.confianza}%)"
        )

    db.commit()
    log.info(f"[{medio.slug}] YouTube Shorts detect_new: {len(nuevas)} nuevos")
    return nuevas


# ── Actualización de métricas ─────────────────────────────────────────────────

def update_metrics(db: Session, medio: Medio, publicaciones: list[Publicacion]) -> int:
    """
    Actualiza métricas de Shorts. Solo procesa los publicados hace > 48h
    (los más recientes tienen datos poco fiables en YouTube Analytics).
    """
    if not publicaciones:
        return 0

    creds = _build_credentials(db, medio.id)
    if not creds:
        return 0

    try:
        yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    except Exception as ex:
        log.error(f"[{medio.slug}] Error construyendo cliente YouTube Shorts: {ex}")
        return 0

    ahora = datetime.now(timezone.utc)
    umbral_48h = ahora - timedelta(hours=SHORTS_MIN_AGE_HOURS)

    # Filtrar solo los shorts con > 48h
    elegibles = []
    for pub in publicaciones:
        fp = pub.fecha_publicacion
        if fp and fp.tzinfo is None:
            fp = fp.replace(tzinfo=timezone.utc)
        if fp and fp <= umbral_48h:
            elegibles.append(pub)
        else:
            log.debug(f"[{medio.slug}] Short {pub.id_externo}: < 48h, saltando")

    if not elegibles:
        log.info(f"[{medio.slug}] Shorts update_metrics: todos < 48h, sin actualizar")
        return 0

    video_ids = [p.id_externo for p in elegibles if p.id_externo]
    details = _get_shorts_details(yt, video_ids)

    actualizadas = 0
    for pub in elegibles:
        if not pub.id_externo:
            continue
        try:
            stats = details.get(pub.id_externo)
            if stats is None:
                # Ya no es un Short o fue eliminado
                log.warning(f"[{medio.slug}] Short {pub.id_externo}: no encontrado en API")
                continue

            db.add(HistorialMetricas(
                publicacion_id=pub.id,
                reach=stats["views"],
                likes=stats["likes"],
                shares=0,
                comments=stats["comments"],
                clicks=0,
            ))

            pub.reach    = stats["views"]
            pub.likes    = stats["likes"]
            pub.comments = stats["comments"]
            pub.ultima_actualizacion = ahora
            pub.estado_metricas = EstadoMetricasEnum.actualizado
            actualizadas += 1

        except Exception as ex:
            log.error(f"[{medio.slug}] Error actualizando Short {pub.id_externo}: {ex}")
            pub.estado_metricas = EstadoMetricasEnum.error

    db.commit()
    log.info(f"[{medio.slug}] YouTube Shorts actualizado: {actualizadas}/{len(elegibles)}")
    return actualizadas


# ── Snapshot semanal ISO ──────────────────────────────────────────────────────

def snapshot_weekly(db: Session, medio: Medio) -> int:
    """
    Snapshot semanal de métricas para Shorts de 2026+.
    Usa YouTube Analytics API para histórico semanal real.
    Mismo patrón que youtube_agent.update_weekly_youtube().
    """
    from utils.semanas import get_semana_iso, get_rango_semana, semanas_entre

    creds = _build_credentials(db, medio.id)
    if not creds:
        log.warning(f"[{medio.slug}] Sin credenciales YouTube para Shorts snapshot_weekly")
        return 0

    try:
        yt_anal = build("youtubeAnalytics", "v2", credentials=creds, cache_discovery=False)
    except Exception as ex:
        log.error(f"[{medio.slug}] Error construyendo Analytics para Shorts: {ex}")
        return 0

    hoy = _date.today()
    inicio_2026 = datetime(2026, 1, 1, tzinfo=timezone.utc)

    pubs = (
        db.query(Publicacion)
        .filter(
            Publicacion.medio_id == medio.id,
            Publicacion.canal == CanalEnum.youtube_short,
            Publicacion.estado_metricas != EstadoMetricasEnum.fijo,
            Publicacion.fecha_publicacion >= inicio_2026,
        )
        .order_by(Publicacion.fecha_publicacion.asc())
        .all()
    )

    if not pubs:
        log.info(f"[{medio.slug}] snapshot_weekly Shorts: sin publicaciones 2026+")
        return 0

    log.info(f"[{medio.slug}] snapshot_weekly Shorts: {len(pubs)} a procesar")
    actualizadas = 0

    for pub in pubs:
        if not pub.id_externo:
            continue
        try:
            pub_date = pub.fecha_publicacion.date() if hasattr(pub.fecha_publicacion, "date") else pub.fecha_publicacion
            todas_semanas = semanas_entre(pub_date, hoy)

            snapshots_existentes = {
                h.semana_iso: h
                for h in db.query(HistorialMetricas).filter(
                    HistorialMetricas.publicacion_id == pub.id,
                    HistorialMetricas.semana_iso.isnot(None),
                ).all()
            }
            semanas_pendientes = [s for s in todas_semanas if s not in snapshots_existentes]
            if not semanas_pendientes:
                continue

            primera_pendiente = semanas_pendientes[0]
            acumulado_reach    = sum(h.reach_diff    or 0 for s, h in snapshots_existentes.items() if s < primera_pendiente)
            acumulado_likes    = sum(h.likes_diff    or 0 for s, h in snapshots_existentes.items() if s < primera_pendiente)
            acumulado_comments = sum(h.comments_diff or 0 for s, h in snapshots_existentes.items() if s < primera_pendiente)

            for semana in semanas_pendientes:
                lunes, domingo = get_rango_semana(semana)
                start = max(pub_date, lunes)
                end   = min(hoy, domingo)
                if start > end:
                    continue

                analytics = _get_analytics_week(yt_anal, pub.id_externo, start, end)
                diff_views    = analytics["views"]
                diff_likes    = analytics["likes"]
                diff_comments = analytics["comments"]
                diff_shares   = analytics["shares"]

                acumulado_reach    += diff_views
                acumulado_likes    += diff_likes
                acumulado_comments += diff_comments

                existing_h = snapshots_existentes.get(semana)
                if existing_h:
                    existing_h.reach = acumulado_reach;    existing_h.reach_diff = diff_views
                    existing_h.likes = acumulado_likes;    existing_h.likes_diff = diff_likes
                    existing_h.comments = acumulado_comments; existing_h.comments_diff = diff_comments
                    existing_h.shares_diff = diff_shares
                    existing_h.fuente = "api"
                    existing_h.fecha_snapshot = datetime.now(timezone.utc)
                else:
                    db.add(HistorialMetricas(
                        publicacion_id=pub.id,
                        semana_iso=semana,
                        reach=acumulado_reach,    reach_diff=diff_views,
                        likes=acumulado_likes,    likes_diff=diff_likes,
                        shares=0, shares_diff=diff_shares,
                        comments=acumulado_comments, comments_diff=diff_comments,
                        clicks=0, clicks_diff=0, fuente="api",
                    ))
                    db.flush()

            pub.reach    = acumulado_reach
            pub.likes    = acumulado_likes
            pub.comments = acumulado_comments
            pub.ultima_actualizacion = datetime.now(timezone.utc)
            pub.estado_metricas = EstadoMetricasEnum.actualizado
            actualizadas += 1

        except Exception as ex:
            log.error(f"[{medio.slug}] Error snapshot_weekly Short {pub.id_externo}: {ex}")

    db.commit()
    log.info(f"[{medio.slug}] YouTube Shorts snapshot_weekly: {actualizadas}/{len(pubs)}")
    return actualizadas
