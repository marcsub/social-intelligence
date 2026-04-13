# Social Analytics Dashboard — Especificación para Claude Code

> Documento de producto completo para construir el módulo de analytics social.  
> Stack sugerido: **React + TypeScript + Tailwind CSS + Recharts + shadcn/ui**  
> Inspiración visual: Hootsuite Analytics, Metricool, Cyfe

---

## 0. Contexto del negocio

- Agencia que gestiona **+25 marcas** simultáneamente
- Canales activos: **Instagram, Facebook, Twitter/X, YouTube, TikTok**
- Gestión paid: **Business Manager / Ads Manager** de cada red (Meta Ads, TikTok Ads, YouTube Ads)
- Ciclo de trabajo semanal → los datos deben ser comparables **semana a semana y mes a mes**
- El histórico de seguidores se guarda en base de datos propia (snapshot diario via API)

---

## 1. Arquitectura global de la aplicación

### 1.1 Navegación principal (top nav)
Tres pestañas de primer nivel, persistentes en toda la app:

```
[ Clipping ]   [ Marcas ]   [ Patrocinados ]
```

- La pestaña activa se marca con un underline del color de acento principal
- El cambio de pestaña NO recarga la página (SPA routing)

### 1.2 Barra de filtros globales
**Siempre visible** bajo la navegación, afecta a TODAS las pestañas simultáneamente:

| Filtro | Tipo | Opciones |
|--------|------|----------|
| Marca | Dropdown buscable | Lista de marcas + "Todas las marcas" |
| Canal | Multi-select con chips | Instagram, Facebook, Twitter/X, YouTube, TikTok + "Todos" |
| Periodo | Toggle + Selector | **Semanas** (Sem 1–53) / **Meses** (Ene–Dic) |
| Comparativa | Toggle | vs. periodo anterior / vs. mismo periodo año anterior |

**Comportamiento del filtro de Canal:**
- Chips con el color/icono de cada red social
- Selección múltiple permitida
- Al seleccionar un canal, todos los gráficos y tablas se filtran en tiempo real
- Estado persistido en URL (query params) para poder compartir vistas

**Comportamiento del filtro de Periodo:**
- Modo Semanas: selector de semana ISO (Sem 14, 2026)
- Modo Meses: selector mes + año
- El rango siempre muestra el periodo actual por defecto
- Siempre visible el delta vs. periodo de comparación elegido

---

## 2. Pestaña: Marcas

### 2.1 Layout general
```
[Filtros globales]
─────────────────────────────────────────────
[KPI Cards × 4-5]
─────────────────────────────────────────────
[Gráfico engagement — 2/3] [Histórico seguidores — 1/3]
─────────────────────────────────────────────
[Top 5 posts]          [Bottom 5 posts]
─────────────────────────────────────────────
[Audiencia: género + edad + horas óptimas]
─────────────────────────────────────────────
```

### 2.2 KPI Cards (fila superior)
Mostrar entre 4 y 5 cards según canales activos. Cada card:

```
┌────────────────────────┐
│ ● Instagram            │  ← punto de color del canal
│                        │
│  48.2K                 │  ← valor principal, 24px bold
│  Seguidores            │  ← label, 12px muted
│                        │
│  ↑ +3.4% vs sem. ant.  │  ← delta en verde/rojo
│  ████░░░░ sparkline    │  ← mini sparkline últimas 8 semanas
└────────────────────────┘
```

- Si el filtro de canal está en "Todos", mostrar una card por canal
- Si está filtrado por un canal, mostrar cards de métricas de ese canal: seguidores, engagement total, alcance, impresiones
- Delta siempre referenciado al periodo de comparación del filtro global

### 2.3 Gráfico de evolución de engagement

**Tipo:** Líneas (Recharts LineChart)  
**Eje X:** Semanas (S1–S8) o Meses según filtro  
**Eje Y:** Total interacciones (likes + comentarios + compartidos)  

**Toggle interno:**
- `Total` → una sola línea morada agregada
- `Por canal` → una línea por canal, cada una con su color de marca y un patrón de trazo diferente (sólido, dashed, dotted) para accesibilidad

