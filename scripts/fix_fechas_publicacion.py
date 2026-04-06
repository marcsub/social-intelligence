"""
scripts/fix_fechas_publicacion.py
Corrige fecha_publicacion en publicaciones existentes consultando la fecha real
a la API de cada canal.

Uso:
    python scripts/fix_fechas_publicacion.py --slug roadrunningreview
    python scripts/fix_fechas_publicacion.py --slug roadrunningreview --canal threads
    python scripts/fix_fechas_publicacion.py --slug roadrunningreview --canal instagram --dry-run

Canales soportados: threads, instagram, facebook, youtube
(web usa sitemap/RSS y no tiene API directa de consulta por ID)
"""
import sys
import os
import json
import urllib.request
import urllib.parse
import argparse
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _parse_ts(s: str) -> datetime | None:
    """Parsea ISO 8601 de Meta APIs. Devuelve None si no se puede parsear."""
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    if len(s) >= 5 and s[-5] in ('+', '-') and ':' not in s[-5:]:
        s = s[:-2] + ':' + s[-2:]
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _graph_get(base_url: str, path: str, token: str, params: dict = None) -> dict:
    p = {"access_token": token}
    if params:
        p.update(params)
    url = f"{base_url}{path}?{urllib.parse.urlencode(p)}"
    with urllib.request.urlopen(url, timeout=20) as r:
        data = json.loads(r.read())
    if "error" in data:
        raise RuntimeError(data["error"].get("message", str(data["error"])))
    return data


# ── Canal: Threads ────────────────────────────────────────────────────────────

def _fetch_threads_timestamps(access_token: str, threads_user_id: str) -> dict[str, datetime]:
    """Descarga todos los posts de Threads con su timestamp real. Devuelve {post_id: datetime}."""
    base = "https://graph.threads.net/v1.0"
    result = {}
    next_url = None
    page = 0
    while page < 50:
        try:
            if next_url:
                with urllib.request.urlopen(next_url, timeout=20) as r:
                    resp = json.loads(r.read())
            else:
                resp = _graph_get(base, f"/{threads_user_id}/threads", access_token,
                                  {"fields": "id,timestamp", "limit": 100})
        except Exception as ex:
            print(f"  ERROR paginando Threads (página {page}): {ex}")
            break

        for item in resp.get("data", []):
            post_id = item.get("id")
            ts = _parse_ts(item.get("timestamp", ""))
            if post_id and ts:
                result[post_id] = ts

        next_url = resp.get("paging", {}).get("next")
        if not next_url:
            break
        page += 1

    return result


def fix_threads(db, medio, dry_run: bool) -> tuple[int, int, int]:
    from core.crypto import decrypt_token
    from core.settings import get_settings
    from models.database import TokenCanal, Publicacion, CanalEnum

    settings = get_settings()

    def tok(clave):
        t = db.query(TokenCanal).filter(
            TokenCanal.medio_id == medio.id,
            TokenCanal.canal == "threads",
            TokenCanal.clave == clave,
        ).first()
        return decrypt_token(t.valor_cifrado, settings.jwt_secret) if t else None

    access_token    = tok("access_token")
    threads_user_id = tok("threads_user_id")
    if not access_token or not threads_user_id:
        print("  ERROR: faltan tokens Threads")
        return 0, 0, 1

    print("  Descargando timestamps de Threads API…")
    api_ts = _fetch_threads_timestamps(access_token, threads_user_id)
    print(f"  {len(api_ts)} posts obtenidos de la API")

    pubs = db.query(Publicacion).filter(
        Publicacion.medio_id == medio.id,
        Publicacion.canal == CanalEnum.threads,
        Publicacion.id_externo.isnot(None),
    ).all()

    actualizadas = sin_cambios = errores = 0
    for pub in pubs:
        ts = api_ts.get(pub.id_externo)
        if ts is None:
            print(f"  SKIP {pub.id_externo}: no encontrado en API (puede haber sido eliminado)")
            sin_cambios += 1
            continue

        fp = pub.fecha_publicacion
        if fp and fp.tzinfo is None:
            fp = fp.replace(tzinfo=timezone.utc)

        diff = abs((ts - fp).total_seconds()) if fp else 999999
        if diff < 60:
            sin_cambios += 1
            continue

        print(f"  FIX {pub.id_externo}: {fp} → {ts}")
        if not dry_run:
            pub.fecha_publicacion = ts
        actualizadas += 1

    if not dry_run and actualizadas:
        db.commit()
    return actualizadas, sin_cambios, errores


