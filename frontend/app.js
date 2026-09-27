const $ = (id) => document.getElementById(id);
let presets = [];

marked.setOptions({ gfm: true, breaks: false });

/* ── Selskapet: klientens egen beskrivelse ───────────────────── */
// Lagres på serveren, ikke i nettleseren: det er CFO-en som skal lese den, og
// den gjelder selskapet — ikke maskinen noen tilfeldigvis satt ved.
let coLoaded = false;

function renderKnown(d) {
  const used = new Set(d.used_in_calculations || []);
  $("coKnown").innerHTML = Object.entries(d.known_settings || {}).map(
    ([k, what]) => `<li class="${used.has(k) ? "on" : ""}">
      <code>${k}</code><span>${what}</span>
      <b>${used.has(k) ? "i bruk: " + d.settings[k] : "ikke satt"}</b></li>`).join("");
  const notes = d.notes || [];
  $("coNotes").innerHTML = notes.map((n) => `<p>${n}</p>`).join("");
  $("coNotes").hidden = !notes.length;
}

async function showCompany() {
  activeId = null;
  show("selskapet");
  document.title = "Selskapet · CFO";
  renderList();
  window.scrollTo(0, 0);
  if (coLoaded) return;
  try {
    const d = await (await fetch("/api/company")).json();
    $("coText").value = d.text || "";
    renderKnown(d);
    coLoaded = true;
  } catch (e) {
    $("coStatus").textContent = "Fikk ikke hentet teksten.";
    console.error("company", e);
  }
}

async function saveCompany() {
  const btn = $("coSave"), status = $("coStatus");
  btn.disabled = true;
  status.textContent = "Lagrer …";
  status.className = "co-status";
  try {
    const r = await fetch("/api/company", {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: $("coText").value }),
    });
    if (!r.ok) throw new Error((await r.text()).slice(0, 200));
    const d = await r.json();
    renderKnown(d);
    status.textContent = "Lagret. CFO-en bruker den fra neste spørsmål.";
    status.className = "co-status ok";
  } catch (e) {
    status.textContent = "Kunne ikke lagre: " + e.message;
    status.className = "co-status bad";
    console.error("company save", e);
  } finally {
    btn.disabled = false;
  }
}

document.addEventListener("click", (e) => {
  if (e.target.closest("#coSave")) saveCompany();
});

async function boot() {
  try {
    const h = await (await fetch("/api/health")).json();
    $("company").textContent = h.company;
  } catch { $("company").textContent = "CFO"; }

  try {
    ({ presets } = await (await fetch("/api/presets")).json());
    fillChips($("chips"));
  } catch { $("chips").hidden = true; }

  Brief.load();
  if (location.hash !== "#saker") Brief.loadDeck();   // bare for tellingen
  $("briefRefresh").addEventListener("click", () => {
    $("briefRefresh").disabled = true;
    Brief.load();
  });
}

/* ── samtaler: lagres i nettleseren ──────────────────────────── */
// Backend holder historikken i minnet, per session_id. Her ligger listen og
// det som ble sagt, slik at en samtale kan åpnes igjen og spørres videre i.
const STORE = "cfo.conversations.v1";
const MAX_CONVS = 60;
let convs = load();
let activeId = null;

function load() {
  try {
    const v = JSON.parse(localStorage.getItem(STORE) || "[]");
    if (!Array.isArray(v)) return [];
    for (const c of v) for (const m of c.messages || []) {
      if (m.role !== "assistant") continue;
      // Samtaler lagret før arbeidssporet fantes, hadde bare en liste verktøy.
      if (!m.steps) m.steps = (m.acts || []).map((a) => ({ kind: "tool", label: a.label, n: 1, done: true }));
      delete m.acts;
      // Et svar som var underveis da siden ble lukket, blir aldri ferdig.
      if (!m.done) {
        m.done = true;
        m.error = m.error || "Svaret ble avbrutt før det var ferdig.";
      }
    }
    return v;
  } catch { return []; }
}
function save() {
  try {
    localStorage.setItem(STORE, JSON.stringify(convs.slice(0, MAX_CONVS),
      (k, v) => (k.startsWith("_") ? undefined : v)));
  } catch { /* privat modus eller full lagring: samtalen virker likevel */ }
}
const find = (id) => convs.find((c) => c.id === id);
const newId = () => (crypto.randomUUID?.() ||
  Date.now().toString(36) + Math.random().toString(36).slice(2)).replace(/-/g, "");
