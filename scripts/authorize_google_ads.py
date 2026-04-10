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
  1. Añadir en Google Cloud Console → Credenciales → roadrunning-youtube
     → URIs de redireccionamiento autorizados:
       http://localhost:8001/auth/google_ads/callback
  2. Ejecutar este script (uvicorn puede seguir corriendo en :8000)
  3. El navegador se abre automáticamente
  4. Autorizar la app con la cuenta Google Ads
  5. El script captura el código y guarda los tokens en DB (canal: google_ads)

Nota: el developer_token y customer_id hay que añadirlos manualmente en el
panel web (Configuración → Tokens API → google_ads).
"""
import sys
import os
import json
import argparse
import urllib.request
import urllib.parse
import urllib.error
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import sessionmaker
from core.settings import get_settings
from models.database import create_db_engine, Medio, TokenCanal
from core.crypto import decrypt_token, encrypt_token

GOOGLE_ADS_SCOPE = "https://www.googleapis.com/auth/adwords"
TOKEN_URL        = "https://oauth2.googleapis.com/token"
AUTH_URL         = "https://accounts.google.com/o/oauth2/v2/auth"
REDIRECT_URI     = "http://localhost:8001/auth/google_ads/callback"

auth_code_received = None


class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global auth_code_received
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        if "code" in params:
            auth_code_received = params["code"][0]
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            html = (
                "<html><body style='font-family:system-ui;text-align:center;padding:60px'>"
                "<h2 style='color:#1d9e75'>Autorización Google Ads completada</h2>"
                "<p>Puedes cerrar esta ventana y volver a la terminal.</p>"
                "</body></html>"
            )
            self.wfile.write(html.encode("utf-8"))
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Error en la autorizacion")

    def log_message(self, format, *args):
        pass


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
        client_id     = get_tok(db, medio.id, "youtube", "client_id", secret)
        client_secret = get_tok(db, medio.id, "youtube", "client_secret", secret)

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
        print(f"  4. Redirect URI añadida en Google Cloud Console → Credenciales → roadrunning-youtube:")
        print(f"     {REDIRECT_URI}")
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
        print("Abriendo el navegador para autorizar el acceso a Google Ads...")
        print("Si no se abre automáticamente, copia esta URL:")
        print(f"\n  {auth_url}\n")

        webbrowser.open(auth_url)

        print(f"Esperando autorización en {REDIRECT_URI} ...")
        print()

        server = HTTPServer(("localhost", 8001), CallbackHandler)
        server.handle_request()

        if not auth_code_received:
            print("ERROR: No se recibió el código de autorización.")
            sys.exit(1)

        print("Código recibido. Obteniendo tokens...")

        # Intercambiar código por tokens
        data = urllib.parse.urlencode({
            "code":          auth_code_received,
            "client_id":     client_id,
            "client_secret": client_secret,
            "redirect_uri":  REDIRECT_URI,
            "grant_type":    "authorization_code",
        }).encode()
        req = urllib.request.Request(TOKEN_URL, data=data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
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

        print()
        print("=" * 55)
        print("  Tokens guardados correctamente en la base de datos")
        print("=" * 55)
        print()
        print(f"  access_token:  guardado y cifrado (canal=google_ads)")
        if refresh_token:
            print(f"  refresh_token: guardado y cifrado (canal=google_ads)")
        print()
        print("Ahora añade manualmente en el panel (Configuración → Tokens API → google_ads):")
        print("  - developer_token  (Google Ads → Herramientas → Centro de API)")
        print("  - customer_id      (ID de tu cuenta Google Ads, sin guiones)")
        print()
        print("Para verificar la conexión:")
        print("  python -c \"import sys; sys.path.insert(0,'.')\"")
        print("  from agents import google_ads_agent")
        print("  from sqlalchemy.orm import Session")
        print("  from models.database import create_db_engine")
        print("  from core.settings import get_settings")
        print("  e=create_db_engine(get_settings().db_url)")
        print(f"  with Session(e) as db: print(google_ads_agent.check_access(db, {medio.id}))")


if __name__ == "__main__":
    main()
