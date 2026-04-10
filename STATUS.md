# Social Intelligence System — STATUS

> Última actualización: 2026-04-09 — datos reales de producción

---

## Descripción del proyecto

Sistema multi-medio de recogida automática de métricas de publicaciones en redes sociales
y web. Permite a ROADRUNNINGReview (y otros medios) agregar el reach, likes, shares y
comentarios de todas sus publicaciones por marca, canal y período, generando informes de
campaña y notificaciones automáticas a cada marca cliente.

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

### Credenciales y IDs de producción

| Parámetro | Valor |
|-----------|-------|
| DB usuario servidor | `pirineos` |
| YouTube canal ID | `UCAc6Iskqwdoc05frp6eD0QA` |
| Threads App ID | `1389357836567753` |
| Threads User ID | `26958667087052227` |
| Facebook Page ID | `1668731220040575` |
| Instagram Account ID | `17841402263658371` |
| GA4 Property ID | `373727530` |

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

    # Frontend estático (build React)
    Alias /social /home/pirineos/social-intelligence/frontend/dist
    <Directory /home/pirineos/social-intelligence/frontend/dist>
        Options -Indexes
        AllowOverride All
        Require all granted
    </Directory>
</VirtualHost>
```

---

## Medios configurados

| slug | Nombre | URL web | RSS/Sitemap | Activo |
|------|--------|---------|-------------|--------|
| `roadrunningreview` | ROADRUNNINGReview | https://www.roadrunningreview.com | SiteMapTrailES0.xml | ✅ |

---

## Estado actual por canal — roadrunningreview

*Datos a 2026-04-09*

| Canal | Pubs | Reach total | Likes | Shares | Actualizadas | Revisión | Pendiente | Errores |
|-------|-----:|------------:|------:|-------:|-------------:|---------:|----------:|--------:|
| instagram_post | 503 | ~16.9M | — | — | — | — | — | — |
| instagram_story | ~10 | — | — | — | — | — | — | — |
| facebook | 503 | — | — | — | — | — | — | — |
| web | ~293 | — | — | — | — | — | — | — |
| youtube | ~49 | — | — | — | — | — | — | — |
| youtube_short | ~30 | — | — | — | — | — | — | — |
| threads | ~138 | — | — | — | — | — | — | — |
| **TOTAL** | **~1.537** | **~30.1M** | | | | | | |

*En revisión: ~132 publicaciones*

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

**Estado de marcas:**
- Total marcas en catálogo: **187**
- `estimated` (asignadas automáticamente): **1.065**
- `to_review` (pendientes validación): **269** → reducido a **~132**
- Sin marca asignada: **97** publicaciones (7,3%)

**Histórico semanal:**
- Semanas con snapshot: **13** (2026-W02 → 2026-W14)
- Total snapshots en `historial_metricas`: **630**

---

## Arquitectura de ficheros

### Backend

| Fichero | Descripción | Estado |
|---------|-------------|--------|
| `main.py` | Punto de entrada FastAPI; inicializa DB, APScheduler, routers, sirve `stories_images/` | ✅ |
| `models/database.py` | Esquema MySQL completo: todos los modelos y Enums | ✅ |
| `core/settings.py` | Configuración global via Pydantic BaseSettings desde `.env` | ✅ |
| `core/crypto.py` | Cifrado/descifrado Fernet para tokens API | ✅ |
| `core/brand_id_agent.py` | Identificación marca/agencia por texto con aliases; fix substring→prefix activo | ✅ |
| `core/orchestrator.py` | Coordinador de agentes, checkpoints, `LogEjecucion`, APScheduler | ✅ |
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
| `agents/threads_agent.py` | Threads API; App ID 1389357836567753; User ID 26958667087052227 | ✅ |
| `utils/semanas.py` | Helpers ISO week: `get_semana_iso`, `get_rango_semana`, `semanas_entre` | ✅ |

### Frontend — `frontend/src/App.jsx`

| Vista | Descripción |
|-------|-------------|
| **Login** | JWT; `application/x-www-form-urlencoded`; token en localStorage; redirección automática si ya autenticado |
| **Panel medios** | CRUD medios, marcas, agencias; gestión tokens cifrados por canal |
| **Publicaciones** | Tabla filtrable por canal/marca/estado/fecha; selección múltiple Shift+click; bulk-refresh, asignar marca, marcar revisado; badge `estado_marca` |
| **Analytics — Resumen** | KPIs período + gráfica mensual reach por canal + top 10 marcas + gráfica semanal ISO (fallback reach acumulado si `reach_diff=0`) |
| **Analytics — Dashboard marca** | KPIs por marca + reach por canal (bar) + evolución mensual + últimas 5 pubs + gráfica semanal |
| **Analytics — Comparar marcas** | Comparativa lado a lado de dos marcas |
| **Analytics — Por canal** | Filtro por canal con gráfica semanal específica |

*Nota: `storyImgUrl()` usa ruta relativa HTTPS en producción para imágenes Stories.*

### Scripts de utilidad — `scripts/`

| Script | Propósito | Comando | Estado |
|--------|-----------|---------|--------|
| `authorize_meta.py` | Tokens Instagram + Facebook via Graph API Explorer | `python scripts/authorize_meta.py roadrunningreview` | ✅ |
| `authorize_facebook.py` | OAuth flow completo → page token permanente | `python scripts/authorize_facebook.py --slug roadrunningreview` | ✅ |
| `authorize_youtube.py` | OAuth2 YouTube → refresh token | `python scripts/authorize_youtube.py` | ✅ |
| `export_youtube_tokens.py` | Exportar tokens YouTube para migrar entre entornos | `python scripts/export_youtube_tokens.py` | 🆕 |
| `import_marcas.py` | Importación masiva catálogo de marcas (187) | `python scripts/import_marcas.py` | ✅ |
| `backfill_historico.py` | Snapshots semanales históricos 2026 web + RRSS | `python scripts/backfill_historico.py --slug roadrunningreview` | ✅ |
| `backfill_reels.py` | Backfill Reels Instagram 2026 con paginación completa | `python scripts/backfill_reels.py --slug roadrunningreview [--dry-run]` | ✅ |
| `backfill_shorts_historico.py` | Histórico completo YouTube Shorts | `python scripts/backfill_shorts_historico.py --slug roadrunningreview` | 🆕 |
| `backfill_texto.py` | Descargar textos de publicaciones (todos los canales) | `python scripts/backfill_texto.py --slug roadrunningreview` | 🆕 |
| `fix_facebook_reach.py` | Rellena reach 500 pubs Facebook con `update_metrics()` v25.0 | `python scripts/fix_facebook_reach.py --slug roadrunningreview` | ✅ |
| `fix_fechas_publicacion.py` | Corrige timestamps Meta (Python 3.10 compat) | `python scripts/fix_fechas_publicacion.py --slug roadrunningreview` | 🆕 |
| `fix_web_fechas.py` | Corrige `datePublished` artículos web desde HTML | `python scripts/fix_web_fechas.py --slug roadrunningreview` | 🆕 |
| `fix_story_images.py` | MP4 → thumbnail para Stories vídeo | `python scripts/fix_story_images.py --slug roadrunningreview` | 🆕 |
| `fix_shorts_metrics.py` | Rellena métricas Shorts sin reach | `python scripts/fix_shorts_metrics.py --slug roadrunningreview` | 🆕 |
| `fix_2026.py` | Diagnostica/corrige pubs 2026 no detectadas por checkpoint | `python scripts/fix_2026.py --slug roadrunningreview` | ✅ |
| `migrate_add_sin_datos.py` | ALTER TABLE MySQL: añade `sin_datos` al ENUM | `python scripts/migrate_add_sin_datos.py` *(1 vez)* | ✅ |
| `migrate_add_youtube_short.py` | Migración DB: añade canal `youtube_short` | `python scripts/migrate_add_youtube_short.py` *(1 vez)* | 🆕 |
| `migrate_add_texto.py` | Migración DB: añade campo `texto` a publicaciones | `python scripts/migrate_add_texto.py` *(1 vez)* | 🆕 |
| `validate_all.py` | Suite validación completa: tokens, DB, API, métricas | `python scripts/validate_all.py --slug roadrunningreview` | ✅ |
| `validate_semanal.py` | Valida histórico semanal | `python scripts/validate_semanal.py --slug roadrunningreview` | 🆕 |
| `check_instagram_errors.py` | Revisar errores Instagram en DB | `python scripts/check_instagram_errors.py --slug roadrunningreview` | 🆕 |
| `test_facebook_reach.py` | Diagnóstico verbose reach Facebook + `/me/permissions` | `python scripts/test_facebook_reach.py --slug roadrunningreview [--post-id ID]` | ✅ |
| `test_fb_metrics_v25.py` | Prueba sistemática métricas/endpoints v25.0 | `python scripts/test_fb_metrics_v25.py --slug roadrunningreview` | ✅ |
| `test_ga4_semanal.py` | Verifica GA4 por semana ISO para web | `python scripts/test_ga4_semanal.py --slug roadrunningreview` | ✅ |
| `diagnose_web_agent.py` | Diagnóstico web agent: sitemap, GA4, checkpoints, DB | `python scripts/diagnose_web_agent.py --slug roadrunningreview` | ✅ |
| `reset_checkpoint.py` | Resetea checkpoint web agent a fecha concreta | `python scripts/reset_checkpoint.py --slug roadrunningreview --fecha 2026-01-01` | ⚠ usar con cuidado |

---

## Fixes críticos aplicados

| Fix | Descripción |
|-----|-------------|
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

## Triggers automáticos (APScheduler) — 10 jobs activos

| Job | Trigger | Descripción |
|-----|---------|-------------|
| Detección diaria (todos los canales) | Cron **07:00 UTC** diario | `_job_daily()` — detección pubs nuevas + update métricas |
| Stories captura | Cron **:00 cada hora** | `_job_stories()` — captura Stories Instagram <24h |
| Stories captura final | Cron **:50-:59 cada hora** | Reintento final antes de expirar las Stories |
| GA4 histórico | Cron **lunes 00:00 UTC** | Snapshot semanal ISO GA4 web |
| YouTube Analytics | Cron **lunes 00:30 UTC** | Snapshot semanal YouTube |
| YouTube Shorts Analytics | Cron **lunes 00:45 UTC** | Snapshot semanal YouTube Shorts |
| Instagram snapshot semanal | Cron **lunes 01:00 UTC** | Snapshot semanal Instagram posts/reels/stories |
| Facebook snapshot semanal | Cron **lunes 01:30 UTC** | Snapshot semanal Facebook |
| Threads snapshot semanal | Cron **lunes 02:00 UTC** | Snapshot semanal Threads |
| YouTube Shorts actualización métricas | Cada **48 horas** | `update_metrics()` para Shorts recientes |

Horarios diarios configurables en `config_medio.hora_trigger_diario` y `hora_trigger_stories`.

---

## Base de datos — volumen actual

*Datos a 2026-04-09*

| Tabla | Filas | Descripción |
|-------|------:|-------------|
| `publicaciones` | ~1.537 | Publicaciones detectadas con métricas actuales |
| `historial_metricas` | ~2.448+ | Snapshots semanales ISO por publicación (reach/likes/shares/diff) |
| `marcas` | 187 | Catálogo de marcas con aliases |
| `log_ejecuciones` | 22+ | Log de cada ejecución de agente (agente, tipo, estado, conteos) |
| `tokens_canal` | 12+ | Tokens API cifrados por medio+canal+clave |
| `agencias` | 0 | Catálogo de agencias *(vacío — pendiente importar)* |
| `config_medio` | 0 | Config por medio *(pendiente — usa valores por defecto)* |
| `medios` | 1 | Medios registrados |

**Desglose publicaciones por canal:**

| Canal | Pubs |
|-------|-----:|
| Web | ~293 |
| YouTube | ~49 |
| YouTube Shorts | ~30 |
| Instagram posts/Reels | 503 |
| Instagram Stories | ~10 |
| Facebook | 503 |
| Threads | ~138 |
| **TOTAL** | **~1.537** |

**Reach total acumulado: ~30.1M**

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
| **v0.7** *(actual)* | YouTube Shorts Agent · Threads Agent · 10 jobs APScheduler · Apache mod_proxy producción · fix Stories inserción/vídeo/retry · fix timestamps Meta · campo `texto` en DB · fix web fechas datePublished · fix Shorts duplicados |

### Pendientes

**Prioridad Alta**
- Generador PDF por marca/año (`reportlab` o `weasyprint`) — portada, tabla pubs, totales canal, capturas
- Renovación automática page token Facebook (~60 días) + alerta 7 días antes

**Prioridad Media**
- Notificación diaria email a cada marca/agencia via SMTP

**Fase 3 — X (Twitter)**
- X Agent: X API v2 Bearer Token — `impressions`, `likes`, `retweets`, `replies`
- Registrar en orchestrator; añadir `CanalEnum.x`

**Fase 3 — TikTok**
- TikTok Agent: Research API (pendiente aprobación) — `plays`, `likes`, `shares`

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

# Reconstruir frontend
cd /home/pirineos/social-intelligence/frontend
npm run build
cd ..

# Actualizar + rebuild + reiniciar (secuencia completa)
cd /home/pirineos/social-intelligence && git pull origin main && \
  cd frontend && npm run build && cd .. && \
  systemctl restart social-intelligence

# Ver logs de aplicación
journalctl -u social-intelligence --since "1 hour ago"
journalctl -u social-intelligence -n 100
```

