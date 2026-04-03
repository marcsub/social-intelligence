# Social Intelligence System — STATUS

> Última actualización: 2026-04-01 — datos reales de DB

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
| Servidor producción | CentOS — **pendiente despliegue** |
| Entorno desarrollo | Windows 11 local — uvicorn `localhost:8000` |

---

## Medios configurados

| slug | Nombre | URL web | RSS/Sitemap | Activo |
|------|--------|---------|-------------|--------|
| `roadrunningreview` | ROADRUNNINGReview | https://www.roadrunningreview.com | SiteMapTrailES0.xml | ✅ |

---

## Estado actual por canal — roadrunningreview

*Datos a 2026-04-01*

| Canal | Pubs | Reach total | Likes | Shares | Actualizadas | Revisión | Pendiente | Errores |
|-------|-----:|------------:|------:|-------:|-------------:|---------:|----------:|--------:|
| instagram_post | 502 | 16.850.197 | 526.172 | 55.980 | 137 | 87 | 278 | 0 |
| facebook | 500 | **0** | 0 | 5.651 | 0 | 0 | 0 | **500** |
| web | 289 | 19.900 | 0 | 0 | 268 | 2 | 19 | 0 |
| youtube | 41 | 184.983 | 5.162 | 0 | 41 | 0 | 0 | 0 |
| instagram_story | 2 | 3.922 | 0 | 0 | 0 | 0 | 2 | 0 |
| **TOTAL** | **1.334** | **17.058.002** | **531.334** | **61.631** | | | | |

**Top 10 marcas por reach acumulado:**

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
- `to_review` (pendientes validación): **269**
- Sin marca asignada: **97** publicaciones (7,3%)

**Histórico semanal:**
- Semanas con snapshot: **13** (2026-W02 → 2026-W14)
- Total snapshots en `historial_metricas`: **630**

**Última ejecución (2026-03-31 03:40 UTC):**

| Agente | Tipo | Estado | Nuevas | Actualizadas | Revisión |
|--------|------|--------|-------:|-------------:|---------:|
| instagram_stories | stories | ✅ ok | 2 | 0 | 0 |
| web | diario | ✅ ok | 0 | 50 | 0 |
| youtube | diario | ✅ ok | 0 | 0 | 0 |
| instagram | diario | ✅ ok | 0 | 50 | 0 |
| facebook | diario | ✅ ok | 0 | 50 | 0 |

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
| `api/auth.py` | JWT login panel, usuario/password desde `.env` | ✅ |
| `api/routes/medios.py` | CRUD medios, marcas, agencias, tokens cifrados | ✅ |
| `api/routes/publicaciones.py` | Listado filtrable, bulk actions, analytics (resumen/marca/comparar/semanal) | ✅ |
| `agents/web_agent.py` | RSS/Sitemap XML → GA4 Data API; histórico semanal por semana ISO | ✅ |
| `agents/youtube_agent.py` | YouTube Data API v3 + Analytics API; OAuth2 con refresh automático | ✅ |
| `agents/instagram_agent.py` | Instagram Graph API; posts + reels; métricas separadas por tipo | ✅ |
| `agents/instagram_stories_agent.py` | Captura Stories + imagen; debe ejecutarse < 24h | ✅ |
| `agents/facebook_agent.py` | Graph API v25.0; `post_impressions_unique` como métrica principal; skip posts > 24 meses | ⚠ reach pendiente backfill |
| `utils/semanas.py` | Helpers ISO week: `get_semana_iso`, `get_rango_semana`, `semanas_entre` | ✅ |

### Frontend — `frontend/src/App.jsx`

| Vista | Descripción |
|-------|-------------|
| **Login** | JWT; token en localStorage; redirección automática si ya autenticado |
| **Panel medios** | CRUD medios, marcas, agencias; gestión tokens cifrados por canal |
| **Publicaciones** | Tabla filtrable por canal/marca/estado/fecha; selección múltiple Shift+click; bulk-refresh, asignar marca, marcar revisado; badge `estado_marca` |
| **Analytics — Resumen** | KPIs período + gráfica mensual reach por canal + top 10 marcas + gráfica semanal ISO (fallback reach acumulado si `reach_diff=0`) |
| **Analytics — Dashboard marca** | KPIs por marca + reach por canal (bar) + evolución mensual + últimas 5 pubs + gráfica semanal |
| **Analytics — Comparar marcas** | Comparativa lado a lado de dos marcas |
| **Analytics — Por canal** | Filtro por canal con gráfica semanal específica |

### Scripts de utilidad — `scripts/`

