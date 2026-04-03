#!/bin/bash
# scripts/setup.sh — Configuración inicial en servidor CentOS
# Ejecutar como root o con sudo

set -e

echo "=== Social Intelligence System — Setup ==="

# 1. Python 3.11+
if ! command -v python3.11 &>/dev/null; then
  echo "[1/6] Instalando Python 3.11..."
  yum install -y python3.11 python3.11-pip python3.11-devel
else
  echo "[1/6] Python 3.11 ya instalado"
fi

# 2. Node.js 20 (para build del frontend)
if ! command -v node &>/dev/null; then
  echo "[2/6] Instalando Node.js 20..."
  curl -fsSL https://rpm.nodesource.com/setup_20.x | bash -
  yum install -y nodejs
else
  echo "[2/6] Node.js ya instalado"
fi

# 3. Virtualenv Python
echo "[3/6] Creando entorno virtual Python..."
python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 4. Build frontend React
echo "[4/6] Construyendo frontend React..."
cd frontend
npm install
npm run build
cd ..

# 5. Copiar .env
if [ ! -f .env ]; then
  echo "[5/6] Creando .env desde plantilla..."
  cp .env.example .env
  echo "  >>> EDITA .env con tus valores antes de arrancar <<<"
else
  echo "[5/6] .env ya existe"
fi

# 6. Crear base de datos MySQL
echo "[6/6] Instrucciones para MySQL:"
echo ""
echo "  Ejecuta en MySQL como root:"
echo "  CREATE DATABASE social_intelligence CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
echo "  CREATE USER 'social_app'@'localhost' IDENTIFIED BY 'TU_PASSWORD';"
echo "  GRANT ALL PRIVILEGES ON social_intelligence.* TO 'social_app'@'localhost';"
echo "  FLUSH PRIVILEGES;"
echo ""
echo "=== Setup completado ==="
echo "Edita .env y luego ejecuta: ./scripts/start.sh"
