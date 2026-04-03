"""
api/routes/medios.py
CRUD completo para medios, marcas, agencias y tokens.
Todas las rutas requieren autenticación JWT.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Optional
from pydantic import BaseModel
from api.auth import get_current_user
from core.settings import get_settings
from core.crypto import encrypt_token, decrypt_token
from models.database import (
    Medio, ConfigMedio, Marca, Agencia, TokenCanal,
    EstadoEntidadEnum
)

router = APIRouter(prefix="/api", tags=["medios"])

# ── Dependency: DB session ────────────────────────────────────────────────────

def get_db():
    from main import SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

Auth = Depends(get_current_user)


# ── Schemas ───────────────────────────────────────────────────────────────────

class MedioCreate(BaseModel):
    slug: str
    nombre: str
    url_web: Optional[str] = None
    rss_url: Optional[str] = None
    timezone: str = "Europe/Madrid"

class MedioUpdate(BaseModel):
    nombre: Optional[str] = None
    url_web: Optional[str] = None
    rss_url: Optional[str] = None
    timezone: Optional[str] = None
    activo: Optional[bool] = None

class ConfigUpdate(BaseModel):
    umbral_confianza_marca: Optional[int] = None
    dias_actualizacion_auto: Optional[int] = None
    hora_trigger_diario: Optional[str] = None
    hora_trigger_stories: Optional[str] = None
    email_alertas_equipo: Optional[str] = None
    ga4_property_id: Optional[str] = None
    youtube_channel_id: Optional[str] = None

class MarcaCreate(BaseModel):
    nombre_canonico: str
    aliases: Optional[str] = None
    email_contacto: Optional[str] = None
    agencias_habituales: Optional[str] = None
    notas: Optional[str] = None

class MarcaUpdate(BaseModel):
    nombre_canonico: Optional[str] = None
    aliases: Optional[str] = None
    email_contacto: Optional[str] = None
    agencias_habituales: Optional[str] = None
    estado: Optional[EstadoEntidadEnum] = None
    notas: Optional[str] = None

class AgenciaCreate(BaseModel):
    nombre_canonico: str
    aliases: Optional[str] = None
    email_contacto: Optional[str] = None
    marcas_habituales: Optional[str] = None
    notas: Optional[str] = None

class AgenciaUpdate(BaseModel):
    nombre_canonico: Optional[str] = None
    aliases: Optional[str] = None
    email_contacto: Optional[str] = None
    marcas_habituales: Optional[str] = None
    estado: Optional[EstadoEntidadEnum] = None
    notas: Optional[str] = None

class TokenSet(BaseModel):
    canal: str
    clave: str
    valor: str   # valor en claro — se cifra antes de guardar


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_medio_or_404(slug: str, db: Session) -> Medio:
    medio = db.query(Medio).filter(Medio.slug == slug).first()
    if not medio:
        raise HTTPException(status_code=404, detail=f"Medio '{slug}' no encontrado")
    return medio

def medio_to_dict(m: Medio) -> dict:
    return {
        "id": m.id, "slug": m.slug, "nombre": m.nombre,
        "url_web": m.url_web, "rss_url": m.rss_url,
        "timezone": m.timezone, "activo": m.activo,
        "created_at": m.created_at, "updated_at": m.updated_at,
    }

def marca_to_dict(m: Marca) -> dict:
    return {
        "id": m.id, "nombre_canonico": m.nombre_canonico,
        "aliases": m.aliases, "email_contacto": m.email_contacto,
        "agencias_habituales": m.agencias_habituales,
        "estado": m.estado, "notas": m.notas,
        "created_at": m.created_at, "updated_at": m.updated_at,
    }

def agencia_to_dict(a: Agencia) -> dict:
    return {
        "id": a.id, "nombre_canonico": a.nombre_canonico,
        "aliases": a.aliases, "email_contacto": a.email_contacto,
        "marcas_habituales": a.marcas_habituales,
        "estado": a.estado, "notas": a.notas,
        "created_at": a.created_at, "updated_at": a.updated_at,
    }


# ── Medios ────────────────────────────────────────────────────────────────────

@router.get("/medios")
async def list_medios(db: Session = Depends(get_db), _=Auth):
    return [medio_to_dict(m) for m in db.query(Medio).all()]

@router.post("/medios", status_code=201)
async def create_medio(data: MedioCreate, db: Session = Depends(get_db), _=Auth):
    if db.query(Medio).filter(Medio.slug == data.slug).first():
        raise HTTPException(400, f"Ya existe un medio con slug '{data.slug}'")
    medio = Medio(**data.model_dump())
    db.add(medio)
    db.flush()
    # Config por defecto
    db.add(ConfigMedio(medio_id=medio.id))
    db.commit()
    db.refresh(medio)
    return medio_to_dict(medio)

@router.get("/medios/{slug}")
async def get_medio(slug: str, db: Session = Depends(get_db), _=Auth):
    return medio_to_dict(get_medio_or_404(slug, db))

@router.patch("/medios/{slug}")
async def update_medio(slug: str, data: MedioUpdate, db: Session = Depends(get_db), _=Auth):
    medio = get_medio_or_404(slug, db)
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(medio, k, v)
    db.commit()
    db.refresh(medio)
    return medio_to_dict(medio)

@router.delete("/medios/{slug}", status_code=204)
async def delete_medio(slug: str, db: Session = Depends(get_db), _=Auth):
    medio = get_medio_or_404(slug, db)
    db.delete(medio)
    db.commit()

# Config
@router.get("/medios/{slug}/config")
async def get_config(slug: str, db: Session = Depends(get_db), _=Auth):
    medio = get_medio_or_404(slug, db)
    c = medio.config
    if not c:
        raise HTTPException(404, "Config no encontrada")
    return {k: v for k, v in vars(c).items() if not k.startswith("_")}

@router.patch("/medios/{slug}/config")
async def update_config(slug: str, data: ConfigUpdate, db: Session = Depends(get_db), _=Auth):
    medio = get_medio_or_404(slug, db)
    c = medio.config
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(c, k, v)
    db.commit()
    db.refresh(c)
    return {k: v for k, v in vars(c).items() if not k.startswith("_")}


# ── Marcas ────────────────────────────────────────────────────────────────────

@router.get("/medios/{slug}/marcas")
async def list_marcas(slug: str, db: Session = Depends(get_db), _=Auth):
    medio = get_medio_or_404(slug, db)
    return [marca_to_dict(m) for m in medio.marcas]

@router.post("/medios/{slug}/marcas", status_code=201)
async def create_marca(slug: str, data: MarcaCreate, db: Session = Depends(get_db), _=Auth):
    medio = get_medio_or_404(slug, db)
    existing = db.query(Marca).filter(
        Marca.medio_id == medio.id,
        Marca.nombre_canonico == data.nombre_canonico
    ).first()
    if existing:
        raise HTTPException(400, f"Ya existe la marca '{data.nombre_canonico}' en este medio")
    marca = Marca(medio_id=medio.id, **data.model_dump())
    db.add(marca)
    db.commit()
    db.refresh(marca)
    return marca_to_dict(marca)

@router.get("/medios/{slug}/marcas/{marca_id}")
async def get_marca(slug: str, marca_id: int, db: Session = Depends(get_db), _=Auth):
    medio = get_medio_or_404(slug, db)
    marca = db.query(Marca).filter(Marca.id == marca_id, Marca.medio_id == medio.id).first()
    if not marca:
        raise HTTPException(404, "Marca no encontrada")
    return marca_to_dict(marca)

@router.patch("/medios/{slug}/marcas/{marca_id}")
async def update_marca(slug: str, marca_id: int, data: MarcaUpdate, db: Session = Depends(get_db), _=Auth):
    medio = get_medio_or_404(slug, db)
    marca = db.query(Marca).filter(Marca.id == marca_id, Marca.medio_id == medio.id).first()
    if not marca:
        raise HTTPException(404, "Marca no encontrada")
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(marca, k, v)
    db.commit()
    db.refresh(marca)
    return marca_to_dict(marca)

@router.delete("/medios/{slug}/marcas/{marca_id}", status_code=204)
async def delete_marca(slug: str, marca_id: int, db: Session = Depends(get_db), _=Auth):
    medio = get_medio_or_404(slug, db)
    marca = db.query(Marca).filter(Marca.id == marca_id, Marca.medio_id == medio.id).first()
    if not marca:
        raise HTTPException(404, "Marca no encontrada")
    db.delete(marca)
    db.commit()


# ── Agencias ──────────────────────────────────────────────────────────────────

@router.get("/medios/{slug}/agencias")
async def list_agencias(slug: str, db: Session = Depends(get_db), _=Auth):
    medio = get_medio_or_404(slug, db)
    return [agencia_to_dict(a) for a in medio.agencias]

@router.post("/medios/{slug}/agencias", status_code=201)
async def create_agencia(slug: str, data: AgenciaCreate, db: Session = Depends(get_db), _=Auth):
    medio = get_medio_or_404(slug, db)
    existing = db.query(Agencia).filter(
        Agencia.medio_id == medio.id,
        Agencia.nombre_canonico == data.nombre_canonico
    ).first()
    if existing:
        raise HTTPException(400, f"Ya existe la agencia '{data.nombre_canonico}'")
    agencia = Agencia(medio_id=medio.id, **data.model_dump())
    db.add(agencia)
    db.commit()
    db.refresh(agencia)
    return agencia_to_dict(agencia)

@router.patch("/medios/{slug}/agencias/{agencia_id}")
async def update_agencia(slug: str, agencia_id: int, data: AgenciaUpdate, db: Session = Depends(get_db), _=Auth):
    medio = get_medio_or_404(slug, db)
    agencia = db.query(Agencia).filter(Agencia.id == agencia_id, Agencia.medio_id == medio.id).first()
    if not agencia:
        raise HTTPException(404, "Agencia no encontrada")
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(agencia, k, v)
    db.commit()
    db.refresh(agencia)
    return agencia_to_dict(agencia)

@router.delete("/medios/{slug}/agencias/{agencia_id}", status_code=204)
async def delete_agencia(slug: str, agencia_id: int, db: Session = Depends(get_db), _=Auth):
    medio = get_medio_or_404(slug, db)
    agencia = db.query(Agencia).filter(Agencia.id == agencia_id, Agencia.medio_id == medio.id).first()
    if not agencia:
        raise HTTPException(404, "Agencia no encontrada")
    db.delete(agencia)
    db.commit()


# ── Tokens ────────────────────────────────────────────────────────────────────

@router.get("/medios/{slug}/tokens")
async def list_tokens(slug: str, db: Session = Depends(get_db), _=Auth):
    """Lista tokens configurados (sin revelar valores)."""
    medio = get_medio_or_404(slug, db)
    return [
        {"canal": t.canal, "clave": t.clave, "configurado": True, "updated_at": t.updated_at}
        for t in medio.tokens
    ]

@router.put("/medios/{slug}/tokens")
async def set_token(slug: str, data: TokenSet, db: Session = Depends(get_db), _=Auth):
    """Crea o actualiza un token cifrado para un canal."""
    medio = get_medio_or_404(slug, db)
    settings = get_settings()
    cifrado = encrypt_token(data.valor, settings.jwt_secret)

    token = db.query(TokenCanal).filter(
        TokenCanal.medio_id == medio.id,
        TokenCanal.canal == data.canal,
        TokenCanal.clave == data.clave
    ).first()

    if token:
        token.valor_cifrado = cifrado
    else:
        token = TokenCanal(
            medio_id=medio.id,
            canal=data.canal,
            clave=data.clave,
            valor_cifrado=cifrado
        )
        db.add(token)
    db.commit()
    return {"canal": data.canal, "clave": data.clave, "configurado": True}

@router.delete("/medios/{slug}/tokens/{canal}/{clave}", status_code=204)
async def delete_token(slug: str, canal: str, clave: str, db: Session = Depends(get_db), _=Auth):
    medio = get_medio_or_404(slug, db)
    token = db.query(TokenCanal).filter(
        TokenCanal.medio_id == medio.id,
        TokenCanal.canal == canal,
        TokenCanal.clave == clave
    ).first()
    if not token:
        raise HTTPException(404, "Token no encontrado")
    db.delete(token)
    db.commit()
