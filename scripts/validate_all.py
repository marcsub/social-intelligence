"""
scripts/validate_all.py
Plan de validación completo del sistema Social Intelligence.
Ejecuta checks en 4 bloques y genera informe final.

Uso:
    python scripts/validate_all.py --slug roadrunningreview
    python scripts/validate_all.py --slug roadrunningreview --api-base http://localhost:8000
"""
import sys
import os
import json
import urllib.request
import urllib.parse
import argparse
import logging
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.WARNING)

GRAPH = "https://graph.facebook.com/v21.0"

# ── Resultado de cada check ───────────────────────────────────────────────────

results = []


def check(code, desc, status, detail=""):
    """status: 'PASS', 'FAIL', 'ALERTA', 'INFO'"""
    icon = {"PASS": "✓", "FAIL": "✗", "ALERTA": "⚠", "INFO": "ℹ"}.get(status, "?")
    results.append((code, desc, status, detail))
    print(f"  {icon} {code}: {desc}")
    if detail:
        for line in detail.split("\n"):
            print(f"      {line}")


def fmtnum(n):
    return f"{n:,}"


# ── BLOQUE 1 — Integridad de datos básica ─────────────────────────────────────

def bloque1(db, medio):
    print("\n─── BLOQUE 1: Integridad de datos básica ───")

    from sqlalchemy import text
    from models.database import Publicacion, CanalEnum

    # V01 — Total publicaciones por canal
    rows = db.execute(
        text("""
            SELECT canal, COUNT(*) as cnt, COALESCE(SUM(reach),0) as reach_total,
                   COALESCE(SUM(likes),0) as likes_total
            FROM publicaciones
            WHERE medio_id = :mid
            GROUP BY canal
        """),
        {"mid": medio.id}
    ).fetchall()

    canal_stats = {r[0]: {"cnt": r[1], "reach": r[2], "likes": r[3]} for r in rows}
    detail_lines = [f"{c}: {s['cnt']} pubs, reach={fmtnum(s['reach'])}" for c, s in canal_stats.items()]
    detail = "\n".join(detail_lines) if detail_lines else "Sin publicaciones"

    canales_esperados = ["web", "instagram_post", "facebook", "youtube"]
    alertas = []
    for c in canales_esperados:
        st = canal_stats.get(c, {})
        if not st or st["cnt"] == 0:
            alertas.append(f"{c}: 0 publicaciones")
        elif st["reach"] == 0:
            alertas.append(f"{c}: reach=0 en todas las publicaciones")

    # Verificar reel
    reel_st = canal_stats.get("instagram_post", {})
    reel_pubs = db.execute(
        text("SELECT COUNT(*) FROM publicaciones WHERE medio_id=:mid AND tipo='reel'"),
        {"mid": medio.id}
    ).scalar()
    if reel_pubs == 0:
        alertas.append("tipo=reel: 0 Reels detectados")
    else:
        detail += f"\nReels (tipo=reel): {reel_pubs}"

    status = "ALERTA" if alertas else "PASS"
    if alertas:
        detail += "\nALERTAS: " + "; ".join(alertas)
    check("V01", "Total publicaciones por canal", status, detail)

    # V02 — Publicaciones sin marca asignada
    total_pubs = db.execute(
        text("SELECT COUNT(*) FROM publicaciones WHERE medio_id=:mid"), {"mid": medio.id}
    ).scalar()
    sin_marca = db.execute(
        text("SELECT COUNT(*) FROM publicaciones WHERE medio_id=:mid AND marca_id IS NULL"), {"mid": medio.id}
    ).scalar()
    pct = round(sin_marca / total_pubs * 100, 1) if total_pubs > 0 else 0
    status = "ALERTA" if pct > 10 else "PASS"
    check("V02", "Publicaciones sin marca asignada", status,
          f"{sin_marca}/{total_pubs} ({pct}%)")

    # V03 — Reach=0 por canal en 2026
    rows3 = db.execute(
        text("""
            SELECT canal, COUNT(*) as cnt
            FROM publicaciones
            WHERE reach=0 AND medio_id=:mid AND fecha_publicacion >= '2026-01-01'
            GROUP BY canal
        """),
        {"mid": medio.id}
    ).fetchall()
    pubs_2026 = db.execute(
        text("SELECT canal, COUNT(*) as cnt FROM publicaciones WHERE medio_id=:mid AND fecha_publicacion >= '2026-01-01' GROUP BY canal"),
        {"mid": medio.id}
    ).fetchall()
    pubs_2026_map = {r[0]: r[1] for r in pubs_2026}
    reach0_map = {r[0]: r[1] for r in rows3}

    alertas3 = []
    for c in ["web", "instagram_post"]:
        total_c = pubs_2026_map.get(c, 0)
        zero_c = reach0_map.get(c, 0)
        if total_c > 0 and zero_c / total_c > 0.5:
            alertas3.append(f"{c}: {zero_c}/{total_c} con reach=0 ({round(zero_c/total_c*100)}%)")

    detail3 = "; ".join(f"{c}: {n} con reach=0" for c, n in reach0_map.items()) or "Todos OK"
    status3 = "ALERTA" if alertas3 else "PASS"
    if alertas3:
        detail3 += "\nALERTAS: " + "; ".join(alertas3)
    check("V03", "Publicaciones con reach=0 en 2026 por canal", status3, detail3)

    # V04 — Distribución estado_marca
    rows4 = db.execute(
        text("SELECT estado_marca, COUNT(*) FROM publicaciones WHERE medio_id=:mid GROUP BY estado_marca"),
        {"mid": medio.id}
    ).fetchall()
    detail4 = "; ".join(f"{r[0] or 'NULL'}: {r[1]}" for r in rows4)
    check("V04", "Distribución estado_marca", "INFO", detail4)


