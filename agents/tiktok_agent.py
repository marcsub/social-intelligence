"""
agents/tiktok_agent.py
Agente TikTok: detecta vídeos del perfil propio via TikTok Open Platform API v2.
Token: OAuth 2.0 access_token (24h) + refresh_token (365 días) con refresh automático.

Métricas disponibles via POST /v2/video/list/:
  view_count    → reach (proxy, equivalente a YouTube views)
  like_count    → likes
  comment_count → comments
  share_count   → shares

Para obtener los tokens iniciales:
    python scripts/authorize_tiktok.py --slug roadrunningreview
"""
import logging
import json
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.orm import Session

from core.brand_id_agent import identify
from core.crypto import decrypt_token, encrypt_token
from core.settings import get_settings
from models.database import (
    Medio, Publicacion, TokenCanal, HistorialMetricas,
    CanalEnum, TipoEnum, EstadoMetricasEnum, EstadoMarcaEnum
)
from utils.semanas import get_semana_iso, get_rango_semana

log = logging.getLogger(__name__)
settings = get_settings()

BASE_URL  = "https://open.tiktokapis.com/v2"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"

# Campos que pedimos a la API de vídeos
VIDEO_FIELDS = (
    "id,title,create_time,cover_image_url,share_url,"
    "video_description,duration,view_count,like_count,"
    "comment_count,share_count"
)

MAX_PER_PAGE = 20  # máximo permitido por TikTok API


# ── Token helpers ─────────────────────────────────────────────────────────────

def _get_tok(db: Session, medio_id: int, clave: str) -> Optional[str]:
    t = db.query(TokenCanal).filter(
        TokenCanal.medio_id == medio_id,
        TokenCanal.canal == "tiktok",
        TokenCanal.clave == clave,
    ).first()
    return decrypt_token(t.valor_cifrado, settings.jwt_secret) if t else None


def _save_tok(db: Session, medio_id: int, clave: str, valor: str):
    encrypted = encrypt_token(valor, settings.jwt_secret)
    t = db.query(TokenCanal).filter(
        TokenCanal.medio_id == medio_id,
        TokenCanal.canal == "tiktok",
        TokenCanal.clave == clave,
    ).first()
    if t:
        t.valor_cifrado = encrypted
    else:
        db.add(TokenCanal(
            medio_id=medio_id,
            canal="tiktok",
            clave=clave,
            valor_cifrado=encrypted,
        ))
    db.commit()


