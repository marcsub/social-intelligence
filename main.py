"""
main.py — Punto de entrada de la aplicación Social Intelligence System.
"""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import sessionmaker

from core.settings import get_settings
from core.orchestrator import setup_scheduler, run_daily, run_update_by_marca
from models.database import create_db_engine, init_db, Medio
from api.auth import router as auth_router
from api.routes.medios import router as medios_router
from api.routes.publicaciones import router as publicaciones_router

# ── Logging ───────────────────────────────────────────────────────────────────
settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s"
)
log = logging.getLogger(__name__)

# ── DB ────────────────────────────────────────────────────────────────────────
engine = create_db_engine(settings.db_url)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# ── App lifecycle ─────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Iniciando Social Intelligence System...")
    init_db(engine)
    log.info("Base de datos inicializada")
    scheduler = setup_scheduler(SessionLocal)
    yield
    scheduler.shutdown(wait=False)
    log.info("Apagando aplicación")

# ── FastAPI ───────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Social Intelligence System",
    description="Gestión multi-medio de publicaciones y métricas en redes sociales",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs" if settings.environment != "production" else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(auth_router)
app.include_router(medios_router)
app.include_router(publicaciones_router)

@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}


# Servir capturas de stories (imágenes locales)
import os as _os
_stories_dir = "stories_images"
if not _os.path.exists(_stories_dir):
    _os.makedirs(_stories_dir, exist_ok=True)
app.mount("/stories_images", StaticFiles(directory=_stories_dir), name="stories_images")


# ── Rutas de ejecución manual del orquestador ─────────────────────────────────
from api.auth import get_current_user
from fastapi import Depends

@app.post("/api/medios/{slug}/run")
async def run_now(slug: str, _=Depends(get_current_user)):
    """Ejecuta el ciclo diario completo para un medio manualmente."""
    db = SessionLocal()
    try:
        medio = db.query(Medio).filter(Medio.slug == slug).first()
        if not medio:
            from fastapi import HTTPException
            raise HTTPException(404, f"Medio '{slug}' no encontrado")
        result = run_daily(db, medio)
        return {"ok": True, "resultado": result}
    finally:
        db.close()


@app.get("/api/auth/tiktok/callback")
async def tiktok_callback(code: str = None, error: str = None, state: str = None):
    """
    Callback OAuth TikTok. TikTok redirige aquí con el código de autorización.
    Muestra el código en pantalla para que el usuario lo copie en el script
    authorize_tiktok.py.
    No requiere autenticación JWT — es el destino de redirección del navegador.
    """
    if error:
        html = f"""<html><body style="font-family:system-ui;text-align:center;padding:60px">
        <h2 style="color:#e53e3e">&#9888; Error en autorización TikTok</h2>
        <p><b>Error:</b> {error}</p>
        <p>Cierra esta ventana y revisa la configuración de la app en TikTok for Developers.</p>
        </body></html>"""
        from fastapi.responses import HTMLResponse
        return HTMLResponse(html, status_code=400)

    if not code:
        from fastapi.responses import HTMLResponse
        return HTMLResponse("<html><body><p>Sin código de autorización.</p></body></html>", status_code=400)

    html = f"""<html>
    <head><title>TikTok autorizado</title></head>
    <body style="font-family:system-ui;max-width:600px;margin:60px auto;text-align:center">
      <h2 style="color:#010101">&#9654; Autorización TikTok completada</h2>
      <p>Copia el siguiente código y pégalo en la terminal donde está esperando el script:</p>
      <div style="background:#f4f4f5;border:1px solid #ddd;border-radius:8px;padding:20px;margin:24px 0;word-break:break-all;font-family:monospace;font-size:14px;text-align:left">
        {code}
      </div>
      <button onclick="navigator.clipboard.writeText('{code}')"
              style="background:#010101;color:white;border:none;padding:10px 24px;border-radius:6px;cursor:pointer;font-size:14px">
        Copiar código
      </button>
      <p style="color:#888;margin-top:32px;font-size:13px">Puedes cerrar esta ventana una vez pegado el código.</p>
    </body></html>"""
    from fastapi.responses import HTMLResponse
    return HTMLResponse(html)


@app.post("/api/medios/{slug}/update-marca/{marca_id}")
async def update_marca(slug: str, marca_id: int, _=Depends(get_current_user)):
    """Actualiza métricas de todas las publicaciones de una marca."""
    db = SessionLocal()
    try:
        medio = db.query(Medio).filter(Medio.slug == slug).first()
        if not medio:
            from fastapi import HTTPException
            raise HTTPException(404, f"Medio '{slug}' no encontrado")
        result = run_update_by_marca(db, medio, marca_id)
        return {"ok": True, "resultado": result}
    finally:
        db.close()
