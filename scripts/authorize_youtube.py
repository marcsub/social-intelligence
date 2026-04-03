"""
scripts/authorize_youtube.py
Obtiene el refresh token de YouTube via OAuth 2.0.
Ejecutar UNA SOLA VEZ para autorizar el acceso al canal.

Uso:
    python scripts/authorize_youtube.py
"""
import sys
import os
import json
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import urllib.request
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import Session
from models.database import create_db_engine, init_db, Medio, TokenCanal
from core.settings import get_settings
from core.crypto import decrypt_token, encrypt_token

REDIRECT_URI = "http://localhost:8000/auth/youtube/callback"
SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]

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
                "<h2 style='color:#1d9e75'>Autorizacion completada</h2>"
                "<p>Puedes cerrar esta ventana y volver a PowerShell.</p>"
                "</body></html>"
            )
            self.wfile.write(html.encode("utf-8"))
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Error en la autorizacion")

    def log_message(self, format, *args):
        pass


def get_stored_token(db, medio_id, clave):
    t = db.query(TokenCanal).filter(
        TokenCanal.medio_id == medio_id,
        TokenCanal.canal == "youtube",
        TokenCanal.clave == clave,
    ).first()
    if not t:
        return None
    return decrypt_token(t.valor_cifrado, get_settings().jwt_secret)


def save_token(db, medio_id, clave, valor):
    settings = get_settings()
    t = db.query(TokenCanal).filter(
        TokenCanal.medio_id == medio_id,
        TokenCanal.canal == "youtube",
        TokenCanal.clave == clave,
    ).first()
    cifrado = encrypt_token(valor, settings.jwt_secret)
    if t:
        t.valor_cifrado = cifrado
    else:
        db.add(TokenCanal(
            medio_id=medio_id,
            canal="youtube",
            clave=clave,
            valor_cifrado=cifrado,
        ))
    db.commit()


def main():
    settings = get_settings()
    engine = create_db_engine(settings.db_url)
    init_db(engine)

    with Session(engine) as db:
        medio = db.query(Medio).filter(Medio.slug == "roadrunningreview").first()
        if not medio:
            print("ERROR: No se encuentra el medio 'roadrunningreview'.")
            sys.exit(1)

        client_id = get_stored_token(db, medio.id, "client_id")
        client_secret = get_stored_token(db, medio.id, "client_secret")

        if not client_id or not client_secret:
            print("ERROR: Falta client_id o client_secret en el panel de tokens.")
            print("Guardalos primero en Tokens API -> youtube y vuelve a ejecutar.")
            sys.exit(1)

        print("=" * 55)
        print("  Autorizacion YouTube - ROADRUNNINGReview")
        print("=" * 55)
        print()

        params = {
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",
            "prompt": "consent",
        }
        auth_url = "https://accounts.google.com/o/oauth2/auth?" + urllib.parse.urlencode(params)

        print("Abriendo el navegador para autorizar el acceso al canal...")
        print("Si no se abre automaticamente, copia esta URL:")
        print()
        print(auth_url)
        print()
        webbrowser.open(auth_url)

        print("Esperando autorizacion en http://localhost:8000/auth/youtube/callback ...")
        print()

        server = HTTPServer(("localhost", 8000), CallbackHandler)
        server.handle_request()

        if not auth_code_received:
            print("ERROR: No se recibio el codigo de autorizacion.")
            sys.exit(1)

        print("Codigo recibido. Obteniendo tokens...")

        token_data = urllib.parse.urlencode({
            "code": auth_code_received,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": REDIRECT_URI,
            "grant_type": "authorization_code",
        }).encode()

        req = urllib.request.Request(
            "https://oauth2.googleapis.com/token",
            data=token_data,
            method="POST",
        )
        req.add_header("Content-Type", "application/x-www-form-urlencoded")

        try:
            with urllib.request.urlopen(req) as resp:
                tokens = json.loads(resp.read())
        except Exception as ex:
            print("ERROR obteniendo tokens: {}".format(ex))
            sys.exit(1)

        access_token  = tokens.get("access_token")
        refresh_token = tokens.get("refresh_token")

        if not refresh_token:
            print("ERROR: No se obtuvo refresh_token.")
            print("Asegurate de que la app tiene acceso offline y vuelve a intentarlo.")
            sys.exit(1)

        save_token(db, medio.id, "access_token", access_token)
        save_token(db, medio.id, "refresh_token", refresh_token)

        print()
        print("=" * 55)
        print("  Tokens guardados correctamente en la base de datos")
        print("=" * 55)
        print()
        print("  access_token:  guardado y cifrado")
        print("  refresh_token: guardado y cifrado")
        print()
        print("El agente de YouTube ya puede ejecutarse.")
        print("Puedes arrancar uvicorn de nuevo.")


if __name__ == "__main__":
    main()