# ── Canal: Instagram ──────────────────────────────────────────────────────────

def _fetch_instagram_timestamps(access_token: str, ig_account_id: str) -> dict[str, datetime]:
    base = "https://graph.facebook.com/v21.0"
    result = {}
    next_url = None
    page = 0
    while page < 50:
        try:
            if next_url:
                with urllib.request.urlopen(next_url, timeout=20) as r:
                    resp = json.loads(r.read())
            else:
                resp = _graph_get(base, f"/{ig_account_id}/media", access_token,
                                  {"fields": "id,timestamp", "limit": 100})
        except Exception as ex:
            print(f"  ERROR paginando Instagram (página {page}): {ex}")
            break

        for item in resp.get("data", []):
            mid = item.get("id")
            ts = _parse_ts(item.get("timestamp", ""))
            if mid and ts:
                result[mid] = ts

        next_url = resp.get("paging", {}).get("next")
        if not next_url:
            break
        page += 1

    return result


def fix_instagram(db, medio, dry_run: bool) -> tuple[int, int, int]:
    from core.crypto import decrypt_token
    from core.settings import get_settings
    from models.database import TokenCanal, Publicacion, CanalEnum

    settings = get_settings()

    def tok(clave):
        t = db.query(TokenCanal).filter(
            TokenCanal.medio_id == medio.id,
            TokenCanal.canal == "instagram",
            TokenCanal.clave == clave,
        ).first()
        return decrypt_token(t.valor_cifrado, settings.jwt_secret) if t else None

    access_token  = tok("access_token")
    ig_account_id = tok("instagram_account_id")
    if not access_token or not ig_account_id:
        print("  ERROR: faltan tokens Instagram")
        return 0, 0, 1

    print("  Descargando timestamps de Instagram API…")
    api_ts = _fetch_instagram_timestamps(access_token, ig_account_id)
    print(f"  {len(api_ts)} posts obtenidos de la API")

    pubs = db.query(Publicacion).filter(
        Publicacion.medio_id == medio.id,
        Publicacion.canal.in_([CanalEnum.instagram_post]),
        Publicacion.id_externo.isnot(None),
    ).all()

    actualizadas = sin_cambios = errores = 0
    for pub in pubs:
        ts = api_ts.get(pub.id_externo)
        if ts is None:
            sin_cambios += 1
            continue

        fp = pub.fecha_publicacion
        if fp and fp.tzinfo is None:
            fp = fp.replace(tzinfo=timezone.utc)

        diff = abs((ts - fp).total_seconds()) if fp else 999999
        if diff < 60:
            sin_cambios += 1
            continue

        print(f"  FIX {pub.id_externo}: {fp} → {ts}")
        if not dry_run:
            pub.fecha_publicacion = ts
        actualizadas += 1

    if not dry_run and actualizadas:
        db.commit()
    return actualizadas, sin_cambios, errores


# ── Canal: Facebook ───────────────────────────────────────────────────────────

