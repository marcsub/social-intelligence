# Social Intelligence System — STATUS

> Última actualización: 2026-04-19 — v0.9

---

## Descripción del proyecto

Sistema multi-medio de recogida automática de métricas de publicaciones en redes sociales
y web. Permite a ROADRUNNINGReview y TRAILRUNNINGReview (y otros medios) agregar el reach,
likes, shares y comentarios de todas sus publicaciones por marca, canal y período, generando
informes de campaña y notificaciones automáticas a cada marca cliente.

---

## Stack tecnológico

| Capa | Tecnología |
|------|-----------|
| Backend API | Python 3.13 + FastAPI + SQLAlchemy (ORM) |
| Base de datos | MySQL — `social_intelligence` |
| Frontend | React 18 + Vite + Chart.js |
| Scheduler | APScheduler 3.x — BackgroundScheduler UTC |
| Cifrado tokens | Fernet (AES-128-CBC) derivado de `JWT_SECRET` |
| Notificaciones | SMTP por medio |
| Servidor producción | CentOS — Apache + mod_proxy → uvicorn :8000 |
| Entorno desarrollo | Windows 11 local — uvicorn `localhost:8000` |

---

## Entorno de producción

| Parámetro | Valor |
|-----------|-------|
| URL panel | https://www.roadrunningreview.com/social/ |
| Proyecto servidor | `/home/pirineos/social-intelligence` |
| Servidor web | Apache con mod_proxy (no nginx) |
| Git repo | https://github.com/marcsub/social-intelligence |
| API base URL prod | `API_BASE=/social/api` |
| API base URL dev | `API_BASE=/api` |

### Configuración Apache (mod_proxy)

```apache
<VirtualHost *:443>
    ServerName www.roadrunningreview.com

    # Deshabilitar caché para /social
    <Location /social>
        ModPagespeed off
        Header set Cache-Control "no-cache, no-store, must-revalidate"
        Header set Pragma "no-cache"
        Header set Expires 0
    </Location>

    # Proxy API → uvicorn
    ProxyPass /social/api http://127.0.0.1:8000/api
    ProxyPassReverse /social/api http://127.0.0.1:8000/api

    # Proxy stories images
    ProxyPass /social/stories_images http://127.0.0.1:8000/stories_images
    ProxyPassReverse /social/stories_images http://127.0.0.1:8000/stories_images

    # Auth callbacks OAuth (Threads, TikTok…)
    ProxyPass /auth http://127.0.0.1:8000/auth
    ProxyPassReverse /auth http://127.0.0.1:8000/auth

    # Frontend estático (build React)
    Alias /social /home/pirineos/social-intelligence/static
    <Directory /home/pirineos/social-intelligence/static>
        Options -Indexes
        AllowOverride All
        Require all granted
    </Directory>
</VirtualHost>
```

---

## Medios configurados

| slug | Nombre | URL web | Sitemap | Activo | Marcas |
|------|--------|---------|---------|--------|--------|
| `roadrunningreview` | ROADRUNNINGReview | https://www.roadrunningreview.com | `SiteMapTrailES0.xml` | ✅ | 187 |
| `trailrunningreview` | TRAILRUNNINGReview | https://www.trailrunningreview.com | `SiteMapTrailES1.xml` | ✅ | 258 |

**Business Portfolio:** Horizonte Norte SL (compartido por ambos medios)

### Credenciales — ROADRUNNINGReview

| Parámetro | Valor |
|-----------|-------|
| DB usuario servidor | `pirineos` |
| YouTube Canal ID | `UCAc6Iskqwdoc05frp6eD0QA` |
| GA4 Property ID | `373727530` |
| Instagram Account ID | `17841402263658371` |
| Facebook Page ID | `1668731220040575` |
| Threads User ID | `26958667087052227` |
| Threads App ID | `1389357836567753` |
| **Google Ads customer_id** | `4405944785` (cuenta "Mal de Altura") |
| **Google Ads developer_token** | cifrado en DB `canal=google_ads`, `clave=developer_token` |
| **Google Ads OAuth** | `access_token` + `refresh_token` en DB `canal=google_ads` |

### Credenciales — TRAILRUNNINGReview

