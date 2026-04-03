"""
scripts/diagnose_web_agent.py
Diagnóstico completo del web agent para un medio.
Ejecutar desde la raíz del proyecto:
  python scripts/diagnose_web_agent.py [slug]
"""
import sys
import json
import logging
from datetime import datetime, timezone

# Logging detallado
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s"
)
log = logging.getLogger("diagnose")

# Añadir raíz al path
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import sessionmaker
from core.settings import get_settings
from models.database import (
    create_db_engine, Medio, Publicacion, TokenCanal, LogEjecucion,
    CanalEnum, EstadoMetricasEnum
)
from core.crypto import decrypt_token

settings = get_settings()
engine = create_db_engine(settings.db_url)
SessionLocal = sessionmaker(bind=engine)

SLUG = sys.argv[1] if len(sys.argv) > 1 else "roadrunningreview"
SEP = "─" * 70


def hr(title=""):
    print(f"\n{SEP}")
    if title:
        print(f"  {title}")
        print(SEP)


def check_medio(db):
    hr("1. MEDIO EN DB")
    medio = db.query(Medio).filter(Medio.slug == SLUG).first()
    if not medio:
        print(f"  ❌  Medio '{SLUG}' NO encontrado en la base de datos")
        return None
    print(f"  ✅  Medio encontrado: id={medio.id}, nombre='{medio.nombre}'")
    print(f"      activo      : {medio.activo}")
    print(f"      url_web     : {medio.url_web}")
    print(f"      rss_url     : {medio.rss_url!r}")

    cfg = medio.config
    if cfg:
        print(f"      ga4_property_id    : {cfg.ga4_property_id!r}")
        print(f"      youtube_channel_id : {cfg.youtube_channel_id!r}")
        print(f"      umbral_confianza   : {cfg.umbral_confianza_marca}")
        print(f"      dias_actualizacion : {cfg.dias_actualizacion_auto}")
    else:
        print("  ⚠️   Sin ConfigMedio (tabla config_medio vacía para este medio)")

    if not medio.rss_url:
        print("  ❌  rss_url está vacío — el web agent devolverá [] sin intentarlo")
    return medio


def check_checkpoint(db, medio):
    hr("2. CHECKPOINT (último log OK)")
    last_ok = (
        db.query(LogEjecucion)
        .filter(
            LogEjecucion.medio_id == medio.id,
            LogEjecucion.agente == "web",
            LogEjecucion.estado == "ok",
        )
        .order_by(LogEjecucion.fin.desc())
        .first()
    )
    if last_ok:
        print(f"  Último run OK: {last_ok.fin}  (UTC)")
        print(f"  → Los artículos con fecha <= {last_ok.fin} serán IGNORADOS")
    else:
        print("  Sin checkpoint previo — se procesarán TODOS los artículos del RSS")

    # Mostrar últimos 5 logs
    logs = (
        db.query(LogEjecucion)
        .filter(LogEjecucion.medio_id == medio.id, LogEjecucion.agente == "web")
        .order_by(LogEjecucion.inicio.desc())
        .limit(5)
        .all()
    )
    if logs:
        print(f"\n  Últimos {len(logs)} runs del agente web:")
        for l in logs:
            err = json.loads(l.errores) if l.errores else []
            print(f"    {l.inicio}  estado={l.estado}  nuevas={l.publicaciones_nuevas}  errores={err}")
    return last_ok.fin if last_ok else None


def check_rss(medio):
    hr("3. TEST RSS")
    if not medio.rss_url:
        print("  ⏭  Saltando — sin rss_url")
        return None

    import feedparser
    import urllib.request

    print(f"  URL: {medio.rss_url}")
    try:
        req = urllib.request.Request(
            medio.rss_url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; SocialIntelligence/1.0)"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
        print(f"  ✅  Descarga OK ({len(raw)} bytes)")
        feed = feedparser.parse(raw)
    except Exception as ex:
        print(f"  ⚠️   Descarga directa falló: {ex}")
        print("  Probando feedparser directo...")
        feed = feedparser.parse(medio.rss_url)

    if feed.bozo:
        print(f"  ❌  RSS bozo=True — excepción: {feed.bozo_exception}")
        print("      (El web agent aborta aquí y devuelve [])")
    else:
        print(f"  ✅  RSS válido. Entradas: {len(feed.entries)}")

    if feed.entries:
        print(f"\n  Primeras 5 entradas:")
        for e in feed.entries[:5]:
            from agents.web_agent import _parse_date
            fecha = _parse_date(e)
            print(f"    · [{fecha.date()}] {e.get('title','(sin título)')[:80]}")
            print(f"              link: {e.get('link','')[:80]}")
    else:
        print("  ❌  Sin entradas en el feed")

    return feed


