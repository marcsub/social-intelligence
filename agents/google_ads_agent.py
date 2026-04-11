"""
agents/google_ads_agent.py
Sincronización de métricas de promoción pagada via Google Ads API REST v20.

ESTADO ACTUAL: Requiere credenciales separadas de YouTube Data API.

Para configurar:
  1. En Google Ads: Herramientas → Centro de API → Obtener developer_token
  2. Anotar customer_id (ID de cuenta Google Ads, sin guiones, ej: 1234567890)
  3. Ejecutar el script de autorización OAuth:
       python scripts/authorize_google_ads.py --slug roadrunningreview
     Este script genera un access_token con scope adwords y lo guarda en DB.
  4. Guardar en panel web (Configuración → Tokens API → google_ads):
       - developer_token
       - customer_id
  5. El access_token lo gestiona authorize_google_ads.py directamente en DB.

Nota sobre el token YouTube existente:
  El OAuth de YouTube Data API NO tiene scope adwords — son flujos separados.
  El scope necesario es: https://www.googleapis.com/auth/adwords
"""
import logging
import json
import urllib.request
import urllib.parse
import urllib.error
from decimal import Decimal
from datetime import datetime, timezone

log = logging.getLogger(__name__)

GOOGLE_ADS_BASE = "https://googleads.googleapis.com/v20"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_token(db, medio_id: int, canal: str, clave: str):
    from models.database import TokenCanal
    from core.crypto import decrypt_token
    from core.settings import get_settings
    t = db.query(TokenCanal).filter(
        TokenCanal.medio_id == medio_id,
        TokenCanal.canal == canal,
        TokenCanal.clave == clave,
    ).first()
    return decrypt_token(t.valor_cifrado, get_settings().jwt_secret) if t else None


def _save_token(db, medio_id: int, canal: str, clave: str, valor: str):
    from models.database import TokenCanal
    from core.crypto import encrypt_token
    from core.settings import get_settings
    secret = get_settings().jwt_secret
    t = db.query(TokenCanal).filter(
        TokenCanal.medio_id == medio_id,
        TokenCanal.canal == canal,
        TokenCanal.clave == clave,
    ).first()
    if t:
        t.valor_cifrado = encrypt_token(valor, secret)
    else:
        db.add(TokenCanal(medio_id=medio_id, canal=canal, clave=clave,
                          valor_cifrado=encrypt_token(valor, secret)))
    db.commit()


