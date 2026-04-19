"""
agents/x_agent.py
Agente X (Twitter): detecta tweets del perfil propio via Twitter API v2.
Auth: Bearer Token (App-only) para lectura de tweets públicos.

Métricas disponibles en public_metrics:
  impression_count → reach
  like_count       → likes
  retweet_count    → shares (incluye retweets)
  reply_count      → comments
  quote_count      → incluido en shares

Rate limits (Free tier):
  GET /2/users/by/username/:username  → 15 req/15min
  GET /2/users/:id/tweets             → 15 req/15min (app-only)
  GET /2/tweets/:id                   → 15 req/15min (app-only)

Para añadir tokens en DB:
    bearer_token, api_key, api_secret, username
    (+ oauth2_client_id, oauth2_client_secret para futura autenticación de usuario)
"""
import logging
import re
import json
import time
import urllib.request
import urllib.parse
import urllib.error
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
from utils.semanas import get_semana_iso

log = logging.getLogger(__name__)
settings = get_settings()

BASE_URL        = "https://api.twitter.com/2"
MAX_RESULTS     = 100   # máximo permitido por el endpoint de timeline
MAX_PAGES       = 20    # límite de paginación para evitar loops infinitos
START_TIME_DEFAULT = "2026-01-01T00:00:00Z"


# ── Token helpers ─────────────────────────────────────────────────────────────

def _get_tok(db: Session, medio_id: int, clave: str) -> Optional[str]:
    t = db.query(TokenCanal).filter(
        TokenCanal.medio_id == medio_id,
        TokenCanal.canal    == "x",
        TokenCanal.clave    == clave,
    ).first()
    return decrypt_token(t.valor_cifrado, settings.jwt_secret) if t else None


# ── API helpers ───────────────────────────────────────────────────────────────

def _api_get(path: str, bearer_token: str, params: dict = None) -> dict:
    """
    GET a Twitter API v2.
    Gestiona rate limit (429) con backoff exponencial: 15s, 30s, 60s.
    Lanza RuntimeError si hay error de la API o HTTP.
    """
    url = BASE_URL + path
    if params:
        url += "?" + urllib.parse.urlencode(params)

    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {bearer_token}")
    req.add_header("User-Agent", "social-intelligence/1.0")

    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read())
            if "errors" in data and "data" not in data:
                raise RuntimeError(data["errors"])
            return data
        except urllib.error.HTTPError as ex:
            if ex.code == 429:
                wait = 15 * (2 ** attempt)
                log.warning(f"[x] Rate limit 429, esperando {wait}s (intento {attempt+1}/3)")
                time.sleep(wait)
                continue
            body = ""
            try:
                body = ex.read().decode()
            except Exception:
                pass
            raise RuntimeError(f"HTTP {ex.code}: {body}")
        except urllib.error.URLError as ex:
            raise RuntimeError(f"URLError: {ex.reason}")

    raise RuntimeError("[x] Rate limit persistente tras 3 reintentos")


def _get_user_id(db: Session, bearer_token: str, username: str, medio_id: int) -> Optional[str]:
    """
    Resuelve el user_id de Twitter a partir del username.
    El user_id se cachea en tokens_canal (clave='user_id') para evitar llamadas repetidas.
    """
    from core.crypto import encrypt_token

    # Intentar leer del caché
    cached = _get_tok(db, medio_id, "user_id")
    if cached:
        return cached

    try:
        data = _api_get(
            f"/users/by/username/{username}",
            bearer_token,
            {"user.fields": "id,name,username"},
        )
        user_id = data.get("data", {}).get("id")
        if user_id:
            # Cachear en DB
            encrypted = encrypt_token(user_id, settings.jwt_secret)
            t = db.query(TokenCanal).filter(
                TokenCanal.medio_id == medio_id,
                TokenCanal.canal    == "x",
                TokenCanal.clave    == "user_id",
            ).first()
            if t:
                t.valor_cifrado = encrypted
            else:
                db.add(TokenCanal(
                    medio_id=medio_id, canal="x",
                    clave="user_id", valor_cifrado=encrypted,
                ))
            db.commit()
            log.info(f"[x] user_id resuelto para @{username}: {user_id}")
        return user_id
    except Exception as ex:
        log.error(f"[x] Error resolviendo user_id para @{username}: {ex}")
        return None


