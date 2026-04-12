"""
core/orchestrator.py
Orquestador central: coordina agentes, gestiona checkpoints,
escribe en Log y lanza notificaciones.
Se ejecuta via APScheduler o manualmente desde la API.
"""
import logging
import json
from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy.orm import Session, sessionmaker

from models.database import (
    Medio, Publicacion, LogEjecucion,
    CanalEnum, EstadoMetricasEnum
)
from agents import web_agent, youtube_agent, youtube_shorts_agent, instagram_agent, facebook_agent, threads_agent, tiktok_agent
from agents import instagram_stories_agent
from agents import meta_ads_agent, google_ads_agent
from core.notifier import notify_daily
from core.settings import get_settings

log = logging.getLogger(__name__)
settings = get_settings()

# SMTP config por defecto (añadir a .env en producción)
DEFAULT_SMTP = {
    "host":     "localhost",
    "port":     25,
    "tls":      False,
    "user":     "",
    "password": "",
    "from":     "noreply@social-intelligence.local",
}


# ── Checkpoint helpers ────────────────────────────────────────────────────────

def _get_checkpoint(db: Session, medio_id: int, agente: str) -> Optional[datetime]:
    """
    Devuelve el timestamp del último run exitoso de un agente para un medio.
    Basado en la última entrada de log con estado='ok'.
    """
    last = (
        db.query(LogEjecucion)
        .filter(
            LogEjecucion.medio_id == medio_id,
            LogEjecucion.agente == agente,
            LogEjecucion.estado == "ok",
        )
        .order_by(LogEjecucion.fin.desc())
        .first()
    )
    if not last or not last.fin:
        return None
    fin = last.fin
    if fin.tzinfo is None:
        fin = fin.replace(tzinfo=timezone.utc)
    return fin