| Script | Propósito | Comando | Estado |
|--------|-----------|---------|--------|
| `authorize_meta.py` | Tokens Instagram + Facebook via Graph API Explorer | `python scripts/authorize_meta.py roadrunningreview` | ✅ |
| `authorize_facebook.py` | OAuth flow completo → page token permanente | `python scripts/authorize_facebook.py --slug roadrunningreview` | 🆕 |
| `authorize_youtube.py` | OAuth2 YouTube → refresh token | `python scripts/authorize_youtube.py` | ✅ |
| `import_marcas.py` | Importación masiva catálogo de marcas (187) | `python scripts/import_marcas.py` | ✅ |
| `backfill_historico.py` | Snapshots semanales históricos 2026 web + RRSS | `python scripts/backfill_historico.py --slug roadrunningreview` | ✅ |
| `backfill_reels.py` | Backfill Reels Instagram 2026 con paginación completa | `python scripts/backfill_reels.py --slug roadrunningreview [--dry-run]` | ✅ |
| `fix_facebook_reach.py` | Rellena reach 500 pubs Facebook con `update_metrics()` v25.0 | `python scripts/fix_facebook_reach.py --slug roadrunningreview` | 🆕 |
| `migrate_add_sin_datos.py` | ALTER TABLE MySQL: añade `sin_datos` al ENUM | `python scripts/migrate_add_sin_datos.py` *(1 vez)* | ✅ |
| `validate_all.py` | Suite validación completa: tokens, DB, API, métricas | `python scripts/validate_all.py --slug roadrunningreview` | ✅ |
| `test_facebook_reach.py` | Diagnóstico verbose reach Facebook + `/me/permissions` | `python scripts/test_facebook_reach.py --slug roadrunningreview [--post-id ID]` | ✅ |
| `test_fb_metrics_v25.py` | Prueba sistemática métricas/endpoints v25.0 | `python scripts/test_fb_metrics_v25.py --slug roadrunningreview` | 🆕 |
| `test_ga4_semanal.py` | Verifica GA4 por semana ISO para web | `python scripts/test_ga4_semanal.py --slug roadrunningreview` | ✅ |
| `diagnose_web_agent.py` | Diagnóstico web agent: RSS, GA4, checkpoints, DB | `python scripts/diagnose_web_agent.py --slug roadrunningreview` | ✅ |
| `reset_checkpoint.py` | Resetea checkpoint web agent a fecha concreta | `python scripts/reset_checkpoint.py --slug roadrunningreview --fecha 2026-01-01` | ⚠ usar con cuidado |
| `fix_2026.py` | Diagnostica/corrige pubs 2026 no detectadas por checkpoint | `python scripts/fix_2026.py --slug roadrunningreview` | ✅ |

---

## Problemas conocidos

### 🔴 EN CURSO

**Facebook reach = 0 — backfill pendiente (500 pubs)**

La DB muestra 500 publicaciones Facebook con `estado_metricas='error'` y `reach=0`.
El fix está implementado (`_resolve_page_token` + `post_impressions_unique` primero),
pero el backfill aún no se ha ejecutado con el nuevo page token OAuth.

Pendiente ejecutar:
```bash
python scripts/authorize_facebook.py --slug roadrunningreview  # si no hecho ya
python scripts/fix_facebook_reach.py --slug roadrunningreview  # ~10 min para 500 posts
```

### 🟡 PENDIENTE DE VERIFICAR

| Área | Descripción |
|------|-------------|
| Stories capturas | Solo 2 stories en DB — verificar que `stories_images/` se está poblando correctamente |
| Reels reach | Algunos de los 502 instagram_posts (reels) pueden tener reach=0 — revisar fallback `plays→reach` |
| Brand ID sin marca | 97 publicaciones sin marca asignada (7,3%) — revisar aliases para Bikkoa, U-Tech y otros |
| Instagram 278 pendientes | 278 posts instagram con `estado_metricas='pendiente'` — ejecutar update_metrics |

### 🔵 LIMITACIONES CONOCIDAS DE APIs

| API | Limitación |
|-----|-----------|
| Facebook v25.0 | Solo `post_impressions_unique` funciona; `reach`, `impressions`, `post_engaged_users` devuelven 400 |
| Facebook | ~10% posts con timeout esporádico — se reintenta en ciclo siguiente |
| Facebook | Page token expira en ~60 días — pendiente alerta/renovación automática |
| YouTube Analytics | `impressions` no soportado por vídeo — se usa `views` como proxy |
| Instagram Reels | API devuelve `media_type=VIDEO` para vídeos y reels — se detectan por permalink `/reel/` |
| Meta RRSS | Histórico solo desde semana actual hacia adelante — no hay backfill de semanas pasadas |
| TikTok | Research API pendiente aprobación |

### ⚪ DEUDA TÉCNICA

| Descripción | Prioridad |
|-------------|-----------|
| Comparaciones `datetime` naive/aware dispersas — centralizar en `utils/dates.py` | Baja |
| `validate_all.py` V11-V13 requieren uvicorn activo para JWT | Baja |
| `authorize_meta.py` usa `GRAPH = v21.0` — actualizar a v25.0 | Baja |
| Facebook page token expira ~60 días — implementar renovación automática o alerta 7 días | Media |

