#!/bin/bash
# scripts/start.sh — Arranca la aplicación en producción
set -e
source venv/bin/activate
exec uvicorn main:app --host 0.0.0.0 --port 8000 --workers 2 --log-level info
