/* Forsiden: dagens brief.
 *
 * Produktet er leveransen, ikke chatten. Denne siden settes sammen av tall
 * som allerede finnes — 13 ukers kontantstrøm, hva av pengene på konto som
 * faktisk er selskapets, nøkkeltallene for bransjen og tilstanden på bøkene —
 * og sier hva som krever handling nå. Chatten er veien videre inn i ett av
 * punktene, ikke stedet arbeidet starter.
 *
 * Alt regnes ut av backend uten modell i loopen, så en sidelast er gratis.
 */
const B = (id) => document.getElementById(id);

/* ── tall og datoer på norsk ─────────────────────────────────────── */
const bkr = (n) =>
  n == null ? "–" : Math.round(n).toLocaleString("nb-NO").replace(/ /g, " ");
const bmill = (n) => {
  if (n == null) return "–";
  const a = Math.abs(n);
  if (a >= 1e6) return (n / 1e6).toFixed(1).replace(".", ",") + " mill.";
  if (a >= 1e4) return Math.round(n / 1e3) + " 000";
  return bkr(n);
};
const bpct = (n, d = 1) =>
  n == null ? "–" : n.toFixed(d).replace(".", ",") + " %";
// Backend oppgir enheten selv: %, kr, dager eller x. Å anta kroner ga
// «betalingstid 32 kr», som er tull.
const unit = (v, u, d = 1) => {
  if (v == null) return "–";
  if (u === "%") return bpct(v, d);
  if (u === "kr") return bkr(v) + " kr";
  if (u === "dager") return Math.round(v) + " dager";
  if (u === "x") return v.toFixed(1).replace(".", ",");
  return bkr(v) + (u ? " " + u : "");
};
const stop = (t) => t + (/[.!?]$/.test(t.trim()) ? "" : ".");

const DAYS = ["søndag", "mandag", "tirsdag", "onsdag", "torsdag", "fredag", "lørdag"];
const dateNo = (iso) =>
  new Date(iso).toLocaleDateString("nb-NO", { day: "numeric", month: "long" });
const dayNo = (iso) => DAYS[new Date(iso).getDay()];

/* ── hva som er nytt siden sist ──────────────────────────────────── */
// Backend har ingen planlagt levering ennå, så «nytt» måles mot forrige gang
// denne nettleseren så brief-en. Ærlig, og det som faktisk betyr noe for den
// som leser: har dette endret seg siden jeg så på det sist.
const SEEN = "cfo.brief.seen.v1";
let seen = new Set();
try { seen = new Set(JSON.parse(localStorage.getItem(SEEN) || "[]")); } catch { /* privat modus */ }
const markSeen = (ids) => {
  try { localStorage.setItem(SEEN, JSON.stringify([...new Set([...seen, ...ids])].slice(-200))); }
  catch { /* ignorér */ }
};

/* ── data ────────────────────────────────────────────────────────── */
const state = {};

async function grab(name, url) {
  const res = await fetch(url);
  const data = await res.json();
  if (data.error) throw new Error(data.error);
  state[name] = data;
  return data;
}

/* ── signalene: det som krever handling ──────────────────────────── */
// Hvert signal er én sak: hvor alvorlig, hva som er galt, og spørsmålet som
// tar deg videre inn i det. Rekkefølgen er alvorlighetsgrad, ikke kilde.
const RANK = { crit: 0, warn: 1, note: 2 };

