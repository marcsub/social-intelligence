"""
scripts/authorize_facebook.py
Obtiene un Page Access Token permanente para Facebook via OAuth 2.0.

El Page Access Token derivado de un long-lived User Token no expira nunca.
Ejecutar cuando:
  - El token actual falla o ha caducado
  - Primera configuración de Facebook insights
  - Tras regenerar el token en Meta Business Suite

Prerequisitos:
  - App ID y App Secret guardados en DB (los crea authorize_meta.py)
  - La app Meta tiene https://localhost:8000/auth/facebook/callback como
    URI de redirección válida (Meta Developer → App → Facebook Login → Configuración)

Uso:
    python scripts/authorize_facebook.py --slug roadrunningreview
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

GRAPH        = "https://graph.facebook.com/v25.0"
REDIRECT_URI = "http://localhost:8000/auth/facebook/callback"
SCOPES       = [
    "pages_read_engagement",
    "pages_show_list",
    "read_insights",
    "pages_manage_metadata",
]

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
                b"<h2 style='color:#1877f2'>Autorizacion Facebook completada</h2>"
                b"<p>Puedes cerrar esta ventana y volver al terminal.</p>"
                b"</body></html>"
            )
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Error: no se recibio el codigo")

    def log_message(self, *args):
        pass


def _graph_get(path, token, params=None):
    p = {"access_token": token}
    if params:
        p.update(params)
    url = f"{GRAPH}{path}?{urllib.parse.urlencode(p)}"
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
            TokenCanal.canal == "facebook",
            TokenCanal.clave == clave,
        ).first()
        if t:
            t.valor_cifrado = cifrado
        else:
            db.add(TokenCanal(medio_id=medio_id, canal="facebook",
                              clave=clave, valor_cifrado=cifrado))
        db.commit()

    def _load(db, medio_id, clave):
        t = db.query(TokenCanal).filter(
            TokenCanal.medio_id == medio_id,
            TokenCanal.canal == "facebook",
            TokenCanal.clave == clave,
        ).first()
        return decrypt_token(t.valor_cifrado, settings.jwt_secret) if t else None

    with Session() as db:
        medio = db.query(Medio).filter(Medio.slug == args.slug).first()
        if not medio:
            print(f"ERROR: Medio '{args.slug}' no encontrado"); sys.exit(1)

        _sep(f"Autorización Facebook Page Token — {medio.nombre} ({args.slug})")

        # ── App credentials ───────────────────────────────────────────────────
        app_id = _load(db, medio.id, "app_id") or _load(db, medio.id, "app_id")
        if not app_id:
            # Intentar también desde el canal instagram (authorize_meta los guarda ahí)
            t = db.query(TokenCanal).filter(
                TokenCanal.medio_id == medio.id,
                TokenCanal.canal == "instagram",
                TokenCanal.clave == "app_id",
            ).first()
            app_id = decrypt_token(t.valor_cifrado, settings.jwt_secret) if t else None

        app_secret = _load(db, medio.id, "app_secret")
        if not app_secret:
            t = db.query(TokenCanal).filter(
                TokenCanal.medio_id == medio.id,
                TokenCanal.canal == "instagram",
                TokenCanal.clave == "app_secret",
            ).first()
            app_secret = decrypt_token(t.valor_cifrado, settings.jwt_secret) if t else None

        if not app_id:
            app_id = input("App ID (Meta Developer Console): ").strip()
            if not app_id: sys.exit(1)
            _save(db, medio.id, "app_id", app_id)

        if not app_secret:
            app_secret = input("App Secret (Meta Developer Console): ").strip()
            if not app_secret: sys.exit(1)
            _save(db, medio.id, "app_secret", app_secret)

        page_id = _load(db, medio.id, "page_id")
        if not page_id:
            page_id = input("Page ID de la página de Facebook: ").strip()
            if not page_id: sys.exit(1)
            _save(db, medio.id, "page_id", page_id)

        print(f"\n  App ID:  {app_id[:10]}…")
        print(f"  Page ID: {page_id}")
        print(f"\n  IMPORTANTE: asegúrate de que esta URI está en Meta Developer")
        print(f"  → App → Facebook Login → OAuth Redirect URIs:")
        print(f"  {REDIRECT_URI}\n")

        # ── Paso 1: OAuth → código ────────────────────────────────────────────
        _sep("Paso 1: Abrir navegador para autorización")

        auth_url = (
            f"https://www.facebook.com/v25.0/dialog/oauth?"
            + urllib.parse.urlencode({
                "client_id":     app_id,
                "redirect_uri":  REDIRECT_URI,
                "scope":         ",".join(SCOPES),
                "response_type": "code",
            })
        )

        print("  Abriendo navegador…")
        print(f"  URL manual si no abre: {auth_url}\n")
        webbrowser.open(auth_url)

        print("  Esperando callback en http://localhost:8000 …")
        HTTPServer(("localhost", 8000), _CallbackHandler).handle_request()

        if not _auth_code:
            print("ERROR: No se recibió el código de autorización"); sys.exit(1)
        print(f"  Código recibido OK")

        # ── Paso 2: Código → short-lived user token ───────────────────────────
        _sep("Paso 2: Obtener short-lived user token")

        token_data = urllib.parse.urlencode({
            "client_id":     app_id,
            "client_secret": app_secret,
            "redirect_uri":  REDIRECT_URI,
            "code":          _auth_code,
        }).encode()
        req = urllib.request.Request(
            f"{GRAPH}/oauth/access_token",
            data=token_data,
            method="POST",
        )
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                tok_resp = json.loads(r.read())
        except Exception as ex:
            print(f"ERROR obteniendo token: {ex}"); sys.exit(1)

        short_token = tok_resp.get("access_token")
        if not short_token:
            print(f"ERROR: No se obtuvo access_token. Respuesta: {tok_resp}"); sys.exit(1)
        print(f"  Short-lived user token: {short_token[:20]}…")

        # ── Paso 3: Short-lived → long-lived user token (60 días) ────────────
        _sep("Paso 3: Convertir a long-lived user token (60 días)")

        ll_url = (
            f"{GRAPH}/oauth/access_token?"
            + urllib.parse.urlencode({
                "grant_type":        "fb_exchange_token",
                "client_id":         app_id,
                "client_secret":     app_secret,
                "fb_exchange_token": short_token,
            })
        )
        try:
            with urllib.request.urlopen(ll_url, timeout=15) as r:
                ll_resp = json.loads(r.read())
        except Exception as ex:
            print(f"ERROR en exchange long-lived: {ex}"); sys.exit(1)

        long_token  = ll_resp.get("access_token")
        expires_in  = ll_resp.get("expires_in", 0)
        if not long_token:
            print(f"ERROR: No se obtuvo long-lived token. Respuesta: {ll_resp}"); sys.exit(1)
        print(f"  Long-lived user token: {long_token[:20]}… (expira en ~{expires_in//86400} días)")

        # ── Paso 4: Obtener Page Access Token permanente ──────────────────────
        _sep("Paso 4: Obtener Page Access Token permanente")

        try:
            page_info = _graph_get(f"/{page_id}", long_token, {"fields": "access_token,name"})
        except RuntimeError as ex:
            print(f"ERROR obteniendo page token: {ex}")
            print("  El token no tiene acceso a esta página o falta pages_show_list")
            sys.exit(1)

        page_token = page_info.get("access_token")
        page_name  = page_info.get("name", "?")

        if not page_token:
            print(f"ERROR: No se obtuvo page_access_token. Respuesta: {page_info}")
            print("  Asegúrate de que el usuario que autorizó es administrador de la página.")
            sys.exit(1)

        print(f"  Página: {page_name} (id={page_id})")
        print(f"  Page Access Token (permanente): {page_token[:20]}…")

        # ── Paso 5: Verificar que el token tiene insights ─────────────────────
        _sep("Paso 5: Verificar permisos del token")

        try:
            perms_data = _graph_get("/me/permissions", page_token)
            granted = [p["permission"] for p in perms_data.get("data", [])
                       if p.get("status") == "granted"]
            needed = ["pages_read_engagement", "pages_show_list", "read_insights"]
            all_ok = True
            for perm in needed:
                mark = "✓" if perm in granted else "✗ FALTA"
                print(f"  {mark} {perm}")
                if perm not in granted:
                    all_ok = False
            if not all_ok:
                print("\n  ⚠ Permisos incompletos — los insights pueden no funcionar.")
                print("  Vuelve a ejecutar este script y asegúrate de autorizar todos los permisos.")
        except Exception as ex:
            print(f"  No se pudo verificar permisos: {ex}")

        # ── Guardar ───────────────────────────────────────────────────────────
        _sep("Guardando tokens")

        _save(db, medio.id, "page_access_token", page_token)
        print(f"  facebook / page_access_token → guardado")

        # Actualizar también access_token con el page token para compatibilidad
        _save(db, medio.id, "access_token", page_token)
        print(f"  facebook / access_token → actualizado con page token")

        _sep("Completado")
        print(f"""
  Tokens guardados para '{args.slug}':
    page_access_token : OK (permanente — no expira)
    access_token      : actualizado al page token

  El agente Facebook ya puede obtener insights.
  Ejecutar backfill de reach:
    python scripts/fix_facebook_reach.py --slug {args.slug}
""")


if __name__ == "__main__":
    main()