def _fetch_tweets_page(bearer_token: str, user_id: str, params: dict) -> dict:
    """
    Llama a GET /2/users/:id/tweets con los params dados.
    Devuelve el dict completo de la respuesta o {} si hay error.
    """
    try:
        return _api_get(f"/users/{user_id}/tweets", bearer_token, params)
    except Exception as ex:
        log.error(f"[x] Error en /users/{user_id}/tweets: {ex}")
        return {}


def _build_tweet_params(checkpoint: Optional[datetime], pagination_token: str = None) -> dict:
    params = {
        "max_results":   MAX_RESULTS,
        "tweet.fields":  "created_at,public_metrics,entities,attachments,possibly_sensitive",
        "expansions":    "attachments.media_keys",
        "media.fields":  "type",
    }
    if checkpoint:
        ts = checkpoint.strftime("%Y-%m-%dT%H:%M:%SZ")
        params["start_time"] = ts
    else:
        params["start_time"] = START_TIME_DEFAULT

    if pagination_token:
        params["pagination_token"] = pagination_token

    return params


# ── Conversión de datos de la API ─────────────────────────────────────────────

def _parse_tweet(tweet: dict, medio: Medio, db: Session, media_map: dict) -> Optional[Publicacion]:
    """
    Convierte un dict de tweet en un objeto Publicacion (sin guardar).
    Devuelve None si faltan datos esenciales.
    """
    tweet_id = tweet.get("id")
    if not tweet_id:
        return None

    # URL canónica
    username = _get_tok(db, medio.id, "username") or medio.slug
    url = f"https://x.com/{username}/status/{tweet_id}"

    # Fecha
    created_at = tweet.get("created_at", "")
    if created_at:
        try:
            fecha = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except ValueError:
            fecha = datetime.now(timezone.utc)
    else:
        fecha = datetime.now(timezone.utc)

    # Texto
    texto = (tweet.get("text") or "").strip()

    # Hashtags de entities
    entities = tweet.get("entities") or {}
    hashtags_raw = entities.get("hashtags") or []
    hashtags = [h.get("tag", "") for h in hashtags_raw if h.get("tag")]
    etiquetas_json = json.dumps([f"#{h}" for h in hashtags], ensure_ascii=False) if hashtags else None

    # Métricas
    pm       = tweet.get("public_metrics") or {}
    reach    = int(pm.get("impression_count", 0) or 0)
    likes    = int(pm.get("like_count",        0) or 0)
    shares   = int(pm.get("retweet_count",     0) or 0) + int(pm.get("quote_count", 0) or 0)
    comments = int(pm.get("reply_count",       0) or 0)

    # Tipo: video si tiene media de tipo video, post en caso contrario
    attachments = tweet.get("attachments") or {}
    media_keys  = attachments.get("media_keys") or []
    tipo = TipoEnum.post
    for mk in media_keys:
        media_type = media_map.get(mk, {}).get("type", "")
        if media_type == "video":
            tipo = TipoEnum.video
            break

    # Brand ID
    texto_limpio = re.sub(r"[#@]\w+", "", texto).strip()
    brand = identify(
        medio_id=medio.id,
        db=db,
        caption=texto_limpio,
        hashtags=" ".join(hashtags),
        url=url,
    )

    config    = medio.config
    umbral    = config.umbral_confianza_marca if config else 80
    estado_metricas = (
        EstadoMetricasEnum.pendiente
        if brand.confianza >= umbral
        else EstadoMetricasEnum.revisar
    )
    estado_marca = (
        EstadoMarcaEnum.estimated
        if brand.marca_id and brand.confianza >= 80
        else EstadoMarcaEnum.to_review
    )

    pub = Publicacion(
        medio_id             = medio.id,
        canal                = CanalEnum.x,
        tipo                 = tipo,
        id_externo           = tweet_id,
        url                  = url,
        titulo               = None,
        texto                = texto[:2000] if texto else None,
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
        notas                = brand.razonamiento if estado_metricas == EstadoMetricasEnum.revisar else None,
        etiquetas            = etiquetas_json,
        ultima_actualizacion = datetime.now(timezone.utc),
    )
    return pub