function signals() {
  const out = [];
  const cash = state.cashflow, com = state.commitments, ov = state.overview,
        dash = state.dashboard, pre = state.preflight;

  if (cash && !cash.error) {
    const floor = cash.assumptions?.monthly_wages || 0;
    if (cash.goes_negative) {
      out.push({ id: "cash_negative", sev: "crit", tag: "Kontanter",
        title: `Kontoen går i minus i ${cash.goes_negative.label.toLowerCase()}`,
        body: `Med det som allerede er fakturert inn og ut, er kontoen tom i ` +
              `uka fra ${dateNo(cash.goes_negative.start)}.`,
        ask: "Gå gjennom kontantstrømmen uke for uke fram til uka vi går i minus. " +
             "Hva er de største utbetalingene, og hva kan flyttes?" });
    } else {
      const dip = cash.weeks.find((w) => w.committed_close < floor);
      if (dip && floor) {
        out.push({ id: "cash_floor:" + dip.label, sev: "warn", tag: "Kontanter",
          title: `Under gulvet i ${dip.label.toLowerCase()}`,
          body: `Den sikre kontantstrømmen faller til ${bkr(dip.committed_close)} kr i uka fra ` +
                `${dateNo(dip.start)} — under én månedslønn (${bkr(floor)} kr).`,
          ask: `Hvorfor faller kontantstrømmen under én månedslønn i ${dip.label}? ` +
               "Vis ukene rundt, og hvilke innbetalinger som må komme inn for å unngå det." });
      }
    }
  }

  if (com && !com.error) {
    const held = (com.items || []).filter((i) => i.kind === "holding");
    const heldSum = held.reduce((n, i) => n + i.amount, 0);
    if (com.verdict === "negative" || com.free_all < 0) {
      out.push({ id: "free_all_negative", sev: "crit", tag: "Penger på konto",
        title: "Forpliktelsene er større enn det som står på konto",
        body: `Det står ${bkr(com.bank)} kr i banken. Trekker du fra alt som er ` +
              `lovet bort, mangler det ${bkr(Math.abs(com.free_all))} kr før alt er betalt. ` +
              `Fritt akkurat nå: ${bkr(com.free_now)} kr.`,
        ask: "Bryt ned forpliktelsene mine etter forfall og vis hvor mye som er fritt " +
             "hver måned framover. Hva bør settes av nå?" });
    }
    if (heldSum > 0 && !com.restricted) {
      out.push({ id: "held_unrestricted", sev: "warn", tag: "Penger på konto",
        title: "Statens penger står på driftskontoen",
        body: `${bkr(heldSum)} kr er moms, arbeidsgiveravgift og skattetrekk dere ` +
              `holder på vegne av staten. Ingenting er satt av på egen konto, så ` +
              `de ser ut som driftsmidler helt til de forfaller.`,
        ask: "Hvor mye av pengene på konto er egentlig statens, når forfaller hver del, " +
             "og hvordan bør jeg sette dem av?" });
    }
  }

  for (const k of (dash?.kpis || []).filter((k) => k.status === "bad" || k.status === "watch")) {
    const over = k.better === "low" ? k.value > k.alert : k.value < k.alert;
    out.push({
      id: `kpi:${k.id}:${Math.round(k.value)}`,
      sev: k.status === "bad" && (k.headline || over) ? "crit" : "warn",
      tag: "Nøkkeltall",
      title: `${k.label} er ${unit(k.value, k.unit)} mot ${unit(k.target, k.unit, 0)} i mål`,
      body: k.why,
      ask: `Hvorfor ligger ${k.label.toLowerCase()} på ${unit(k.value, k.unit)}? ` +
           "Er dette et nivåskifte eller en engangseffekt, og hva skal til for å nå målet?",
    });
  }

  if (ov?.top_debtor && ov.top_debtor.share_pct >= 25) {
    const d = ov.top_debtor;
    out.push({ id: `debtor:${d.name}:${Math.round(d.share_pct)}`, sev: "warn", tag: "Kunder",
      title: `${d.name} er ${bpct(d.share_pct, 0)} av alt kundene skylder`,
      body: `De skylder ${bkr(d.amount)} kr av totalt ${bkr(ov.kpis?.kundefordringer)} kr. ` +
            `Blir den betalingen forsinket, er det kontantstrømmen deres som venter.`,
      ask: `Gå gjennom ${d.name}: hva er fakturert, hva er forfalt, hvor lenge har de brukt på å ` +
           "betale før, og hva er eksponeringen vår hvis de stopper?" });
  }
  if (ov?.flags?.ubokfort_skatt) {
    out.push({ id: "tax_unbooked", sev: "note", tag: "Regnskap",
      title: "Skatten er ikke satt av",
      body: `Regnskapet viser 0 i skattekostnad. Med 22 % selskapsskatt bygger det seg ` +
            `opp rundt ${bkr(ov.flags.ubokfort_skatt)} kr som ikke er synlig i resultatet.`,
      ask: "Hvor mye skatt burde vært avsatt hittil i år, og hva gjør det med resultatet?" });
  }

  out.sort((a, b) => RANK[a.sev] - RANK[b.sev]);
  return out;
}