| Parámetro | Valor |
|-----------|-------|
| YouTube Canal ID | `UC9wFjjB6qX_5VUaBGFssx8A` |
| GA4 Property ID | `372768532` |
| Instagram Account ID | `17841400253330854` |
| Facebook Page ID | `139115256153733` |
| Threads User ID | `27386364534299660` |
| Threads App ID | `1389357836567753` (mismo que RRR) |

---

## Estado actual por canal — roadrunningreview

*Datos a 2026-04-09*

| Canal | Pubs | Reach total |
|-------|-----:|------------:|
| instagram_post | 503 | ~16.9M |
| instagram_story | ~10 | — |
| facebook | 503 | — |
| web | ~293 | — |
| youtube | ~49 | — |
| youtube_short | ~30 | — |
| threads | ~138 | — |
| **TOTAL** | **~1.537** | **~30.1M** |

**Top 10 marcas por reach acumulado** *(datos 2026-04-01)*:

| # | Marca | Pubs | Reach |
|---|-------|-----:|------:|
| 1 | Adidas | 193 | 3.893.318 |
| 2 | ASICS | 153 | 2.374.040 |
| 3 | On | 91 | 1.855.878 |
| 4 | Mizuno | 68 | 987.817 |
| 5 | Nike | 66 | 921.465 |
| 6 | Gore Running Wear | 37 | 780.162 |
| 7 | Brooks | 85 | 711.015 |
| 8 | Hoka | 80 | 601.892 |
| 9 | Coros | 16 | 531.970 |
| 10 | Kiprun | 29 | 431.834 |

---

## Estado actual por canal — trailrunningreview

*Datos a 2026-04-15*

| Canal | Pubs | Reach total | Estado |
|-------|-----:|------------:|--------|
| web | 192 | — | ✅ configurado |
| instagram_post | 2.000 | 50.8M | ✅ configurado |
| facebook | 500 | 4.1M | ✅ configurado |
| youtube | 90 | 417K | ✅ 45 vídeos detectados, OAuth funcionando |
| youtube_short | 3 | 6.9K | ✅ configurado |
| threads | 4 | 3.6K | ✅ configurado |
| instagram_story | 0 | — | ✅ captura automática activa |
| tiktok | — | — | ⚠ tokens configurados, rate limit temporal — pendiente backfill 2026-01-01 |
| x | — | — | ⚠ agente listo, pendiente plan de pago ($100/mes) |
| **TOTAL** | **~2.789** | **~55.4M** | |

**Marcas importadas:** 258 marcas con emails de contacto

---

## Estado global del sistema

*Datos a 2026-04-15*

| Medio | Pubs | Reach |
|-------|-----:|------:|
| ROADRUNNINGReview | ~1.537 | ~30.1M |
| TRAILRUNNINGReview | 2.789 | 55.4M |
| **TOTAL SISTEMA** | **~4.326** | **~85.5M** |

**Jobs activos:** 28 (14 por medio)

---

## APIs de Ads — estado promoción pagada

### Canales — estado por agente

| Canal | Agente | roadrunningreview | trailrunningreview |
|-------|--------|:-----------------:|:-----------------:|
| Web (GA4) | `web_agent.py` | ✅ | ✅ |
| YouTube | `youtube_agent.py` | ✅ | ✅ |
| YouTube Shorts | `youtube_shorts_agent.py` | ✅ | ✅ |
| Instagram posts/reels | `instagram_agent.py` | ✅ | ✅ |
| Instagram Stories | `instagram_stories_agent.py` | ✅ | ✅ |
| Facebook | `facebook_agent.py` | ✅ | ✅ |
| Threads | `threads_agent.py` | ✅ | ✅ |
| TikTok | `tiktok_agent.py` | ✅ | ⚠ rate limit temporal |
| **X (Twitter)** | `x_agent.py` | ⚠ pendiente billing | ⚠ pendiente billing |

> **X (Twitter):** Agente implementado (`agents/x_agent.py`) y tokens configurados en DB para ambos medios. Bloqueado por plan de pago — X API Basic = $100/mes. Reactivar cuando se decida contratar el plan.

---