### Despliegue inicial en CentOS (referencia)

```bash
# 1. Clonar
git clone https://github.com/marcsub/social-intelligence /home/pirineos/social-intelligence
cd /home/pirineos/social-intelligence

# 2. Entorno Python
python3.13 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 3. MySQL
mysql -u root -p -e "CREATE DATABASE social_intelligence CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
# Crear usuario pirineos, configurar DB_URL en .env

# 4. Variables entorno
cp .env.example .env  # editar: DB_URL, JWT_SECRET, SMTP_*

# 5. Frontend
cd frontend && npm install && npm run build && cd ..

# 6. Migraciones DB (ejecutar una vez)
python scripts/migrate_add_sin_datos.py
python scripts/migrate_add_youtube_short.py
python scripts/migrate_add_texto.py

# 7. Tokens y datos base
python scripts/import_marcas.py
python scripts/authorize_meta.py roadrunningreview
python scripts/authorize_facebook.py --slug roadrunningreview
python scripts/authorize_youtube.py

# 8. systemd
# /etc/systemd/system/social-intelligence.service
# ExecStart=/home/pirineos/social-intelligence/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
systemctl enable --now social-intelligence

# 9. Apache — ver sección "Configuración Apache" arriba

# 10. Backfill inicial producción
python scripts/fix_2026.py --slug roadrunningreview
python scripts/backfill_historico.py --slug roadrunningreview
python scripts/backfill_shorts_historico.py --slug roadrunningreview
python scripts/backfill_texto.py --slug roadrunningreview
python scripts/fix_facebook_reach.py --slug roadrunningreview
```

