# Social Intelligence System

Sistema multi-medio de recogida y gestión de métricas de publicaciones en redes sociales.

## Stack
- **Backend:** Python 3.11 + FastAPI + SQLAlchemy
- **Base de datos:** MySQL (una base de datos, esquema compartido)
- **Frontend:** React 18 + Vite
- **Scheduler:** APScheduler (dentro del proceso Python)
- **Servidor:** CentOS con systemd

## Estructura del proyecto

```
social-intelligence/
├── main.py                    # Punto de entrada FastAPI
├── requirements.txt
├── .env.example               # Plantilla de variables de entorno
├── api/
│   ├── auth.py                # JWT login
│   └── routes/
│       └── medios.py          # CRUD medios, marcas, agencias, tokens
├── core/
│   ├── settings.py            # Configuración global (pydantic-settings)
│   ├── crypto.py              # Cifrado Fernet para tokens
│   └── brand_id_agent.py      # Identificación de marca por texto
├── models/
│   └── database.py            # Modelos SQLAlchemy + esquema MySQL
├── agents/                    # Agentes por canal (Fase 1+)
│   ├── web_agent.py           # RSS + GA4
│   └── youtube_agent.py       # YouTube Data API + Analytics API
├── frontend/
│   ├── index.html
│   ├── package.json
│   ├── vite.config.js
│   └── src/
│       ├── main.jsx
│       └── App.jsx            # Panel completo (un solo fichero)
└── scripts/
    ├── setup.sh               # Instalación en CentOS
    ├── start.sh               # Arranque producción
    └── social-intelligence.service  # Systemd unit
```

## Instalación

### 1. Clonar y configurar
```bash
cd /opt
git clone <repo> social-intelligence
cd social-intelligence
chmod +x scripts/*.sh
./scripts/setup.sh
```

### 2. Configurar MySQL
```sql
CREATE DATABASE social_intelligence CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'social_app'@'localhost' IDENTIFIED BY 'TU_PASSWORD';
GRANT ALL PRIVILEGES ON social_intelligence.* TO 'social_app'@'localhost';
FLUSH PRIVILEGES;
```

### 3. Editar .env
```bash
cp .env.example .env
nano .env
# Rellenar: DB_PASSWORD, PANEL_PASSWORD, JWT_SECRET (mínimo 32 caracteres)
```

### 4. Arrancar
```bash
# Desarrollo
source venv/bin/activate
uvicorn main:app --reload --port 8000

# Producción (systemd)
cp scripts/social-intelligence.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now social-intelligence
```

### 5. Frontend en desarrollo
```bash
cd frontend
npm install
npm run dev   # http://localhost:5173 (proxy → :8000)
```

## Tablas de base de datos

| Tabla | Descripción |
|-------|-------------|
| `medios` | Medios/publicaciones configurados |
| `config_medio` | Configuración operativa por medio |
| `tokens_canal` | Tokens de API cifrados por medio+canal |
| `marcas` | Catálogo de marcas por medio (editable en panel) |
| `agencias` | Catálogo de agencias por medio (editable en panel) |
| `publicaciones` | Registro central de publicaciones y métricas |
| `historial_metricas` | Snapshots históricos de métricas |
| `log_ejecuciones` | Log de cada ejecución de agentes |

## Seguridad de tokens

Los tokens de API (Instagram, YouTube, X, TikTok, GA4) se cifran con **Fernet AES-128**
antes de guardarlos en MySQL. La clave se deriva del `JWT_SECRET` del `.env`.
Nunca se almacenan en texto plano. Desde el panel sólo se pueden escribir o borrar,
nunca leer.

## Añadir un nuevo medio

1. Panel web → "Nuevo medio" → rellenar slug, nombre, RSS
2. Configuración → ajustar umbral de confianza, triggers, GA4 property ID
3. Tokens API → introducir tokens para cada canal
4. Marcas → crear catálogo de marcas con aliases y emails
5. Agencias → crear catálogo de agencias con aliases

## Fases de desarrollo

| Fase | Contenido |
|------|-----------|
| **1 — actual** | Base, Web Agent, YouTube Agent, Brand ID Agent, panel, orquestador |
| **2** | Instagram Agent (posts + Stories), Facebook Agent |
| **3** | X Agent, TikTok Agent |
| **4** | Generador PDF de informes, Dashboard Looker Studio |
| **5** | YouTube Scraper (canales ajenos), Brand Vision Agent (IA visual) |