# ── BLOQUE 2 — Histórico semanal ─────────────────────────────────────────────

def bloque2(db, medio):
    print("\n─── BLOQUE 2: Histórico semanal ───")

    from sqlalchemy import text

    # V05 — Snapshots en historial_metricas por canal
    rows5 = db.execute(
        text("""
            SELECT p.canal, COUNT(h.id) as cnt, COALESCE(SUM(h.reach_diff),0) as sum_diff
            FROM historial_metricas h
            JOIN publicaciones p ON h.publicacion_id = p.id
            WHERE p.medio_id = :mid AND h.semana_iso IS NOT NULL
            GROUP BY p.canal
        """),
        {"mid": medio.id}
    ).fetchall()

    alertas5 = []
    detail5_lines = []
    for r in rows5:
        canal, cnt, sdiff = r[0], r[1], r[2]
        detail5_lines.append(f"{canal}: {cnt} snapshots, SUM(reach_diff)={fmtnum(sdiff)}")
        if canal == "web":
            # Contar semanas únicas con datos para web
            semanas_web = db.execute(
                text("""
                    SELECT COUNT(DISTINCT h.semana_iso)
                    FROM historial_metricas h
                    JOIN publicaciones p ON h.publicacion_id=p.id
                    WHERE p.medio_id=:mid AND p.canal='web' AND h.semana_iso IS NOT NULL
                """),
                {"mid": medio.id}
            ).scalar()
            detail5_lines.append(f"  → web: {semanas_web} semanas únicas con snapshot")
            if semanas_web < 5:
                alertas5.append(f"web: solo {semanas_web} semanas de snapshots (mínimo esperado: 5)")
            if sdiff == 0:
                alertas5.append("web: SUM(reach_diff)=0 — backfill no guardó diffs")

    if not rows5:
        alertas5.append("Sin snapshots en historial_metricas con semana_iso")

    status5 = "ALERTA" if alertas5 else "PASS"
    detail5 = "\n".join(detail5_lines) or "Sin datos"
    if alertas5:
        detail5 += "\nALERTAS: " + "; ".join(alertas5)
    check("V05", "Snapshots semanales en historial_metricas por canal", status5, detail5)

    # V06 — Tabla de semanas con datos para canal web
    rows6 = db.execute(
        text("""
            SELECT h.semana_iso, COUNT(*) as pubs, COALESCE(SUM(h.reach_diff),0) as sum_diff
            FROM historial_metricas h
            JOIN publicaciones p ON h.publicacion_id=p.id
            WHERE p.medio_id=:mid AND p.canal='web' AND h.semana_iso IS NOT NULL
            GROUP BY h.semana_iso
            ORDER BY h.semana_iso
        """),
        {"mid": medio.id}
    ).fetchall()

    if not rows6:
        check("V06", "Tabla semanas web en historial", "ALERTA", "Sin datos para canal web")
    else:
        semanas_con_diff = sum(1 for r in rows6 if r[2] > 0)
        semanas_sin_diff = sum(1 for r in rows6 if r[2] == 0)
        lines6 = [f"{r[0]}: {r[1]} pubs, reach_diff={fmtnum(r[2])}" for r in rows6[-12:]]
        detail6 = f"Total semanas: {len(rows6)}, con diff>0: {semanas_con_diff}, diff=0: {semanas_sin_diff}\n"
        detail6 += "Últimas 12 semanas:\n" + "\n".join(lines6)
        status6 = "ALERTA" if semanas_sin_diff > semanas_con_diff else "PASS"
        check("V06", "Semanas con datos en historial (web)", status6, detail6)

    # V07 — Coherencia acumulado vs historial (5 pubs aleatorias web 2026)
    pubs7 = db.execute(
        text("""
            SELECT id, reach, url
            FROM publicaciones
            WHERE medio_id=:mid AND canal='web' AND fecha_publicacion >= '2026-01-01'
            AND reach > 0
            ORDER BY RAND()
            LIMIT 5
        """),
        {"mid": medio.id}
    ).fetchall()

    alertas7 = []
    lines7 = []
    for pub in pubs7:
        sum_diff = db.execute(
            text("SELECT COALESCE(SUM(reach_diff),0) FROM historial_metricas WHERE publicacion_id=:pid AND semana_iso IS NOT NULL"),
            {"pid": pub[0]}
        ).scalar()
        diff_pct = abs(pub[1] - sum_diff) / pub[1] * 100 if pub[1] > 0 else 0
        lines7.append(f"pub {pub[0]}: reach_db={fmtnum(pub[1])}, sum_diff={fmtnum(sum_diff)}, desvío={round(diff_pct)}%")
        if diff_pct > 10:
            alertas7.append(f"pub {pub[0]}: desvío {round(diff_pct)}%")

    status7 = "ALERTA" if alertas7 else ("INFO" if not pubs7 else "PASS")
    check("V07", "Coherencia reach vs SUM(reach_diff) en historial", status7,
          "\n".join(lines7) or "Sin pubs web con reach>0")


