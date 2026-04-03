"""
scripts/test_fb_metrics_v25.py
Diagnóstico sistemático de métricas Facebook v25.0.
Prueba cada métrica/endpoint una a una e imprime respuesta RAW completa.

Uso:
    python scripts/test_fb_metrics_v25.py --slug roadrunningreview
    python scripts/test_fb_metrics_v25.py --slug roadrunningreview --post-id 123_456
"""
import sys
import os
import json
import urllib.request
import urllib.parse
import urllib.error
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

GRAPH = "https://graph.facebook.com/v25.0"
DEFAULT_POST_ID = "1668731220040575_1554301083365875"

# Todas las métricas a probar en /{post_id}/insights
METRICS_TO_TEST = [
    "reach",
    "impressions",
    "post_engaged_users",
    "post_clicks",
    "post_activity",
    "post_activity_by_action_type",
    "page_post_engagements",
    "post_impressions",
    "post_impressions_unique",
    "post_impressions_paid",
    "post_impressions_organic",
    "post_reactions_like_total",
    "post_reactions_by_type_total",
    "post_video_views",
    "post_video_complete_views_organic",
]

# Períodos a combinar con reach/impressions
PERIODS = ["lifetime", "day", "week", "days_28"]


def _graph_raw(path, token, params=None):
    """Devuelve (data_dict, http_status)."""
    p = {"access_token": token}
    if params:
        p.update(params)
    url = f"{GRAPH}{path}?{urllib.parse.urlencode(p)}"
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            return json.loads(r.read()), r.status
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read())
        except Exception:
            body = {"_raw": e.read().decode("utf-8", errors="replace")}
        return body, e.code
    except Exception as ex:
        return {"_exception": str(ex)}, None


def _get_token(db, medio_id, clave):
    from core.crypto import decrypt_token
    from core.settings import get_settings
    from models.database import TokenCanal
    settings = get_settings()
    t = db.query(TokenCanal).filter(
        TokenCanal.medio_id == medio_id,
        TokenCanal.canal == "facebook",
        TokenCanal.clave == clave,
    ).first()
    return decrypt_token(t.valor_cifrado, settings.jwt_secret) if t else None


def section(title):
    print(f"\n{'═'*60}")
    print(f"  {title}")
    print(f"{'═'*60}")