**Interactividad:**
- Tooltip al hover mostrando valores exactos por canal
- Click en un punto → abre panel lateral con desglose de ese periodo
- Leyenda clickable para mostrar/ocultar canales

**Colores de canales (constantes en toda la app):**
```
Instagram:  #E1306C
Facebook:   #1877F2
Twitter/X:  #1DA1F2
YouTube:    #FF0000
TikTok:     #534AB7  (usar morado porque el negro no es visible en modo oscuro)
```

### 2.4 Histórico de seguidores

Panel lateral del gráfico de engagement.

**Estructura:**
- Lista vertical, un ítem por canal activo
- Cada ítem: icono canal + nombre + valor actual + barra de progreso relativa + delta %
- Barra de progreso: ancho proporcional al canal con más seguidores (100%)
- Delta coloreado: verde si positivo, rojo si negativo

**Nota de implementación:**  
Los datos vienen de la tabla `followers_snapshots` de la base de datos propia (snapshot diario). El componente debe soportar que algunos canales no tengan histórico (mostrar "Sin datos" en lugar de 0).

### 2.5 Tabla Top 5 / Bottom 5 posts

**Dos tablas side-by-side:**
- Izquierda: Top 5 (mayor engagement del periodo)
- Derecha: Bottom 5 (menor engagement del periodo)

**Columnas de cada tabla:**
| # | Canal | Publicación | Fecha | Alcance | Engagement | Tasa eng. |
|---|-------|-------------|-------|---------|------------|-----------|

**Especificaciones:**
- `#` → número de ranking con color verde (top) o rojo (bottom)
- `Canal` → badge con color e inicial del canal (IG, FB, TW, YT, TT)
- `Publicación` → texto truncado a 2 líneas, con tooltip al hover mostrando texto completo y miniatura si existe
- `Alcance` → número formateado (K/M)
- `Engagement` → número + mini barra de progreso relativa al máximo de la tabla
- `Tasa eng.` → engagement/alcance en %, coloreada si supera benchmark (>3% verde, <1% rojo)

**Filtros específicos de las tablas:**
- Filtro de canal (hereda el global pero puede sobreescribirse localmente)
- Filtro de tipo de contenido: Todo / Foto / Vídeo / Carrusel / Reel / Story
- Ordenación por columna clickable

**Paginación:** mostrar 5 registros, con opción "Ver todos" que abre modal o expande

### 2.6 Panel de audiencia

Tres cards en una fila:

**Card 1: Distribución por género**
- Gráfico de barras horizontales: Mujeres / Hombres / Otro
- Porcentaje + valor absoluto estimado

**Card 2: Distribución por edad**
- Gráfico de barras verticales: 13-17 / 18-24 / 25-34 / 35-44 / 45-54 / 55+
- Barras coloreadas con la intensidad del grupo dominante

**Card 3: Mejores horas para publicar**
- Heatmap 7×24 (días de semana × horas del día)
- Color más intenso = mayor engagement histórico en esa franja
- Tooltip con engagement medio al hover

---

## 3. Pestaña: Patrocinados

### 3.1 Layout general
```
[Filtros globales]
─────────────────────────────────────────────
[KPI Cards paid × 5]
─────────────────────────────────────────────
[Inversión por canal — 1/2] [Orgánico vs Paid — 1/2]
─────────────────────────────────────────────
[Tabla de campañas activas — ancho completo]
─────────────────────────────────────────────
[Evolución gasto semanal — 1/2] [CTR por canal — 1/2]
─────────────────────────────────────────────
```

### 3.2 KPI Cards paid

| Card | Métrica | Descripción |
|------|---------|-------------|
| 1 | Inversión total | Suma del gasto del periodo en todos los canales activos |
| 2 | Alcance pagado | Personas únicas impactadas por contenido patrocinado |
| 3 | Impresiones | Total de veces que se mostró el contenido |
| 4 | CPM medio | Coste por 1.000 impresiones |
| 5 | CTR medio | Click-through rate medio de todas las campañas |

Cada card incluye delta vs. periodo anterior con flecha y color.  
CPM: delta invertido (subida es negativa = rojo, bajada es positiva = verde).

### 3.3 Gráfico: Inversión y alcance por canal

