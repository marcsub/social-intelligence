# RESULTADO — Social Intelligence

Histórico de ejecuciones y estado del sistema.

---

## 2026-04-01 — Ejecución completa de diagnóstico + fixes + validación

### Diagnósticos ejecutados

#### test_facebook_reach.py → PROBLEMA: permisos insuficientes

- `post_impressions_unique` devuelve `data=[]` (sin error, sin datos)
- `post_impressions` y `post_reach` devuelven `#100 invalid metric` — estas métricas **no existen** en v21.0
- El system_token arroja `Invalid OAuth 2.0 Access Token`
- **Causa raíz: el token Facebook no tiene el permiso `pages_read_engagement`**
- **Acción requerida del usuario** (ver abajo)

#### test_ga4_semanal.py → OK, no hay problema

- GA4 conecta correctamente, paths coinciden, views = reach en DB
- `SUM(reach_diff) = reach` para todas las publicaciones web → historial correcto
- No se requiere ningún fix

#### backfill_reels.py → BUG encontrado y corregido

- La Instagram Graph API devuelve `media_type='VIDEO'` para Reels, **nunca 'REELS'**
- Corrección: detección por permalink (`/reel/` en la URL)
- **61 Reels de 2026 encontrados; 60 ya existían en DB con tipo='video' (incorrecto)**
- Corrección masiva en DB: **349 registros actualizados de tipo='video' → tipo='reel'**

### Fixes de código aplicados

| Fix | Archivo | Descripción |
|-----|---------|-------------|
| Bug 3 — Reels | `agents/instagram_agent.py` | Función `_get_tipo()`: detecta reel por permalink `/reel/` |
| Bug 3 — Reels | `scripts/backfill_reels.py` | Filtro por permalink en vez de `media_type=='REELS'` |
| Bug 1 — Facebook | `agents/facebook_agent.py` | Elimina métricas inválidas del fallback (`post_impressions`, `post_reach`) |
| Validador | `scripts/validate_all.py` | V10: detecta reels por permalink en vez de media_type |
| DB | SQL directo | 349 publicaciones actualizadas tipo='video'→'reel' |

### Resultado validate_all.py

```
PASS: 6 | FAIL: 0 | ALERTA: 6 | INFO: 1

✓ V02: Sin marca asignada — 7.3% (OK, < 10%)
✓ V03: Reach=0 en 2026 — sólo facebook (esperado)
✓ V05: Histórico semanal — web 13 semanas, todos con diff>0
✓ V06: Semanas web — 13 semanas, todas con reach_diff>0 (W03-W14)
✓ V07: Coherencia reach vs SUM(reach_diff) — 0% desvío en 5 publicaciones
✓ V08: GA4 conecta — views=838 ≈ reach DB=837

⚠ V01: Facebook reach=0 en 500 publicaciones → falta pages_read_engagement
⚠ V09: Facebook insights reach=0 → mismo motivo
⚠ V10: FALSA ALARMA en validador → ya corregida (reels detectados por permalink)
⚠ V11-V13: API server no arrancado → errores de conexión (no es un bug)
```

### Resumen de datos en DB

| Canal           | Pubs  | Reach      | Snapshots | Reels |
|-----------------|-------|------------|-----------|-------|
| instagram_post  | 501   | 16,850,197 | 81        | 350   |
| youtube         | 41    | 184,983    | 41        | 0     |
| web             | 289   | 104,657    | 428       | 0     |
| instagram_story | 2     | 3,922      | 0         | 0     |
| facebook        | 500   | 0          | 80        | 0     |

---

## ACCIÓN REQUERIDA — Bug 1 Facebook reach=0

**El token Facebook no tiene el permiso `pages_read_engagement`.**
Sin este permiso, `/{post_id}/insights?metric=post_impressions_unique` devuelve `data=[]`.

### Pasos para arreglarlo:

1. Ir a **Meta for Developers** → tu app → **Graph API Explorer**
2. Generar un nuevo User Token con estos permisos:
   - `pages_read_engagement` ← **el que falta**
   - `pages_read_user_content`
   - `pages_show_list`
   - `business_management`
3. Intercambiarlo por un Long-Lived User Token (60 días):
   ```
   GET /oauth/access_token?grant_type=fb_exchange_token&client_id={app_id}&client_secret={app_secret}&fb_exchange_token={short_token}
   ```
4. Obtener el Page Access Token:
   ```
   GET /{page_id}?fields=access_token&access_token={long_lived_token}
   ```
5. Actualizar el token en la DB via `python scripts/authorize_meta.py`
6. Re-ejecutar: `python scripts/validate_all.py --slug roadrunningreview`

---

## Comandos para ejecutar el sistema

```bash
# Arrancar API (necesaria para V11-V13)
cd C:/proyectos/social-intelligence
source venv/Scripts/activate
python main.py
# O en background: uvicorn main:app --reload

# Backfill web si hacen falta más semanas
python scripts/backfill_historico.py --slug roadrunningreview --canal web --anio 2026

# Validación completa (con API arrancada)
python scripts/validate_all.py --slug roadrunningreview
```