def _log_start(db: Session, medio_id: int, agente: str, tipo: str) -> LogEjecucion:
    entry = LogEjecucion(
        medio_id=medio_id,
        agente=agente,
        tipo_ejecucion=tipo,
        inicio=datetime.now(timezone.utc),
        estado="corriendo",
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def _log_end(db: Session, entry: LogEjecucion, nuevas=0, actualizadas=0, revision=0, emails=0, errores=None):
    entry.fin = datetime.now(timezone.utc)
    entry.publicaciones_nuevas = nuevas
    entry.publicaciones_actualizadas = actualizadas
    entry.publicaciones_revision = revision
    entry.emails_enviados = emails
    entry.estado = "error" if errores else "ok"
    entry.errores = json.dumps(errores) if errores else None
    db.commit()


# ── Registro de agentes ───────────────────────────────────────────────────────

AGENTS = {
    "web":            web_agent,
    "youtube":        youtube_agent,
    "youtube_shorts": youtube_shorts_agent,
    "instagram":      instagram_agent,
    "facebook":       facebook_agent,
    "threads":        threads_agent,
    "tiktok":         tiktok_agent,
}

# Canal asociado a cada agente (para query de métricas pendientes en run_agent).
# youtube_shorts NO está aquí: sus métricas se actualizan en el job de 48h propio.
AGENT_CANAL: dict[str, CanalEnum] = {
    "web":       CanalEnum.web,
    "youtube":   CanalEnum.youtube,
    "instagram": CanalEnum.instagram_post,
    "facebook":  CanalEnum.facebook,
    "threads":   CanalEnum.threads,
    "tiktok":    CanalEnum.tiktok,
}


# ── Ejecución de un agente para un medio ─────────────────────────────────────

def run_agent(db: Session, medio: Medio, agente_name: str, tipo: str = "diario") -> dict:
    """
    Ejecuta un agente específico para un medio:
    1. Detecta publicaciones nuevas
    2. Actualiza métricas de publicaciones pendientes
    3. Registra en Log
    """
    agent = AGENTS.get(agente_name)
    if not agent:
        log.warning(f"Agente '{agente_name}' no registrado")
        return {"nuevas": 0, "actualizadas": 0, "revision": 0}

    log_entry = _log_start(db, medio.id, agente_name, tipo)
    errores = []
    nuevas_pubs = []

    # 1. Detección de publicaciones nuevas
    try:
        checkpoint = _get_checkpoint(db, medio.id, agente_name)
        nuevas_pubs = agent.detect_new(db, medio, checkpoint)
        log.info(f"[{medio.slug}/{agente_name}] {len(nuevas_pubs)} publicaciones nuevas")
    except Exception as ex:
        log.error(f"[{medio.slug}/{agente_name}] Error en detección: {ex}")
        errores.append({"fase": "deteccion", "error": str(ex)})

    # 2. Actualización de métricas (publicaciones recientes pendientes/con error)
    actualizadas = 0
    canal_enum = AGENT_CANAL.get(agente_name)
    if canal_enum:
        try:
            dias = medio.config.dias_actualizacion_auto if medio.config else 30
            # >= : publicaciones de los últimos N días (recientes, con métricas cambiantes)
            umbral_fecha = datetime.now(timezone.utc) - timedelta(days=dias)

            pendientes = (
                db.query(Publicacion)
                .filter(
                    Publicacion.medio_id == medio.id,
                    Publicacion.canal == canal_enum,
                    Publicacion.fecha_publicacion >= umbral_fecha,
                    Publicacion.estado_metricas.in_([
                        EstadoMetricasEnum.pendiente,
                        EstadoMetricasEnum.error,
                        EstadoMetricasEnum.actualizado,
                    ]),
                )
                # Primero las nunca actualizadas, luego las más antiguas
                .order_by(
                    Publicacion.ultima_actualizacion.is_(None).desc(),
                    Publicacion.ultima_actualizacion.asc(),
                )
                .limit(50)
                .all()
            )

            if pendientes:
                actualizadas = agent.update_metrics(db, medio, pendientes)
        except Exception as ex:
            log.error(f"[{medio.slug}/{agente_name}] Error en actualización: {ex}")
            errores.append({"fase": "actualizacion", "error": str(ex)})

    revision = sum(1 for p in nuevas_pubs if p.estado_metricas == EstadoMetricasEnum.revisar)

    _log_end(db, log_entry, len(nuevas_pubs), actualizadas, revision, errores=errores if errores else None)

    return {
        "nuevas": len(nuevas_pubs),
        "actualizadas": actualizadas,
        "revision": revision,
        "pubs": nuevas_pubs,
    }


# ── Ejecución de stories ──────────────────────────────────────────────────────

def run_stories(db: Session, medio: Medio) -> dict:
    """
    Entrada manual/API: detecta stories y actualiza métricas activas.
    En producción el scheduler usa _job_stories_hourly() + _job_stories_final().
    """
    if not medio.activo:
        return {}

    log_entry = _log_start(db, medio.id, "instagram_stories_hourly", "stories")
    errores = []

    try:
        nuevas = instagram_stories_agent.detect_and_update(db, medio)
        log.info(f"[{medio.slug}/stories] {len(nuevas)} stories nuevas")
    except Exception as ex:
        log.error(f"[{medio.slug}/stories] Error en detect_and_update: {ex}")
        nuevas = []
        errores.append({"fase": "detect_and_update", "error": str(ex)})

    revision = sum(1 for p in nuevas if p.estado_metricas == EstadoMetricasEnum.revisar)
    _log_end(db, log_entry, len(nuevas), 0, revision, errores=errores if errores else None)

    return {"nuevas": len(nuevas), "revision": revision}


# ── Ejecución diaria completa para un medio ───────────────────────────────────

def run_daily(db: Session, medio: Medio, smtp_config: dict = None) -> dict:
    """
    Ejecuta todos los agentes activos para un medio y envía notificaciones.
    Punto de entrada para el trigger diario del scheduler.
    """
    if not medio.activo:
        log.info(f"[{medio.slug}] Medio inactivo, saltando")
        return {}

    log.info(f"[{medio.slug}] === Ejecución diaria iniciada ===")
    smtp = smtp_config or DEFAULT_SMTP
    todas_nuevas = []
    resumen = {}

    for agente_name in AGENTS:
        result = run_agent(db, medio, agente_name, tipo="diario")
        resumen[agente_name] = result
        todas_nuevas.extend(result.get("pubs", []))

    # Notificaciones por email
    emails = 0
    if todas_nuevas:
        try:
            emails = notify_daily(db, medio, todas_nuevas, smtp)
        except Exception as ex:
            log.error(f"[{medio.slug}] Error en notificaciones: {ex}")

    log.info(
        f"[{medio.slug}] === Ejecución completada — "
        f"nuevas: {sum(r['nuevas'] for r in resumen.values())}, "
        f"emails: {emails} ==="
    )
    return resumen


# ── Actualización manual por marca ────────────────────────────────────────────

def run_update_by_marca(db: Session, medio: Medio, marca_id: int) -> dict:
    """
    Actualiza todas las métricas de publicaciones de una marca específica.
    Invocado desde el panel web manualmente.
    """
    log.info(f"[{medio.slug}] Actualización manual para marca_id={marca_id}")
    resumen = {}

    for agente_name, agent in AGENTS.items():
        canal_enum = AGENT_CANAL.get(agente_name)
        if not canal_enum:
            continue
        pubs = (
            db.query(Publicacion)
            .filter(
                Publicacion.medio_id == medio.id,
                Publicacion.marca_id == marca_id,
                Publicacion.canal == canal_enum,
                Publicacion.estado_metricas != EstadoMetricasEnum.fijo,
            )
            .all()
        )
        if pubs:
            actualizadas = agent.update_metrics(db, medio, pubs)
            resumen[agente_name] = {"actualizadas": actualizadas, "total": len(pubs)}

    return resumen


# ── Scheduler setup ───────────────────────────────────────────────────────────

def setup_scheduler(SessionLocal: sessionmaker):
    """
    Configura y arranca APScheduler con los triggers de todos los medios activos.
    Se llama una vez al inicio de la aplicación.
    """
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.executors.pool import ThreadPoolExecutor

    executors = {"default": ThreadPoolExecutor(max_workers=4)}
    job_defaults = {
        "coalesce":          True,   # Si se perdieron N ejecuciones, ejecutar una sola vez
        "max_instances":     1,      # Nunca ejecutar el mismo job en paralelo
        "misfire_grace_time": 3600,  # Si el servidor estuvo caído, ejecutar hasta 1h después
    }
    scheduler = BackgroundScheduler(
        timezone="UTC",
        executors=executors,
        job_defaults=job_defaults,
    )

    with SessionLocal() as db:
        medios = db.query(Medio).filter(Medio.activo == True).all()
        for medio in medios:
            _register_medio_jobs(scheduler, SessionLocal, medio)

    scheduler.start()
    log.info(f"Scheduler iniciado con {len(scheduler.get_jobs())} jobs")
    return scheduler


def _add_job(scheduler, func, trigger, args, job_id, name, **kwargs):
    """Wrapper seguro para add_job con opciones de robustez.
    coalesce/max_instances/misfire_grace_time ya vienen de job_defaults;
    sólo se pasan en kwargs si se quieren sobreescribir para un job concreto.
    """
    scheduler.add_job(
        func=func,
        trigger=trigger,
        args=args,
        id=job_id,
        name=name,
        replace_existing=True,
        **kwargs,
    )


def _register_medio_jobs(scheduler, SessionLocal, medio: Medio):
    """Registra los jobs de un medio en el scheduler."""
    from apscheduler.triggers.cron import CronTrigger

    config = medio.config
    hora_diario = (config.hora_trigger_diario or "07:00") if config else "07:00"
    h_d, m_d = hora_diario.split(":")
    slug = medio.slug

    # ── Job horario (todos los canales) — cada hora a :10 ─────────────────────
    # Detecta nuevas publicaciones + actualiza métricas pendientes en todos los canales.
    # Se escalona a :10 para no coincidir con stories (:00) ni otros jobs.
    _add_job(
        scheduler, _job_hourly,
        trigger=CronTrigger(minute=10),
        args=[SessionLocal, medio.id],
        job_id=f"{slug}_hourly",
        name=f"{slug} — detección+métricas horaria (todos canales)",
    )
    log.info(f"[{slug}] Job horario registrado (cada :10 UTC)")

    # ── Job diario — notificaciones + detección adicional ─────────────────────
    # Sigue corriendo para emails y logs de resumen diario.
    _add_job(
        scheduler, _job_daily,
        trigger=CronTrigger(hour=int(h_d), minute=int(m_d)),
        args=[SessionLocal, medio.id],
        job_id=f"{slug}_daily",
        name=f"{slug} — resumen diario + notificaciones",
    )
    log.info(f"[{slug}] Job diario registrado a las {hora_diario} UTC")

    # ── Stories: cada hora en punto (:00) ─────────────────────────────────────
    _add_job(
        scheduler, _job_stories_hourly,
        trigger=CronTrigger(minute=0),
        args=[SessionLocal, medio.id],
        job_id=f"{slug}_stories_hourly",
        name=f"{slug} — stories horario",
    )
    # Captura final stories: :50-:59 cada hora
    _add_job(
        scheduler, _job_stories_final,
        trigger=CronTrigger(minute="50-59"),
        args=[SessionLocal, medio.id],
        job_id=f"{slug}_stories_final",
        name=f"{slug} — stories captura final",
        misfire_grace_time=60,  # captura final: solo vale por 1 min
    )
    log.info(f"[{slug}] Jobs stories: horario (:00) + captura final (:50-:59)")

    # ── Shorts: cada 48h ───────────────────────────────────────────────────────
    _add_job(
        scheduler, _job_shorts_update,
        trigger="interval", hours=48,
        args=[SessionLocal, medio.id],
        job_id=f"{slug}_youtube_shorts_update",
        name=f"{slug} — YouTube Shorts actualización 48h",
    )
    log.info(f"[{slug}] Job Shorts update registrado (intervalo 48h)")

    # ── Jobs semanales — lunes, escalonados ───────────────────────────────────
    _WEEKLY_FUNCS = [
        ("web_ga4",        0,  0,  "GA4 histórico",            _job_weekly_web_ga4),
        ("youtube",        0,  30, "YouTube Analytics",        _job_weekly_youtube),
        ("youtube_shorts", 0,  45, "YouTube Shorts Analytics", _job_weekly_youtube_shorts),
        ("instagram",      1,  0,  "Instagram snapshot",       _job_weekly_instagram),
        ("facebook",       1,  30, "Facebook snapshot",        _job_weekly_facebook),
        ("threads",        2,  0,  "Threads snapshot",         _job_weekly_threads),
        ("tiktok",         2,  30, "TikTok snapshot",          _job_weekly_tiktok),
    ]
    for job_name, hour, minute, desc, func in _WEEKLY_FUNCS:
        _add_job(
            scheduler, func,
            trigger=CronTrigger(day_of_week="mon", hour=hour, minute=minute),
            args=[SessionLocal, medio.id],
            job_id=f"{slug}_weekly_{job_name}",
            name=f"{slug} — {desc}",
        )
    log.info(f"[{slug}] Jobs semanales registrados (lunes 00:00→02:30 UTC)")

    # ── Métricas pagadas — martes 03:00 UTC ───────────────────────────────────
    _add_job(
        scheduler, _job_weekly_paid_metrics,
        trigger=CronTrigger(day_of_week="tue", hour=3, minute=0),
        args=[SessionLocal, medio.id],
        job_id=f"{slug}_weekly_paid_metrics",
        name=f"{slug} — Sync métricas pagadas (Ads)",
    )
    log.info(f"[{slug}] Job paid_metrics registrado (martes 03:00 UTC)")


def _safe_session(SessionLocal, medio_id: int):
    """Abre sesión y carga medio de forma segura. Devuelve (db, medio) o (None, None)."""
    try:
        db = SessionLocal()
        medio = db.get(Medio, medio_id)
        if not medio or not medio.activo:
            db.close()
            return None, None
        return db, medio
    except Exception as ex:
        log.error(f"[scheduler] Error abriendo sesión DB para medio {medio_id}: {ex}")
        return None, None


def _job_hourly(SessionLocal, medio_id: int):
    """
    Job horario (cada :10) — detecta nuevas publicaciones + actualiza métricas
    para TODOS los canales. Usa run_agent() por agente para que cada uno tenga
    su propio log y checkpoint independiente. Un fallo en un canal no afecta a los demás.
    """
    db, medio = _safe_session(SessionLocal, medio_id)
    if not db:
        return
    try:
        for agente_name in AGENTS:
            try:
                result = run_agent(db, medio, agente_name, tipo="horario")
                if result["nuevas"] or result["actualizadas"]:
                    log.info(
                        f"[{medio.slug}/{agente_name}] horario — "
                        f"nuevas={result['nuevas']} actualizadas={result['actualizadas']}"
                    )
            except Exception as ex:
                log.error(f"[{medio.slug}/{agente_name}] Error inesperado en job horario: {ex}")
    finally:
        db.close()


def _job_daily(SessionLocal, medio_id: int):
    """Job diario — notificaciones + detección de seguridad."""
    db, medio = _safe_session(SessionLocal, medio_id)
    if not db:
        return
    try:
        run_daily(db, medio)
    except Exception as ex:
        log.error(f"[{medio.slug if medio else medio_id}] Error en job diario: {ex}")
    finally:
        db.close()


def _job_stories_hourly(SessionLocal, medio_id: int):
    """Job horario stories — detecta nuevas y actualiza métricas activas."""
    db, medio = _safe_session(SessionLocal, medio_id)
    if not db:
        return

    _check_stories_alert(db, medio)
    log_entry = _log_start(db, medio.id, "instagram_stories_hourly", "stories")
    errores = []
    nuevas = []
    actualizadas_count = 0
    try:
        # detect_and_update devuelve solo las nuevas; las actualizadas se cuentan
        # leyendo cuántas stories activas había antes de la llamada
        activas_antes = db.query(Publicacion).filter(
            Publicacion.medio_id == medio.id,
            Publicacion.canal == CanalEnum.instagram_story,
            Publicacion.estado_metricas != EstadoMetricasEnum.fijo,
        ).count()
        nuevas = instagram_stories_agent.detect_and_update(db, medio)
        activas_despues = db.query(Publicacion).filter(
            Publicacion.medio_id == medio.id,
            Publicacion.canal == CanalEnum.instagram_story,
            Publicacion.estado_metricas != EstadoMetricasEnum.fijo,
        ).count()
        # Las actualizadas son las que estaban activas y siguen activas (excluye las nuevas)
        actualizadas_count = max(0, activas_antes - len(nuevas))
        log.info(f"[{medio.slug}] Stories: {len(nuevas)} nuevas, ~{actualizadas_count} actualizadas, {activas_despues} aún activas")
    except Exception as ex:
        log.error(f"[{medio.slug}] Error en stories horario: {ex}")
        errores.append({"fase": "detect_and_update", "error": str(ex)})
    _log_end(db, log_entry, nuevas=len(nuevas), actualizadas=actualizadas_count, errores=errores if errores else None)
    db.close()


def _job_stories_final(SessionLocal, medio_id: int):
    """Job captura final stories — :50-:59 cada hora, solo si hay stories próximas a caducar."""
    db, medio = _safe_session(SessionLocal, medio_id)
    if not db:
        return
    log_entry = _log_start(db, medio.id, "instagram_stories_final", "stories")
    errores = []
    try:
        n = instagram_stories_agent.capture_final(db, medio)
        _log_end(db, log_entry, actualizadas=n)
    except Exception as ex:
        log.error(f"[{medio.slug}] Error en stories captura final: {ex}")
        errores.append({"fase": "capture_final", "error": str(ex)})
        _log_end(db, log_entry, errores=errores)
    finally:
        db.close()


def _check_stories_alert(db: Session, medio: Medio):
    """
    Envía alerta por email si el trigger horario de stories lleva más de 2 horas
    sin ejecutarse. Con el nuevo diseño horario, una brecha de >2h indica problema.
    """
    last = (
        db.query(LogEjecucion)
        .filter(
            LogEjecucion.medio_id == medio.id,
            LogEjecucion.agente.in_(["instagram_stories_hourly", "instagram_stories"]),
        )
        .order_by(LogEjecucion.fin.desc())
        .first()
    )
    if last and last.fin:
        fin = last.fin.replace(tzinfo=timezone.utc) if last.fin.tzinfo is None else last.fin
        horas = (datetime.now(timezone.utc) - fin).total_seconds() / 3600
        if horas <= 2:
            return  # ejecución reciente — sin alerta

    # Han pasado >2h (o nunca ha corrido): enviar alerta
    try:
        from core.notifier import send_email
        asunto = f"[{medio.slug}] ALERTA: trigger Stories horario no ejecutado en >2h"
        cuerpo = (
            f"El job horario de Instagram Stories para '{medio.nombre}' ({medio.slug}) "
            f"no se ha ejecutado en las últimas 2 horas.\n\n"
            f"Con el nuevo trigger horario, esto indica un problema en el scheduler.\n"
            f"Las stories pueden perderse si no se capturan antes de las 24h.\n\n"
            f"Comprueba el scheduler y los logs de la aplicación.\n"
        )
        smtp = DEFAULT_SMTP
        send_email(smtp, smtp["from"], [smtp["from"]], asunto, cuerpo)
        log.warning(f"[{medio.slug}] Alerta stories enviada: >2h sin ejecución")
    except Exception as ex:
        log.error(f"[{medio.slug}] No se pudo enviar alerta stories: {ex}")


def _job_weekly_web_ga4(SessionLocal, medio_id: int):
    db, medio = _safe_session(SessionLocal, medio_id)
    if not db: return
    try:
        _run_weekly_agent(db, medio, "web_ga4", web_agent.update_weekly_ga4)
    finally:
        db.close()


def _job_shorts_update(SessionLocal, medio_id: int):
    """Job de actualización de Shorts cada 48h — solo procesa los shorts con > 48h de antigüedad."""
    db, medio = _safe_session(SessionLocal, medio_id)
    if not db: return
    log_entry = _log_start(db, medio.id, "youtube_shorts", "shorts_update")
    errores = []
    actualizadas = 0
    try:
        umbral_48h = datetime.now(timezone.utc) - timedelta(hours=48)
        pubs = (
            db.query(Publicacion)
            .filter(
                Publicacion.medio_id == medio.id,
                Publicacion.canal == CanalEnum.youtube_short,
                Publicacion.fecha_publicacion <= umbral_48h,
                Publicacion.estado_metricas.in_([
                    EstadoMetricasEnum.pendiente,
                    EstadoMetricasEnum.actualizado,
                ]),
            )
            .order_by(
                Publicacion.ultima_actualizacion.is_(None).desc(),
                Publicacion.ultima_actualizacion.asc(),
            )
            .limit(50)
            .all()
        )
        if pubs:
            actualizadas = youtube_shorts_agent.update_metrics(db, medio, pubs)
    except Exception as ex:
        log.error(f"[{medio.slug}] Error en Shorts update 48h: {ex}")
        errores.append({"fase": "update_metrics", "error": str(ex)})
    finally:
        _log_end(db, log_entry, actualizadas=actualizadas, errores=errores if errores else None)
        db.close()


def _job_weekly_youtube(SessionLocal, medio_id: int):
    db, medio = _safe_session(SessionLocal, medio_id)
    if not db: return
    try:
        _run_weekly_agent(db, medio, "youtube", youtube_agent.update_weekly_youtube)
    finally:
        db.close()


def _job_weekly_youtube_shorts(SessionLocal, medio_id: int):
    db, medio = _safe_session(SessionLocal, medio_id)
    if not db: return
    try:
        _run_weekly_agent(db, medio, "youtube_shorts", youtube_shorts_agent.snapshot_weekly)
    finally:
        db.close()


def _job_weekly_instagram(SessionLocal, medio_id: int):
    db, medio = _safe_session(SessionLocal, medio_id)
    if not db: return
    try:
        _run_weekly_agent(db, medio, "instagram", instagram_agent.snapshot_weekly)
    finally:
        db.close()


def _job_weekly_facebook(SessionLocal, medio_id: int):
    db, medio = _safe_session(SessionLocal, medio_id)
    if not db: return
    try:
        _run_weekly_agent(db, medio, "facebook", facebook_agent.snapshot_weekly)
    finally:
        db.close()


def _job_weekly_threads(SessionLocal, medio_id: int):
    db, medio = _safe_session(SessionLocal, medio_id)
    if not db: return
    try:
        _run_weekly_agent(db, medio, "threads", threads_agent.snapshot_weekly)
    finally:
        db.close()


def _job_weekly_tiktok(SessionLocal, medio_id: int):
    db, medio = _safe_session(SessionLocal, medio_id)
    if not db: return
    try:
        _run_weekly_agent(db, medio, "tiktok", tiktok_agent.snapshot_weekly)
    finally:
        db.close()


def _job_weekly_paid_metrics(SessionLocal, medio_id: int):
    """Job semanal (martes 03:00 UTC) — sincroniza métricas pagadas desde Meta Ads y Google Ads."""
    db, medio = _safe_session(SessionLocal, medio_id)
    if not db: return
    log_entry = _log_start(db, medio.id, "paid_metrics", "semanal")
    errores = []
    actualizadas = 0
    try:
        n = meta_ads_agent.sync_paid_metrics(db, medio)
        actualizadas += n
    except Exception as ex:
        log.error(f"[{medio.slug}] Error meta_ads paid_metrics: {ex}")
        errores.append({"fase": "meta_ads", "error": str(ex)})
    try:
        ok, _ = google_ads_agent.check_access(db, medio.id)
        if ok:
            n = google_ads_agent.sync_paid_metrics(db, medio)
            actualizadas += n
    except Exception as ex:
        log.error(f"[{medio.slug}] Error google_ads paid_metrics: {ex}")
        errores.append({"fase": "google_ads", "error": str(ex)})
    finally:
        _log_end(db, log_entry, actualizadas=actualizadas, errores=errores if errores else None)
        db.close()


def _run_weekly_agent(db: Session, medio: Medio, agente_name: str, func) -> int:
    """
    Ejecuta un agente semanal con log propio en log_ejecuciones.
    Devuelve el número de publicaciones procesadas.
    """
    log_entry = _log_start(db, medio.id, f"semanal_{agente_name}", "semanal")
    errores = []
    n = 0
    try:
        n = func(db, medio)
        log.info(f"[{medio.slug}] semanal_{agente_name}: {n} procesadas")
    except Exception as ex:
        log.error(f"[{medio.slug}] Error semanal_{agente_name}: {ex}")
        errores.append({"fase": agente_name, "error": str(ex)})
    _log_end(db, log_entry, 0, n, errores=errores if errores else None)
    return n


def run_semanal(db: Session, medio: Medio) -> dict:
    """
    Ejecución semanal completa (entrada manual o API):
    Orden: GA4 web → YouTube Analytics → Instagram → Facebook → Threads
    Cada agente escribe su propio log en log_ejecuciones.
    Si un agente falla se continúa con el siguiente.
    """
    if not medio.activo:
        return {}

    from utils.semanas import get_semana_iso
    from datetime import date as _date

    semana_actual = get_semana_iso(_date.today())
    log.info(f"[{medio.slug}] === Snapshot semanal {semana_actual} iniciado ===")

    steps = [
        ("web_ga4",        lambda d, m: web_agent.update_weekly_ga4(d, m)),
        ("youtube",        lambda d, m: youtube_agent.update_weekly_youtube(d, m)),
        ("youtube_shorts", lambda d, m: youtube_shorts_agent.snapshot_weekly(d, m)),
        ("instagram",      lambda d, m: instagram_agent.snapshot_weekly(d, m)),
        ("facebook",       lambda d, m: facebook_agent.snapshot_weekly(d, m)),
        ("threads",        lambda d, m: threads_agent.snapshot_weekly(d, m)),
        ("tiktok",         lambda d, m: tiktok_agent.snapshot_weekly(d, m)),
        ("paid_meta",      lambda d, m: meta_ads_agent.sync_paid_metrics(d, m)),
        ("paid_google",    lambda d, m: google_ads_agent.sync_paid_metrics(d, m) if google_ads_agent.check_access(d, m.id)[0] else 0),
    ]

    resumen: dict = {}
    total_actualizadas = 0
    for nombre, fn in steps:
        n = _run_weekly_agent(db, medio, nombre, fn)
        resumen[nombre] = {"actualizadas": n}
        total_actualizadas += n

    log.info(f"[{medio.slug}] === Snapshot semanal completado — {total_actualizadas} actualizadas ===")
    return resumen
