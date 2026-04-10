"""
scripts/authorize_meta.py
Configura los tokens de Instagram y Facebook para un medio.

PASO PREVIO (una sola vez, en Meta Developer Console):
  1. Crear una App en https://developers.facebook.com/apps/
     Tipo: "Business" o "Consumer"
  2. Añadir producto "Instagram Graph API" y "Facebook Login"
  3. Permisos necesarios:
       instagram_basic, instagram_manage_insights,
       pages_show_list, pages_read_engagement, read_insights
  4. En "Graph API Explorer" (https://developers.facebook.com/tools/explorer/):
       - Selecciona tu app
       - Solicita los permisos anteriores
       - Haz clic en "Generate Access Token" → copia el token (dura ~1h)

Uso:
  python scripts/authorize_meta.py [slug]
  python scripts/authorize_meta.py roadrunningreview
"""
import sys
import os
import json
import urllib.request
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import Session
from models.database import create_db_engine, init_db, Medio, TokenCanal
from core.settings import get_settings
from core.crypto import encrypt_token, decrypt_token

settings = get_settings()
engine   = create_db_engine(settings.db_url)
GRAPH    = "https://graph.facebook.com/v21.0"

SLUG = sys.argv[1] if len(sys.argv) > 1 else "roadrunningreview"


def save_token(db: Session, medio_id: int, canal: str, clave: str, valor: str):
    cifrado = encrypt_token(valor, settings.jwt_secret)
    t = db.query(TokenCanal).filter(
        TokenCanal.medio_id == medio_id,
        TokenCanal.canal == canal,
        TokenCanal.clave == clave,
    ).first()
    if t:
        t.valor_cifrado = cifrado
    else:
        db.add(TokenCanal(
            medio_id=medio_id, canal=canal, clave=clave, valor_cifrado=cifrado
        ))
    db.commit()


def get_stored(db: Session, medio_id: int, canal: str, clave: str) -> str | None:
    t = db.query(TokenCanal).filter(
        TokenCanal.medio_id == medio_id,
        TokenCanal.canal == canal,
        TokenCanal.clave == clave,
    ).first()
    return decrypt_token(t.valor_cifrado, settings.jwt_secret) if t else None


def graph_get(path: str, token: str, params: dict = None) -> dict:
    p = {"access_token": token}
    if params:
        p.update(params)
    url = f"{GRAPH}{path}?{urllib.parse.urlencode(p)}"
    with urllib.request.urlopen(url, timeout=15) as r:
        return json.loads(r.read())


def exchange_long_lived(app_id: str, app_secret: str, short_token: str) -> dict:
    """Intercambia un short-lived token por un long-lived token (60 días)."""
    params = urllib.parse.urlencode({
        "grant_type":        "fb_exchange_token",
        "client_id":         app_id,
        "client_secret":     app_secret,
        "fb_exchange_token": short_token,
    })
    url = f"{GRAPH}/oauth/access_token?{params}"
    with urllib.request.urlopen(url, timeout=15) as r:
        return json.loads(r.read())


def sep(title=""):
    print("\n" + "─" * 60)
    if title:
        print(f"  {title}")
        print("─" * 60)


