-- Migración: añadir columna etiquetas a publicaciones
-- Ejecutar: mysql -u root -p social_intelligence < scripts/migrate_etiquetas.sql

ALTER TABLE publicaciones
  ADD COLUMN etiquetas TEXT NULL COMMENT 'JSON list de etiquetas: @mentions, usertags, playlists'
  AFTER notas;