/* ── overskriften: én setning, den viktigste ─────────────────────── */
function headline(list) {
  const cash = state.cashflow, ov = state.overview;
  if (cash && !cash.error) {
    const floor = cash.assumptions?.monthly_wages || 0;
    const dip = cash.weeks.findIndex((w) => w.committed_close < floor);
    const debtor = ov?.top_debtor?.name;
    if (cash.goes_negative) {
      return `Kontoen er tom i ${cash.goes_negative.label.toLowerCase()} hvis ingenting endres.`;
    }
    if (dip > 0 && floor) {
      const safe = cash.weeks[dip - 1], hit = cash.weeks[dip];
      return `Dere er trygge til og med ${safe.label.toLowerCase()}. I ${hit.label.toLowerCase()} ` +
             `faller kontoen under gulvet` + (debtor ? `, med mindre ${debtor} betaler.` : ".");
    }
    if (dip === -1 && floor) {
      return `Kontantstrømmen holder seg over én månedslønn alle de neste 13 ukene. ` +
             `Tynnest i ${cash.low_committed.label.toLowerCase()}, med ` +
             `${bkr(cash.low_committed.amount)} kr.`;
    }
  }
  const crit = list.find((s) => s.sev === "crit");
  if (crit) return stop(crit.title);
  return "Ingenting krever handling i dag.";
}

/* ── kontantstrømmen: 13 uker ────────────────────────────────────── */
// To linjer, aldri én: det som allerede er fakturert (fakta) og det samme
// pluss fortsatt drift (anslag). Gulvet er én månedslønn, og det står det.
const compact = () => window.innerWidth < 680;

