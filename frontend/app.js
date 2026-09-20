const $ = (id) => document.getElementById(id);
let presets = [];

marked.setOptions({ gfm: true, breaks: false });

/* ── tall på norsk ───────────────────────────────────────────── */
const kr = (n) =>
  n == null ? "–" : Math.round(n).toLocaleString("nb-NO").replace(/ /g, " ");
const mill = (n) => {
  if (n == null) return "–";
  const a = Math.abs(n);
  if (a >= 1e6) return (n / 1e6).toFixed(1).replace(".", ",") + " mill.";
  if (a >= 1e4) return Math.round(n / 1e3) + " 000";
  return kr(n);
};
const pct = (n) => (n == null ? "–" : n.toFixed(1).replace(".", ",") + " %");
const dot = (s) => (String(s).trim().endsWith(".") ? "" : ".");
const N = (text, tone) => `<span class="n${tone ? " " + tone : ""}">${text}</span>`;

/* ── dommen: signaturen på forsiden ──────────────────────────── */
function buildVerdict(k) {
  const rev = k.omsetning, revB = k.omsetning_budsjett;
  const res = k.driftsresultat, resB = k.driftsresultat_budsjett;
  const parts = [];

  if (rev != null && revB) {
    const gap = rev - revB, off = Math.abs(gap / revB);
    const how = off < 0.015
      ? N("på budsjett", "flat")
      : `${N(mill(Math.abs(gap)), gap > 0 ? "up" : "down")} ${gap > 0 ? "over" : "under"} budsjett`;
    parts.push(`Dere har omsatt for ${N(mill(rev))} hittil i år — ${how}.`);
  } else if (rev != null) {
    parts.push(`Dere har omsatt for ${N(mill(rev))} hittil i år.`);
  }

  if (res != null && resB) {
    const gap = res - resB;
    const wageGap = k.lonnsandel_pct != null && k.lonnsandel_budsjett_pct != null
      ? k.lonnsandel_pct - k.lonnsandel_budsjett_pct : null;
    if (gap < 0 && wageGap != null && wageGap > 1) {
      parts.push(
        `Men lønnsandelen er ${N(pct(k.lonnsandel_pct), "down")} mot ` +
        `${N(pct(k.lonnsandel_budsjett_pct))} budsjettert, og det er hele grunnen til at ` +
        `driftsresultatet er ${N(mill(res), "down")} og ikke ${N(mill(resB))}${dot(mill(resB))}`);
    } else if (gap < 0) {
      parts.push(`Driftsresultatet er ${N(mill(res), "down")} mot ${N(mill(resB))} budsjettert.`);
    } else {
      parts.push(`Driftsresultatet er ${N(mill(res), "up")}, ` +
                 `${N(mill(Math.abs(gap)), "up")} bedre enn budsjett.`);
    }
  } else if (res != null) {
    parts.push(`Driftsresultatet er ${N(mill(res))}${dot(mill(res))}`);
  }
  return parts.join(" ") || "Fant ingen tall for perioden.";
}

/* ── forsiden ────────────────────────────────────────────────── */
function renderOverview(d) {
  const k = d.kpis || {};
  $("verdictBlock").classList.remove("loading");
  $("verdict").innerHTML = buildVerdict(k);

  const setFig = (id, val, note) => {
    $(id).textContent = val;
    if (note != null) $(id + "Note").innerHTML = note;
  };
  const gap = (a, b) => {
    if (a == null || !b) return "";
    const g = a - b;
    if (Math.abs(g / b) < 0.015) return "på budsjett";
    return `<span class="${g > 0 ? "up" : "down"}">${g > 0 ? "+" : "−"}${kr(Math.abs(g))}</span> mot budsjett`;
  };
  setFig("fRevenue", kr(k.omsetning), gap(k.omsetning, k.omsetning_budsjett));
  setFig("fResult", kr(k.driftsresultat), gap(k.driftsresultat, k.driftsresultat_budsjett));
  setFig("fCash", kr(k.bank), k.likviditetsgrad != null
    ? `likviditetsgrad ${String(k.likviditetsgrad).replace(".", ",")}` : "");
  setFig("fAr", kr(k.kundefordringer), d.top_debtor
    ? `${d.top_debtor.name} står for ${pct(d.top_debtor.share_pct)}` : "");
  $("figures").hidden = false;

  // lønnsandel
  if (k.lonnsandel_pct != null) {
    const now = k.lonnsandel_pct, target = k.lonnsandel_budsjett_pct;
    const scale = Math.max(100, now + 8);
    const fill = $("gaugeFill");
    fill.style.width = (now / scale * 100) + "%";
    if (target != null && now > target) fill.classList.add("over");
    $("gaugeNow").textContent = pct(now);
    if (now > (target ?? Infinity)) $("gaugeNow").classList.add("over");
    if (target != null) {
      $("gaugeTarget").style.left = (target / scale * 100) + "%";
      $("gaugeTarget").querySelector("span").textContent = "budsjett";
      $("gaugeBudget").textContent = pct(target);
    } else {
      $("gaugeTarget").hidden = true;
    }
    $("gaugeWrap").hidden = false;
  }

  // månedsgraf
  const months = d.revenue_by_month || [];
  if (months.length) {
    const vals = months.map((m) => m.value);
    const peak = Math.max(...vals);
    const last = months.length - 1;
    $("bars").innerHTML = months.map((m, i) => {
      const partial = i === last && m.value < peak * 0.4;
      const h = Math.max((m.value / peak) * 100, 1.5);
      return `<div class="bar ${m.value === peak ? "peak" : ""} ${partial ? "partial" : ""}">
        <span class="bar-val">${mill(m.value)}</span>
        <span class="bar-fill" style="height:${h}%"></span>
        <span class="bar-lab">${m.month}</span></div>`;
    }).join("");
    const lastM = months[last];
    $("chartNote").textContent = lastM && lastM.value < peak * 0.4
      ? `${lastM.month} er ikke ferdig` : "";
    $("chartWrap").hidden = false;
  }

  // det som krever handling
  const alerts = [];
  if (d.flags?.ubokfort_skatt) {
    alerts.push({ tone: "", title: "Skatten er ikke satt av ennå",
      body: `Regnskapet viser 0 i skattekostnad. Med 22 % selskapsskatt bygger det seg opp
             rundt ${kr(d.flags.ubokfort_skatt)} som ikke er synlig i resultatet.` });
  }
  if (k.lonnsandel_pct != null && k.lonnsandel_budsjett_pct != null
      && k.lonnsandel_pct - k.lonnsandel_budsjett_pct > 3) {
    alerts.push({ tone: "crit", title: "Lønnsandelen ligger over budsjett",
      body: `${pct(k.lonnsandel_pct)} mot ${pct(k.lonnsandel_budsjett_pct)} budsjettert.
             Ett prosentpoeng er rundt ${kr((k.omsetning || 0) / 100)} på bunnlinjen.` });
  }
  if (d.top_debtor && d.top_debtor.share_pct > 30) {
    alerts.push({ tone: "crit", title: `${d.top_debtor.name} er en stor eksponering`,
      body: `De skylder ${kr(d.top_debtor.amount)}, altså ${pct(d.top_debtor.share_pct)}
             av alt kundene deres skylder.` });
  }
  if (alerts.length) {
    $("alerts").innerHTML = alerts.map((a) =>
      `<div class="alert ${a.tone}"><div class="alert-body">
        <h3>${a.title}</h3><p>${a.body}</p></div></div>`).join("");
    $("alerts").hidden = false;
  }

  if (d.period) {
    const to = new Date(d.period.to);
    $("period").textContent = "1. jan – " + to.toLocaleDateString("nb-NO",
      { day: "numeric", month: "short" });
  }
}