def _refresh_access_token(db, medio_id: int) -> str | None:
    """
    Refresca el access_token usando el refresh_token y lo guarda en DB.
    Retorna el nuevo access_token o None si falla.
    """
    refresh_token = _get_token(db, medio_id, "google_ads", "refresh_token")
    client_id     = _get_token(db, medio_id, "youtube", "client_id")
    client_secret = _get_token(db, medio_id, "youtube", "client_secret")

    if not refresh_token or not client_id or not client_secret:
        return None

    data = urllib.parse.urlencode({
        "grant_type":    "refresh_token",
        "refresh_token": refresh_token,
        "client_id":     client_id,
        "client_secret": client_secret,
    }).encode()
    req = urllib.request.Request(GOOGLE_TOKEN_URL, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            tokens = json.loads(r.read())
        new_token = tokens.get("access_token")
        if new_token:
            _save_token(db, medio_id, "google_ads", "access_token", new_token)
            log.info(f"google_ads: access_token refrescado correctamente")
            return new_token
    except Exception as ex:
        log.warning(f"google_ads: error refrescando access_token: {ex}")
    return None


def _gaql_search(
    customer_id: str, developer_token: str, access_token: str, query: str,
    db=None, medio_id: int = None,
) -> dict:
    """
    Ejecuta una query GAQL contra la API REST de Google Ads.
    Si recibe 401 y hay db/medio_id, refresca el access_token y reintenta.
    """
    url = f"{GOOGLE_ADS_BASE}/customers/{customer_id}/googleAds:search"
    body = json.dumps({"query": query}).encode()

    def _do_request(token):
        req = urllib.request.Request(
            url, data=body,
            headers={
                "Authorization": f"Bearer {token}",
                "developer-token": developer_token,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())

    try:
        return _do_request(access_token)
    except urllib.error.HTTPError as ex:
        if ex.code == 401 and db is not None and medio_id is not None:
            log.info("google_ads: access_token expirado, refrescando...")
            new_token = _refresh_access_token(db, medio_id)
            if new_token:
                return _do_request(new_token)
        raise


# ── Verificación de acceso ────────────────────────────────────────────────────

def check_access(db, medio_id: int) -> tuple[bool, str]:
    """
    Verifica si Google Ads está configurado y accesible.
    Retorna (ok: bool, mensaje: str).
    """
    developer_token = _get_token(db, medio_id, "google_ads", "developer_token")
    customer_id     = _get_token(db, medio_id, "google_ads", "customer_id")
    access_token    = _get_token(db, medio_id, "google_ads", "access_token")

    if not developer_token or not customer_id or not access_token:
        missing = []
        if not developer_token: missing.append("developer_token")
        if not customer_id:     missing.append("customer_id")
        if not access_token:    missing.append("access_token")
        return False, (
            f"Google Ads no configurado. Faltan: {', '.join(missing)}.\n"
            "Pasos:\n"
            "  1. Obtener developer_token: Google Ads → Herramientas → Centro de API\n"
            "  2. Obtener customer_id: ID de tu cuenta (sin guiones)\n"
            "  3. Ejecutar: python scripts/authorize_google_ads.py --slug <slug>\n"
            "  4. Añadir developer_token y customer_id en panel → Tokens API → google_ads"
        )

    log.info(f"google_ads check_access: customer_id={customer_id[:10]}... dev_token={developer_token[:10]}...")

    # Intentar listar campañas (query mínima para verificar conectividad)
    try:
        result = _gaql_search(
            customer_id, developer_token, access_token,
            "SELECT customer.id, customer.descriptive_name FROM customer LIMIT 1",
            db=db, medio_id=medio_id,
        )
        rows = result.get("results", [])
        name = rows[0]["customer"].get("descriptiveName", "") if rows else ""
        return True, f"Conectado. Cuenta: {name} ({customer_id})"
    except urllib.error.HTTPError as ex:
        body = ex.read().decode()
        log.error(f"google_ads HTTP {ex.code} — error completo:\n{body}")
        return False, f"HTTP {ex.code}: {body}"
    except Exception as ex:
        log.error(f"google_ads error inesperado: {ex}")
        return False, str(ex)


# ── Métricas pagadas por vídeo ────────────────────────────────────────────────

def _fetch_video_metrics_map(
    customer_id: str,
    developer_token: str,
    access_token: str,
    db=None,
    medio_id: int = None,
) -> dict:
    """
    Construye un mapa {youtube_video_id: {"impressions": int, "cost_micros": int}}
    usando dos queries GAQL:
      1. assets YOUTUBE_VIDEO  → asset_resource_name → youtube_video_id
      2. ad_group_ad VIDEO_RESPONSIVE_AD → asset_resource_name + métricas
    """
    # 1. Mapa asset_resource_name → youtube_video_id
    asset_q = (
        "SELECT asset.resource_name, asset.youtube_video_asset.youtube_video_id "
        "FROM asset WHERE asset.type = YOUTUBE_VIDEO LIMIT 1000"
    )
    try:
        asset_data = _gaql_search(
            customer_id, developer_token, access_token, asset_q,
            db=db, medio_id=medio_id,
        )
    except Exception as ex:
        log.warning(f"google_ads: error obteniendo assets YouTube: {ex}")
        return {}

    asset_map: dict[str, str] = {}  # asset_resource_name → youtube_video_id
    for row in asset_data.get("results", []):
        a = row.get("asset", {})
        rn = a.get("resourceName", "")
        yt_id = a.get("youtubeVideoAsset", {}).get("youtubeVideoId", "")
        if rn and yt_id:
            asset_map[rn] = yt_id

    if not asset_map:
        log.warning("google_ads: no se encontraron assets de tipo YOUTUBE_VIDEO")
        return {}

    log.info(f"google_ads: {len(asset_map)} assets YouTube encontrados")

    # 2. Métricas por ad_group_ad VIDEO_RESPONSIVE con sus asset de vídeo
    # Nota: GAQL no permite filtrar métricas numéricas en WHERE — se filtra en Python
    metrics_q = (
        "SELECT ad_group_ad.ad.video_responsive_ad.videos, "
        "metrics.impressions, metrics.cost_micros "
        "FROM ad_group_ad "
        "WHERE segments.date >= '2026-01-01' "
        "AND ad_group_ad.ad.type = VIDEO_RESPONSIVE_AD "
        "LIMIT 1000"
    )
    try:
        metrics_data = _gaql_search(
            customer_id, developer_token, access_token, metrics_q,
            db=db, medio_id=medio_id,
        )
    except Exception as ex:
        log.warning(f"google_ads: error obteniendo métricas ad_group_ad: {ex}")
        return {}

    # 3. Agregar por youtube_video_id
    result: dict[str, dict] = {}
    for row in metrics_data.get("results", []):
        met = row.get("metrics", {})
        impressions = int(met.get("impressions", 0) or 0)
        cost_micros = int(met.get("costMicros", 0) or 0)
        if not impressions and not cost_micros:
            continue
        videos = (
            row.get("adGroupAd", {})
               .get("ad", {})
               .get("videoResponsiveAd", {})
               .get("videos", [])
        )
        for v in videos:
            yt_id = asset_map.get(v.get("asset", ""))
            if not yt_id:
                continue
            if yt_id not in result:
                result[yt_id] = {"impressions": 0, "cost_micros": 0}
            result[yt_id]["impressions"] += impressions
            result[yt_id]["cost_micros"] += cost_micros

    log.info(f"google_ads: métricas encontradas para {len(result)} vídeos YouTube")
    return result


def get_video_paid_metrics(
    video_id: str,
    customer_id: str,
    developer_token: str,
    access_token: str,
    db=None,
    medio_id: int = None,
) -> dict:
    """
    Obtiene impresiones e inversión de un vídeo de YouTube via GAQL.

    Retorna: {"reach_pagado": int, "inversion_pagada": float}
    Los costMicros se convierten a EUR (o la divisa de la cuenta).
    """
    try:
        metrics_map = _fetch_video_metrics_map(
            customer_id, developer_token, access_token, db=db, medio_id=medio_id,
        )
        m = metrics_map.get(video_id, {})
        return {
            "reach_pagado": m.get("impressions", 0),
            "inversion_pagada": round(m.get("cost_micros", 0) / 1_000_000, 2),
        }
    except Exception as ex:
        log.debug(f"google_ads: sin datos para vídeo {video_id}: {ex}")
        return {"reach_pagado": 0, "inversion_pagada": 0.0}


# ── Sync principal ────────────────────────────────────────────────────────────

def sync_paid_metrics(db, medio) -> int:
    """
    Sincroniza métricas pagadas para vídeos YouTube del medio (2026+).

    - Si las credenciales no están configuradas: loguea instrucciones y retorna 0.
    - Si están configuradas: actualiza reach_pagado e inversion_pagada.

    Retorna número de publicaciones actualizadas.
    """
    from models.database import Publicacion, CanalEnum

    developer_token = _get_token(db, medio.id, "google_ads", "developer_token")
    customer_id     = _get_token(db, medio.id, "google_ads", "customer_id")
    access_token    = _get_token(db, medio.id, "google_ads", "access_token")

    if not developer_token or not customer_id or not access_token:
        log.info(
            f"[{medio.slug}] google_ads: credenciales no configuradas. "
            "Ejecuta scripts/authorize_google_ads.py para configurar."
        )
        return 0

    inicio_2026 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    pubs = (
        db.query(Publicacion)
        .filter(
            Publicacion.medio_id == medio.id,
            Publicacion.canal.in_([CanalEnum.youtube, CanalEnum.youtube_short]),
            Publicacion.fecha_publicacion >= inicio_2026,
            Publicacion.id_externo.isnot(None),
        )
        .all()
    )

    if not pubs:
        log.info(f"[{medio.slug}] google_ads: sin vídeos YouTube 2026+ para sincronizar")
        return 0

    # Una sola llamada a la API para obtener todas las métricas de una vez
    metrics_map = _fetch_video_metrics_map(
        customer_id, developer_token, access_token, db=db, medio_id=medio.id,
    )
    if not metrics_map:
        log.info(f"[{medio.slug}] google_ads: no se encontraron métricas pagadas")
        return 0

    actualizadas = 0
    for pub in pubs:
        m = metrics_map.get(pub.id_externo)
        if not m:
            continue
        impressions = m["impressions"]
        inversion = round(m["cost_micros"] / 1_000_000, 2)
        if impressions > 0 or inversion > 0:
            pub.reach_pagado = impressions
            pub.inversion_pagada = Decimal(str(inversion))
            actualizadas += 1
            log.info(
                f"[{medio.slug}] Video {pub.id_externo} ({pub.canal.value}): "
                f"reach_pagado={impressions:,}, inversion={inversion:.2f}€"
            )

    if actualizadas:
        db.commit()

    log.info(
        f"[{medio.slug}] google_ads sync completado: "
        f"{actualizadas}/{len(pubs)} vídeos con datos pagados"
    )
    return actualizadas