function drawCash(cash) {
  const wrap = B("cash");
  if (!cash || cash.error) { wrap.hidden = true; return; }
  const weeks = cash.weeks || [];
  if (!weeks.length) { wrap.hidden = true; return; }

  const floor = cash.assumptions?.monthly_wages || 0;
  // Telefon får sin egen geometri, ikke bare større tekst: høyere plott,
  // verdiene langs venstre kant og annenhver uke merket.
  const cm = compact();
  const W = 920, H = cm ? 440 : 300;
  const L = 8, R = cm ? 118 : 92, T = cm ? 34 : 26, Bm = cm ? 78 : 46;
  const xs = (i) => L + (i / (weeks.length - 1)) * (W - L - R);
  const vals = weeks.flatMap((w) => [w.committed_close, w.expected_close])
                    .concat(floor ? [floor] : []).concat([cash.opening]);
  const hi = Math.max(...vals), lo = Math.min(0, ...vals);
  const pad = (hi - lo) * 0.12 || 1;
  const top = hi + pad, bot = lo - pad * 0.4;
  const ys = (v) => T + (1 - (v - bot) / (top - bot)) * (H - T - Bm);
  const path = (key) => weeks.map((w, i) => `${i ? "L" : "M"}${xs(i).toFixed(1)} ${ys(w[key]).toFixed(1)}`).join(" ");

  const last = weeks[weeks.length - 1];
  const gridVals = [top, (top + bot) / 2, Math.max(bot, 0)];
  const yLabel = (v) => cm
    ? `<text class="ax yl" x="${L + 2}" y="${(ys(v) - 9).toFixed(1)}">${bmill(v)}</text>`
    : `<text class="ax" x="${W - R + 6}" y="${(ys(v) + 3.5).toFixed(1)}">${bmill(v)}</text>`;

  wrap.hidden = false;
  B("cashTitle").textContent = "Kontanter, 13 uker";
  B("cashNote").textContent = `Fra ${dateNo(cash.as_of)} · ${bkr(cash.opening)} kr på konto nå`;

  B("cashSvg").innerHTML = `
    <svg class="${cm ? "compact" : ""}" viewBox="0 0 ${W} ${H}" role="img"
         aria-label="Kontantbeholdning 13 uker fram, bundet og forventet, mot et gulv på én månedslønn">
      ${gridVals.map((v, i) => `<line class="grid" x1="${L}" x2="${W - R}" y1="${ys(v).toFixed(1)}" y2="${ys(v).toFixed(1)}"/>
        ${cm && i ? "" : yLabel(v)}`).join("")}
      ${floor ? `<line class="floor" x1="${L}" x2="${W - R}" y1="${ys(floor).toFixed(1)}" y2="${ys(floor).toFixed(1)}"/>
        <text class="floor-lab" x="${L + 4}" y="${(ys(floor) + (cm ? 26 : -7)).toFixed(1)}">gulv · én månedslønn ${bmill(floor)}</text>` : ""}
      <path class="ln expected" d="${path("expected_close")}"/>
      <path class="ln committed" d="${path("committed_close")}"/>
      <text class="lab expected" x="${(W - R + 6).toFixed(1)}" y="${(ys(last.expected_close) + 3.5).toFixed(1)}">anslag</text>
      <text class="lab committed" x="${(W - R + 6).toFixed(1)}" y="${(ys(last.committed_close) + 3.5).toFixed(1)}">bundet</text>
      ${weeks.map((w, i) => (cm && i % 2)
        ? "" : `<text class="ax wk" x="${xs(i).toFixed(1)}" y="${H - (cm ? 34 : 22)}">${w.label.replace("Uke ", "")}</text>`).join("")}
      <text class="ax wk-unit" x="${L}" y="${H - (cm ? 6 : 6)}">uke</text>
      <g id="cashHover" hidden>
        <line class="cross" y1="${T}" y2="${H - Bm}"/>
        <circle class="dot expected" r="${cm ? 8 : 4.5}"/><circle class="dot committed" r="${cm ? 8 : 4.5}"/>
      </g>
      <rect id="cashHit" x="${L}" y="${T}" width="${W - L - R}" height="${H - T - Bm}" fill="transparent"/>
    </svg>
    <div class="tip" id="cashTip" hidden></div>`;

  // Hover: krysshår og verdiene for den uka.
  const svg = B("cashSvg").querySelector("svg"), hov = B("cashHover"), tip = B("cashTip");
  const hit = B("cashHit");
  const move = (e) => {
    const box = svg.getBoundingClientRect();
    const x = ((e.clientX - box.left) / box.width) * W;
    const i = Math.min(weeks.length - 1, Math.max(0,
      Math.round(((x - L) / (W - L - R)) * (weeks.length - 1))));
    const w = weeks[i];
    hov.hidden = false;
    hov.querySelector(".cross").setAttribute("x1", xs(i));
    hov.querySelector(".cross").setAttribute("x2", xs(i));
    hov.querySelector(".dot.committed").setAttribute("cx", xs(i));
    hov.querySelector(".dot.committed").setAttribute("cy", ys(w.committed_close));
    hov.querySelector(".dot.expected").setAttribute("cx", xs(i));
    hov.querySelector(".dot.expected").setAttribute("cy", ys(w.expected_close));
    tip.hidden = false;
    tip.innerHTML = `<b>${w.label}</b><span class="tip-sub">fra ${dateNo(w.start)}</span>
      <span class="tip-row"><i class="sw committed"></i>bundet<b>${bkr(w.committed_close)}</b></span>
      <span class="tip-row"><i class="sw expected"></i>anslag<b>${bkr(w.expected_close)}</b></span>`;
    const left = (xs(i) / W) * box.width;
    tip.style.left = Math.min(Math.max(left, 70), box.width - 70) + "px";
  };
  hit.addEventListener("pointermove", move);
  hit.addEventListener("pointerleave", () => { hov.hidden = true; tip.hidden = true; });

  const lowC = cash.low_committed;
  B("cashLow").innerHTML =
    `Tynnest i <b>${lowC.label.toLowerCase()}</b> (fra ${dateNo(lowC.start)}): ` +
    `<b>${bkr(lowC.amount)} kr</b> bundet. Åpne kundefakturaer: ` +
    `${bkr(cash.open_invoices?.receivable_total)} kr på ${cash.open_invoices?.receivable} fakturaer.`;

  B("cashTable").innerHTML = `<table><thead><tr><th>Uke</th><th>Inn</th><th>Ut</th>
      <th>Bundet</th><th>Anslag</th></tr></thead><tbody>` +
    weeks.map((w) => `<tr><td>${w.label}</td><td>${bkr(w.in + w.expected_in)}</td>
      <td>${bkr(w.out + w.expected_out)}</td><td>${bkr(w.committed_close)}</td>
      <td>${bkr(w.expected_close)}</td></tr>`).join("") + "</tbody></table>";
}