---

## Triggers automáticos (APScheduler)

| Job ID | Trigger | Función | Tareas |
|--------|---------|---------|--------|
| `roadrunningreview_stories` | Cron diario **06:00 UTC** | `_job_stories()` | Captura Stories Instagram antes de 24h |
| `roadrunningreview_daily` | Cron diario **07:00 UTC** | `_job_daily()` | Detección pubs nuevas todos los canales + update métricas |
| `roadrunningreview_web_weekly` | Cron **lunes 01:00 UTC** | `_job_web_weekly()` | Snapshot semanal ISO GA4 + RRSS |

Horarios diarios configurables en `config_medio.hora_trigger_diario` y `hora_trigger_stories`.

---

## Base de datos — volumen actual

| Tabla | Filas | Descripción |
|-------|------:|-------------|
| `historial_metricas` | 2.448 | Snapshots semanales ISO por publicación (reach/likes/shares/diff) |
| `publicaciones` | 1.334 | Publicaciones detectadas con métricas actuales |
| `marcas` | 187 | Catálogo de marcas con aliases |
| `log_ejecuciones` | 22 | Log de cada ejecución de agente (agente, tipo, estado, conteos) |
| `tokens_canal` | 12 | Tokens API cifrados por medio+canal+clave |
| `agencias` | 0 | Catálogo de agencias *(vacío — pendiente importar)* |
| `config_medio` | 0 | Config por medio *(pendiente — usa valores por defecto)* |
| `medios` | 1 | Medios registrados *(MySQL informa 0 por estimación, real=1)* |

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
| **v0.6** *(actual)* | Fix Brand ID Agent substring→prefix · fix timezone naive/aware · Facebook v21→v25 + `_resolve_page_token` · `estado_marca` en publicaciones · `sin_datos` enum · `authorize_facebook.py` · `validate_all.py` · STATUS.md |

### Pendientes

**Fase 3 — X (Twitter) + TikTok**
- X Agent: X API v2 Bearer Token — `impressions`, `likes`, `retweets`, `replies`
- TikTok Agent: Research API (pendiente aprobación) — `plays`, `likes`, `shares`
- Registrar en orchestrator; añadir `CanalEnum.x` / `CanalEnum.tiktok`

**Fase 4 — Informes PDF**
- Generador PDF por marca/año con `reportlab` o `weasyprint`
- Plantilla: portada, tabla publicaciones, totales por canal, espacio capturas
- Botón en panel → descarga PDF inmediata
- Envío automático email al contacto de la marca

**Fase 5 — Avanzado**
- YouTube Scraper canales ajenos (reach vídeos de marcas externas)
- Brand Vision Agent: identificación marca por imagen con Claude API Vision (cuando Brand ID < umbral)
- Renovación automática page token Facebook + alerta 7 días antes de expirar

---

## Guía de despliegue CentOS

```bash
# 1. Clonar
git clone <repo> /opt/social-intelligence && cd /opt/social-intelligence

# 2. Entorno Python
python3.13 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 3. MySQL
mysql -u root -p -e "CREATE DATABASE social_intelligence CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
# Crear usuario, configurar DB_URL en .env

# 4. Variables entorno
cp .env.example .env  # editar: DB_URL, JWT_SECRET, SMTP_*

# 5. Frontend
cd frontend && npm install && npm run build && cd ..

# 6. Tokens y datos base
python scripts/import_marcas.py
python scripts/authorize_meta.py roadrunningreview
python scripts/authorize_facebook.py --slug roadrunningreview
python scripts/authorize_youtube.py
python scripts/migrate_add_sin_datos.py

# 7. systemd
# /etc/systemd/system/social-intelligence.service
# ExecStart=/opt/social-intelligence/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
systemctl enable --now social-intelligence

# 8. nginx + SSL
# proxy_pass http://127.0.0.1:8000
certbot --nginx -d <dominio>

# 9. Backfill inicial producción
python scripts/fix_2026.py --slug roadrunningreview
python scripts/backfill_historico.py --slug roadrunningreview
python scripts/fix_facebook_reach.py --slug roadrunningreview
```

---

## Próximas prioridades

| # | Tarea | Estado |
|---|-------|--------|
| 1 | Ejecutar `fix_facebook_reach.py` y verificar reach > 0 en > 80% posts | 🔴 pendiente |
| 2 | Verificar capturas Stories end-to-end (solo 2 en DB) | 🟡 pendiente |
| 3 | Actualizar 278 instagram_posts con `estado='pendiente'` | 🟡 pendiente |
| 4 | Fase 3: X Agent (Bearer Token ya disponible en X Developer Portal) | ⬜ siguiente |
| 5 | Fase 4: Generador PDF informes por marca | ⬜ siguiente |
| 6 | Despliegue servidor CentOS | ⬜ siguiente |
