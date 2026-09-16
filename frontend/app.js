const $ = (id) => document.getElementById(id);
let sessionId = null, busy = false;

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

const CHIPS = [
  "Hvorfor er lønnen høyere enn budsjett?",
  "Hvem skylder oss penger nå?",
  "Hvordan ligger vi an på likviditet?",
  "Lag en prognose ut året",
];

async function boot() {
  try {
    const h = await (await fetch("/api/health")).json();
    $("company").textContent = h.company;
  } catch { $("company").textContent = "CFO"; }

  $("chips").innerHTML = CHIPS.map((c) => `<button class="chip">${c}</button>`).join("");
  $("chips").querySelectorAll(".chip").forEach((b) =>
    b.addEventListener("click", () => ask(b.textContent)));

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

/* ── samtale ─────────────────────────────────────────────────── */
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

function showChat() {
  $("home").hidden = true; $("chat").hidden = false; $("backHome").hidden = false;
}
$("backHome").addEventListener("click", () => {
  $("chat").hidden = true; $("home").hidden = false; $("backHome").hidden = true;
  window.scrollTo(0, 0);
});

async function ask(message) {
  if (busy || !message.trim()) return;
  busy = true;
  showChat();
  document.querySelectorAll(".composer button").forEach((b) => (b.disabled = true));

  const thread = $("thread");
  const u = document.createElement("div");
  u.className = "msg user";
  u.innerHTML = `<div class="bubble"></div>`;
  u.querySelector(".bubble").textContent = message;
  thread.append(u);

  const a = document.createElement("div");
  a.className = "msg assistant";
  a.innerHTML = `<div class="who">CFO</div><div class="activity"></div><div class="body-md"></div>`;
  thread.append(a);
  const activity = a.querySelector(".activity"), body = a.querySelector(".body-md");
  window.scrollTo(0, document.body.scrollHeight);

  let text = "", pending = false;
  const stick = () =>
    window.innerHeight + window.scrollY > document.body.scrollHeight - 160;
  const paint = () => {
    pending = false;
    const keep = stick();
    renderMarkdown(body, text);
    if (busy) body.insertAdjacentHTML("beforeend", '<span class="caret"></span>');
    if (keep) window.scrollTo(0, document.body.scrollHeight);
  };

  try {
    const res = await fetch("/api/chat", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, session_id: sessionId }),
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
        if (ev.type === "session") sessionId = ev.session_id;
        else if (ev.type === "tool") {
          activity.querySelectorAll(".spin").forEach((s) => (s.outerHTML = TICK));
          const row = document.createElement("div");
          row.className = "act";
          row.innerHTML = '<span class="spin"></span>';
          row.append(document.createTextNode(ev.label));
          activity.append(row);
          if (stick()) window.scrollTo(0, document.body.scrollHeight);
        } else if (ev.type === "text") {
          text += ev.text;
          if (!pending) { pending = true; requestAnimationFrame(paint); }
        } else if (ev.type === "error") {
          const e = document.createElement("div");
          e.className = "err"; e.textContent = ev.message; a.append(e);
        }
      }
    }
  } catch (err) {
    const e = document.createElement("div");
    e.className = "err";
    e.textContent = "Mistet forbindelsen. Prøv igjen.";
    a.append(e);
  } finally {
    busy = false;
    activity.querySelectorAll(".spin").forEach((s) => (s.outerHTML = TICK));
    paint();
    document.querySelectorAll(".composer button").forEach((b) => (b.disabled = false));
    $("inputChat").focus();
  }
}

for (const [form, input] of [["composerHome", "inputHome"], ["composerChat", "inputChat"]]) {
  $(form).addEventListener("submit", (e) => {
    e.preventDefault();
    const v = $(input).value; $(input).value = ""; ask(v);
  });
}

boot();
