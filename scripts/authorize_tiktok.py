"""
scripts/authorize_tiktok.py
OAuth 2.0 + PKCE flow para TikTok Open Platform API v2.

Uso:
    python scripts/authorize_tiktok.py --slug roadrunningreview

Requisitos previos:
  1. Tener una app en https://developers.tiktok.com/ con:
     - Producto "Login Kit" activado
     - Scopes: user.info.basic, video.list
     - Redirect URI autorizada: http://tiktok.social-intelligence.local:8002/callback
       (TikTok no acepta localhost — añade al fichero hosts de Windows:
        127.0.0.1  tiktok.social-intelligence.local)
  2. Haber guardado en el panel (Configuración → Tokens API → canal: tiktok):
     - client_key    → tu Client Key
     - client_secret → tu Client Secret

El script:
  1. Lee client_key y client_secret de la DB
  2. Genera PKCE (code_verifier + code_challenge SHA-256)
  3. Abre el navegador con la URL de autorización TikTok
  4. Escucha en localhost:8002/callback el código OAuth
  5. Intercambia el código por access_token + refresh_token
  6. Guarda los tokens cifrados en DB (canal: tiktok)
"""
import sys
import os
import json
import argparse
import hashlib
import base64
import secrets
import urllib.request
import urllib.parse
import urllib.error
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import sessionmaker
from core.settings import get_settings
from models.database import create_db_engine, Medio, TokenCanal
from core.crypto import decrypt_token, encrypt_token

AUTH_URL     = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL    = "https://open.tiktokapis.com/v2/oauth/token/"
REDIRECT_URI = "https://www.roadrunningreview.com/social/api/auth/tiktok/callback"
SCOPES       = "user.info.basic,video.list"


# ── PKCE helpers ──────────────────────────────────────────────────────────────

def _generate_code_verifier() -> str:
    """Genera un code_verifier aleatorio de 64 caracteres (URL-safe)."""
    return secrets.token_urlsafe(48)  # 48 bytes → 64 chars base64url