def main():
    init_db(engine)

    with Session(engine) as db:
        medio = db.query(Medio).filter(Medio.slug == SLUG).first()
        if not medio:
            print(f"ERROR: Medio '{SLUG}' no encontrado.")
            sys.exit(1)

        sep(f"Autorización Meta — {medio.nombre} ({SLUG})")
        print("""
Necesitas un short-lived User Access Token con los permisos:
  instagram_basic, instagram_manage_insights,
  pages_show_list, pages_read_engagement, read_insights,
  pages_manage_metadata, ads_read

  IMPORTANTE: ads_read es necesario para sincronizar métricas de
  promoción pagada (Meta Ads). Asegúrate de marcarlo.

Obtenerlo en: https://developers.facebook.com/tools/explorer/
  1. Selecciona tu App en el desplegable superior
  2. Marca los permisos indicados (incluyendo ads_read)
  3. Haz clic en "Generate Access Token" y copia el resultado
""")

        # ── Datos de la app ───────────────────────────────────────────────────
        app_id = get_stored(db, medio.id, "instagram", "app_id")
        if app_id:
            print(f"App ID guardado: {app_id[:10]}...")
            change = input("¿Cambiar? [s/N]: ").strip().lower()
            if change == "s":
                app_id = None

        if not app_id:
            app_id = input("App ID (de Meta Developer Console): ").strip()
            if not app_id:
                print("App ID requerido. Abortando.")
                sys.exit(1)
            save_token(db, medio.id, "instagram", "app_id", app_id)
            save_token(db, medio.id, "facebook",  "app_id", app_id)

        app_secret = get_stored(db, medio.id, "instagram", "app_secret")
        if app_secret:
            print(f"App Secret guardado: {app_secret[:6]}...")
            change = input("¿Cambiar? [s/N]: ").strip().lower()
            if change == "s":
                app_secret = None

        if not app_secret:
            app_secret = input("App Secret (de Meta Developer Console): ").strip()
            if not app_secret:
                print("App Secret requerido. Abortando.")
                sys.exit(1)
            save_token(db, medio.id, "instagram", "app_secret", app_secret)
            save_token(db, medio.id, "facebook",  "app_secret", app_secret)

        # ── Short-lived token → Long-lived ────────────────────────────────────
        sep("Paso 1: Convertir token a long-lived (60 días)")

        short_token = input("Pega el short-lived token del Graph API Explorer: ").strip()
        if not short_token:
            print("Token requerido. Abortando.")
            sys.exit(1)

        print("Convirtiendo a long-lived token...")
        try:
            result = exchange_long_lived(app_id, app_secret, short_token)
        except Exception as ex:
            print(f"ERROR en exchange: {ex}")
            sys.exit(1)

        long_token = result.get("access_token")
        expires_in = result.get("expires_in", 0)
        if not long_token:
            print(f"ERROR: No se obtuvo long-lived token. Respuesta: {result}")
            sys.exit(1)

        days = expires_in // 86400
        print(f"Long-lived token obtenido (expira en ~{days} dias)")

        save_token(db, medio.id, "instagram", "access_token", long_token)
        print("Token Instagram guardado.")

        # ── Instagram Account ID ──────────────────────────────────────────────
        sep("Paso 2: Obtener Instagram Business Account ID")

        try:
            me = graph_get("/me", long_token, {
                "fields": "id,name,accounts{instagram_business_account,name,id}"
            })
        except Exception as ex:
            print(f"ERROR consultando /me: {ex}")
            sys.exit(1)

        print(f"Usuario: {me.get('name')} (id={me.get('id')})")

        # Buscar Instagram Business Account en las páginas
        ig_account_id = None
        page_id       = None
        page_token    = None

        accounts = me.get("accounts", {}).get("data", [])
        if not accounts:
            print("\nNo se encontraron páginas de Facebook vinculadas a este token.")
            print("Asegúrate de haber concedido el permiso 'pages_show_list'.")
        else:
            print(f"\nPáginas encontradas: {len(accounts)}")
            for i, acc in enumerate(accounts):
                ig = acc.get("instagram_business_account", {})
                ig_id = ig.get("id") if ig else None
                print(f"  [{i}] {acc.get('name')} (page_id={acc.get('id')}) IG={ig_id or 'no vinculada'}")

            idx = 0
            if len(accounts) > 1:
                idx = int(input(f"Selecciona la página [0-{len(accounts)-1}]: ").strip() or "0")

            chosen = accounts[idx]
            page_id = chosen.get("id")
            ig_data = chosen.get("instagram_business_account")
            if ig_data:
                ig_account_id = ig_data.get("id")

            # Obtener Page Access Token (no expira)
            try:
                page_info = graph_get(f"/{page_id}", long_token, {
                    "fields": "access_token,name"
                })
                page_token = page_info.get("access_token")
                print(f"\nPágina seleccionada: {page_info.get('name')}")
            except Exception as ex:
                print(f"Error obteniendo page token: {ex}")
                page_token = long_token  # fallback al user token

        # ── Guardar todo ──────────────────────────────────────────────────────
        sep("Paso 3: Guardando tokens")

        if ig_account_id:
            save_token(db, medio.id, "instagram", "instagram_account_id", ig_account_id)
            print(f"instagram_account_id: {ig_account_id}")
        else:
            ig_account_id = input(
                "No se detectó IG account ID automáticamente.\n"
                "Introdu­celo manualmente (desde Meta Business Suite → Configuración → "
                "Cuenta de Instagram → ID de cuenta): "
            ).strip()
            if ig_account_id:
                save_token(db, medio.id, "instagram", "instagram_account_id", ig_account_id)

        if page_id:
            save_token(db, medio.id, "facebook", "page_id", page_id)
            print(f"page_id: {page_id}")
        else:
            page_id = input("Page ID de Facebook (si tienes página): ").strip()
            if page_id:
                save_token(db, medio.id, "facebook", "page_id", page_id)

        if page_token:
            save_token(db, medio.id, "facebook", "access_token", page_token)
            save_token(db, medio.id, "facebook", "page_access_token", page_token)
            print("Page access token guardado (Facebook).")

        sep("Autorización completada")
        print(f"""
  Tokens guardados para '{SLUG}':
  Canal "instagram":
    app_id                  OK
    app_secret              OK
    access_token            OK (long-lived, ~60 dias)
    instagram_account_id    {'OK  → ' + ig_account_id if ig_account_id else 'FALTA — introduce manualmente'}

  Canal "facebook":
    app_id                  OK
    page_id                 {'OK  → ' + page_id if page_id else 'FALTA — introduce manualmente'}
    access_token            {'OK (page token, no expira)' if page_token else 'FALTA'}

  Próximos pasos:
    - Reinicia uvicorn para que los agentes Instagram/Facebook estén activos
    - Lanza una ejecución manual:  POST /api/medios/{SLUG}/run
    - Los stories necesitan el trigger de las 06:00 configurado en el scheduler
""")


if __name__ == "__main__":
    main()
