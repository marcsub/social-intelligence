"""
scripts/authorize_google_ads.py
OAuth 2.0 flow para Google Ads API (scope: adwords).

Uso:
    python scripts/authorize_google_ads.py --slug roadrunningreview

El script usa el client_id y client_secret de YouTube (mismo proyecto GCP),
pero solicita el scope adwords adicionalmente. Si el proyecto GCP no tiene
Google Ads API habilitada, hay que activarla en:
  https://console.cloud.google.com/apis/library/googleads.googleapis.com

Pasos:
  1. Ejecutar este script
  2. Abrir la URL que aparece en el navegador
  3. Autorizar la app con la cuenta Google Ads
  4. Copiar el código de autorización
  5. El script guarda el access_token y refresh_token en DB (canal: google_ads)

Nota: el developer_token y customer_id hay que añadirlos manualmente en el
panel web (Configuración → Tokens API → google_ads).
"""
import sys
import os
import json
import argparse
import urllib.request
import urllib.parse
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import sessionmaker
from core.settings import get_settings
from models.database import create_db_engine, Medio, TokenCanal
from core.crypto import decrypt_token, encrypt_token

GOOGLE_ADS_SCOPE = "https://www.googleapis.com/auth/adwords"
TOKEN_URL        = "https://oauth2.googleapis.com/token"
AUTH_URL         = "https://accounts.google.com/o/oauth2/v2/auth"
REDIRECT_URI     = "urn:ietf:wg:oauth:2.0:oob"  # out-of-band, sin servidor local


def get_tok(db, medio_id, canal, clave, secret):
    t = db.query(TokenCanal).filter(
        TokenCanal.medio_id == medio_id,
        TokenCanal.canal == canal,
        TokenCanal.clave == clave,
    ).first()
    return decrypt_token(t.valor_cifrado, secret) if t else None


def save_tok(db, medio_id, canal, clave, valor, secret):
    encrypted = encrypt_token(valor, secret)
    existing = db.query(TokenCanal).filter(
        TokenCanal.medio_id == medio_id,
        TokenCanal.canal == canal,
        TokenCanal.clave == clave,
    ).first()
    if existing:
        existing.valor_cifrado = encrypted
    else:
        db.add(TokenCanal(
            medio_id=medio_id,
            canal=canal,
            clave=clave,
            valor_cifrado=encrypted,
        ))
    db.commit()


def main():
    parser = argparse.ArgumentParser(description="Autorizar Google Ads API OAuth")
    parser.add_argument("--slug", required=True, help="Slug del medio")
    args = parser.parse_args()

    settings = get_settings()
    engine = create_db_engine(settings.db_url)
    SessionLocal = sessionmaker(bind=engine)
    secret = settings.jwt_secret

    with SessionLocal() as db:
        medio = db.query(Medio).filter(Medio.slug == args.slug).first()
        if not medio:
            print(f"ERROR: Medio '{args.slug}' no encontrado"); sys.exit(1)

        # Obtener client_id y client_secret del proyecto YouTube (mismo GCP)
        client_id     = get_tok(db, medio.id, "youtube", "client_id")
        client_secret = get_tok(db, medio.id, "youtube", "client_secret")

        if not client_id or not client_secret:
            print("ERROR: client_id / client_secret de YouTube no encontrados en DB.")
            print("Configúralos primero en panel → Tokens API → youtube")
            sys.exit(1)

        print(f"\n=== Autorización Google Ads para '{medio.slug}' ===\n")
        print("IMPORTANTE: Antes de continuar, verifica que tienes:")
        print("  1. Google Ads API habilitada en tu proyecto GCP:")
        print("     https://console.cloud.google.com/apis/library/googleads.googleapis.com")
        print("  2. Tu developer_token de Google Ads (Tools → API Center)")
        print("  3. Tu customer_id (ID de cuenta Google Ads, sin guiones)")
        print()

        # Generar URL de autorización
        params = {
            "client_id":     client_id,
            "redirect_uri":  REDIRECT_URI,
            "response_type": "code",
            "scope":         GOOGLE_ADS_SCOPE,
            "access_type":   "offline",
            "prompt":        "consent",
        }
        auth_url = AUTH_URL + "?" + urllib.parse.urlencode(params)
        print("Abre esta URL en tu navegador:")
        print(f"\n  {auth_url}\n")

        try:
            webbrowser.open(auth_url)
            print("(Intentando abrir el navegador automáticamente...)\n")
        except Exception:
            pass

        code = input("Pega aquí el código de autorización: ").strip()
        if not code:
            print("ERROR: no se proporcionó código"); sys.exit(1)

        # Intercambiar código por tokens
        data = urllib.parse.urlencode({
            "code":          code,
            "client_id":     client_id,
            "client_secret": client_secret,
            "redirect_uri":  REDIRECT_URI,
            "grant_type":    "authorization_code",
        }).encode()
        req = urllib.request.Request(TOKEN_URL, data=data, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                tokens = json.loads(r.read())
        except urllib.error.HTTPError as ex:
            print(f"ERROR obteniendo tokens: HTTP {ex.code}: {ex.read().decode()}")
            sys.exit(1)

        if "error" in tokens:
            print(f"ERROR: {tokens['error']} — {tokens.get('error_description','')}")
            sys.exit(1)

        access_token  = tokens["access_token"]
        refresh_token = tokens.get("refresh_token", "")

        # Guardar en DB
        save_tok(db, medio.id, "google_ads", "access_token",  access_token,  secret)
        if refresh_token:
            save_tok(db, medio.id, "google_ads", "refresh_token", refresh_token, secret)

        print(f"\n✓ access_token guardado en DB (canal=google_ads, clave=access_token)")
        if refresh_token:
            print(f"✓ refresh_token guardado en DB (canal=google_ads, clave=refresh_token)")
        print()
        print("Ahora añade manualmente en el panel (Configuración → Tokens API → google_ads):")
        print("  - developer_token  (Google Ads → Herramientas → Centro de API)")
        print("  - customer_id      (ID de tu cuenta Google Ads, sin guiones)")
        print()
        print("Para verificar la conexión:")
        print(f"  cd /home/pirineos/social-intelligence && venv/bin/python -c \"")
        print(f"  import sys; sys.path.insert(0,'.')")
        print(f"  from agents import google_ads_agent")
        print(f"  from core.settings import get_settings")
        print(f"  from models.database import create_db_engine")
        print(f"  from sqlalchemy.orm import Session")
        print(f"  e=create_db_engine(get_settings().db_url)")
        print(f"  with Session(e) as db: print(google_ads_agent.check_access(db, 1))\"")


if __name__ == "__main__":
    main()