def _fetch_facebook_timestamps(access_token: str, page_id: str) -> dict[str, datetime]:
    base = "https://graph.facebook.com/v25.0"
    result = {}
    next_url = None
    page = 0
    while page < 50:
        try:
            if next_url:
                with urllib.request.urlopen(next_url, timeout=20) as r:
                    resp = json.loads(r.read())
            else:
                resp = _graph_get(base, f"/{page_id}/posts", access_token,
                                  {"fields": "id,created_time", "limit": 100})
        except Exception as ex:
            print(f"  ERROR paginando Facebook (página {page}): {ex}")
            break

        for item in resp.get("data", []):
            pid = item.get("id")
            ts = _parse_ts(item.get("created_time", ""))
            if pid and ts:
                result[pid] = ts

        next_url = resp.get("paging", {}).get("next")
        if not next_url:
            break
        page += 1

    return result


def fix_facebook(db, medio, dry_run: bool) -> tuple[int, int, int]:
    from core.crypto import decrypt_token
    from core.settings import get_settings
    from models.database import TokenCanal, Publicacion, CanalEnum
    from agents.facebook_agent import _resolve_page_token

    settings = get_settings()

    def tok(clave):
        t = db.query(TokenCanal).filter(
            TokenCanal.medio_id == medio.id,
            TokenCanal.canal == "facebook",
            TokenCanal.clave == clave,
        ).first()
        return decrypt_token(t.valor_cifrado, settings.jwt_secret) if t else None

    page_id = tok("page_id")
    if not page_id:
        print("  ERROR: falta page_id Facebook")
        return 0, 0, 1

    try:
        access_token = _resolve_page_token(db, medio.id, page_id)
    except Exception as ex:
        print(f"  ERROR obteniendo page_access_token: {ex}")
        return 0, 0, 1

    print("  Descargando timestamps de Facebook API…")
    api_ts = _fetch_facebook_timestamps(access_token, page_id)
    print(f"  {len(api_ts)} posts obtenidos de la API")

    pubs = db.query(Publicacion).filter(
        Publicacion.medio_id == medio.id,
        Publicacion.canal == CanalEnum.facebook,
        Publicacion.id_externo.isnot(None),
    ).all()

    actualizadas = sin_cambios = errores = 0
    for pub in pubs:
        ts = api_ts.get(pub.id_externo)
        if ts is None:
            sin_cambios += 1
            continue

        fp = pub.fecha_publicacion
        if fp and fp.tzinfo is None:
            fp = fp.replace(tzinfo=timezone.utc)

        diff = abs((ts - fp).total_seconds()) if fp else 999999
        if diff < 60:
            sin_cambios += 1
            continue

        print(f"  FIX {pub.id_externo}: {fp} → {ts}")
        if not dry_run:
            pub.fecha_publicacion = ts
        actualizadas += 1

    if not dry_run and actualizadas:
        db.commit()
    return actualizadas, sin_cambios, errores


# ── Canal: YouTube ────────────────────────────────────────────────────────────

