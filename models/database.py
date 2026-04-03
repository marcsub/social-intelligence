"""
models/database.py
Esquema completo de base de datos MySQL para Social Intelligence System.
Una base de datos compartida con todas las tablas prefijadas por medio.
"""
from datetime import datetime
from typing import Optional
from sqlalchemy import (
    create_engine, Column, String, Integer, Float, Text,
    DateTime, Boolean, ForeignKey, Enum, UniqueConstraint, Index
)
from sqlalchemy.orm import DeclarativeBase, relationship, Session
from sqlalchemy.sql import func
import enum


class Base(DeclarativeBase):
    pass


# ── Enums ────────────────────────────────────────────────────────────────────

class CanalEnum(str, enum.Enum):
    web           = "web"
    instagram_post  = "instagram_post"
    instagram_story = "instagram_story"
    facebook      = "facebook"
    x             = "x"
    tiktok        = "tiktok"
    youtube       = "youtube"
    threads       = "threads"

class TipoEnum(str, enum.Enum):
    articulo = "articulo"
    post     = "post"
    story    = "story"
    reel     = "reel"
    video    = "video"
    tweet    = "tweet"

class EstadoMetricasEnum(str, enum.Enum):
    pendiente   = "pendiente"
    actualizado = "actualizado"
    error       = "error"
    revisar     = "revisar"
    fijo        = "fijo"       # Stories: métricas no se actualizan tras 24h
    sin_datos   = "sin_datos"  # Meta no proporciona insights (post > 24 meses)

class EstadoEntidadEnum(str, enum.Enum):
    activa   = "activa"
    inactiva = "inactiva"

class EstadoMarcaEnum(str, enum.Enum):
    estimated = "estimated"   # Asignada automáticamente con confianza >= 80
    to_review = "to_review"   # Confianza < 80 o sin marca
    ok        = "ok"          # Validada manualmente


# ── Tabla: medios ─────────────────────────────────────────────────────────────