---

## Problemas conocidos

### 🔴 PENDIENTE

| Problema | Descripción | Acción |
|----------|-------------|--------|
| Facebook page token | Caduca en ~60 días — pendiente renovación automática | Implementar alerta + renovación |
| Stories 8 abril sin reach | Stories del 2026-04-08 sin datos de reach | Introducir manualmente |

### 🟡 EN SEGUIMIENTO

| Área | Descripción |
|------|-------------|
| Instagram errores 400 | Posts antiguos >2 años devuelven 400 — normal, Meta no expone insights históricos | Esperado |
| YouTube reach | YouTube Analytics no expone impresiones por vídeo via API — `views` como proxy | Limitación API |
| Brand ID sin marca | ~97 publicaciones sin marca asignada — revisar aliases Bikkoa, U-Tech y otros | Manual |

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
| TikTok | Research API pendiente aprobación |

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
| 3 | Notificación diaria email a cada marca | 🟡 Media | ⬜ siguiente |
| 4 | X (Twitter) Agent — Bearer Token disponible | 🟡 Media | ⬜ siguiente |
| 5 | TikTok Agent — pendiente aprobación API | 🔵 Baja | ⬜ bloqueado |
| 6 | Brand Vision Agent — identificación marca por imagen con Claude API | 🔵 Baja | ⬜ siguiente |
