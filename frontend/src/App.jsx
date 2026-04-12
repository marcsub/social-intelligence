import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { Chart, registerables } from "chart.js";
Chart.register(...registerables);

const API_BASE = import.meta.env.PROD ? "/social/api" : "/api";

// ── API helpers ───────────────────────────────────────────────────────────────
function useAuth() {
  const [token, setToken] = useState(() => localStorage.getItem("si_token"));
  const login = async (username, password) => {
    const r = await fetch("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: `username=${encodeURIComponent(username)}&password=${encodeURIComponent(password)}`,
    });
    if (!r.ok) throw new Error("Credenciales incorrectas");
    const { access_token } = await r.json();
    localStorage.setItem("si_token", access_token);
    setToken(access_token);
  };
  const logout = () => { localStorage.removeItem("si_token"); setToken(null); };
  return { token, login, logout };
}

function useApi(token) {
  const call = useCallback(async (method, path, body) => {
    const r = await fetch(`${API_BASE}${path}`, {
      method,
      headers: {
        "Authorization": `Bearer ${token}`,
        ...(body ? { "Content-Type": "application/json" } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
    });
    if (r.status === 204) return null;
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: r.statusText }));
      throw new Error(err.detail || "Error en la petición");
    }
    return r.json();
  }, [token]);
  return call;
}

// ── Constants ─────────────────────────────────────────────────────────────────
const CANAL_COLORS = {
  web: "#378ADD",
  instagram_post: "#D4537E",
  instagram_story: "#C13584",
  facebook: "#185FA5",
  youtube: "#E24B4A",
  youtube_short: "#E24B4A",
  x: "#1DA1F2",
  tiktok: "#010101",
  reel: "#9B59B6",
  threads: "#000000",
};
const CANAL_LABELS = {
  web: "Web",
  instagram_post: "Instagram",
  instagram_story: "Stories",
  facebook: "Facebook",
  youtube: "YouTube",
  youtube_short: "Shorts",
  x: "X / Twitter",
  tiktok: "TikTok",
  reel: "Reels",
  threads: "Threads",
};
const ESTADO_STYLE = {
  pendiente:  { background: "#fff3cd", color: "#856404" },
  actualizado:{ background: "#d4edda", color: "#155724" },
  error:      { background: "#f8d7da", color: "#721c24" },
  revisar:    { background: "#ffe0b2", color: "#e65100" },
  fijo:       { background: "#e2e3e5", color: "#6c757d" },
};
const ESTADO_MARCA_STYLE = {
  estimated:  { background: "#dbeafe", color: "#1d4ed8" },
  to_review:  { background: "#fef9c3", color: "#854d0e" },
  ok:         { background: "#dcfce7", color: "#166534" },
};
const ESTADO_MARCA_LABEL = {
  estimated: "Estimated",
  to_review: "To review",
  ok:        "Ok",
};

// ── Helpers ───────────────────────────────────────────────────────────────────
function fmtNum(n) {
  if (!n && n !== 0) return "—";
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000)     return (n / 1_000).toFixed(1) + "K";
  return n.toLocaleString("es-ES");
}
function fmtDate(d) {
  if (!d) return "—";
  return new Date(d).toLocaleDateString("es-ES", { day: "2-digit", month: "short", year: "numeric" });
}
function fmtMetric(n) {
  // Para reach/likes: 0 o null → "—", >0 → formateado
  if (!n || n === 0) return "—";
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000)     return (n / 1_000).toFixed(1) + "K";
  return n.toLocaleString("es-ES");
}
function fmtEuro(n) {
  if (!n && n !== 0) return "—";
  return n.toLocaleString("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + " €";
}
function getProximoLunes() {
  const d = new Date();
  const dow = d.getDay(); // 0=dom, 1=lun...
  const daysUntilMonday = dow === 1 ? 7 : (8 - dow) % 7 || 7;
  d.setDate(d.getDate() + daysUntilMonday);
  return d.toLocaleDateString("es-ES", { weekday:"short", day:"numeric", month:"short" });
}

// ── Styles ────────────────────────────────────────────────────────────────────
const s = {
  app: { display:"flex", minHeight:"100vh", fontFamily:"system-ui,sans-serif", fontSize:14, color:"#1a1a2e", background:"#f5f6fa" },
  sidebar: { width:220, background:"#1a1a2e", color:"#fff", display:"flex", flexDirection:"column", padding:"24px 0", flexShrink:0 },
  sidebarTitle: { padding:"0 20px 20px", fontSize:15, fontWeight:600, borderBottom:"1px solid #2d2d4e", marginBottom:8 },
  sidebarSub: { fontSize:11, color:"#888", marginBottom:4 },
  navItem: (active) => ({ padding:"9px 20px", cursor:"pointer", background: active ? "#2d2d4e" : "transparent", color: active ? "#fff" : "#aaa", borderLeft: active ? "3px solid #6c63ff" : "3px solid transparent", fontSize:13, transition:"all .15s" }),
  navSubItem: (active) => ({ padding:"7px 20px 7px 32px", cursor:"pointer", background: active ? "#2d2d4e" : "transparent", color: active ? "#ccc" : "#777", borderLeft: active ? "3px solid #6c63ff" : "3px solid transparent", fontSize:12, transition:"all .15s" }),
  navGroup: { padding:"8px 20px 4px", fontSize:10, color:"#555", textTransform:"uppercase", letterSpacing:"0.08em", fontWeight:600 },
  main: { flex:1, padding:32, overflowY:"auto" },
  card: { background:"#fff", borderRadius:10, padding:24, marginBottom:20, boxShadow:"0 1px 3px rgba(0,0,0,.07)" },
  h2: { margin:"0 0 20px", fontSize:18, fontWeight:600, color:"#1a1a2e" },
  h3: { margin:"0 0 14px", fontSize:15, fontWeight:600, color:"#1a1a2e" },
  row: { display:"flex", gap:12, alignItems:"center", marginBottom:12, flexWrap:"wrap" },
  input: { flex:1, minWidth:160, padding:"8px 12px", border:"1px solid #ddd", borderRadius:7, fontSize:13, outline:"none" },
  select: { padding:"8px 12px", border:"1px solid #ddd", borderRadius:7, fontSize:13, background:"#fff", outline:"none" },
  textarea: { width:"100%", padding:"8px 12px", border:"1px solid #ddd", borderRadius:7, fontSize:13, minHeight:60, resize:"vertical", boxSizing:"border-box" },
  btn: (variant="primary") => ({
    padding:"8px 16px", borderRadius:7, border:"none", cursor:"pointer", fontSize:13, fontWeight:500,
    background: variant==="primary" ? "#6c63ff" : variant==="danger" ? "#e24b4a" : variant==="success" ? "#1d9e75" : variant==="warning" ? "#f59e0b" : "#f0f0f0",
    color: variant==="ghost" ? "#555" : "#fff",
    opacity: 1,
  }),
  badge: (v) => ({ display:"inline-block", padding:"2px 8px", borderRadius:20, fontSize:11, fontWeight:500,
    background: v==="activa" ? "#d4edda" : "#f8d7da", color: v==="activa" ? "#155724" : "#721c24" }),
  table: { width:"100%", borderCollapse:"collapse" },
  th: { textAlign:"left", padding:"8px 12px", fontSize:11, color:"#888", borderBottom:"1px solid #eee", fontWeight:500, textTransform:"uppercase", letterSpacing:"0.05em" },
  td: { padding:"11px 12px", fontSize:13, borderBottom:"1px solid #f5f5f5", verticalAlign:"middle" },
  alert: (type) => ({ padding:"10px 14px", borderRadius:7, marginBottom:16, fontSize:13,
    background: type==="error" ? "#f8d7da" : "#d4edda", color: type==="error" ? "#721c24" : "#155724" }),
  tokenRow: { display:"flex", alignItems:"center", gap:8, padding:"8px 0", borderBottom:"1px solid #f5f5f5" },
  tag: { background:"#eee", borderRadius:4, padding:"1px 6px", fontSize:11, color:"#555" },
  kpiGrid: { display:"grid", gridTemplateColumns:"repeat(5,1fr)", gap:12, marginBottom:20 },
  kpiCard: { background:"#f8f9ff", borderRadius:10, padding:"16px 12px", textAlign:"center", border:"1px solid #e8eaf6" },
  chartBox: { background:"#fff", borderRadius:10, padding:20, boxShadow:"0 1px 3px rgba(0,0,0,.07)", marginBottom:16 },
  tabBar: { display:"flex", gap:4, marginBottom:20, borderBottom:"2px solid #eee", paddingBottom:0 },
  tabBtn: (active) => ({ padding:"8px 18px", border:"none", background:"transparent", cursor:"pointer", fontSize:13,
    fontWeight: active?600:400, color: active?"#6c63ff":"#888",
    borderBottom: active?"2px solid #6c63ff":"2px solid transparent", marginBottom:-2 }),
};

// ── Shared UI ─────────────────────────────────────────────────────────────────

function Alert({ msg, type="error", onClose }) {
  if (!msg) return null;
  return <div style={s.alert(type)}>{msg} {onClose && <span style={{float:"right",cursor:"pointer"}} onClick={onClose}>✕</span>}</div>;
}

function Modal({ title, onClose, children }) {
  return (
    <div style={{position:"fixed",inset:0,background:"rgba(0,0,0,.45)",display:"flex",alignItems:"center",justifyContent:"center",zIndex:1000}}>
      <div style={{background:"#fff",borderRadius:12,padding:28,width:520,maxWidth:"90vw",maxHeight:"80vh",overflowY:"auto",boxShadow:"0 8px 32px rgba(0,0,0,.2)"}}>
        <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:20}}>
          <strong style={{fontSize:16}}>{title}</strong>
          <button style={s.btn("ghost")} onClick={onClose}>✕</button>
        </div>
        {children}
      </div>
    </div>
  );
}

function PeriodSelector({ periodo, setPeriodo, fechaDesde, setFechaDesde, fechaHasta, setFechaHasta }) {
  return (
    <div style={{ display:"flex", gap:8, alignItems:"center", flexWrap:"wrap" }}>
      {[["3m","3 meses"],["6m","6 meses"],["12m","12 meses"],["custom","Personalizado"]].map(([v,l]) => (
        <button key={v} style={{ ...s.btn(periodo===v?"primary":"ghost"), padding:"6px 14px" }} onClick={() => setPeriodo(v)}>{l}</button>
      ))}
      {periodo === "custom" && (
        <>
          <input type="date" style={{ ...s.select, minWidth:130 }} value={fechaDesde} onChange={e => setFechaDesde(e.target.value)} />
          <span style={{color:"#888"}}>—</span>
          <input type="date" style={{ ...s.select, minWidth:130 }} value={fechaHasta} onChange={e => setFechaHasta(e.target.value)} />
        </>
      )}
    </div>
  );
}

function KpiCard({ label, value, color="#6c63ff" }) {
  return (
    <div style={s.kpiCard}>
      <div style={{ fontSize:22, fontWeight:700, color }}>{fmtNum(value)}</div>
      <div style={{ fontSize:11, color:"#888", marginTop:4 }}>{label}</div>
    </div>
  );
}

// ── Chart components ──────────────────────────────────────────────────────────

function ChartCanvas({ type, data, options = {}, height = 280 }) {
  const ref = useRef(null);
  const inst = useRef(null);
  const key = JSON.stringify({ type, data });

  useEffect(() => {
    if (!ref.current || !data) return;
    if (inst.current) { inst.current.destroy(); inst.current = null; }
    inst.current = new Chart(ref.current, {
      type,
      data,
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: "bottom" } }, ...options },
    });
    return () => { if (inst.current) { inst.current.destroy(); inst.current = null; } };
  }, [key]);

  return <div style={{ height, position:"relative" }}><canvas ref={ref} /></div>;
}

// ── Login ─────────────────────────────────────────────────────────────────────
function LoginPage({ onLogin }) {
  const [u, setU] = useState(""); const [p, setP] = useState(""); const [err, setErr] = useState("");
  const submit = async (e) => {
    e.preventDefault(); setErr("");
    try { await onLogin(u, p); } catch(ex) { setErr(ex.message); }
  };
  return (
    <div style={{display:"flex",alignItems:"center",justifyContent:"center",minHeight:"100vh",background:"#f5f6fa"}}>
      <div style={{...s.card,width:360,padding:36}}>
        <div style={{textAlign:"center",marginBottom:28}}>
          <div style={{fontSize:22,fontWeight:700,color:"#6c63ff"}}>Social Intelligence</div>
          <div style={{fontSize:13,color:"#888",marginTop:4}}>Panel de administración</div>
        </div>
        <Alert msg={err} />
        <form onSubmit={submit}>
          <div style={{marginBottom:12}}><input style={{...s.input,width:"100%",boxSizing:"border-box"}} placeholder="Usuario" value={u} onChange={e=>setU(e.target.value)} autoFocus /></div>
          <div style={{marginBottom:20}}><input style={{...s.input,width:"100%",boxSizing:"border-box"}} type="password" placeholder="Contraseña" value={p} onChange={e=>setP(e.target.value)} /></div>
          <button style={{...s.btn(),width:"100%",padding:"10px"}} type="submit">Entrar</button>
        </form>
      </div>
    </div>
  );
}