**Tipo:** Gráfico combinado (barras + línea)  
- Barras: inversión en € por canal (eje Y izquierdo)
- Línea punteada: alcance en K por canal (eje Y derecho)
- Cada barra con el color del canal correspondiente
- Leyenda custom en HTML (no la default de Recharts)

### 3.4 Orgánico vs. Patrocinado

**Comparativa por canal:**
- Para cada canal activo: dos barras horizontales apiladas
- Barra gris: alcance orgánico
- Barra de color: alcance pagado
- Valores absolutos a la derecha
- Ratio paid/orgánico en tooltip

### 3.5 Tabla de campañas

**Columnas:**
| Canal | Nombre campaña | Estado | Inversión | Alcance | Impresiones | CPM | CTR | Acción |
|-------|----------------|--------|-----------|---------|-------------|-----|-----|--------|

**Estados con pills coloreados:**
- `activa` → verde
- `pausada` → ámbar
- `finalizada` → gris
- `borrador` → azul claro

**Ordenación por defecto:** CPM ascendente (las más eficientes arriba)

**Fila de totales** al final de la tabla con suma/media de columnas numéricas.

**Columna CTR:**
- Verde si CTR > 3%
- Gris si CTR entre 1-3%
- Rojo si CTR < 1%

**Acción:** icono de enlace externo → abre el Business Manager del canal correspondiente en nueva pestaña

### 3.6 Evolución del gasto

**Tipo:** Gráfico combinado (barras + línea)  
- Barras: gasto total del periodo (color morado con transparencia)
- Línea: alcance total (línea verde punteada, eje Y derecho)
- Eje X: semanas o meses según filtro global
- Responde al filtro de canal (si se filtra por IG, solo muestra gasto de IG)

### 3.7 CTR por canal

**Tipo:** Barras horizontales  
- Una barra por canal activo, con su color
- Ordenadas de mayor a menor CTR
- Línea de referencia vertical en el benchmark del sector (2.5%)
- Tooltip con número exacto y diferencia vs. benchmark

---

## 4. Pestaña: Clipping

> Esta pestaña mantiene su funcionalidad existente. El único cambio es:
> - Renombrarla de "Analytics" a "Clipping" en la navegación
> - Añadir los filtros globales de Marca y Canal en la parte superior
> - Los filtros afectan al contenido de clipping mostrado

---

## 5. Sistema de diseño

### 5.1 Principios visuales (inspiración Hootsuite/Metricool/Cyfe)

- **Limpio y denso:** mucha información visible sin scroll, sin aire innecesario
- **Datos primero:** los gráficos y números son los protagonistas, no la UI
- **Modo oscuro nativo:** soporte completo dark/light desde el inicio
- **Sin gradientes decorativos:** fondos planos, bordes finos (1px), sombras mínimas
- **Color con significado:** verde = positivo/activo, rojo = negativo/alerta, gris = neutral

### 5.2 Paleta de colores

```css
/* Acento principal */
--color-accent: #6C5CE7;          /* morado — acento de navegación y CTAs */
--color-accent-light: #A29BFE;    /* hover states */

/* Semánticos */
--color-positive: #00B894;        /* verde — deltas positivos */
--color-negative: #D63031;        /* rojo — deltas negativos */
--color-warning: #FDCB6E;         /* ámbar — advertencias */
--color-neutral: #636E72;         /* gris — sin cambio */

/* Canales sociales (constantes) */
--color-instagram: #E1306C;
--color-facebook: #1877F2;
--color-twitter: #1DA1F2;
--color-youtube: #FF0000;
--color-tiktok: #6C5CE7;          /* morado para evitar negro en dark mode */

/* Superficies (light) */
--surface-page: #F8F9FA;
--surface-card: #FFFFFF;
--surface-elevated: #FFFFFF;
--border-default: rgba(0,0,0,0.08);
--border-strong: rgba(0,0,0,0.15);

/* Superficies (dark) */
--surface-page-dark: #0D1117;
--surface-card-dark: #161B22;
--surface-elevated-dark: #21262D;
--border-default-dark: rgba(255,255,255,0.08);
--border-strong-dark: rgba(255,255,255,0.15);

/* Texto */
--text-primary: #1A1A2E;
--text-secondary: #636E72;
--text-tertiary: #B2BEC3;
--text-primary-dark: #E6EDF3;
--text-secondary-dark: #8B949E;
```