# ── BLOQUE 3 — APIs y conectividad ────────────────────────────────────────────

def bloque3(db, medio):
    print("\n─── BLOQUE 3: APIs y conectividad ───")

    from core.crypto import decrypt_token
    from core.settings import get_settings
    from models.database import TokenCanal, Publicacion, CanalEnum
    from sqlalchemy import text

    settings = get_settings()

    def get_tok(canal, clave):
        t = db.query(TokenCanal).filter(
            TokenCanal.medio_id == medio.id,
            TokenCanal.canal == canal,
            TokenCanal.clave == clave,
        ).first()
        return decrypt_token(t.valor_cifrado, settings.jwt_secret) if t else None

    # V08 — Test GA4
    config = medio.config
    ga4_ok = False
    if config and config.ga4_property_id:
        sa_json = get_tok("ga4", "service_account_json")
        if sa_json:
            try:
                import json as _json
                from google.oauth2 import service_account
                from googleapiclient.discovery import build
                from urllib.parse import urlparse

                info = _json.loads(sa_json)
                creds = service_account.Credentials.from_service_account_info(
                    info, scopes=["https://www.googleapis.com/auth/analytics.readonly"]
                )
                svc = build("analyticsdata", "v1beta", credentials=creds, cache_discovery=False)

                # Pub web con más reach
                pub8 = db.execute(
                    text("""
                        SELECT id, url, reach FROM publicaciones
                        WHERE medio_id=:mid AND canal='web' AND reach>0
                        ORDER BY reach DESC LIMIT 1
                    """),
                    {"mid": medio.id}
                ).fetchone()

                if pub8:
                    path = urlparse(pub8[1]).path or pub8[1]
                    resp = svc.properties().runReport(
                        property=f"properties/{config.ga4_property_id}",
                        body={
                            "dateRanges": [{"startDate": "2026-01-01", "endDate": "today"}],
                            "dimensions": [{"name": "pagePath"}],
                            "metrics": [{"name": "screenPageViews"}],
                            "dimensionFilter": {"filter": {"fieldName": "pagePath",
                                "stringFilter": {"matchType": "CONTAINS", "value": path}}},
                            "limit": 1,
                        }
                    ).execute()
                    rows = resp.get("rows", [])
                    views = int(rows[0]["metricValues"][0]["value"]) if rows else 0
                    ga4_ok = views > 0
                    status8 = "PASS" if views > 0 else "ALERTA"
                    check("V08", "Test GA4 — pub web real", status8,
                          f"URL: {pub8[1][:80]}\npath: {path}\nviews GA4: {fmtnum(views)}\nreach DB: {fmtnum(pub8[2])}")
                else:
                    check("V08", "Test GA4 — pub web real", "ALERTA", "Sin pubs web con reach>0")
            except Exception as ex:
                check("V08", "Test GA4 — pub web real", "FAIL", str(ex))
        else:
            check("V08", "Test GA4 — pub web real", "FAIL", "Token GA4 no encontrado")
    else:
        check("V08", "Test GA4 — pub web real", "ALERTA", "ga4_property_id no configurado")

    # V09 — Test Facebook insights
    system_token = get_tok("facebook", "access_token")
    page_id      = get_tok("facebook", "page_id")

    if system_token and page_id:
        try:
            import urllib.request as _ur
            import urllib.parse as _up

            def _gr(path, token, params=None):
                p = {"access_token": token}
                if params: p.update(params)
                url = f"{GRAPH}{path}?{_up.urlencode(p)}"
                with _ur.urlopen(url, timeout=15) as r:
                    return json.loads(r.read())

            # Obtener page token
            page_tok_data = _gr(f"/{page_id}", system_token, {"fields": "access_token"})
            page_tok = page_tok_data.get("access_token")

            if not page_tok:
                check("V09", "Test Facebook insights", "FAIL", "No se pudo obtener page_access_token")
            else:
                pub9 = db.execute(
                    text("SELECT id_externo, reach FROM publicaciones WHERE medio_id=:mid AND canal='facebook' AND id_externo IS NOT NULL LIMIT 1"),
                    {"mid": medio.id}
                ).fetchone()

                if pub9:
                    post_id = pub9[0]
                    data9 = _gr(f"/{post_id}/insights", page_tok, {"metric": "post_impressions_unique"})
                    items = data9.get("data", [])
                    reach9 = 0
                    for it in items:
                        if it.get("name") == "post_impressions_unique":
                            vals = it.get("values", [])
                            if vals:
                                reach9 = int(vals[-1].get("value", 0))

                    status9 = "PASS" if reach9 > 0 else "ALERTA"
                    check("V09", "Test Facebook insights", status9,
                          f"post_id: {post_id}\nreach DB: {fmtnum(pub9[1])}\nreach API: {fmtnum(reach9)}")
                else:
                    check("V09", "Test Facebook insights", "ALERTA", "Sin pubs Facebook en DB")
        except Exception as ex:
            check("V09", "Test Facebook insights", "FAIL", str(ex))
    else:
        check("V09", "Test Facebook insights", "ALERTA", "Tokens Facebook no configurados")

    # V10 — Test Instagram Reels
    ig_token      = get_tok("instagram", "access_token")
    ig_account_id = get_tok("instagram", "instagram_account_id")

    if ig_token and ig_account_id:
        try:
            import urllib.request as _ur
            import urllib.parse as _up

            def _ig(path, token, params=None):
                p = {"access_token": token}
                if params: p.update(params)
                url = f"{GRAPH}{path}?{_up.urlencode(p)}"
                with _ur.urlopen(url, timeout=15) as r:
                    return json.loads(r.read())

            resp10 = _ig(f"/{ig_account_id}/media", ig_token, {"fields": "media_type", "limit": 50})
            tipos = {}
            for item in resp10.get("data", []):
                t = item.get("media_type", "?")
                tipos[t] = tipos.get(t, 0) + 1

            # La API devuelve media_type=VIDEO para Reels; detectamos por permalink /reel/
            reels_api = sum(1 for item in resp10.get("data", [])
                            if item.get("media_type") == "VIDEO" and "/reel/" in item.get("permalink", ""))
            reels_count = tipos.get("REELS", 0) + reels_api  # REELS type (legacy) + VIDEO /reel/
            status10 = "PASS" if reels_count > 0 else "ALERTA"
            detail10 = f"Tipos raw API (primeros 50): {tipos}\nReels detectados por permalink /reel/: {reels_api}"
            if reels_count == 0:
                detail10 += "\nALERTA: No hay Reels detectables en los primeros 50 posts"

            # Contar Reels en DB
            reels_db = db.execute(
                text("SELECT COUNT(*) FROM publicaciones WHERE medio_id=:mid AND tipo='reel'"),
                {"mid": medio.id}
            ).scalar()
            detail10 += f"\nReels en DB (tipo=reel): {reels_db}"
            check("V10", "Test Instagram Reels — verificar acceso", status10, detail10)
        except Exception as ex:
            check("V10", "Test Instagram Reels — verificar acceso", "FAIL", str(ex))
    else:
        check("V10", "Test Instagram Reels — verificar acceso", "ALERTA", "Tokens Instagram no configurados")