// ── Marcas / Agencias CRUD ────────────────────────────────────────────────────
function EntidadCRUD({ slug, tipo, api }) {
  const endpoint = `/medios/${slug}/${tipo}`;
  const label = tipo === "marcas" ? "marca" : "agencia";
  const [items, setItems] = useState([]);
  const [err, setErr] = useState("");
  const [ok, setOk] = useState("");
  const [modal, setModal] = useState(null);
  const [form, setForm] = useState({});

  const load = useCallback(async () => {
    try { setItems(await api("GET", endpoint)); } catch(ex) { setErr(ex.message); }
  }, [slug, tipo]);

  useEffect(() => { load(); }, [load]);

  const openNew = () => { setForm({ nombre_canonico:"", aliases:"", email_contacto:"", notas:"" }); setModal("new"); };
  const openEdit = (item) => { setForm({...item}); setModal(item); };
  const closeModal = () => { setModal(null); setForm({}); };

  const save = async () => {
    setErr(""); setOk("");
    try {
      if (modal === "new") {
        await api("POST", endpoint, form);
        setOk(`${label} creada`);
      } else {
        await api("PATCH", `${endpoint}/${modal.id}`, form);
        setOk(`${label} actualizada`);
      }
      await load(); closeModal();
    } catch(ex) { setErr(ex.message); }
  };

  const toggle = async (item) => {
    const nuevoEstado = item.estado === "activa" ? "inactiva" : "activa";
    try { await api("PATCH", `${endpoint}/${item.id}`, { estado: nuevoEstado }); await load(); }
    catch(ex) { setErr(ex.message); }
  };

  const destroy = async (item) => {
    if (!confirm(`¿Eliminar ${label} "${item.nombre_canonico}"? Esta acción no se puede deshacer.`)) return;
    try { await api("DELETE", `${endpoint}/${item.id}`); await load(); }
    catch(ex) { setErr(ex.message); }
  };

  const aliasField = tipo === "marcas" ? "agencias_habituales" : "marcas_habituales";
  const aliasLabel = tipo === "marcas" ? "Agencias habituales" : "Marcas habituales";

  return (
    <div>
      <Alert msg={err} type="error" onClose={() => setErr("")} />
      <Alert msg={ok} type="success" onClose={() => setOk("")} />
      <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:16}}>
        <span style={{color:"#888",fontSize:13}}>{items.length} {tipo}</span>
        <button style={s.btn()} onClick={openNew}>+ Nueva {label}</button>
      </div>
      <table style={s.table}>
        <thead><tr>
          <th style={s.th}>Nombre</th>
          <th style={s.th}>Aliases</th>
          <th style={s.th}>Email</th>
          <th style={s.th}>Estado</th>
          <th style={s.th}>Acciones</th>
        </tr></thead>
        <tbody>
          {items.map((item, idx) => (
            <tr key={item.id}
              style={{ background: idx % 2 === 0 ? "#ffffff" : "#f7f8fb", transition:"background .1s" }}
              onMouseEnter={e => e.currentTarget.style.background = "#EBF4FF"}
              onMouseLeave={e => e.currentTarget.style.background = idx % 2 === 0 ? "#ffffff" : "#f7f8fb"}>
              <td style={s.td}><strong>{item.nombre_canonico}</strong></td>
              <td style={s.td}><span style={{color:"#888",fontSize:12}}>{item.aliases || "—"}</span></td>
              <td style={s.td}><span style={{fontSize:12}}>{item.email_contacto || "—"}</span></td>
              <td style={s.td}><span style={s.badge(item.estado)}>{item.estado}</span></td>
              <td style={s.td}>
                <div style={{display:"flex",gap:6}}>
                  <button style={s.btn("ghost")} onClick={() => openEdit(item)}>Editar</button>
                  <button style={s.btn("ghost")} onClick={() => toggle(item)}>{item.estado==="activa"?"Desactivar":"Activar"}</button>
                  <button style={s.btn("danger")} onClick={() => destroy(item)}>Eliminar</button>
                </div>
              </td>
            </tr>
          ))}
          {items.length === 0 && <tr><td colSpan={5} style={{...s.td,color:"#aaa",textAlign:"center",padding:24}}>Sin {tipo} registradas</td></tr>}
        </tbody>
      </table>

      {modal && (
        <Modal title={modal === "new" ? `Nueva ${label}` : `Editar ${label}`} onClose={closeModal}>
          <div style={{display:"flex",flexDirection:"column",gap:12}}>
            <div>
              <label style={{fontSize:12,color:"#888",display:"block",marginBottom:4}}>Nombre canónico *</label>
              <input style={{...s.input,width:"100%",boxSizing:"border-box"}} value={form.nombre_canonico||""} onChange={e=>setForm({...form,nombre_canonico:e.target.value})} placeholder="Nike Running" />
            </div>
            <div>
              <label style={{fontSize:12,color:"#888",display:"block",marginBottom:4}}>Aliases (separados por coma)</label>
              <input style={{...s.input,width:"100%",boxSizing:"border-box"}} value={form.aliases||""} onChange={e=>setForm({...form,aliases:e.target.value})} placeholder="Nike, NikeES, @nikerunning" />
            </div>
            <div>
              <label style={{fontSize:12,color:"#888",display:"block",marginBottom:4}}>Email de contacto</label>
              <input style={{...s.input,width:"100%",boxSizing:"border-box"}} value={form.email_contacto||""} onChange={e=>setForm({...form,email_contacto:e.target.value})} placeholder="marca@ejemplo.com" />
            </div>
            <div>
              <label style={{fontSize:12,color:"#888",display:"block",marginBottom:4}}>{aliasLabel} (separados por coma)</label>
              <input style={{...s.input,width:"100%",boxSizing:"border-box"}} value={form[aliasField]||""} onChange={e=>setForm({...form,[aliasField]:e.target.value})} placeholder="Agencia A, Agencia B" />
            </div>
            <div>
              <label style={{fontSize:12,color:"#888",display:"block",marginBottom:4}}>Notas</label>
              <textarea style={s.textarea} value={form.notas||""} onChange={e=>setForm({...form,notas:e.target.value})} />
            </div>
            <div style={{display:"flex",gap:8,justifyContent:"flex-end",marginTop:8}}>
              <button style={s.btn("ghost")} onClick={closeModal}>Cancelar</button>
              <button style={s.btn()} onClick={save}>Guardar</button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}

// ── Tokens panel ──────────────────────────────────────────────────────────────
const TOKEN_FIELDS = {
  youtube:    [["client_id","Client ID"],["client_secret","Client Secret"],["refresh_token","Refresh Token"],["channel_id","Channel ID"]],
  instagram:  [["app_id","App ID"],["app_secret","App Secret"],["access_token","Access Token (long-lived)"],["instagram_account_id","Instagram Account ID"]],
  facebook:   [["page_id","Page ID"],["access_token","Access Token"]],
  threads:    [["app_id","App ID"],["app_secret","App Secret"],["access_token","Access Token"],["threads_user_id","Threads User ID"]],
  x:          [["bearer_token","Bearer Token"],["api_key","API Key"],["api_secret","API Secret"]],
  tiktok:     [["client_key","Client Key"],["client_secret","Client Secret"],["access_token","Access Token"]],
  ga4:        [["property_id","Property ID"],["service_account_json","Service Account JSON (completo)"]],
  meta_ads:   [["ad_account_id","Ad Account ID (autodetectado si vacío)"]],
  google_ads: [["developer_token","Developer Token (Google Ads → Herramientas → Centro de API)"],["customer_id","Customer ID (sin guiones)"],["access_token","Access Token (generado por authorize_google_ads.py)"]],
};

function TokensPanel({ slug, api }) {
  const [existing, setExisting] = useState([]);
  const [canal, setCanal] = useState("youtube");
  const [form, setForm] = useState({});
  const [err, setErr] = useState(""); const [ok, setOk] = useState("");

  const load = useCallback(async () => {
    try { setExisting(await api("GET", `/medios/${slug}/tokens`)); } catch {}
  }, [slug]);
  useEffect(() => { load(); }, [load]);

  const isSet = (c, k) => existing.some(t => t.canal === c && t.clave === k);

  const save = async (clave, valor) => {
    if (!valor) return;
    setErr(""); setOk("");
    try {
      await api("PUT", `/medios/${slug}/tokens`, { canal, clave, valor });
      setOk(`Token ${clave} guardado`); setForm(f=>({...f,[clave]:""})); await load();
    } catch(ex) { setErr(ex.message); }
  };

  const del = async (c, k) => {
    if (!confirm(`¿Eliminar token ${k} de ${c}?`)) return;
    try { await api("DELETE", `/medios/${slug}/tokens/${c}/${k}`); await load(); }
    catch(ex) { setErr(ex.message); }
  };

  return (
    <div>
      <Alert msg={err} type="error" onClose={()=>setErr("")} />
      <Alert msg={ok} type="success" onClose={()=>setOk("")} />
      <div style={s.row}>
        {Object.keys(TOKEN_FIELDS).map(c => (
          <button key={c} style={{...s.btn(canal===c?"primary":"ghost"),textTransform:"capitalize"}} onClick={()=>{setCanal(c);setForm({});}}>
            {c}
          </button>
        ))}
      </div>
      <div style={{marginTop:8}}>
        {(TOKEN_FIELDS[canal]||[]).map(([key, label]) => (
          <div key={key} style={s.tokenRow}>
            <div style={{width:200,fontSize:13}}>
              <div style={{fontWeight:500}}>{label}</div>
              <div style={{marginTop:2}}>{isSet(canal,key) ? <span style={{...s.badge("activa"),fontSize:10}}>configurado</span> : <span style={{...s.badge("inactiva"),fontSize:10}}>no configurado</span>}</div>
            </div>
            <input
              style={{...s.input,flex:1}}
              type="password"
              placeholder={isSet(canal,key) ? "••••••••••••" : "Pegar valor aquí"}
              value={form[key]||""}
              onChange={e=>setForm(f=>({...f,[key]:e.target.value}))}
            />
            <button style={s.btn("success")} onClick={()=>save(key,form[key])}>Guardar</button>
            {isSet(canal,key) && <button style={s.btn("danger")} onClick={()=>del(canal,key)}>Borrar</button>}
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Config panel ──────────────────────────────────────────────────────────────
function ConfigPanel({ slug, api }) {
  const [cfg, setCfg] = useState(null);
  const [err, setErr] = useState(""); const [ok, setOk] = useState("");

  useEffect(() => {
    api("GET", `/medios/${slug}/config`).then(setCfg).catch(ex=>setErr(ex.message));
  }, [slug]);

  const save = async () => {
    setErr(""); setOk("");
    try {
      const updated = await api("PATCH", `/medios/${slug}/config`, {
        umbral_confianza_marca: parseInt(cfg.umbral_confianza_marca),
        dias_actualizacion_auto: parseInt(cfg.dias_actualizacion_auto),
        hora_trigger_diario: cfg.hora_trigger_diario,
        hora_trigger_stories: cfg.hora_trigger_stories,
        email_alertas_equipo: cfg.email_alertas_equipo,
        ga4_property_id: cfg.ga4_property_id,
        youtube_channel_id: cfg.youtube_channel_id,
      });
      setCfg(updated); setOk("Configuración guardada");
    } catch(ex) { setErr(ex.message); }
  };

  if (!cfg) return <div style={{color:"#aaa"}}>Cargando...</div>;
  const field = (label, key, type="text", hint="") => (
    <div style={{marginBottom:16}}>
      <label style={{fontSize:12,color:"#888",display:"block",marginBottom:4}}>{label}</label>
      <input style={{...s.input,maxWidth:320}} type={type} value={cfg[key]||""} onChange={e=>setCfg({...cfg,[key]:e.target.value})} />
      {hint && <div style={{fontSize:11,color:"#aaa",marginTop:3}}>{hint}</div>}
    </div>
  );

  return (
    <div>
      <Alert msg={err} type="error" onClose={()=>setErr("")} />
      <Alert msg={ok} type="success" onClose={()=>setOk("")} />
      <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:24}}>
        <div>
          <div style={s.h3}>Identificación de marca</div>
          {field("Umbral de confianza (0-100)","umbral_confianza_marca","number","Publicaciones por debajo van a cola de revisión")}
        </div>
        <div>
          <div style={s.h3}>Actualizaciones automáticas</div>
          {field("Días para actualización automática","dias_actualizacion_auto","number","Tras este número de días se refresca el reach")}
          {field("Hora trigger diario (HH:MM)","hora_trigger_diario","text","Detección de publicaciones nuevas")}
          {field("Hora trigger Stories (HH:MM)","hora_trigger_stories","text","Debe ejecutarse antes de las 24h de la Story")}
        </div>
        <div>
          <div style={s.h3}>Google / YouTube</div>
          {field("GA4 Property ID","ga4_property_id","text","Ej: 123456789")}
          {field("YouTube Channel ID","youtube_channel_id","text","Ej: UCxxxxxxxxxxxxxxx")}
        </div>
        <div>
          <div style={s.h3}>Notificaciones</div>
          {field("Emails de alerta del equipo","email_alertas_equipo","text","Separados por coma")}
        </div>
      </div>
      <button style={s.btn()} onClick={save}>Guardar configuración</button>
    </div>
  );
}

// ── Medio config (tabs: marcas/agencias/tokens/config) ────────────────────────
function MedioConfig({ slug, api }) {
  const [tab, setTab] = useState("marcas");
  const tabs = [["marcas","Marcas"],["agencias","Agencias"],["tokens","Tokens API"],["config","Configuración"]];
  return (
    <div>
      <div style={s.tabBar}>
        {tabs.map(([key,label]) => (
          <button key={key} onClick={()=>setTab(key)} style={s.tabBtn(tab===key)}>{label}</button>
        ))}
      </div>
      <div style={s.card}>
        {tab === "marcas"   && <EntidadCRUD slug={slug} tipo="marcas" api={api} />}
        {tab === "agencias" && <EntidadCRUD slug={slug} tipo="agencias" api={api} />}
        {tab === "tokens"   && <TokensPanel slug={slug} api={api} />}
        {tab === "config"   && <ConfigPanel slug={slug} api={api} />}
      </div>
    </div>
  );
}

// ── Story popover ──────────────────────────────────────────────────────────────
function StoryPopover({ item, x, y, imgUrl, onClose }) {
  const ref = useRef(null);

  useEffect(() => {
    const handler = (e) => {
      if (ref.current && !ref.current.contains(e.target)) onClose();
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [onClose]);

  return (
    <div
      ref={ref}
      style={{
        position:"fixed",
        top: y,
        left: x,
        zIndex: 9999,
        width: 380,
        maxHeight: 600,
        background:"#fff",
        borderRadius:12,
        boxShadow:"0 4px 24px rgba(0,0,0,0.18)",
        border:"1px solid #e8e8e8",
        display:"flex",
        flexDirection:"column",
        overflow:"hidden",
      }}
    >
      {/* Header */}
      <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center",
        padding:"10px 14px", borderBottom:"1px solid #f0f0f0", flexShrink:0 }}>
        <span style={{ fontSize:13, fontWeight:600, color:"#1a1a2e" }}>Captura de Story</span>
        <button onClick={onClose}
          style={{ background:"none", border:"none", cursor:"pointer", fontSize:16, color:"#aaa", lineHeight:1, padding:"0 2px" }}>✕</button>
      </div>
      {/* Imagen */}
      <div style={{ overflowY:"auto", display:"flex", flexDirection:"column", alignItems:"center", padding:12, gap:12 }}>
        <img
          src={imgUrl}
          alt="Captura story"
          style={{ maxWidth:340, maxHeight:440, borderRadius:8, objectFit:"contain", width:"100%" }}
        />
        <div style={{ width:"100%", fontSize:13, color:"#444", display:"flex", flexDirection:"column", gap:4 }}>
          <div><strong>Fecha:</strong> {fmtDate(item.fecha_publicacion)}</div>
          <div><strong>Marca:</strong> {item.marca_nombre || "— sin marca —"}</div>
          <div><strong>Reach:</strong> {fmtNum(item.reach)}</div>
          <div><strong>Replies:</strong> {fmtNum(item.comments)}</div>
        </div>
      </div>
    </div>
  );
}

// ── Publicaciones page ────────────────────────────────────────────────────────
const PER_PAGE = 50;
const CANALES_OPTS = [
  ["web","Web"],
  ["instagram_post","Instagram"],
  ["instagram_story","Stories"],
  ["reel","Reels"],
  ["facebook","Facebook"],
  ["youtube","YouTube"],
  ["youtube_short","Shorts"],
  ["threads","Threads"],
  ["tiktok","TikTok"],
];
const ESTADOS_OPTS = [
  ["","Todos los estados"],
  ["pendiente","Pendiente"],
  ["actualizado","Actualizado"],
  ["revisar","En revisión"],
  ["error","Error"],
  ["fijo","Fijo"],
];

function EstadoBadge({ estado }) {
  const st = ESTADO_STYLE[estado] || { background:"#eee", color:"#555" };
  return <span style={{ ...st, display:"inline-block", padding:"2px 8px", borderRadius:20, fontSize:11, fontWeight:500 }}>{estado}</span>;
}

function EstadoMarcaBadge({ estado }) {
  if (!estado) return null;
  const st = ESTADO_MARCA_STYLE[estado] || { background:"#eee", color:"#555" };
  return <span style={{ ...st, display:"inline-block", padding:"2px 8px", borderRadius:20, fontSize:11, fontWeight:500 }}>{ESTADO_MARCA_LABEL[estado] || estado}</span>;
}

function CanalDot({ canal }) {
  return (
    <span style={{ display:"inline-flex", alignItems:"center", gap:5 }}>
      <span style={{ width:8, height:8, borderRadius:"50%", background: CANAL_COLORS[canal] || "#999", display:"inline-block" }} />
      <span style={{ fontSize:12 }}>{CANAL_LABELS[canal] || canal}</span>
    </span>
  );
}

// ── Pub table badges ──────────────────────────────────────────────────────────

const CANAL_DOT_COLORS = {
  web: "#185FA5",
  instagram_post: "#D4537E",
  instagram_story: "#BA7517",
  facebook: "#0866FF",
  youtube: "#E24B4A",
  youtube_short: "#E24B4A",
  reel: "#9B59B6",
  threads: "#000000",
};
const CANAL_DOT_LABELS = {
  web: "Web",
  instagram_post: "Instagram",
  instagram_story: "Stories",
  facebook: "Facebook",
  youtube: "YouTube",
  youtube_short: "Short",
  reel: "Reel",
  threads: "Threads",
};

function TextTooltip({ texto, isOpen, onOpen, onClose }) {
  const popoverRef = useRef(null);

  useEffect(() => {
    if (!isOpen) return;
    const handler = (e) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target)) {
        onClose();
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [isOpen, onClose]);

  if (!texto) return null;
  return (
    <span
      ref={popoverRef}
      style={{ position: "relative", display: "inline-flex", alignItems: "center", flexShrink: 0 }}
    >
      {/* Icono documento — click para abrir */}
      <svg
        width="16" height="16" viewBox="0 0 16 16" fill="none"
        onClick={(e) => { e.stopPropagation(); isOpen ? onClose() : onOpen(); }}
        style={{ color: "#999", cursor: "pointer", display: "block" }}
      >
        <rect x="2.5" y="1.5" width="11" height="13" rx="1.5" stroke="currentColor" strokeWidth="1.4" fill="none"/>
        <line x1="5" y1="5.5"  x2="11" y2="5.5"  stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"/>
        <line x1="5" y1="8"    x2="11" y2="8"    stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"/>
        <line x1="5" y1="10.5" x2="9"  y2="10.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"/>
      </svg>
      {isOpen && (
        <div style={{
          position: "absolute",
          bottom: "calc(100% + 6px)",
          left: "50%",
          transform: "translateX(-50%)",
          zIndex: 300,
          background: "#fff",
          border: "1px solid #e0e0e0",
          borderRadius: 8,
          width: 450,
          boxShadow: "0 4px 16px rgba(0,0,0,0.15)",
        }}>
          {/* Header con botón X */}
          <div style={{
            display: "flex", justifyContent: "flex-end", alignItems: "center",
            padding: "6px 10px 4px", borderBottom: "1px solid #f0f0f0",
          }}>
            <button
              onClick={(e) => { e.stopPropagation(); onClose(); }}
              style={{ background: "none", border: "none", cursor: "pointer", fontSize: 14,
                color: "#aaa", lineHeight: 1, padding: "0 2px" }}
            >✕</button>
          </div>
          {/* Cuerpo con scroll */}
          <div style={{
            padding: "12px 16px",
            maxHeight: 260,
            overflowY: "auto",
            fontSize: 13,
            color: "#444",
            lineHeight: 1.6,
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
          }}>
            {texto}
          </div>
        </div>
      )}
    </span>
  );
}

function CanalCell({ canal, tipo }) {
  const key = tipo === "reel" ? "reel" : canal;
  const color = CANAL_DOT_COLORS[key] || "#999";
  const label = CANAL_DOT_LABELS[key] || canal;
  return (
    <span style={{ display:"inline-flex", alignItems:"center", gap:5 }}>
      <span style={{ width:7, height:7, borderRadius:"50%", background:color, display:"inline-block", flexShrink:0 }} />
      <span style={{ fontSize:12, fontWeight:500, color }}>{label}</span>
    </span>
  );
}

function MarcaBadge({ estadoMarca }) {
  if (estadoMarca === "ok")        return <span style={{ display:"inline-flex", alignItems:"center", gap:4, background:"#EAF3DE", color:"#27500A", borderRadius:12, padding:"2px 8px", fontSize:11, fontWeight:500 }}><span style={{ width:5, height:5, borderRadius:"50%", background:"#3B6D11", flexShrink:0 }} />Validada</span>;
  if (estadoMarca === "estimated") return <span style={{ display:"inline-flex", alignItems:"center", gap:4, background:"#E6F1FB", color:"#0C447C", borderRadius:12, padding:"2px 8px", fontSize:11, fontWeight:500 }}><span style={{ width:5, height:5, borderRadius:"50%", background:"#185FA5", flexShrink:0 }} />Autodetectada</span>;
  return <span style={{ display:"inline-flex", alignItems:"center", gap:4, background:"#FAEEDA", color:"#633806", borderRadius:12, padding:"2px 8px", fontSize:11, fontWeight:500 }}><span style={{ width:5, height:5, borderRadius:"50%", background:"#854F0B", flexShrink:0 }} />Revisar</span>;
}

function ConfianzaBar({ value }) {
  if (value == null) return null;
  const color = value >= 80 ? "#3B6D11" : value >= 60 ? "#854F0B" : "#A32D2D";
  return (
    <span style={{ display:"inline-flex", alignItems:"center", gap:5 }}>
      <span style={{ width:36, height:4, background:"#eee", borderRadius:2, display:"inline-block", overflow:"hidden" }}>
        <span style={{ display:"block", height:"100%", width:`${Math.min(100, value)}%`, background:color, borderRadius:2 }} />
      </span>
      <span style={{ fontSize:11, color:"#888" }}>{value}%</span>
    </span>
  );
}

function EstadoMetricasBadge({ estado, intentos }) {
  const proximoLunes = getProximoLunes();
  const ESTADOS_METRICAS = {
    actualizado: { bg:"#EAF3DE", color:"#27500A", dot:"#3B6D11",  label:"Sincronizado",  retry:false },
    pendiente:   { bg:"#F1EFE8", color:"#444441", dot:"#888780",  label:"Pendiente",     retry:true  },
    error:       { bg:"#FCEBEB", color:"#791F1F", dot:"#A32D2D",  label:`Error · ${intentos||0}/5`, retry:true },
    fijo:        { bg:"#EEEDFE", color:"#3C3489", dot:"#534AB7",  label:"Fijo",          retry:false },
    sin_datos:   { bg:"#F1EFE8", color:"#5F5E5A", dot:"#B4B2A9",  label:"Sin datos",     retry:false },
    revisar:     { bg:"#FAEEDA", color:"#633806", dot:"#854F0B",  label:"Revisar",       retry:true  },
  };
  const cfg = ESTADOS_METRICAS[estado] || { bg:"#eee", color:"#555", dot:"#aaa", label:estado, retry:false };
  return (
    <div>
      <span style={{ display:"inline-flex", alignItems:"center", gap:4, background:cfg.bg, color:cfg.color, borderRadius:12, padding:"2px 8px", fontSize:11, fontWeight:500, whiteSpace:"nowrap" }}>
        <span style={{ width:5, height:5, borderRadius:"50%", background:cfg.dot, flexShrink:0 }} />
        {cfg.label}
      </span>
      {cfg.retry && <div style={{ fontSize:11, color:"#aaa", marginTop:3 }}>reintento · {proximoLunes}</div>}
    </div>
  );
}

function MultiMarcaSelector({ value, onChange, marcas }) {
  // value: array of marca id numbers
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");

  const selected = value.map(Number).filter(Boolean);
  const available = marcas.filter(m => !selected.includes(m.id));
  const filtered = search
    ? available.filter(m => m.nombre_canonico.toLowerCase().includes(search.toLowerCase()))
    : available;

  const remove = (id) => onChange(selected.filter(v => v !== id));
  const add = (id) => { onChange([...selected, id]); setSearch(""); };

  return (
    <div style={{ position:"relative" }}>
      {/* Chips de marcas seleccionadas + botón añadir */}
      <div style={{ display:"flex", flexWrap:"wrap", gap:3, alignItems:"center" }}>
        {selected.map(id => {
          const m = marcas.find(x => x.id === id);
          return (
            <span key={id} style={{
              display:"inline-flex", alignItems:"center", gap:3,
              background:"#EBF4FF", color:"#0C447C", borderRadius:10,
              padding:"2px 5px 2px 8px", fontSize:11, fontWeight:500, lineHeight:"16px",
            }}>
              {m?.nombre_canonico ?? id}
              <button
                onClick={e => { e.stopPropagation(); remove(id); }}
                style={{ background:"none", border:"none", cursor:"pointer", color:"#5FA0D0",
                  padding:"0 1px", lineHeight:1, fontSize:14, fontWeight:400 }}>×</button>
            </span>
          );
        })}
        <button
          onClick={() => { setOpen(o => !o); setSearch(""); }}
          style={{
            background:"none", border:"1px dashed #ccc", borderRadius:8,
            padding:"1px 7px", cursor:"pointer", fontSize:12, color:"#999", lineHeight:"16px",
          }}
          title={open ? "Cerrar" : "Añadir marca"}>
          {open ? "−" : "+"}
        </button>
      </div>

      {/* Dropdown de búsqueda */}
      {open && (
        <div style={{
          position:"absolute", zIndex:200, top:"100%", left:0, marginTop:3,
          background:"#fff", border:"1px solid #d0d0d0", borderRadius:7,
          boxShadow:"0 4px 16px rgba(0,0,0,0.12)", minWidth:180, maxWidth:240,
        }}>
          <div style={{ padding:"6px 8px", borderBottom:"1px solid #f0f0f0" }}>
            <input
              autoFocus
              placeholder="Buscar marca…"
              value={search}
              onChange={e => setSearch(e.target.value)}
              style={{ width:"100%", boxSizing:"border-box", fontSize:12,
                border:"1px solid #ddd", borderRadius:5, padding:"3px 6px", outline:"none" }}
            />
          </div>
          <div style={{ maxHeight:140, overflowY:"auto" }}>
            {filtered.length === 0 && (
              <div style={{ padding:"8px 10px", color:"#bbb", fontSize:12 }}>Sin resultados</div>
            )}
            {filtered.map(m => (
              <div key={m.id}
                onClick={() => add(m.id)}
                style={{ padding:"6px 10px", cursor:"pointer", fontSize:12, color:"#1a1a2e",
                  borderBottom:"1px solid #f5f5f5" }}
                onMouseEnter={e => e.currentTarget.style.background = "#f0f5ff"}
                onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
                {m.nombre_canonico}
              </div>
            ))}
          </div>
          <div style={{ padding:"5px 8px", borderTop:"1px solid #f0f0f0", textAlign:"right" }}>
            <button onClick={() => setOpen(false)}
              style={{ background:"none", border:"none", cursor:"pointer", fontSize:11, color:"#888" }}>
              Cerrar
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function PublicacionesPage({ slug, api }) {
  const [marcas, setMarcas] = useState([]);
  const initFiltros = { marca_id: "", canales: [], estado: "", fecha_desde: "", fecha_hasta: "", patrocinado: "" };
  const [filtros, setFiltros] = useState(initFiltros);
  const [applied, setApplied] = useState(initFiltros);
  const [page, setPage] = useState(1);
  // sortConfig: [{col, dir}] — dir: "asc" | "desc"
  const [sortConfig, setSortConfig] = useState([]);
  const [canalOpen, setCanalOpen] = useState(false);
  const canalRef = useRef(null);
  useEffect(() => {
    const handler = e => { if (canalRef.current && !canalRef.current.contains(e.target)) setCanalOpen(false); };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [ok, setOk] = useState("");
  const [selected, setSelected] = useState(new Set());
  const [bulkLoading, setBulkLoading] = useState(false);
  const [marcaAsignar, setMarcaAsignar] = useState("");
  const [rowMarcas, setRowMarcas] = useState({});
  const [rowPromo, setRowPromo] = useState({});
  const [rowSaving, setRowSaving] = useState({});
  const [storyModal, setStoryModal] = useState(null);
  const [hoveredRow, setHoveredRow] = useState(null);
  const [textoAbierto, setTextoAbierto] = useState(null);

  useEffect(() => {
    api("GET", `/medios/${slug}/marcas`).then(setMarcas).catch(() => {});
  }, [slug]);

  // Sincronizar rowMarcas cuando llegan datos nuevos (sin borrar edits en curso)
  useEffect(() => {
    if (data?.items) {
      setRowMarcas(prev => {
        const next = { ...prev };
        data.items.forEach(i => {
          if (!(i.id in next)) {
            next[i.id] = i.marcas_ids?.length ? i.marcas_ids : (i.marca_id ? [i.marca_id] : []);
          }
        });
        return next;
      });
      setRowPromo(prev => {
        const next = { ...prev };
        data.items.forEach(i => {
          if (!(i.id in next)) {
            next[i.id] = {
              inversion_pagada: i.inversion_pagada != null ? i.inversion_pagada : "",
              reach_pagado: i.reach_pagado > 0 ? i.reach_pagado : "",
            };
          }
        });
        return next;
      });
    }
  }, [data]);

  const loadPubs = useCallback(async () => {
    setLoading(true);
    setSelected(new Set());
    try {
      const p = new URLSearchParams({ page, per_page: PER_PAGE });
      if (applied.marca_id) p.set("marca_id", applied.marca_id);
      // Multicanal: si hay selección, separar reels (van por tipo) del resto
      if (applied.canales?.length) {
        const sinReel = applied.canales.filter(c => c !== "reel");
        const conReel = applied.canales.includes("reel");
        if (sinReel.length) p.set("canal", sinReel.join(","));
        if (conReel) p.set("tipo", "reel");
      }
      if (applied.estado)       p.set("estado", applied.estado);
      if (applied.fecha_desde)  p.set("fecha_desde", applied.fecha_desde);
      if (applied.fecha_hasta)  p.set("fecha_hasta", applied.fecha_hasta);
      if (applied.patrocinado)  p.set("patrocinado", applied.patrocinado);
      const d = await api("GET", `/medios/${slug}/publicaciones?${p}`);
      setData(d);
    } catch (ex) {
      setErr(ex.message);
    } finally {
      setLoading(false);
    }
  }, [slug, applied, page]);

  useEffect(() => { loadPubs(); }, [loadPubs]);

  const handleBuscar = () => { setPage(1); setApplied({ ...filtros }); setSortConfig([]); };

  // Ordenación multicolumna: cicla none→desc→asc→none
  const handleSort = (col) => {
    setSortConfig(prev => {
      const idx = prev.findIndex(s => s.col === col);
      if (idx === -1) return [...prev, { col, dir: "desc" }];
      const cur = prev[idx];
      if (cur.dir === "desc") {
        const next = [...prev]; next[idx] = { col, dir: "asc" }; return next;
      }
      // asc → quitar
      return prev.filter(s => s.col !== col);
    });
  };

  // Items ordenados según sortConfig (orden client-side sobre la página actual)
  const sortedItems = useMemo(() => {
    if (!data?.items || sortConfig.length === 0) return data?.items ?? [];
    return [...data.items].sort((a, b) => {
      for (const { col, dir } of sortConfig) {
        const mult = dir === "asc" ? 1 : -1;
        let va = a[col], vb = b[col];
        if (va == null) va = dir === "asc" ? Infinity : -Infinity;
        if (vb == null) vb = dir === "asc" ? Infinity : -Infinity;
        if (typeof va === "string") {
          const cmp = va.localeCompare(vb, "es"); if (cmp !== 0) return cmp * mult;
        } else {
          if (va < vb) return -1 * mult;
          if (va > vb) return  1 * mult;
        }
      }
      return 0;
    });
  }, [data?.items, sortConfig]);

  const toggleSelect = (id) => {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };
  const toggleAll = () => {
    if (!data) return;
    const allIds = data.items.map(i => i.id);
    setSelected(prev => prev.size === allIds.length ? new Set() : new Set(allIds));
  };

  const handleBulkRefresh = async () => {
    setBulkLoading(true); setErr(""); setOk("");
    try {
      const r = await api("POST", `/medios/${slug}/publicaciones/bulk-refresh`, { ids: [...selected] });
      setOk(`Métricas actualizadas: ${r.actualizadas}. Errores: ${r.errores}`);
      await loadPubs();
    } catch (ex) { setErr(ex.message); }
    finally { setBulkLoading(false); }
  };

  const handleAsignarMarca = async () => {
    if (!marcaAsignar) return;
    setBulkLoading(true); setErr(""); setOk("");
    try {
      await api("PATCH", `/medios/${slug}/publicaciones/bulk-update`, {
        ids: [...selected], accion: "asignar_marca", marca_id: parseInt(marcaAsignar),
      });
      setOk(`Marca asignada a ${selected.size} publicaciones`);
      setMarcaAsignar("");
      await loadPubs();
    } catch (ex) { setErr(ex.message); }
    finally { setBulkLoading(false); }
  };

  const handleMarcarRevisado = async () => {
    setBulkLoading(true); setErr(""); setOk("");
    try {
      await api("PATCH", `/medios/${slug}/publicaciones/bulk-update`, {
        ids: [...selected], accion: "marcar_revisado",
      });
      setOk(`${selected.size} publicaciones marcadas como revisadas`);
      await loadPubs();
    } catch (ex) { setErr(ex.message); }
    finally { setBulkLoading(false); }
  };

  const asignarInline = async (pubId, marcaId) => {
    if (!marcaId) return;
    try {
      await api("PATCH", `/medios/${slug}/publicaciones/bulk-update`, {
        ids: [pubId], accion: "asignar_marca", marca_id: parseInt(marcaId),
      });
      await loadPubs();
    } catch (ex) { setErr(ex.message); }
  };

  const guardarMarcaInline = async (item) => {
    const marcaIds = (rowMarcas[item.id] ?? []).map(Number).filter(Boolean);
    const promo = rowPromo[item.id] ?? {};
    setRowSaving(prev => ({ ...prev, [item.id]: true }));
    try {
      await api("PATCH", `/medios/${slug}/publicaciones/${item.id}/marcas`, {
        marca_ids: marcaIds, estado_marca: "ok",
      });
      // Guardar promoción si hay datos
      const inversion = promo.inversion_pagada !== "" ? parseFloat(promo.inversion_pagada) || 0 : 0;
      const reachPag = promo.reach_pagado !== "" ? parseInt(promo.reach_pagado) || 0 : 0;
      await api("PATCH", `/medios/${slug}/publicaciones/${item.id}/promocion`, {
        inversion_pagada: inversion,
        reach_pagado: reachPag,
      });
      const primaryId = marcaIds[0] ?? null;
      const primaryNombre = primaryId ? marcas.find(m => m.id === primaryId)?.nombre_canonico : null;
      const marcasNombres = marcaIds.map(id => marcas.find(m => m.id === id)?.nombre_canonico).filter(Boolean);
      setData(prev => ({
        ...prev,
        items: prev.items.map(i =>
          i.id === item.id
            ? { ...i, marca_id: primaryId, marca_nombre: primaryNombre,
                marcas_ids: marcaIds, marcas_nombres: marcasNombres,
                estado_marca: "ok",
                inversion_pagada: inversion > 0 ? inversion : null,
                reach_pagado: reachPag,
                estado_metricas: i.estado_metricas === "revisar" ? "pendiente" : i.estado_metricas }
            : i
        ),
      }));
      setRowMarcas(prev => ({ ...prev, [item.id]: marcaIds }));
      setRowPromo(prev => ({ ...prev, [item.id]: { inversion_pagada: inversion || "", reach_pagado: reachPag || "" } }));
    } catch (ex) { setErr(ex.message); }
    finally { setRowSaving(prev => ({ ...prev, [item.id]: false })); }
  };

  const items = sortedItems;
  const allSelected = items.length > 0 && selected.size === items.length;
  const inicio = data ? (page - 1) * PER_PAGE + 1 : 0;
  const fin    = data ? Math.min(page * PER_PAGE, data.total) : 0;

  const storyImgUrl = (captura_url) => {
    if (!captura_url || captura_url === "expired") return null;
    const path = captura_url.replace(/\\/g, "/");
    const clean = path.startsWith("stories_images/") ? path.slice("stories_images/".length) : path;
    if (import.meta.env.PROD) {
      return `/social/stories_images/${clean}`;
    } else {
      return `http://localhost:8000/stories_images/${clean}`;
    }
  };

  return (
    <div style={{ position:"relative" }}>
      <h2 style={s.h2}>Publicaciones</h2>

      {/* Filtros */}
      <div style={s.card}>
        <div style={{ display:"flex", gap:10, flexWrap:"wrap", alignItems:"flex-end" }}>
          <div>
            <div style={{ fontSize:11, color:"#888", marginBottom:4 }}>Marca</div>
            <select style={s.select} value={filtros.marca_id} onChange={e => setFiltros({...filtros, marca_id: e.target.value})}>
              <option value="">Todas las marcas</option>
              {marcas.map(m => <option key={m.id} value={m.id}>{m.nombre_canonico}</option>)}
            </select>
          </div>
          {/* Canal — dropdown custom multiselect */}
          <div ref={canalRef} style={{ position:"relative" }}>
            <div style={{ fontSize:11, color:"#888", marginBottom:4 }}>Canal</div>
            <button
              type="button"
              onClick={() => setCanalOpen(o => !o)}
              style={{ ...s.select, display:"flex", alignItems:"center", justifyContent:"space-between",
                gap:8, minWidth:160, cursor:"pointer", background:"#fff", textAlign:"left" }}
            >
              <span style={{ overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap", color: filtros.canales.length ? "#1a1a2e" : "#888" }}>
                {filtros.canales.length === 0
                  ? "Todos los canales"
                  : filtros.canales.map(c => CANALES_OPTS.find(([v])=>v===c)?.[1]||c).join(", ")}
              </span>
              <span style={{ fontSize:10, color:"#888", flexShrink:0 }}>
                {filtros.canales.length > 0
                  ? <span style={{ background:"#185FA5", color:"#fff", borderRadius:10, padding:"1px 6px", fontSize:10 }}>{filtros.canales.length}</span>
                  : "▾"}
              </span>
            </button>
            {canalOpen && (
              <div style={{ position:"absolute", top:"100%", left:0, zIndex:999, background:"#fff",
                border:"1px solid #ddd", borderRadius:8, boxShadow:"0 4px 16px rgba(0,0,0,.12)",
                minWidth:180, padding:"6px 0", marginTop:2 }}>
                {CANALES_OPTS.map(([v, l]) => {
                  const checked = filtros.canales.includes(v);
                  return (
                    <label key={v} style={{ display:"flex", alignItems:"center", gap:8,
                      padding:"6px 14px", cursor:"pointer", fontSize:13,
                      background: checked ? "#EBF4FF" : "transparent",
                      color: checked ? "#185FA5" : "#1a1a2e" }}
                      onMouseEnter={e => e.currentTarget.style.background = checked ? "#daeaf8" : "#f5f6fa"}
                      onMouseLeave={e => e.currentTarget.style.background = checked ? "#EBF4FF" : "transparent"}
                      onClick={() => {
                        const next = checked
                          ? filtros.canales.filter(c => c !== v)
                          : [...filtros.canales, v];
                        setFiltros({...filtros, canales: next});
                      }}
                    >
                      <input type="checkbox" checked={checked} readOnly
                        style={{ accentColor:"#185FA5", width:14, height:14 }} />
                      {l}
                    </label>
                  );
                })}
                {filtros.canales.length > 0 && (
                  <div style={{ borderTop:"1px solid #eee", margin:"4px 0", padding:"6px 14px" }}>
                    <button type="button"
                      onClick={() => setFiltros({...filtros, canales:[]})}
                      style={{ fontSize:12, color:"#888", background:"none", border:"none", cursor:"pointer", padding:0 }}>
                      Limpiar selección
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
          <div>
            <div style={{ fontSize:11, color:"#888", marginBottom:4 }}>Estado</div>
            <select style={s.select} value={filtros.estado} onChange={e => setFiltros({...filtros, estado: e.target.value})}>
              {ESTADOS_OPTS.map(([v,l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </div>
          <div>
            <div style={{ fontSize:11, color:"#888", marginBottom:4 }}>Patrocinado</div>
            <select style={s.select} value={filtros.patrocinado} onChange={e => setFiltros({...filtros, patrocinado: e.target.value})}>
              <option value="">Todos</option>
              <option value="1">Solo patrocinados</option>
              <option value="0">Sin patrocinar</option>
            </select>
          </div>
          <div>
            <div style={{ fontSize:11, color:"#888", marginBottom:4 }}>Desde</div>
            <input type="date" style={s.select} value={filtros.fecha_desde} onChange={e => setFiltros({...filtros, fecha_desde: e.target.value})} />
          </div>
          <div>
            <div style={{ fontSize:11, color:"#888", marginBottom:4 }}>Hasta</div>
            <input type="date" style={s.select} value={filtros.fecha_hasta} onChange={e => setFiltros({...filtros, fecha_hasta: e.target.value})} />
          </div>
          <button style={s.btn()} onClick={handleBuscar}>Buscar</button>
          <button style={s.btn("ghost")} onClick={() => { setFiltros(initFiltros); setApplied(initFiltros); setPage(1); }}>Limpiar</button>
        </div>
      </div>

      {/* KPIs compactos + bulk bar */}
      <div style={{ display:"flex", alignItems:"center", gap:10, marginBottom:16, flexWrap:"wrap", justifyContent:"space-between" }}>
        {data ? (
          <div style={{ display:"flex", gap:8, flexWrap:"wrap" }}>
            <div style={{ background:"#f5f6fa", borderRadius:8, padding:"8px 14px", fontSize:13 }}>
              <span style={{ fontWeight:600, color:"#1a1a2e" }}>{data.total.toLocaleString("es-ES")}</span>
              <span style={{ color:"#888", marginLeft:5 }}>publicaciones</span>
            </div>
            <div style={{ background:"#f5f6fa", borderRadius:8, padding:"8px 14px", fontSize:13 }}>
              <span style={{ fontWeight:600, color:"#185FA5" }}>{fmtNum(data.reach_total)}</span>
              <span style={{ color:"#888", marginLeft:5 }}>reach orgánico</span>
            </div>
            {data.reach_pagado_total > 0 && (
              <div style={{ background:"#fdebd0", borderRadius:8, padding:"8px 14px", fontSize:13 }}>
                <span style={{ fontWeight:600, color:"#E67E22" }}>{fmtNum(data.reach_pagado_total)}</span>
                <span style={{ color:"#784212", marginLeft:5 }}>reach pagado</span>
              </div>
            )}
            {data.reach_total_combinado > 0 && data.reach_pagado_total > 0 && (
              <div style={{ background:"#f5f6fa", borderRadius:8, padding:"8px 14px", fontSize:13 }}>
                <span style={{ fontWeight:600, color:"#1a1a2e" }}>{fmtNum(data.reach_total_combinado)}</span>
                <span style={{ color:"#888", marginLeft:5 }}>reach total</span>
              </div>
            )}
            {data.inversion_total > 0 && (
              <div style={{ background:"#fdebd0", borderRadius:8, padding:"8px 14px", fontSize:13 }}>
                <span style={{ fontWeight:600, color:"#E67E22" }}>{fmtEuro(data.inversion_total)}</span>
                <span style={{ color:"#784212", marginLeft:5 }}>inversión</span>
              </div>
            )}
            {data.en_revision > 0 && (
              <div style={{ background:"#FAEEDA", borderRadius:8, padding:"8px 14px", fontSize:13 }}>
                <span style={{ fontWeight:600, color:"#854F0B" }}>{data.en_revision}</span>
                <span style={{ color:"#854F0B", marginLeft:5 }}>en revisión</span>
              </div>
            )}
          </div>
        ) : <div />}
      </div>

      {/* Bulk action bar */}
      {selected.size > 0 && (
        <div style={{ display:"flex", gap:10, alignItems:"center", padding:"10px 16px",
          background:"#EBF4FF", borderRadius:8, marginBottom:12, flexWrap:"wrap",
          border:"1px solid #B8D6F5" }}>
          <span style={{ fontWeight:500, color:"#0C447C", fontSize:13 }}>{selected.size} seleccionadas</span>
          <button style={{ padding:"6px 14px", borderRadius:7, border:"1px solid #185FA5", background:"#185FA5", color:"#fff", cursor:"pointer", fontSize:12, fontWeight:500, opacity: bulkLoading ? 0.6 : 1 }} onClick={handleBulkRefresh} disabled={bulkLoading}>
            {bulkLoading ? "Actualizando..." : "Actualizar métricas"}
          </button>
          <div style={{ display:"flex", gap:6, alignItems:"center" }}>
            <select style={s.select} value={marcaAsignar} onChange={e => setMarcaAsignar(e.target.value)}>
              <option value="">Asignar marca...</option>
              {marcas.map(m => <option key={m.id} value={m.id}>{m.nombre_canonico}</option>)}
            </select>
            {marcaAsignar && (
              <button style={{ padding:"6px 14px", borderRadius:7, border:"1px solid #185FA5", background:"transparent", color:"#185FA5", cursor:"pointer", fontSize:12, fontWeight:500 }} onClick={handleAsignarMarca} disabled={bulkLoading}>Aplicar</button>
            )}
          </div>
          <button style={{ padding:"6px 14px", borderRadius:7, border:"1px solid #B8D6F5", background:"transparent", color:"#0C447C", cursor:"pointer", fontSize:12 }} onClick={handleMarcarRevisado} disabled={bulkLoading}>Marcar revisado</button>
        </div>
      )}

      <Alert msg={err} type="error" onClose={() => setErr("")} />
      <Alert msg={ok} type="success" onClose={() => setOk("")} />

      {/* Tabla */}
      <div style={s.card}>
        {loading ? (
          <div style={{ textAlign:"center", padding:40, color:"#aaa" }}>Cargando...</div>
        ) : (
          <>
            <table style={s.table}>
              <thead>
                <tr style={{ background:"#fafafa" }}>
                  <th style={{...s.th, width:32}}>
                    <input type="checkbox" checked={allSelected} onChange={toggleAll} />
                  </th>
                  {[
                    { col:"fecha_publicacion", label:"Fecha",       align:"left"  },
                    { col:"canal",             label:"Canal",       align:"left"  },
                    { col:null,                label:"Contenido",   align:"left"  },
                    { col:null,                label:"Marca",       align:"left", minWidth:160 },
                    { col:"reach",             label:"Reach",       align:"right" },
                    { col:"likes",             label:"Likes",       align:"right" },
                    { col:"inversion_pagada",  label:"Inversión €", align:"right", minWidth:90 },
                    { col:"reach_pagado",      label:"Reach pag.",  align:"right", minWidth:90 },
                    { col:"estado_metricas",   label:"Métricas",   align:"left"  },
                    { col:null,                label:"Acción",      align:"left"  },
                  ].map(({ col, label, align, minWidth }) => {
                    const si = col ? sortConfig.findIndex(s => s.col === col) : -1;
                    const sc = si >= 0 ? sortConfig[si] : null;
                    const sortable = !!col;
                    return (
                      <th key={label}
                        style={{ ...s.th, textAlign: align, minWidth, cursor: sortable ? "pointer" : "default",
                          userSelect: "none", whiteSpace:"nowrap",
                          background: sc ? "#EBF4FF" : "#fafafa" }}
                        onClick={sortable ? () => handleSort(col) : undefined}
                        title={sortable ? "Haz clic para ordenar" : undefined}
                      >
                        {label}
                        {sc && (
                          <span style={{ marginLeft:5, fontSize:10, color:"#185FA5", fontWeight:700 }}>
                            {sc.dir === "desc" ? "▼" : "▲"}
                            {sortConfig.length > 1 && <sup style={{ fontSize:9 }}>{si+1}</sup>}
                          </span>
                        )}
                        {!sc && sortable && (
                          <span style={{ marginLeft:4, fontSize:10, color:"#ccc" }}>⇅</span>
                        )}
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {items.map((item, idx) => {
                  const marcasActual = (rowMarcas[item.id] ?? item.marcas_ids ?? (item.marca_id ? [item.marca_id] : [])).map(Number).filter(Boolean);
                  const marcasOriginal = (item.marcas_ids?.length ? item.marcas_ids : (item.marca_id ? [item.marca_id] : [])).map(Number).filter(Boolean);
                  const marcaCambiada = JSON.stringify([...marcasActual].sort()) !== JSON.stringify([...marcasOriginal].sort());
                  const promoActual = rowPromo[item.id] ?? {};
                  const inversionActual = promoActual.inversion_pagada !== "" ? parseFloat(promoActual.inversion_pagada) || 0 : 0;
                  const reachPagActual = promoActual.reach_pagado !== "" ? parseInt(promoActual.reach_pagado) || 0 : 0;
                  const inversionOrig = item.inversion_pagada != null ? item.inversion_pagada : 0;
                  const reachPagOrig = item.reach_pagado || 0;
                  const promoCambiada = inversionActual !== inversionOrig || reachPagActual !== reachPagOrig;
                  const hayCambios = marcaCambiada || promoCambiada;
                  const rowBg = selected.has(item.id) || hoveredRow === item.id
                    ? "#EBF4FF"
                    : idx % 2 === 0 ? "#ffffff" : "#f7f8fb";
                  return (
                  <tr key={item.id}
                    onMouseEnter={() => setHoveredRow(item.id)}
                    onMouseLeave={() => setHoveredRow(null)}
                    style={{ background: rowBg }}>
                    <td style={s.td}>
                      <input type="checkbox" checked={selected.has(item.id)} onChange={() => toggleSelect(item.id)} />
                    </td>

                    {/* Fecha */}
                    <td style={{...s.td, whiteSpace:"nowrap", fontSize:12, color:"#888"}}>
                      {fmtDate(item.fecha_publicacion)}
                    </td>

                    {/* Canal */}
                    <td style={s.td}>
                      <CanalCell canal={item.canal} tipo={item.tipo} />
                      {item.inversion_pagada > 0 && (
                        <span style={{ display:"block", marginTop:3, padding:"1px 6px", borderRadius:10, fontSize:10, fontWeight:600, background:"#fdebd0", color:"#784212", border:"1px solid #f0a500" }}>
                          Patrocinado
                        </span>
                      )}
                    </td>

                    {/* Contenido */}
                    <td style={{...s.td, maxWidth:260}}>
                      <div style={{ display:"flex", alignItems:"center", gap:6 }}>
                        {item.canal === "instagram_story" && (() => {
                          const cap = item.captura_url;
                          if (cap && cap !== "expired") {
                            return (
                              <span title="Ver captura" onClick={(e) => {
                                const rect = e.currentTarget.getBoundingClientRect();
                                let x = rect.right + 8;
                                let y = rect.top;
                                if (x + 420 > window.innerWidth) x = rect.left - 420 - 8;
                                if (y + 650 > window.innerHeight) y = window.innerHeight - 650 - 8;
                                setStoryModal({ item, x, y });
                              }}
                                style={{ fontSize:15, cursor:"pointer", flexShrink:0, userSelect:"none",
                                  background:"#e6f9ec", borderRadius:4, padding:"1px 4px",
                                  border:"1px solid #a3d9b0", lineHeight:1.4 }}>📷</span>
                            );
                          }
                          return (
                            <span title={cap === "expired" ? "Captura expirada (>24h)" : "Sin captura"}
                              style={{ fontSize:15, flexShrink:0, userSelect:"none", opacity:0.35,
                                borderRadius:4, padding:"1px 4px", border:"1px solid #ddd",
                                background:"#f5f5f5", lineHeight:1.4 }}>
                              {cap === "expired" ? "🕐" : "📷"}
                            </span>
                          );
                        })()}
                        <div style={{ overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap", minWidth:0, flex:1 }}
                          title={item.titulo || item.url}>
                          {item.titulo
                            ? <span style={{ fontSize:13, color:"#1a1a2e" }}>{item.titulo}</span>
                            : <span style={{ fontSize:11, color:"#aaa" }}>{item.url}</span>
                          }
                        </div>
                        <TextTooltip
                          texto={item.texto}
                          isOpen={textoAbierto === item.id}
                          onOpen={() => setTextoAbierto(item.id)}
                          onClose={() => setTextoAbierto(null)}
                        />
                      </div>
                    </td>

                    {/* Marca */}
                    <td style={{...s.td, minWidth:180}}>
                      <div style={{ marginBottom:4 }}>
                        <MultiMarcaSelector
                          value={marcasActual}
                          onChange={newIds => setRowMarcas(prev => ({ ...prev, [item.id]: newIds }))}
                          marcas={marcas}
                        />
                      </div>
                      <div style={{ display:"flex", alignItems:"center", gap:6, flexWrap:"wrap" }}>
                        <ConfianzaBar value={item.confianza_marca} />
                        <MarcaBadge estadoMarca={marcasActual.length === 0 ? null : item.estado_marca} />
                      </div>
                    </td>

                    {/* Reach */}
                    <td style={{...s.td, textAlign:"right", fontWeight: item.reach > 0 ? 500 : 400,
                      color: item.reach > 0 ? "#1a1a2e" : "#aaa", fontSize:13}}>
                      {fmtMetric(item.reach)}
                      {item.canal === "instagram_story" && item.es_final && (
                        <span style={{ display:"inline-block", marginLeft:5, padding:"1px 5px", borderRadius:10,
                          fontSize:10, fontWeight:600, background:"#dcfce7", color:"#166534", verticalAlign:"middle" }}>
                          Final
                        </span>
                      )}
                    </td>

                    {/* Likes */}
                    <td style={{...s.td, textAlign:"right", fontWeight: item.likes > 0 ? 500 : 400,
                      color: item.likes > 0 ? "#1a1a2e" : "#aaa", fontSize:13}}>
                      {fmtMetric(item.likes)}
                    </td>

                    {/* Inversión € */}
                    <td style={{...s.td, textAlign:"right"}}>
                      {item.canal !== "web" ? (
                        <input
                          type="number"
                          min="0"
                          step="0.01"
                          placeholder="0.00"
                          value={(rowPromo[item.id] ?? {}).inversion_pagada ?? ""}
                          onChange={e => setRowPromo(prev => ({ ...prev, [item.id]: { ...(prev[item.id] ?? {}), inversion_pagada: e.target.value } }))}
                          style={{ width:74, padding:"3px 6px", border:"1px solid #ddd", borderRadius:5, fontSize:12, textAlign:"right", background: (rowPromo[item.id] ?? {}).inversion_pagada > 0 ? "#fef9f0" : "#fff" }}
                        />
                      ) : <span style={{color:"#ddd",fontSize:12}}>—</span>}
                    </td>

                    {/* Reach pagado */}
                    <td style={{...s.td, textAlign:"right"}}>
                      {item.canal !== "web" ? (
                        <input
                          type="number"
                          min="0"
                          step="1"
                          placeholder="0"
                          value={(rowPromo[item.id] ?? {}).reach_pagado ?? ""}
                          onChange={e => setRowPromo(prev => ({ ...prev, [item.id]: { ...(prev[item.id] ?? {}), reach_pagado: e.target.value } }))}
                          style={{ width:74, padding:"3px 6px", border:"1px solid #ddd", borderRadius:5, fontSize:12, textAlign:"right", background: (rowPromo[item.id] ?? {}).reach_pagado > 0 ? "#fef9f0" : "#fff" }}
                        />
                      ) : <span style={{color:"#ddd",fontSize:12}}>—</span>}
                    </td>

                    {/* Métricas */}
                    <td style={s.td}>
                      <EstadoMetricasBadge estado={item.estado_metricas} intentos={item.intentos_fallidos} />
                      {item.canal === "instagram_story" && item.hora_ultima_captura && (
                        <div style={{ fontSize:10, color:"#888", marginTop:2 }}>
                          {new Date(item.hora_ultima_captura).toLocaleTimeString("es-ES", { hour:"2-digit", minute:"2-digit" })}
                        </div>
                      )}
                    </td>

                    {/* Acción */}
                    <td style={{...s.td, whiteSpace:"nowrap"}}>
                      {item.url && (
                        <a href={item.url} target="_blank" rel="noreferrer"
                          style={{ color:"#aaa", fontSize:13, textDecoration:"none", marginRight:6 }}
                          title="Abrir enlace">↗</a>
                      )}
                      {hayCambios ? (
                        <button
                          style={{ padding:"3px 10px", borderRadius:6, border:"1px solid #185FA5",
                            background:"#185FA5", color:"#fff", cursor:"pointer", fontSize:12, fontWeight:500 }}
                          disabled={rowSaving[item.id]}
                          onClick={() => guardarMarcaInline(item)}>
                          {rowSaving[item.id] ? "..." : "Guardar"}
                        </button>
                      ) : (
                        <span style={{ fontSize:13, color:"#ddd", cursor:"default" }} title="Editar">✎</span>
                      )}
                    </td>
                  </tr>
                  );
                })}
                {items.length === 0 && (
                  <tr><td colSpan={11} style={{...s.td, color:"#aaa", textAlign:"center", padding:32}}>
                    Sin publicaciones para los filtros seleccionados
                  </td></tr>
                )}
              </tbody>
            </table>

            {/* Paginación */}
            {data && data.total > PER_PAGE && (
              <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center", marginTop:16, fontSize:12, color:"#888" }}>
                <span>Mostrando {inicio}–{fin} de {data.total.toLocaleString("es-ES")}</span>
                <div style={{ display:"flex", gap:4, alignItems:"center" }}>
                  <button
                    style={{ padding:"5px 12px", borderRadius:6, border:"1px solid #e0e0e0", background:"transparent", color: page===1?"#ccc":"#555", cursor:page===1?"default":"pointer", fontSize:12 }}
                    onClick={() => setPage(p => Math.max(1, p-1))} disabled={page === 1}>← Anterior</button>
                  {Array.from({length: Math.min(data.paginas, 7)}, (_, i) => {
                    const p = i + 1;
                    return (
                      <button key={p}
                        style={{ padding:"5px 10px", borderRadius:6, border:"1px solid #e0e0e0", fontSize:12, cursor:"pointer",
                          background: page===p ? "#EBF4FF" : "transparent",
                          color: page===p ? "#0C447C" : "#555",
                          fontWeight: page===p ? 600 : 400 }}
                        onClick={() => setPage(p)}>{p}</button>
                    );
                  })}
                  {data.paginas > 7 && <span style={{padding:"0 4px"}}>…</span>}
                  <button
                    style={{ padding:"5px 12px", borderRadius:6, border:"1px solid #e0e0e0", background:"transparent", color: page===data.paginas?"#ccc":"#555", cursor:page===data.paginas?"default":"pointer", fontSize:12 }}
                    onClick={() => setPage(p => Math.min(data.paginas, p+1))} disabled={page === data.paginas}>Siguiente →</button>
                </div>
              </div>
            )}
          </>
        )}
      </div>

      {/* Popover captura de Story (position:fixed, sigue scroll) */}
      {storyModal && (() => {
        const { item: sm, x, y } = storyModal;
        return (
          <StoryPopover
            item={sm}
            x={x}
            y={y}
            imgUrl={storyImgUrl(sm.captura_url)}
            onClose={() => setStoryModal(null)}
          />
        );
      })()}
    </div>
  );
}

// ── Analytics page ────────────────────────────────────────────────────────────

function MarcaReachBars({ data, label = "Reach" }) {
  if (!data || Object.keys(data).length === 0) return <div style={{color:"#aaa",fontSize:12}}>Sin datos</div>;
  const total = Object.values(data).reduce((a, b) => a + b, 0) || 1;
  return (
    <div>
      {Object.entries(data).sort((a,b) => b[1]-a[1]).map(([canal, val]) => (
        <div key={canal} style={{ marginBottom:10 }}>
          <div style={{ display:"flex", justifyContent:"space-between", fontSize:12, marginBottom:3 }}>
            <span style={{ color:CANAL_COLORS[canal]||"#999", fontWeight:500 }}>{CANAL_LABELS[canal]||canal}</span>
            <span style={{ color:"#555" }}>{fmtNum(val)}</span>
          </div>
          <div style={{ background:"#f0f0f0", borderRadius:4, height:8 }}>
            <div style={{ background:CANAL_COLORS[canal]||"#999", borderRadius:4, height:8, width:`${Math.round(val/total*100)}%`, transition:"width .3s" }} />
          </div>
        </div>
      ))}
    </div>
  );
}

function DistribucionPorcentual({ reach, likes, shares, comments }) {
  const metrics = [
    { label:"Reach",    data:reach },
    { label:"Likes",    data:likes },
    { label:"Shares",   data:shares },
    { label:"Comments", data:comments },
  ];
  return (
    <div>
      {metrics.map(({ label, data }) => {
        const total = data ? Object.values(data).reduce((a,b)=>a+b,0) : 0;
        if (total === 0) return null;
        return (
          <div key={label} style={{ marginBottom:12 }}>
            <div style={{ fontSize:11, color:"#888", marginBottom:4 }}>{label}</div>
            <div style={{ display:"flex", height:16, borderRadius:4, overflow:"hidden" }}>
              {Object.entries(data).sort((a,b)=>b[1]-a[1]).map(([canal, val]) => (
                <div key={canal} title={`${CANAL_LABELS[canal]||canal}: ${fmtNum(val)}`}
                     style={{ background:CANAL_COLORS[canal]||"#999", width:`${Math.round(val/total*100)}%`, minWidth:val>0?2:0 }} />
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function MarcaAnalyticsView({ data, semanalData = null, compact = false }) {
  const [selCanal, setSelCanal] = useState(null);
  if (!data) return null;
  const lineData = data.evolucion_mensual?.length > 0 ? {
    labels: data.evolucion_mensual.map(e => e.mes),
    datasets: [{ label:"Reach", data: data.evolucion_mensual.map(e => e.reach),
      borderColor:"#6c63ff", backgroundColor:"rgba(108,99,255,0.1)", tension:0.3, fill:true }],
  } : null;

  const hasPaid = data.kpis.inversion_pagada > 0 || data.kpis.reach_pagado > 0;

  // Build stacked bar data for reach orgánico + pagado per canal
  const stackedReachData = (() => {
    const canales = Object.keys(data.reach_por_canal || {});
    if (!canales.length) return null;
    return {
      labels: canales.map(c => CANAL_LABELS[c] || c),
      datasets: [
        {
          label: "Reach orgánico",
          data: canales.map(c => Math.max(0, (data.reach_por_canal[c] || 0) - (data.reach_pagado_por_canal?.[c] || 0))),
          backgroundColor: canales.map(c => CANAL_COLORS[c] || "#999"),
          borderRadius: 4,
        },
        {
          label: "Reach pagado",
          data: canales.map(c => data.reach_pagado_por_canal?.[c] || 0),
          backgroundColor: "#E67E22",
          borderRadius: 4,
        },
      ],
    };
  })();

  return (
    <div>
      {!compact && <div style={{ fontWeight:600, fontSize:15, marginBottom:14, color:"#6c63ff" }}>{data.marca_nombre}</div>}
      <div style={{ display:"grid", gridTemplateColumns: hasPaid ? "repeat(4,1fr)" : "repeat(5,1fr)", gap:12, marginBottom:20 }}>
        <KpiCard label="Reach orgánico" value={data.kpis.reach_organico ?? data.kpis.reach} />
        <KpiCard label="Publicaciones" value={data.kpis.publicaciones} color="#1d9e75" />
        <KpiCard label="Likes" value={data.kpis.likes} color="#D4537E" />
        <KpiCard label="Shares" value={data.kpis.shares} color="#185FA5" />
        {!hasPaid && <KpiCard label="Comentarios" value={data.kpis.comments} color="#f59e0b" />}
      </div>
      {hasPaid && (
        <div style={{ display:"grid", gridTemplateColumns:"repeat(3,1fr)", gap:12, marginBottom:20 }}>
          <div style={{ ...s.kpiCard, border:"1px solid #f0a500", background:"#fef9f0" }}>
            <div style={{ fontSize:22, fontWeight:700, color:"#E67E22" }}>{fmtEuro(data.kpis.inversion_pagada)}</div>
            <div style={{ fontSize:11, color:"#888", marginTop:4 }}>Inversión total</div>
          </div>
          <div style={{ ...s.kpiCard, border:"1px solid #f0a500", background:"#fef9f0" }}>
            <div style={{ fontSize:22, fontWeight:700, color:"#E67E22" }}>{fmtNum(data.kpis.reach_pagado)}</div>
            <div style={{ fontSize:11, color:"#888", marginTop:4 }}>Reach pagado</div>
          </div>
          <div style={{ ...s.kpiCard }}>
            <div style={{ fontSize:22, fontWeight:700, color:"#6c63ff" }}>{fmtNum((data.kpis.reach_organico ?? data.kpis.reach) + data.kpis.reach_pagado)}</div>
            <div style={{ fontSize:11, color:"#888", marginTop:4 }}>Reach total combinado</div>
          </div>
        </div>
      )}

      {!compact && (
        <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:16, marginBottom:16 }}>
          <div style={s.chartBox}>
            <div style={{ fontSize:13, fontWeight:600, marginBottom:12 }}>Reach por canal {hasPaid ? "(orgánico + pagado)" : ""}</div>
            {hasPaid && stackedReachData ? (
              <ChartCanvas
                type="bar"
                data={stackedReachData}
                options={{ scales: { x: { stacked:true }, y: { stacked:true, ticks: { callback: v => fmtNum(v) } } }, plugins: { legend: { position:"bottom" } } }}
                height={200}
              />
            ) : (
              <MarcaReachBars data={data.reach_por_canal} />
            )}
          </div>
          <div style={s.chartBox}>
            <div style={{ fontSize:13, fontWeight:600, marginBottom:12 }}>Distribución porcentual</div>
            <DistribucionPorcentual
              reach={data.reach_por_canal}
              likes={data.likes_por_canal}
              shares={data.shares_por_canal}
              comments={data.comments_por_canal}
            />
          </div>
        </div>
      )}

      {compact && (
        <div style={{ marginBottom:12 }}>
          <div style={{ fontSize:12, fontWeight:600, marginBottom:8 }}>Reach por canal</div>
          <MarcaReachBars data={data.reach_por_canal} />
        </div>
      )}

      {!compact && semanalData?.semanas?.length > 0 && (
        <div style={s.chartBox}>
          <div style={{ fontSize:13, fontWeight:600, marginBottom:8, display:"flex", alignItems:"center", gap:10 }}>
            <span>
              Crecimiento semanal de reach
              {semanalData.series.some(s => s.fallback) && (
                <span style={{ fontSize:11, color:"#f59e0b", fontWeight:400, marginLeft:8 }}>
                  ⚠ usando reach acumulado
                </span>
              )}
            </span>
            {selCanal && (
              <button onClick={() => setSelCanal(null)}
                style={{ fontSize:11, padding:"2px 8px", background:"#f0f0ff", border:"1px solid #c5c2f0",
                  borderRadius:12, cursor:"pointer", color:"#6c63ff" }}>
                ✕ {CANAL_LABELS[selCanal] || selCanal}
              </button>
            )}
          </div>
          <ChartCanvas
            type="line"
            data={{
              labels: semanalData.semanas,
              datasets: buildSemanalDatasets(semanalData, selCanal),
            }}
            options={{
              scales: DUAL_AXIS_SCALES,
              plugins: {
                legend: {
                  position: "bottom",
                  onClick: (_e, legendItem) => {
                    const canal = semanalData.series[legendItem.datasetIndex]?.canal;
                    if (canal) setSelCanal(prev => prev === canal ? null : canal);
                  },
                },
                tooltip: { callbacks: {
                  label: ctx => {
                    const ser = semanalData.series[ctx.datasetIndex];
                    return `${ctx.dataset.label}: ${ser?.fallback ? "reach acum" : "+reach"} ${fmtNum(ctx.raw)}`;
                  },
                  afterLabel: ctx => {
                    const ser = semanalData.series[ctx.datasetIndex];
                    if (ser?.fallback) return null;
                    const idx = ctx.dataIndex;
                    const acum = ser.data.slice(0, idx + 1).reduce((a, b) => a + b, 0);
                    const prev = idx > 0 ? ser.data[idx - 1] : null;
                    const lines = [`Acumulado: ${fmtNum(acum)}`];
                    if (prev != null && prev > 0) {
                      const pct = ((ctx.raw - prev) / prev * 100).toFixed(1);
                      lines.push(`vs anterior: ${pct >= 0 ? "+" : ""}${pct}%`);
                    }
                    return lines;
                  },
                }},
              },
            }}
            height={220}
          />
        </div>
      )}
      {!compact && !semanalData?.semanas?.length && lineData && (
        <div style={s.chartBox}>
          <div style={{ fontSize:13, fontWeight:600, marginBottom:12 }}>Evolución mensual de reach</div>
          <ChartCanvas type="line" data={lineData} height={220} />
        </div>
      )}

      {!compact && data.ultimas_publicaciones?.length > 0 && (
        <div style={s.chartBox}>
          <div style={{ fontSize:13, fontWeight:600, marginBottom:12 }}>Últimas publicaciones</div>
          {data.ultimas_publicaciones.map(p => (
            <div key={p.id} style={{ display:"flex", justifyContent:"space-between", alignItems:"center", padding:"8px 0", borderBottom:"1px solid #f5f5f5" }}>
              <div style={{ flex:1, minWidth:0 }}>
                <CanalDot canal={p.canal} />
                <span style={{ marginLeft:8, fontSize:12, color:"#555" }}>{p.titulo || "Sin título"}</span>
              </div>
              <div style={{ display:"flex", gap:16, alignItems:"center", flexShrink:0 }}>
                <span style={{ fontSize:12, color:"#888" }}>{fmtDate(p.fecha_publicacion)}</span>
                <span style={{ fontSize:13, fontWeight:500, color:"#6c63ff" }}>{fmtNum(p.reach)}</span>
                {p.url && <a href={p.url} target="_blank" rel="noreferrer" style={{ color:"#6c63ff", fontSize:12, textDecoration:"none" }}>↗</a>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// Canales de escala pequeña (Web) → eje Y derecho en gráficas duales
const WEB_CANALES = ["web"];

function buildSemanalDatasets(sem, selectedCanal) {
  return sem.series.map(ser => {
    const base = CANAL_COLORS[ser.canal] || "#999";
    const dimmed = selectedCanal && selectedCanal !== ser.canal;
    const color = dimmed ? base + "44" : base;
    return {
      label: CANAL_LABELS[ser.canal] || ser.canal,
      data: ser.data,
      borderColor: color,
      pointBackgroundColor: color,
      backgroundColor: "transparent",
      tension: 0.3,
      pointRadius: 3,
      borderDash: ser.fallback ? [4, 4] : [],
      yAxisID: WEB_CANALES.includes(ser.canal) ? "y1" : "y",
    };
  });
}

const DUAL_AXIS_SCALES = {
  y: {
    type: "linear", position: "left",
    ticks: { callback: v => fmtNum(v) },
    title: { display: true, text: "RRSS", font: { size: 11 } },
  },
  y1: {
    type: "linear", position: "right",
    ticks: { callback: v => fmtNum(v) },
    grid: { drawOnChartArea: false },
    title: { display: true, text: "Web", font: { size: 11 } },
  },
};

function AnalyticsPage({ slug, api }) {
  const [tab, setTab] = useState("resumen");
  const [marcas, setMarcas] = useState([]);
  const [periodo, setPeriodo] = useState("3m");
  const [fechaDesde, setFechaDesde] = useState("");
  const [fechaHasta, setFechaHasta] = useState("");

  // Resumen tab
  const [resumen, setResumen] = useState(null);
  const [loadingResumen, setLoadingResumen] = useState(false);

  // Marca tab
  const [marcaId, setMarcaId] = useState("");
  const [marcaData, setMarcaData] = useState(null);
  const [loadingMarca, setLoadingMarca] = useState(false);

  // Comparar tab
  const [marcaA, setMarcaA] = useState("");
  const [marcaB, setMarcaB] = useState("");
  const [compararData, setCompararData] = useState(null);
  const [loadingComparar, setLoadingComparar] = useState(false);

  // Canal tab
  const [canal, setCanal] = useState("instagram_post");
  const [canalData, setCanalData] = useState(null);
  const [loadingCanal, setLoadingCanal] = useState(false);

  // Semanal — para resumen y marca
  const [semanal, setSemanal] = useState(null);
  const [marcaSemanal, setMarcaSemanal] = useState(null);

  // Filtrado cruzado
  const [selectedCanal, setSelectedCanal] = useState(null);   // leyenda semanal resumen
  const [selectedMarca, setSelectedMarca] = useState(null);   // top marcas → filtra semanal
  const [semanalFiltrada, setSemanalFiltrada] = useState(null); // semanal para marca seleccionada

  useEffect(() => {
    api("GET", `/medios/${slug}/marcas`).then(setMarcas).catch(() => {});
  }, [slug]);

  // Cuando se selecciona una marca en top marcas, carga semanal filtrada
  useEffect(() => {
    if (!selectedMarca) { setSemanalFiltrada(null); return; }
    const semP = new URLSearchParams({ marca_id: selectedMarca.id });
    if (periodo !== "custom") semP.set("periodo", periodo);
    if (fechaDesde) semP.set("fecha_desde", fechaDesde);
    if (fechaHasta) semP.set("fecha_hasta", fechaHasta);
    api("GET", `/medios/${slug}/analytics/semanal?${semP}`)
      .then(setSemanalFiltrada).catch(() => {});
  }, [selectedMarca, periodo, fechaDesde, fechaHasta, slug]);

  const periodoP = () => {
    const p = new URLSearchParams();
    if (periodo === "custom") {
      if (fechaDesde) p.set("fecha_desde", fechaDesde);
      if (fechaHasta) p.set("fecha_hasta", fechaHasta);
    } else {
      p.set("periodo", periodo);
    }
    return p.toString();
  };

  // Auto-load resumen and canal tabs
  useEffect(() => {
    if (tab !== "resumen") return;
    setLoadingResumen(true);
    const pp = periodoP();
    Promise.all([
      api("GET", `/medios/${slug}/analytics/resumen?${pp}`),
      api("GET", `/medios/${slug}/analytics/semanal?${pp}`),
    ]).then(([res, sem]) => {
      setResumen(res);
      setSemanal(sem);
      console.log("[Semanal resumen]", sem);
    })
      .catch(() => {})
      .finally(() => setLoadingResumen(false));
  }, [tab, periodo, fechaDesde, fechaHasta, slug]);

  useEffect(() => {
    if (tab !== "canal") return;
    setLoadingCanal(true);
    const p = new URLSearchParams({ canal });
    if (periodo !== "custom") p.set("periodo", periodo);
    if (fechaDesde) p.set("fecha_desde", fechaDesde);
    if (fechaHasta) p.set("fecha_hasta", fechaHasta);
    api("GET", `/medios/${slug}/analytics/resumen?${p}`)
      .then(setCanalData).catch(() => {}).finally(() => setLoadingCanal(false));
  }, [tab, canal, periodo, fechaDesde, fechaHasta, slug]);

  const loadMarca = () => {
    if (!marcaId) return;
    setLoadingMarca(true);
    const pp = periodoP();
    const semP = new URLSearchParams({ marca_id: marcaId });
    if (periodo === "custom") {
      if (fechaDesde) semP.set("fecha_desde", fechaDesde);
      if (fechaHasta) semP.set("fecha_hasta", fechaHasta);
    }
    Promise.all([
      api("GET", `/medios/${slug}/analytics/marca/${marcaId}?${pp}`),
      api("GET", `/medios/${slug}/analytics/semanal?${semP}`),
    ]).then(([marca, sem]) => {
      setMarcaData(marca);
      setMarcaSemanal(sem);
      console.log("[Semanal marca]", sem);
    })
      .catch(() => {})
      .finally(() => setLoadingMarca(false));
  };

  const loadComparar = () => {
    if (!marcaA || !marcaB) return;
    setLoadingComparar(true);
    const p = new URLSearchParams({ marca_a: marcaA, marca_b: marcaB });
    if (periodo !== "custom") p.set("periodo", periodo);
    if (fechaDesde) p.set("fecha_desde", fechaDesde);
    if (fechaHasta) p.set("fecha_hasta", fechaHasta);
    api("GET", `/medios/${slug}/analytics/comparar?${p}`)
      .then(setCompararData).catch(() => {}).finally(() => setLoadingComparar(false));
  };

  // Stacked bar chart data for resumen
  const resumenChartData = resumen?.meses?.length > 0 ? {
    labels: resumen.meses,
    datasets: Object.entries(resumen.canales || {}).map(([c, vals]) => ({
      label: CANAL_LABELS[c] || c,
      data: vals,
      backgroundColor: CANAL_COLORS[c] || "#999",
    })),
  } : null;

  // Top marcas horizontal bar (con highlighting por marca seleccionada)
  const topMarcasData = resumen?.top_marcas?.length > 0 ? {
    labels: resumen.top_marcas.map(m => m.nombre),
    datasets: [{
      label: "Reach",
      data: resumen.top_marcas.map(m => m.reach),
      backgroundColor: resumen.top_marcas.map(m =>
        selectedMarca && selectedMarca.id !== m.id ? "#6c63ff44" : "#6c63ff"
      ),
      borderRadius: 4,
    }],
  } : null;

  const tabs = [
    ["resumen","Resumen general"],
    ["marca","Dashboard marca"],
    ["comparar","Comparar marcas"],
    ["canal","Por canal"],
  ];

  return (
    <div>
      <h2 style={s.h2}>Analytics</h2>

      {/* Selector de período (global) */}
      <div style={{ ...s.card, paddingTop:16, paddingBottom:16, marginBottom:16 }}>
        <PeriodSelector
          periodo={periodo} setPeriodo={setPeriodo}
          fechaDesde={fechaDesde} setFechaDesde={setFechaDesde}
          fechaHasta={fechaHasta} setFechaHasta={setFechaHasta}
        />
      </div>

      {/* Tabs */}
      <div style={s.tabBar}>
        {tabs.map(([k,l]) => (
          <button key={k} style={s.tabBtn(tab===k)} onClick={() => setTab(k)}>{l}</button>
        ))}
      </div>

      {/* Resumen general */}
      {tab === "resumen" && (
        <div>
          {loadingResumen ? (
            <div style={{ textAlign:"center", padding:40, color:"#aaa" }}>Cargando...</div>
          ) : !resumen || !resumen.meses?.length ? (
            <div style={{ ...s.card, color:"#aaa", textAlign:"center", padding:40 }}>Sin datos para el período seleccionado</div>
          ) : (
            <>
              <div style={s.chartBox}>
                <div style={{ fontSize:14, fontWeight:600, marginBottom:16 }}>Reach por canal y mes</div>
                {resumenChartData && (
                  <ChartCanvas
                    type="bar"
                    data={resumenChartData}
                    options={{ scales: { x: { stacked:true }, y: { stacked:true, ticks: { callback: v => fmtNum(v) } } } }}
                    height={300}
                  />
                )}
              </div>
              <div style={s.chartBox}>
                <div style={{ fontSize:14, fontWeight:600, marginBottom:8, display:"flex", alignItems:"center", gap:10 }}>
                  <span>Top 10 marcas por reach</span>
                  {selectedMarca && (
                    <button onClick={() => setSelectedMarca(null)}
                      style={{ fontSize:11, padding:"2px 8px", background:"#f0f0ff", border:"1px solid #c5c2f0",
                        borderRadius:12, cursor:"pointer", color:"#6c63ff" }}>
                      ✕ {selectedMarca.nombre}
                    </button>
                  )}
                </div>
                {topMarcasData && (
                  <ChartCanvas
                    type="bar"
                    data={topMarcasData}
                    options={{
                      indexAxis: "y",
                      onClick: (_e, elements) => {
                        if (!elements.length) return;
                        const m = resumen.top_marcas[elements[0].index];
                        if (m) setSelectedMarca(prev => prev?.id === m.id ? null : m);
                      },
                      plugins: { legend: { display: false } },
                      scales: { x: { ticks: { callback: v => fmtNum(v) } } },
                    }}
                    height={320}
                  />
                )}
              </div>
              {(() => {
                const semData = semanalFiltrada || semanal;
                if (!semData?.semanas?.length) return null;
                const hasFallback = semData.series.some(s => s.fallback);
                return (
                  <div style={s.chartBox}>
                    <div style={{ fontSize:14, fontWeight:600, marginBottom:8, display:"flex", alignItems:"center", gap:10, flexWrap:"wrap" }}>
                      <span>
                        Crecimiento semanal de reach por canal
                        {selectedMarca && <span style={{ fontSize:12, fontWeight:400, color:"#6c63ff" }}> — {selectedMarca.nombre}</span>}
                        {hasFallback && (
                          <span style={{ fontSize:11, color:"#f59e0b", fontWeight:400, marginLeft:8 }}>
                            ⚠ reach_diff=0 — mostrando reach acumulado
                          </span>
                        )}
                      </span>
                      {selectedCanal && (
                        <button onClick={() => setSelectedCanal(null)}
                          style={{ fontSize:11, padding:"2px 8px", background:"#f0f0ff", border:"1px solid #c5c2f0",
                            borderRadius:12, cursor:"pointer", color:"#6c63ff" }}>
                          ✕ {CANAL_LABELS[selectedCanal] || selectedCanal}
                        </button>
                      )}
                    </div>
                    <ChartCanvas
                      type="line"
                      data={{
                        labels: semData.semanas,
                        datasets: buildSemanalDatasets(semData, selectedCanal),
                      }}
                      options={{
                        scales: DUAL_AXIS_SCALES,
                        plugins: {
                          legend: {
                            position: "bottom",
                            onClick: (_e, legendItem) => {
                              const canal = semData.series[legendItem.datasetIndex]?.canal;
                              if (canal) setSelectedCanal(prev => prev === canal ? null : canal);
                            },
                          },
                          tooltip: { callbacks: {
                            label: ctx => {
                              const ser = semData.series[ctx.datasetIndex];
                              return `${ctx.dataset.label}: ${ser?.fallback ? "reach acum" : "+reach"} ${fmtNum(ctx.raw)}`;
                            },
                          }},
                        },
                      }}
                      height={280}
                    />
                  </div>
                );
              })()}
            </>
          )}
        </div>
      )}

      {/* Dashboard marca */}
      {tab === "marca" && (
        <div>
          <div style={{ display:"flex", gap:10, marginBottom:20, alignItems:"flex-end" }}>
            <div>
              <div style={{ fontSize:11, color:"#888", marginBottom:4 }}>Marca</div>
              <select style={s.select} value={marcaId} onChange={e => setMarcaId(e.target.value)}>
                <option value="">Seleccionar marca</option>
                {marcas.map(m => <option key={m.id} value={m.id}>{m.nombre_canonico}</option>)}
              </select>
            </div>
            <button style={s.btn()} onClick={loadMarca} disabled={!marcaId || loadingMarca}>
              {loadingMarca ? "Cargando..." : "Ver dashboard"}
            </button>
          </div>
          {marcaData && <MarcaAnalyticsView data={marcaData} semanalData={marcaSemanal} />}
          {!marcaData && !loadingMarca && (
            <div style={{ ...s.card, color:"#aaa", textAlign:"center", padding:40 }}>
              Selecciona una marca y pulsa "Ver dashboard"
            </div>
          )}
        </div>
      )}

      {/* Comparar marcas */}
      {tab === "comparar" && (
        <div>
          <div style={{ display:"flex", gap:10, marginBottom:20, alignItems:"flex-end", flexWrap:"wrap" }}>
            <div>
              <div style={{ fontSize:11, color:"#888", marginBottom:4 }}>Marca A</div>
              <select style={s.select} value={marcaA} onChange={e => setMarcaA(e.target.value)}>
                <option value="">Seleccionar</option>
                {marcas.map(m => <option key={m.id} value={m.id}>{m.nombre_canonico}</option>)}
              </select>
            </div>
            <div style={{ paddingBottom:8, color:"#aaa", fontSize:16 }}>VS</div>
            <div>
              <div style={{ fontSize:11, color:"#888", marginBottom:4 }}>Marca B</div>
              <select style={s.select} value={marcaB} onChange={e => setMarcaB(e.target.value)}>
                <option value="">Seleccionar</option>
                {marcas.map(m => <option key={m.id} value={m.id}>{m.nombre_canonico}</option>)}
              </select>
            </div>
            <button style={s.btn()} onClick={loadComparar} disabled={!marcaA || !marcaB || loadingComparar}>
              {loadingComparar ? "Comparando..." : "Comparar"}
            </button>
          </div>

          {compararData ? (
            <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:20 }}>
              <div style={{ ...s.card, borderTop:"3px solid #6c63ff" }}>
                <div style={{ fontWeight:700, fontSize:15, color:"#6c63ff", marginBottom:16 }}>
                  {compararData.marca_a.marca_nombre}
                </div>
                <MarcaAnalyticsView data={compararData.marca_a} compact={true} />
              </div>
              <div style={{ ...s.card, borderTop:"3px solid #D4537E" }}>
                <div style={{ fontWeight:700, fontSize:15, color:"#D4537E", marginBottom:16 }}>
                  {compararData.marca_b.marca_nombre}
                </div>
                <MarcaAnalyticsView data={compararData.marca_b} compact={true} />
              </div>
            </div>
          ) : !loadingComparar && (
            <div style={{ ...s.card, color:"#aaa", textAlign:"center", padding:40 }}>
              Selecciona dos marcas y pulsa "Comparar"
            </div>
          )}
        </div>
      )}

      {/* Por canal */}
      {tab === "canal" && (
        <div>
          <div style={{ display:"flex", gap:10, marginBottom:20, alignItems:"flex-end" }}>
            <div>
              <div style={{ fontSize:11, color:"#888", marginBottom:4 }}>Canal</div>
              <select style={s.select} value={canal} onChange={e => setCanal(e.target.value)}>
                {Object.entries(CANAL_LABELS).map(([v,l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </div>
          </div>

          {loadingCanal ? (
            <div style={{ textAlign:"center", padding:40, color:"#aaa" }}>Cargando...</div>
          ) : !canalData || !canalData.meses?.length ? (
            <div style={{ ...s.card, color:"#aaa", textAlign:"center", padding:40 }}>Sin datos para este canal en el período</div>
          ) : (
            <>
              {/* Evolución del canal */}
              {canalData.canales[canal] && (
                <div style={s.chartBox}>
                  <div style={{ fontSize:14, fontWeight:600, marginBottom:16 }}>
                    Evolución mensual — <span style={{ color:CANAL_COLORS[canal] }}>{CANAL_LABELS[canal]}</span>
                  </div>
                  <ChartCanvas
                    type="bar"
                    data={{
                      labels: canalData.meses,
                      datasets: [{ label:"Reach", data:canalData.canales[canal], backgroundColor:CANAL_COLORS[canal], borderRadius:4 }],
                    }}
                    options={{ plugins:{ legend:{ display:false } }, scales:{ y:{ ticks:{ callback: v => fmtNum(v) } } } }}
                    height={260}
                  />
                </div>
              )}
              {/* Top marcas en ese canal */}
              {canalData.top_marcas?.length > 0 && (
                <div style={s.chartBox}>
                  <div style={{ fontSize:14, fontWeight:600, marginBottom:16 }}>Top marcas en {CANAL_LABELS[canal]}</div>
                  <ChartCanvas
                    type="bar"
                    data={{
                      labels: canalData.top_marcas.map(m => m.nombre),
                      datasets: [{ label:"Reach", data:canalData.top_marcas.map(m => m.reach), backgroundColor:CANAL_COLORS[canal]||"#6c63ff", borderRadius:4 }],
                    }}
                    options={{ indexAxis:"y", plugins:{ legend:{ display:false } }, scales:{ x:{ ticks:{ callback: v => fmtNum(v) } } } }}
                    height={280}
                  />
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

// ── Medios list ───────────────────────────────────────────────────────────────
function MediosList({ api, onSelect }) {
  const [medios, setMedios] = useState([]);
  const [modal, setModal] = useState(false);
  const [form, setForm] = useState({ slug:"", nombre:"", url_web:"", rss_url:"" });
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try { setMedios(await api("GET", "/medios")); } catch(ex) { setErr(ex.message); }
  }, [api]);
  useEffect(() => { load(); }, [load]);

  const create = async () => {
    setErr("");
    try { await api("POST", "/medios", form); setModal(false); setForm({slug:"",nombre:"",url_web:"",rss_url:""}); await load(); }
    catch(ex) { setErr(ex.message); }
  };

  return (
    <div>
      <Alert msg={err} type="error" onClose={()=>setErr("")} />
      <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:20}}>
        <h2 style={s.h2}>Medios configurados</h2>
        <button style={s.btn()} onClick={()=>setModal(true)}>+ Nuevo medio</button>
      </div>
      <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fill,minmax(280px,1fr))",gap:16}}>
        {medios.map(m => (
          <div key={m.slug} style={{...s.card,cursor:"pointer",transition:"box-shadow .15s",padding:20}} onClick={()=>onSelect(m.slug)}
            onMouseEnter={e=>e.currentTarget.style.boxShadow="0 4px 16px rgba(108,99,255,.15)"}
            onMouseLeave={e=>e.currentTarget.style.boxShadow="0 1px 3px rgba(0,0,0,.07)"}>
            <div style={{display:"flex",justifyContent:"space-between",alignItems:"flex-start"}}>
              <div>
                <div style={{fontWeight:700,fontSize:16,color:"#6c63ff"}}>@{m.slug}</div>
                <div style={{fontSize:13,color:"#555",marginTop:2}}>{m.nombre}</div>
                {m.url_web && <div style={{fontSize:11,color:"#aaa",marginTop:4}}>{m.url_web}</div>}
              </div>
              <span style={s.badge(m.activo?"activa":"inactiva")}>{m.activo?"activo":"inactivo"}</span>
            </div>
            <div style={{marginTop:14,fontSize:12,color:"#888"}}>Haz clic para configurar →</div>
          </div>
        ))}
        {medios.length === 0 && <div style={{...s.card,color:"#aaa",textAlign:"center",padding:40}}>No hay medios. Crea el primero.</div>}
      </div>
      {modal && (
        <Modal title="Nuevo medio" onClose={()=>setModal(false)}>
          <div style={{display:"flex",flexDirection:"column",gap:12}}>
            <div><label style={{fontSize:12,color:"#888",display:"block",marginBottom:4}}>Slug (único, sin espacios) *</label><input style={{...s.input,width:"100%",boxSizing:"border-box"}} value={form.slug} onChange={e=>setForm({...form,slug:e.target.value.toLowerCase().replace(/\s/g,"")})} placeholder="roadrunningreview" /></div>
            <div><label style={{fontSize:12,color:"#888",display:"block",marginBottom:4}}>Nombre del medio *</label><input style={{...s.input,width:"100%",boxSizing:"border-box"}} value={form.nombre} onChange={e=>setForm({...form,nombre:e.target.value})} placeholder="ROADRUNNINGReview" /></div>
            <div><label style={{fontSize:12,color:"#888",display:"block",marginBottom:4}}>URL web</label><input style={{...s.input,width:"100%",boxSizing:"border-box"}} value={form.url_web} onChange={e=>setForm({...form,url_web:e.target.value})} placeholder="https://roadrunningreview.com" /></div>
            <div><label style={{fontSize:12,color:"#888",display:"block",marginBottom:4}}>URL del RSS</label><input style={{...s.input,width:"100%",boxSizing:"border-box"}} value={form.rss_url} onChange={e=>setForm({...form,rss_url:e.target.value})} placeholder="https://roadrunningreview.com/feed" /></div>
            <div style={{display:"flex",gap:8,justifyContent:"flex-end",marginTop:8}}>
              <button style={s.btn("ghost")} onClick={()=>setModal(false)}>Cancelar</button>
              <button style={s.btn()} onClick={create}>Crear medio</button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}

// ── App root ──────────────────────────────────────────────────────────────────
export default function App() {
  const { token, login, logout } = useAuth();
  const api = useApi(token);
  const [page, setPage] = useState("medios");
  const [selectedMedio, setSelectedMedio] = useState(null);

  if (!token) return <LoginPage onLogin={login} />;

  const selectMedio = (slug) => { setSelectedMedio(slug); setPage("config"); };
  const back = () => { setSelectedMedio(null); setPage("medios"); };

  const navMedio = (p) => setPage(p);

  return (
    <div style={s.app}>
      {/* Sidebar */}
      <div style={s.sidebar}>
        <div style={s.sidebarTitle}>
          <div>Social Intelligence</div>
          <div style={s.sidebarSub}>Panel de gestión</div>
        </div>

        <div
          style={s.navItem(!selectedMedio && page === "medios")}
          onClick={back}
        >
          Medios
        </div>

        {selectedMedio && (
          <>
            <div style={{ padding:"10px 20px 4px", fontSize:11, color:"#555", textTransform:"uppercase", letterSpacing:"0.08em", fontWeight:600, borderTop:"1px solid #2d2d4e", marginTop:8 }}>
              @{selectedMedio}
            </div>
            <div style={s.navSubItem(page === "config")} onClick={() => navMedio("config")}>Configuración</div>
            <div style={s.navSubItem(page === "publicaciones")} onClick={() => navMedio("publicaciones")}>Publicaciones</div>
            <div style={s.navSubItem(page === "analytics")} onClick={() => navMedio("analytics")}>Analytics</div>
          </>
        )}

        <div style={{ flex:1 }} />
        <div style={{ padding:"0 20px" }}>
          <button style={{ ...s.btn("ghost"), width:"100%", color:"#aaa", fontSize:12 }} onClick={logout}>
            Cerrar sesión
          </button>
        </div>
      </div>

      {/* Main content */}
      <div style={s.main}>
        {page === "medios" && <MediosList api={api} onSelect={selectMedio} />}

        {selectedMedio && page === "config" && (
          <div>
            <div style={{ display:"flex", alignItems:"center", gap:12, marginBottom:24 }}>
              <button style={s.btn("ghost")} onClick={back}>← Volver</button>
              <h2 style={{ margin:0, fontSize:20, fontWeight:700, color:"#6c63ff" }}>@{selectedMedio}</h2>
            </div>
            <MedioConfig slug={selectedMedio} api={api} />
          </div>
        )}

        {selectedMedio && page === "publicaciones" && (
          <PublicacionesPage slug={selectedMedio} api={api} />
        )}

        {selectedMedio && page === "analytics" && (
          <AnalyticsPage slug={selectedMedio} api={api} />
        )}
      </div>
    </div>
  );
}
