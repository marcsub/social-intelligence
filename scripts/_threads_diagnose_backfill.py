"""
Script de diagnostico y backfill de Threads via paramiko.
Sube un script de diagnostico al servidor, lo ejecuta, muestra la salida,
y si encuentra posts perdidos los carga desde 2026-01-01.
"""
import paramiko
import sys
import io

HOST    = "82.223.101.232"
USER    = "root"
PASS    = "GNORTEHOR1._"
PROJECT = "/home/pirineos/social-intelligence"
VENV    = f"{PROJECT}/venv/bin/python"
SLUG    = "roadrunningreview"


def run(ssh, cmd, timeout=300, label=None):
    if label:
        sys.stdout.buffer.write(f"\n[{label}]\n".encode("utf-8"))
        sys.stdout.buffer.flush()
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    combined = (out + err).strip()
    if combined:
        sys.stdout.buffer.write((combined[:8000] + "\n").encode("utf-8"))
        sys.stdout.buffer.flush()
    return combined


# ── Script de diagnostico ──────────────────────────────────────────────────────
DIAG_SCRIPT = r'''
import sys, os, json, urllib.request, urllib.parse
os.chdir("/home/pirineos/social-intelligence")
sys.path.insert(0, "/home/pirineos/social-intelligence")

from sqlalchemy.orm import sessionmaker
from core.settings import get_settings
from core.crypto import decrypt_token
from models.database import create_db_engine, Medio, Publicacion, TokenCanal, CanalEnum

settings = get_settings()
engine   = create_db_engine(settings.db_url)
Session  = sessionmaker(bind=engine)

SLUG = "roadrunningreview"
BASE_URL = "https://graph.threads.net/v1.0"

with Session() as db:
    medio = db.query(Medio).filter(Medio.slug == SLUG).first()
    if not medio:
        print("ERROR: medio no encontrado")
        sys.exit(1)

    # Leer token
    tok_row = db.query(TokenCanal).filter(
        TokenCanal.medio_id == medio.id,
        TokenCanal.canal == "threads",
        TokenCanal.clave == "access_token",
    ).first()
    uid_row = db.query(TokenCanal).filter(
        TokenCanal.medio_id == medio.id,
        TokenCanal.canal == "threads",
        TokenCanal.clave == "threads_user_id",
    ).first()

    if not tok_row:
        print("ERROR: no hay access_token para threads en BD")
        sys.exit(1)
    if not uid_row:
        print("ERROR: no hay threads_user_id en BD")
        sys.exit(1)

    access_token    = decrypt_token(tok_row.valor_cifrado, settings.jwt_secret)
    threads_user_id = decrypt_token(uid_row.valor_cifrado, settings.jwt_secret)

    print("threads_user_id:", threads_user_id)
    print("token (primeros 30 chars):", access_token[:30] if access_token else "VACIO")

    # Verificar token via /me
    try:
        p = urllib.parse.urlencode({"access_token": access_token, "fields": "id,name,username"})
        url = f"{BASE_URL}/me?{p}"
        with urllib.request.urlopen(url, timeout=10) as r:
            me = json.loads(r.read())
        print("Token OK - usuario:", me)
    except Exception as ex:
        print("ERROR token /me:", ex)

    # Llamar API threads
    try:
        p = urllib.parse.urlencode({
            "access_token": access_token,
            "fields": "id,media_type,timestamp,text",
            "limit": 10,
        })
        url = f"{BASE_URL}/{threads_user_id}/threads?{p}"
        print("Llamando:", url[:120], "...")
        with urllib.request.urlopen(url, timeout=15) as r:
            resp = json.loads(r.read())

        items = resp.get("data", [])
        paging = resp.get("paging", {})
        print("Posts devueltos por API:", len(items))
        print("Paging cursors:", list(paging.keys()))

        for it in items[:5]:
            print("  POST", it.get("id"), it.get("timestamp"), it.get("media_type"),
                  repr((it.get("text") or "")[:60]))

    except Exception as ex:
        print("ERROR llamada API:", ex)
        import traceback
        traceback.print_exc()

    # Publicaciones en BD
    total_threads = db.query(Publicacion).filter(
        Publicacion.medio_id == medio.id,
        Publicacion.canal == CanalEnum.threads,
    ).count()
    print("Publicaciones Threads en BD:", total_threads)

    from datetime import datetime, timezone
    inicio_2026 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    desde_2026 = db.query(Publicacion).filter(
        Publicacion.medio_id == medio.id,
        Publicacion.canal == CanalEnum.threads,
        Publicacion.fecha_publicacion >= inicio_2026,
    ).count()
    print("Threads 2026 en BD:", desde_2026)

    # La mas reciente
    last_pub = db.query(Publicacion).filter(
        Publicacion.medio_id == medio.id,
        Publicacion.canal == CanalEnum.threads,
    ).order_by(Publicacion.fecha_publicacion.desc()).first()
    if last_pub:
        print("Ultimo Threads en BD:", last_pub.fecha_publicacion, "-", repr((last_pub.texto or "")[:80]))

print("DIAGNOSTICO COMPLETO")
'''

