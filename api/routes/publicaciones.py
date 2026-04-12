"""
api/routes/publicaciones.py
Endpoints de publicaciones y analytics para un medio.
Todas las rutas requieren autenticación JWT.
"""
import logging
log = logging.getLogger(__name__)
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional, List
from sqlalchemy import or_, and_
from datetime import date, datetime, timedelta, timezone
from collections import defaultdict
from pydantic import BaseModel
from api.auth import get_current_user
from models.database import (
    Medio, Publicacion, Marca, Agencia, HistorialMetricas, PublicacionMarca,
    CanalEnum, TipoEnum, EstadoMetricasEnum, EstadoMarcaEnum
)

router = APIRouter(prefix="/api", tags=["publicaciones"])


def get_db():
    from main import SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


Auth = Depends(get_current_user)


def get_medio_or_404(slug: str, db: Session) -> Medio:
    m = db.query(Medio).filter(Medio.slug == slug).first()
    if not m:
        raise HTTPException(404, f"Medio '{slug}' no encontrado")
    return m


_INTENTOS_PREFIX = "intentos_fallidos:"

def _parse_intentos(notas) -> int:
    if not notas:
        return 0
    for part in str(notas).split("|"):
        if part.startswith(_INTENTOS_PREFIX):
            try:
                return int(part[len(_INTENTOS_PREFIX):])
            except ValueError:
                pass
    return 0


def _pub_item(p: Publicacion, marcas_map: dict, agencias_map: dict, pub_marcas_map: dict = None, story_snapshots: dict = None) -> dict:
    # Multi-marca: IDs y nombres ordenados (principal primero)
    pm_entries = sorted(pub_marcas_map.get(p.id, []), key=lambda x: (not x[1], x[0])) if pub_marcas_map else []
    marcas_ids = [m[0] for m in pm_entries]
    marcas_nombres = [marcas_map.get(m[0]) for m in pm_entries if m[0] in marcas_map]
    # Fallback: si publicacion_marcas vacío, usar marca_id directo
    if not marcas_ids and p.marca_id:
        marcas_ids = [p.marca_id]
        marcas_nombres = [marcas_map.get(p.marca_id)]
    snap = (story_snapshots or {}).get(p.id)
    return {
        "id": p.id,
        "fecha_publicacion": p.fecha_publicacion.isoformat() if p.fecha_publicacion else None,
        "canal": p.canal.value if p.canal else None,
        "tipo": p.tipo.value if p.tipo else None,
        "url": p.url,
        "titulo": p.titulo,
        "marca_id": p.marca_id,
        "marca_nombre": marcas_map.get(p.marca_id),
        "marcas_ids": marcas_ids,
        "marcas_nombres": [n for n in marcas_nombres if n],
        "agencia_nombre": agencias_map.get(p.agencia_id),
        "reach": p.reach or 0,
        "likes": p.likes or 0,
        "shares": p.shares or 0,
        "comments": p.comments or 0,
        "inversion_pagada": float(p.inversion_pagada) if p.inversion_pagada is not None else None,
        "reach_pagado": p.reach_pagado or 0,
        "estado_metricas": p.estado_metricas.value if p.estado_metricas else None,
        "confianza_marca": p.confianza_marca,
        "estado_marca": p.estado_marca.value if p.estado_marca else None,
        "captura_url": p.captura_url,
        "texto": p.texto or None,
        "ultima_actualizacion": p.ultima_actualizacion.isoformat() if p.ultima_actualizacion else None,
        "intentos_fallidos": _parse_intentos(p.notas),
        "es_final": snap["es_final"] if snap else False,
        "hora_ultima_captura": snap["hora_snapshot"] if snap else None,
    }


