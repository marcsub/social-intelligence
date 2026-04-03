"""
scripts/test_facebook_reach.py
Diagnóstico verbose: verifica reach de posts Facebook directamente contra la API.

Uso:
    python scripts/test_facebook_reach.py --slug roadrunningreview
    python scripts/test_facebook_reach.py --slug roadrunningreview --post-id 1668731220040575_1554301083365875
"""
import sys
import os
import json
import urllib.request
import urllib.parse
import urllib.error
import argparse
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import sessionmaker
from core.settings import get_settings
from core.crypto import decrypt_token
from models.database import create_db_engine, Medio, Publicacion, TokenCanal, CanalEnum

GRAPH = "https://graph.facebook.com/v25.0"


def _get_token(db, medio_id, clave):
    settings = get_settings()
    t = db.query(TokenCanal).filter(
        TokenCanal.medio_id == medio_id,
        TokenCanal.canal == "facebook",
        TokenCanal.clave == clave,
    ).first()
    return decrypt_token(t.valor_cifrado, settings.jwt_secret) if t else None


def _graph_raw_verbose(path, token, params=None, label=""):
    """Llamada GET con respuesta RAW completa incluyendo headers."""
    p = {"access_token": token}
    if params:
        p.update(params)
    url = f"{GRAPH}{path}?{urllib.parse.urlencode(p)}"
    # Ocultar token en el log
    url_safe = url.replace(token, token[:10] + "…")
    print(f"  → {label or path}")
    print(f"    URL: {url_safe}")
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            body = r.read()
            status = r.status
            headers = dict(r.headers)
            data = json.loads(body)
            print(f"    HTTP {status} | headers relevantes: x-fb-rev={headers.get('x-fb-rev','?')} | Content-Type={headers.get('Content-Type','?')}")
            return data, status, headers
    except urllib.error.HTTPError as e:
        body = e.read()
        headers = dict(e.headers)
        try:
            data = json.loads(body)
        except Exception:
            data = {"_raw_body": body.decode("utf-8", errors="replace")}
        print(f"    HTTP {e.code} ERROR | x-fb-trace-id={headers.get('x-fb-trace-id','?')}")
        print(f"    Headers completos: {dict(headers)}")
        return data, e.code, headers
    except Exception as ex:
        print(f"    EXCEPCIÓN: {ex}")
        return {"_exception": str(ex)}, None, {}


def _get_page_token(system_token, page_id):
    data, status, _ = _graph_raw_verbose(
        f"/{page_id}", system_token, {"fields": "access_token"}, "Obtener page_access_token"
    )
    return data.get("access_token")


def _check_permissions(token):
    """Verifica qué permisos tiene el token actual."""
    print("\n─── /me/permissions ───────────────────────────────────────────")
    data, status, _ = _graph_raw_verbose("/me/permissions", token, label="/me/permissions")
    if "error" in data:
        print(f"  ERROR: {data['error']}")
        return []
    perms = data.get("data", [])
    granted = [p["permission"] for p in perms if p.get("status") == "granted"]
    declined = [p["permission"] for p in perms if p.get("status") == "declined"]
    print(f"  Permisos GRANTED ({len(granted)}): {granted}")
    if declined:
        print(f"  Permisos DECLINED: {declined}")
    # Verificar los críticos para insights
    needed = ["pages_read_engagement", "pages_show_list", "business_management"]
    for perm in needed:
        mark = "✓" if perm in granted else "✗ FALTA"
        print(f"  {mark} {perm}")
    return granted


