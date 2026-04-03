"""
scripts/test_ga4_semanal.py
Diagnóstico: verifica que GA4 devuelve datos correctos para publicaciones web.

Uso:
    python scripts/test_ga4_semanal.py --slug roadrunningreview
"""
import sys
import os
import json
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import sessionmaker
from sqlalchemy import func
from core.settings import get_settings
from core.crypto import decrypt_token
from models.database import create_db_engine, Medio, Publicacion, TokenCanal, HistorialMetricas, CanalEnum
from urllib.parse import urlparse

GRAPH = "https://graph.facebook.com/v21.0"


def _get_token(db, medio_id, canal, clave):
    settings = get_settings()
    t = db.query(TokenCanal).filter(
        TokenCanal.medio_id == medio_id,
        TokenCanal.canal == canal,
        TokenCanal.clave == clave,
    ).first()
    return decrypt_token(t.valor_cifrado, settings.jwt_secret) if t else None


def _build_ga4(sa_json_str):
    import json as _json
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    info = _json.loads(sa_json_str)
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/analytics.readonly"]
    )
    return build("analyticsdata", "v1beta", credentials=creds, cache_discovery=False)


def _query_ga4(service, property_id, path, start, end, match_type="CONTAINS"):
    resp = service.properties().runReport(
        property=f"properties/{property_id}",
        body={
            "dateRanges": [{"startDate": start, "endDate": end}],
            "dimensions": [{"name": "pagePath"}],
            "metrics": [
                {"name": "sessions"},
                {"name": "totalUsers"},
                {"name": "screenPageViews"},
            ],
            "dimensionFilter": {
                "filter": {
                    "fieldName": "pagePath",
                    "stringFilter": {"matchType": match_type, "value": path}
                }
            },
            "limit": 5,
        }
    ).execute()
    rows = resp.get("rows", [])
    if not rows:
        return None, []
    results = []
    for row in rows:
        dim = row.get("dimensionValues", [{}])[0].get("value", "")
        vals = [int(m.get("value", 0)) for m in row.get("metricValues", [])]
        results.append({"path": dim, "sessions": vals[0], "users": vals[1], "views": vals[2]})
    return results[0]["views"] if results else 0, results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", required=True)
    args = parser.parse_args()

    settings = get_settings()
    engine = create_db_engine(settings.db_url)
    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as db:
        medio = db.query(Medio).filter(Medio.slug == args.slug).first()
        if not medio:
            print(f"ERROR: Medio '{args.slug}' no encontrado"); sys.exit(1)

        config = medio.config
        if not config or not config.ga4_property_id:
            print("ERROR: ga4_property_id no configurado"); sys.exit(1)

        sa_json = _get_token(db, medio.id, "ga4", "service_account_json")
        if not sa_json:
            print("ERROR: Token GA4 no encontrado"); sys.exit(1)

        print(f"\n=== Diagnóstico GA4 semanal — {args.slug} ===")
        print(f"property_id: {config.ga4_property_id}\n")

        try:
            service = _build_ga4(sa_json)
            print("GA4 service: OK\n")
        except Exception as ex:
            print(f"ERROR construyendo GA4 service: {ex}"); sys.exit(1)

        from datetime import datetime, timezone, date as _date
        inicio_2026 = datetime(2026, 1, 1, tzinfo=timezone.utc)

        # 3 publicaciones web con más reach de 2026
        pubs = (
            db.query(Publicacion)
            .filter(
                Publicacion.medio_id == medio.id,
                Publicacion.canal == CanalEnum.web,
                Publicacion.fecha_publicacion >= inicio_2026,
            )
            .order_by(Publicacion.reach.desc())
            .limit(3)
            .all()
        )

        if not pubs:
            print("No hay publicaciones web de 2026 en la DB"); sys.exit(0)

        print(f"Publicaciones a diagnosticar: {len(pubs)}\n")

        # Semana 2026-W01 (5-11 enero)
        test_start = "2026-01-05"
        test_end   = "2026-01-11"
        test_semana = "2026-W01"

        for pub in pubs:
            print(f"--- Publicación ID={pub.id} ---")
            print(f"    URL: {pub.url}")
            print(f"    Fecha: {pub.fecha_publicacion}")
            print(f"    Reach en DB: {pub.reach}")

            path = urlparse(pub.url).path or pub.url
            print(f"    page_path usado: {path}")

            # Contar snapshots en historial
            snaps = (
                db.query(HistorialMetricas)
                .filter(
                    HistorialMetricas.publicacion_id == pub.id,
                    HistorialMetricas.semana_iso.isnot(None),
                )
                .all()
            )
            print(f"    Snapshots semanales en historial: {len(snaps)}")
            nonzero = [s for s in snaps if (s.reach_diff or 0) > 0]
            print(f"    Snapshots con reach_diff > 0: {len(nonzero)}")
            if snaps:
                total_diff = sum(s.reach_diff or 0 for s in snaps)
                print(f"    SUM(reach_diff) en historial: {total_diff}")

            # Test GA4 para semana 2026-W01 si la pub es de enero
            pub_date = pub.fecha_publicacion.date() if hasattr(pub.fecha_publicacion, "date") else pub.fecha_publicacion
            if pub_date <= _date(2026, 1, 11):
                print(f"\n    → Test GA4 para {test_semana} ({test_start} → {test_end}):")

                # Probar con CONTAINS
                try:
                    views, rows = _query_ga4(service, config.ga4_property_id, path, test_start, test_end, "CONTAINS")
                    print(f"      CONTAINS '{path}': views={views}, rows={rows}")
                except Exception as ex:
                    print(f"      CONTAINS ERROR: {ex}")

                # Probar con EXACT
                try:
                    views2, rows2 = _query_ga4(service, config.ga4_property_id, path, test_start, test_end, "EXACT")
                    print(f"      EXACT '{path}': views={views2}, rows={rows2}")
                except Exception as ex:
                    print(f"      EXACT ERROR: {ex}")

                # Probar con trailing slash
                path_slash = path.rstrip("/") + "/"
                if path_slash != path:
                    try:
                        views3, rows3 = _query_ga4(service, config.ga4_property_id, path_slash, test_start, test_end, "CONTAINS")
                        print(f"      CONTAINS '{path_slash}': views={views3}, rows={rows3}")
                    except Exception as ex:
                        print(f"      CONTAINS (slash) ERROR: {ex}")

                # Probar con sin trailing slash
                path_noslash = path.rstrip("/")
                if path_noslash != path:
                    try:
                        views4, rows4 = _query_ga4(service, config.ga4_property_id, path_noslash, test_start, test_end, "CONTAINS")
                        print(f"      CONTAINS '{path_noslash}': views={views4}, rows={rows4}")
                    except Exception as ex:
                        print(f"      CONTAINS (no slash) ERROR: {ex}")
            else:
                print(f"    (pub posterior a W01, skipping W01 test)")

                # Test con rango desde publicación hasta hoy
                hoy = _date.today().isoformat()
                pub_start = pub_date.isoformat()
                try:
                    views, rows = _query_ga4(service, config.ga4_property_id, path, pub_start, hoy, "CONTAINS")
                    print(f"\n    → Test GA4 total ({pub_start} → {hoy}):")
                    print(f"      CONTAINS '{path}': views={views}, rows={rows}")
                except Exception as ex:
                    print(f"\n    → Test GA4 total ERROR: {ex}")

            print()

    print("=== Diagnóstico completado ===")


if __name__ == "__main__":
    main()
