/**
 * DashboardPage.jsx
 * Analytics dashboard — Clipping | Marcas | Patrocinados
 * Phase 1 MVP: navigation + global filters + Marcas tab + Clipping integration
 */
import { useState, useEffect, useCallback, useMemo } from "react";
import {
  LineChart, Line, BarChart, Bar, ComposedChart,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from "recharts";

// ── Design tokens ─────────────────────────────────────────────────────────────
const T = {
  accent:    "#6C5CE7",
  accentLt:  "#A29BFE",
  positive:  "#00B894",
  negative:  "#D63031",
  warning:   "#FDCB6E",
  neutral:   "#636E72",
  pageBg:    "#F0F2F5",
  card:      "#FFFFFF",
  border:    "rgba(0,0,0,0.08)",
  borderSt:  "rgba(0,0,0,0.15)",
  text1:     "#1A1A2E",
  text2:     "#636E72",
  text3:     "#B2BEC3",
};

const CH = {
  instagram_post:  "#E1306C",
  instagram_story: "#C13584",
  facebook:        "#1877F2",
  youtube:         "#FF0000",
  youtube_short:   "#FF0000",
  tiktok:          "#6C5CE7",
  threads:         "#000000",
  web:             "#378ADD",
  x:               "#1DA1F2",
};

const CH_LABEL = {
  instagram_post:  "Instagram",
  instagram_story: "Stories",
  facebook:        "Facebook",
  youtube:         "YouTube",
  youtube_short:   "Shorts",
  tiktok:          "TikTok",
  threads:         "Threads",
  web:             "Web",
  x:               "X/Twitter",
};

const CH_INIT = {
  instagram_post: "IG", facebook: "FB", youtube: "YT",
  tiktok: "TT", threads: "TH", web: "WB", x: "X",
  instagram_story: "ST", youtube_short: "SH",
};

// ── Formatters ────────────────────────────────────────────────────────────────
function fmtNum(n) {
  if (!n && n !== 0) return "—";
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000)     return (n / 1_000).toFixed(1) + "K";
  return n.toLocaleString("es-ES");
}
function fmtPct(n) {
  if (n === null || n === undefined) return "—";
  return n.toFixed(1) + "%";
}
function fmtDate(d) {
  if (!d) return "—";
  return new Date(d).toLocaleDateString("es-ES", { day: "2-digit", month: "short" });
}

// ── Shared components ─────────────────────────────────────────────────────────

function ChannelBadge({ canal }) {
  const color = CH[canal] || T.neutral;
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", justifyContent: "center",
      width: 26, height: 26, borderRadius: 7,
      background: color + "26", color,
      fontSize: 10, fontWeight: 700, flexShrink: 0,
    }}>
      {CH_INIT[canal] || "?"}
    </span>
  );
}

function DeltaBadge({ current, previous, invert = false }) {
  if (previous === undefined || previous === null) return null;
  const delta = previous === 0 ? 0 : ((current - previous) / previous) * 100;
  const positive = invert ? delta < 0 : delta > 0;
  const zero = Math.abs(delta) < 0.05;
  const color = zero ? T.neutral : positive ? T.positive : T.negative;
  const arrow = zero ? "→" : positive ? "↑" : "↓";
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 2, fontSize: 11, fontWeight: 500, color }}>
      {arrow} {zero ? "0%" : `${positive ? "+" : ""}${delta.toFixed(1)}%`}
    </span>
  );
}

function StatusPill({ status }) {
  const map = {
    activa:     { bg: "#dcfce7", color: "#166534" },
    pausada:    { bg: "#fef3c7", color: "#92400e" },
    finalizada: { bg: "#f3f4f6", color: "#6b7280" },
    borrador:   { bg: "#dbeafe", color: "#1d4ed8" },
  };
  const st = map[status] || map.borrador;
  return (
    <span style={{
      padding: "3px 10px", borderRadius: 20, fontSize: 11, fontWeight: 500,
      background: st.bg, color: st.color,
    }}>{status}</span>
  );
}