class Medio(Base):
    """
    Cada medio/publicación que gestiona el sistema.
    Ej: ROADRUNNINGReview, medio2, medio3...
    """
    __tablename__ = "medios"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    slug          = Column(String(80), unique=True, nullable=False)   # roadrunningreview
    nombre        = Column(String(200), nullable=False)               # ROADRUNNINGReview
    url_web       = Column(String(500))                               # https://roadrunningreview.com
    rss_url       = Column(String(500))                               # URL del feed RSS
    timezone      = Column(String(50), default="Europe/Madrid")
    activo        = Column(Boolean, default=True)
    created_at    = Column(DateTime, default=func.now())
    updated_at    = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relaciones
    tokens        = relationship("TokenCanal", back_populates="medio", cascade="all, delete-orphan")
    marcas        = relationship("Marca", back_populates="medio", cascade="all, delete-orphan")
    agencias      = relationship("Agencia", back_populates="medio", cascade="all, delete-orphan")
    publicaciones = relationship("Publicacion", back_populates="medio", cascade="all, delete-orphan")
    config        = relationship("ConfigMedio", back_populates="medio", uselist=False, cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Medio {self.slug}>"


# ── Tabla: config_medio ───────────────────────────────────────────────────────

class ConfigMedio(Base):
    """Configuración operativa de cada medio."""
    __tablename__ = "config_medio"

    id                        = Column(Integer, primary_key=True, autoincrement=True)
    medio_id                  = Column(Integer, ForeignKey("medios.id"), unique=True, nullable=False)
    umbral_confianza_marca    = Column(Integer, default=80)     # 0-100
    dias_actualizacion_auto   = Column(Integer, default=30)     # días tras publicación para actualizar
    hora_trigger_diario       = Column(String(5), default="07:00")   # HH:MM
    hora_trigger_stories      = Column(String(5), default="06:00")   # HH:MM — prioritario
    email_alertas_equipo      = Column(String(500))             # emails separados por coma
    ga4_property_id           = Column(String(50))              # 123456789
    youtube_channel_id        = Column(String(50))              # UCxxxxxxx

    medio = relationship("Medio", back_populates="config")


# ── Tabla: tokens_canal ───────────────────────────────────────────────────────

class TokenCanal(Base):
    """
    Tokens y credenciales de API por canal y medio.
    Los valores se almacenan cifrados (Fernet) en la columna valor_cifrado.
    La columna clave identifica qué credencial es.
    """
    __tablename__ = "tokens_canal"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    medio_id       = Column(Integer, ForeignKey("medios.id"), nullable=False)
    canal          = Column(String(40), nullable=False)         # youtube, instagram, x...
    clave          = Column(String(100), nullable=False)        # client_id, access_token...
    valor_cifrado  = Column(Text, nullable=False)               # valor cifrado con Fernet
    updated_at     = Column(DateTime, default=func.now(), onupdate=func.now())

    medio = relationship("Medio", back_populates="tokens")

    __table_args__ = (
        UniqueConstraint("medio_id", "canal", "clave", name="uq_token_medio_canal_clave"),
        Index("ix_tokens_medio_canal", "medio_id", "canal"),
    )


# ── Tabla: marcas ─────────────────────────────────────────────────────────────

class Marca(Base):
    """
    Catálogo de marcas por medio. Editables desde el panel web.
    """
    __tablename__ = "marcas"

    id                  = Column(Integer, primary_key=True, autoincrement=True)
    medio_id            = Column(Integer, ForeignKey("medios.id"), nullable=False)
    nombre_canonico     = Column(String(200), nullable=False)   # Nike Running
    aliases             = Column(Text)                          # Nike,NikeES,@nikerunning (CSV)
    email_contacto      = Column(String(500))                   # email(s) separados por coma
    agencias_habituales = Column(Text)                          # nombres de agencias (CSV)
    estado              = Column(Enum(EstadoEntidadEnum), default=EstadoEntidadEnum.activa)
    notas               = Column(Text)
    created_at          = Column(DateTime, default=func.now())
    updated_at          = Column(DateTime, default=func.now(), onupdate=func.now())

    medio         = relationship("Medio", back_populates="marcas")
    publicaciones = relationship("Publicacion", back_populates="marca_rel")

    __table_args__ = (
        UniqueConstraint("medio_id", "nombre_canonico", name="uq_marca_medio_nombre"),
        Index("ix_marca_medio", "medio_id"),
    )

    def aliases_list(self) -> list[str]:
        if not self.aliases:
            return []
        return [a.strip().lower() for a in self.aliases.split(",") if a.strip()]

    def __repr__(self):
        return f"<Marca {self.nombre_canonico}>"


# ── Tabla: agencias ───────────────────────────────────────────────────────────

class Agencia(Base):
    """
    Catálogo de agencias por medio. Editables desde el panel web.
    """
    __tablename__ = "agencias"

    id                = Column(Integer, primary_key=True, autoincrement=True)
    medio_id          = Column(Integer, ForeignKey("medios.id"), nullable=False)
    nombre_canonico   = Column(String(200), nullable=False)     # Havas Media
    aliases           = Column(Text)                            # Havas,HavasES,@havesmedia (CSV)
    email_contacto    = Column(String(500))
    marcas_habituales = Column(Text)                            # nombres de marcas que gestiona (CSV)
    estado            = Column(Enum(EstadoEntidadEnum), default=EstadoEntidadEnum.activa)
    notas             = Column(Text)
    created_at        = Column(DateTime, default=func.now())
    updated_at        = Column(DateTime, default=func.now(), onupdate=func.now())

    medio         = relationship("Medio", back_populates="agencias")
    publicaciones = relationship("Publicacion", back_populates="agencia_rel")

    __table_args__ = (
        UniqueConstraint("medio_id", "nombre_canonico", name="uq_agencia_medio_nombre"),
        Index("ix_agencia_medio", "medio_id"),
    )

    def aliases_list(self) -> list[str]:
        if not self.aliases:
            return []
        return [a.strip().lower() for a in self.aliases.split(",") if a.strip()]

    def __repr__(self):
        return f"<Agencia {self.nombre_canonico}>"


# ── Tabla: publicaciones ──────────────────────────────────────────────────────

class Publicacion(Base):
    """
    Registro central de publicaciones. Una fila = una publicación en un canal.
    Las comparativas multi-marca generan varias filas con el mismo
    id_externo + sufijo (_1, _2...).
    """
    __tablename__ = "publicaciones"

    id                  = Column(Integer, primary_key=True, autoincrement=True)
    medio_id            = Column(Integer, ForeignKey("medios.id"), nullable=False)
    marca_id            = Column(Integer, ForeignKey("marcas.id"), nullable=True)   # null si estado=revisar
    agencia_id          = Column(Integer, ForeignKey("agencias.id"), nullable=True)

    # Identificación
    id_externo          = Column(String(200))                   # ID de la plataforma (video_id, post_id...)
    campana             = Column(String(200))                   # Nike_2026
    canal               = Column(Enum(CanalEnum), nullable=False)
    tipo                = Column(Enum(TipoEnum), nullable=False)
    url                 = Column(String(1000), nullable=False)
    titulo              = Column(String(500))                   # título del artículo o vídeo
    fecha_publicacion   = Column(DateTime, nullable=False)

    # Métricas
    reach               = Column(Integer, default=0)
    likes               = Column(Integer, default=0)
    shares              = Column(Integer, default=0)
    comments            = Column(Integer, default=0)
    clicks              = Column(Integer, default=0)
    ga4_sessions        = Column(Integer, default=0)
    ga4_users           = Column(Integer, default=0)

    # Control
    estado_metricas     = Column(Enum(EstadoMetricasEnum), default=EstadoMetricasEnum.pendiente)
    confianza_marca     = Column(Integer, nullable=True)        # 0-100, null si manual
    estado_marca        = Column(Enum(EstadoMarcaEnum), nullable=True)  # estimated | to_review | ok
    ultima_actualizacion = Column(DateTime, nullable=True)
    captura_url         = Column(String(1000))                  # ruta local captura / link Drive
    notas               = Column(Text)
    fecha_insercion     = Column(DateTime, default=func.now())

    # Relaciones
    medio      = relationship("Medio", back_populates="publicaciones")
    marca_rel  = relationship("Marca", back_populates="publicaciones")
    agencia_rel = relationship("Agencia", back_populates="publicaciones")
    historial  = relationship("HistorialMetricas", back_populates="publicacion", cascade="all, delete-orphan")
    pub_marcas = relationship("PublicacionMarca", back_populates="publicacion", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_pub_medio_fecha", "medio_id", "fecha_publicacion"),
        Index("ix_pub_marca", "marca_id"),
        Index("ix_pub_agencia", "agencia_id"),
        Index("ix_pub_canal", "canal"),
        Index("ix_pub_estado", "estado_metricas"),
    )

    def __repr__(self):
        return f"<Publicacion {self.canal} {self.url[:40]}>"


# ── Tabla: publicacion_marcas ─────────────────────────────────────────────────

class PublicacionMarca(Base):
    """
    Relación N:M entre publicaciones y marcas.
    Una publicación puede asociarse a varias marcas (comparativas, co-branding).
    La primera con es_principal=True es la marca principal para analytics.
    """
    __tablename__ = "publicacion_marcas"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    publicacion_id  = Column(Integer, ForeignKey("publicaciones.id"), nullable=False)
    marca_id        = Column(Integer, ForeignKey("marcas.id"), nullable=False)
    es_principal    = Column(Boolean, default=True)

    publicacion = relationship("Publicacion", back_populates="pub_marcas")
    marca       = relationship("Marca")

    __table_args__ = (
        UniqueConstraint("publicacion_id", "marca_id", name="uq_pub_marca"),
        Index("ix_pub_marcas_pub", "publicacion_id"),
    )


# ── Tabla: historial_metricas ─────────────────────────────────────────────────

class HistorialMetricas(Base):
    """
    Snapshot de métricas en cada actualización.
    Permite ver la evolución del reach de una publicación en el tiempo.
    """
    __tablename__ = "historial_metricas"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    publicacion_id  = Column(Integer, ForeignKey("publicaciones.id"), nullable=False)
    semana_iso      = Column(String(8), nullable=True)   # YYYY-WNN, ej: 2026-W13
    fecha_snapshot  = Column(DateTime, default=func.now())

    # Valores acumulados en ese momento
    reach           = Column(Integer, default=0)
    likes           = Column(Integer, default=0)
    shares          = Column(Integer, default=0)
    comments        = Column(Integer, default=0)
    clicks          = Column(Integer, default=0)         # solo web/GA4

    # Diferencial vs semana anterior
    reach_diff      = Column(Integer, default=0)
    likes_diff      = Column(Integer, default=0)
    shares_diff     = Column(Integer, default=0)
    comments_diff   = Column(Integer, default=0)
    clicks_diff     = Column(Integer, default=0)

    fuente          = Column(String(20), default="api")  # 'api' | 'ga4' | 'manual'

    # Stories: snapshot preciso por hora (no por semana ISO)
    hora_snapshot   = Column(DateTime, nullable=True)
    es_final        = Column(Boolean, default=False)     # True = última captura antes de caducar

    publicacion = relationship("Publicacion", back_populates="historial")

    __table_args__ = (
        Index("ix_historial_pub", "publicacion_id"),
        UniqueConstraint("publicacion_id", "semana_iso", name="uq_historial_pub_semana"),
    )


# ── Tabla: log_ejecuciones ────────────────────────────────────────────────────

class LogEjecucion(Base):
    """Registro de cada ejecución del orquestador por medio y agente."""
    __tablename__ = "log_ejecuciones"

    id                  = Column(Integer, primary_key=True, autoincrement=True)
    medio_id            = Column(Integer, ForeignKey("medios.id"), nullable=False)
    agente              = Column(String(50))                    # web, youtube, instagram...
    tipo_ejecucion      = Column(String(30))                    # diario, mensual, manual
    inicio              = Column(DateTime, default=func.now())
    fin                 = Column(DateTime, nullable=True)
    publicaciones_nuevas = Column(Integer, default=0)
    publicaciones_actualizadas = Column(Integer, default=0)
    publicaciones_revision = Column(Integer, default=0)
    emails_enviados     = Column(Integer, default=0)
    errores             = Column(Text)                          # JSON con errores capturados
    estado              = Column(String(20), default="corriendo")  # corriendo | ok | error

    __table_args__ = (
        Index("ix_log_medio_inicio", "medio_id", "inicio"),
    )


# ── Factory de engine ─────────────────────────────────────────────────────────

def create_db_engine(db_url: str):
    return create_engine(
        db_url,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
        echo=False,
    )

def init_db(engine):
    """Crea todas las tablas si no existen."""
    Base.metadata.create_all(engine)