# ── BLOQUE 4 — Frontend y endpoints ──────────────────────────────────────────

def bloque4(api_base, slug, db, medio):
    print("\n─── BLOQUE 4: Frontend y endpoints ───")

    from sqlalchemy import text
    from models.database import Marca

    def _api_get(path):
        import urllib.request as _ur
        url = f"{api_base}{path}"
        # Sin auth token — algunos endpoints pueden requerir auth
        try:
            with _ur.urlopen(url, timeout=15) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            return {"_http_error": e.code, "_msg": e.reason}
        except Exception as ex:
            return {"_exception": str(ex)}

    def _api_auth_get(path, token):
        import urllib.request as _ur
        req = _ur.Request(f"{api_base}{path}", headers={"Authorization": f"Bearer {token}"})
        try:
            with _ur.urlopen(req, timeout=15) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            return {"_http_error": e.code, "_msg": e.reason}
        except Exception as ex:
            return {"_exception": str(ex)}

    # V11 — Test endpoint /publicaciones
    data11 = _api_get(f"/api/medios/{slug}/publicaciones?per_page=5")
    if "_http_error" in data11 or "_exception" in data11:
        check("V11", "Endpoint /publicaciones", "ALERTA",
              f"Error (puede requerir auth): {data11}\nTest manual: GET {api_base}/api/medios/{slug}/publicaciones?per_page=5")
    else:
        items = data11.get("items", [])
        fields_ok = all("reach" in i and "estado_marca" in i for i in items)
        has_reel = any(i.get("tipo") == "reel" for i in items)
        detail11 = f"{len(items)} items devueltos\nCampos OK (reach, estado_marca): {fields_ok}\nHay reels: {has_reel}"
        status11 = "PASS" if items and fields_ok else "ALERTA"
        check("V11", "Endpoint /publicaciones", status11, detail11)

    # V12 — Test endpoint /analytics/semanal
    data12 = _api_get(f"/api/medios/{slug}/analytics/semanal?periodo=12m")
    if "_http_error" in data12 or "_exception" in data12:
        check("V12", "Endpoint /analytics/semanal", "ALERTA",
              f"Error (puede requerir auth): {data12}\nTest manual: GET {api_base}/api/medios/{slug}/analytics/semanal?periodo=12m")
    else:
        semanas = data12.get("semanas", [])
        series = data12.get("series", [])
        web_serie = next((s for s in series if s.get("canal") == "web"), None)
        has_diff = web_serie and sum(web_serie.get("data", [])) > 0
        fallback = web_serie and web_serie.get("fallback", False)

        detail12 = f"Semanas: {len(semanas)}, Series: {len(series)}"
        if web_serie:
            detail12 += f"\nWeb SUM(data): {sum(web_serie.get('data', []))}"
            if fallback:
                detail12 += " (FALLBACK reach acumulado — reach_diff=0)"
        status12 = "ALERTA" if not has_diff else "PASS"
        if not semanas:
            status12 = "FAIL"
            detail12 += "\nFAIL: 0 semanas devueltas"
        check("V12", "Endpoint /analytics/semanal", status12, detail12)

    # V13 — Test endpoint /analytics/marca
    marca_top = db.execute(
        text("""
            SELECT m.id, m.nombre_canonico, SUM(p.reach) as r
            FROM marcas m JOIN publicaciones p ON p.marca_id=m.id
            WHERE m.medio_id=:mid
            GROUP BY m.id, m.nombre_canonico
            ORDER BY r DESC LIMIT 1
        """),
        {"mid": medio.id}
    ).fetchone()

    if not marca_top:
        check("V13", "Endpoint /analytics/marca", "ALERTA", "Sin marcas con publicaciones")
    else:
        data13 = _api_get(f"/api/medios/{slug}/analytics/marca/{marca_top[0]}?periodo=12m")
        if "_http_error" in data13 or "_exception" in data13:
            check("V13", "Endpoint /analytics/marca", "ALERTA",
                  f"Error (puede requerir auth): {data13}\nTest manual: GET {api_base}/api/medios/{slug}/analytics/marca/{marca_top[0]}")
        else:
            kpis = data13.get("kpis", {})
            evolucion = data13.get("evolucion_mensual", [])
            status13 = "PASS" if kpis.get("reach", 0) > 0 else "ALERTA"
            check("V13", "Endpoint /analytics/marca", status13,
                  f"Marca: {marca_top[1]}\nKPIs: reach={fmtnum(kpis.get('reach',0))}, pubs={kpis.get('publicaciones',0)}\nevolucion_mensual: {len(evolucion)} meses")