## APIs de Ads — estado promoción pagada

| Canal | Estado | Cuenta | Datos |
|-------|--------|--------|-------|
| **Google Ads** | ✅ conectado | Mal de Altura (4405944785) | 7 vídeos con `reach_pagado` + `inversion_pagada` |
| **Meta Ads** | ⏳ pendiente | — | Requiere reactivar cuenta publicitaria + permiso `ads_read` |

**Google Ads — configuración:**
- `developer_token`: cifrado en DB (`canal=google_ads`, `clave=developer_token`)
- `customer_id`: `4405944785`
- `access_token` + `refresh_token`: OAuth en DB (`canal=google_ads`)
- Sync automático: **martes 03:00 UTC**
- Histórico: desde `2026-01-01`
- Script manual: `python scripts/sync_paid_metrics.py --slug roadrunningreview --canal google --fecha-desde 2026-01-01`

---

## Arquitectura de ficheros

### Backend

| Fichero | Descripción | Estado |
|---------|-------------|--------|
| `main.py` | Punto de entrada FastAPI; inicializa DB, APScheduler, routers, sirve `stories_images/`; callbacks OAuth `/auth/threads/callback` + `/api/auth/tiktok/callback` | ✅ |
| `models/database.py` | Esquema MySQL completo: todos los modelos y Enums | ✅ |
| `core/settings.py` | Configuración global via Pydantic BaseSettings desde `.env` | ✅ |
| `core/crypto.py` | Cifrado/descifrado Fernet para tokens API | ✅ |
| `core/brand_id_agent.py` | Identificación marca/agencia por texto con aliases; fix substring→prefix activo | ✅ |
| `core/orchestrator.py` | Coordinador de agentes, checkpoints, `LogEjecucion`, APScheduler; `run_agent()` + `run_stories()` | ✅ |
| `core/notifier.py` | Digest email diario por marca/agencia via SMTP | ✅ |
| `api/auth.py` | JWT login panel; `application/x-www-form-urlencoded` (no JSON) | ✅ |
| `api/routes/medios.py` | CRUD medios, marcas, agencias, tokens cifrados | ✅ |
| `api/routes/publicaciones.py` | Listado filtrable, bulk actions, analytics (resumen/marca/comparar/semanal) | ✅ |
| `agents/web_agent.py` | Sitemap XML → GA4 Data API; extrae `datePublished` del HTML; histórico semanal ISO | ✅ |
| `agents/youtube_agent.py` | YouTube Data API v3 + Analytics API; OAuth2 con refresh automático | ✅ |
| `agents/youtube_shorts_agent.py` | YouTube Shorts: Data API v3 + Analytics; job 48h + semanal | ✅ |
| `agents/instagram_agent.py` | Instagram Graph API; posts + reels; métricas separadas por tipo | ✅ |
| `agents/instagram_stories_agent.py` | Captura Stories + imagen; `thumbnail_url` para VIDEO; retry si `captura_url=NULL` | ✅ |
| `agents/facebook_agent.py` | Graph API v25.0; page token OAuth permanente; `post_impressions_unique`; skip >24m | ✅ |
| `agents/threads_agent.py` | Threads API; App ID 1389357836567753; paginación hasta checkpoint | ✅ |
| `agents/meta_ads_agent.py` | Meta Marketing API v25; fallo silencioso si falta permiso `ads_read` | ✅ |
| `agents/google_ads_agent.py` | Google Ads API v20; GAQL dual (FROM asset + FROM ad_group_ad); VIDEO_RESPONSIVE_AD; rango fechas explícito; refresh automático access_token | ✅ |
| `agents/x_agent.py` | Twitter API v2 Bearer Token; detect_new + update_metrics batch 100 IDs + snapshot_weekly; backoff exponencial en 429; user_id cacheado en DB | ✅ |
| `utils/semanas.py` | Helpers ISO week: `get_semana_iso`, `get_rango_semana`, `semanas_entre` | ✅ |

### Frontend — `frontend/src/App.jsx`