### 5.3 Tipografía

```css
font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;

/* Escala */
--text-xs: 11px;   /* badges, labels de ejes */
--text-sm: 12px;   /* labels secundarios, subtítulos */
--text-base: 13px; /* body, tablas */
--text-md: 14px;   /* labels de cards */
--text-lg: 16px;   /* títulos de sección */
--text-xl: 22px;   /* valores KPI */
--text-2xl: 28px;  /* valores KPI principales */

font-weight: 400 (body), 500 (labels), 600 (valores KPI, headings)
```

### 5.4 Componentes base

#### Card
```
background: var(--surface-card)
border: 1px solid var(--border-default)
border-radius: 12px
padding: 20px 24px
```

#### KPI Card
```
background: var(--surface-card)
border: 1px solid var(--border-default)
border-radius: 12px
padding: 16px 20px
min-height: 120px

Variante destacada (canal seleccionado):
border-left: 3px solid [color del canal]
```

#### Tabla
```
header: background var(--surface-page), font-size 11px uppercase letter-spacing 0.08em
rows: border-bottom 1px var(--border-default), hover background var(--surface-page)
alternating rows: NO (usar hover únicamente)
```

#### Badge de canal
```
width: 26px
height: 26px
border-radius: 7px
background: [color del canal con 15% opacidad]
color: [color del canal]
font-size: 10px
font-weight: 600
```

#### Pill de estado
```
padding: 3px 10px
border-radius: 20px
font-size: 11px
font-weight: 500
```

#### Delta badge
```
display: inline-flex
align-items: center
gap: 3px
font-size: 12px
font-weight: 500
color: positivo/negativo según valor
icono: ↑ / ↓ (SVG, no emoji)
```

### 5.5 Gráficos (Recharts)

**Configuración base para todos los gráficos:**
```jsx
<ResponsiveContainer width="100%" height="100%">
  <LineChart data={data} margin={{ top: 5, right: 5, bottom: 5, left: 0 }}>
    <CartesianGrid strokeDasharray="3 3" stroke="rgba(0,0,0,0.06)" vertical={false} />
    <XAxis 
      tick={{ fontSize: 11, fill: 'var(--text-secondary)' }} 
      axisLine={false} 
      tickLine={false} 
    />
    <YAxis 
      tick={{ fontSize: 11, fill: 'var(--text-secondary)' }} 
      axisLine={false} 
      tickLine={false}
      tickFormatter={formatNumber}
    />
    <Tooltip content={<CustomTooltip />} />
  </LineChart>
</ResponsiveContainer>
```

**Tooltip custom:**
```
background: var(--surface-elevated)
border: 1px solid var(--border-strong)
border-radius: 8px
padding: 10px 14px
box-shadow: 0 4px 12px rgba(0,0,0,0.12)
```

**Sparkline (mini gráfico en KPI cards):**
```jsx
<Sparklines data={weeklyData} width={80} height={24}>
  <SparklinesLine color={channelColor} style={{ strokeWidth: 1.5 }} />
</Sparklines>
```

---

## 6. Estructura de datos

### 6.1 Modelos principales