# ── Informe final ─────────────────────────────────────────────────────────────

def informe_final(db, medio, slug):
    from sqlalchemy import text

    print("\n" + "═" * 60)
    print("INFORME FINAL")
    print("═" * 60)

    # Tabla resumen por canal
    rows = db.execute(
        text("""
            SELECT p.canal,
                   COUNT(DISTINCT p.id) as pubs,
                   COALESCE(SUM(p.reach),0) as reach_total,
                   COUNT(DISTINCT h.id) as snapshots,
                   SUM(CASE WHEN p.tipo='reel' THEN 1 ELSE 0 END) as reels
            FROM publicaciones p
            LEFT JOIN historial_metricas h ON h.publicacion_id=p.id AND h.semana_iso IS NOT NULL
            WHERE p.medio_id=:mid
            GROUP BY p.canal
            ORDER BY reach_total DESC
        """),
        {"mid": medio.id}
    ).fetchall()

    print("\nResumen por canal:")
    print(f"  {'Canal':<20} {'Pubs':>6} {'Reach':>12} {'Snapshots':>10} {'Reels':>6}")
    print(f"  {'-'*20} {'-'*6} {'-'*12} {'-'*10} {'-'*6}")
    for r in rows:
        print(f"  {r[0]:<20} {r[1]:>6} {fmtnum(r[2]):>12} {r[3]:>10} {r[4]:>6}")

    print("\nResultados por check:")
    pass_count = sum(1 for r in results if r[2] == "PASS")
    fail_count = sum(1 for r in results if r[2] == "FAIL")
    alerta_count = sum(1 for r in results if r[2] == "ALERTA")

    for code, desc, status, _ in results:
        icon = {"PASS": "✓", "FAIL": "✗", "ALERTA": "⚠", "INFO": "ℹ"}.get(status, "?")
        print(f"  {icon} {code}: {status}")

    print(f"\n  PASS: {pass_count} | FAIL: {fail_count} | ALERTA: {alerta_count} | INFO: {len(results)-pass_count-fail_count-alerta_count}")

    if fail_count == 0 and alerta_count == 0:
        print("\n  ✓ DIAGNÓSTICO: Sistema OK — todos los checks pasaron")
    else:
        print("\n  ✗ DIAGNÓSTICO: Problemas pendientes:")
        for code, desc, status, detail in results:
            if status in ("FAIL", "ALERTA"):
                print(f"    • {code} [{status}]: {desc}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Validación completa del sistema Social Intelligence")
    parser.add_argument("--slug",     required=True, help="Slug del medio")
    parser.add_argument("--api-base", default="http://localhost:8000", help="Base URL de la API (default: http://localhost:8000)")
    args = parser.parse_args()

    from sqlalchemy.orm import sessionmaker
    from core.settings import get_settings
    from models.database import create_db_engine, Medio

    settings = get_settings()
    engine = create_db_engine(settings.db_url)
    SessionLocal = sessionmaker(bind=engine)

    print(f"\n{'═'*60}")
    print(f"VALIDACIÓN SISTEMA SOCIAL INTELLIGENCE — {args.slug}")
    print(f"{'═'*60}")
    print(f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"API base: {args.api_base}")

    with SessionLocal() as db:
        medio = db.query(Medio).filter(Medio.slug == args.slug).first()
        if not medio:
            print(f"\nERROR: Medio '{args.slug}' no encontrado"); sys.exit(1)

        print(f"Medio: {medio.slug} (id={medio.id})")

        bloque1(db, medio)
        bloque2(db, medio)
        bloque3(db, medio)
        bloque4(args.api_base, args.slug, db, medio)
        informe_final(db, medio, args.slug)

    print()


if __name__ == "__main__":
    main()