/* ── nøkkeltallene i bransjen ────────────────────────────────────── */
function drawKpis(dash) {
  const wrap = B("kpis");
  if (!dash || dash.error || !dash.kpis?.length) { wrap.hidden = true; return; }
  wrap.hidden = false;
  B("kpiNote").textContent = dash.industry ? `Målt mot ${dash.industry.toLowerCase()}` : "";
  B("kpiList").innerHTML = dash.kpis.map((k) => {
    const v = unit(k.value, k.unit);
    const t = unit(k.target, k.unit, 0);
    const scale = Math.max(k.value, k.target, k.alert) * 1.15 || 1;
    return `<div class="pack ${k.status}">
      <div class="pack-top"><span class="pack-label">${k.label}</span>
        <span class="pack-val">${v}</span></div>
      <div class="pack-bar"><span style="width:${Math.min(100, (k.value / scale) * 100)}%"></span>
        <i class="pack-target" style="left:${Math.min(100, (k.target / scale) * 100)}%"></i></div>
      <p class="pack-plain">${k.plain}. Mål ${t}.</p>
    </div>`;
  }).join("");
}

/* ── tilstanden på bøkene ────────────────────────────────────────── */
function drawBooks(pre, cash) {
  const wrap = B("books");
  const checks = (pre?.checks || []).filter((c) => c.status !== "ok");
  const extra = (cash?.warnings || []).map((w) => ({ label: "Kundefordringer", status: "note", headline: w }));
  const all = [...checks, ...extra];
  if (!all.length) { wrap.hidden = true; return; }
  wrap.hidden = false;
  const worst = all.some((c) => c.status === "warn") ? "warn" : "note";
  B("booksSum").textContent = `${all.length} ting å rydde i regnskapet`;
  B("booksSum").className = "books-sum " + worst;
  B("booksList").innerHTML = all.map((c) => `<li class="${c.status}">
    <b>${c.label}</b> ${c.headline}${c.detail ? `<span class="books-detail">${c.detail}</span>` : ""}</li>`).join("");
}

