"""
scripts/backfill_shorts_historico.py
Backfill histórico de YouTube Shorts desde 2026-01-01.

Usa la playlist de uploads del canal (no la Search API) para obtener todos los
vídeos de forma fiable, con paginación completa y filtro de fecha.

Flujo:
  1. Obtiene uploadsPlaylistId via channels().list(mine=True)
  2. Pagina playlistItems().list() en orden descendente
  3. Para cuando publishedAt < 2026-01-01
  4. Verifica duración <= 60s via videos().list(part='contentDetails,snippet')
  5. Inserta los Shorts no existentes en DB (canal='youtube_short')

Uso:
    python scripts/backfill_shorts_historico.py --slug roadrunningreview
    python scripts/backfill_shorts_historico.py --slug roadrunningreview --dry-run
"""
import sys
import os
import logging
import argparse
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
log = logging.getLogger("backfill_shorts")

FECHA_INICIO = datetime(2026, 1, 1, tzinfo=timezone.utc)
SHORTS_MAX_SECONDS = 60
BATCH_SIZE = 50


def _parse_duration(iso: str) -> int:
    import re
    if not iso:
        return 0
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso)
    if not m:
        return 0
    return int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60 + int(m.group(3) or 0)


def main():
    parser = argparse.ArgumentParser(description="Backfill histórico de YouTube Shorts (2026+)")
    parser.add_argument("--slug",    required=True, help="Slug del medio")
    parser.add_argument("--dry-run", action="store_true", help="Solo diagnóstico, sin insertar")
    args = parser.parse_args()

    from sqlalchemy.orm import sessionmaker
    from googleapiclient.discovery import build

    from core.settings import get_settings
    from core.brand_id_agent import identify
    from models.database import (
        create_db_engine, Medio, Publicacion, HistorialMetricas,
        CanalEnum, TipoEnum, EstadoMetricasEnum, EstadoMarcaEnum,
    )
    from agents.youtube_agent import _build_credentials

    settings = get_settings()
    engine = create_db_engine(settings.db_url)
    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as db:
        medio = db.query(Medio).filter(Medio.slug == args.slug).first()
        if not medio:
            log.error(f"Medio '{args.slug}' no encontrado")
            sys.exit(1)

        log.info(f"=== Backfill Shorts histórico para {medio.slug} (desde {FECHA_INICIO.date()}) ===")
        if args.dry_run:
            log.info("Modo dry-run: sin cambios en DB")

        # ── Credenciales y cliente YouTube ────────────────────────────────────
        creds = _build_credentials(db, medio.id)
        if not creds:
            log.error("Sin credenciales YouTube — abortando")
            sys.exit(1)

        yt = build("youtube", "v3", credentials=creds, cache_discovery=False)

        # ── Paso 1: obtener uploadsPlaylistId ─────────────────────────────────
        ch_resp = yt.channels().list(part="contentDetails", mine=True).execute()
        ch_items = ch_resp.get("items", [])
        if not ch_items:
            log.error("channels().list no devolvió items — verifica credenciales OAuth")
            sys.exit(1)

        uploads_playlist = (
            ch_items[0]
            .get("contentDetails", {})
            .get("relatedPlaylists", {})
            .get("uploads", "")
        )
        if not uploads_playlist:
            log.error("No se encontró uploadsPlaylistId en la respuesta")
            sys.exit(1)

        log.info(f"Uploads playlist: {uploads_playlist}")

        # ── Paso 2: paginar playlistItems hasta FECHA_INICIO ──────────────────
        all_video_ids: list[str] = []   # todos los video_id dentro de fecha
        total_escaneados = 0
        page_token = None
        page_num = 0
        stop_pagination = False

        while not stop_pagination:
            page_num += 1
            req_params: dict = {
                "part":       "snippet",
                "playlistId": uploads_playlist,
                "maxResults": BATCH_SIZE,
            }
            if page_token:
                req_params["pageToken"] = page_token

            try:
                pl_resp = yt.playlistItems().list(**req_params).execute()
            except Exception as ex:
                log.error(f"Error en playlistItems().list (página {page_num}): {ex}")
                break

            pl_items = pl_resp.get("items", [])
            dentro_fecha = 0
            shorts_pagina = 0  # se calcula tras videos.list; aquí solo contamos para el log

            for pl_item in pl_items:
                total_escaneados += 1
                snippet = pl_item.get("snippet", {})
                published_str = snippet.get("publishedAt", "")
                video_id = snippet.get("resourceId", {}).get("videoId", "")

                if not video_id:
                    continue

                # Parsear fecha de publicación
                try:
                    pub_dt = datetime.fromisoformat(published_str.replace("Z", "+00:00"))
                except Exception:
                    pub_dt = None

                if pub_dt and pub_dt < FECHA_INICIO:
                    log.info(
                        f"  video_id={video_id} publishedAt={published_str[:10]} "
                        f"< {FECHA_INICIO.date()} — parando paginación"
                    )
                    stop_pagination = True
                    break

                all_video_ids.append(video_id)
                dentro_fecha += 1

            log.info(
                f"Página {page_num}: {len(pl_items)} vídeos, "
                f"{dentro_fecha} dentro de fecha "
                f"(acumulado: {len(all_video_ids)})"
            )

            page_token = pl_resp.get("nextPageToken")
            if not page_token:
                break

        log.info(f"Paginación completa: {total_escaneados} escaneados, {len(all_video_ids)} dentro de {FECHA_INICIO.date()}")

        # ── Paso 3: obtener detalles en lotes de 50 y filtrar Shorts ─────────
        config = medio.config
        umbral = config.umbral_confianza_marca if config else 80

        shorts_encontrados = 0
        nuevos_insertados = 0
        nuevos: list[Publicacion] = []

        for i in range(0, len(all_video_ids), BATCH_SIZE):
            batch = all_video_ids[i:i + BATCH_SIZE]
            log.info(f"videos.list lote {i // BATCH_SIZE + 1}: {len(batch)} vídeos...")

            try:
                v_resp = yt.videos().list(
                    part="contentDetails,snippet,statistics",
                    id=",".join(batch),
                ).execute()
            except Exception as ex:
                log.error(f"Error en videos.list (lote {i // BATCH_SIZE + 1}): {ex}")
                continue

            for v_item in v_resp.get("items", []):
                video_id    = v_item["id"]
                duration_iso = v_item.get("contentDetails", {}).get("duration", "")
                duration_s   = _parse_duration(duration_iso)
                snippet      = v_item.get("snippet", {})
                stats        = v_item.get("statistics", {})
                titulo       = snippet.get("title", "")
                descripcion  = snippet.get("description", "")[:500]
                tags         = " ".join(snippet.get("tags", []))
                published_str = snippet.get("publishedAt", "")

                log.info(f"  {video_id}: duration={duration_s}s ({duration_iso}) title={titulo[:50]}")

                # Criterio principal: duración
                if duration_s > SHORTS_MAX_SECONDS:
                    log.info(f"  → No es Short ({duration_s}s > {SHORTS_MAX_SECONDS}s)")
                    continue

                # Fallback: sin duración, comprobar #Shorts en título
                if duration_iso == "" and "#shorts" not in titulo.lower():
                    log.info(f"  → Sin duración ni #Shorts en título — omitido")
                    continue

                shorts_encontrados += 1
                log.info(f"  → Short confirmado: {video_id}")

                # Verificar duplicado (solo canal youtube_short)
                existe = db.query(Publicacion).filter(
                    Publicacion.medio_id == medio.id,
                    Publicacion.canal    == CanalEnum.youtube_short,
                    Publicacion.id_externo == video_id,
                ).first()
                if existe:
                    log.info(f"  → Ya existe en DB (id={existe.id}) — omitido")
                    continue

                if args.dry_run:
                    log.info(f"  → [dry-run] Se insertaría: {titulo[:60]}")
                    nuevos_insertados += 1
                    continue

                # Parsear fecha de publicación
                try:
                    fecha = datetime.fromisoformat(published_str.replace("Z", "+00:00"))
                except Exception:
                    fecha = datetime.now(timezone.utc)

                url = f"https://www.youtube.com/shorts/{video_id}"

                brand = identify(
                    medio_id=medio.id,
                    db=db,
                    title=titulo,
                    description=descripcion,
                    hashtags=tags,
                    url=url,
                )

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
                    medio_id    = medio.id,
                    marca_id    = brand.marca_id,
                    agencia_id  = brand.agencia_id,
                    id_externo  = video_id,
                    canal       = CanalEnum.youtube_short,
                    tipo        = TipoEnum.short,
                    url         = url,
                    titulo      = titulo,
                    texto       = descripcion or None,
                    fecha_publicacion = fecha,
                    reach    = int(stats.get("viewCount",    0)),
                    likes    = int(stats.get("likeCount",    0)),
                    comments = int(stats.get("commentCount", 0)),
                    estado_metricas  = estado,
                    confianza_marca  = brand.confianza if brand.confianza > 0 else None,
                    estado_marca     = estado_marca,
                    notas = brand.razonamiento if estado == EstadoMetricasEnum.revisar else None,
                )
                db.add(pub)
                db.flush()

                db.add(HistorialMetricas(
                    publicacion_id = pub.id,
                    reach    = pub.reach,
                    likes    = pub.likes,
                    shares   = 0,
                    comments = pub.comments,
                    clicks   = 0,
                ))

                nuevos.append(pub)
                nuevos_insertados += 1
                log.info(
                    f"  → Insertado: {titulo[:60]} "
                    f"— marca: {brand.marca_nombre} ({brand.confianza}%)"
                )

        if not args.dry_run:
            db.commit()

        # ── Resumen final ─────────────────────────────────────────────────────
        print(
            f"\nTotal escaneados: {total_escaneados} | "
            f"Shorts encontrados: {shorts_encontrados} | "
            f"Nuevos insertados: {nuevos_insertados}"
        )
        if nuevos:
            for pub in nuevos:
                print(f"  [{pub.fecha_publicacion.date()}] {pub.titulo[:70]}")


if __name__ == "__main__":
    main()