const clip = (t, n = 64) => (t.length > n ? t.slice(0, n - 1).trimEnd() + "…" : t);

/* ── sidefeltet ──────────────────────────────────────────────── */
function bucket(ts) {
  const d = new Date(ts), now = new Date();
  const day = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = Math.round((day(now) - day(d)) / 864e5);
  if (diff <= 0) return "I dag";
  if (diff === 1) return "I går";
  if (diff < 7) return "Siste 7 dager";
  if (diff < 30) return "Siste 30 dager";
  return "Eldre";
}

function renderList() {
  const list = $("convList");
  list.innerHTML = "";
  $("convEmpty").hidden = convs.length > 0;

  let group = null, ul = null;
  for (const c of convs) {
    const g = bucket(c.updated);
    if (g !== group) {
      group = g;
      const h = document.createElement("p");
      h.className = "side-label"; h.textContent = g;
      ul = document.createElement("ul"); ul.className = "conv-list";
      list.append(h, ul);
    }
    const li = document.createElement("li");
    li.className = "conv" + (c.id === activeId ? " active" : "") + (c._busy ? " busy" : "");
    const a = document.createElement("a");
    a.href = "#c/" + c.id; a.className = "conv-link"; a.title = c.title;
    a.textContent = c.title;
    if (c.id === activeId) a.setAttribute("aria-current", "page");
    const del = document.createElement("button");
    del.className = "conv-del"; del.setAttribute("aria-label", "Slett samtalen");
    del.innerHTML = '<svg viewBox="0 0 20 20" width="13" height="13" aria-hidden="true">' +
      '<path d="M5 5l10 10M15 5 5 15" stroke="currentColor" stroke-width="1.7" ' +
      'stroke-linecap="round"/></svg>';
    del.addEventListener("click", (e) => { e.preventDefault(); removeConv(c.id); });
    li.append(a, del);
    ul.append(li);
  }
}

function removeConv(id) {
  const c = find(id);
  if (!c || !confirm(`Slette «${c.title}»?`)) return;
  c._ctrl?.abort();
  convs = convs.filter((x) => x.id !== id);
  save();
  if (c.sessionId) {
    fetch("/api/session/reset?session_id=" + encodeURIComponent(c.sessionId),
      { method: "POST" }).catch(() => {});
  }
  if (activeId === id) location.hash = "";
  else renderList();
}

const openSidebar = () => {
  document.body.classList.add("side-open"); $("scrim").hidden = false;
};
const closeSidebar = () => {
  document.body.classList.remove("side-open"); $("scrim").hidden = true;
};
/* ── sammenslått sidefelt: bare ikoner ───────────────────────── */
// Tilstanden settes på <html> av et lite skript i <head>, slik at et
// sammenslått sidefelt ikke rekker å blinke i full bredde ved lasting.
const RAIL = "cfo.rail.v1";
const railed = () => document.documentElement.classList.contains("rail-collapsed");
function setRail(collapsed) {
  document.documentElement.classList.toggle("rail-collapsed", collapsed);
  const b = $("railToggle");
  b.setAttribute("aria-expanded", String(!collapsed));
  b.title = collapsed ? "Fold ut menyen" : "Slå sammen menyen";
  try { localStorage.setItem(RAIL, collapsed ? "collapsed" : "open"); } catch { /* ignorér */ }
}
setRail(railed());
$("railToggle").addEventListener("click", () => setRail(!railed()));
// Samtalelista er skjult i ikonmodus, så ikonet folder ut og viser den.
$("railConvs").addEventListener("click", () => {
  setRail(false);
  $("convScroll").scrollTop = 0;
});