def _refresh_access_token(db: Session, medio_id: int) -> Optional[str]:
    """
    Renueva el access_token usando el refresh_token.
    TikTok access_token expira en 24h; refresh_token en 365 días.
    Devuelve el nuevo access_token o None si falla.
    """
    client_key    = _get_tok(db, medio_id, "client_key")
    client_secret = _get_tok(db, medio_id, "client_secret")
    refresh_token = _get_tok(db, medio_id, "refresh_token")

    if not all([client_key, client_secret, refresh_token]):
        log.error("[tiktok] Faltan client_key, client_secret o refresh_token para renovar token")
        return None

    data = urllib.parse.urlencode({
        "client_key":    client_key,
        "client_secret": client_secret,
        "grant_type":    "refresh_token",
        "refresh_token": refresh_token,
    }).encode()

    req = urllib.request.Request(TOKEN_URL, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("Cache-Control", "no-cache")

    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            resp = json.loads(r.read())
    except Exception as ex:
        log.error(f"[tiktok] Error renovando token: {ex}")
        return None

    new_access  = resp.get("access_token")
    new_refresh = resp.get("refresh_token")

    if not new_access:
        log.error(f"[tiktok] Respuesta refresh sin access_token: {resp}")
        return None

    _save_tok(db, medio_id, "access_token", new_access)
    if new_refresh:
        _save_tok(db, medio_id, "refresh_token", new_refresh)

    log.info("[tiktok] access_token renovado correctamente")
    return new_access


def _get_valid_token(db: Session, medio_id: int) -> Optional[str]:
    """
    Devuelve un access_token válido. Si la llamada API falla por 401/token expirado,
    el agente debe llamar a _refresh_access_token() y reintentar.
    Aquí simplemente leemos lo que hay en DB.
    """
    return _get_tok(db, medio_id, "access_token")


# ── API helpers ───────────────────────────────────────────────────────────────

def _api_post(path: str, token: str, payload: dict, fields: str = None) -> dict:
    """
    POST a TikTok Open Platform API v2.
    `fields` va como query param en la URL; el resto del payload en el body JSON.
    """
    url = BASE_URL + path
    if fields:
        url += "?" + urllib.parse.urlencode({"fields": fields})
    body = json.dumps(payload).encode("utf-8")
    req  = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json; charset=UTF-8")

    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def _fetch_videos(db: Session, medio_id: int, token: str, cursor: int = 0) -> dict:
    """
    Llama a /v2/video/list/ con paginación.
    Devuelve el bloque 'data' de la respuesta o {} si hay error.
    Reintenta una vez con token renovado si recibe 401.
    """
    payload = {
        "max_count": MAX_PER_PAGE,
        "cursor":    cursor,
    }

    for attempt in range(2):
        try:
            resp = _api_post("/video/list/", token, payload, fields=VIDEO_FIELDS)
            err  = resp.get("error", {})
            code = err.get("code", "ok")

            if code == "ok":
                return resp.get("data", {})

            # Token expirado → renovar y reintentar una vez
            if code in ("access_token_invalid", "token_expired") and attempt == 0:
                log.warning("[tiktok] Token expirado, renovando...")
                new_token = _refresh_access_token(db, medio_id)
                if new_token:
                    token   = new_token
                    payload = payload  # mismo payload
                    continue
                return {}

            log.error(f"[tiktok] Error API: {code} — {err.get('message', '')}")
            return {}

        except urllib.error.HTTPError as ex:
            if ex.code == 401 and attempt == 0:
                log.warning("[tiktok] 401 recibido, renovando token...")
                new_token = _refresh_access_token(db, medio_id)
                if new_token:
                    token = new_token
                    continue
            log.error(f"[tiktok] HTTP {ex.code}: {ex.read().decode()}")
            return {}
        except Exception as ex:
            log.error(f"[tiktok] Error en _fetch_videos: {ex}")
            return {}

    return {}


def _iter_all_videos(db: Session, medio: Medio, token: str):
    """
    Generador que pagina todos los vídeos del perfil TikTok.
    Yields: dict con los datos de cada vídeo.
    """
    cursor   = 0
    has_more = True

    while has_more:
        data = _fetch_videos(db, medio.id, token, cursor)
        if not data:
            break

        for video in data.get("videos", []):
            yield video

        has_more = data.get("has_more", False)
        cursor   = data.get("cursor", 0)

        if not has_more:
            break


# ── Conversión de datos de la API ─────────────────────────────────────────────

def _parse_video(video: dict, medio: Medio, db: Session) -> Optional[Publicacion]:
    """
    Convierte un dict de vídeo TikTok en un objeto Publicacion (sin guardar).
    Devuelve None si faltan datos esenciales.
    """
    video_id = video.get("id")
    if not video_id:
        return None

    # URL canónica del vídeo
    share_url = video.get("share_url") or f"https://www.tiktok.com/@{medio.slug}/video/{video_id}"

    # Timestamp de publicación (Unix timestamp entero)
    create_time = video.get("create_time")
    if create_time:
        fecha = datetime.fromtimestamp(int(create_time), tz=timezone.utc)
    else:
        fecha = datetime.now(timezone.utc)

    # Texto del vídeo (título o descripción)
    titulo = (video.get("title") or video.get("video_description") or "").strip()

    # Métricas
    reach    = int(video.get("view_count",    0) or 0)
    likes    = int(video.get("like_count",    0) or 0)
    comments = int(video.get("comment_count", 0) or 0)
    shares   = int(video.get("share_count",   0) or 0)

    # Identificar marca
    brand = identify(medio_id=medio.id, db=db, caption=titulo, hashtags=[], url=share_url)
    estado_marca = (
        EstadoMarcaEnum.estimated if brand.marca_id and brand.confianza >= 80
        else EstadoMarcaEnum.to_review
    )

    estado_metricas = EstadoMetricasEnum.actualizado if reach > 0 else EstadoMetricasEnum.pendiente

    pub = Publicacion(
        medio_id             = medio.id,
        canal                = CanalEnum.tiktok,
        tipo                 = TipoEnum.video,
        id_externo           = video_id,
        url                  = share_url,
        titulo               = titulo[:500] if titulo else None,
        texto                = titulo[:2000] if titulo else None,
        fecha_publicacion    = fecha,
        reach                = reach,
        likes                = likes,
        comments             = comments,
        shares               = shares,
        marca_id             = brand.marca_id,
        agencia_id           = brand.agencia_id,
        confianza_marca      = brand.confianza if brand.confianza > 0 else None,
        estado_marca         = estado_marca,
        estado_metricas      = estado_metricas,
        ultima_actualizacion = datetime.now(timezone.utc),
    )
    return pub


# ── Interfaz pública del agente ───────────────────────────────────────────────

def detect_new(db: Session, medio: Medio, checkpoint: Optional[datetime]) -> list[Publicacion]:
    """
    Detecta vídeos TikTok nuevos (posteriores al checkpoint) y los inserta en DB.
    Devuelve la lista de Publicacion insertadas.
    """
    token = _get_valid_token(db, medio.id)
    if not token:
        log.error(f"[{medio.slug}/tiktok] No hay access_token disponible. "
                  "Ejecuta: python scripts/authorize_tiktok.py --slug " + medio.slug)
        return []

    nuevas = []
    for video in _iter_all_videos(db, medio, token):
        video_id = video.get("id")
        if not video_id:
            continue

        # Ya existe en DB
        existe = db.query(Publicacion).filter(
            Publicacion.medio_id    == medio.id,
            Publicacion.canal       == CanalEnum.tiktok,
            Publicacion.id_externo == video_id,
        ).first()
        if existe:
            continue

        # Filtrar por checkpoint (si existe)
        create_time = video.get("create_time")
        if checkpoint and create_time:
            fecha = datetime.fromtimestamp(int(create_time), tz=timezone.utc)
            if fecha <= checkpoint:
                continue

        pub = _parse_video(video, medio, db)
        if pub:
            db.add(pub)
            db.flush()
            nuevas.append(pub)
            log.info(f"[{medio.slug}/tiktok] Nueva: {pub.url} ({pub.reach} views)")

    if nuevas:
        db.commit()
        log.info(f"[{medio.slug}/tiktok] {len(nuevas)} vídeos nuevos insertados")

    return nuevas


def update_metrics(db: Session, medio: Medio, publicaciones: list[Publicacion]) -> int:
    """
    Actualiza las métricas de una lista de publicaciones TikTok.
    TikTok v2 no tiene endpoint individual de métricas; usamos video/list/ completo
    y cruzamos por id_externo.
    Devuelve el número de publicaciones actualizadas.
    """
    token = _get_valid_token(db, medio.id)
    if not token:
        log.error(f"[{medio.slug}/tiktok] No hay access_token para update_metrics")
        return 0

    # Construir mapa id_externo → Publicacion
    id_map = {p.id_externo: p for p in publicaciones if p.id_externo}
    if not id_map:
        return 0

    actualizadas = 0
    for video in _iter_all_videos(db, medio, token):
        video_id = video.get("id")
        if video_id not in id_map:
            continue

        pub = id_map[video_id]
        pub.reach        = int(video.get("view_count",    0) or 0)
        pub.likes        = int(video.get("like_count",    0) or 0)
        pub.comments     = int(video.get("comment_count", 0) or 0)
        pub.shares       = int(video.get("share_count",   0) or 0)
        pub.thumbnail_url = video.get("cover_image_url") or pub.thumbnail_url

        if pub.reach > 0:
            pub.estado_metricas = EstadoMetricasEnum.actualizado
        pub.ultima_actualizacion = datetime.now(timezone.utc)
        actualizadas += 1

    if actualizadas:
        db.commit()
        log.info(f"[{medio.slug}/tiktok] {actualizadas} métricas actualizadas")

    return actualizadas


def snapshot_weekly(db: Session, medio: Medio) -> int:
    """
    Snapshot semanal ISO: guarda en historial_metricas el reach actual de cada
    publicación TikTok. Sigue el mismo patrón que instagram_agent.snapshot_weekly.
    Devuelve el número de snapshots guardados.
    """
    from datetime import date as _date
    semana = get_semana_iso(_date.today())

    pubs = db.query(Publicacion).filter(
        Publicacion.medio_id == medio.id,
        Publicacion.canal    == CanalEnum.tiktok,
        Publicacion.estado_metricas.in_([
            EstadoMetricasEnum.actualizado,
            EstadoMetricasEnum.pendiente,
        ]),
    ).all()

    if not pubs:
        return 0

    guardados = 0
    for pub in pubs:
        ya_existe = db.query(HistorialMetricas).filter(
            HistorialMetricas.publicacion_id == pub.id,
            HistorialMetricas.semana         == semana,
        ).first()
        if ya_existe:
            continue

        # Calcular diferencia respecto al último snapshot
        ultimo = (
            db.query(HistorialMetricas)
            .filter(HistorialMetricas.publicacion_id == pub.id)
            .order_by(HistorialMetricas.fecha_snapshot.desc())
            .first()
        )
        reach_actual = pub.reach or 0
        reach_diff   = reach_actual - (ultimo.reach_total or 0) if ultimo else reach_actual

        snap = HistorialMetricas(
            publicacion_id = pub.id,
            semana         = semana,
            reach_total    = reach_actual,
            reach_diff     = max(0, reach_diff),
            likes          = pub.likes or 0,
            shares         = pub.shares or 0,
            comentarios    = pub.comments or 0,
            fecha_snapshot = datetime.now(timezone.utc),
        )
        db.add(snap)
        guardados += 1

    if guardados:
        db.commit()
        log.info(f"[{medio.slug}/tiktok] Snapshot semanal {semana}: {guardados} registros")

    return guardados
