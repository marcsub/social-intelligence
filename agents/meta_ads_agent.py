"""
agents/meta_ads_agent.py
Sincronización de métricas de promoción pagada via Meta Marketing API v25.0.

ESTADO ACTUAL: Requiere permiso 'ads_read' que aún no está concedido.

Para activar:
  1. Meta Business Suite → Configuración → Aplicaciones → [Tu App]
  2. Añadir producto: Marketing API
  3. Solicitar permiso: ads_read (y opcionalmente ads_management)
  4. Una vez aprobado: el usuario re-autoriza la app (nuevo access_token)
  5. Las funciones de este módulo funcionarán automáticamente sin cambios de código.

Permisos actuales del user token (2026-04-10):
  read_insights, pages_show_list, pages_read_engagement, pages_manage_metadata,
  instagram_basic, instagram_manage_insights, instagram_content_publish,
  business_management, public_profile
  → ads_read: NO disponible
"""
import logging
import json
import urllib.request
import urllib.parse
import urllib.error
from decimal import Decimal
from datetime import datetime, timezone

log = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.facebook.com/v25.0"


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


def _graph_get(path: str, token: str, params: dict = None) -> dict:
    qs = urllib.parse.urlencode(params or {})
    sep = "&" if qs else ""
    url = f"{GRAPH_BASE}{path}?access_token={token}{sep}{qs}"
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read())


# ── Ad account discovery ──────────────────────────────────────────────────────

def _get_ad_accounts(user_token: str) -> list:
    """
    Devuelve la lista de ad accounts accesibles.
    Lanza PermissionError si falta ads_read.
    """
    try:
        data = _graph_get("/me/adaccounts", user_token, {"fields": "id,name,currency"})
        return data.get("data", [])
    except urllib.error.HTTPError as ex:
        body = ex.read().decode()
        if ex.code == 403 or '"code": 10' in body or '"code":10' in body or '"code": 200' in body:
            raise PermissionError("ads_read permission not granted")
        raise


def _resolve_ad_account(db, medio_id: int, user_token: str) -> str | None:
    """
    Obtiene el ad_account_id: primero desde DB (meta_ads.ad_account_id),
    si no está, lo autodetecta via API.
    Retorna None si no hay acceso o no hay cuentas.
    """
    # 1. Buscar en tokens configurados manualmente
    stored = _get_token(db, medio_id, "meta_ads", "ad_account_id")
    if stored:
        return stored.replace("act_", "")

    # 2. Autodetectar via API
    try:
        accounts = _get_ad_accounts(user_token)
        if not accounts:
            log.info("meta_ads: no se encontraron ad accounts asociados al token")
            return None
        account_id = accounts[0]["id"].replace("act_", "")
        name = accounts[0].get("name", "")
        currency = accounts[0].get("currency", "")
        log.info(f"meta_ads: usando ad account '{name}' ({account_id}) [{currency}]")
        return account_id

    except PermissionError:
        log.warning(
            "meta_ads: falta permiso 'ads_read' en el user token.\n"
            "Para activarlo:\n"
            "  1. Meta Business Suite → Configuración → Aplicaciones → [Tu App]\n"
            "  2. Añadir producto: Marketing API\n"
            "  3. Solicitar permiso: ads_read\n"
            "  4. Una vez aprobado, re-autorizar la app (nuevo access_token en panel)"
        )
        return None
    except Exception as ex:
        log.error(f"meta_ads: error obteniendo ad accounts: {ex}")
        return None


# ── Métricas pagadas por post ─────────────────────────────────────────────────

def get_post_paid_metrics(post_id: str, page_id: str, ad_account_id: str, user_token: str) -> dict:
    """
    Consulta Meta Marketing API para obtener reach e inversión pagados
    de un post específico.

    Formato del effective_object_story_id: {page_id}_{post_id}

    Retorna: {"reach_pagado": int, "inversion_pagada": float}
    """
    story_id = f"{page_id}_{post_id}"
    filtering = json.dumps([{
        "field": "effective_object_story_id",
        "operator": "IN",
        "value": [story_id],
    }])
    params = {
        "fields": "spend,reach,impressions",
        "date_preset": "maximum",
        "filtering": filtering,
        "level": "ad",
    }
    qs = urllib.parse.urlencode(params)
    url = f"{GRAPH_BASE}/act_{ad_account_id}/insights?access_token={user_token}&{qs}"
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            data = json.loads(r.read()).get("data", [])
        if not data:
            return {"reach_pagado": 0, "inversion_pagada": 0.0}
        total_reach = sum(int(d.get("reach", 0) or 0) for d in data)
        total_spend = sum(float(d.get("spend", 0) or 0) for d in data)
        return {
            "reach_pagado": total_reach,
            "inversion_pagada": round(total_spend, 2),
        }
    except Exception as ex:
        log.debug(f"meta_ads: sin datos pagados para post {post_id}: {ex}")
        return {"reach_pagado": 0, "inversion_pagada": 0.0}


# ── Sync principal ────────────────────────────────────────────────────────────

def sync_paid_metrics(db, medio) -> int:
    """
    Sincroniza métricas pagadas para publicaciones Instagram y Facebook de 2026+.

    - Si ads_read no está disponible: loguea instrucciones y retorna 0.
    - Si está disponible: actualiza reach_pagado e inversion_pagada en publicaciones.

    Retorna número de publicaciones actualizadas con datos pagados.
    """
    from models.database import Publicacion, CanalEnum

    user_token = _get_token(db, medio.id, "instagram", "access_token")
    page_id = _get_token(db, medio.id, "facebook", "page_id")

    if not user_token:
        log.warning(f"[{medio.slug}] meta_ads: sin user token (instagram.access_token)")
        return 0
    if not page_id:
        log.warning(f"[{medio.slug}] meta_ads: sin page_id configurado")
        return 0

    ad_account_id = _resolve_ad_account(db, medio.id, user_token)
    if not ad_account_id:
        return 0

    inicio_2026 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    pubs = (
        db.query(Publicacion)
        .filter(
            Publicacion.medio_id == medio.id,
            Publicacion.canal.in_([CanalEnum.instagram_post, CanalEnum.facebook]),
            Publicacion.fecha_publicacion >= inicio_2026,
            Publicacion.id_externo.isnot(None),
        )
        .all()
    )

    if not pubs:
        log.info(f"[{medio.slug}] meta_ads: sin publicaciones Meta 2026+ para sincronizar")
        return 0

    actualizadas = 0
    for pub in pubs:
        metrics = get_post_paid_metrics(pub.id_externo, page_id, ad_account_id, user_token)
        if metrics["reach_pagado"] > 0 or metrics["inversion_pagada"] > 0:
            pub.reach_pagado = metrics["reach_pagado"]
            pub.inversion_pagada = Decimal(str(metrics["inversion_pagada"]))
            actualizadas += 1
            log.info(
                f"[{medio.slug}] Post {pub.id_externo} ({pub.canal.value}): "
                f"reach_pagado={metrics['reach_pagado']:,}, "
                f"inversion={metrics['inversion_pagada']:.2f}€"
            )

    if actualizadas:
        db.commit()

    log.info(
        f"[{medio.slug}] meta_ads sync completado: "
        f"{actualizadas}/{len(pubs)} posts con datos pagados"
    )
    return actualizadas