```typescript
// Marca
interface Brand {
  id: string;
  name: string;
  slug: string;
  channels: ChannelConfig[];
  createdAt: Date;
}

// Configuración de canal por marca
interface ChannelConfig {
  channel: 'instagram' | 'facebook' | 'twitter' | 'youtube' | 'tiktok';
  accountId: string;
  accountName: string;
  connected: boolean;
}

// Snapshot de seguidores (guardado diario)
interface FollowersSnapshot {
  id: string;
  brandId: string;
  channel: Channel;
  date: Date;           // fecha del snapshot
  week: number;         // semana ISO
  month: number;
  year: number;
  followers: number;
  followersGained: number;
  followersLost: number;
}

// Post orgánico
interface Post {
  id: string;
  brandId: string;
  channel: Channel;
  externalId: string;   // ID en la red social
  publishedAt: Date;
  week: number;
  month: number;
  year: number;
  type: 'photo' | 'video' | 'carousel' | 'reel' | 'story' | 'text';
  caption: string;
  thumbnailUrl?: string;
  metrics: PostMetrics;
}

interface PostMetrics {
  likes: number;
  comments: number;
  shares: number;
  saves: number;
  reach: number;
  impressions: number;
  engagement: number;         // suma de interacciones
  engagementRate: number;     // engagement / reach * 100
}

// Campaña patrocinada
interface PaidCampaign {
  id: string;
  brandId: string;
  channel: Channel;
  externalCampaignId: string; // ID en Business Manager
  name: string;
  status: 'active' | 'paused' | 'completed' | 'draft';
  startDate: Date;
  endDate?: Date;
  week: number;
  month: number;
  year: number;
  metrics: PaidMetrics;
}

interface PaidMetrics {
  spend: number;         // en euros
  reach: number;
  impressions: number;
  clicks: number;
  cpm: number;           // coste por mil impresiones
  ctr: number;           // click-through rate %
  cpc: number;           // coste por clic
}

// Demografía de audiencia
interface AudienceDemographics {
  brandId: string;
  channel: Channel;
  date: Date;
  gender: { female: number; male: number; other: number };  // porcentajes
  ageGroups: {
    '13-17': number; '18-24': number; '25-34': number;
    '35-44': number; '45-54': number; '55+': number;
  };
  // Heatmap de engagement: [díaSemana 0-6][hora 0-23] = engagement medio
  engagementHeatmap: number[][];
}
```

### 6.2 API endpoints necesarios

```
GET /api/brands                              → lista de marcas
GET /api/brands/:id/followers?week=14&year=2026    → histórico seguidores
GET /api/brands/:id/posts?week=14&year=2026&channel=instagram  → posts del periodo
GET /api/brands/:id/campaigns?week=14&year=2026    → campañas del periodo
GET /api/brands/:id/audience?channel=instagram     → demografía audiencia
GET /api/analytics/overview?brandId=...&week=14    → KPIs agregados
```

### 6.3 Lógica de comparativas temporales

```typescript
// Dado un periodo, calcular el anterior
function getPreviousPeriod(period: 'week' | 'month', value: number, year: number) {
  if (period === 'week') {
    return value === 1 
      ? { value: 52, year: year - 1 }
      : { value: value - 1, year };
  }
  return value === 1
    ? { value: 12, year: year - 1 }
    : { value: value - 1, year };
}

// Calcular delta porcentual
function calcDelta(current: number, previous: number): number {
  if (previous === 0) return 0;
  return ((current - previous) / previous) * 100;
}
```

---

## 7. Estados de la UI

### 7.1 Estado de carga
- Skeleton loaders para cards y gráficos (NO spinners globales)
- Cada componente carga independientemente
- Las KPI cards tienen skeleton de la misma altura que el contenido real

### 7.2 Sin datos
- Card con ilustración simple y texto explicativo
- Si no hay posts en el periodo: "No hay publicaciones en la semana X para esta marca/canal"
- Si no hay histórico de seguidores: "El seguimiento de seguidores comenzará a registrarse desde hoy"
- NO mostrar gráficos vacíos con ejes sin datos

### 7.3 Error de conexión API
- Inline error dentro del componente afectado (no bloquear toda la página)
- Botón "Reintentar" en cada componente con error
- Toast de notificación solo para errores críticos

### 7.4 Datos parciales
- Si solo algunos canales tienen datos, mostrar solo esos y añadir nota "Sin datos disponibles para: YouTube, TikTok"

---

## 8. Interacciones y UX

### 8.1 Filtros
- Cambio de filtro → actualización inmediata con loading skeleton
- Debounce de 300ms en el selector de marca (si es buscable)
- Los filtros se persisten en localStorage + URL params
- Botón "Limpiar filtros" visible cuando hay filtros activos

### 8.2 Tablas de posts
- Click en fila → panel lateral (drawer) con detalle del post
- El drawer muestra: miniatura, caption completo, métricas desglosadas, enlace a la red social
- Ordenación por columna con indicador visual (↑↓)
- El estado de ordenación se mantiene al cambiar filtros

