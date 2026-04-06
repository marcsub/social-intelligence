"""
scripts/backfill_texto.py
Rellena el campo texto en publicaciones existentes que lo tienen vacío,
consultando la API de cada canal.

Uso:
    python scripts/backfill_texto.py --slug roadrunningreview
    python scripts/backfill_texto.py --slug roadrunningreview --canal threads
    python scripts/backfill_texto.py --slug roadrunningreview --dry-run

Canales soportados: threads, instagram, facebook, youtube
"""
import sys
import os
import json
import urllib.request
import urllib.parse
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BATCH = 50


# ── helpers ───────────────────────────────────────────────────────────────────

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


def _get_db_token(db, medio_id: int, canal: str, clave: str):
    from core.crypto import decrypt_token
    from core.settings import get_settings
    from models.database import TokenCanal

    settings = get_settings()
    t = db.query(TokenCanal).filter(
        TokenCanal.medio_id == medio_id,
        TokenCanal.canal == canal,
        TokenCanal.clave == clave,
    ).first()
    return decrypt_token(t.valor_cifrado, settings.jwt_secret) if t else None


# ── Threads ───────────────────────────────────────────────────────────────────

def backfill_threads(db, medio, dry_run: bool) -> int:
    from models.database import Publicacion, CanalEnum

    access_token    = _get_db_token(db, medio.id, "threads", "access_token")
    threads_user_id = _get_db_token(db, medio.id, "threads", "threads_user_id")
    if not access_token or not threads_user_id:
        print("  ERROR: faltan tokens Threads")
        return 0

    pubs = db.query(Publicacion).filter(
        Publicacion.medio_id == medio.id,
        Publicacion.canal == CanalEnum.threads,
        Publicacion.id_externo.isnot(None),
        Publicacion.texto.is_(None),
    ).all()

    if not pubs:
        print("  Sin publicaciones Threads sin texto")
        return 0

    recuperadas = 0
    base = "https://graph.threads.net/v1.0"
    for i in range(0, len(pubs), BATCH):
        lote = pubs[i:i + BATCH]
        for pub in lote:
            try:
                data = _graph_get(base, f"/{pub.id_externo}", access_token, {"fields": "text"})
                texto = (data.get("text") or "").strip() or None
                if texto:
                    if not dry_run:
                        pub.texto = texto
                    recuperadas += 1
            except Exception as ex:
                print(f"  ERROR {pub.id_externo}: {ex}")

    if not dry_run and recuperadas:
        db.commit()
    return recuperadas


# ── Instagram ─────────────────────────────────────────────────────────────────

def backfill_instagram(db, medio, dry_run: bool) -> int:
    from models.database import Publicacion, CanalEnum

    access_token = _get_db_token(db, medio.id, "instagram", "access_token")
    if not access_token:
        print("  ERROR: falta access_token Instagram")
        return 0

    pubs = db.query(Publicacion).filter(
        Publicacion.medio_id == medio.id,
        Publicacion.canal == CanalEnum.instagram_post,
        Publicacion.id_externo.isnot(None),
        Publicacion.texto.is_(None),
    ).all()

    if not pubs:
        print("  Sin publicaciones Instagram sin texto")
        return 0

    recuperadas = 0
    base = "https://graph.facebook.com/v21.0"
    for i in range(0, len(pubs), BATCH):
        lote = pubs[i:i + BATCH]
        for pub in lote:
            try:
                data = _graph_get(base, f"/{pub.id_externo}", access_token, {"fields": "caption"})
                texto = (data.get("caption") or "").strip() or None
                if texto:
                    if not dry_run:
                        pub.texto = texto
                    recuperadas += 1
            except Exception as ex:
                print(f"  ERROR {pub.id_externo}: {ex}")

    if not dry_run and recuperadas:
        db.commit()
    return recuperadas


# ── Facebook ──────────────────────────────────────────────────────────────────

