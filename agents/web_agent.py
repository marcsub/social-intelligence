"""
agents/web_agent.py
Agente para el canal web: detecta artículos nuevos via RSS y recoge
métricas de GA4 Data API.
"""
import logging
import hashlib
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Optional
import feedparser
import httpx
from sqlalchemy.orm import Session
from google.oauth2 import service_account
from googleapiclient.discovery import build

from core.brand_id_agent import identify
from core.crypto import decrypt_token
from core.settings import get_settings
from models.database import (
    Medio, Publicacion, TokenCanal, HistorialMetricas,
    CanalEnum, TipoEnum, EstadoMetricasEnum, EstadoMarcaEnum
)

log = logging.getLogger(__name__)
settings = get_settings()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_token(db: Session, medio_id: int, canal: str, clave: str) -> Optional[str]:
    t = db.query(TokenCanal).filter(
        TokenCanal.medio_id == medio_id,
        TokenCanal.canal == canal,
        TokenCanal.clave == clave,
    ).first()
    if not t:
        return None
    return decrypt_token(t.valor_cifrado, settings.jwt_secret)


def _pub_id(url: str) -> str:
    """Hash corto para identificar una URL de forma única."""
    return hashlib.sha1(url.encode()).hexdigest()[:16]


def _parse_date(entry) -> datetime:
    """Parsea la fecha de una entrada RSS a datetime UTC."""
    try:
        import time
        t = entry.get("published_parsed") or entry.get("updated_parsed")
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc)
    except Exception:
        pass
    return datetime.now(timezone.utc)


