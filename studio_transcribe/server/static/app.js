"use strict";

const TOKEN_KEY = "st_token";
let CFG = null;
let ws = null;

function token() { return localStorage.getItem(TOKEN_KEY) || ""; }
function setToken(t) { localStorage.setItem(TOKEN_KEY, t); }

async function api(path, opts = {}) {
  const headers = Object.assign({ "X-Auth-Token": token() }, opts.headers || {});
  if (opts.body) headers["Content-Type"] = "application/json";
  const res = await fetch(path, Object.assign({}, opts, { headers }));
  if (res.status === 401) { showLogin(); throw new Error("unauthorized"); }
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (e) {}
    throw new Error(detail);
  }
  const ct = res.headers.get("content-type") || "";
  return ct.includes("application/json") ? res.json() : res.text();
}

/* ---------- login ---------- */
function showLogin() { document.getElementById("login").classList.remove("hidden"); }
function hideLogin() { document.getElementById("login").classList.add("hidden"); }

document.getElementById("loginBtn").onclick = async () => {
  setToken(document.getElementById("loginPassword").value);
  try { await api("/api/status"); hideLogin(); boot(); }
  catch (e) { document.getElementById("loginError").classList.remove("hidden"); }
};
document.getElementById("logoutBtn").onclick = () => { setToken(""); location.reload(); };

/* ---------- tabs ---------- */
document.querySelectorAll(".tab").forEach((t) => {
  t.onclick = () => {
    document.querySelectorAll(".tab").forEach((x) => x.classList.remove("active"));
    document.querySelectorAll(".panel").forEach((x) => x.classList.remove("active"));
    t.classList.add("active");
    document.getElementById(t.dataset.tab).classList.add("active");
    if (t.dataset.tab === "archive") loadSessions();
    if (t.dataset.tab === "settings") loadSettings();
  };
});

/* ---------- status ---------- */
async function loadStatus() {
  const s = await api("/api/status");
  const live = s.live || {};
  setLivePill(!!live.running);
  document.getElementById("liveEngine").textContent = live.engine || s.engine || "—";
  document.getElementById("liveSink").textContent = live.sink || "—";
  document.getElementById("liveActive").textContent =
    (live.active_channels && live.active_channels.join(", ")) || "—";
  const err = document.getElementById("liveError");
  if (live.sink_error) { err.textContent = "אזהרת יעד: " + live.sink_error; err.classList.remove("hidden"); }
  else err.classList.add("hidden");
}

function setLivePill(on) {
  const pill = document.getElementById("statusPill");
  const btn = document.getElementById("liveToggle");
  pill.className = "pill " + (on ? "on" : "off");
  pill.textContent = on ? "פעיל" : "לא פעיל";
  btn.className = "big-btn " + (on ? "stop" : "start");
  btn.textContent = on ? "■ כיבוי כתוביות" : "▶ הדלקת כתוביות חיות";
  btn.dataset.on = on ? "1" : "";
}

document.getElementById("liveToggle").onclick = async () => {
  const on = document.getElementById("liveToggle").dataset.on === "1";
  try {
    await api(on ? "/api/live/stop" : "/api/live/start", { method: "POST" });
    await loadStatus();
  } catch (e) {
    const err = document.getElementById("liveError");
    err.textContent = "שגיאה: " + e.message; err.classList.remove("hidden");
  }
};

/* ---------- websocket ---------- */
function connectWS() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/api/ws?token=${encodeURIComponent(token())}`);
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === "caption") document.getElementById("captions").textContent = msg.text;
    else if (msg.type === "status") loadStatus();
    else if (msg.type === "job") renderJob(msg.job);
  };
  ws.onclose = () => setTimeout(connectWS, 3000);
}

/* ---------- transcribe jobs ---------- */
document.getElementById("trRun").onclick = async () => {
  const input = document.getElementById("trInput").value.trim();
  if (!input) return;
  const formats = [...document.querySelectorAll("#transcribe .formats input:checked")].map((c) => c.value);
  try { await api("/api/transcribe", { method: "POST", body: JSON.stringify({ input, formats }) }); }
  catch (e) { alert("שגיאה: " + e.message); }
};

function renderJob(job) {
  let el = document.getElementById("job-" + job.id);
  if (!el) {
    el = document.createElement("div");
    el.id = "job-" + job.id;
    el.className = "job";
    document.getElementById("jobs").prepend(el);
  }
  const last = job.progress.length ? job.progress[job.progress.length - 1] : "";
  let links = "";
  for (const fmt of Object.keys(job.outputs || {}))
    links += `<a href="/api/jobs/${job.id}/download/${fmt}?token=${encodeURIComponent(token())}">${fmt}</a>`;
  el.innerHTML = `<div class="st">${job.input} — <b>${job.status}</b></div>
    <div class="muted">${job.error || last}</div><div>${links}</div>`;
}

/* ---------- archive ---------- */
document.getElementById("searchBtn").onclick = async () => {
  const q = document.getElementById("searchQuery").value.trim();
  const speaker = document.getElementById("searchSpeaker").value.trim();
  const params = new URLSearchParams({ q });
  if (speaker) params.set("speaker", speaker);
  const hits = await api("/api/search?" + params.toString());
  const box = document.getElementById("searchResults");
  box.innerHTML = hits.length ? "" : '<div class="muted">אין תוצאות</div>';
  for (const h of hits) {
    const div = document.createElement("div");
    div.className = "result";
    div.innerHTML = `<div class="meta">${h.session_name || ""} · ${(h.start || 0).toFixed(1)}s · ${h.speaker || ""}</div>${escapeHtml(h.text)}`;
    box.appendChild(div);
  }
};

async function loadSessions() {
  const rows = await api("/api/sessions");
  const box = document.getElementById("sessions");
  box.innerHTML = rows.length ? "" : '<div class="muted">אין הקלטות שמורות</div>';
  for (const r of rows) {
    const div = document.createElement("div");
    div.className = "session";
    div.innerHTML = `<div class="meta">#${r.id} · ${r.started_at || ""}</div>${escapeHtml(r.name || "")}`;
    box.appendChild(div);
  }
}