def _periodo_filtro(periodo: Optional[str], fecha_desde: Optional[date], fecha_hasta: Optional[date]):
    now = datetime.now(timezone.utc)
    if fecha_desde and fecha_hasta:
        fd = datetime.combine(fecha_desde, datetime.min.time()).replace(tzinfo=timezone.utc)
        fh = datetime.combine(fecha_hasta, datetime.max.time()).replace(tzinfo=timezone.utc)
        return fd, fh
    dias = {"3m": 90, "6m": 180, "12m": 365}.get(periodo or "3m", 90)
    return now - timedelta(days=dias), now


def _marca_analytics(db: Session, medio: Medio, marca_id: int, fd: datetime, fh: datetime) -> Optional[dict]:
    marca = db.query(Marca).filter(Marca.id == marca_id, Marca.medio_id == medio.id).first()
    if not marca:
        return None

    base = db.query(Publicacion).filter(
        Publicacion.medio_id == medio.id,
        Publicacion.marca_id == marca_id,
        Publicacion.fecha_publicacion >= fd,
        Publicacion.fecha_publicacion <= fh,
    )

    agg = base.with_entities(
        func.coalesce(func.sum(Publicacion.reach), 0).label("reach"),
        func.count(Publicacion.id).label("publicaciones"),
        func.coalesce(func.sum(Publicacion.likes), 0).label("likes"),
        func.coalesce(func.sum(Publicacion.shares), 0).label("shares"),
        func.coalesce(func.sum(Publicacion.comments), 0).label("comments"),
        func.coalesce(func.sum(Publicacion.reach_pagado), 0).label("reach_pagado"),
        func.coalesce(func.sum(Publicacion.inversion_pagada), 0).label("inversion_pagada"),
    ).first()

    # Métricas por canal
    canal_rows = base.with_entities(
        Publicacion.canal,
        func.coalesce(func.sum(Publicacion.reach), 0).label("reach"),
        func.coalesce(func.sum(Publicacion.likes), 0).label("likes"),
        func.coalesce(func.sum(Publicacion.shares), 0).label("shares"),
        func.coalesce(func.sum(Publicacion.comments), 0).label("comments"),
        func.coalesce(func.sum(Publicacion.reach_pagado), 0).label("reach_pagado"),
    ).group_by(Publicacion.canal).all()

    reach_por_canal = {}
    likes_por_canal = {}
    shares_por_canal = {}
    comments_por_canal = {}
    reach_pagado_por_canal = {}
    for r in canal_rows:
        k = r.canal.value
        reach_por_canal[k] = int(r.reach)
        likes_por_canal[k] = int(r.likes)
        shares_por_canal[k] = int(r.shares)
        comments_por_canal[k] = int(r.comments)
        reach_pagado_por_canal[k] = int(r.reach_pagado)

    # Evolución mensual
    mes_rows = base.with_entities(
        func.date_format(Publicacion.fecha_publicacion, '%Y-%m').label('mes'),
        func.coalesce(func.sum(Publicacion.reach), 0).label('reach'),
    ).group_by('mes').order_by('mes').all()

    # Últimas publicaciones
    ultimas = base.order_by(Publicacion.fecha_publicacion.desc()).limit(5).all()

    return {
        "marca_id": marca_id,
        "marca_nombre": marca.nombre_canonico,
        "kpis": {
            "reach": int(agg.reach),
            "publicaciones": int(agg.publicaciones),
            "likes": int(agg.likes),
            "shares": int(agg.shares),
            "comments": int(agg.comments),
            "reach_pagado": int(agg.reach_pagado),
            "inversion_pagada": float(agg.inversion_pagada) if agg.inversion_pagada else 0.0,
            "reach_organico": max(0, int(agg.reach) - int(agg.reach_pagado)),
        },
        "reach_por_canal": reach_por_canal,
        "reach_pagado_por_canal": reach_pagado_por_canal,
        "likes_por_canal": likes_por_canal,
        "shares_por_canal": shares_por_canal,
        "comments_por_canal": comments_por_canal,
        "evolucion_mensual": [{"mes": r.mes, "reach": int(r.reach)} for r in mes_rows],
        "ultimas_publicaciones": [{
            "id": p.id, "url": p.url, "titulo": p.titulo,
            "canal": p.canal.value if p.canal else None,
            "fecha_publicacion": p.fecha_publicacion.isoformat() if p.fecha_publicacion else None,
            "reach": p.reach or 0,
        } for p in ultimas],
    }