/* ── signalene ───────────────────────────────────────────────────── */
function drawSignals(list) {
  const wrap = B("signals");
  if (!list.length) { wrap.hidden = true; return; }
  wrap.hidden = false;
  const fresh = list.filter((s) => !seen.has(s.id)).length;
  B("signalCount").textContent = fresh
    ? `${fresh} nytt siden sist du var her` : "Ingenting nytt siden sist";
  B("signalList").innerHTML = list.map((s) => `<article class="sig ${s.sev}">
      <div class="sig-head">
        <span class="sig-tag">${s.tag}</span>
        ${seen.has(s.id) ? "" : '<span class="sig-new">nytt</span>'}
      </div>
      <h3>${s.title}</h3>
      <p>${s.body}</p>
      <button class="sig-ask" type="button">Grav i dette →</button>
    </article>`).join("");
  B("signalList").querySelectorAll(".sig-ask").forEach((b, i) => {
    b.addEventListener("click", () => window.askCFO?.(list[i].ask, list[i].title));
  });
  markSeen(list.map((s) => s.id));
}

/* ── sammenstillingen ────────────────────────────────────────────── */
function paintHead() {
  const as_of = state.cashflow?.as_of || state.overview?.generated_at || new Date().toISOString().slice(0, 10);
  B("briefDate").textContent = `Brief · ${dayNo(as_of)} ${dateNo(as_of)}`;
  const list = signals();
  B("briefLead").textContent = headline(list);
  B("briefLead").classList.remove("loading");
  drawSignals(list);
}

/* ── kortstokken: arbeid som venter på et ja ─────────────────────── */
// Kortene lages i backend, av kontrollene som allerede kjører, og kommer
// ferdig formulert med utkast. Ingen knapp her rører Tripletex: «Send» betyr
// at utkastet er godkjent og gjort klart — det er fortsatt du som sender det.
const esc = (t) => String(t ?? "").replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function cardHtml(c) {
  const ev = (c.evidence || []).map((e) =>
    `<li><span>${esc(e.label)}</span><b>${esc(e.value)}</b></li>`).join("");
  const draft = c.draft ? `
    <details class="draft">
      <summary>Se utkastet</summary>
      <div class="draft-body">
        ${c.draft.subject ? `<p class="draft-subj">${esc(c.draft.subject)}</p>` : ""}
        <pre id="draft-${c.id}">${esc(c.draft.text)}</pre>
        <button class="copy" data-copy="${c.id}">Kopier teksten</button>
      </div>
    </details>` : "";
  const acts = (c.options || []).map((o, i) =>
    `<button class="opt${i === 0 ? " primary" : ""}"
       data-card="${c.id}" data-opt="${o.id}">${esc(o.label)}</button>`).join("");
  return `<article class="card ${c.urgency}" id="card-${c.id}">
    <h3>${esc(c.title)}</h3>
    <p class="card-body">${esc(c.body)}</p>
    ${ev ? `<ul class="card-ev">${ev}</ul>` : ""}
    ${draft}
    <div class="card-acts">${acts}</div>
  </article>`;
}

function drawDeck(d) {
  if (!d || d.error) return;
  const open = d.open || [], later = d.snoozed || [];
  B("deckTitle").textContent = open.length
    ? `${open.length} sak${open.length === 1 ? "" : "er"} venter på deg`
    : "Ingenting venter på deg nå";
  B("cards").innerHTML = open.map(cardHtml).join("");
  B("deckWrap").hidden = !open.length;
  B("deckEmpty").hidden = !!(open.length || later.length);

  B("deckLater").textContent = later.length
    ? `${later.length} sak${later.length === 1 ? "" : "er"}` : "";
  B("laterList").innerHTML = later.map((c) =>
    `<li><span>${esc(c.title)}</span><b>tilbake ${dateNo(c.snooze_until)}</b></li>`).join("");
  B("deckLaterWrap").hidden = !later.length;

  // Tallet i menyen, så man ser at noe venter uten å gå inn på siden.
  const n = open.length;
  const badge = B("navSakerCount");
  if (badge) { badge.textContent = n || ""; badge.hidden = !n; }
}