/* ---------- settings ---------- */
async function loadSettings() {
  CFG = await api("/api/config");
  document.getElementById("setModel").value = CFG.model || "";
  document.getElementById("setDevice").value = CFG.device || "";
  document.getElementById("setDb").value = CFG.db_path || "";
  const live = CFG.live || {};
  document.getElementById("setSink").value = live.sink || "stdout";
  document.getElementById("setObsSource").value = (live.obs && live.obs.source) || "";
  document.getElementById("setObsHost").value = (live.obs && live.obs.host) || "";
  document.getElementById("setObsPort").value = (live.obs && live.obs.port) || "";
  document.getElementById("setVmixUrl").value = (live.vmix && live.vmix.url) || "";
  document.getElementById("setVmixInput").value = (live.vmix && live.vmix.input) || "";
  document.getElementById("setVmixField").value = (live.vmix && live.vmix.field) || "";
  document.getElementById("setFilePath").value = (live.file && live.file.path) || "";
  renderChannels(CFG.channels || []);
  const g = await api("/api/glossary");
  document.getElementById("glossary").value = g.text || "";
}

function renderChannels(channels) {
  const body = document.getElementById("channelsBody");
  body.innerHTML = "";
  channels.forEach((c) => addChannelRow(c.index, c.speaker, c.enabled !== false));
}
function addChannelRow(index, speaker, enabled) {
  const tr = document.createElement("tr");
  tr.innerHTML = `<td><input type="number" value="${index || 1}" class="ch-idx" /></td>
    <td><input type="text" value="${speaker || ""}" class="ch-spk" /></td>
    <td style="text-align:center"><input type="checkbox" class="ch-en" ${enabled ? "checked" : ""} /></td>
    <td><button class="ghost ch-del">✕</button></td>`;
  tr.querySelector(".ch-del").onclick = () => tr.remove();
  document.getElementById("channelsBody").appendChild(tr);
}
document.getElementById("addChannel").onclick = () =>
  addChannelRow(document.querySelectorAll("#channelsBody tr").length + 1, "", true);

document.getElementById("saveSettings").onclick = async () => {
  if (!CFG) CFG = {};
  CFG.model = document.getElementById("setModel").value;
  CFG.device = document.getElementById("setDevice").value;
  CFG.db_path = document.getElementById("setDb").value || null;
  CFG.channels = [...document.querySelectorAll("#channelsBody tr")].map((tr) => ({
    index: parseInt(tr.querySelector(".ch-idx").value, 10) || 1,
    speaker: tr.querySelector(".ch-spk").value,
    enabled: tr.querySelector(".ch-en").checked,
  }));
  CFG.live = Object.assign(CFG.live || {}, {
    sink: document.getElementById("setSink").value,
    obs: {
      source: document.getElementById("setObsSource").value,
      host: document.getElementById("setObsHost").value || "localhost",
      port: parseInt(document.getElementById("setObsPort").value, 10) || 4455,
      password: (CFG.live && CFG.live.obs && CFG.live.obs.password) || "",
    },
    vmix: {
      url: document.getElementById("setVmixUrl").value,
      input: document.getElementById("setVmixInput").value,
      field: document.getElementById("setVmixField").value || "Headline.Text",
    },
    file: { path: document.getElementById("setFilePath").value || "captions.txt" },
  });
  const msg = document.getElementById("saveMsg");
  try {
    await api("/api/config", { method: "PUT", body: JSON.stringify(CFG) });
    await api("/api/glossary", { method: "PUT", body: JSON.stringify({ text: document.getElementById("glossary").value }) });
    msg.textContent = "נשמר ✓";
  } catch (e) { msg.textContent = "שגיאה: " + e.message; }
  setTimeout(() => (msg.textContent = ""), 3000);
};

function escapeHtml(s) {
  return (s || "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
}

/* ---------- boot ---------- */
async function boot() {
  try {
    await loadStatus();
    connectWS();
  } catch (e) { /* login overlay already shown on 401 */ }
}
boot();