# ── Interfaz pública del agente ───────────────────────────────────────────────

def detect_new(db: Session, medio: Medio, checkpoint: Optional[datetime]) -> list[Publicacion]:
    """
    Detecta tweets nuevos (posteriores al checkpoint) y los inserta en DB.
    Devuelve la lista de Publicacion insertadas.
    """
    bearer_token = _get_tok(db, medio.id, "bearer_token")
    username     = _get_tok(db, medio.id, "username")

    if not bearer_token or not username:
        log.warning(f"[{medio.slug}/x] Faltan bearer_token o username. "
                    "Guarda canal='x' clave='bearer_token' y 'username' en tokens_canal.")
        return []

    if checkpoint and checkpoint.tzinfo is None:
        checkpoint = checkpoint.replace(tzinfo=timezone.utc)

    user_id = _get_user_id(db, bearer_token, username, medio.id)
    if not user_id:
        log.error(f"[{medio.slug}/x] No se pudo resolver user_id para @{username}")
        return []

    nuevas          = []
    pagination_token = None
    page            = 0

    while page < MAX_PAGES:
        params = _build_tweet_params(checkpoint, pagination_token)
        resp   = _fetch_tweets_page(bearer_token, user_id, params)

        if not resp:
            break

        tweets = resp.get("data") or []
        if not tweets:
            break

        # Construir mapa media_key → media para detectar tipo video
        includes   = resp.get("includes") or {}
        media_list = includes.get("media") or []
        media_map  = {m["media_key"]: m for m in media_list if m.get("media_key")}

        for tweet in tweets:
            tweet_id = tweet.get("id")
            if not tweet_id:
                continue

            # Comprobar duplicado
            existe = db.query(Publicacion).filter(
                Publicacion.medio_id   == medio.id,
                Publicacion.canal      == CanalEnum.x,
                Publicacion.id_externo == tweet_id,
            ).first()
            if existe:
                continue

            pub = _parse_tweet(tweet, medio, db, media_map)
            if pub:
                db.add(pub)
                db.flush()
                nuevas.append(pub)
                log.info(
                    f"[{medio.slug}/x] Nuevo tweet: {pub.url} "
                    f"— marca: {pub.marca_id} ({pub.confianza_marca}%)"
                )

        meta  = resp.get("meta") or {}
        pagination_token = meta.get("next_token")
        if not pagination_token:
            break

        page += 1

    if nuevas:
        db.commit()
        log.info(f"[{medio.slug}/x] {len(nuevas)} tweets nuevos insertados")

    return nuevas