def _test_post(post_id, page_token, system_token, fecha_pub=None):
    """Test completo de reach para un post_id."""
    print(f"\n─── Post: {post_id} ───────────────────────────────────────────")
    if fecha_pub:
        edad_dias = (datetime.now(timezone.utc) - fecha_pub.replace(tzinfo=timezone.utc)).days
        print(f"  Fecha publicación: {fecha_pub.date()} ({edad_dias} días, {edad_dias//30} meses)")
        if edad_dias > 730:
            print(f"  ⚠ Post con más de 24 meses — Meta puede no tener insights disponibles")

    # Verificar formato del ID
    if "_" in post_id:
        page_part, post_part = post_id.split("_", 1)
        print(f"  Formato compuesto: page_id={page_part} | post_part={post_part}")
    else:
        print(f"  Formato simple: {post_id}")

    # 1. Métricas via /insights con page token
    print("\n  [A] /insights con page_token:")
    for metric in ["post_impressions_unique", "post_impressions", "post_reach"]:
        data, status, _ = _graph_raw_verbose(
            f"/{post_id}/insights", page_token, {"metric": metric},
            label=f"page_token / {metric}"
        )
        print(f"    RAW: {json.dumps(data)[:300]}")
        if "error" in data:
            print(f"    ✗ ERROR: {data['error'].get('message','?')} (code={data['error'].get('code','?')}, subcode={data['error'].get('error_subcode','?')})")
        else:
            items = data.get("data", [])
            for item in items:
                if item.get("name") == metric:
                    values = item.get("values", [])
                    val = values[-1].get("value", 0) if values else 0
                    marker = "✓" if val and int(val) > 0 else "·"
                    print(f"    {marker} {metric} = {val}")

    # 2. Endpoint alternativo: fields=insights.metric(...)
    print("\n  [B] Endpoint alternativo ?fields=insights.metric(post_impressions_unique):")
    data2, status2, _ = _graph_raw_verbose(
        f"/{post_id}", page_token,
        {"fields": "insights.metric(post_impressions_unique)"},
        label="page_token / fields=insights.metric(post_impressions_unique)"
    )
    print(f"    RAW: {json.dumps(data2)[:400]}")

    # 3. Con system_token
    print("\n  [C] /insights con system_token:")
    data3, status3, _ = _graph_raw_verbose(
        f"/{post_id}/insights", system_token,
        {"metric": "post_impressions_unique"},
        label="system_token / post_impressions_unique"
    )
    print(f"    RAW: {json.dumps(data3)[:300]}")

    # 4. Campo reach directo en el post
    print("\n  [D] Campo reach directo en el post:")
    data4, status4, _ = _graph_raw_verbose(
        f"/{post_id}", page_token,
        {"fields": "id,message,created_time,insights{name,values}"},
        label="page_token / fields=id,message,created_time,insights{name,values}"
    )
    print(f"    RAW: {json.dumps(data4)[:400]}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", required=True)
    parser.add_argument("--post-id", default=None, help="Post ID específico a testear (además de los de la DB)")
    args = parser.parse_args()

    settings = get_settings()
    engine = create_db_engine(settings.db_url)
    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as db:
        medio = db.query(Medio).filter(Medio.slug == args.slug).first()
        if not medio:
            print(f"ERROR: Medio '{args.slug}' no encontrado"); sys.exit(1)

        system_token = _get_token(db, medio.id, "access_token")
        page_id = _get_token(db, medio.id, "page_id")

        if not system_token or not page_id:
            print("ERROR: Faltan tokens (access_token o page_id)"); sys.exit(1)

        print(f"\n{'='*60}")
        print(f"  Diagnóstico Facebook reach — {args.slug}")
        print(f"  page_id: {page_id}")
        print(f"{'='*60}")

        # Paso 1: verificar permisos
        granted = _check_permissions(system_token)
        has_insights = "pages_read_engagement" in granted

        # Paso 2: obtener page access token
        print("\n─── Page Access Token ──────────────────────────────────────")
        page_token = _get_page_token(system_token, page_id)
        if not page_token:
            print("ERROR: No se pudo obtener page_access_token")
            print("  Causa probable: token sin pages_read_engagement o página sin 'Control total'")
            sys.exit(1)
        print(f"  page_access_token: OK (primeros 20 chars: {page_token[:20]}…)")

        # Paso 3: contar posts por antigüedad
        print("\n─── Distribución de posts por antigüedad ───────────────────")
        from sqlalchemy import func, case
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        cutoff_24m = now - timedelta(days=730)
        pubs_all = (
            db.query(Publicacion)
            .filter(
                Publicacion.medio_id == medio.id,
                Publicacion.canal == CanalEnum.facebook,
            )
            .all()
        )
        recientes = [p for p in pubs_all if p.fecha_publicacion and p.fecha_publicacion.replace(tzinfo=timezone.utc) >= cutoff_24m]
        antiguos  = [p for p in pubs_all if p.fecha_publicacion and p.fecha_publicacion.replace(tzinfo=timezone.utc) < cutoff_24m]
        sin_fecha = [p for p in pubs_all if not p.fecha_publicacion]
        print(f"  Total posts Facebook en DB: {len(pubs_all)}")
        print(f"  Recientes (< 24 meses):     {len(recientes)}")
        print(f"  Antiguos (> 24 meses):       {len(antiguos)}")
        print(f"  Sin fecha:                   {len(sin_fecha)}")

        recientes_reach0 = [p for p in recientes if (p.reach or 0) == 0]
        print(f"  Recientes con reach=0:       {len(recientes_reach0)} de {len(recientes)}")
        if len(recientes_reach0) == len(recientes):
            print("  ⚠ TODOS los posts recientes tienen reach=0 → problema de PERMISOS, no de antigüedad")
        elif len(recientes_reach0) == 0 and len(antiguos) > 0:
            print("  ✓ Posts recientes OK, solo los antiguos tienen reach=0 → LIMITACIÓN DE META (> 24 meses)")

        # Paso 4: testear el post específico si se pasó por argumento
        if args.post_id:
            print(f"\n{'='*60}")
            print(f"  TEST ESPECÍFICO: {args.post_id}")
            print(f"{'='*60}")
            _test_post(args.post_id, page_token, system_token)

        # Paso 5: testear los 5 posts más recientes de la DB
        print(f"\n{'='*60}")
        print(f"  TEST POSTS RECIENTES (últimos 5 en DB)")
        print(f"{'='*60}")
        pubs = (
            db.query(Publicacion)
            .filter(
                Publicacion.medio_id == medio.id,
                Publicacion.canal == CanalEnum.facebook,
                Publicacion.id_externo.isnot(None),
            )
            .order_by(Publicacion.fecha_publicacion.desc())
            .limit(5)
            .all()
        )

        if not pubs:
            print("  No hay publicaciones Facebook en la DB")
        else:
            for pub in pubs:
                _test_post(pub.id_externo, page_token, system_token, pub.fecha_publicacion)

    print(f"\n{'='*60}")
    print("  Diagnóstico completado")
    print(f"{'='*60}")

    if not has_insights:
        print("\n⚠ ACCIÓN REQUERIDA: El token no tiene pages_read_engagement")
        print("  Pasos en Meta Business Suite:")
        print("  1. Ir a business.facebook.com → Configuración → Usuarios del sistema")
        print("  2. Seleccionar el usuario de sistema → 'Editar'")
        print("  3. En 'Permisos de la aplicación', asegurarse de tener:")
        print("     - pages_read_engagement")
        print("     - pages_show_list")
        print("     - read_insights")
        print("  4. En la PÁGINA: Configuración → Roles de la página → verificar que el")
        print("     usuario del sistema tiene 'Control total' (no 'Acceso parcial')")
        print("  5. Regenerar el token de sistema con esos permisos")
        print("  6. Actualizar el token en la DB con: python scripts/authorize_meta.py")


if __name__ == "__main__":
    main()
