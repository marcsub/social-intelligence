-- migrate_nuevas_columnas.sql
-- Añade las columnas nuevas de Mejora 1 y Mejora 2 a la BD existente.
-- Ejecutar UNA sola vez contra la base de datos en producción.
-- Las columnas son nullable → no requiere backfill previo para no romper la app.

-- ── Mejora 1: semana_iso en historial_metricas ────────────────────────────────
ALTER TABLE historial_metricas
  ADD COLUMN semana_iso VARCHAR(8) NULL COMMENT 'Semana ISO, ej: 2026-W13';

-- ── Mejora 2: estado_marca en publicaciones ───────────────────────────────────
ALTER TABLE publicaciones
  ADD COLUMN estado_marca ENUM('estimated','to_review','ok') NULL
  COMMENT 'Estado de asignación de marca: estimated=auto>=80, to_review=revisar, ok=validado manualmente';

-- Retroalimentar publicaciones existentes
UPDATE publicaciones
  SET estado_marca = 'estimated'
  WHERE confianza_marca >= 80 AND marca_id IS NOT NULL;

UPDATE publicaciones
  SET estado_marca = 'to_review'
  WHERE estado_marca IS NULL AND (confianza_marca < 80 OR marca_id IS NULL);