# ── Publicaciones ─────────────────────────────────────────────────────────────

@router.get("/medios/{slug}/publicaciones")
def list_publicaciones(
    slug: str,
    marca_id: Optional[int] = None,
    canal: List[str] = Query(default=[]),
    estado: Optional[str] = None,
    fecha_desde: Optional[date] = None,
    fecha_hasta: Optional[date] = None,
    patrocinado: Optional[str] = None,
    incluir_reels: bool = False,
    page: int = 1,
    per_page: int = 50,
    db: Session = Depends(get_db),
    _=Auth,
):
    medio = get_medio_or_404(slug, db)
    q = db.query(Publicacion).filter(Publicacion.medio_id == medio.id)

    if marca_id is not None:
        q = q.filter(Publicacion.marca_id == marca_id)

    # Filtro multicanal: cada canal llega como param separado (?canal=X&canal=Y)
    # incluir_reels=1 añade OR (canal=instagram_post AND tipo=reel)
    if canal or incluir_reels:
        canales_enum = []
        for c in canal:
            try:
                canales_enum.append(CanalEnum(c))
            except ValueError:
                pass
        parts = []
        if canales_enum:
            cond = Publicacion.canal.in_(canales_enum)
            # Si instagram_post está sin pedir reels explícitamente, excluirlos
            if CanalEnum.instagram_post in canales_enum and not incluir_reels:
                cond = and_(cond, or_(
                    Publicacion.canal != CanalEnum.instagram_post,
                    Publicacion.tipo != TipoEnum.reel
                ))
            parts.append(cond)
        if incluir_reels:
            parts.append(and_(
                Publicacion.canal == CanalEnum.instagram_post,
                Publicacion.tipo == TipoEnum.reel
            ))
        if parts:
            q = q.filter(or_(*parts) if len(parts) > 1 else parts[0])
    if estado:
        try:
            q = q.filter(Publicacion.estado_metricas == EstadoMetricasEnum(estado))
        except ValueError:
            pass
    if fecha_desde:
        q = q.filter(Publicacion.fecha_publicacion >= datetime.combine(fecha_desde, datetime.min.time()))
    if fecha_hasta:
        q = q.filter(Publicacion.fecha_publicacion <= datetime.combine(fecha_hasta, datetime.max.time()))
    if patrocinado == "1":
        q = q.filter(Publicacion.inversion_pagada > 0)
    elif patrocinado == "0":
        q = q.filter((Publicacion.inversion_pagada == None) | (Publicacion.inversion_pagada == 0))

    total = q.count()
    reach_total = q.with_entities(func.coalesce(func.sum(Publicacion.reach), 0)).scalar()
    reach_pagado_total = q.with_entities(func.coalesce(func.sum(Publicacion.reach_pagado), 0)).scalar()
    inversion_total = q.with_entities(func.coalesce(func.sum(Publicacion.inversion_pagada), 0)).scalar()
    en_revision = q.filter(Publicacion.estado_metricas == EstadoMetricasEnum.revisar).count()

    items_q = (
        q.order_by(Publicacion.fecha_publicacion.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    pub_ids = [p.id for p in items_q]
    marca_ids = {p.marca_id for p in items_q if p.marca_id}
    agencia_ids = {p.agencia_id for p in items_q if p.agencia_id}

    # Batch-load publicacion_marcas para los pubs de esta página
    pm_rows = (
        db.query(PublicacionMarca)
        .filter(PublicacionMarca.publicacion_id.in_(pub_ids))
        .all()
    ) if pub_ids else []
    pub_marcas_map: dict = {}
    for pm in pm_rows:
        pub_marcas_map.setdefault(pm.publicacion_id, []).append((pm.marca_id, pm.es_principal))
        marca_ids.add(pm.marca_id)

    marcas_map = (
        {m.id: m.nombre_canonico for m in db.query(Marca).filter(Marca.id.in_(marca_ids)).all()}
        if marca_ids else {}
    )
    agencias_map = (
        {a.id: a.nombre_canonico for a in db.query(Agencia).filter(Agencia.id.in_(agencia_ids)).all()}
        if agencia_ids else {}
    )

    # Batch-load latest hora_snapshot per story pub (avoids N+1)
    story_pub_ids = [p.id for p in items_q if p.canal == CanalEnum.instagram_story]
    story_snapshots: dict = {}
    if story_pub_ids:
        max_subq = (
            db.query(
                HistorialMetricas.publicacion_id,
                func.max(HistorialMetricas.hora_snapshot).label("max_hora"),
            )
            .filter(
                HistorialMetricas.publicacion_id.in_(story_pub_ids),
                HistorialMetricas.hora_snapshot.isnot(None),
            )
            .group_by(HistorialMetricas.publicacion_id)
            .subquery()
        )
        snap_rows = (
            db.query(HistorialMetricas)
            .join(
                max_subq,
                (HistorialMetricas.publicacion_id == max_subq.c.publicacion_id) &
                (HistorialMetricas.hora_snapshot == max_subq.c.max_hora),
            )
            .all()
        )
        for sn in snap_rows:
            story_snapshots[sn.publicacion_id] = {
                "es_final": sn.es_final,
                "hora_snapshot": sn.hora_snapshot.isoformat() if sn.hora_snapshot else None,
            }

    return {
        "items": [_pub_item(p, marcas_map, agencias_map, pub_marcas_map, story_snapshots) for p in items_q],
        "total": total,
        "reach_total": int(reach_total),
        "reach_pagado_total": int(reach_pagado_total),
        "reach_total_combinado": int(reach_total) + int(reach_pagado_total),
        "inversion_total": float(inversion_total) if inversion_total else 0.0,
        "en_revision": en_revision,
        "paginas": max(1, (total + per_page - 1) // per_page),
    }


class BulkUpdateBody(BaseModel):
    ids: list[int]
    accion: str  # "asignar_marca" | "marcar_revisado"
    marca_id: Optional[int] = None


@router.patch("/medios/{slug}/publicaciones/bulk-update")
def bulk_update(slug: str, body: BulkUpdateBody, db: Session = Depends(get_db), _=Auth):
    medio = get_medio_or_404(slug, db)
    pubs = db.query(Publicacion).filter(
        Publicacion.id.in_(body.ids),
        Publicacion.medio_id == medio.id,
    ).all()

    if body.accion == "asignar_marca":
        if not body.marca_id:
            raise HTTPException(400, "marca_id requerido para asignar_marca")
        marca = db.query(Marca).filter(Marca.id == body.marca_id, Marca.medio_id == medio.id).first()
        if not marca:
            raise HTTPException(404, "Marca no encontrada")
        for p in pubs:
            p.marca_id = body.marca_id
            if p.estado_metricas == EstadoMetricasEnum.revisar:
                p.estado_metricas = EstadoMetricasEnum.pendiente
    elif body.accion == "marcar_revisado":
        for p in pubs:
            p.estado_metricas = EstadoMetricasEnum.actualizado
    else:
        raise HTTPException(400, f"Acción desconocida: {body.accion}")

    db.commit()
    return {"actualizadas": len(pubs)}


class BulkRefreshBody(BaseModel):
    ids: list[int]


@router.post("/medios/{slug}/publicaciones/bulk-refresh")
def bulk_refresh(slug: str, body: BulkRefreshBody, db: Session = Depends(get_db), _=Auth):
    from agents import web_agent, youtube_agent, instagram_agent, facebook_agent

    CANAL_AGENT = {
        CanalEnum.web: web_agent,
        CanalEnum.youtube: youtube_agent,
        CanalEnum.instagram_post: instagram_agent,
        CanalEnum.facebook: facebook_agent,
    }

    medio = get_medio_or_404(slug, db)
    pubs = db.query(Publicacion).filter(
        Publicacion.id.in_(body.ids),
        Publicacion.medio_id == medio.id,
        Publicacion.estado_metricas != EstadoMetricasEnum.fijo,
    ).all()

    by_canal: dict = defaultdict(list)
    for p in pubs:
        by_canal[p.canal].append(p)

    actualizadas = 0
    errores = 0
    for canal_enum, canal_pubs in by_canal.items():
        agent = CANAL_AGENT.get(canal_enum)
        if not agent:
            errores += len(canal_pubs)
            continue
        try:
            n = agent.update_metrics(db, medio, canal_pubs)
            actualizadas += n
            errores += len(canal_pubs) - n
        except Exception:
            errores += len(canal_pubs)

    return {"actualizadas": actualizadas, "errores": errores}


class MarcaUpdateBody(BaseModel):
    marca_id: int
    estado_marca: str = "ok"


@router.patch("/medios/{slug}/publicaciones/{pub_id}/marca")
def update_pub_marca(
    slug: str,
    pub_id: int,
    body: MarcaUpdateBody,
    db: Session = Depends(get_db),
    _=Auth,
):
    """Valida la marca de una publicación manualmente. Cambia estado_marca a 'ok'."""
    medio = get_medio_or_404(slug, db)
    pub = db.query(Publicacion).filter(
        Publicacion.id == pub_id,
        Publicacion.medio_id == medio.id,
    ).first()
    if not pub:
        raise HTTPException(404, "Publicación no encontrada")

    marca = db.query(Marca).filter(Marca.id == body.marca_id, Marca.medio_id == medio.id).first()
    if not marca:
        raise HTTPException(404, "Marca no encontrada")

    pub.marca_id = body.marca_id
    try:
        pub.estado_marca = EstadoMarcaEnum(body.estado_marca)
    except ValueError:
        pub.estado_marca = EstadoMarcaEnum.ok

    # Si estaba en revisión, mover a pendiente para que se actualicen métricas
    if pub.estado_metricas == EstadoMetricasEnum.revisar:
        pub.estado_metricas = EstadoMetricasEnum.pendiente

    db.commit()
    return {"ok": True, "marca_id": pub.marca_id, "estado_marca": pub.estado_marca.value}


class PromocionUpdateBody(BaseModel):
    inversion_pagada: Optional[float] = None
    reach_pagado: Optional[int] = None


@router.patch("/medios/{slug}/publicaciones/{pub_id}/promocion")
def update_pub_promocion(
    slug: str,
    pub_id: int,
    body: PromocionUpdateBody,
    db: Session = Depends(get_db),
    _=Auth,
):
    """Guarda inversión pagada y reach pagado de una publicación."""
    medio = get_medio_or_404(slug, db)
    pub = db.query(Publicacion).filter(
        Publicacion.id == pub_id,
        Publicacion.medio_id == medio.id,
    ).first()
    if not pub:
        raise HTTPException(404, "Publicación no encontrada")

    if body.inversion_pagada is not None:
        from decimal import Decimal
        pub.inversion_pagada = Decimal(str(body.inversion_pagada)) if body.inversion_pagada > 0 else None
    if body.reach_pagado is not None:
        pub.reach_pagado = max(0, body.reach_pagado)

    db.commit()
    return {
        "ok": True,
        "inversion_pagada": float(pub.inversion_pagada) if pub.inversion_pagada else None,
        "reach_pagado": pub.reach_pagado or 0,
    }


class MarcasUpdateBody(BaseModel):
    marca_ids: list[int]
    estado_marca: str = "ok"


@router.patch("/medios/{slug}/publicaciones/{pub_id}/marcas")
def update_pub_marcas(
    slug: str,
    pub_id: int,
    body: MarcasUpdateBody,
    db: Session = Depends(get_db),
    _=Auth,
):
    """Asigna múltiples marcas a una publicación. El primero de la lista es el principal."""
    medio = get_medio_or_404(slug, db)
    pub = db.query(Publicacion).filter(
        Publicacion.id == pub_id,
        Publicacion.medio_id == medio.id,
    ).first()
    if not pub:
        raise HTTPException(404, "Publicación no encontrada")

    # Validar que todas las marcas pertenecen al medio
    valid_ids: list[int] = []
    for mid in body.marca_ids:
        m = db.query(Marca).filter(Marca.id == mid, Marca.medio_id == medio.id).first()
        if m:
            valid_ids.append(mid)

    # Reemplazar publicacion_marcas
    db.query(PublicacionMarca).filter(PublicacionMarca.publicacion_id == pub_id).delete()
    for i, mid in enumerate(valid_ids):
        db.add(PublicacionMarca(publicacion_id=pub_id, marca_id=mid, es_principal=(i == 0)))

    # Actualizar marca_id principal en publicaciones (para compatibilidad con analytics)
    pub.marca_id = valid_ids[0] if valid_ids else None
    try:
        pub.estado_marca = EstadoMarcaEnum(body.estado_marca)
    except ValueError:
        pub.estado_marca = EstadoMarcaEnum.ok

    if pub.estado_metricas == EstadoMetricasEnum.revisar:
        pub.estado_metricas = EstadoMetricasEnum.pendiente

    db.commit()
    return {"ok": True, "marca_ids": valid_ids, "marca_id": pub.marca_id}


# ── Analytics ─────────────────────────────────────────────────────────────────

@router.get("/medios/{slug}/analytics/resumen")
def analytics_resumen(
    slug: str,
    periodo: Optional[str] = "3m",
    fecha_desde: Optional[date] = None,
    fecha_hasta: Optional[date] = None,
    canal: Optional[str] = None,
    db: Session = Depends(get_db),
    _=Auth,
):
    medio = get_medio_or_404(slug, db)
    fd, fh = _periodo_filtro(periodo, fecha_desde, fecha_hasta)

    base = db.query(Publicacion).filter(
        Publicacion.medio_id == medio.id,
        Publicacion.fecha_publicacion >= fd,
        Publicacion.fecha_publicacion <= fh,
    )
    if canal:
        try:
            base = base.filter(Publicacion.canal == CanalEnum(canal))
        except ValueError:
            pass

    # Totales globales para el período
    totales = base.with_entities(
        func.coalesce(func.sum(Publicacion.reach_pagado), 0).label("reach_pagado_total"),
        func.coalesce(func.sum(Publicacion.inversion_pagada), 0).label("inversion_total"),
    ).first()

    # Reach por canal y mes
    rows = base.with_entities(
        func.date_format(Publicacion.fecha_publicacion, '%Y-%m').label('mes'),
        Publicacion.canal,
        func.coalesce(func.sum(Publicacion.reach), 0).label('reach'),
    ).group_by('mes', Publicacion.canal).order_by('mes').all()

    meses = sorted({r.mes for r in rows if r.mes})
    canales_data: dict = defaultdict(lambda: {m: 0 for m in meses})
    for r in rows:
        if r.mes:
            canales_data[r.canal.value][r.mes] = int(r.reach)

    # Top 10 marcas por reach
    top = (
        base.filter(Publicacion.marca_id.isnot(None))
        .with_entities(
            Publicacion.marca_id,
            func.coalesce(func.sum(Publicacion.reach), 0).label('reach'),
        )
        .group_by(Publicacion.marca_id)
        .order_by(func.sum(Publicacion.reach).desc())
        .limit(10)
        .all()
    )
    marca_ids = [r.marca_id for r in top]
    marcas_map = {
        m.id: m.nombre_canonico
        for m in db.query(Marca).filter(Marca.id.in_(marca_ids)).all()
    } if marca_ids else {}

    return {
        "meses": meses,
        "canales": {
            canal_name: [vals[m] for m in meses]
            for canal_name, vals in canales_data.items()
        },
        "top_marcas": [
            {"marca_id": r.marca_id, "nombre": marcas_map.get(r.marca_id, "?"), "reach": int(r.reach)}
            for r in top
        ],
        "reach_pagado_total": int(totales.reach_pagado_total) if totales else 0,
        "inversion_total": float(totales.inversion_total) if totales and totales.inversion_total else 0.0,
    }


@router.get("/medios/{slug}/analytics/marca/{marca_id}")
def analytics_marca(
    slug: str,
    marca_id: int,
    periodo: Optional[str] = "3m",
    fecha_desde: Optional[date] = None,
    fecha_hasta: Optional[date] = None,
    db: Session = Depends(get_db),
    _=Auth,
):
    medio = get_medio_or_404(slug, db)
    fd, fh = _periodo_filtro(periodo, fecha_desde, fecha_hasta)
    result = _marca_analytics(db, medio, marca_id, fd, fh)
    if result is None:
        raise HTTPException(404, "Marca no encontrada")
    return result


@router.get("/medios/{slug}/analytics/comparar")
def analytics_comparar(
    slug: str,
    marca_a: int,
    marca_b: int,
    periodo: Optional[str] = "3m",
    fecha_desde: Optional[date] = None,
    fecha_hasta: Optional[date] = None,
    db: Session = Depends(get_db),
    _=Auth,
):
    medio = get_medio_or_404(slug, db)
    fd, fh = _periodo_filtro(periodo, fecha_desde, fecha_hasta)
    data_a = _marca_analytics(db, medio, marca_a, fd, fh)
    data_b = _marca_analytics(db, medio, marca_b, fd, fh)
    if data_a is None or data_b is None:
        raise HTTPException(404, "Una o ambas marcas no encontradas")
    return {"marca_a": data_a, "marca_b": data_b}


@router.get("/medios/{slug}/analytics/semanal")
def analytics_semanal(
    slug: str,
    marca_id: Optional[int] = None,
    canal: Optional[str] = None,
    fecha_desde: Optional[date] = None,
    fecha_hasta: Optional[date] = None,
    db: Session = Depends(get_db),
    _=Auth,
):
    """
    Crecimiento semanal ISO: reach_diff por semana, por canal y por marca.
    Solo publicaciones de 2026 en adelante con snapshots semanales.

    Response:
      semanas: ["2026-W01", "2026-W02", ...]
      series: [{ canal: "web", data: [diff_w01, diff_w02, ...] }]
      por_marca: [{ marca: "On", data: [...] }]   (top 10, solo sin filtro de marca)
    """
    from utils.semanas import get_semana_iso

    medio = get_medio_or_404(slug, db)

    base = (
        db.query(
            HistorialMetricas.semana_iso,
            Publicacion.canal,
            func.coalesce(func.sum(HistorialMetricas.reach_diff), 0).label("reach_diff"),
            func.coalesce(func.sum(HistorialMetricas.reach), 0).label("reach"),
        )
        .join(Publicacion, HistorialMetricas.publicacion_id == Publicacion.id)
        .filter(
            Publicacion.medio_id == medio.id,
            HistorialMetricas.semana_iso.isnot(None),
        )
    )

    if marca_id is not None:
        base = base.filter(Publicacion.marca_id == marca_id)
    if canal:
        try:
            base = base.filter(Publicacion.canal == CanalEnum(canal))
        except ValueError:
            pass
    if fecha_desde:
        base = base.filter(HistorialMetricas.semana_iso >= get_semana_iso(fecha_desde))
    if fecha_hasta:
        base = base.filter(HistorialMetricas.semana_iso <= get_semana_iso(fecha_hasta))

    rows = (
        base.group_by(HistorialMetricas.semana_iso, Publicacion.canal)
        .order_by(HistorialMetricas.semana_iso)
        .all()
    )

    log.info(f"[{slug}] analytics/semanal: {len(rows)} filas devueltas")

    semanas = sorted(set(r.semana_iso for r in rows if r.semana_iso))

    by_canal: dict = defaultdict(lambda: defaultdict(int))
    by_canal_reach: dict = defaultdict(lambda: defaultdict(int))
    for r in rows:
        if r.semana_iso:
            by_canal[r.canal.value][r.semana_iso] = int(r.reach_diff)
            by_canal_reach[r.canal.value][r.semana_iso] = int(r.reach)

    # Fallback: si reach_diff es 0 para todas las semanas de un canal, usar reach
    series = []
    for c in sorted(by_canal.keys()):
        diff_data = [by_canal[c].get(s, 0) for s in semanas]
        if sum(diff_data) == 0:
            # Backfill con reach acumulado puede ser incorrecto; usar igual como indicador
            reach_data = [by_canal_reach[c].get(s, 0) for s in semanas]
            series.append({"canal": c, "data": reach_data, "fallback": True})
            log.warning(f"[{slug}] Canal {c}: reach_diff=0 en todas las semanas, usando reach acumulado como fallback")
        else:
            series.append({"canal": c, "data": diff_data, "fallback": False})

    # Top 10 marcas (solo cuando no hay filtro de marca_id)
    por_marca = []
    if marca_id is None:
        marca_base = (
            db.query(
                HistorialMetricas.semana_iso,
                Publicacion.marca_id,
                func.coalesce(func.sum(HistorialMetricas.reach_diff), 0).label("reach_diff"),
                func.coalesce(func.sum(HistorialMetricas.reach), 0).label("reach"),
            )
            .join(Publicacion, HistorialMetricas.publicacion_id == Publicacion.id)
            .filter(
                Publicacion.medio_id == medio.id,
                Publicacion.marca_id.isnot(None),
                HistorialMetricas.semana_iso.isnot(None),
            )
        )
        if canal:
            try:
                marca_base = marca_base.filter(Publicacion.canal == CanalEnum(canal))
            except ValueError:
                pass
        if fecha_desde:
            marca_base = marca_base.filter(HistorialMetricas.semana_iso >= get_semana_iso(fecha_desde))
        if fecha_hasta:
            marca_base = marca_base.filter(HistorialMetricas.semana_iso <= get_semana_iso(fecha_hasta))

        marca_rows = (
            marca_base.group_by(HistorialMetricas.semana_iso, Publicacion.marca_id)
            .order_by(HistorialMetricas.semana_iso)
            .all()
        )

        m_ids = list({r.marca_id for r in marca_rows})
        marcas_map = (
            {m.id: m.nombre_canonico for m in db.query(Marca).filter(Marca.id.in_(m_ids)).all()}
            if m_ids else {}
        )

        by_marca: dict = defaultdict(lambda: defaultdict(int))
        by_marca_reach: dict = defaultdict(lambda: defaultdict(int))
        for r in marca_rows:
            if r.semana_iso:
                by_marca[r.marca_id][r.semana_iso] += int(r.reach_diff)
                by_marca_reach[r.marca_id][r.semana_iso] += int(r.reach)

        # Detectar si todos los reach_diff son 0 (fallback a reach)
        total_diff_all = sum(sum(v.values()) for v in by_marca.values())
        use_reach_fallback = (total_diff_all == 0)

        # Ordenar por reach total desc, top 10
        if use_reach_fallback:
            top = sorted(by_marca_reach.items(), key=lambda x: sum(x[1].values()), reverse=True)[:10]
            por_marca = [
                {"marca": marcas_map.get(mid, "?"), "data": [vals.get(s, 0) for s in semanas], "fallback": True}
                for mid, vals in top
            ]
        else:
            top = sorted(by_marca.items(), key=lambda x: sum(x[1].values()), reverse=True)[:10]
            por_marca = [
                {"marca": marcas_map.get(mid, "?"), "data": [vals.get(s, 0) for s in semanas], "fallback": False}
                for mid, vals in top
            ]

    return {"semanas": semanas, "series": series, "por_marca": por_marca}