function SkeletonCard({ h = 120 }) {
  return (
    <div style={{
      background: T.card, border: `1px solid ${T.border}`, borderRadius: 12,
      padding: "16px 20px", minHeight: h,
      animation: "pulse 1.5s ease-in-out infinite",
    }}>
      <div style={{ background: T.border, borderRadius: 6, height: 12, width: "60%", marginBottom: 12 }} />
      <div style={{ background: T.border, borderRadius: 6, height: 28, width: "40%", marginBottom: 8 }} />
      <div style={{ background: T.border, borderRadius: 6, height: 10, width: "30%" }} />
      <style>{`@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.5} }`}</style>
    </div>
  );
}

function EmptyState({ title, subtitle }) {
  return (
    <div style={{
      display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
      padding: "48px 24px", color: T.text3, gap: 8, textAlign: "center",
    }}>
      <div style={{ fontSize: 36 }}>📊</div>
      <div style={{ fontSize: 14, fontWeight: 600, color: T.text2 }}>{title}</div>
      {subtitle && <div style={{ fontSize: 12 }}>{subtitle}</div>}
    </div>
  );
}

// Custom tooltip for recharts
function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div style={{
      background: T.card, border: `1px solid ${T.borderSt}`,
      borderRadius: 8, padding: "10px 14px",
      boxShadow: "0 4px 12px rgba(0,0,0,0.12)", fontSize: 12,
    }}>
      <div style={{ fontWeight: 600, marginBottom: 6, color: T.text1 }}>{label}</div>
      {payload.map((p, i) => (
        <div key={i} style={{ display: "flex", alignItems: "center", gap: 6, color: p.color, marginBottom: 2 }}>
          <span style={{ width: 8, height: 8, borderRadius: "50%", background: p.color, flexShrink: 0 }} />
          <span style={{ color: T.text2 }}>{p.name}:</span>
          <span style={{ fontWeight: 600 }}>{fmtNum(p.value)}</span>
        </div>
      ))}
    </div>
  );
}

