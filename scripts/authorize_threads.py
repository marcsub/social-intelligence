"""
scripts/authorize_threads.py
Obtiene un Long-Lived Access Token de Threads via OAuth 2.0.

Flow:
  1. Browser OAuth → código de autorización
  2. Código → short-lived token (POST graph.threads.net/oauth/access_token)
  3. Short-lived → long-lived token (60 días, GET graph.threads.net/refresh_access_token)
  4. Obtener Threads User ID (GET graph.threads.net/v1.0/me)
  5. Guardar en DB canal 'threads': access_token, threads_user_id, app_id, app_secret

Prerequisitos:
  - App de Threads creada en developers.facebook.com con
    threads_basic y threads_manage_insights
  - URI de redirección configurada en la app:
    http://localhost:8000/auth/threads/callback

Uso:
    python scripts/authorize_threads.py --slug roadrunningreview
"""
import sys
import os
import json
import webbrowser
import urllib.request
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

THREADS_API  = "https://graph.threads.net"
REDIRECT_URI = "https://www.roadrunningreview.com/auth/threads/callback"
SCOPES       = "threads_basic,threads_manage_insights"

_auth_code = None


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global _auth_code
        params = parse_qs(urlparse(self.path).query)
        if "code" in params:
            _auth_code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"<html><body style='font-family:system-ui;text-align:center;padding:60px'>"
                b"<h2 style='color:#000'>Autorizacion Threads completada</h2>"
                b"<p>Puedes cerrar esta ventana y volver al terminal.</p>"
                b"</body></html>"
            )
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Error: no se recibio el codigo")

    def log_message(self, *args):
        pass


def _threads_get(path, token, params=None):
    p = {"access_token": token}
    if params:
        p.update(params)
    url = f"{THREADS_API}{path}?{urllib.parse.urlencode(p)}"
    with urllib.request.urlopen(url, timeout=15) as r:
        data = json.loads(r.read())
    if "error" in data:
        raise RuntimeError(data["error"].get("message", str(data["error"])))
    return data