def update_metrics(db: Session, medio: Medio, publicaciones: list[Publicacion]) -> int:
    """
    Actualiza métricas de tweets via GET /2/tweets/:id.
    Devuelve el número de publicaciones actualizadas.
    """
    if not publicaciones:
        return 0

    bearer_token = _get_tok(db, medio.id, "bearer_token")
    if not bearer_token:
        log.warning(f"[{medio.slug}/x] Sin bearer_token para update_metrics")
        return 0

    # Actualización por lotes de hasta 100 IDs (endpoint /2/tweets soporta hasta 100)
    ids = [p.id_externo for p in publicaciones if p.id_externo]
    if not ids:
        return 0

    id_map      = {p.id_externo: p for p in publicaciones if p.id_externo}
    actualizadas = 0

    BATCH_SIZE = 100
    for i in range(0, len(ids), BATCH_SIZE):
        batch = ids[i:i + BATCH_SIZE]
        try:
            resp = _api_get(
                "/tweets",
                bearer_token,
                {
                    "ids":           ",".join(batch),
                    "tweet.fields":  "public_metrics",
                },
            )
        except Exception as ex:
            log.error(f"[{medio.slug}/x] Error en /tweets batch: {ex}")
            continue

        for tweet in resp.get("data") or []:
            tweet_id = tweet.get("id")
            if tweet_id not in id_map:
                continue
            pub = id_map[tweet_id]
            pm  = tweet.get("public_metrics") or {}

            pub.reach    = int(pm.get("impression_count", pub.reach or 0) or pub.reach or 0)
            pub.likes    = int(pm.get("like_count",    0) or 0)
            pub.shares   = int(pm.get("retweet_count", 0) or 0) + int(pm.get("quote_count", 0) or 0)
            pub.comments = int(pm.get("reply_count",   0) or 0)
            pub.ultima_actualizacion = datetime.now(timezone.utc)
            pub.estado_metricas      = EstadoMetricasEnum.actualizado
            actualizadas += 1

    if actualizadas:
        db.commit()
        log.info(f"[{medio.slug}/x] {actualizadas} métricas actualizadas")

    return actualizadas


def snapshot_weekly(db: Session, medio: Medio) -> int:
    """
    Snapshot semanal ISO: guarda en historial_metricas el estado actual de cada
    tweet activo. Calcula diferencial vs semana anterior.
    Se ejecuta los lunes a las 02:30 UTC.
    """
    from datetime import date as _date

    semana_actual = get_semana_iso(_date.today())
    inicio_2026   = datetime(2026, 1, 1, tzinfo=timezone.utc)

    pubs = (
        db.query(Publicacion)
        .filter(
            Publicacion.medio_id == medio.id,
            Publicacion.canal    == CanalEnum.x,
            Publicacion.estado_metricas.in_([
                EstadoMetricasEnum.pendiente,
                EstadoMetricasEnum.actualizado,
            ]),
            Publicacion.fecha_publicacion >= inicio_2026,
        )
        .all()
    )

    if not pubs:
        log.info(f"[{medio.slug}/x] snapshot_weekly: sin publicaciones 2026+")
        return 0

    # Actualizar métricas antes del snapshot
    update_metrics(db, medio, pubs)

    guardados = 0
    for pub in pubs:
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
        reach_actual    = pub.reach    or 0
        likes_actual    = pub.likes    or 0
        shares_actual   = pub.shares   or 0
        comments_actual = pub.comments or 0

        reach_diff    = max(0, reach_actual    - (prev.reach    if prev else 0))
        likes_diff    = max(0, likes_actual    - (prev.likes    if prev else 0))
        shares_diff   = max(0, shares_actual   - (prev.shares   if prev else 0))
        comments_diff = max(0, comments_actual - (prev.comments if prev else 0))

        existing = (
            db.query(HistorialMetricas)
            .filter(
                HistorialMetricas.publicacion_id == pub.id,
                HistorialMetricas.semana_iso     == semana_actual,
            )
            .first()
        )
        if existing:
            existing.reach = reach_actual; existing.reach_diff = reach_diff
            existing.likes = likes_actual; existing.likes_diff = likes_diff
            existing.shares = shares_actual; existing.shares_diff = shares_diff
            existing.comments = comments_actual; existing.comments_diff = comments_diff
            existing.fecha_snapshot = datetime.now(timezone.utc)
        else:
            db.add(HistorialMetricas(
                publicacion_id=pub.id,
                semana_iso=semana_actual,
                reach=reach_actual,    reach_diff=reach_diff,
                likes=likes_actual,    likes_diff=likes_diff,
                shares=shares_actual,  shares_diff=shares_diff,
                comments=comments_actual, comments_diff=comments_diff,
                clicks=0, clicks_diff=0,
                fuente="api",
                reach_pagado=pub.reach_pagado or 0,
                inversion_pagada=pub.inversion_pagada,
            ))
        guardados += 1

    if guardados:
        db.commit()
        log.info(f"[{medio.slug}/x] Snapshot semanal {semana_actual}: {guardados} registros")

    return guardados