// Siden lastes når man går inn på den, så den alltid viser det som gjelder nå.
let deckLoading = null;
function loadDeck(force) {
  if (deckLoading && !force) return deckLoading;
  deckLoading = fetch("/api/cards")
    .then((r) => r.json())
    .then((d) => { drawDeck(d); return d; })
    .catch((e) => { console.error("cards", e); })
    .finally(() => { deckLoading = null; });
  return deckLoading;
}

async function decideCard(cardId, optionId) {
  const el = B("card-" + cardId);
  if (el) el.classList.add("deciding");
  try {
    const r = await fetch(`/api/cards/${cardId}/decide`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ option: optionId }),
    });
    if (!r.ok) throw new Error(await r.text());
    const { card } = await r.json();
    if (!el) return;
    const d = card.decided || {};
    // Et godkjent utkast er klart til å sendes — av deg, ikke av oss.
    const hand = card.draft && d.effect === "approve"
      ? `<button class="copy" data-copy="${card.id}">Kopier teksten og send</button>
         <pre hidden id="draft-${card.id}">${esc(card.draft.text)}</pre>` : "";
    const when = card.snooze_until ? ` Kommer tilbake ${dateNo(card.snooze_until)}.` : "";
    el.classList.remove("deciding");
    el.classList.add("settled");
    el.innerHTML = `<h3>${esc(card.title)}</h3>
      <p class="card-done">${esc(d.label || "Registrert")}.${when}</p>${hand}`;
  } catch (e) {
    if (el) el.classList.remove("deciding");
    console.error("decide", e);
  }
}

document.addEventListener("click", (e) => {
  // Only buttons that actually carry a card: the class alone is not enough,
  // since other pages style their buttons the same way.
  const opt = e.target.closest("button.opt[data-card][data-opt]");
  if (opt) { decideCard(opt.dataset.card, opt.dataset.opt); return; }
  const copy = e.target.closest("button.copy");
  if (!copy) return;
  const pre = B("draft-" + copy.dataset.copy);
  if (!pre) return;
  navigator.clipboard.writeText(pre.textContent).then(() => {
    const was = copy.textContent;
    copy.textContent = "Kopiert";
    setTimeout(() => { copy.textContent = was; }, 1800);
  }).catch(() => { copy.textContent = "Kunne ikke kopiere"; });
});

async function loadBrief() {
  const say = (t) => { B("briefLead").textContent = t; };
  say("Leser regnskapet …");

  const jobs = [
    grab("overview", "/api/overview"),
    grab("dashboard", "/api/dashboard"),
    grab("commitments", "/api/commitments"),
    grab("preflight", "/api/preflight"),
    grab("cashflow", "/api/cashflow"),
  ];
  // Hver del tegnes når den lander; kontantstrømmen tar lengst tid og skal
  // ikke holde resten av siden igjen.
  jobs[0].then(() => paintHead()).catch(() => {});
  jobs[1].then((d) => { drawKpis(d); paintHead(); }).catch(() => {});
  jobs[2].then(() => paintHead()).catch(() => {});
  jobs[3].then((d) => { drawBooks(d, state.cashflow); }).catch(() => {});
  jobs[4].then((d) => { drawCash(d); drawBooks(state.preflight, d); paintHead(); }).catch(() => {});

  const res = await Promise.allSettled(jobs);
  if (res.every((r) => r.status === "rejected")) {
    say("Får ikke tak i regnskapet akkurat nå. Spørsmålsfeltet nederst virker fortsatt.");
    B("briefLead").classList.remove("loading");
  }
  B("briefRefresh").disabled = false;
}

let resizeTimer, wasCompact = compact();
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    if (compact() === wasCompact || !state.cashflow) return;
    wasCompact = compact();
    drawCash(state.cashflow);
  }, 200);
});

window.Brief = { load: loadBrief, loadDeck };