def _sep(title=""):
    print("\n" + "─" * 60)
    if title:
        print(f"  {title}")
        print("─" * 60)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", required=True)
    args = parser.parse_args()

    from sqlalchemy.orm import sessionmaker
    from core.settings import get_settings
    from core.crypto import encrypt_token, decrypt_token
    from models.database import create_db_engine, init_db, Medio, TokenCanal

    settings = get_settings()
    engine   = create_db_engine(settings.db_url)
    init_db(engine)
    Session  = sessionmaker(bind=engine)

    def _save(db, medio_id, clave, valor):
        cifrado = encrypt_token(valor, settings.jwt_secret)
        t = db.query(TokenCanal).filter(
            TokenCanal.medio_id == medio_id,
            TokenCanal.canal == "threads",
            TokenCanal.clave == clave,
        ).first()
        if t:
            t.valor_cifrado = cifrado
        else:
            db.add(TokenCanal(medio_id=medio_id, canal="threads",
                              clave=clave, valor_cifrado=cifrado))
        db.commit()

    def _load(db, medio_id, clave):
        t = db.query(TokenCanal).filter(
            TokenCanal.medio_id == medio_id,
            TokenCanal.canal == "threads",
            TokenCanal.clave == clave,
        ).first()
        return decrypt_token(t.valor_cifrado, settings.jwt_secret) if t else None

    with Session() as db:
        medio = db.query(Medio).filter(Medio.slug == args.slug).first()
        if not medio:
            print(f"ERROR: Medio '{args.slug}' no encontrado"); sys.exit(1)

        _sep(f"Autorización Threads — {medio.nombre} ({args.slug})")

        # ── Credenciales de la app ────────────────────────────────────────────
        app_id = _load(db, medio.id, "app_id")
        if not app_id:
            app_id = input("App ID de Threads (developers.facebook.com): ").strip()
            if not app_id: sys.exit(1)
            _save(db, medio.id, "app_id", app_id)

        app_secret = _load(db, medio.id, "app_secret")
        if not app_secret:
            app_secret = input("App Secret de Threads: ").strip()
            if not app_secret: sys.exit(1)
            _save(db, medio.id, "app_secret", app_secret)

        print(f"\n  App ID: {app_id[:10]}…")
        print(f"\n  IMPORTANTE: asegúrate de que esta URI está en Threads App → Redirect URIs:")
        print(f"  {REDIRECT_URI}\n")

        # ── Paso 1: OAuth → código ────────────────────────────────────────────
        _sep("Paso 1: Abrir navegador para autorización")

        auth_url = (
            "https://threads.net/oauth/authorize?"
            + urllib.parse.urlencode({
                "client_id":     app_id,
                "redirect_uri":  REDIRECT_URI,
                "scope":         SCOPES,
                "response_type": "code",
            })
        )

        print("  Abriendo navegador…")
        print(f"  URL manual si no abre: {auth_url}\n")
        webbrowser.open(auth_url)

        print("  El navegador abrirá https://www.roadrunningreview.com/auth/threads/callback")
        print("  La página mostrará el código de autorización. Cópialo y pégalo aquí:\n")
        _auth_code = input("  Código de autorización: ").strip()

        if not _auth_code:
            print("ERROR: No se recibió el código de autorización"); sys.exit(1)
        print(f"  Código recibido OK")

        # ── Paso 2: Código → short-lived token ───────────────────────────────
        _sep("Paso 2: Obtener short-lived token")

        token_data = urllib.parse.urlencode({
            "client_id":     app_id,
            "client_secret": app_secret,
            "redirect_uri":  REDIRECT_URI,
            "code":          _auth_code,
            "grant_type":    "authorization_code",
        }).encode()
        req = urllib.request.Request(
            f"{THREADS_API}/oauth/access_token",
            data=token_data,
            method="POST",
        )
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                tok_resp = json.loads(r.read())
        except Exception as ex:
            print(f"ERROR obteniendo short-lived token: {ex}"); sys.exit(1)

        short_token = tok_resp.get("access_token")
        user_id_from_short = str(tok_resp.get("user_id", ""))
        if not short_token:
            print(f"ERROR: No se obtuvo access_token. Respuesta: {tok_resp}"); sys.exit(1)
        print(f"  Short-lived token: {short_token[:20]}…")
        if user_id_from_short:
            print(f"  User ID (de respuesta): {user_id_from_short}")

        # ── Paso 3: Short-lived → long-lived (60 días) ───────────────────────
        _sep("Paso 3: Convertir a long-lived token (60 días)")

        ll_url = (
            f"{THREADS_API}/access_token?"
            + urllib.parse.urlencode({
                "grant_type":        "th_exchange_token",
                "client_secret":     app_secret,
                "access_token":      short_token,
            })
        )
        try:
            with urllib.request.urlopen(ll_url, timeout=15) as r:
                ll_resp = json.loads(r.read())
        except Exception as ex:
            print(f"ERROR en exchange long-lived: {ex}"); sys.exit(1)

        long_token = ll_resp.get("access_token")
        expires_in = ll_resp.get("expires_in", 0)
        if not long_token:
            print(f"ERROR: No se obtuvo long-lived token. Respuesta: {ll_resp}"); sys.exit(1)
        print(f"  Long-lived token: {long_token[:20]}… (expira en ~{expires_in//86400} días)")

        # ── Paso 4: Obtener Threads User ID ──────────────────────────────────
        _sep("Paso 4: Obtener Threads User ID")

        try:
            me = _threads_get("/v1.0/me", long_token, {"fields": "id,username"})
        except Exception as ex:
            print(f"ERROR obteniendo /me: {ex}"); sys.exit(1)

        threads_user_id = str(me.get("id", ""))
        username = me.get("username", "?")
        if not threads_user_id:
            print(f"ERROR: No se obtuvo user ID. Respuesta: {me}"); sys.exit(1)
        print(f"  Usuario: @{username} (id={threads_user_id})")

        # ── Guardar ───────────────────────────────────────────────────────────
        _sep("Guardando tokens en DB")

        _save(db, medio.id, "access_token",     long_token)
        _save(db, medio.id, "threads_user_id",  threads_user_id)
        _save(db, medio.id, "app_id",           app_id)
        _save(db, medio.id, "app_secret",       app_secret)

        print(f"  threads / access_token      → guardado")
        print(f"  threads / threads_user_id   → {threads_user_id}")
        print(f"  threads / app_id            → guardado")
        print(f"  threads / app_secret        → guardado")

        _sep("Completado")
        print(f"""
  Tokens guardados para '{args.slug}':
    @{username} — Threads User ID: {threads_user_id}
    Long-lived token (~{expires_in//86400} días)

  NOTA: El long-lived token de Threads expira a los 60 días.
  Renovar con:
    GET https://graph.threads.net/refresh_access_token
        ?grant_type=th_refresh_token&access_token={{token}}
  (Planifica un cron de renovación mensual)

  Probar detección:
    python -c "
    import sys; sys.path.insert(0,'.')
    from sqlalchemy.orm import sessionmaker
    from core.settings import get_settings
    from models.database import create_db_engine, Medio
    from agents import threads_agent
    s = get_settings(); db = sessionmaker(bind=create_db_engine(s.db_url))()
    m = db.query(Medio).filter_by(slug='{args.slug}').first()
    pubs = threads_agent.detect_new(db, m, None)
    print(f'Detectadas: {{len(pubs)}}')
    "
""")


if __name__ == "__main__":
    main()
