-- migrate_historico.sql
-- Actualiza historial_metricas para el sistema de snapshots semanales ISO.
-- Ejecutar UNA sola vez. Requiere MySQL 8+.

-- ── 1. Nuevas columnas de diferencial y fuente ────────────────────────────────
-- Usar procedimiento para añadir solo si no existen (compatible MySQL 8)

ALTER TABLE historial_metricas
  ADD COLUMN IF NOT EXISTS reach_diff    INT        NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS likes_diff    INT        NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS shares_diff   INT        NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS comments_diff INT        NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS clicks_diff   INT        NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS fuente        VARCHAR(20) NOT NULL DEFAULT 'api';

-- ── 2. Unique key (publicacion_id, semana_iso) ────────────────────────────────
-- Primero limpiar duplicados si los hubiera (mantener el más reciente)
DELETE h1 FROM historial_metricas h1
INNER JOIN historial_metricas h2
ON  h1.publicacion_id = h2.publicacion_id
AND h1.semana_iso     = h2.semana_iso
AND h1.id             < h2.id
WHERE h1.semana_iso IS NOT NULL;

-- Añadir constraint (si no existe)
ALTER TABLE historial_metricas
  ADD CONSTRAINT uq_historial_pub_semana UNIQUE (publicacion_id, semana_iso);

-- ── 3. Inicializar reach_diff con reach para snapshots existentes ─────────────
-- Para registros con semana_iso que tienen reach_diff=0, asumir que el diff
-- es el propio reach (primera captura, sin semana previa).
UPDATE historial_metricas
  SET reach_diff = reach
  WHERE semana_iso IS NOT NULL AND reach_diff = 0 AND reach > 0;
