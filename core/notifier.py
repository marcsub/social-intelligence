"""
core/notifier.py
Servicio de notificación por email.
Usa smtplib con las credenciales configuradas en .env.
"""
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from collections import defaultdict
from sqlalchemy.orm import Session
from models.database import Publicacion, Marca, Agencia, Medio

log = logging.getLogger(__name__)


def _send_email(to: list[str], subject: str, html: str, smtp_config: dict):
    """Envía un email HTML via SMTP."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = smtp_config["from"]
    msg["To"]      = ", ".join(to)
    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP(smtp_config["host"], smtp_config["port"]) as server:
        server.ehlo()
        if smtp_config.get("tls"):
            server.starttls()
        if smtp_config.get("user"):
            server.login(smtp_config["user"], smtp_config["password"])
        server.sendmail(smtp_config["from"], to, msg.as_bytes())


def notify_daily(db: Session, medio: Medio, nuevas: list[Publicacion], smtp_config: dict) -> int:
    """
    Agrupa publicaciones nuevas por marca y envía un email a cada contacto.
    Devuelve el número de emails enviados.
    """
    if not nuevas:
        return 0

    # Agrupar por marca
    por_marca: dict[int, list[Publicacion]] = defaultdict(list)
    sin_marca: list[Publicacion] = []

    for pub in nuevas:
        if pub.marca_id:
            por_marca[pub.marca_id].append(pub)
        else:
            sin_marca.append(pub)

    enviados = 0

    for marca_id, pubs in por_marca.items():
        marca = db.get(Marca, marca_id)
        if not marca or not marca.email_contacto:
            continue

        destinatarios = [e.strip() for e in marca.email_contacto.split(",") if e.strip()]
        if not destinatarios:
            continue

        html = _build_daily_html(medio, marca.nombre_canonico, pubs)
        subject = f"[{medio.nombre}] Publicaciones de hoy — {marca.nombre_canonico}"

        try:
            _send_email(destinatarios, subject, html, smtp_config)
            enviados += 1
            log.info(f"[{medio.slug}] Email enviado a {marca.nombre_canonico}: {len(pubs)} publicaciones")
        except Exception as ex:
            log.error(f"[{medio.slug}] Error enviando email a {marca.nombre_canonico}: {ex}")

    # Alerta de publicaciones sin marca al equipo
    if sin_marca and medio.config and medio.config.email_alertas_equipo:
        equipo = [e.strip() for e in medio.config.email_alertas_equipo.split(",") if e.strip()]
        html = _build_review_html(medio, sin_marca)
        try:
            _send_email(equipo, f"[{medio.nombre}] Publicaciones pendientes de etiquetado", html, smtp_config)
            log.info(f"[{medio.slug}] Alerta de revisión enviada: {len(sin_marca)} publicaciones")
        except Exception as ex:
            log.error(f"[{medio.slug}] Error enviando alerta de revisión: {ex}")

    return enviados


def _canal_label(canal: str) -> str:
    labels = {
        "web": "Web", "youtube": "YouTube", "instagram_post": "Instagram",
        "instagram_story": "Instagram Story", "facebook": "Facebook",
        "x": "X (Twitter)", "tiktok": "TikTok",
    }
    return labels.get(canal, canal)


def _build_daily_html(medio: Medio, marca_nombre: str, pubs: list[Publicacion]) -> str:
    fecha = datetime.now().strftime("%d/%m/%Y")
    rows = ""
    for p in pubs:
        rows += f"""
        <tr>
          <td style="padding:10px 14px;border-bottom:1px solid #f0f0f0;font-size:13px;">
            <span style="background:#e8e0f5;color:#3c3489;padding:2px 8px;border-radius:12px;font-size:11px;font-weight:500;">
              {_canal_label(str(p.canal))}
            </span>
          </td>
          <td style="padding:10px 14px;border-bottom:1px solid #f0f0f0;font-size:13px;">
            {p.titulo or '—'}
          </td>
          <td style="padding:10px 14px;border-bottom:1px solid #f0f0f0;font-size:13px;">
            <a href="{p.url}" style="color:#6c63ff;">Ver publicación →</a>
          </td>
        </tr>"""

    return f"""
    <div style="font-family:system-ui,sans-serif;max-width:640px;margin:0 auto;padding:24px;">
      <div style="background:#6c63ff;color:#fff;padding:20px 24px;border-radius:10px 10px 0 0;">
        <div style="font-size:18px;font-weight:600;">{medio.nombre}</div>
        <div style="font-size:13px;opacity:.8;margin-top:4px;">Publicaciones del {fecha}</div>
      </div>
      <div style="background:#fff;border:1px solid #eee;border-top:none;border-radius:0 0 10px 10px;padding:24px;">
        <p style="font-size:14px;color:#555;margin:0 0 20px;">
          Se han realizado <strong>{len(pubs)} publicación(es)</strong> asociadas a
          <strong>{marca_nombre}</strong> hoy.
        </p>
        <table style="width:100%;border-collapse:collapse;">
          <thead>
            <tr style="background:#f5f6fa;">
              <th style="padding:8px 14px;text-align:left;font-size:12px;color:#888;font-weight:500;">Canal</th>
              <th style="padding:8px 14px;text-align:left;font-size:12px;color:#888;font-weight:500;">Título</th>
              <th style="padding:8px 14px;text-align:left;font-size:12px;color:#888;font-weight:500;">Enlace</th>
            </tr>
          </thead>
          <tbody>{rows}</tbody>
        </table>
        <p style="font-size:12px;color:#aaa;margin-top:24px;">
          Las métricas de alcance se actualizarán automáticamente a los {medio.config.dias_actualizacion_auto if medio.config else 30} días.
        </p>
      </div>
    </div>"""


def _build_review_html(medio: Medio, pubs: list[Publicacion]) -> str:
    rows = ""
    for p in pubs:
        rows += f"""
        <tr>
          <td style="padding:8px 12px;border-bottom:1px solid #f0f0f0;font-size:12px;">{_canal_label(str(p.canal))}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #f0f0f0;font-size:12px;">{p.titulo or '—'}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #f0f0f0;font-size:12px;">{p.notas or '—'}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #f0f0f0;font-size:12px;">
            <a href="{p.url}" style="color:#6c63ff;">Ver →</a>
          </td>
        </tr>"""

    return f"""
    <div style="font-family:system-ui,sans-serif;max-width:640px;margin:0 auto;padding:24px;">
      <div style="background:#e24b4a;color:#fff;padding:20px 24px;border-radius:10px 10px 0 0;">
        <div style="font-size:16px;font-weight:600;">Publicaciones pendientes de etiquetado</div>
        <div style="font-size:12px;opacity:.8;margin-top:4px;">{medio.nombre}</div>
      </div>
      <div style="background:#fff;border:1px solid #eee;border-top:none;border-radius:0 0 10px 10px;padding:24px;">
        <p style="font-size:13px;color:#555;margin:0 0 16px;">
          {len(pubs)} publicación(es) no pudieron identificarse automáticamente y requieren etiquetado manual.
        </p>
        <table style="width:100%;border-collapse:collapse;">
          <thead><tr style="background:#f5f6fa;">
            <th style="padding:8px 12px;text-align:left;font-size:11px;color:#888;">Canal</th>
            <th style="padding:8px 12px;text-align:left;font-size:11px;color:#888;">Título</th>
            <th style="padding:8px 12px;text-align:left;font-size:11px;color:#888;">Sugerencia</th>
            <th style="padding:8px 12px;text-align:left;font-size:11px;color:#888;">URL</th>
          </tr></thead>
          <tbody>{rows}</tbody>
        </table>
      </div>
    </div>"""
