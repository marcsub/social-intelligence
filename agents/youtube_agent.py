"""
agents/youtube_agent.py
Agente YouTube: detecta vídeos nuevos en el canal propio y recoge
métricas via YouTube Data API v3 + YouTube Analytics API.
OAuth 2.0 con refresh automático de token.
"""
import logging
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy.orm import Session
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

from core.brand_id_agent import identify
from core.crypto import decrypt_token
from core.settings import get_settings
from models.database import (
    Medio, Publicacion, TokenCanal, HistorialMetricas,
    CanalEnum, TipoEnum, EstadoMetricasEnum, EstadoMarcaEnum
)

log = logging.getLogger(__name__)
settings = get_settings()

SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]


# ── Token helpers ─────────────────────────────────────────────────────────────

def _get_token(db: Session, medio_id: int, clave: str) -> Optional[str]:
    t = db.query(TokenCanal).filter(
        TokenCanal.medio_id == medio_id,
        TokenCanal.canal == "youtube",
        TokenCanal.clave == clave,
    ).first()
    return decrypt_token(t.valor_cifrado, settings.jwt_secret) if t else None


def _save_token(db: Session, medio_id: int, clave: str, valor: str):
    from core.crypto import encrypt_token
    t = db.query(TokenCanal).filter(
        TokenCanal.medio_id == medio_id,
        TokenCanal.canal == "youtube",
        TokenCanal.clave == clave,
    ).first()
    if t:
        t.valor_cifrado = encrypt_token(valor, settings.jwt_secret)
    else:
        t = TokenCanal(
            medio_id=medio_id, canal="youtube", clave=clave,
            valor_cifrado=encrypt_token(valor, settings.jwt_secret)
        )
        db.add(t)
    db.commit()


def _build_credentials(db: Session, medio_id: int) -> Optional[Credentials]:
    """
    Construye y refresca credenciales OAuth2 para YouTube.
    Guarda el access_token renovado en DB automáticamente.
    """
    client_id     = _get_token(db, medio_id, "client_id")
    client_secret = _get_token(db, medio_id, "client_secret")
    refresh_token = _get_token(db, medio_id, "refresh_token")
    access_token  = _get_token(db, medio_id, "access_token")

    if not all([client_id, client_secret, refresh_token]):
        log.warning(f"[YouTube] Faltan credenciales OAuth para medio {medio_id}")
        return None

    creds = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )

    # Refrescar si está expirado
    if not creds.valid:
        try:
            creds.refresh(Request())
            _save_token(db, medio_id, "access_token", creds.token)
            log.info(f"[YouTube] Token refrescado para medio {medio_id}")
        except Exception as ex:
            log.error(f"[YouTube] Error refrescando token: {ex}")
            return None

    return creds


# ── Detección de vídeos nuevos ────────────────────────────────────────────────