| Vista | Descripción |
|-------|-------------|
| **Login** | JWT; `application/x-www-form-urlencoded`; token en localStorage; redirección automática si ya autenticado |
| **Panel medios** | CRUD medios, marcas, agencias; gestión tokens cifrados por canal |
| **Publicaciones** | Tabla filtrable por canal/marca/estado/fecha; selección múltiple Shift+click; bulk-refresh, asignar marca, marcar revisado; badge `estado_marca`; badge **Patrocinado** (naranja) si `inversion_pagada > 0`; columnas `reach_pagado`/`inversion_pagada` de solo lectura; totales en cabecera (reach orgánico, reach pagado, inversión total) |
| **Analytics — Resumen** | KPIs período + gráfica mensual reach por canal + top 10 marcas + gráfica semanal ISO (fallback reach acumulado si `reach_diff=0`) |
| **Analytics — Dashboard marca** | KPIs por marca (incl. inversión total + reach pagado) + reach por canal con barras apiladas orgánico/pagado (naranja) + evolución mensual + últimas 5 pubs + gráfica semanal |
| **Analytics — Comparar marcas** | Comparativa lado a lado de dos marcas |
| **Analytics — Por canal** | Filtro por canal con gráfica semanal específica |

*Nota: `storyImgUrl()` usa ruta relativa HTTPS en producción para imágenes Stories.*

### Scripts de utilidad — `scripts/`

| Script | Propósito | Comando | Estado |
|--------|-----------|---------|--------|
| `authorize_meta.py` | Tokens Instagram + Facebook via Graph API Explorer | `python scripts/authorize_meta.py {slug}` | ✅ |
| `authorize_facebook.py` | OAuth flow completo → page token permanente | `python scripts/authorize_facebook.py --slug {slug}` | ✅ |
| `authorize_youtube.py` | OAuth2 YouTube → refresh token | `python scripts/authorize_youtube.py --slug {slug}` | ✅ |
| `authorize_threads.py` | OAuth Threads → long-lived token 60 días; redirect URI HTTPS servidor prod | `python scripts/authorize_threads.py --slug {slug}` | ✅ |
| `export_youtube_tokens.py` | Exportar tokens YouTube para migrar entre entornos | `python scripts/export_youtube_tokens.py` | ✅ |
| `import_marcas.py` | Importación masiva catálogo de marcas | `python scripts/import_marcas.py` | ✅ |
| `backfill_historico.py` | Snapshots semanales históricos 2026 web + RRSS | `python scripts/backfill_historico.py --slug {slug}` | ✅ |
| `backfill_reels.py` | Backfill Reels Instagram 2026 con paginación completa | `python scripts/backfill_reels.py --slug {slug} [--dry-run]` | ✅ |
| `backfill_shorts_historico.py` | Histórico completo YouTube Shorts | `python scripts/backfill_shorts_historico.py --slug {slug}` | ✅ |
| `backfill_texto.py` | Descargar textos de publicaciones (todos los canales) | `python scripts/backfill_texto.py --slug {slug}` | ✅ |
| `fix_facebook_reach.py` | Rellena reach 500 pubs Facebook con `update_metrics()` v25.0 | `python scripts/fix_facebook_reach.py --slug {slug}` | ✅ |
| `fix_fechas_publicacion.py` | Corrige timestamps Meta (Python 3.10 compat) | `python scripts/fix_fechas_publicacion.py --slug {slug}` | ✅ |
| `fix_web_fechas.py` | Corrige `datePublished` artículos web desde HTML | `python scripts/fix_web_fechas.py --slug {slug}` | ✅ |
| `fix_story_images.py` | MP4 → thumbnail para Stories vídeo | `python scripts/fix_story_images.py --slug {slug}` | ✅ |
| `fix_shorts_metrics.py` | Rellena métricas Shorts sin reach | `python scripts/fix_shorts_metrics.py --slug {slug}` | ✅ |
| `fix_2026.py` | Diagnostica/corrige pubs 2026 no detectadas por checkpoint | `python scripts/fix_2026.py --slug {slug}` | ✅ |
| `migrate_add_sin_datos.py` | ALTER TABLE MySQL: añade `sin_datos` al ENUM | `python scripts/migrate_add_sin_datos.py` *(1 vez)* | ✅ |
| `migrate_add_youtube_short.py` | Migración DB: añade canal `youtube_short` | `python scripts/migrate_add_youtube_short.py` *(1 vez)* | ✅ |
| `migrate_add_texto.py` | Migración DB: añade campo `texto` a publicaciones | `python scripts/migrate_add_texto.py` *(1 vez)* | ✅ |
| `sync_paid_metrics.py` | Sync métricas pagadas desde Meta Ads y/o Google Ads | `python scripts/sync_paid_metrics.py --slug {slug} --canal [meta\|google\|all] --fecha-desde YYYY-MM-DD` | ✅ |
| `authorize_google_ads.py` | OAuth flow Google Ads → `access_token`+`refresh_token` en DB; HTTPServer en :8001 | `python scripts/authorize_google_ads.py --slug {slug}` | ✅ |
| `validate_all.py` | Suite validación completa: tokens, DB, API, métricas | `python scripts/validate_all.py --slug {slug}` | ✅ |
| `validate_semanal.py` | Valida histórico semanal | `python scripts/validate_semanal.py --slug {slug}` | ✅ |
| `reset_checkpoint.py` | Resetea checkpoint web agent a fecha concreta | `python scripts/reset_checkpoint.py --slug {slug} --fecha 2026-01-01` | ⚠ usar con cuidado |
| `authorize_tiktok.py` | OAuth TikTok Open Platform con soporte `--slug` | `python scripts/authorize_tiktok.py --slug {slug}` | ✅ |
| `backfill_historico.py` | Snapshots semanales históricos; soporta `--canal x` y `--canal tiktok` | `python scripts/backfill_historico.py --slug {slug} --canal x --anio 2026` | ✅ |