### 8.3 Gráficos
- Hover en punto → tooltip flotante con todos los valores del periodo
- Click en leyenda → toggle de visibilidad de esa serie
- Gráficos responsivos: en pantallas < 768px, reducir a 2 canales visibles y añadir scroll horizontal

### 8.4 Exportación
- Botón "Exportar" en cada sección principal
- Opciones: CSV (datos crudos), PDF (vista actual del dashboard)
- El PDF debe respetar el diseño visual del dashboard

---

## 9. Estructura de carpetas sugerida

```
src/
├── components/
│   ├── layout/
│   │   ├── TopNav.tsx          ← navegación principal con las 3 pestañas
│   │   ├── GlobalFilters.tsx   ← barra de filtros persistente
│   │   └── AppShell.tsx        ← wrapper general
│   ├── shared/
│   │   ├── KPICard.tsx         ← card de métrica con sparkline y delta
│   │   ├── ChannelBadge.tsx    ← badge con color e inicial del canal
│   │   ├── DeltaBadge.tsx      ← indicador +/-% con color semántico
│   │   ├── StatusPill.tsx      ← pill de estado (activa/pausada/etc.)
│   │   ├── DataTable.tsx       ← tabla genérica ordenable
│   │   ├── EmptyState.tsx      ← estado sin datos
│   │   ├── SkeletonCard.tsx    ← skeleton loader
│   │   └── ExportButton.tsx    ← botón de exportación
│   ├── charts/
│   │   ├── EngagementChart.tsx ← líneas multi-canal con toggle
│   │   ├── FollowersPanel.tsx  ← barras horizontales de seguidores
│   │   ├── SpendChart.tsx      ← barras+línea para gasto paid
│   │   ├── CTRChart.tsx        ← barras horizontales CTR
│   │   ├── AudienceHeatmap.tsx ← heatmap 7×24 horas
│   │   └── Sparkline.tsx       ← mini gráfico para KPI cards
│   ├── marcas/
│   │   ├── MarcasPage.tsx      ← layout de la pestaña Marcas
│   │   ├── PostsTable.tsx      ← tabla top/bottom 5 posts
│   │   ├── PostDrawer.tsx      ← panel lateral de detalle de post
│   │   └── AudienceSection.tsx ← sección de demografía
│   └── patrocinados/
│       ├── PatrocinadosPage.tsx ← layout de la pestaña Patrocinados
│       ├── CampaignTable.tsx    ← tabla de campañas
│       └── OrgVsPaidChart.tsx   ← comparativa orgánico vs paid
├── hooks/
│   ├── useFilters.ts           ← estado global de filtros (Zustand o Context)
│   ├── useBrands.ts            ← fetch de marcas
│   ├── useFollowers.ts         ← fetch de histórico de seguidores
│   ├── usePosts.ts             ← fetch de posts con filtros
│   ├── useCampaigns.ts         ← fetch de campañas paid
│   └── useAudience.ts          ← fetch de demografía
├── utils/
│   ├── formatters.ts           ← fmtNum, fmtEur, fmtPct, calcDelta
│   ├── periods.ts              ← lógica de semanas/meses y comparativas
│   └── channelConfig.ts        ← colores, labels, iconos por canal
├── types/
│   └── index.ts                ← todos los interfaces TypeScript
└── pages/
    ├── DashboardPage.tsx       ← orquesta las 3 pestañas
    └── _app.tsx
```

---

## 10. Priorización de implementación

### Fase 1 — MVP (sprints 1-2)
1. Estructura de navegación con 3 pestañas
2. Barra de filtros globales funcional (marca, canal, periodo)
3. Pestaña Marcas: KPI cards + gráfico de engagement + histórico seguidores
4. Pestaña Marcas: tabla top 5 / bottom 5 posts con filtros de canal
5. Renombrar pestaña existente a "Clipping"

### Fase 2 — Patrocinados (sprint 3)
6. Pestaña Patrocinados: KPI cards paid
7. Tabla de campañas con estados
8. Gráfico inversión + alcance por canal
9. Comparativa orgánico vs. patrocinado
10. Gráfico CTR por canal