def fix_youtube(db, medio, dry_run: bool) -> tuple[int, int, int]:
    """
    Corrige fecha_publicacion para YouTube usando la Data API v3.
    YouTube usa el formato Z que ya se parsea correctamente, pero por si acaso
    algún registro fue insertado con fecha errónea.
    """
    from core.crypto import decrypt_token
    from core.settings import get_settings
    from models.database import TokenCanal, Publicacion, CanalEnum

    settings = get_settings()

    def tok(clave):
        t = db.query(TokenCanal).filter(
            TokenCanal.medio_id == medio.id,
            TokenCanal.canal == "youtube",
            TokenCanal.clave == clave,
        ).first()
        return decrypt_token(t.valor_cifrado, settings.jwt_secret) if t else None

    client_id     = tok("client_id")
    client_secret = tok("client_secret")
    refresh_token = tok("refresh_token")
    if not all([client_id, client_secret, refresh_token]):
        print("  ERROR: faltan tokens YouTube")
        return 0, 0, 1

    # Obtener access_token vía OAuth2
    try:
        token_resp = urllib.request.urlopen(
            urllib.request.Request(
                "https://oauth2.googleapis.com/token",
                data=urllib.parse.urlencode({
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                }).encode(),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            ),
            timeout=15,
        )
        access_token = json.loads(token_resp.read())["access_token"]
    except Exception as ex:
        print(f"  ERROR obteniendo access_token YouTube: {ex}")
        return 0, 0, 1

    pubs = db.query(Publicacion).filter(
        Publicacion.medio_id == medio.id,
        Publicacion.canal == CanalEnum.youtube,
        Publicacion.id_externo.isnot(None),
    ).all()

    # Consultar en lotes de 50
    api_ts: dict[str, datetime] = {}
    ids = [p.id_externo for p in pubs if p.id_externo]
    for i in range(0, len(ids), 50):
        batch = ids[i:i+50]
        try:
            url = (
                "https://www.googleapis.com/youtube/v3/videos?"
                + urllib.parse.urlencode({
                    "part": "snippet",
                    "id": ",".join(batch),
                    "access_token": access_token,
                })
            )
            with urllib.request.urlopen(url, timeout=20) as r:
                data = json.loads(r.read())
            for item in data.get("items", []):
                vid = item["id"]
                pa = item.get("snippet", {}).get("publishedAt", "")
                ts = _parse_ts(pa)
                if ts:
                    api_ts[vid] = ts
        except Exception as ex:
            print(f"  ERROR consultando YouTube batch {i}: {ex}")

    print(f"  {len(api_ts)} vídeos obtenidos de la API")

    actualizadas = sin_cambios = errores = 0
    for pub in pubs:
        ts = api_ts.get(pub.id_externo)
        if ts is None:
            sin_cambios += 1
            continue

        fp = pub.fecha_publicacion
        if fp and fp.tzinfo is None:
            fp = fp.replace(tzinfo=timezone.utc)

        diff = abs((ts - fp).total_seconds()) if fp else 999999
        if diff < 60:
            sin_cambios += 1
            continue

        print(f"  FIX {pub.id_externo}: {fp} → {ts}")
        if not dry_run:
            pub.fecha_publicacion = ts
        actualizadas += 1

    if not dry_run and actualizadas:
        db.commit()
    return actualizadas, sin_cambios, errores


# ── Main ──────────────────────────────────────────────────────────────────────

CANAL_FUNCS = {
    "threads":   fix_threads,
    "instagram": fix_instagram,
    "facebook":  fix_facebook,
    "youtube":   fix_youtube,
}

CANAL_ORDER = ["threads", "instagram", "facebook", "youtube"]


def main():
    parser = argparse.ArgumentParser(description="Corrige fecha_publicacion en DB usando la API de cada canal")
    parser.add_argument("--slug", required=True, help="Slug del medio (ej: roadrunningreview)")
    parser.add_argument("--canal", choices=list(CANAL_FUNCS.keys()), default=None,
                        help="Canal específico a corregir (por defecto: todos)")
    parser.add_argument("--dry-run", action="store_true", help="Muestra cambios sin aplicarlos")
    args = parser.parse_args()

    from models.database import create_db_engine, Medio
    from sqlalchemy.orm import sessionmaker
    from core.settings import get_settings

    settings = get_settings()
    engine = create_db_engine(settings.db_url)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    try:
        medio = db.query(Medio).filter(Medio.slug == args.slug).first()
        if not medio:
            print(f"ERROR: medio '{args.slug}' no encontrado")
            sys.exit(1)

        canales = [args.canal] if args.canal else CANAL_ORDER
        if args.dry_run:
            print("=== DRY RUN — no se aplicarán cambios ===")

        total_act = total_sc = total_err = 0
        for canal in canales:
            print(f"\n[{canal.upper()}]")
            act, sc, err = CANAL_FUNCS[canal](db, medio, args.dry_run)
            print(f"  Actualizadas: {act} | Sin cambios: {sc} | Errores: {err}")
            total_act += act; total_sc += sc; total_err += err

        print(f"\n{'[DRY RUN] ' if args.dry_run else ''}TOTAL — Actualizadas: {total_act} | Sin cambios: {total_sc} | Errores: {total_err}")

    finally:
        db.close()


if __name__ == "__main__":
    main()