---

## Fixes críticos aplicados

| Fix | Descripción |
|-----|-------------|
| **Google Ads GAQL query** | Campo `video_ad.in_stream.video.resource_name` inexistente para `VIDEO_RESPONSIVE_AD` → query dual: `FROM asset` (asset_rn→yt_id) + `FROM ad_group_ad` con `video_responsive_ad.videos` |
| **Google Ads GAQL date range** | `LAST_365_DAYS` y `THIS_YEAR` inválidos en GAQL v20 → rango explícito `'{year}-01-01' AND '{year}-12-31'` calculado dinámicamente |
| **Google Ads GAQL WHERE** | `metrics.impressions > 0` inválido en WHERE de GAQL → filtrado en Python post-query |
| **authorize_google_ads.py URI** | Redirect URI OOB (`urn:ietf:wg:oauth:2.0:oob`) deprecada → `HTTPServer` local en `:8001` |
| **Threads OAuth redirect URI** | Threads rechaza callbacks HTTP → cambiado a `https://www.roadrunningreview.com/auth/threads/callback`; endpoint `/auth/threads/callback` añadido a `main.py`; script muestra código en browser y pide pegarlo en terminal |
| **Threads primer run sin checkpoint** | Sin checkpoint el agente pagina todos los posts históricos (~1000+) → insertar `LogEjecucion` fake con fecha 30 días atrás antes del primer run |
| **TRR sitemap incorrecto** | `SiteMapTrailES0.xml` solo tiene páginas de marcas sin `<lastmod>` → sitemap correcto es `SiteMapTrailES1.xml` |
| **authorize_*.py --slug** | Scripts `authorize_youtube.py`, `authorize_threads.py`, `authorize_facebook.py` ahora aceptan `--slug` como parámetro obligatorio (antes hardcodeado para roadrunningreview) |
| `_parse_ts()` | Timestamps Meta sin dos puntos en el offset de zona horaria (Python 3.10 compat) |
| Stories inserción | `detect_and_update()` inserta Stories nuevas además de actualizar las existentes |
| Stories vídeo | Usa `thumbnail_url` en lugar de `media_url` para Stories de tipo VIDEO |
| Stories imagen retry | Reintenta descarga de imagen cada hora si `captura_url=NULL` |
| YouTube Shorts duplicados | Verifica existencia por `canal='youtube_short'` antes de insertar |
| Web fechas | Extrae `datePublished` del HTML del artículo en lugar de `lastmod` del sitemap |
| Facebook token | Page token OAuth permanente via `_resolve_page_token`; `post_impressions_unique` v25.0 |
| Login frontend | Usa `application/x-www-form-urlencoded` en lugar de JSON |
| API base URL | `API_BASE=/social/api` en producción, `/api` en desarrollo |
| Stories URL imágenes | `storyImgUrl()` usa ruta relativa HTTPS en producción |
| Caché Apache | `ModPagespeed off` + `no-cache` headers en `/social` |
| Texto publicaciones | Campo `texto` añadido a DB; backfill ejecutado para todos los canales |