// ── KPI Card ──────────────────────────────────────────────────────────────────
function KPICard({ canal, label, value, prev, color, unit = "" }) {
  return (
    <div style={{
      background: T.card,
      border: `1px solid ${T.border}`,
      borderLeft: `3px solid ${color}`,
      borderRadius: 12,
      padding: "16px 20px",
      minHeight: 110,
      display: "flex", flexDirection: "column", gap: 4,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <ChannelBadge canal={canal} />
        <span style={{ fontSize: 11, fontWeight: 500, color: T.text2 }}>{CH_LABEL[canal] || canal}</span>
      </div>
      <div style={{ fontSize: 26, fontWeight: 700, color: T.text1, lineHeight: 1.2, marginTop: 6 }}>
        {fmtNum(value)}{unit}
      </div>
      <div style={{ fontSize: 11, color: T.text2 }}>{label}</div>
      <DeltaBadge current={value} previous={prev} />
    </div>
  );
}

// ── Engagement Chart (Recharts LineChart) ─────────────────────────────────────
function EngagementChart({ semanal }) {
  const [mode, setMode] = useState("total"); // total | por_canal
  const [hidden, setHidden] = useState({});

  if (!semanal?.semanas?.length) return <EmptyState title="Sin datos de evolución" subtitle="No hay historial semanal para este periodo" />;

  const { semanas, series } = semanal;

  const data = semanas.map((s, i) => {
    const obj = { semana: s.replace(/\d{4}-/, "").replace("W", "S") };
    let total = 0;
    series.forEach(sr => { obj[sr.canal] = sr.data[i] || 0; total += sr.data[i] || 0; });
    obj._total = total;
    return obj;
  });

  const lineStyles = ["", "5 5", "2 4", "10 3 3 3"];

  return (
    <div>
      <div style={{ display: "flex", gap: 4, marginBottom: 12 }}>
        {["total", "por_canal"].map(m => (
          <button key={m} onClick={() => setMode(m)} style={{
            padding: "4px 12px", borderRadius: 20, border: `1px solid ${mode === m ? T.accent : T.border}`,
            background: mode === m ? T.accent : "transparent",
            color: mode === m ? "#fff" : T.text2,
            fontSize: 11, fontWeight: 500, cursor: "pointer",
          }}>{m === "total" ? "Total" : "Por canal"}</button>
        ))}
      </div>
      <ResponsiveContainer width="100%" height={220}>
        <LineChart data={data} margin={{ top: 5, right: 5, bottom: 5, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(0,0,0,0.06)" vertical={false} />
          <XAxis dataKey="semana" tick={{ fontSize: 11, fill: T.text2 }} axisLine={false} tickLine={false} />
          <YAxis tick={{ fontSize: 11, fill: T.text2 }} axisLine={false} tickLine={false} tickFormatter={fmtNum} width={40} />
          <Tooltip content={<CustomTooltip />} />
          {mode === "total" ? (
            <Line type="monotone" dataKey="_total" name="Total" stroke={T.accent} strokeWidth={2} dot={false} />
          ) : (
            series.map((sr, i) => (
              !hidden[sr.canal] && (
                <Line key={sr.canal} type="monotone" dataKey={sr.canal}
                  name={CH_LABEL[sr.canal] || sr.canal}
                  stroke={CH[sr.canal] || "#ccc"} strokeWidth={2}
                  strokeDasharray={lineStyles[i % lineStyles.length]}
                  dot={false} />
              )
            ))
          )}
        </LineChart>
      </ResponsiveContainer>
      {mode === "por_canal" && (
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginTop: 8 }}>
          {series.map(sr => (
            <div key={sr.canal} onClick={() => setHidden(h => ({ ...h, [sr.canal]: !h[sr.canal] }))}
              style={{ display: "flex", alignItems: "center", gap: 4, cursor: "pointer",
                opacity: hidden[sr.canal] ? 0.35 : 1 }}>
              <span style={{ width: 10, height: 2, background: CH[sr.canal] || "#ccc", display: "block", borderRadius: 1 }} />
              <span style={{ fontSize: 11, color: T.text2 }}>{CH_LABEL[sr.canal] || sr.canal}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Followers Panel (placeholder — tabla followers_snapshots no existe aún) ────
function FollowersPanel({ kpis }) {
  const canales = Object.entries(kpis || {});
  if (!canales.length) return <EmptyState title="Sin datos" />;

  const maxReach = Math.max(...canales.map(([, v]) => v.reach || 0), 1);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {canales
        .filter(([, v]) => v.reach > 0)
        .sort(([, a], [, b]) => b.reach - a.reach)
        .map(([canal, v]) => (
          <div key={canal}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <ChannelBadge canal={canal} />
                <span style={{ fontSize: 12, fontWeight: 500, color: T.text1 }}>{CH_LABEL[canal] || canal}</span>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ fontSize: 13, fontWeight: 700, color: T.text1 }}>{fmtNum(v.reach)}</span>
                <span style={{ fontSize: 11, color: T.text2 }}>reach</span>
              </div>
            </div>
            <div style={{ background: T.border, borderRadius: 4, height: 6, overflow: "hidden" }}>
              <div style={{
                height: "100%",
                width: `${(v.reach / maxReach) * 100}%`,
                background: CH[canal] || T.accent,
                borderRadius: 4,
                transition: "width .4s ease",
              }} />
            </div>
            <div style={{ fontSize: 11, color: T.text2, marginTop: 3 }}>
              {v.publicaciones} publicaciones · {fmtNum(v.likes + v.comments + v.shares)} interacciones
            </div>
          </div>
        ))}
    </div>
  );
}

// ── Top/Bottom Posts Table ────────────────────────────────────────────────────
function PostsTable({ posts = [], variant = "top" }) {
  const accent = variant === "top" ? T.positive : T.negative;
  const maxEng = Math.max(...posts.map(p => p.engagement || 0), 1);

  if (!posts.length) return <EmptyState title={`Sin publicaciones`} subtitle="No hay datos para este periodo" />;

  return (
    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
      <thead>
        <tr>
          {["#", "Canal", "Publicación", "Fecha", "Alcance", "Engagement", "Tasa"].map(h => (
            <th key={h} style={{
              padding: "8px 10px", textAlign: "left", fontSize: 10,
              fontWeight: 600, color: T.text2, textTransform: "uppercase",
              letterSpacing: "0.06em", borderBottom: `1px solid ${T.border}`,
              background: T.pageBg,
            }}>{h}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {posts.map((p, i) => (
          <tr key={p.id} style={{ borderBottom: `1px solid ${T.border}` }}
            onMouseEnter={e => e.currentTarget.style.background = T.pageBg}
            onMouseLeave={e => e.currentTarget.style.background = ""}>
            <td style={{ padding: "10px 10px", width: 28 }}>
              <span style={{
                display: "inline-flex", alignItems: "center", justifyContent: "center",
                width: 22, height: 22, borderRadius: 6,
                background: accent + "20", color: accent, fontSize: 10, fontWeight: 700,
              }}>{i + 1}</span>
            </td>
            <td style={{ padding: "10px 10px" }}>
              <ChannelBadge canal={p.canal} />
            </td>
            <td style={{ padding: "10px 10px", maxWidth: 200 }}>
              <div style={{
                overflow: "hidden", display: "-webkit-box",
                WebkitLineClamp: 2, WebkitBoxOrient: "vertical",
                color: T.text1, lineHeight: 1.4,
              }} title={p.texto || p.titulo}>
                {p.texto ? p.texto.slice(0, 120) : p.titulo || "—"}
              </div>
              {p.marca && <div style={{ fontSize: 10, color: T.text3, marginTop: 2 }}>{p.marca}</div>}
            </td>
            <td style={{ padding: "10px 10px", whiteSpace: "nowrap", color: T.text2 }}>
              {fmtDate(p.fecha_publicacion)}
            </td>
            <td style={{ padding: "10px 10px", fontWeight: 600 }}>
              {fmtNum(p.reach)}
            </td>
            <td style={{ padding: "10px 10px", minWidth: 100 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span style={{ fontWeight: 600 }}>{fmtNum(p.engagement)}</span>
                <div style={{ flex: 1, background: T.border, borderRadius: 3, height: 5, overflow: "hidden", minWidth: 40 }}>
                  <div style={{
                    height: "100%", borderRadius: 3,
                    width: `${(p.engagement / maxEng) * 100}%`,
                    background: accent,
                  }} />
                </div>
              </div>
            </td>
            <td style={{ padding: "10px 10px" }}>
              <span style={{
                color: p.engagement_rate > 3 ? T.positive : p.engagement_rate < 1 ? T.negative : T.text2,
                fontWeight: 600,
              }}>
                {fmtPct(p.engagement_rate)}
              </span>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// ── Global Filters ────────────────────────────────────────────────────────────
const PERIODOS = [
  { value: "1m", label: "1 mes" },
  { value: "3m", label: "3 meses" },
  { value: "6m", label: "6 meses" },
  { value: "1y", label: "1 año" },
];

const CANALES_OPTS = [
  { value: "instagram_post", label: "Instagram" },
  { value: "facebook",       label: "Facebook" },
  { value: "youtube",        label: "YouTube" },
  { value: "tiktok",         label: "TikTok" },
  { value: "threads",        label: "Threads" },
  { value: "web",            label: "Web" },
  { value: "youtube_short",  label: "Shorts" },
];

function GlobalFilters({ filtros, onChange, marcas }) {
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap",
      padding: "10px 0 14px", borderBottom: `1px solid ${T.border}`, marginBottom: 20,
    }}>
      {/* Marca */}
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <span style={{ fontSize: 11, color: T.text2, fontWeight: 500 }}>Marca</span>
        <select value={filtros.marca_id || ""} onChange={e => onChange({ ...filtros, marca_id: e.target.value || null })}
          style={{ fontSize: 12, border: `1px solid ${T.border}`, borderRadius: 8, padding: "5px 10px", background: T.card, color: T.text1, cursor: "pointer" }}>
          <option value="">Todas las marcas</option>
          {marcas.map(m => <option key={m.id} value={m.id}>{m.nombre_canonico}</option>)}
        </select>
      </div>

      {/* Canales multi-select chips */}
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <span style={{ fontSize: 11, color: T.text2, fontWeight: 500 }}>Canales</span>
        <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
          {CANALES_OPTS.map(c => {
            const active = !filtros.canal || filtros.canal === c.value;
            return (
              <button key={c.value}
                onClick={() => onChange({ ...filtros, canal: filtros.canal === c.value ? null : c.value })}
                style={{
                  padding: "3px 10px", borderRadius: 20, fontSize: 11, fontWeight: 500, cursor: "pointer",
                  border: `1px solid ${active ? CH[c.value] : T.border}`,
                  background: filtros.canal === c.value ? CH[c.value] + "20" : "transparent",
                  color: filtros.canal === c.value ? CH[c.value] : T.text2,
                  transition: "all .15s",
                }}>{c.label}</button>
            );
          })}
        </div>
      </div>

      {/* Periodo */}
      <div style={{ display: "flex", alignItems: "center", gap: 4, marginLeft: "auto" }}>
        {PERIODOS.map(p => (
          <button key={p.value} onClick={() => onChange({ ...filtros, periodo: p.value })}
            style={{
              padding: "4px 12px", borderRadius: 20, fontSize: 11, fontWeight: 500, cursor: "pointer",
              border: `1px solid ${filtros.periodo === p.value ? T.accent : T.border}`,
              background: filtros.periodo === p.value ? T.accent : "transparent",
              color: filtros.periodo === p.value ? "#fff" : T.text2,
            }}>{p.label}</button>
        ))}
      </div>
    </div>
  );
}

// ── Marcas Tab ────────────────────────────────────────────────────────────────
function MarcasTab({ slug, api, filtros, marcas }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    const p = new URLSearchParams({ periodo: filtros.periodo });
    if (filtros.marca_id) p.set("marca_id", filtros.marca_id);
    if (filtros.canal)    p.set("canal", filtros.canal);
    api("GET", `/medios/${slug}/analytics/dashboard?${p}`)
      .then(setData)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, [slug, filtros, api]);

  useEffect(() => { load(); }, [load]);

  const kpis = data?.kpis || {};
  const kpisPrev = data?.kpis_periodo_anterior || {};
  const canalesActivos = Object.keys(kpis).filter(c => kpis[c].reach > 0);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      {/* KPI Cards */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(170px, 1fr))", gap: 12 }}>
        {loading ? (
          Array(4).fill(0).map((_, i) => <SkeletonCard key={i} />)
        ) : error ? (
          <div style={{ gridColumn: "1/-1", color: T.negative, padding: 16 }}>
            Error: {error}{" "}
            <button onClick={load} style={{ color: T.accent, cursor: "pointer", border: "none", background: "none", textDecoration: "underline" }}>Reintentar</button>
          </div>
        ) : canalesActivos.length === 0 ? (
          <div style={{ gridColumn: "1/-1" }}>
            <EmptyState title="Sin publicaciones en este periodo" subtitle="Prueba con un rango de fechas más amplio" />
          </div>
        ) : (
          canalesActivos.map(canal => (
            <KPICard key={canal} canal={canal}
              label="Reach total" value={kpis[canal].reach}
              prev={kpisPrev[canal]?.reach} color={CH[canal] || T.accent} />
          ))
        )}
      </div>

      {/* Charts row */}
      {data && (
        <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 16 }}>
          {/* Engagement evolution */}
          <div style={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: 12, padding: "20px 24px" }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: T.text1, marginBottom: 4 }}>Evolución del engagement</div>
            <div style={{ fontSize: 11, color: T.text2, marginBottom: 12 }}>Interacciones semanales por canal</div>
            <EngagementChart semanal={data.semanal} />
          </div>

          {/* Reach por canal */}
          <div style={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: 12, padding: "20px 24px" }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: T.text1, marginBottom: 4 }}>Reach por canal</div>
            <div style={{ fontSize: 11, color: T.text2, marginBottom: 16 }}>Distribución del periodo</div>
            <FollowersPanel kpis={kpis} />
          </div>
        </div>
      )}

      {/* Top / Bottom posts */}
      {data && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
          {/* Top 5 */}
          <div style={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: 12, overflow: "hidden" }}>
            <div style={{ padding: "16px 20px 0", display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ width: 8, height: 8, borderRadius: "50%", background: T.positive, display: "block" }} />
              <span style={{ fontSize: 13, fontWeight: 600, color: T.text1 }}>Top 5 publicaciones</span>
            </div>
            <PostsTable posts={data.top_posts || []} variant="top" />
          </div>

          {/* Bottom 5 */}
          <div style={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: 12, overflow: "hidden" }}>
            <div style={{ padding: "16px 20px 0", display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ width: 8, height: 8, borderRadius: "50%", background: T.negative, display: "block" }} />
              <span style={{ fontSize: 13, fontWeight: 600, color: T.text1 }}>Bottom 5 publicaciones</span>
            </div>
            <PostsTable posts={data.bottom_posts || []} variant="bottom" />
          </div>
        </div>
      )}

      {/* Engagement KPIs secondary row */}
      {data && canalesActivos.length > 0 && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 12 }}>
          {canalesActivos.map(canal => {
            const v = kpis[canal];
            const vp = kpisPrev[canal];
            const eng = (v.likes || 0) + (v.comments || 0) + (v.shares || 0);
            const engPrev = vp ? (vp.likes || 0) + (vp.comments || 0) + (vp.shares || 0) : undefined;
            return (
              <div key={canal} style={{
                background: T.card, border: `1px solid ${T.border}`, borderRadius: 12,
                padding: "14px 18px", display: "flex", flexDirection: "column", gap: 6,
              }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <ChannelBadge canal={canal} />
                  <span style={{ fontSize: 11, fontWeight: 500, color: T.text2 }}>{CH_LABEL[canal]}</span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12 }}>
                  <span style={{ color: T.text2 }}>Likes</span>
                  <span style={{ fontWeight: 600 }}>{fmtNum(v.likes)}</span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12 }}>
                  <span style={{ color: T.text2 }}>Comentarios</span>
                  <span style={{ fontWeight: 600 }}>{fmtNum(v.comments)}</span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12 }}>
                  <span style={{ color: T.text2 }}>Shares</span>
                  <span style={{ fontWeight: 600 }}>{fmtNum(v.shares)}</span>
                </div>
                <div style={{
                  display: "flex", justifyContent: "space-between", fontSize: 12,
                  paddingTop: 6, borderTop: `1px solid ${T.border}`, marginTop: 2,
                }}>
                  <span style={{ color: T.text2, fontWeight: 500 }}>Engagement</span>
                  <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <span style={{ fontWeight: 700, color: T.accent }}>{fmtNum(eng)}</span>
                    <DeltaBadge current={eng} previous={engPrev} />
                  </div>
                </div>
                <div style={{ fontSize: 10, color: T.text3 }}>{v.publicaciones} publicaciones</div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Patrocinados Tab (Phase 2 placeholder) ────────────────────────────────────
function PatrocinadosTab({ slug, api, filtros }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    const p = new URLSearchParams({ periodo: filtros.periodo });
    if (filtros.canal) p.set("canal", filtros.canal);
    api("GET", `/medios/${slug}/analytics/resumen?${p}`)
      .then(d => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, [slug, filtros, api]);

  const inversion = data?.inversion_total || 0;
  const reachPagado = data?.reach_pagado_total || 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      {/* KPI paid cards */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: 12 }}>
        {loading ? Array(3).fill(0).map((_, i) => <SkeletonCard key={i} />) : (
          <>
            <div style={cardStyle("#6C5CE7")}>
              <div style={{ fontSize: 11, fontWeight: 500, color: T.text2 }}>Inversión total</div>
              <div style={{ fontSize: 26, fontWeight: 700, color: T.text1, margin: "6px 0" }}>
                {inversion ? inversion.toLocaleString("es-ES", { minimumFractionDigits: 2 }) + " €" : "—"}
              </div>
              <div style={{ fontSize: 11, color: T.text2 }}>gasto del periodo</div>
            </div>
            <div style={cardStyle("#E1306C")}>
              <div style={{ fontSize: 11, fontWeight: 500, color: T.text2 }}>Alcance pagado</div>
              <div style={{ fontSize: 26, fontWeight: 700, color: T.text1, margin: "6px 0" }}>{fmtNum(reachPagado)}</div>
              <div style={{ fontSize: 11, color: T.text2 }}>personas impactadas</div>
            </div>
            <div style={cardStyle(T.neutral)}>
              <div style={{ fontSize: 11, fontWeight: 500, color: T.text2 }}>CPM medio</div>
              <div style={{ fontSize: 26, fontWeight: 700, color: T.text1, margin: "6px 0" }}>
                {reachPagado > 0 ? (inversion / reachPagado * 1000).toFixed(2) + " €" : "—"}
              </div>
              <div style={{ fontSize: 11, color: T.text2 }}>coste por 1.000 impresiones</div>
            </div>
          </>
        )}
      </div>

      {/* Top marcas por reach */}
      {data?.top_marcas?.length > 0 && (
        <div style={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: 12, padding: "20px 24px" }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: T.text1, marginBottom: 16 }}>Top marcas por reach</div>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={data.top_marcas} layout="vertical" margin={{ left: 80, right: 20, top: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(0,0,0,0.06)" horizontal={false} />
              <XAxis type="number" tick={{ fontSize: 11, fill: T.text2 }} axisLine={false} tickLine={false} tickFormatter={fmtNum} />
              <YAxis type="category" dataKey="nombre" tick={{ fontSize: 11, fill: T.text1 }} axisLine={false} tickLine={false} width={80} />
              <Tooltip content={<CustomTooltip />} />
              <Bar dataKey="reach" name="Reach" fill={T.accent} radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      <div style={{
        background: T.card, border: `1px dashed ${T.border}`, borderRadius: 12,
        padding: 32, textAlign: "center", color: T.text3,
      }}>
        <div style={{ fontSize: 24, marginBottom: 8 }}>🚧</div>
        <div style={{ fontSize: 13, fontWeight: 600, color: T.text2 }}>Módulo en desarrollo</div>
        <div style={{ fontSize: 12, marginTop: 4 }}>
          La tabla de campañas, gráficos de CTR y comparativa orgánico/paid llegan en la Fase 2.
        </div>
      </div>
    </div>
  );
}

function cardStyle(accentColor) {
  return {
    background: T.card,
    border: `1px solid ${T.border}`,
    borderLeft: `3px solid ${accentColor}`,
    borderRadius: 12,
    padding: "16px 20px",
    minHeight: 100,
  };
}

// ── Main DashboardPage ────────────────────────────────────────────────────────
export default function DashboardPage({ slug, api, PublicacionesPage }) {
  const [tab, setTab] = useState("clipping");
  const [marcas, setMarcas] = useState([]);
  const [filtros, setFiltros] = useState({ periodo: "3m", marca_id: null, canal: null });

  useEffect(() => {
    api("GET", `/medios/${slug}/marcas`).then(setMarcas).catch(() => {});
  }, [slug, api]);

  const TABS = [
    { key: "clipping",      label: "Clipping" },
    { key: "marcas",        label: "Marcas" },
    { key: "patrocinados",  label: "Patrocinados" },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      {/* Top tab navigation */}
      <div style={{
        display: "flex", gap: 0, borderBottom: `2px solid ${T.border}`,
        marginBottom: 0, flexShrink: 0,
      }}>
        {TABS.map(t => (
          <button key={t.key} onClick={() => setTab(t.key)} style={{
            padding: "10px 22px", border: "none", cursor: "pointer",
            background: "transparent", fontSize: 13, fontWeight: tab === t.key ? 600 : 400,
            color: tab === t.key ? T.accent : T.text2,
            borderBottom: `2px solid ${tab === t.key ? T.accent : "transparent"}`,
            marginBottom: -2, transition: "all .15s",
          }}>{t.label}</button>
        ))}
      </div>

      {/* Global filters — visible except in clipping where the page has its own */}
      {tab !== "clipping" && (
        <GlobalFilters filtros={filtros} onChange={setFiltros} marcas={marcas} />
      )}

      {/* Tab content */}
      <div style={{ flex: 1, overflowY: "auto", paddingTop: tab === "clipping" ? 0 : 4 }}>
        {tab === "clipping" && <PublicacionesPage slug={slug} api={api} />}
        {tab === "marcas"   && <MarcasTab slug={slug} api={api} filtros={filtros} marcas={marcas} />}
        {tab === "patrocinados" && <PatrocinadosTab slug={slug} api={api} filtros={filtros} />}
      </div>
    </div>
  );
}