$("menuBtn").addEventListener("click", openSidebar);
$("sideClose").addEventListener("click", closeSidebar);
$("scrim").addEventListener("click", closeSidebar);
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeSidebar(); });

/* ── visninger ───────────────────────────────────────────────── */
function route() {
  const m = location.hash.match(/^#c\/([\w-]+)$/);
  if (m && find(m[1])) openConv(m[1]);
  else if (location.hash === "#ny") openConv(null);
  else if (location.hash === "#saker") showSaker();
  else if (location.hash === "#selskapet") showCompany();
  else showHome();
  closeSidebar();
}
window.addEventListener("hashchange", route);

const pages = ["home", "saker", "selskapet", "chat"];
function show(page) {
  pages.forEach((id) => { $(id).hidden = id !== page; });
  $("navHome").classList.toggle("active", page === "home");
  $("navSaker").classList.toggle("active", page === "saker");
  $("navCompany").classList.toggle("active", page === "selskapet");
  // "Ny samtale" lyser bare på en samtale som ennå ikke er lagret.
  $("newChat").classList.toggle("active", page === "chat" && activeId === null);
}

function showHome() {
  activeId = null;
  show("home");
  document.title = "CFO";
  renderList();
  window.scrollTo(0, 0);
}

function showSaker() {
  activeId = null;
  show("saker");
  document.title = "Saker · CFO";
  // Hentes hver gang: en sak kan ha løst seg siden sist man så på den.
  Brief.loadDeck(true);
  renderList();
  window.scrollTo(0, 0);
}

function openConv(id) {
  activeId = id;
  show("chat");
  const c = id && find(id);
  document.title = c ? c.title + " · CFO" : "Ny samtale · CFO";
  renderThread(c);
  $("inputChat").placeholder = c ? "Spør videre …" : "Spør om hva som helst …";
  renderList();
  setComposer();
  window.scrollTo(0, c ? document.body.scrollHeight : 0);
  if (matchMedia("(pointer:fine)").matches) $("inputChat").focus();
}

function setComposer() {
  const c = activeId && find(activeId);
  $("composerChat").querySelector("button").disabled = !!c?._busy;
}

/* ── tråden ──────────────────────────────────────────────────── */
const TICK = '<svg class="tick" viewBox="0 0 16 16" aria-hidden="true">' +
  '<path d="M3.5 8.4l3 3 6-6.8" fill="none" stroke="currentColor" stroke-width="2" ' +
  'stroke-linecap="round" stroke-linejoin="round"/></svg>';
const SPIN = '<span class="spin"></span>';

function renderMarkdown(el, raw) {
  el.innerHTML = marked.parse(raw);
  el.querySelectorAll("table").forEach((t) => {
    if (t.parentElement.classList.contains("table-scroll")) return;
    const w = document.createElement("div"); w.className = "table-scroll";
    t.replaceWith(w); w.append(t);
  });
  el.querySelectorAll("a").forEach((a) => { a.target = "_blank"; a.rel = "noopener noreferrer"; });
}

function fillChips(box) {
  box.innerHTML = "";
  for (const p of presets) {
    const b = document.createElement("button");
    b.className = "chip"; b.type = "button"; b.textContent = p.label;
    b.addEventListener("click", () => ask(p.id, p.label, box === $("chips")));
    box.append(b);
  }
}

function renderThread(c) {
  const thread = $("thread");
  thread.innerHTML = "";
  if (!c || !c.messages.length) {
    thread.innerHTML = `<div class="empty"><h2>Hva lurer du på?</h2>
      <p>Spør om tallene, en kunde, en kostnad eller en plan. Svaret bygger på
         regnskapet deres slik det står i Tripletex nå.</p><div class="chips"></div></div>`;
    fillChips(thread.querySelector(".chips"));
    return;
  }
  for (const m of c.messages) thread.append(msgEl(m));
}

function msgEl(m) {
  const el = document.createElement("div");
  el.className = "msg " + m.role;
  if (m.role === "user") {
    el.innerHTML = '<div class="bubble"></div>';
    el.querySelector(".bubble").textContent = m.text;
  } else {
    el.innerHTML = '<div class="who">CFO</div><div class="work"></div><div class="body-md"></div>';
    m._el = el;
    draw(el, m);
  }
  return el;
}

/* Arbeidssporet: hva den gjorde før den svarte. Åpent mens det står på,
   slått sammen til én linje når svaret er ferdig. */
function summary(m) {
  const looks = m.steps.reduce((n, s) => n + (s.kind === "tool" ? s.n : 0), 0);
  const secs = m.elapsed ? Math.round(m.elapsed / 1000) : null;
  const time = secs == null ? "" : secs >= 60
    ? ` · ${Math.floor(secs / 60)} min ${secs % 60} s` : ` · ${secs} s`;
  if (!looks) return "Tenkte gjennom svaret" + time;
  return `${looks} oppslag i regnskapet${time}`;
}

function status(m) {
  const last = m.steps[m.steps.length - 1];
  if (!last) return "Tenker …";
  if (last.kind === "tool") return last.label + (last.n > 1 ? ` ×${last.n}` : "");
  return "Tenker …";
}

function drawWork(work, m) {
  if (!m.steps.length && m.done) { work.hidden = true; return; }
  work.hidden = false;
  work.classList.toggle("running", !m.done);
  work.classList.toggle("open", !m.done || !!m.open);

  work.innerHTML = `<button class="work-head" type="button">
      <span class="work-icon">${m.done ? TICK : SPIN}</span>
      <span class="work-status"></span>
      <svg class="chev" viewBox="0 0 16 16" width="13" height="13" aria-hidden="true">
        <path d="M4 6.5 8 10.5 12 6.5" fill="none" stroke="currentColor"
              stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>
    </button><div class="work-body"></div>`;

  const head = work.querySelector(".work-head");
  head.querySelector(".work-status").textContent = m.done ? summary(m) : status(m);
  head.setAttribute("aria-expanded", String(!m.done || !!m.open));
  head.disabled = !m.done;
  head.addEventListener("click", () => {
    m.open = !m.open;
    drawWork(work, m);
    save();
  });

  const body = work.querySelector(".work-body");
  const live = !m.done && m.steps.length;
  m.steps.forEach((st, i) => {
    const row = document.createElement("div");
    const last = i === m.steps.length - 1;
    row.className = "step " + st.kind + (live && last ? " live" : "");
    if (st.kind === "tool") {
      row.innerHTML = (last && !m.done ? SPIN : TICK);
      row.append(document.createTextNode(st.label));
      if (st.n > 1) {
        const c = document.createElement("span");
        c.className = "count"; c.textContent = "×" + st.n;
        row.append(c);
      }
    } else {
      row.textContent = st.text;
    }
    body.append(row);
  });
}

// Et svar som strømmer inn mens en annen samtale er åpen, oppdateres bare i
// dataene; elementet tegnes på nytt når samtalen åpnes igjen.
function paintMsg(m) {
  if (m._el?.isConnected) draw(m._el, m);
}

function draw(el, m) {
  drawWork(el.querySelector(".work"), m);
  const body = el.querySelector(".body-md");
  renderMarkdown(body, m.text || "");
  body.hidden = !m.text;
  if (!m.done && m.text) body.insertAdjacentHTML("beforeend", '<span class="caret"></span>');
  el.querySelector(".err")?.remove();
  if (m.error) {
    const e = document.createElement("div");
    e.className = "err"; e.textContent = m.error; el.append(e);
  }
}

const nearBottom = () =>
  window.innerHeight + window.scrollY > document.body.scrollHeight - 160;

/* ── spørsmål og svar ────────────────────────────────────────── */
async function ask(message, shownAs, fresh = false) {
  if (!message.trim()) return;
  let c = !fresh && activeId ? find(activeId) : null;
  if (c?._busy) return;

  const now = Date.now();
  if (!c) {
    c = { id: newId(), title: clip((shownAs || message).trim()), sessionId: null,
          created: now, updated: now, messages: [] };
    convs.unshift(c);
    if (convs.length > MAX_CONVS) convs.length = MAX_CONVS;
    history.pushState(null, "", "#c/" + c.id);
    openConv(c.id);
  }
  const q = { role: "user", text: shownAs || message };
  const m = { role: "assistant", text: "", steps: [], done: false,
              started: now, open: false };
  c.messages.push(q, m);
  c.updated = now;
  convs = [c, ...convs.filter((x) => x !== c)];
  c._busy = true;
  c._ctrl = new AbortController();
  save(); renderList(); setComposer();

  if (activeId === c.id) {
    $("thread").querySelector(".empty")?.remove();
    $("thread").append(msgEl(q), msgEl(m));
    window.scrollTo(0, document.body.scrollHeight);
  }

  // Underveis-prat hører hjemme i sporet, ikke i svaret.
  const stash = (msg) => {
    const t = msg.text.trim();
    if (t) msg.steps.push({ kind: "note", text: t });
    msg.text = "";
  };

  let pending = false;
  const paint = () => {
    pending = false;
    const keep = activeId === c.id && nearBottom();
    paintMsg(m);
    if (keep) window.scrollTo(0, document.body.scrollHeight);
  };
  const schedule = () => { if (!pending) { pending = true; requestAnimationFrame(paint); } };

  try {
    const res = await fetch("/api/chat", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, session_id: c.sessionId }),
      signal: c._ctrl.signal,
    });
    if (!res.ok || !res.body) throw new Error("HTTP " + res.status);
    const reader = res.body.getReader(), dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const frames = buf.split("\n\n"); buf = frames.pop() ?? "";
      for (const f of frames) {
        const line = f.split("\n").find((l) => l.startsWith("data: "));
        if (!line) continue;
        let ev; try { ev = JSON.parse(line.slice(6)); } catch { continue; }
        if (ev.type === "session") { c.sessionId = ev.session_id; save(); }
        else if (ev.type === "tool") {
          // Tekst som kom før et verktøykall var underveis-prat, ikke svaret.
          stash(m);
          const last = m.steps[m.steps.length - 1];
          if (last?.kind === "tool" && last.label === ev.label) last.n += 1;
          else m.steps.push({ kind: "tool", label: ev.label, n: 1 });
          schedule();
        } else if (ev.type === "reasoning") {
          const last = m.steps[m.steps.length - 1];
          if (last?.kind === "think") last.text += ev.text;
          else m.steps.push({ kind: "think", text: ev.text });
          schedule();
        } else if (ev.type === "text") {
          m.text += ev.text;
          schedule();
        } else if (ev.type === "error") {
          m.error = ev.message;
          schedule();
        }
      }
    }
  } catch (err) {
    if (err.name !== "AbortError") m.error = "Mistet forbindelsen. Prøv igjen.";
  } finally {
    m.done = true;
    m.elapsed = Date.now() - m.started;
    // Endte turen på et verktøykall, er siste mellomtekst likevel svaret.
    if (!m.text.trim() && m.steps[m.steps.length - 1]?.kind === "note") {
      m.text = m.steps.pop().text;
    }
    c._busy = false; c._ctrl = null;
    c.updated = Date.now();
    paint(); save(); renderList(); setComposer();
    if (activeId === c.id && matchMedia("(pointer:fine)").matches) $("inputChat").focus();
  }
}

// Brief-en åpner chatten med et ferdig spørsmål om ett av punktene sine.
window.askCFO = (message, shownAs) => ask(message, shownAs, true);

$("composerHome").addEventListener("submit", (e) => {
  e.preventDefault();
  const v = $("inputHome").value; $("inputHome").value = ""; ask(v, null, true);
});
$("composerChat").addEventListener("submit", (e) => {
  e.preventDefault();
  const c = activeId && find(activeId);
  if (c?._busy) return;
  const v = $("inputChat").value; $("inputChat").value = ""; ask(v);
});
route();
boot();