def check_brand_id(db, medio, feed):
    hr("4. TEST BRAND ID AGENT (primeros 3 artículos)")
    if not feed or not feed.entries:
        print("  ⏭  Sin feed disponible")
        return

    from core.brand_id_agent import identify
    from agents.web_agent import _parse_date

    for entry in feed.entries[:3]:
        titulo = entry.get("title", "")
        resumen = entry.get("summary", "")[:300]
        url = entry.get("link", "")
        tags = " ".join(t.get("term", "") for t in entry.get("tags", []))

        result = identify(
            medio_id=medio.id,
            db=db,
            title=titulo,
            description=resumen,
            hashtags=tags,
            url=url,
        )
        marca_str = f"{result.marca_nombre} ({result.confianza}%)" if result.marca_id else "— sin marca —"
        agencia_str = result.agencia_nombre or "— sin agencia —"
        print(f"\n  Artículo: {titulo[:70]}")
        print(f"    marca  : {marca_str}")
        print(f"    agencia: {agencia_str}")
        print(f"    razón  : {result.razonamiento}")


def check_checkpoint_filter(db, medio, feed, checkpoint):
    hr("5. FILTRO POR CHECKPOINT")
    if not feed or not feed.entries:
        print("  ⏭  Sin feed disponible")
        return

    from agents.web_agent import _parse_date, _pub_id

    total = len(feed.entries)
    pasan_checkpoint = 0
    duplicados = 0
    sin_url = 0

    for entry in feed.entries:
        url = entry.get("link", "")
        if not url:
            sin_url += 1
            continue
        fecha = _parse_date(entry)
        if checkpoint and fecha <= checkpoint:
            continue
        # Comprobar duplicado en DB
        id_externo = _pub_id(url)
        existente = db.query(Publicacion).filter(
            Publicacion.medio_id == medio.id,
            Publicacion.id_externo == id_externo,
        ).first()
        if existente:
            duplicados += 1
        else:
            pasan_checkpoint += 1

    print(f"  Total entradas RSS      : {total}")
    print(f"  Sin URL                 : {sin_url}")
    if checkpoint:
        filtradas = total - sin_url - pasan_checkpoint - duplicados
        print(f"  Filtradas por checkpoint: {filtradas}")
    print(f"  Duplicadas (ya en DB)   : {duplicados}")
    print(f"  ✅ Nuevas a insertar     : {pasan_checkpoint}")

    if pasan_checkpoint == 0 and checkpoint:
        print("\n  ⚠️  CAUSA MÁS PROBABLE: El checkpoint filtra todos los artículos")
        print(f"      Checkpoint: {checkpoint}")
        print(f"      Para forzar un nuevo escaneo, borra o ignora el checkpoint")


def check_publicaciones_db(db, medio):
    hr("6. PUBLICACIONES EN DB")
    total = db.query(Publicacion).filter(
        Publicacion.medio_id == medio.id,
        Publicacion.canal == CanalEnum.web,
    ).count()
    print(f"  Publicaciones web ya almacenadas: {total}")

    if total > 0:
        from sqlalchemy import desc
        recientes = (
            db.query(Publicacion)
            .filter(Publicacion.medio_id == medio.id, Publicacion.canal == CanalEnum.web)
            .order_by(desc(Publicacion.fecha_publicacion))
            .limit(3)
            .all()
        )
        print(f"\n  Las 3 más recientes:")
        for p in recientes:
            print(f"    · [{p.fecha_publicacion.date() if p.fecha_publicacion else '?'}] {(p.titulo or '')[:60]}")


def check_ga4_token(db, medio):
    hr("7. TOKEN GA4")
    t = db.query(TokenCanal).filter(
        TokenCanal.medio_id == medio.id,
        TokenCanal.canal == "ga4",
        TokenCanal.clave == "service_account_json",
    ).first()
    if not t:
        print("  ❌  Token GA4 (service_account_json) NO encontrado en tokens_canal")
    else:
        try:
            val = decrypt_token(t.valor_cifrado, settings.jwt_secret)
            data = json.loads(val)
            print(f"  ✅  Token GA4 encontrado")
            print(f"      project_id     : {data.get('project_id','?')}")
            print(f"      client_email   : {data.get('client_email','?')}")
        except Exception as ex:
            print(f"  ❌  Error descifrando token GA4: {ex}")


def main():
    with SessionLocal() as db:
        medio = check_medio(db)
        if not medio:
            return

        checkpoint = check_checkpoint(db, medio)
        feed = check_rss(medio)
        check_checkpoint_filter(db, medio, feed, checkpoint)
        check_brand_id(db, medio, feed)
        check_publicaciones_db(db, medio)
        check_ga4_token(db, medio)

        hr("RESUMEN")
        issues = []
        if not medio.rss_url:
            issues.append("rss_url vacío en tabla medios")
        if feed and feed.bozo:
            issues.append(f"RSS inválido (bozo): {feed.bozo_exception}")
        if not feed or not feed.entries:
            issues.append("El RSS no contiene entradas")

        if issues:
            print("  Problemas detectados:")
            for i in issues:
                print(f"    ❌  {i}")
        else:
            print("  No se detectaron problemas estructurales")
            print("  Si nuevas=0, revisar sección 5 (filtro checkpoint)")

        print()


if __name__ == "__main__":
    main()