### Fase 3 — Audiencia + pulido (sprint 4)
11. Sección de audiencia: género, edad, heatmap de horas
12. Exportación a CSV y PDF
13. Panel lateral (drawer) de detalle de post
14. Persistencia de filtros en URL
15. Optimización de rendimiento y lazy loading de pestañas

### Fase 4 — Histórico y datos reales (sprint 5)
16. Implementar el job de snapshot diario de seguidores (cron job)
17. Conectar con APIs reales: Meta Graph API, TikTok API, YouTube Data API, Twitter API v2
18. Manejo de rate limits y caché de datos
19. Sistema de alertas cuando un KPI cae por debajo de umbral definido

---

## 11. Notas técnicas importantes

### Histórico de seguidores
Las APIs sociales NO proporcionan histórico retroactivo extenso:
- Instagram: máximo 30 días de histórico via API
- TikTok: sin histórico retroactivo
- YouTube: 28 días histórico
- Facebook: histórico variable según tipo de cuenta

**Solución:** implementar un cron job que ejecute cada día a las 00:00 UTC y guarde en base de datos el snapshot de seguidores de cada canal/marca. Esto debe arrancar el día 1 — sin este job, el histórico no existirá.

```sql
-- Tabla de snapshots
CREATE TABLE followers_snapshots (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  brand_id UUID REFERENCES brands(id),
  channel VARCHAR(20) NOT NULL,
  snapshot_date DATE NOT NULL,
  iso_week INTEGER NOT NULL,
  iso_year INTEGER NOT NULL,
  month INTEGER NOT NULL,
  followers INTEGER NOT NULL,
  followers_gained INTEGER DEFAULT 0,
  followers_lost INTEGER DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(brand_id, channel, snapshot_date)
);
```

### Gestión de rate limits de APIs
- Meta Graph API: 200 llamadas/hora por token
- Usar caché agresivo: datos de semanas pasadas no cambian → cachear 24h
- Datos de la semana actual → cachear 1h
- Implementar cola de peticiones con backoff exponencial

### Colores en modo oscuro
El color de TikTok en su identidad oficial es negro (#000000), que es invisible en dark mode. Usar `#6C5CE7` (morado) como color representativo de TikTok en toda la app para mantener legibilidad en ambos modos.

---

## 12. Checklist de entrega

- [ ] Navegación con 3 pestañas funcional
- [ ] Filtros globales: marca (dropdown buscable), canal (multi-select), periodo (semana/mes)
- [ ] Filtros persisten en URL y localStorage
- [ ] Pestaña Marcas: 5 KPI cards con sparkline y delta
- [ ] Pestaña Marcas: gráfico engagement (total + por canal con toggle)
- [ ] Pestaña Marcas: histórico de seguidores con barras y deltas
- [ ] Pestaña Marcas: tabla Top 5 posts (verde) con ranking, canal, métricas
- [ ] Pestaña Marcas: tabla Bottom 5 posts (rojo) con ranking, canal, métricas
- [ ] Tablas filtrables por canal y tipo de contenido, ordenables por columna
- [ ] Drawer de detalle de post al hacer click en una fila
- [ ] Pestaña Marcas: audiencia con género, edad y heatmap de horas
- [ ] Pestaña Patrocinados: 5 KPI cards paid con deltas
- [ ] Pestaña Patrocinados: gráfico inversión + alcance por canal
- [ ] Pestaña Patrocinados: comparativa orgánico vs. patrocinado
- [ ] Pestaña Patrocinados: tabla de campañas con estados y CTR coloreado
- [ ] Pestaña Patrocinados: evolución gasto semanal/mensual
- [ ] Pestaña Patrocinados: CTR por canal (barras horizontales)
- [ ] Skeleton loaders en todos los componentes async
- [ ] Estados de "sin datos" con mensajes descriptivos
- [ ] Errores inline sin bloquear la página
- [ ] Dark mode funcional en todos los componentes
- [ ] Diseño responsive (mínimo 1280px desktop, adaptaciones para 768px tablet)
- [ ] Exportación CSV por sección
- [ ] Job de snapshot de seguidores documentado e implementado
- [ ] Colores de canales consistentes en toda la app

