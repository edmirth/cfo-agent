const $ = (id) => document.getElementById(id);
const thread = $("thread"), input = $("input"), sendBtn = $("send");
// Fresh conversation per page load, so the thread on screen always matches
// the history the server is reasoning over.
let sessionId = null;
let busy = false;

marked.setOptions({ breaks: false, gfm: true });

/* ---------- boot ---------- */

async function boot() {
  try {
    const h = await (await fetch("/api/health")).json();
    $("companyName").textContent = h.company;
    $("statusDot").className = "dot " + (h.ok ? "ok" : "bad");
    const ready = h.ok && h.tripletex_configured;
    $("statusDot").className = "dot " + (ready ? "ok" : "bad");
    $("statusText").textContent = ready ? "Klar" : "Ikke konfigurert";
    $("statusMeta").textContent =
      h.model + (h.tripletex_configured ? " · Tripletex tilkoblet" : " · Tripletex mangler token");
    const w = $("welcomeState");
    if (w) {
      const ready = h.ok && h.tripletex_configured;
      w.textContent = ready ? "Tilkoblet Tripletex"
        : !h.ok ? "Ikke klar — mangler ANTHROPIC_API_KEY"
        : "Ikke klar — mangler Tripletex-token";
      w.style.color = ready ? "" : "var(--crit)";
    }
  } catch {
    $("statusDot").className = "dot bad";
    $("statusText").textContent = "Backend svarer ikke";
    const w = $("welcomeState");
    if (w) { w.textContent = "Backend svarer ikke"; w.style.color = "var(--crit)"; }
  }

  try {
    const { presets } = await (await fetch("/api/presets")).json();
    for (const p of presets) {
      const b = document.createElement("button");
      b.className = "preset";
      b.textContent = p.label;
      b.onclick = () => send(p.id, p.label);
      $("presets").append(b);

      const s = document.createElement("button");
      s.className = "starter";
      s.textContent = p.label;
      s.onclick = () => send(p.id, p.label);
      $("starters").append(s);
    }
  } catch { /* rail stays empty; typing still works */ }
}

/* ---------- rendering ---------- */

function renderMarkdown(el, raw) {
  el.innerHTML = marked.parse(raw);
  // Wide tables scroll inside their own container, never the page.
  el.querySelectorAll("table").forEach((t) => {
    if (t.parentElement.classList.contains("table-scroll")) return;
    const w = document.createElement("div");
    w.className = "table-scroll";
    t.replaceWith(w);
    w.append(t);
  });
  el.querySelectorAll("a").forEach((a) => {
    a.target = "_blank";
    a.rel = "noopener noreferrer";
  });
}

function userMessage(text) {
  const el = document.createElement("div");
  el.className = "msg user";
  const b = document.createElement("div");
  b.className = "bubble";
  b.textContent = text;
  el.append(b);
  thread.append(el);
  return el;
}

function assistantMessage() {
  const el = document.createElement("div");
  el.className = "msg assistant";
  el.innerHTML =
    '<div class="who">CFO</div>' +
    '<div class="activity"></div>' +
    '<details class="reason" hidden><summary>Resonnement</summary>' +
    '<div class="body"></div></details>' +
    '<div class="body-md"></div>';
  thread.append(el);
  return {
    root: el,
    activity: el.querySelector(".activity"),
    reason: el.querySelector("details.reason"),
    reasonBody: el.querySelector("details.reason .body"),
    body: el.querySelector(".body-md"),
  };
}

const TICK =
  '<svg class="tick" viewBox="0 0 16 16" aria-hidden="true">' +
  '<path d="M3.5 8.4l3 3 6-6.8" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';

function addActivity(container, label) {
  container
    .querySelectorAll(".act .spin")
    .forEach((s) => s.outerHTML = TICK);
  const row = document.createElement("div");
  row.className = "act";
  row.innerHTML = '<span class="spin"></span>';
  row.append(document.createTextNode(label));
  container.append(row);
}

function settleActivity(container) {
  container.querySelectorAll(".act .spin").forEach((s) => s.outerHTML = TICK);
}

const atBottom = () =>
  thread.scrollHeight - thread.scrollTop - thread.clientHeight < 140;

/* ---------- send ---------- */

async function send(message, displayAs) {
  if (busy || !message.trim()) return;
  busy = true;
  sendBtn.disabled = true;
  $("welcome")?.remove();
  document.querySelectorAll(".preset").forEach((p) => (p.disabled = true));

  userMessage(displayAs || message);
  const ui = assistantMessage();
  thread.scrollTop = thread.scrollHeight;

  let text = "", reasoning = "", pending = false;
  const paint = () => {
    pending = false;
    const stick = atBottom();
    renderMarkdown(ui.body, text);
    if (busy) ui.body.insertAdjacentHTML("beforeend", '<span class="caret"></span>');
    if (stick) thread.scrollTop = thread.scrollHeight;
  };

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, session_id: sessionId }),
    });
    if (!res.ok || !res.body) throw new Error("HTTP " + res.status);

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const frames = buffer.split("\n\n");
      buffer = frames.pop() ?? "";

      for (const frame of frames) {
        const line = frame.split("\n").find((l) => l.startsWith("data: "));
        if (!line) continue;
        let ev;
        try { ev = JSON.parse(line.slice(6)); } catch { continue; }

        if (ev.type === "session") {
          sessionId = ev.session_id;
        } else if (ev.type === "tool") {
          addActivity(ui.activity, ev.label);
          if (atBottom()) thread.scrollTop = thread.scrollHeight;
        } else if (ev.type === "reasoning") {
          reasoning += ev.text;
          ui.reason.hidden = false;
          ui.reasonBody.textContent = reasoning;
        } else if (ev.type === "text") {
          text += ev.text;
          if (!pending) { pending = true; requestAnimationFrame(paint); }
        } else if (ev.type === "error") {
          settleActivity(ui.activity);
          const e = document.createElement("div");
          e.className = "err";
          e.textContent = ev.message;
          ui.root.append(e);
        }
      }
    }
  } catch (err) {
    const e = document.createElement("div");
    e.className = "err";
    e.textContent = "Mistet forbindelsen til backend: " + err.message;
    ui.root.append(e);
  } finally {
    busy = false;
    settleActivity(ui.activity);
    paint();
    sendBtn.disabled = false;
    document.querySelectorAll(".preset").forEach((p) => (p.disabled = false));
    input.focus();
  }
}

/* ---------- composer ---------- */

$("composer").addEventListener("submit", (e) => {
  e.preventDefault();
  const v = input.value;
  input.value = "";
  input.style.height = "auto";
  send(v);
});

input.addEventListener("input", () => {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 184) + "px";
});

input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    $("composer").requestSubmit();
  }
});

$("newChat").addEventListener("click", async () => {
  if (sessionId) {
    try {
      await fetch("/api/session/reset?session_id=" + encodeURIComponent(sessionId), {
        method: "POST",
      });
    } catch { /* resetting locally is enough to start over */ }
  }
  sessionId = null;
  location.reload();
});

boot();