# ── Script de backfill ──────────────────────────────────────────────────────────
BACKFILL_SCRIPT = r'''
import sys, os, logging
os.chdir("/home/pirineos/social-intelligence")
sys.path.insert(0, "/home/pirineos/social-intelligence")

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s")
log = logging.getLogger("backfill_threads")

from datetime import datetime, timezone
from sqlalchemy.orm import sessionmaker
from core.settings import get_settings
from models.database import create_db_engine, Medio, LogEjecucion

settings = get_settings()
engine   = create_db_engine(settings.db_url)
Session  = sessionmaker(bind=engine)

SLUG      = "roadrunningreview"
FECHA_STR = "2026-01-01"

fecha_desde = datetime.strptime(FECHA_STR, "%Y-%m-%d").replace(
    hour=0, minute=0, second=0, tzinfo=timezone.utc
)

with Session() as db:
    medio = db.query(Medio).filter(Medio.slug == SLUG).first()
    if not medio:
        log.error("Medio '%s' no encontrado", SLUG)
        sys.exit(1)

    # Reset checkpoint solo del agente threads
    logs = (db.query(LogEjecucion)
            .filter(LogEjecucion.medio_id == medio.id,
                    LogEjecucion.agente == "threads")
            .all())
    for l in logs:
        db.delete(l)

    fake = LogEjecucion(
        medio_id=medio.id, agente="threads", tipo_ejecucion="manual_reset",
        inicio=fecha_desde, fin=fecha_desde, publicaciones_nuevas=0, estado="ok",
    )
    db.add(fake)
    db.commit()
    log.info("Checkpoint threads -> %s", fecha_desde.date())
    medio_id = medio.id

from core.orchestrator import run_agent

log.info("Ejecutando threads detect_new desde %s ...", fecha_desde.date())
with Session() as agent_db:
    try:
        agent_medio = agent_db.query(Medio).filter(Medio.id == medio_id).first()
        result = run_agent(agent_db, agent_medio, "threads", tipo="manual_backfill")
        nuevas       = result.get("nuevas", 0)
        actualizadas = result.get("actualizadas", 0)
        log.info("OK: nuevas=%d actualizadas=%d", nuevas, actualizadas)
    except Exception as ex:
        log.error("ERROR: %s", ex)
        import traceback
        traceback.print_exc()
        try:
            agent_db.rollback()
        except Exception:
            pass

log.info("BACKFILL THREADS COMPLETADO")
'''


def main():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PASS, look_for_keys=False, allow_agent=False)
    sys.stdout.buffer.write(b"Conectado al servidor OK\n")
    sys.stdout.buffer.flush()

    # Subir scripts via SFTP
    sftp = ssh.open_sftp()
    sftp.putfo(io.BytesIO(DIAG_SCRIPT.encode()), "/tmp/_threads_diag.py")
    sftp.putfo(io.BytesIO(BACKFILL_SCRIPT.encode()), "/tmp/_threads_backfill.py")
    sftp.close()
    sys.stdout.buffer.write(b"Scripts subidos\n")
    sys.stdout.buffer.flush()

    # 1. Diagnostico
    run(ssh, f"cd {PROJECT} && {VENV} /tmp/_threads_diag.py 2>&1",
        timeout=60, label="DIAGNOSTICO THREADS")

    # 2. Preguntar si ejecutar backfill
    sys.stdout.buffer.write(b"\nEjecutando backfill desde 2026-01-01...\n")
    sys.stdout.buffer.flush()

    run(ssh, f"cd {PROJECT} && {VENV} /tmp/_threads_backfill.py 2>&1",
        timeout=600, label="BACKFILL THREADS 2026-01-01")

    ssh.close()
    sys.stdout.buffer.write(b"\nLISTO\n")
    sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