def _fetch_date_published(url: str) -> Optional[datetime]:
    """
    Hace GET al artículo y extrae datePublished del JSON-LD.
    Devuelve datetime UTC (sin hora) o None si falla o no encuentra el campo.
    Timeout de 5s para no ralentizar detect_new.
    """
    try:
        with httpx.Client(timeout=5, follow_redirects=True) as client:
            resp = client.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; SocialIntelligence/1.0)"},
            )
            html = resp.text
        match = re.search(r'"datePublished"\s*:\s*"(\d{4}-\d{2}-\d{2})', html)
        if match:
            return datetime.strptime(match.group(1), "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except Exception as ex:
        log.debug(f"_fetch_date_published({url}): {ex}")
    return None


# ── Sitemap XML parser ────────────────────────────────────────────────────────

def _parse_sitemap_entries(raw_xml: bytes) -> list[dict]:
    """
    Parsea un Google Sitemap XML (formato urlset) y devuelve una lista de
    entradas compatibles con el formato feedparser (dicts con link, title,
    published_parsed, summary, tags).
    Solo incluye URLs que parezcan artículos (contienen '/es/', '/en/' con
    una parte identificativa como REVIEW--, REPORTAJE--, etc.).
    """
    try:
        root = ET.fromstring(raw_xml)
    except ET.ParseError as ex:
        log.error(f"Error parseando sitemap XML: {ex}")
        return []

    sm_ns = root.tag.split("}")[0].lstrip("{") if "}" in root.tag else ""
    img_ns = "http://www.google.com/schemas/sitemap-image/1.1"

    def tag(ns, name):
        return f"{{{ns}}}{name}" if ns else name

    entries = []
    for url_elem in root.findall(tag(sm_ns, "url")):
        loc = url_elem.findtext(tag(sm_ns, "loc"), "")
        lastmod = url_elem.findtext(tag(sm_ns, "lastmod"), "")

        if not loc or not lastmod:
            continue

        # Filtrar páginas que no sean artículos (sin segmento de idioma + ID)
        path = loc.split("://", 1)[-1].split("/", 1)[-1]  # quitar dominio
        path_parts = [p for p in path.split("/") if p]
        if len(path_parts) < 2:
            continue
        # Requerir al menos un segmento de idioma (/es/, /en/, /fr/...)
        lang_segments = {"es", "en", "fr", "de", "pt", "it"}
        if path_parts[0] not in lang_segments:
            continue

        # Extraer título: primero de la primera imagen, luego del slug
        title = ""
        img_elem = url_elem.find(tag(img_ns, "image"))
        if img_elem is not None:
            title = img_elem.findtext(tag(img_ns, "title"), "")
        if not title:
            slug = path_parts[1] if len(path_parts) > 1 else path_parts[0]
            # Quitar sufijo de ID (ej: REVIEW--101498 → tomar solo la parte del slug)
            slug = slug.split("--")[0]
            title = slug.replace("-", " ").title()

        # Convertir YYYY-MM-DD a time.struct_time
        try:
            dt = datetime.strptime(lastmod[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            published_parsed = dt.timetuple()
        except ValueError:
            continue

        entries.append({
            "link": loc,
            "title": title,
            "published_parsed": published_parsed,
            "summary": "",
            "tags": [],
        })

    return entries


# ── GA4 ───────────────────────────────────────────────────────────────────────

def _build_ga4_service(service_account_json: str):
    """Construye el cliente de GA4 Data API usando cuenta de servicio."""
    import json
    info = json.loads(service_account_json)
    creds = service_account.Credentials.from_service_account_info(
        info,
        scopes=["https://www.googleapis.com/auth/analytics.readonly"]
    )
    return build("analyticsdata", "v1beta", credentials=creds, cache_discovery=False)


def _get_ga4_metrics(
    service,
    property_id: str,
    page_path: str,
    start_date: str = "30daysAgo",
    end_date: str = "today",
) -> dict:
    """
    Consulta GA4 para una URL específica.
    Prueba el path tal cual y luego con/sin trailing slash.
    Devuelve sesiones, usuarios y vistas de página.
    """
    # Variantes de path a probar: original, sin trailing slash, con trailing slash
    path_variants = [page_path]
    if page_path.endswith("/"):
        path_variants.append(page_path.rstrip("/"))
    else:
        path_variants.append(page_path + "/")

    def _run_query(path):
        resp = service.properties().runReport(
            property=f"properties/{property_id}",
            body={
                "dateRanges": [{"startDate": start_date, "endDate": end_date}],
                "dimensions": [{"name": "pagePath"}],
                "metrics": [
                    {"name": "sessions"},
                    {"name": "totalUsers"},
                    {"name": "screenPageViews"},
                ],
                "dimensionFilter": {
                    "filter": {
                        "fieldName": "pagePath",
                        "stringFilter": {"matchType": "CONTAINS", "value": path}
                    }
                },
                "limit": 1,
            }
        ).execute()
        rows = resp.get("rows", [])
        if not rows:
            return None
        values = [int(m.get("value", 0)) for m in rows[0].get("metricValues", [])]
        return {
            "sessions": values[0] if len(values) > 0 else 0,
            "users":    values[1] if len(values) > 1 else 0,
            "views":    values[2] if len(values) > 2 else 0,
            "_path_used": path,
        }

    for variant in path_variants:
        try:
            result = _run_query(variant)
            if result and result["views"] > 0:
                return result
        except Exception as ex:
            log.warning(f"GA4 error para path '{variant}': {ex}")

    return {"sessions": 0, "users": 0, "views": 0, "_path_used": page_path}


# ── Detección de publicaciones nuevas ────────────────────────────────────────

def detect_new(db: Session, medio: Medio, checkpoint: Optional[datetime]) -> list[Publicacion]:
    """
    Lee el RSS del medio y detecta artículos publicados desde el checkpoint.
    Invoca el Brand ID Agent para cada artículo y lo inserta en la DB.
    Devuelve lista de Publicacion insertadas.
    """
    if not medio.rss_url:
        log.warning(f"[{medio.slug}] Sin RSS URL configurada")
        return []

    # Fallback a 365 días si no hay checkpoint (primera ejecución)
    if checkpoint is None:
        checkpoint = datetime.now(timezone.utc) - timedelta(days=365)
        log.info(f"[{medio.slug}] web detect_new: sin checkpoint previo, usando fallback = hace 365 días ({checkpoint.date()})")
    else:
        log.info(f"[{medio.slug}] web detect_new: checkpoint = {checkpoint.isoformat()}")

    log.info(f"[{medio.slug}] Leyendo fuente web: {medio.rss_url}")
    import urllib.request
    raw = b""
    try:
        req = urllib.request.Request(
            medio.rss_url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; SocialIntelligence/1.0)"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
    except Exception as ex:
        log.warning(f"[{medio.slug}] Error descargando fuente: {ex}")

    # Intentar RSS/Atom con feedparser
    entries = []
    if raw:
        feed = feedparser.parse(raw)
        if not feed.bozo and feed.entries:
            log.info(f"[{medio.slug}] Feed RSS/Atom: {len(feed.entries)} entradas")
            entries = feed.entries
        else:
            if feed.bozo:
                log.info(f"[{medio.slug}] feedparser bozo ({feed.bozo_exception}), intentando como sitemap XML")
            else:
                log.info(f"[{medio.slug}] feedparser devolvió 0 entradas, intentando como sitemap XML")
            entries = _parse_sitemap_entries(raw)
            if entries:
                log.info(f"[{medio.slug}] Sitemap XML parseado: {len(entries)} artículos")
            else:
                log.error(f"[{medio.slug}] Sin entradas en RSS ni sitemap")
                return []

    if not entries:
        log.error(f"[{medio.slug}] No se pudo obtener contenido de {medio.rss_url}")
        return []

    nuevas = []
    config = medio.config

    for entry in entries:
        url = entry.get("link", "")
        if not url:
            continue

        # lastmod se usa solo para el filtro de checkpoint (cuándo cambió el sitemap)
        lastmod_fecha = _parse_date(entry)

        # Filtrar por checkpoint usando lastmod (no datePublished, que puede ser anterior)
        if checkpoint and lastmod_fecha <= checkpoint:
            continue

        # Evitar duplicados
        id_externo = _pub_id(url)
        existente = db.query(Publicacion).filter(
            Publicacion.medio_id == medio.id,
            Publicacion.canal == CanalEnum.web,
            Publicacion.id_externo == id_externo,
        ).first()
        if existente:
            continue

        # Obtener fecha real de publicación desde el HTML del artículo
        fecha_real = _fetch_date_published(url)
        if fecha_real:
            fecha = fecha_real
            log.debug(f"[{medio.slug}] datePublished={fecha.date()} para {url[:60]}")
        else:
            fecha = lastmod_fecha
            log.debug(f"[{medio.slug}] datePublished no encontrado, usando lastmod={fecha.date()} para {url[:60]}")

        titulo = entry.get("title", "")
        resumen = entry.get("summary", "")[:500]
        tags = " ".join(t.get("term", "") for t in entry.get("tags", []))

        # Identificar marca
        brand = identify(
            medio_id=medio.id,
            db=db,
            title=titulo,
            description=resumen,
            hashtags=tags,
            url=url,
        )

        umbral = config.umbral_confianza_marca if config else 80
        estado = (
            EstadoMetricasEnum.pendiente
            if brand.confianza >= umbral
            else EstadoMetricasEnum.revisar
        )
        estado_marca = (
            EstadoMarcaEnum.estimated
            if brand.marca_id and brand.confianza >= 80
            else EstadoMarcaEnum.to_review
        )

        pub = Publicacion(
            medio_id=medio.id,
            marca_id=brand.marca_id,
            agencia_id=brand.agencia_id,
            id_externo=id_externo,
            canal=CanalEnum.web,
            tipo=TipoEnum.articulo,
            url=url,
            titulo=titulo,
            texto=resumen or None,
            fecha_publicacion=fecha,
            estado_metricas=estado,
            confianza_marca=brand.confianza if brand.confianza > 0 else None,
            estado_marca=estado_marca,
            notas=brand.razonamiento if estado == EstadoMetricasEnum.revisar else None,
        )
        db.add(pub)
        db.flush()

        # Marcas secundarias (comparativas) — una fila por marca adicional
        for sec in brand.marcas_secundarias:
            pub_sec = Publicacion(
                medio_id=medio.id,
                marca_id=sec["marca_id"],
                agencia_id=brand.agencia_id,
                id_externo=f"{id_externo}_{sec['marca_id']}",
                canal=CanalEnum.web,
                tipo=TipoEnum.articulo,
                url=url,
                titulo=titulo,
                texto=resumen or None,
                fecha_publicacion=fecha,
                estado_metricas=EstadoMetricasEnum.pendiente,
                confianza_marca=sec["confianza"],
            )
            db.add(pub_sec)

        nuevas.append(pub)
        log.info(f"[{medio.slug}] Nueva publicación web: {titulo[:60]} — marca: {brand.marca_nombre} ({brand.confianza}%)")

    db.commit()
    return nuevas


# ── Actualización de métricas GA4 (legado — solo para bulk-refresh manual) ────

def update_metrics(db: Session, medio: Medio, publicaciones: list[Publicacion]) -> int:
    """
    Actualiza métricas GA4 para una lista concreta de publicaciones.
    Usado por bulk-refresh manual desde la UI. No guarda snapshot semanal.
    """
    if not publicaciones:
        return 0

    config = medio.config
    if not config or not config.ga4_property_id:
        log.warning(f"[{medio.slug}] GA4 property_id no configurado")
        return 0

    sa_json = _get_token(db, medio.id, "ga4", "service_account_json")
    if not sa_json:
        log.warning(f"[{medio.slug}] Token GA4 service_account_json no encontrado")
        return 0

    try:
        service = _build_ga4_service(sa_json)
    except Exception as ex:
        log.error(f"[{medio.slug}] Error construyendo cliente GA4: {ex}")
        return 0

    from urllib.parse import urlparse

    actualizadas = 0
    for pub in publicaciones:
        try:
            path = urlparse(pub.url).path or pub.url
            metricas = _get_ga4_metrics(service, config.ga4_property_id, path)
            pub.reach = metricas["views"]
            pub.ga4_sessions = metricas["sessions"]
            pub.ga4_users = metricas["users"]
            pub.clicks = metricas["sessions"]
            pub.ultima_actualizacion = datetime.now(timezone.utc)
            pub.estado_metricas = EstadoMetricasEnum.actualizado
            actualizadas += 1
        except Exception as ex:
            log.error(f"[{medio.slug}] Error GA4 para {pub.url}: {ex}")
            pub.estado_metricas = EstadoMetricasEnum.error

    db.commit()
    log.info(f"[{medio.slug}] GA4 bulk: {actualizadas}/{len(publicaciones)} actualizadas")
    return actualizadas


# ── Actualización semanal GA4 con histórico ISO ───────────────────────────────

def update_weekly_ga4(db: Session, medio: Medio) -> int:
    """
    Snapshot semanal ISO para TODAS las publicaciones web de 2026 en adelante.

    Para cada publicación:
    - Calcula semanas pendientes (no snapshoteadas aún)
    - Primera ejecución: recalcula toda la historia desde semana de publicación
    - Ejecuciones siguientes: solo la semana actual
    - Llama a GA4 con el rango exacto de cada semana (lunes-domingo)
    - Guarda reach_diff (vistas de esa semana) y reach (acumulado)
    - Hace UPSERT para evitar duplicados en caso de re-ejecución

    Devuelve número de publicaciones procesadas.
    """
    from urllib.parse import urlparse
    from datetime import date as _date
    from utils.semanas import get_semana_iso, get_rango_semana, semanas_entre

    config = medio.config
    if not config or not config.ga4_property_id:
        log.warning(f"[{medio.slug}] GA4 property_id no configurado — saltando update_weekly_ga4")
        return 0

    sa_json = _get_token(db, medio.id, "ga4", "service_account_json")
    if not sa_json:
        log.warning(f"[{medio.slug}] Token GA4 no encontrado — saltando update_weekly_ga4")
        return 0

    try:
        service = _build_ga4_service(sa_json)
    except Exception as ex:
        log.error(f"[{medio.slug}] Error construyendo GA4: {ex}")
        return 0

    hoy = _date.today()
    semana_actual = get_semana_iso(hoy)
    inicio_2026 = datetime(2026, 1, 1, tzinfo=timezone.utc)

    pubs = (
        db.query(Publicacion)
        .filter(
            Publicacion.medio_id == medio.id,
            Publicacion.canal == CanalEnum.web,
            Publicacion.estado_metricas != EstadoMetricasEnum.fijo,
            Publicacion.fecha_publicacion >= inicio_2026,
        )
        .order_by(Publicacion.fecha_publicacion.asc())
        .all()
    )

    if not pubs:
        log.info(f"[{medio.slug}] update_weekly_ga4: sin publicaciones web 2026+")
        return 0

    log.info(f"[{medio.slug}] update_weekly_ga4: {len(pubs)} publicaciones a procesar")
    actualizadas = 0

    for pub in pubs:
        try:
            pub_date = pub.fecha_publicacion.date() if hasattr(pub.fecha_publicacion, "date") else pub.fecha_publicacion
            todas_semanas = semanas_entre(pub_date, hoy)

            # Semanas ya snapshoteadas
            snapshots_existentes = {
                h.semana_iso: h
                for h in db.query(HistorialMetricas).filter(
                    HistorialMetricas.publicacion_id == pub.id,
                    HistorialMetricas.semana_iso.isnot(None),
                ).all()
            }
            semanas_pendientes = [s for s in todas_semanas if s not in snapshots_existentes]

            if not semanas_pendientes:
                continue

            path = urlparse(pub.url).path or pub.url

            # Calcular acumulado hasta la semana previa a la primera pendiente
            primera_pendiente = semanas_pendientes[0]
            acumulado_reach = sum(
                (h.reach_diff or h.reach or 0)
                for s, h in snapshots_existentes.items()
                if s < primera_pendiente
            )
            acumulado_clicks = sum(
                (h.clicks_diff or h.clicks or 0)
                for s, h in snapshots_existentes.items()
                if s < primera_pendiente
            )

            for semana in semanas_pendientes:
                lunes, domingo = get_rango_semana(semana)
                start = max(pub_date, lunes)
                end = min(hoy, domingo)

                if start > end:
                    continue

                metricas = _get_ga4_metrics(
                    service,
                    config.ga4_property_id,
                    path,
                    start_date=start.strftime("%Y-%m-%d"),
                    end_date=end.strftime("%Y-%m-%d"),
                )

                diff_reach = metricas["views"]
                diff_clicks = metricas["sessions"]
                acumulado_reach += diff_reach
                acumulado_clicks += diff_clicks

                existing_h = snapshots_existentes.get(semana)
                if existing_h:
                    existing_h.reach = acumulado_reach
                    existing_h.reach_diff = diff_reach
                    existing_h.clicks = acumulado_clicks
                    existing_h.clicks_diff = diff_clicks
                    existing_h.fuente = "ga4"
                    existing_h.fecha_snapshot = datetime.now(timezone.utc)
                else:
                    db.add(HistorialMetricas(
                        publicacion_id=pub.id,
                        semana_iso=semana,
                        reach=acumulado_reach,
                        reach_diff=diff_reach,
                        likes=0, likes_diff=0,
                        shares=0, shares_diff=0,
                        comments=0, comments_diff=0,
                        clicks=acumulado_clicks,
                        clicks_diff=diff_clicks,
                        fuente="ga4",
                    ))
                    db.flush()

                path_used = metricas.get("_path_used", path)
                log.info(f"[{medio.slug}] {semana} | {pub.url[:60]} | path={path_used} | vistas={diff_reach} (acum={acumulado_reach})")

            # Actualizar reach total en la publicación
            pub.reach = acumulado_reach
            pub.clicks = acumulado_clicks
            pub.ultima_actualizacion = datetime.now(timezone.utc)
            pub.estado_metricas = EstadoMetricasEnum.actualizado
            actualizadas += 1

        except Exception as ex:
            log.error(f"[{medio.slug}] Error en update_weekly_ga4 para {pub.url}: {ex}")
            pub.estado_metricas = EstadoMetricasEnum.error

    db.commit()
    log.info(f"[{medio.slug}] update_weekly_ga4 completado: {actualizadas}/{len(pubs)} publicaciones")
    return actualizadas