def detect_new(db: Session, medio: Medio, checkpoint: Optional[datetime]) -> list[Publicacion]:
    """
    Detecta vídeos nuevos publicados en el canal propio desde el checkpoint.
    Inserta en DB con Brand ID Agent aplicado.
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

    # Buscar vídeos del canal ordenados por fecha
    # publishedAfter requiere formato RFC 3339 con Z (aware UTC)
    if checkpoint:
        cp = checkpoint if checkpoint.tzinfo else checkpoint.replace(tzinfo=timezone.utc)
        published_after = cp.strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        published_after = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")

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
        log.error(f"[{medio.slug}] Error en YouTube search: {ex}")
        return []

    items = resp.get("items", [])
    if not items:
        log.info(f"[{medio.slug}] Sin vídeos nuevos en YouTube")
        return []

    # Obtener detalles (estadísticas) en lote
    video_ids = [i["id"]["videoId"] for i in items if i.get("id", {}).get("videoId")]
    details_map = _get_video_details(yt, video_ids)

    # Obtener mapa de playlists para todos los nuevos vídeos
    playlists_map = _get_playlists_map(yt)

    nuevas = []
    umbral = config.umbral_confianza_marca if config else 80

    for item in items:
        video_id = item.get("id", {}).get("videoId")
        if not video_id:
            continue

        snippet = item.get("snippet", {})
        titulo = snippet.get("title", "")
        descripcion = snippet.get("description", "")[:500]
        tags_raw = details_map.get(video_id, {}).get("tags", [])
        tags = " ".join(tags_raw)
        fecha_str = snippet.get("publishedAt", "")

        try:
            fecha = datetime.fromisoformat(fecha_str.replace("Z", "+00:00"))
        except Exception:
            fecha = datetime.now(timezone.utc)

        url = f"https://www.youtube.com/watch?v={video_id}"

        # Evitar duplicados
        existente = db.query(Publicacion).filter(
            Publicacion.medio_id == medio.id,
            Publicacion.id_externo == video_id,
        ).first()
        if existente:
            continue

        # Brand ID
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

        stats = details_map.get(video_id, {})
        # Playlists a las que pertenece este vídeo
        pl_titles = playlists_map.get(video_id, [])
        etiquetas_json = json.dumps(pl_titles, ensure_ascii=False) if pl_titles else None
        pub = Publicacion(
            medio_id=medio.id,
            marca_id=brand.marca_id,
            agencia_id=brand.agencia_id,
            id_externo=video_id,
            canal=CanalEnum.youtube,
            tipo=TipoEnum.video,
            url=url,
            titulo=titulo,
            texto=descripcion or None,
            fecha_publicacion=fecha,
            reach=stats.get("views", 0),
            likes=stats.get("likes", 0),
            comments=stats.get("comments", 0),
            estado_metricas=estado,
            confianza_marca=brand.confianza if brand.confianza > 0 else None,
            estado_marca=estado_marca,
            notas=brand.razonamiento if estado == EstadoMetricasEnum.revisar else None,
            etiquetas=etiquetas_json,
        )
        db.add(pub)
        db.flush()

        # Historial inicial
        db.add(HistorialMetricas(
            publicacion_id=pub.id,
            reach=pub.reach, likes=pub.likes,
            shares=0, comments=pub.comments, clicks=0,
        ))

        nuevas.append(pub)
        log.info(f"[{medio.slug}] Nuevo vídeo: {titulo[:60]} — marca: {brand.marca_nombre} ({brand.confianza}%)")

    db.commit()
    return nuevas


def _get_video_details(yt, video_ids: list[str]) -> dict:
    """Obtiene estadísticas y tags de una lista de video_ids en una sola llamada."""
    if not video_ids:
        return {}
    try:
        resp = yt.videos().list(
            part="statistics,snippet",
            id=",".join(video_ids),
        ).execute()
        result = {}
        for item in resp.get("items", []):
            vid = item["id"]
            stats = item.get("statistics", {})
            snippet = item.get("snippet", {})
            result[vid] = {
                "views":    int(stats.get("viewCount", 0)),
                "likes":    int(stats.get("likeCount", 0)),
                "comments": int(stats.get("commentCount", 0)),
                "tags":     snippet.get("tags", []),
            }
        return result
    except Exception as ex:
        log.error(f"[YouTube] Error obteniendo detalles de vídeos: {ex}")
        return {}


def _get_playlists_map(yt) -> dict:
    """
    Devuelve un mapa {video_id: [playlist_title, ...]} con todas las playlists
    del canal y los vídeos que contiene cada una.
    Hace paginación completa de playlists y de playlistItems.
    """
    video_playlists: dict = {}
    try:
        # Obtener todas las playlists del canal
        next_page = None
        playlists = []
        while True:
            kwargs = {"part": "snippet", "mine": True, "maxResults": 50}
            if next_page:
                kwargs["pageToken"] = next_page
            resp = yt.playlists().list(**kwargs).execute()
            for pl in resp.get("items", []):
                playlists.append({"id": pl["id"], "title": pl["snippet"]["title"]})
            next_page = resp.get("nextPageToken")
            if not next_page:
                break

        # Para cada playlist, obtener todos sus items
        for pl in playlists:
            pl_id = pl["id"]
            pl_title = pl["title"]
            next_page = None
            while True:
                kwargs = {"part": "snippet", "playlistId": pl_id, "maxResults": 50}
                if next_page:
                    kwargs["pageToken"] = next_page
                resp = yt.playlistItems().list(**kwargs).execute()
                for item in resp.get("items", []):
                    vid = item.get("snippet", {}).get("resourceId", {}).get("videoId")
                    if vid:
                        video_playlists.setdefault(vid, [])
                        if pl_title not in video_playlists[vid]:
                            video_playlists[vid].append(pl_title)
                next_page = resp.get("nextPageToken")
                if not next_page:
                    break

    except Exception as ex:
        log.error(f"[YouTube] Error obteniendo playlists: {ex}")

    return video_playlists


# ── Actualización de métricas ─────────────────────────────────────────────────

def update_metrics(db: Session, medio: Medio, publicaciones: list[Publicacion]) -> int:
    """
    Actualiza métricas de vídeos YouTube: views, likes, comments (Data API)
    + impressions/reach (Analytics API — solo canal propio).
    """
    if not publicaciones:
        return 0

    creds = _build_credentials(db, medio.id)
    if not creds:
        return 0

    try:
        yt      = build("youtube", "v3", credentials=creds, cache_discovery=False)
        yt_anal = build("youtubeAnalytics", "v2", credentials=creds, cache_discovery=False)
    except Exception as ex:
        log.error(f"[{medio.slug}] Error construyendo clientes YouTube: {ex}")
        return 0

    video_ids = [p.id_externo for p in publicaciones if p.id_externo]
    details = _get_video_details(yt, video_ids)

    actualizadas = 0
    for pub in publicaciones:
        if not pub.id_externo:
            continue
        try:
            stats = details.get(pub.id_externo, {})

            # Views desde Analytics API (más preciso que Data API para canal propio)
            analytics_views = _get_analytics_views(yt_anal, pub.id_externo, pub.fecha_publicacion)
            reach = analytics_views if analytics_views else stats.get("views", pub.reach)

            # Snapshot
            db.add(HistorialMetricas(
                publicacion_id=pub.id,
                reach=reach,
                likes=stats.get("likes", pub.likes),
                shares=0,
                comments=stats.get("comments", pub.comments),
                clicks=0,
            ))

            pub.reach    = reach
            pub.likes    = stats.get("likes", pub.likes)
            pub.comments = stats.get("comments", pub.comments)
            pub.ultima_actualizacion = datetime.now(timezone.utc)
            pub.estado_metricas = EstadoMetricasEnum.actualizado
            actualizadas += 1

        except Exception as ex:
            log.error(f"[{medio.slug}] Error actualizando YouTube {pub.id_externo}: {ex}")
            pub.estado_metricas = EstadoMetricasEnum.error

    db.commit()
    log.info(f"[{medio.slug}] YouTube actualizado: {actualizadas}/{len(publicaciones)}")
    return actualizadas


# ── Snapshot semanal ISO ──────────────────────────────────────────────────────

def snapshot_weekly(db: Session, medio: Medio) -> int:
    """
    Snapshot semanal de métricas YouTube para todas las publicaciones de 2026+.
    Usa YouTube Data API para totales; calcula diff vs semana anterior.
    """
    from datetime import date as _date
    from utils.semanas import get_semana_iso

    creds = _build_credentials(db, medio.id)
    if not creds:
        log.warning(f"[{medio.slug}] Sin credenciales YouTube para snapshot_weekly")
        return 0

    try:
        yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    except Exception as ex:
        log.error(f"[{medio.slug}] Error construyendo cliente YouTube: {ex}")
        return 0

    hoy = _date.today()
    semana_actual = get_semana_iso(hoy)
    inicio_2026 = datetime(2026, 1, 1, tzinfo=timezone.utc)

    pubs = (
        db.query(Publicacion)
        .filter(
            Publicacion.medio_id == medio.id,
            Publicacion.canal == CanalEnum.youtube,
            Publicacion.estado_metricas != EstadoMetricasEnum.fijo,
            Publicacion.fecha_publicacion >= inicio_2026,
        )
        .all()
    )

    if not pubs:
        log.info(f"[{medio.slug}] snapshot_weekly YouTube: sin publicaciones 2026+")
        return 0

    video_ids = [p.id_externo for p in pubs if p.id_externo]
    details = _get_video_details(yt, video_ids)

    actualizadas = 0
    for pub in pubs:
        if not pub.id_externo:
            continue
        try:
            stats = details.get(pub.id_externo, {})
            reach_actual    = stats.get("views", pub.reach)
            likes_actual    = stats.get("likes", pub.likes)
            comments_actual = stats.get("comments", pub.comments)

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
            prev_comments = prev.comments if prev else 0

            reach_diff    = max(0, reach_actual - prev_reach)
            likes_diff    = max(0, likes_actual - prev_likes)
            comments_diff = max(0, comments_actual - prev_comments)

            existing = (
                db.query(HistorialMetricas)
                .filter(HistorialMetricas.publicacion_id == pub.id, HistorialMetricas.semana_iso == semana_actual)
                .first()
            )
            if existing:
                existing.reach = reach_actual; existing.reach_diff = reach_diff
                existing.likes = likes_actual; existing.likes_diff = likes_diff
                existing.comments = comments_actual; existing.comments_diff = comments_diff
                existing.fuente = "api"; existing.fecha_snapshot = datetime.now(timezone.utc)
            else:
                db.add(HistorialMetricas(
                    publicacion_id=pub.id, semana_iso=semana_actual,
                    reach=reach_actual, reach_diff=reach_diff,
                    likes=likes_actual, likes_diff=likes_diff,
                    shares=0, shares_diff=0,
                    comments=comments_actual, comments_diff=comments_diff,
                    clicks=0, clicks_diff=0, fuente="api",
                    reach_pagado=pub.reach_pagado or 0,
                    inversion_pagada=pub.inversion_pagada,
                ))

            pub.reach = reach_actual; pub.likes = likes_actual; pub.comments = comments_actual
            pub.ultima_actualizacion = datetime.now(timezone.utc)
            pub.estado_metricas = EstadoMetricasEnum.actualizado
            actualizadas += 1

        except Exception as ex:
            log.error(f"[{medio.slug}] Error snapshot_weekly YouTube {pub.id_externo}: {ex}")

    db.commit()
    log.info(f"[{medio.slug}] YouTube snapshot_weekly: {actualizadas}/{len(pubs)}")
    return actualizadas


def _get_analytics_week(yt_anal, video_id: str, start, end) -> dict:
    """
    Consulta YouTube Analytics API para un vídeo en un rango de fechas específico.
    Devuelve dict con views, likes, comments, shares para ese período.
    """
    try:
        resp = yt_anal.reports().query(
            ids="channel==MINE",
            startDate=start.strftime("%Y-%m-%d"),
            endDate=end.strftime("%Y-%m-%d"),
            metrics="views,likes,comments,shares",
            dimensions="video",
            filters=f"video=={video_id}",
        ).execute()
        rows = resp.get("rows", [])
        if rows:
            row = rows[0]  # [video_id, views, likes, comments, shares]
            return {
                "views":    int(row[1]) if len(row) > 1 else 0,
                "likes":    int(row[2]) if len(row) > 2 else 0,
                "comments": int(row[3]) if len(row) > 3 else 0,
                "shares":   int(row[4]) if len(row) > 4 else 0,
            }
        return {"views": 0, "likes": 0, "comments": 0, "shares": 0}
    except Exception as ex:
        log.warning(f"[YouTube Analytics] Sin datos para {video_id} ({start}→{end}): {ex}")
        return {"views": 0, "likes": 0, "comments": 0, "shares": 0}


def update_weekly_youtube(db: Session, medio: Medio) -> int:
    """
    Snapshot semanal ISO para YouTube con histórico real semana a semana.
    Usa YouTube Analytics API para obtener views/likes/comments por semana concreta.
    Sigue el mismo patrón que update_weekly_ga4() en web_agent:
    - Primera ejecución: recalcula toda la historia desde semana de publicación
    - Ejecuciones siguientes: solo semanas pendientes (normalmente la actual)
    - Guarda reach_diff (views de esa semana) y reach (acumulado)
    """
    from datetime import date as _date
    from utils.semanas import get_semana_iso, get_rango_semana, semanas_entre

    creds = _build_credentials(db, medio.id)
    if not creds:
        log.warning(f"[{medio.slug}] Sin credenciales YouTube para update_weekly_youtube")
        return 0

    try:
        yt_anal = build("youtubeAnalytics", "v2", credentials=creds, cache_discovery=False)
    except Exception as ex:
        log.error(f"[{medio.slug}] Error construyendo cliente Analytics YouTube: {ex}")
        return 0

    hoy = _date.today()
    inicio_2026 = datetime(2026, 1, 1, tzinfo=timezone.utc)

    pubs = (
        db.query(Publicacion)
        .filter(
            Publicacion.medio_id == medio.id,
            Publicacion.canal == CanalEnum.youtube,
            Publicacion.estado_metricas != EstadoMetricasEnum.fijo,
            Publicacion.fecha_publicacion >= inicio_2026,
        )
        .order_by(Publicacion.fecha_publicacion.asc())
        .all()
    )

    if not pubs:
        log.info(f"[{medio.slug}] update_weekly_youtube: sin publicaciones 2026+")
        return 0

    log.info(f"[{medio.slug}] update_weekly_youtube: {len(pubs)} publicaciones a procesar")
    actualizadas = 0

    for pub in pubs:
        if not pub.id_externo:
            continue
        try:
            pub_date = pub.fecha_publicacion.date() if hasattr(pub.fecha_publicacion, "date") else pub.fecha_publicacion
            todas_semanas = semanas_entre(pub_date, hoy)

            # Semanas ya snapshoteadas
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
                        clicks=0, clicks_diff=0,
                        fuente="api",
                        reach_pagado=pub.reach_pagado or 0,
                        inversion_pagada=pub.inversion_pagada,
                    ))
                    db.flush()

                log.info(f"[{medio.slug}] {semana} | {pub.id_externo} | views={diff_views} (acum={acumulado_reach})")

            pub.reach    = acumulado_reach
            pub.likes    = acumulado_likes
            pub.comments = acumulado_comments
            pub.ultima_actualizacion = datetime.now(timezone.utc)
            pub.estado_metricas = EstadoMetricasEnum.actualizado
            actualizadas += 1

        except Exception as ex:
            log.error(f"[{medio.slug}] Error en update_weekly_youtube para {pub.id_externo}: {ex}")
            pub.estado_metricas = EstadoMetricasEnum.error

    db.commit()
    log.info(f"[{medio.slug}] update_weekly_youtube completado: {actualizadas}/{len(pubs)}")
    return actualizadas


def _get_analytics_views(yt_anal, video_id: str, fecha_pub: datetime) -> Optional[int]:
    """
    Consulta YouTube Analytics API para obtener views del vídeo desde su
    fecha de publicación hasta hoy. Solo funciona para el canal autenticado.
    Nota: 'impressions' no está disponible por vídeo en la Analytics API v2;
    se usa 'views' como métrica de alcance.
    """
    try:
        start = fecha_pub.strftime("%Y-%m-%d")
        end   = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        resp = yt_anal.reports().query(
            ids="channel==MINE",
            startDate=start,
            endDate=end,
            metrics="views,estimatedMinutesWatched",
            dimensions="video",
            filters=f"video=={video_id}",
        ).execute()
        rows = resp.get("rows", [])
        if rows:
            return int(rows[0][1])  # [video_id, views, estimatedMinutesWatched]
        return None
    except Exception as ex:
        log.warning(f"[YouTube Analytics] Sin datos para {video_id}: {ex}")
        return None


# ── Backfill de etiquetas ─────────────────────────────────────────────────────

def update_etiquetas(db: Session, medio: Medio, publicaciones: list[Publicacion]) -> int:
    """
    Obtiene las playlists de YouTube y actualiza el campo etiquetas para
    las publicaciones dadas. Construye el mapa de playlists una sola vez.
    """
    creds = _build_credentials(db, medio.id)
    if not creds:
        log.warning(f"[{medio.slug}] Sin credenciales YouTube para update_etiquetas")
        return 0

    try:
        yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    except Exception as ex:
        log.error(f"[{medio.slug}] Error construyendo cliente YouTube: {ex}")
        return 0

    playlists_map = _get_playlists_map(yt)
    actualizadas = 0
    for pub in publicaciones:
        if not pub.id_externo:
            continue
        pl_titles = playlists_map.get(pub.id_externo, [])
        pub.etiquetas = json.dumps(pl_titles, ensure_ascii=False) if pl_titles else None
        actualizadas += 1

    db.commit()
    log.info(f"[{medio.slug}] YouTube etiquetas actualizadas: {actualizadas}/{len(publicaciones)}")
    return actualizadas