---

## Triggers automáticos (APScheduler) — 26 jobs activos (13 por medio)

| Job | Trigger | Descripción |
|-----|---------|-------------|
| `{slug}_hourly` | Cron **:10 cada hora** | Detección nuevas pubs + actualiza métricas pendientes (todos los canales) |
| `{slug}_daily` | Cron **07:00 UTC** diario | Resumen diario + notificaciones email |
| `{slug}_stories_hourly` | Cron **:00 cada hora** | Captura Stories Instagram <24h |
| `{slug}_stories_final` | Cron **:50-:59 cada hora** | Captura final Stories antes de expirar |
| `{slug}_youtube_shorts_update` | **Cada 48h** | Actualiza métricas YouTube Shorts recientes |
| `{slug}_weekly_web_ga4` | Cron **lunes 00:00 UTC** | Snapshot semanal ISO GA4 web |
| `{slug}_weekly_youtube` | Cron **lunes 00:30 UTC** | Snapshot semanal YouTube Analytics |
| `{slug}_weekly_youtube_shorts` | Cron **lunes 00:45 UTC** | Snapshot semanal YouTube Shorts Analytics |
| `{slug}_weekly_instagram` | Cron **lunes 01:00 UTC** | Snapshot semanal Instagram posts/reels/stories |
| `{slug}_weekly_facebook` | Cron **lunes 01:30 UTC** | Snapshot semanal Facebook |
| `{slug}_weekly_threads` | Cron **lunes 02:00 UTC** | Snapshot semanal Threads |
| `{slug}_weekly_tiktok` | Cron **lunes 02:30 UTC** | Snapshot semanal TikTok |
| `{slug}_weekly_x` | Cron **lunes 02:45 UTC** | Snapshot semanal X (Twitter) |
| `{slug}_weekly_paid_metrics` | Cron **martes 03:00 UTC** | Sync métricas pagadas (Google Ads + Meta Ads) |

---

## Guía para añadir un nuevo medio

1. **Crear medio en panel web** (o DB directamente): `slug`, `nombre`, `url_web`, `rss_url` (sitemap correcto con `<lastmod>`)
2. **GA4**: añadir `roadrunning-ga4@...` como Lector en la propiedad GA4; configurar `ga4_property_id` en `config_medio`
3. **YouTube**: `python scripts/authorize_youtube.py --slug {nuevo_slug}`
   - Copiar `client_id`/`client_secret` de otro medio si se usa la misma Google Cloud app
4. **Instagram/Facebook**: añadir cuenta al Business Portfolio Horizonte Norte SL → asignar usuario `socialintelligencebot` → regenerar System User Token → obtener `instagram_account_id` y `page_id` via Graph API Explorer (`/me/accounts`, `?fields=instagram_business_account`)
5. **Threads**: añadir cuenta como evaluador en Meta Developers → Threads API → aceptar invitación desde **app móvil de Threads** (no email) → `python scripts/authorize_threads.py --slug {nuevo_slug}`; insertar `LogEjecucion` fake 30 días atrás para evitar paginar histórico completo en primer run
6. **Importar marcas**: CSV con columnas `v_idmarca;v_descmarca;v_emails` → script de importación `/tmp/import_{slug}.py`
7. **Reiniciar servicio** para que el scheduler registre los jobs del nuevo medio: `systemctl restart social-intelligence`
8. **Probar cada agente**: `run_agent(db, medio, canal, 'manual')` para `web`, `instagram`, `facebook`, `youtube`, `threads`; `run_stories(db, medio)` para stories

---

## Base de datos — volumen actual

*Datos a 2026-04-15*