def backfill_facebook(db, medio, dry_run: bool) -> int:
    from models.database import Publicacion, CanalEnum
    from agents.facebook_agent import _resolve_page_token

    page_id = _get_db_token(db, medio.id, "facebook", "page_id")
    if not page_id:
        print("  ERROR: falta page_id Facebook")
        return 0
    try:
        access_token = _resolve_page_token(db, medio.id, page_id)
    except Exception as ex:
        print(f"  ERROR obteniendo page_access_token: {ex}")
        return 0

    pubs = db.query(Publicacion).filter(
        Publicacion.medio_id == medio.id,
        Publicacion.canal == CanalEnum.facebook,
        Publicacion.id_externo.isnot(None),
        Publicacion.texto.is_(None),
    ).all()

    if not pubs:
        print("  Sin publicaciones Facebook sin texto")
        return 0

    recuperadas = 0
    base = "https://graph.facebook.com/v25.0"
    for i in range(0, len(pubs), BATCH):
        lote = pubs[i:i + BATCH]
        for pub in lote:
            try:
                data = _graph_get(base, f"/{pub.id_externo}", access_token, {"fields": "message"})
                texto = (data.get("message") or "").strip() or None
                if texto:
                    if not dry_run:
                        pub.texto = texto
                    recuperadas += 1
            except Exception as ex:
                print(f"  ERROR {pub.id_externo}: {ex}")

    if not dry_run and recuperadas:
        db.commit()
    return recuperadas


# ── YouTube ───────────────────────────────────────────────────────────────────

def backfill_youtube(db, medio, dry_run: bool) -> int:
    from models.database import Publicacion, CanalEnum

    pubs = db.query(Publicacion).filter(
        Publicacion.medio_id == medio.id,
        Publicacion.canal == CanalEnum.youtube,
        Publicacion.id_externo.isnot(None),
        Publicacion.texto.is_(None),
    ).all()

    if not pubs:
        print("  Sin publicaciones YouTube sin texto")
        return 0

    client_id     = _get_db_token(db, medio.id, "youtube", "client_id")
    client_secret = _get_db_token(db, medio.id, "youtube", "client_secret")
    refresh_token = _get_db_token(db, medio.id, "youtube", "refresh_token")
    if not all([client_id, client_secret, refresh_token]):
        print("  ERROR: faltan tokens YouTube")
        return 0

    try:
        resp = urllib.request.urlopen(
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
        access_token = json.loads(resp.read())["access_token"]
    except Exception as ex:
        print(f"  ERROR obteniendo access_token YouTube: {ex}")
        return 0

    recuperadas = 0
    ids = [p.id_externo for p in pubs]
    # Mapear id → pub para actualizar
    pub_map = {p.id_externo: p for p in pubs}

    for i in range(0, len(ids), BATCH):
        batch_ids = ids[i:i + BATCH]
        try:
            url = (
                "https://www.googleapis.com/youtube/v3/videos?"
                + urllib.parse.urlencode({
                    "part": "snippet",
                    "id": ",".join(batch_ids),
                    "access_token": access_token,
                })
            )
            with urllib.request.urlopen(url, timeout=20) as r:
                data = json.loads(r.read())
            for item in data.get("items", []):
                vid = item["id"]
                desc = (item.get("snippet", {}).get("description") or "").strip()
                if desc and vid in pub_map:
                    if not dry_run:
                        pub_map[vid].texto = desc[:500]
                    recuperadas += 1
        except Exception as ex:
            print(f"  ERROR batch YouTube {i}: {ex}")

    if not dry_run and recuperadas:
        db.commit()
    return recuperadas


# ── Main ──────────────────────────────────────────────────────────────────────

CANAL_FUNCS = {
    "threads":   backfill_threads,
    "instagram": backfill_instagram,
    "facebook":  backfill_facebook,
    "youtube":   backfill_youtube,
}

CANAL_ORDER = ["threads", "instagram", "facebook", "youtube"]


def main():
    parser = argparse.ArgumentParser(description="Rellena campo texto en publicaciones existentes")
    parser.add_argument("--slug", required=True)
    parser.add_argument("--canal", choices=list(CANAL_FUNCS.keys()), default=None)
    parser.add_argument("--dry-run", action="store_true")
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

        if args.dry_run:
            print("=== DRY RUN ===")

        canales = [args.canal] if args.canal else CANAL_ORDER
        for canal in canales:
            print(f"\n[{canal.upper()}]")
            n = CANAL_FUNCS[canal](db, medio, args.dry_run)
            print(f"  Canal {canal}: {n} textos recuperados")

    finally:
        db.close()


if __name__ == "__main__":
    main()