def _generate_code_challenge(verifier: str) -> str:
    """SHA-256 del verifier, codificado en base64url sin padding."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


# ── DB helpers ────────────────────────────────────────────────────────────────

def _get_tok(db, medio_id, clave, secret):
    t = db.query(TokenCanal).filter(
        TokenCanal.medio_id == medio_id,
        TokenCanal.canal == "tiktok",
        TokenCanal.clave == clave,
    ).first()
    return decrypt_token(t.valor_cifrado, secret) if t else None


def _save_tok(db, medio_id, clave, valor, secret):
    encrypted = encrypt_token(valor, secret)
    existing = db.query(TokenCanal).filter(
        TokenCanal.medio_id == medio_id,
        TokenCanal.canal == "tiktok",
        TokenCanal.clave == clave,
    ).first()
    if existing:
        existing.valor_cifrado = encrypted
    else:
        db.add(TokenCanal(
            medio_id=medio_id,
            canal="tiktok",
            clave=clave,
            valor_cifrado=encrypted,
        ))
    db.commit()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Autorizar TikTok API OAuth 2.0 + PKCE")
    parser.add_argument("--slug", required=True, help="Slug del medio (ej: roadrunningreview)")
    args = parser.parse_args()

    settings = get_settings()
    engine = create_db_engine(settings.db_url)
    SessionLocal = sessionmaker(bind=engine)
    secret = settings.jwt_secret

    with SessionLocal() as db:
        medio = db.query(Medio).filter(Medio.slug == args.slug).first()
        if not medio:
            print(f"ERROR: Medio '{args.slug}' no encontrado en la DB.")
            sys.exit(1)

        client_key    = _get_tok(db, medio.id, "client_key", secret)
        client_secret = _get_tok(db, medio.id, "client_secret", secret)

        if not client_key or not client_secret:
            print("ERROR: client_key o client_secret de TikTok no encontrados en DB.")
            print()
            print("Añádelos en el panel → Configuración → Tokens API → canal: tiktok")
            print("  clave: client_key    → tu Client Key de TikTok for Developers")
            print("  clave: client_secret → tu Client Secret de TikTok for Developers")
            sys.exit(1)

        print(f"\n=== Autorización TikTok para '{medio.slug}' ===\n")
        print("Verifica que en tu app de TikTok for Developers tienes:")
        print(f"  - Redirect URI: {REDIRECT_URI}")
        print(f"  - Scopes activos: {SCOPES}")
        print()

        # Generar PKCE
        code_verifier  = _generate_code_verifier()
        code_challenge = _generate_code_challenge(code_verifier)
        state          = secrets.token_urlsafe(16)

        # Construir URL de autorización
        params = {
            "client_key":             client_key,
            "response_type":          "code",
            "scope":                  SCOPES,
            "redirect_uri":           REDIRECT_URI,
            "state":                  state,
            "code_challenge":         code_challenge,
            "code_challenge_method":  "S256",
        }
        auth_url = AUTH_URL + "?" + urllib.parse.urlencode(params)

        print("Abriendo el navegador para autorizar el acceso a TikTok...")
        print("Si no se abre automáticamente, copia esta URL en el navegador:")
        print(f"\n  {auth_url}\n")

        webbrowser.open(auth_url)

        print(f"TikTok redirigirá a: {REDIRECT_URI}")
        print("El navegador mostrará el código de autorización.")
        print()
        auth_code_received = input("Pega aquí el código que aparece en el navegador y pulsa Enter: ").strip()

        if not auth_code_received:
            print("ERROR: No se introdujo ningún código.")
            sys.exit(1)

        print("\nCódigo recibido. Intercambiando por tokens...")

        # Intercambiar código por tokens
        data = urllib.parse.urlencode({
            "client_key":     client_key,
            "client_secret":  client_secret,
            "code":           auth_code_received,
            "grant_type":     "authorization_code",
            "redirect_uri":   REDIRECT_URI,
            "code_verifier":  code_verifier,
        }).encode()

        req = urllib.request.Request(TOKEN_URL, data=data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        req.add_header("Cache-Control", "no-cache")

        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                tokens = json.loads(r.read())
        except urllib.error.HTTPError as ex:
            body = ex.read().decode()
            print(f"ERROR HTTP {ex.code}: {body}")
            sys.exit(1)

        if "error" in tokens and tokens["error"] not in ("", "ok"):
            print(f"ERROR: {tokens['error']} — {tokens.get('error_description', '')}")
            sys.exit(1)

        access_token  = tokens.get("access_token")
        refresh_token = tokens.get("refresh_token")
        open_id       = tokens.get("open_id", "")
        expires_in    = tokens.get("expires_in", 86400)

        if not access_token:
            print(f"ERROR: No se obtuvo access_token. Respuesta: {tokens}")
            sys.exit(1)

        # Guardar en DB
        _save_tok(db, medio.id, "access_token",  access_token,  secret)
        if refresh_token:
            _save_tok(db, medio.id, "refresh_token", refresh_token, secret)
        if open_id:
            _save_tok(db, medio.id, "open_id", open_id, secret)

        print()
        print("=" * 60)
        print("  Tokens TikTok guardados correctamente en la base de datos")
        print("=" * 60)
        print()
        print(f"  access_token:  guardado y cifrado (expira en {expires_in}s / ~24h)")
        if refresh_token:
            print(f"  refresh_token: guardado y cifrado (expira en ~365 días)")
        if open_id:
            print(f"  open_id:       {open_id}")
        print()
        print("El access_token se renueva automáticamente con el agente.")
        print()
        print("Para lanzar una detección manual de TikTok:")
        print(f"  python -c \"")
        print(f"    import sys; sys.path.insert(0,'.')")
        print(f"    from models.database import create_db_engine")
        print(f"    from core.settings import get_settings")
        print(f"    from sqlalchemy.orm import Session")
        print(f"    from agents import tiktok_agent")
        print(f"    from models.database import Medio")
        print(f"    e = create_db_engine(get_settings().db_url)")
        print(f"    with Session(e) as db:")
        print(f"        m = db.query(Medio).filter_by(slug='{args.slug}').first()")
        print(f"        print(tiktok_agent.detect_new(db, m, None))")
        print(f"  \"")


if __name__ == "__main__":
    main()