| Tabla | Filas | Descripción |
|-------|------:|-------------|
| `publicaciones` | ~4.326 | Publicaciones detectadas con métricas actuales (2 medios) |
| `historial_metricas` | ~2.448+ | Snapshots semanales ISO por publicación (reach/likes/shares/diff) |
| `marcas` | 445 | Catálogo de marcas (187 RRR + 258 TRR) |
| `log_ejecuciones` | 30+ | Log de cada ejecución de agente (agente, tipo, estado, conteos) |
| `tokens_canal` | 30+ | Tokens API cifrados por medio+canal+clave |
| `medios` | 2 | roadrunningreview + trailrunningreview |
| `agencias` | 0 | Catálogo de agencias *(vacío — pendiente importar)* |

---

## Fases de desarrollo

### Completadas

| Versión | Contenido |
|---------|-----------|
| v0.1 | Estructura base, modelos DB, auth JWT, CRUD panel |
| v0.2 | Web Agent + YouTube Agent + Brand ID Agent + Orquestador |
| v0.3 | Instagram Agent (posts + stories + reels) + Facebook Agent |
| v0.4 | Frontend publicaciones selección múltiple + Analytics Chart.js |
| v0.5 | Histórico semanal métricas + backfill GA4 |
| v0.6 | Fix Brand ID Agent substring→prefix · fix timezone naive/aware · Facebook v21→v25 + `_resolve_page_token` · `estado_marca` · `sin_datos` enum · `authorize_facebook.py` · `validate_all.py` |
| v0.7 | YouTube Shorts Agent · Threads Agent · 10 jobs APScheduler · Apache mod_proxy producción · fix Stories inserción/vídeo/retry · fix timestamps Meta · campo `texto` en DB · fix web fechas datePublished · fix Shorts duplicados |
| v0.8 | Meta Ads Agent + Google Ads Agent · columnas `reach_pagado`/`inversion_pagada` en DB · badge Patrocinado panel · barras apiladas orgánico+pagado en Analytics · `sync_paid_metrics.py --fecha-desde` · `authorize_google_ads.py` · 11 jobs APScheduler · fix GAQL VIDEO_RESPONSIVE_AD + rango fechas + WHERE metrics |
| **v0.9** *(actual)* | Segundo medio TRAILRUNNINGReview: 2.789 pubs/55.4M reach · 258 marcas importadas · todos los canales activos (Instagram/Facebook/YouTube/Threads/TikTok/Web/Stories) · TikTok Agent: OAuth 2.0 access_token + refresh automático · X (Twitter) Agent: `x_agent.py` Bear Token v2 + `snapshot_weekly` · tokens X configurados en DB ambos medios · 28 jobs scheduler (14 × 2 medios, +X weekly lunes 02:45) · fix Threads OAuth HTTPS redirect URI · fix sitemap TRR (`SiteMapTrailES1.xml`) · `authorize_*.py` acepta `--slug` · endpoint `/auth/threads/callback` en main.py |

### Pendientes

**Prioridad Alta**
- Generador PDF por marca/año (`reportlab` o `weasyprint`) — portada, tabla pubs, totales canal, capturas
- Renovación automática page token Facebook (~60 días) + alerta 7 días antes
- Meta Ads: reactivar cuenta publicitaria + añadir permiso `ads_read` en token sistema
- TikTok trailrunningreview: ejecutar backfill desde 2026-01-01 cuando expire rate limit

**Prioridad Media**
- Notificación diaria email a cada marca/agencia via SMTP
- X (Twitter): activar plan Basic ($100/mes) cuando se decida — agente ya implementado
- Tercer medio: TREKKINGReview (aparece en Business Portfolio Horizonte Norte SL)

**Fase 5 — Avanzado**
- YouTube Scraper canales ajenos (reach vídeos de marcas externas)
- Brand Vision Agent: identificación marca por imagen con Claude API Vision

---

## Guía de despliegue

### Flujo de trabajo

```
Windows (Claude Code) → git push → Servidor (git pull + npm run build + systemctl restart)
```

### Comandos de gestión en servidor