def probe(label, path, token, params=None):
    data, status = _graph_raw(path, token, params)
    ok = status == 200 and "error" not in data
    marker = "✓" if ok else "✗"
    has_data = ok and (data.get("data") or any(k not in ("id", "paging") for k in data))
    print(f"\n  {marker} [{status}] {label}")
    if "error" in data:
        err = data["error"]
        print(f"      ERROR {err.get('code')}/{err.get('error_subcode','?')}: {err.get('message','?')}")
    else:
        raw = json.dumps(data)
        print(f"      RAW ({len(raw)} chars): {raw[:400]}{'…' if len(raw)>400 else ''}")
    return ok, has_data, data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug",    required=True)
    parser.add_argument("--post-id", default=DEFAULT_POST_ID)
    args = parser.parse_args()

    from sqlalchemy.orm import sessionmaker
    from core.settings import get_settings
    from models.database import create_db_engine, Medio

    settings = get_settings()
    engine   = create_db_engine(settings.db_url)
    Session  = sessionmaker(bind=engine)

    with Session() as db:
        medio = db.query(Medio).filter(Medio.slug == args.slug).first()
        if not medio:
            print(f"ERROR: Medio '{args.slug}' no encontrado"); sys.exit(1)

        system_token = _get_token(db, medio.id, "access_token")
        page_id      = _get_token(db, medio.id, "page_id")
        if not system_token or not page_id:
            print("ERROR: Faltan tokens (access_token o page_id) en la DB"); sys.exit(1)

        print(f"\nSystem token (primeros 20): {system_token[:20]}…")
        print(f"page_id: {page_id}")

        # Intentar intercambiar system token por page access token
        print(f"\nIntentando GET /{page_id}?fields=access_token,name,new_pages_experience …")
        page_data, page_status = _graph_raw(
            f"/{page_id}", system_token,
            {"fields": "access_token,name,new_pages_experience"},
        )
        print(f"  HTTP {page_status} — RAW: {json.dumps(page_data)[:300]}")

        page_token = page_data.get("access_token")
        page_name  = page_data.get("name", "?")
        new_pages  = page_data.get("new_pages_experience", "?")

        if page_token:
            print(f"  page_access_token OK (primeros 20): {page_token[:20]}…")
        else:
            if "error" in page_data:
                err = page_data["error"]
                print(f"  FALLO intercambio — ERROR {err.get('code')}/{err.get('error_subcode','?')}: {err.get('message','?')}")
                if err.get("code") in (190, 102):
                    print("  → El system_token ha CADUCADO.")
                    print("    Regenerar en: Meta Business Suite → Usuarios del sistema")
                    print("    → socialintelligencebot → Generar identificador")
                    print("    → Actualizar con: python scripts/authorize_meta.py")
            else:
                print("  FALLO intercambio — respuesta sin access_token ni error. Usando system_token para todas las pruebas.")
            print(f"\n  Continuando pruebas con system_token ({system_token[:20]}…)")
            page_token = system_token  # fallback: probar igual con system token

        print(f"\nPágina: {page_name} (id={page_id})")
        print(f"New Pages Experience: {new_pages}")

        post_id = args.post_id
        print(f"Post ID: {post_id}\n")

        working = []   # (label, params) de los que funcionan con datos

        # ── A. /{post_id}/insights con cada métrica (sin period) ─────────────
        section("A. /{post_id}/insights — métrica individual (sin period)")
        for metric in METRICS_TO_TEST:
            ok, has_data, data = probe(
                metric,
                f"/{post_id}/insights",
                page_token,
                {"metric": metric},
            )
            if has_data:
                working.append(("A", metric, "no period"))

        # ── B. /{post_id}/insights reach/impressions con period ──────────────
        section("B. /{post_id}/insights reach + impressions con period=")
        for metric in ("reach", "impressions", "post_impressions_unique"):
            for period in PERIODS:
                ok, has_data, data = probe(
                    f"{metric} period={period}",
                    f"/{post_id}/insights",
                    page_token,
                    {"metric": metric, "period": period},
                )
                if has_data:
                    working.append(("B", metric, f"period={period}"))

        # ── C. Fields directos en el post ────────────────────────────────────
        section("C. GET /{post_id}?fields=… (campos directos)")
        fields_sets = [
            "likes.summary(true),comments.summary(true),shares",
            "insights{name,values}",
            "insights.metric(reach){name,values}",
            "insights.metric(impressions){name,values}",
            "insights.metric(post_impressions_unique){name,values}",
            "reactions.summary(true)",
            "full_picture,message,created_time,likes.summary(true),comments.summary(true),shares",
        ]
        for fields in fields_sets:
            ok, has_data, data = probe(
                f"fields={fields[:60]}",
                f"/{post_id}",
                page_token,
                {"fields": fields},
            )
            if has_data:
                working.append(("C", "fields", fields[:60]))

        # ── D. New Pages Experience: /{page_id}/insights por post ────────────
        section("D. /{page_id}/insights — métricas agregadas de página")
        page_metrics = [
            "page_post_impressions_unique",
            "page_post_impressions",
            "page_impressions_unique",
            "page_reach",
            "page_posts_impressions_unique",
        ]
        for metric in page_metrics:
            ok, has_data, data = probe(
                metric,
                f"/{page_id}/insights",
                page_token,
                {"metric": metric, "period": "day"},
            )
            if has_data:
                working.append(("D", metric, "page-level"))

        # ── E. /{post_id} con system token ───────────────────────────────────
        section("E. /{post_id}/insights con system_token (no page_token)")
        for metric in ("reach", "impressions", "post_impressions_unique"):
            ok, has_data, data = probe(
                f"system_token / {metric}",
                f"/{post_id}/insights",
                system_token,
                {"metric": metric},
            )
            if has_data:
                working.append(("E_system", metric, "system_token"))

        # ── F. Endpoint alternativo v25 de métricas por post ─────────────────
        section("F. Endpoints alternativos v25.0")
        alt_probes = [
            ("/{post_id}?fields=insights{values,name,period}",
             f"/{post_id}", {"fields": "insights{values,name,period}"}),
            ("/{post_id}/insights?breakdown=gender_age",
             f"/{post_id}/insights", {"metric": "reach", "breakdown": "gender_age"}),
            ("/me?fields=posts{insights{name,values}}",
             "/me", {"fields": "posts{id,insights{name,values}}"}),
        ]
        for label, path, params in alt_probes:
            ok, has_data, data = probe(label, path, page_token, params)
            if has_data:
                working.append(("F", label, ""))

        # ── Resumen ───────────────────────────────────────────────────────────
        print(f"\n{'═'*60}")
        print(f"  RESUMEN — endpoints con datos reales")
        print(f"{'═'*60}")
        if working:
            for group, metric, note in working:
                print(f"  ✓ [{group}] {metric}  {note}")
        else:
            print("  ✗ Ningún endpoint devolvió datos.")
            print()
            print("  POSIBLES CAUSAS:")
            print("  1. El token no tiene 'pages_read_engagement' o la página")
            print("     no le ha concedido 'Control total' al usuario de sistema.")
            print("  2. El post es demasiado antiguo (> 2 años) y Meta no")
            print("     conserva insights históricos.")
            print("  3. New Pages Experience limita insights a nivel de página,")
            print("     no por post individual — usar /{page_id}/insights en su lugar.")
            print()
            print("  PRÓXIMOS PASOS:")
            print("  → Si todos son 403/200-vacío: regenerar token con permisos completos")
            print("  → Si 400 en reach/impressions: usar post_engaged_users o campos directos")
            print("  → Si página usa New Pages Experience: agregar reach a nivel página/semana")


if __name__ == "__main__":
    main()
