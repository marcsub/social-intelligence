"""
agents/google_ads_agent.py
Sincronización de métricas de promoción pagada via Google Ads API REST v17.

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
import urllib.error
from decimal import Decimal
from datetime import datetime, timezone

log = logging.getLogger(__name__)

GOOGLE_ADS_BASE = "https://googleads.googleapis.com/v17"


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


def _gaql_search(customer_id: str, developer_token: str, access_token: str, query: str) -> dict:
    """Ejecuta una query GAQL contra la API REST de Google Ads."""
    url = f"{GOOGLE_ADS_BASE}/customers/{customer_id}/googleAds:search"
    body = json.dumps({"query": query}).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {access_token}",
            "developer-token": developer_token,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


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

    # Intentar listar campañas (query mínima para verificar conectividad)
    try:
        result = _gaql_search(
            customer_id, developer_token, access_token,
            "SELECT customer.id, customer.descriptive_name FROM customer LIMIT 1"
        )
        rows = result.get("results", [])
        name = rows[0]["customer"].get("descriptiveName", "") if rows else ""
        return True, f"Conectado. Cuenta: {name} ({customer_id})"
    except urllib.error.HTTPError as ex:
        body = ex.read().decode()[:300]
        return False, f"HTTP {ex.code}: {body}"
    except Exception as ex:
        return False, str(ex)


# ── Métricas pagadas por vídeo ────────────────────────────────────────────────

def get_video_paid_metrics(
    video_id: str,
    customer_id: str,
    developer_token: str,
    access_token: str,
) -> dict:
    """
    Obtiene impresiones e inversión de un vídeo de YouTube via GAQL.

    Retorna: {"reach_pagado": int, "inversion_pagada": float}
    Los costMicros se convierten a EUR (o la divisa de la cuenta).
    """
    query = f"""
        SELECT
            metrics.impressions,
            metrics.cost_micros,
            ad_group_ad.ad.video_ad.in_stream.video.resource_name
        FROM ad_group_ad
        WHERE ad_group_ad.ad.video_ad.in_stream.video.resource_name
              LIKE '%{video_id}%'
        AND segments.date DURING ALL_TIME
    """
    try:
        data = _gaql_search(customer_id, developer_token, access_token, query)
        results = data.get("results", [])
        if not results:
            return {"reach_pagado": 0, "inversion_pagada": 0.0}
        total_impressions = sum(
            int(r.get("metrics", {}).get("impressions", 0) or 0)
            for r in results
        )
        total_cost_micros = sum(
            int(r.get("metrics", {}).get("costMicros", 0) or 0)
            for r in results
        )
        inversion = round(total_cost_micros / 1_000_000, 2)
        return {"reach_pagado": total_impressions, "inversion_pagada": inversion}
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

    actualizadas = 0
    for pub in pubs:
        metrics = get_video_paid_metrics(
            pub.id_externo, customer_id, developer_token, access_token
        )
        if metrics["reach_pagado"] > 0 or metrics["inversion_pagada"] > 0:
            pub.reach_pagado = metrics["reach_pagado"]
            pub.inversion_pagada = Decimal(str(metrics["inversion_pagada"]))
            actualizadas += 1
            log.info(
                f"[{medio.slug}] Video {pub.id_externo} ({pub.canal.value}): "
                f"reach_pagado={metrics['reach_pagado']:,}, "
                f"inversion={metrics['inversion_pagada']:.2f}€"
            )

    if actualizadas:
        db.commit()

    log.info(
        f"[{medio.slug}] google_ads sync completado: "
        f"{actualizadas}/{len(pubs)} vídeos con datos pagados"
    )
    return actualizadas