async function boot() {
  try {
    const h = await (await fetch("/api/health")).json();
    $("company").textContent = h.company;
  } catch { $("company").textContent = "CFO"; }

  try {
    ({ presets } = await (await fetch("/api/presets")).json());
    fillChips($("chips"));
  } catch { $("chips").hidden = true; }

  try {
    const d = await (await fetch("/api/overview")).json();
    if (d.error) throw new Error(d.error);
    renderOverview(d);
  } catch (e) {
    $("verdictBlock").classList.remove("loading");
    $("verdict").innerHTML =
      `Får ikke tak i regnskapet akkurat nå. Spørsmålsfeltet under virker fortsatt.`;
    $("verdict").style.fontSize = "20px";
    console.error(e);
  }
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
    // Et svar som var underveis da siden ble lukket, blir aldri ferdig.
    for (const c of v) for (const m of c.messages || []) {
      if (m.role === "assistant" && !m.done) {
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
  $("navHome").classList.toggle("active", activeId === null && !$("home").hidden);
  $("newChat").classList.toggle("active", activeId === null && $("home").hidden);

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
$("menuBtn").addEventListener("click", openSidebar);
$("sideClose").addEventListener("click", closeSidebar);
$("scrim").addEventListener("click", closeSidebar);
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeSidebar(); });

/* ── visninger ───────────────────────────────────────────────── */
function route() {
  const m = location.hash.match(/^#c\/([\w-]+)$/);
  if (m && find(m[1])) openConv(m[1]);
  else if (location.hash === "#ny") openConv(null);
  else showHome();
  closeSidebar();
}
window.addEventListener("hashchange", route);

function showHome() {
  activeId = null;
  $("chat").hidden = true; $("home").hidden = false;
  document.title = "CFO";
  renderList();
  window.scrollTo(0, 0);
}

function openConv(id) {
  activeId = id;
  $("home").hidden = true; $("chat").hidden = false;
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
    el.innerHTML = '<div class="who">CFO</div><div class="activity"></div><div class="body-md"></div>';
    m._el = el;
    draw(el, m);
  }
  return el;
}

// Et svar som strømmer inn mens en annen samtale er åpen, oppdateres bare i
// dataene; elementet tegnes på nytt når samtalen åpnes igjen.
function paintMsg(m) {
  if (m._el?.isConnected) draw(m._el, m);
}

function draw(el, m) {
  const activity = el.querySelector(".activity");
  activity.innerHTML = "";
  for (const a of m.acts || []) {
    const row = document.createElement("div");
    row.className = "act";
    row.innerHTML = a.done ? TICK : '<span class="spin"></span>';
    row.append(document.createTextNode(a.label));
    activity.append(row);
  }
  const body = el.querySelector(".body-md");
  renderMarkdown(body, m.text || "");
  if (!m.done) body.insertAdjacentHTML("beforeend", '<span class="caret"></span>');
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
  const m = { role: "assistant", text: "", acts: [], done: false };
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
          m.acts.forEach((a) => (a.done = true));
          m.acts.push({ label: ev.label, done: false });
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
    m.acts.forEach((a) => (a.done = true));
    c._busy = false; c._ctrl = null;
    c.updated = Date.now();
    paint(); save(); renderList(); setComposer();
    if (activeId === c.id && matchMedia("(pointer:fine)").matches) $("inputChat").focus();
  }
}

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