```bash
# Estado del servicio
systemctl status social-intelligence

# Logs en tiempo real
journalctl -u social-intelligence -f

# Reiniciar servicio
systemctl restart social-intelligence

# Actualizar código desde git
cd /home/pirineos/social-intelligence
git pull origin main

# Actualizar + rebuild + reiniciar (secuencia completa)
cd /home/pirineos/social-intelligence && git pull origin main && \
  cd frontend && npm run build && cd .. && \
  systemctl restart social-intelligence

# Ver logs de aplicación
journalctl -u social-intelligence --since "1 hour ago"
journalctl -u social-intelligence -n 100
```

---

## Problemas conocidos

### 🔴 PENDIENTE

| Problema | Descripción | Acción |
|----------|-------------|--------|
| Facebook page token | Caduca en ~60 días — pendiente renovación automática | Implementar alerta + renovación |
| TRR Threads token | Long-lived token expira en 60 días — renovar con `authorize_threads.py --slug trailrunningreview` | Recordatorio mensual |

### 🟡 EN SEGUIMIENTO

| Área | Descripción |
|------|-------------|
| Instagram errores 400 | Posts antiguos >2 años devuelven 400 — normal, Meta no expone insights históricos | Esperado |
| YouTube reach | YouTube Analytics no expone impresiones por vídeo via API — `views` como proxy | Limitación API |
| Brand ID sin marca | ~97 pubs RRR sin marca asignada — revisar aliases Bikkoa, U-Tech y otros | Manual |

### 🔵 LIMITACIONES CONOCIDAS DE APIs

| API | Limitación |
|-----|-----------|
| Facebook v25.0 | Solo `post_impressions_unique` funciona; `reach`, `impressions`, `post_engaged_users` devuelven 400 |
| Facebook | ~10% posts con timeout esporádico — se reintenta en ciclo siguiente |
| Facebook | Page token expira en ~60 días — pendiente renovación automática |
| YouTube Analytics | `impressions` no soportado por vídeo — se usa `views` como proxy |
| Instagram Reels | API devuelve `media_type=VIDEO` para vídeos y reels — se detectan por permalink `/reel/` |
| Instagram | Posts >2 años devuelven error 400 en insights — comportamiento esperado de Meta |
| Meta RRSS | Histórico semanal solo desde semana actual hacia adelante — no hay backfill de semanas pasadas |
| Threads | Primer run sin checkpoint pagina histórico completo (~1000+ posts) — insertar LogEjecucion fake 30 días antes |
| TikTok | Free tier: rate limit 429 esporádico — esperar y reintentar; TRR pendiente backfill |
| X (Twitter) | API Basic ($100/mes) requerida para `impression_count`; Free tier puede devolver 402 CreditsDepleted |

### ⚪ DEUDA TÉCNICA

| Descripción | Prioridad |
|-------------|-----------|
| Comparaciones `datetime` naive/aware dispersas — centralizar en `utils/dates.py` | Baja |
| `validate_all.py` V11-V13 requieren uvicorn activo para JWT | Baja |
| `authorize_meta.py` usa `GRAPH = v21.0` — actualizar a v25.0 | Baja |
| Facebook page token expira ~60 días — implementar renovación automática o alerta 7 días | Media |

---

## Próximas prioridades

| # | Tarea | Prioridad | Estado |
|---|-------|-----------|--------|
| 1 | Generador PDF informes por marca/año | 🔴 Alta | ⬜ siguiente |
| 2 | Renovación automática page token Facebook | 🔴 Alta | ⬜ siguiente |
| 3 | Meta Ads: reactivar cuenta + permiso `ads_read` | 🔴 Alta | ⬜ pendiente externo |
| 4 | TikTok TRR: backfill 2026-01-01 (tras expirar rate limit) | 🔴 Alta | ⬜ siguiente |
| 5 | Notificación diaria email a cada marca | 🟡 Media | ⬜ siguiente |
| 6 | X (Twitter): activar plan Basic ($100/mes) | 🟡 Media | ⬜ bloqueado billing |
| 7 | Tercer medio TREKKINGReview | 🟡 Media | ⬜ siguiente |
| 8 | Brand Vision Agent — identificación marca por imagen con Claude API | 🔵 Baja | ⬜ siguiente |
