import { useEffect, useMemo, useState } from "react"
import { CartesianGrid, Line, LineChart, ReferenceLine, XAxis, YAxis } from "recharts"

import { ChevronDown } from "lucide-react"

import { Dot, SectionHead, Status } from "@/components/brand"
import { DecisionBody, useDeck } from "@/components/decision"
import { MetricCard } from "@/components/metric-card"
import type { Point } from "@/components/metric-card"
import { SignalList } from "@/components/signal-list"
import { SummaryCard } from "@/components/summary-card"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
} from "@/components/ui/chart"
import type { ChartConfig } from "@/components/ui/chart"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { api, get } from "@/lib/api"
import type {
  Cashflow,
  Commitments,
  Dashboard,
  Month,
  Overview,
  Preflight,
  Rules,
  Schedule,
  Summary,
  WeeklyBrief,
} from "@/lib/api"
import { dateNo, dateShortNo, dayNo, kr, mill, pct, stop, unit } from "@/lib/format"
import { rank } from "@/lib/signals"
import type { Signal } from "@/lib/signals"
import { useConversations } from "@/store/conversations"
import { authFetch } from "@/lib/auth"

/* ── hva som er nytt siden sist ───────────────────────────────── */
// Backend leverer ennå ikke brief-er på plan, så «nytt» måles mot forrige gang
// denne nettleseren så saken.
const SEEN = "cfo.brief.seen.v1"
const seenIds = (): Set<string> => {
  try {
    return new Set(JSON.parse(localStorage.getItem(SEEN) || "[]"))
  } catch {
    return new Set()
  }
}
const markSeen = (ids: string[], had: Set<string>) => {
  try {
    localStorage.setItem(SEEN, JSON.stringify([...new Set([...had, ...ids])].slice(-200)))
  } catch {
    /* ignorér */
  }
}

type Data = {
  cash?: Cashflow
  com?: Commitments
  ov?: Overview
  dash?: Dashboard
  pre?: Preflight
  sum?: Summary
  weekly?: WeeklyBrief | null
  rules?: Rules
  sched?: Schedule
  /** Hvorfor kontantstrømmen ikke kom, så blokken kan si det i stedet for å
   *  stå som en grå flate for alltid. */
  cashError?: string
}

/* ── morgenkjøringen ──────────────────────────────────────────── */
// «Klargjort 07:01» når morgenkjøringen gikk som den skulle i dag, så det
// synes at forsiden var klar før noen spurte. En kjøring for hånd teller ikke.
function preparedAt(sched?: Schedule): string | null {
  const last = sched?.jobs.find((j) => j.name === "morning")?.last_run
  if (!last || last.status !== "ok" || last.triggered_by !== "schedule" || !last.finished_at) {
    return null
  }
  const done = new Date(last.finished_at)
  if (done.toDateString() !== new Date().toDateString()) return null
  return done.toLocaleTimeString("nb-NO", { hour: "2-digit", minute: "2-digit" })
}

/* ── gulvet ───────────────────────────────────────────────────── */
// Fra selskapets regler, samme tall som sakene måles mot. Har ikke selskapet
// satt et eget, er gulvet vårt anslag — én månedslønn — og det sies, ellers
// leses gjetningen vår som deres regel.
function floorOf({ rules }: Data) {
  const r = rules?.likviditetsgulv_kr
  const amount = r?.value || 0
  const assumed = !!r?.assumed
  return {
    amount,
    assumed,
    // Kort, til grafen: «antatt én månedslønn» eller «deres eget».
    tag: assumed ? `antatt ${r?.basis === "standard" ? "standard" : r?.basis}` : "deres eget",
    said: assumed ? ` — antatt ${r?.basis === "standard" ? "standardverdi" : r?.basis}, sett deres eget under Selskapet` : "",
  }
}

/* ── de fire kortene ──────────────────────────────────────────── */
// Månedstallene kommer fra saldobalansen, så de fire kortene er samme kilde som
// resten av forsiden. Null i en måned betyr at rapporten ikke dekker den, og de
// månedene faller ut av serien i stedet for å tegnes som null kroner.
const pick = (m: Month[], key: keyof Omit<Month, "month">): Point[] =>
  m.map((x) => ({ month: x.month, value: x[key] }))

const sum = (p: Point[]) =>
  p.reduce<number | null>((n, x) => (x.value == null ? n : (n ?? 0) + x.value), null)

type CardSpec = {
  label: string
  value: string
  series: Point[]
  note: React.ReactNode
  kind?: "bar" | "line"
  partial?: boolean
}

function metrics({ ov, rules }: Data): CardSpec[] {
  const k = ov?.kpis || {}
  const m = ov?.monthly || []

  const revenue = pick(m, "revenue")
  const wages = pick(m, "wages")
  const result = pick(m, "result")
  const bank = pick(m, "bank")

  // Budsjettet er periodisert likt som omsetningen, altså hittil i år mot
  // hittil i år. Mangler det, sier kortet hva snittmåneden har vært i stedet.
  const budget = k.omsetning_budsjett
  const revNote = budget
    ? `${pct((k.omsetning / budget) * 100, 0)} av budsjettet hittil i år`
    : (() => {
        const seen = revenue.filter((p) => p.value != null)
        return seen.length
          ? `Snitt ${mill((sum(revenue) || 0) / seen.length)} per måned`
          : "Hittil i år"
      })()

  // Selskapets eget mål går foran budsjettet: det er regelen sakene og
  // nøkkeltallet måles mot, og to forskjellige mål på samme tall er ett for mye.
  const wageGoal = rules?.lonnsandel_mal_pct
  const wageTarget = wageGoal?.value != null && !wageGoal.assumed ? wageGoal.value : null
  const wageBudget = k.lonnsandel_budsjett_pct
  const wageNote = k.lonnsandel_pct
    ? `${pct(k.lonnsandel_pct, 0)} av omsetningen` +
      (wageTarget
        ? `, mot ${pct(wageTarget, 0)} i mål`
        : wageBudget
          ? `, mot ${pct(wageBudget, 0)} i budsjettet`
          : "")
    : "Hittil i år"

  // Retningen de siste tre månedene sier mer om banken enn saldoen alene.
  const seenBank = bank.filter((p) => p.value != null)
  const back = seenBank[Math.max(0, seenBank.length - 4)]
  const last = seenBank[seenBank.length - 1]
  const bankNote =
    seenBank.length > 3 && back && last && back.value != null && last.value != null
      ? `${last.value >= back.value ? "Opp" : "Ned"} ${mill(Math.abs(last.value - back.value))} siden ${back.month}`
      : "På driftskontoen nå"

  // Inneværende måned er ikke fakturert ferdig. Bevegelsene tones derfor ned i
  // siste søyle; banksaldoen er ikke en bevegelse og står som den er.
  return [
    {
      label: "Omsetning",
      value: mill(k.omsetning),
      series: revenue,
      note: revNote,
      partial: true,
    },
    {
      label: "Lønnskostnad",
      value: mill(sum(wages)),
      series: wages,
      note: wageNote,
      partial: true,
    },
    {
      label: "Penger i banken",
      value: mill(k.bank),
      series: bank,
      kind: "line",
      note: bankNote,
    },
    {
      label: "Driftsresultat",
      value: mill(k.driftsresultat),
      series: result,
      note: k.driftsmargin_pct
        ? `Margin ${pct(k.driftsmargin_pct)} av omsetningen`
        : "Hittil i år",
      partial: true,
    },
  ]
}

/* ── signalene: det som krever handling ───────────────────────── */
function buildSignals(data: Data): Signal[] {
  const { cash, com, ov, dash } = data
  const out: Signal[] = []

  if (cash) {
    const { amount: floor, said } = floorOf(data)
    // The committed line, not the expected one: this card's own words are
    // "det som allerede er fakturert og de faste regningene", and its amount reads
    // committed_close. It used to key off goes_negative, which the backend
    // measured on the expected line, so the card stayed silent exactly when
    // the floor went dry while the forecast still looked healthy.
    const negative = cash.goes_negative_committed
    if (negative) {
      const week = cash.weeks.find((w) => w.start === negative.start)
      out.push({
        id: "cash_negative",
        sev: "crit",
        tag: "Kontanter",
        title: `Kontoen går i minus i ${negative.label.toLowerCase()}`,
        body: `Med det som allerede er fakturert og de faste regningene, er kontoen tom i uka fra ${dateNo(negative.start)}.`,
        ask: "Gå gjennom kontantstrømmen uke for uke fram til uka vi går i minus. Hva er de største utbetalingene, og hva kan flyttes?",
        amount: week ? Math.abs(week.committed_close) : undefined,
        due: negative.start,
      })
    } else {
      const dip = cash.weeks.find((w) => w.committed_close < floor)
      if (dip && floor) {
        out.push({
          id: "cash_floor:" + dip.label,
          sev: "warn",
          tag: "Kontanter",
          title: `Under gulvet i ${dip.label.toLowerCase()}`,
          body: `Den sikre kontantstrømmen faller til ${kr(dip.committed_close)} kr i uka fra ${dateNo(dip.start)} — under gulvet på ${kr(floor)} kr${said}.`,
          ask: `Hvorfor faller kontantstrømmen under gulvet på ${kr(floor)} kr i ${dip.label}? Vis ukene rundt, og hvilke innbetalinger som må komme inn for å unngå det.`,
          amount: floor - dip.committed_close,
          due: dip.start,
        })
      }
    }
  }

  if (com) {
    const held = (com.items || []).filter((i) => i.kind === "holding")
    const heldSum = held.reduce((n, i) => n + i.amount, 0)
    // Nærmeste forfall blant forpliktelsene er det som avgjør hvor mye det haster.
    const soonest = (items: typeof held) =>
      items.map((i) => i.due).filter(Boolean).sort()[0]
    if (com.verdict === "negative" || com.free_all < 0) {
      out.push({
        id: "free_all_negative",
        sev: "crit",
        tag: "Penger på konto",
        title: "Forpliktelsene er større enn det som står på konto",
        body: `Det står ${kr(com.bank)} kr i banken. Trekker du fra alt som er lovet bort, mangler det ${kr(Math.abs(com.free_all))} kr før alt er betalt. Fritt akkurat nå: ${kr(com.free_now)} kr.`,
        ask: "Bryt ned forpliktelsene mine etter forfall og vis hvor mye som er fritt hver måned framover. Hva bør settes av nå?",
        amount: Math.abs(com.free_all),
        due: soonest(com.items || []),
      })
    }
    if (heldSum > 0 && !com.restricted) {
      out.push({
        id: "held_unrestricted",
        sev: "warn",
        tag: "Penger på konto",
        title: "Statens penger står på driftskontoen",
        body: `${kr(heldSum)} kr er moms, arbeidsgiveravgift og skattetrekk dere holder på vegne av staten. Ingenting er satt av på egen konto, så de ser ut som driftsmidler helt til de forfaller.`,
        ask: "Hvor mye av pengene på konto er egentlig statens, når forfaller hver del, og hvordan bør jeg sette dem av?",
        amount: heldSum,
        due: soonest(held),
      })
    }
  }

  for (const k of (dash?.kpis || []).filter(
    (k) => k.value != null && (k.status === "bad" || k.status === "watch"),
  )) {
    const v = k.value as number
    const over = k.better === "low" ? v > k.alert : v < k.alert
    // Bare hovedtallet kan være kritisk. Bransjeprofilen har allerede pekt ut
    // det ene nøkkeltallet som avgjør denne driften; lar vi alle som ligger
    // forbi varselnivået bli kritiske, står det fire røde kort der og da sier
    // fargen ingenting lenger. De andre blir advarsler, og rangeres i stedet
    // etter hvor langt unna målet de ligger.
    const miss = k.target ? Math.abs(v - k.target) / Math.abs(k.target) : 0
    out.push({
      id: `kpi:${k.id}:${Math.round(v)}`,
      sev: k.status === "bad" && k.headline ? "crit" : "warn",
      tag: "Nøkkeltall",
      title: `${k.label} er ${unit(v, k.unit)} mot ${unit(k.target, k.unit, 0)} i mål`,
      body: k.why,
      ask: `Hvorfor ligger ${k.label.toLowerCase()} på ${unit(v, k.unit)}? Er dette et nivåskifte eller en engangseffekt, og hva skal til for å nå målet?`,
      nudge: Math.min(200, miss * 200) + (k.status === "bad" ? 60 : 0) + (over ? 40 : 0),
    })
  }

  if (ov?.top_debtor && ov.top_debtor.share_pct >= 25) {
    const d = ov.top_debtor
    out.push({
      id: `debtor:${d.name}:${Math.round(d.share_pct)}`,
      sev: "warn",
      tag: "Kunder",
      title: `${d.name} er ${pct(d.share_pct, 0)} av alt kundene skylder`,
      body: `De skylder ${kr(d.amount)} kr av totalt ${kr(ov.kpis?.kundefordringer)} kr. Blir den betalingen forsinket, er det kontantstrømmen deres som venter.`,
      ask: `Gå gjennom ${d.name}: hva er fakturert, hva er forfalt, hvor lenge har de brukt på å betale før, og hva er eksponeringen vår hvis de stopper?`,
      amount: d.amount,
    })
  }
  if (ov?.flags?.ubokfort_skatt) {
    out.push({
      id: "tax_unbooked",
      sev: "note",
      tag: "Regnskap",
      title: "Skatten er ikke satt av",
      body: `Regnskapet viser 0 i skattekostnad. Med 22 % selskapsskatt bygger det seg opp rundt ${kr(ov.flags.ubokfort_skatt)} kr som ikke er synlig i resultatet.`,
      ask: "Hvor mye skatt burde vært avsatt hittil i år, og hva gjør det med resultatet?",
      amount: ov.flags.ubokfort_skatt,
    })
  }

  return rank(out)
}

/* ── overskriften: én setning, den viktigste ──────────────────── */
function headline(data: Data, list: Signal[]) {
  const { cash, ov } = data
  if (cash) {
    const { amount: floor, assumed } = floorOf(data)
    const dip = cash.weeks.findIndex((w) => w.committed_close < floor)
    const debtor = ov?.top_debtor?.name
    // "hvis ingenting endres" is the committed line by definition — nothing
    // new invoiced, nothing new collected.
    if (cash.goes_negative_committed) {
      return `Kontoen er tom i ${cash.goes_negative_committed.label.toLowerCase()} hvis ingenting endres.`
    }
    if (dip > 0 && floor) {
      const safe = cash.weeks[dip - 1]
      const hit = cash.weeks[dip]
      return (
        `Dere er trygge til og med ${safe.label.toLowerCase()}. I ${hit.label.toLowerCase()} faller kontoen under gulvet` +
        (debtor ? `, med mindre ${debtor} betaler.` : ".")
      )
    }
    if (dip === -1 && floor) {
      return `Kontantstrømmen holder seg over gulvet på ${kr(floor)} kr${assumed ? " (antatt)" : ""} alle de neste 13 ukene. Tynnest i ${cash.low_committed.label.toLowerCase()}, med ${kr(cash.low_committed.amount)} kr.`
    }
  }
  const crit = list.find((s) => s.sev === "crit")
  return crit ? stop(crit.title) : "Ingenting krever handling i dag."
}

/* ── kontantgrafen ────────────────────────────────────────────── */
// Fargeparet er kjørt gjennom fargevalidatoren i begge moduser.
const chartConfig = {
  committed_close: { label: "bundet", color: "var(--chart-committed)" },
  expected_close: { label: "anslag", color: "var(--chart-expected)" },
} satisfies ChartConfig

function CashChart({ cash, rules }: { cash: Cashflow; rules?: Rules }) {
  const { amount: floor, tag } = floorOf({ rules })
  const data = cash.weeks.map((w) => ({ ...w, week: w.label.replace("Uke ", "") }))
  return (
    <ChartContainer config={chartConfig} className="h-[260px] w-full sm:h-[300px] xl:h-[340px]">
      <LineChart data={data} margin={{ left: 8, right: 16, top: 16, bottom: 8 }}>
        <CartesianGrid vertical={false} stroke="var(--border)" />
        <XAxis
          dataKey="week"
          tickLine={false}
          axisLine={false}
          tickMargin={10}
          // Alle tretten når det er plass; på en smal skjerm hoppes annenhver
          // over i stedet for at tallene skrives oppå hverandre.
          interval="preserveStartEnd"
          minTickGap={6}
        />
        <YAxis
          tickLine={false}
          axisLine={false}
          // Smalere enn dette brekker «800 000» over to linjer.
          width={74}
          tickFormatter={(v) => mill(v as number)}
        />
        {floor > 0 && (
          <ReferenceLine
            y={floor}
            stroke="var(--chart-floor)"
            strokeDasharray="2 4"
            label={{
              value: `Gulv · ${tag} ${mill(floor)}`,
              position: "insideBottomLeft",
              fill: "var(--muted-foreground)",
              fontSize: 12,
            }}
          />
        )}
        <ChartTooltip
          content={
            <ChartTooltipContent
              labelFormatter={(_, p) => {
                const w = p?.[0]?.payload as { label: string; start: string }
                return w ? `${w.label} · fra ${dateNo(w.start)}` : ""
              }}
              formatter={(value, name) => (
                <div className="flex w-full items-center justify-between gap-4">
                  <span className="text-muted-foreground">
                    {chartConfig[name as keyof typeof chartConfig]?.label ?? name}
                  </span>
                  <span className="font-medium tabular-nums">
                    {kr(value as number)}
                  </span>
                </div>
              )}
            />
          }
        />
        <Line
          dataKey="committed_close"
          stroke="var(--color-committed_close)"
          strokeWidth={2}
          dot={false}
          activeDot={{ r: 4 }}
        />
        <Line
          dataKey="expected_close"
          stroke="var(--color-expected_close)"
          strokeWidth={2}
          strokeDasharray="6 5"
          dot={false}
          activeDot={{ r: 4 }}
        />
        <ChartLegend content={<ChartLegendContent />} />
      </LineChart>
    </ChartContainer>
  )
}

/* Uke for uke, under kurven. Kurven viser formen, tabellen er den man følger:
 * «hvilken uke er det tynt, og hvor mye kommer inn den uka». Inn og Ut legger
 * bundet og forventet sammen i én kolonne, mens de to saldoene står hver for
 * seg — samme oppsett som tabellen CFO-en har i prompten, så det han sier i
 * samtalen og det som står på skjermen er det samme bildet. */
function CashTable({ cash }: { cash: Cashflow }) {
  const low = cash.low_committed.label
  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          {["Uke", "Fra", "Inn", "Ut", "Bundet", "Forventet"].map((h, i) => (
            <TableHead
              key={h}
              className={`text-muted-foreground border-[var(--gray-300)] h-9 text-[13px] font-medium ${
                i > 1 ? "text-right" : ""
              }`}
            >
              {h}
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {cash.weeks.map((w) => {
          const thin = w.label === low
          return (
            <TableRow
              key={w.index}
              // Den tynneste uka er hele poenget med tabellen, så den er den
              // ene raden som får lov til å rope.
              className={thin ? "bg-brand-100/60 hover:bg-brand-100/60 dark:bg-brand-950 dark:hover:bg-brand-950" : undefined}
            >
              <TableCell className="py-2.5 font-medium">
                {w.label}
                {thin && (
                  <span className="text-good-text ml-2 text-xs font-medium">tynnest</span>
                )}
                {w.index === 0 && !thin && (
                  <span className="text-muted-foreground ml-2 text-xs">nå</span>
                )}
              </TableCell>
              <TableCell className="text-muted-foreground py-2.5 text-[13px]">
                {dateShortNo(w.start)}
              </TableCell>
              {/* En uke uten bevegelse er et faktum, ikke et hull, så nullen
                  blir stående — men dempet, så øyet går til ukene der det
                  faktisk skjer noe. */}
              <TableCell
                className={`py-2.5 text-right tabular-nums ${
                  w.in + w.expected_in ? "" : "text-muted-foreground/40"
                }`}
              >
                {kr(w.in + w.expected_in)}
              </TableCell>
              <TableCell
                className={`py-2.5 text-right tabular-nums ${
                  w.out + w.expected_out ? "text-muted-foreground" : "text-muted-foreground/40"
                }`}
              >
                {kr(-(w.out + w.expected_out))}
              </TableCell>
              <TableCell
                className={`py-2.5 text-right font-medium tabular-nums ${
                  w.committed_close < 0 ? "text-bad-text" : ""
                }`}
              >
                {kr(w.committed_close)}
              </TableCell>
              <TableCell
                className={`py-2.5 text-right tabular-nums ${
                  w.expected_close < 0 ? "text-bad-text" : "text-muted-foreground"
                }`}
              >
                {kr(w.expected_close)}
              </TableCell>
            </TableRow>
          )
        })}
      </TableBody>
    </Table>
  )
}

/* ── dommen ───────────────────────────────────────────────────── */
/** «Mandag, uke 41» fra brevet; uten brev, dagens dato. */
function weekLine(weekly: WeeklyBrief | null | undefined, asOf: string) {
  const cap = (t: string) => t.charAt(0).toUpperCase() + t.slice(1)
  if (weekly) {
    const week = Number(weekly.period.split("-W")[1])
    // Et brev fra en tidligere uke sier fra hvilken dag det er, ikke hvilken
    // dag det er i dag.
    return weekly.current
      ? `${cap(dayNo(weekly.made_on))}, uke ${week}`
      : `Uke ${week} · skrevet ${dayNo(weekly.made_on)} ${dateNo(weekly.made_on)}`
  }
  return `${cap(dayNo(asOf))} ${dateNo(asOf)}`
}

/** «Driftsmargin: 2,4 %, fra 3,4 %.» som tre deler, så tallet kan stå stort.
 *  Står setningen i en annen form, vises den som den er. */
function change(line: string): { label: string; now: string; before: string } | null {
  const m = line.match(/^(.+?):\s*(.+?),\s*fra\s+(.+?)\.?$/)
  return m ? { label: m[1], now: m[2], before: m[3] } : null
}

/** «Sendt på e-post til deg@x.no mandag kl 07:01», fra tidspunktet serveren
 *  lagret. */
function sentLine(sent: NonNullable<WeeklyBrief["sent"]>) {
  const when = new Date(sent.at).toLocaleString("nb-NO", {
    weekday: "long",
    hour: "2-digit",
    minute: "2-digit",
  })
  return `Sendt på e-post til ${sent.to.join(", ")} ${when}.`
}

/** Det laveste punktet de neste tretten ukene, som ett tall med hva det
 *  betyr under: hvor langt fra gulvet, og om gulvet er deres eget. */
function LowPoint({ low }: { low: WeeklyBrief["low_point"] }) {
  const gap = Math.abs(low.amount - low.floor)
  return (
    <aside className="border-border border-t pt-6 xl:border-t-0 xl:border-l xl:pt-0 xl:pb-2 xl:pl-12">
      <p className="label">Laveste punkt</p>
      <p className="mt-3 text-[clamp(40px,4vw,52px)] leading-none font-light tracking-[-0.03em] whitespace-nowrap">
        {kr(low.amount)}
        <span className="text-muted-foreground ml-1.5 text-[0.4em] tracking-normal">kr</span>
      </p>
      <p className="text-muted-foreground mt-3 text-[15px]">
        {low.week}
        {low.start && ` · fra ${dateNo(low.start)}`}
      </p>
      {low.floor > 0 && (
        <p className="border-border mt-5 border-t pt-4 text-[15px] leading-6">
          <span className={low.under_floor ? "text-bad-text font-medium" : "text-good-text font-medium"}>
            {kr(gap)} kr {low.under_floor ? "under" : "over"} gulvet
          </span>
          <span className="text-muted-foreground">
            {" "}på {kr(low.floor)} kr
            {low.floor_assumed && (
              <>
                {" "}— antatt, ikke satt av dere.{" "}
                <a href="#selskapet" className="text-good-text hover:underline">
                  Sett deres eget →
                </a>
              </>
            )}
          </span>
        </p>
      )}
    </aside>
  )
}

/* ── nøkkeltallene ────────────────────────────────────────────── */
type Kpi = Dashboard["kpis"][number]

/** Ett nøkkeltall mot målet: tallet, en tynn linje med målet som strek, og
 *  hva tallet betyr. Grønt bare når backend sier «good»; en status frontenden
 *  ikke kjenner, males aldri som frisk. */
function KpiRow({ k }: { k: Kpi }) {
  // Backend melder «unknown» når tallet ikke lar seg regne ut nå. Da er en tom
  // linje verre enn ingen linje.
  const missing = k.value == null || k.status === "unknown"
  const scale = Math.max(k.value ?? 0, k.target, k.alert) * 1.15 || 1
  const tone = missing
    ? "text-muted-foreground"
    : k.status === "bad"
      ? "text-bad-text"
      : k.status === "good"
        ? "text-good-text"
        : "text-warn-text"
  const bar = k.status === "bad" ? "bg-negative" : k.status === "good" ? "bg-positive" : "bg-warning"
  return (
    <div className="border-border border-t py-5">
      <div className="flex items-baseline justify-between gap-4">
        <span className="min-w-0 text-[15px] font-medium">{k.label}</span>
        <span className={`shrink-0 text-[20px] font-light whitespace-nowrap ${tone}`}>
          {unit(k.value, k.unit)}
        </span>
      </div>
      {missing ? (
        <p className="text-muted-foreground my-3 text-[13px]">Ikke tilgjengelig nå</p>
      ) : (
        <div className="bg-secondary relative my-3 h-1 rounded-full" aria-hidden>
          <span
            className={`block h-full rounded-full ${bar}`}
            style={{ width: `${Math.min(100, ((k.value ?? 0) / scale) * 100)}%` }}
          />
          <i
            className="bg-foreground absolute -top-1.5 -bottom-1.5 w-px"
            style={{ left: `${Math.min(100, (k.target / scale) * 100)}%` }}
          />
        </div>
      )}
      <p className="text-muted-foreground text-[13px] leading-5">
        {k.plain}. Mål {unit(k.target, k.unit, 0)}.
      </p>
    </div>
  )
}

/* ── siden ────────────────────────────────────────────────────── */
export function Brief({ onCount }: { onCount?: (n: number) => void }) {
  const [d, setD] = useState<Data>({})
  const [loading, setLoading] = useState(true)
  const [failed, setFailed] = useState(false)
  const [had] = useState(seenIds)
  const [rewriting, setRewriting] = useState(false)

  const loadAll = () => {
    setLoading(true)
    setFailed(false)
    const jobs = [
      api.overview().then((ov) => setD((s) => ({ ...s, ov }))),
      api.dashboard().then((dash) => setD((s) => ({ ...s, dash }))),
      api.commitments().then((com) => setD((s) => ({ ...s, com }))),
      api.preflight().then((pre) => setD((s) => ({ ...s, pre }))),
      api
        .cashflow()
        .then((cash) => setD((s) => ({ ...s, cash, cashError: undefined })))
        .catch((e: unknown) => {
          setD((s) => ({ ...s, cashError: e instanceof Error ? e.message : String(e) }))
          throw e
        }),
      api.rules().then((r) => setD((s) => ({ ...s, rules: r.rules }))),
    ]
    Promise.allSettled(jobs).then((res) => {
      setLoading(false)
      setFailed(res.every((r) => r.status === "rejected"))
    })
    // Oppsummeringen står for seg: den er skrevet, ikke regnet ut, og skal
    // verken holde igjen resten av forsiden eller felle den om den feiler.
    api
      .summary()
      .then((sum) => setD((s) => ({ ...s, sum })))
      // Grunnen beholdes. Kortet skal kunne si hvorfor det ikke står noe der,
      // ellers ser en tom oppsummering likedan ut uansett årsak.
      .catch((e: unknown) =>
        setD((s) => ({ ...s, sum: { error: e instanceof Error ? e.message : String(e) } })),
      )
    // Mandagsbrevet står også for seg: det er lagret, ikke regnet ut nå.
    api
      .brief()
      .then((r) => setD((s) => ({ ...s, weekly: r.brief })))
      .catch(() => setD((s) => ({ ...s, weekly: null })))
    // Om morgenkjøringen gjorde jobben sin. Står for seg, som oppsummeringen.
    api
      .schedule()
      .then((sched) => setD((s) => ({ ...s, sched })))
      .catch(() => {})
  }

  useEffect(loadAll, [])

  // Kjører morgenjobben på nytt for hånd, og laster forsiden når den er ferdig.
  // Tar et minutt eller to: den henter alt og skriver oppsummeringen.
  const [runningNow, setRunningNow] = useState(false)
  const runNow = (name: string) => {
    setRunningNow(true)
    authFetch(`/api/schedule/${name}/run`, { method: "POST" })
      .catch(() => {})
      .finally(() => {
        setRunningNow(false)
        loadAll()
      })
  }

  // Sender ukas lagrede brev på e-post, og laster brevet på nytt så kortet
  // viser når det gikk og til hvem. Feiler det, sier planleggerens linje
  // øverst hvorfor.
  const [sendingNow, setSendingNow] = useState(false)
  const sendNow = () => {
    setSendingNow(true)
    authFetch("/api/schedule/weekly_mail/run", { method: "POST" })
      .catch(() => {})
      .finally(() => {
        setSendingNow(false)
        api.brief().then((r) => setD((s) => ({ ...s, weekly: r.brief }))).catch(() => {})
        api.schedule().then((sched) => setD((s) => ({ ...s, sched }))).catch(() => {})
      })
  }

  const rewrite = () => {
    setRewriting(true)
    get<Summary>("/api/summary?refresh=true")
      .then((sum) => setD((s) => ({ ...s, sum })))
      .catch(() => {})
      .finally(() => setRewriting(false))
  }

  const signals = useMemo(() => buildSignals(d), [d])
  useEffect(() => {
    if (signals.length) markSeen(signals.map((s) => s.id), had)
  }, [signals, had])

  const asOf = d.cash?.as_of || d.ov?.generated_at || new Date().toISOString().slice(0, 10)
  const fresh = signals.filter((s) => !had.has(s.id)).length
  const prepared = preparedAt(d.sched)
  const attention = (d.sched?.jobs || []).filter((j) => j.attention)
  const cleanup = (d.pre?.checks || []).filter((c) => c.status !== "ok")

  // Den ene saken som trenger en beslutning: den øverste blant de åpne, med
  // de samme knappene som på Saker.
  const deck = useDeck(onCount)
  const openCases = deck.deck?.open || []
  const top = openCases[0]

  // «Grav i dette» åpner en ny samtale med spørsmålet allerede stilt.
  const { ask: askCfo } = useConversations()
  const ask = (q: string, title: string) => askCfo(q, title, true)

  return (
    <div className="space-y-16 sm:space-y-20">
      {/* ── 1. Dommen: fargen, én setning og det ene tallet som betyr noe ── */}
      <header className="arv-rise pt-8">
        <div className="label mb-6 flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span>{weekLine(d.weekly, asOf)}</span>
          {prepared && <span>· klargjort {prepared}</span>}
          <Button variant="link" className="text-[13px]" onClick={loadAll} disabled={loading}>
            Oppdater
          </Button>
        </div>
        {/* Dommen til venstre, det ene tallet den hviler på til høyre: på en
            bred skjerm fyller de to bredden sammen i stedet for at setningen
            står alene mot venstre kant. Først fra xl: ved 1024 px med menyen
            åpen ble setningen klemt til seks linjer ved siden av tallet. */}
        <div className="grid gap-x-16 gap-y-10 xl:grid-cols-[minmax(0,1fr)_minmax(300px,340px)] xl:items-end 2xl:grid-cols-[minmax(0,1fr)_minmax(320px,380px)] 2xl:gap-x-20">
        <div className="min-w-0">
        {d.weekly && !failed && <Status light={d.weekly.light} className="mb-4" />}
        {loading && !d.cash && d.weekly === undefined ? (
          <div className="grid gap-3">
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-2/3" />
          </div>
        ) : failed ? (
          <h1 className="font-heading text-[clamp(30px,3.6vw,44px)] leading-[1.1] tracking-[-0.02em] text-pretty">
            Får ikke tak i regnskapet akkurat nå. Spørsmålsfeltet virker fortsatt.
          </h1>
        ) : (
          <h1 className="font-heading max-w-[22ch] text-[clamp(34px,4.4vw,58px)] leading-[1.05] tracking-[-0.03em] text-balance">
            {d.weekly ? stop(d.weekly.sentence) : headline(d, signals)}
          </h1>
        )}
        {/* Uten et tall å stå på står forklaringen som ingress i stedet. */}
        {d.weekly?.low_point.text && !failed && !(d.weekly.low_point.amount != null && d.weekly.low_point.week) && (
          <p className="text-[var(--gray-700)] dark:text-[var(--gray-300)] mt-5 max-w-[640px] text-[18px] leading-[28px] text-pretty">
            {d.weekly.low_point.text}
          </p>
        )}
        </div>
        {d.weekly && !failed && d.weekly.low_point.amount != null && d.weekly.low_point.week && (
          <LowPoint low={d.weekly.low_point} />
        )}
        </div>
        {/* Uten brev er det ingen dom å vise, så det å få skrevet det står
            øverst. Alt annet som ikke kjørte, står nederst. */}
        {d.weekly === null && !failed && (
          <div className="bg-tint mt-6 flex flex-wrap items-baseline justify-between gap-3 rounded-xl px-5 py-4">
            <p className="text-[15px]">
              Mandagsbrevet skrives første virkedag hver uke kl 07. Det er ikke skrevet ennå.
            </p>
            <Button variant="link" onClick={() => runNow("weekly_brief")} disabled={runningNow}>
              {runningNow ? "Skriver …" : "Skriv det nå"}
            </Button>
          </div>
        )}
      </header>

      {/* ── 2. Trenger deg: den ene saken, med knappene ── */}
      {top ? (
        <section
          aria-labelledby="trenger-deg"
          className="bg-tint arv-rise rounded-xl px-6 py-7 sm:px-10 sm:py-9 xl:px-12 xl:py-10"
          style={{ "--i": 1 } as React.CSSProperties}
        >
          <div className="mb-5 flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
            <span id="trenger-deg" className="label">
              Trenger deg · 1 av {openCases.length}
            </span>
            {openCases.length > 1 && (
              <a href="#saker" className="text-good-text text-sm font-medium hover:underline">
                Se alle {openCases.length} i Saker →
              </a>
            )}
          </div>
          {/* Tallene bak saken står ved siden av når blokken er bred nok, der
              det ellers ville stått tomt. Smalt holdes knappene nær teksten. */}
          <DecisionBody c={top} state={deck} facts="wide" />
        </section>
      ) : deck.deck && d.weekly?.light === "green" ? (
        <p className="font-heading arv-rise text-[28px] leading-tight tracking-[-0.015em]">
          “Ingenting trenger deg denne uken.”
        </p>
      ) : null}

      {/* ── 3. Hva endret seg siden forrige mandag ── */}
      {!!d.weekly?.changed.length && (
        <section className="arv-rise" style={{ "--i": 2 } as React.CSSProperties}>
          <SectionHead title="Hva endret seg" aside="Siden forrige mandag" />
          <div className="border-border grid border-t sm:grid-cols-3">
            {d.weekly.changed.map((c, i) => {
              const ch = change(c)
              return (
                <div
                  key={c}
                  className={`border-border border-b py-5 sm:border-b-0 ${
                    i > 0 ? "sm:border-l sm:pl-6" : ""
                  } sm:pr-6`}
                >
                  {ch ? (
                    <>
                      <p className="label">{ch.label}</p>
                      <p className="mt-2 text-[28px] leading-none font-light tracking-[-0.02em]">
                        {ch.now}
                      </p>
                      <p className="text-muted-foreground mt-2 text-[13px]">fra {ch.before}</p>
                    </>
                  ) : (
                    <p className="text-[15px] leading-6">{c}</p>
                  )}
                </div>
              )
            })}
          </div>
        </section>
      )}

      {/* ── 4. De tretten ukene: svaret på «klarer jeg det» ── */}
      <section>
        <SectionHead
          title="Kontantene de neste 13 ukene"
          aside={
            d.cash && (
              <>
                {kr(d.cash.opening)} kr nå
                {d.cash.bank?.adjustment == null
                  ? d.cash.bank && " (bokført, banken ikke lest)"
                  : Math.abs(d.cash.bank.adjustment) >= 1 &&
                    ` i banken (bokført ${kr(d.cash.bank.booked)})`}
                {" "}· tynnest {d.cash.low_committed.label.toLowerCase()} fra{" "}
                {dateNo(d.cash.low_committed.start)}
              </>
            )
          }
        />
        {/* grid-cols-[minmax(0,1fr)], ikke bare «grid»: en rute er som
            standard minst like bred som innholdet, og tabellen med seks
            kolonner presset kortet forbi skjermkanten på mobil. Nå krymper
            ruta, og tabellen ruller inni sin egen boks. */}
        <Card className="rounded-xl">
          <CardContent className="grid grid-cols-[minmax(0,1fr)] gap-6">
            {d.cash ? (
              <>
                <CashChart cash={d.cash} rules={d.rules} />
                <p className="text-muted-foreground max-w-[72ch] text-[13px] leading-5">
                  Tynnest i {d.cash.low_committed.label.toLowerCase()}:{" "}
                  <span className="text-foreground font-medium">
                    {kr(d.cash.low_committed.amount)} kr
                  </span>{" "}
                  bundet
                  {d.cash.goes_negative_committed
                    ? `, og den bundne linjen går i minus i ${d.cash.goes_negative_committed.label.toLowerCase()}.`
                    : d.cash.goes_negative
                      ? `, og den forventede linjen går i minus i ${d.cash.goes_negative.label.toLowerCase()}.`
                      : ". Ingen av linjene går i minus i perioden."}{" "}
                  Bundet er det som alt er fakturert inn og ut, lønn og skattedatoer.
                  Forventet legger vanlig drift på toppen, og er et anslag.
                </p>
                <Collapsible>
                  <CollapsibleTrigger className="group text-good-text flex items-center gap-1.5 text-sm font-medium">
                    Vis uke for uke
                    <ChevronDown className="size-4 stroke-[1.5] transition-transform duration-300 group-data-[panel-open]:rotate-180" />
                  </CollapsibleTrigger>
                  <CollapsibleContent className="mt-4">
                    <CashTable cash={d.cash} />
                  </CollapsibleContent>
                </Collapsible>
              </>
            ) : d.cashError ? (
              <div className="grid min-h-[160px] place-content-center gap-2 text-center">
                <p className="font-heading text-[22px]">Prognosen er ikke tilgjengelig akkurat nå.</p>
                <p className="text-muted-foreground mx-auto max-w-[56ch] text-[13px] leading-5">
                  {d.cashError}
                </p>
              </div>
            ) : (
              <Skeleton className="h-[260px] w-full sm:h-[300px] xl:h-[340px]" />
            )}
          </CardContent>
        </Card>
      </section>

      {/* ── 5. Nøkkeltall: de fire store tallene og målene, samlet ── */}
      <section>
        <SectionHead
          title="Nøkkeltall"
          aside={d.dash?.industry ? `Målt mot ${d.dash.industry.toLowerCase()}` : undefined}
        />
        {/* Fire i bredden først når hvert kort får plass til tallet sitt; ved
            1024 px med menyen åpen ble de 160 px smale. */}
        <div className="grid gap-3 sm:grid-cols-2 lg:gap-4 xl:grid-cols-4">
          {metrics(d).map((c) => (
            <MetricCard
              key={c.label}
              label={c.label}
              value={c.value}
              series={c.series}
              note={c.note}
              kind={c.kind}
              partial={c.partial}
              loading={loading && !d.ov}
            />
          ))}
        </div>
        {!!d.dash?.kpis?.length && (
          <div className="mt-12 grid gap-x-12 sm:grid-cols-2 2xl:grid-cols-3">
            {d.dash.kpis.map((k) => (
              <KpiRow key={k.id} k={k} />
            ))}
          </div>
        )}
      </section>

      {/* ── 6 og 7: Arvaka om driften ved siden av det som er verdt å følge
          med på. Prosaen holder lesebredden, så på en bred skjerm får lista
          resten av plassen i stedet for at halve siden står tom. ── */}
      <div
        className={`grid gap-16 sm:gap-20 ${
          signals.length ? "xl:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] xl:gap-x-16 2xl:gap-x-24" : ""
        }`}
      >
        <section>
          <SummaryCard
            data={d.sum}
            loading={loading && !d.sum}
            refreshing={rewriting}
            onRefresh={rewrite}
            onAsk={() =>
              ask(
                "Gå gjennom hvordan det går i selskapet nå: omsetning, lønnskostnad, driftsresultat og penger på konto de siste månedene. Hva har endret seg, og hva bør jeg gjøre noe med?",
                "Hvordan det går",
              )
            }
          />
        </section>

        {signals.length > 0 && (
          <section>
            <SectionHead
              title="Verdt å følge med på"
              aside={fresh ? `${fresh} nytt siden sist du var her` : "Ingenting nytt siden sist"}
            />
            <SignalList signals={signals} seen={had} onAsk={(s: Signal) => ask(s.ask, s.title)} />
          </section>
        )}
      </div>

      {/* ── Bunnlinja: hvor ferske tallene er, og det som ikke kjørte ── */}
      <footer className="border-border text-muted-foreground grid gap-3 border-t pt-6 text-[13px] leading-5">
        {d.weekly && (
          <>
            <p>
              {d.weekly.books.text}
              {d.weekly.books.lines.length > 0 && " " + d.weekly.books.lines.join(" ")}
            </p>
            <p>{d.weekly.accuracy.text}</p>
            {d.weekly.written_by === "engine" && (
              <p>Skrevet ut fra tallene alene denne gangen — Arvaka fikk ikke skrevet sine egne ord.</p>
            )}
            {d.weekly.current && (
              <p className="flex flex-wrap items-baseline gap-x-3">
                <span>{d.weekly.sent ? sentLine(d.weekly.sent) : "Ikke sendt på e-post ennå."}</span>
                <Button variant="link" className="text-[13px]" onClick={sendNow} disabled={sendingNow}>
                  {sendingNow ? "Sender …" : d.weekly.sent ? "Send igjen" : "Send på e-post nå"}
                </Button>
              </p>
            )}
            {!d.weekly.current && <p>Brevet er fra {dateNo(d.weekly.made_on)}.</p>}
          </>
        )}
        <div className="flex flex-wrap gap-x-6 gap-y-2">
          {!!cleanup.length && (
            <Collapsible>
              <CollapsibleTrigger className="group hover:text-foreground flex items-center gap-2">
                <Dot tone="warn" />
                {cleanup.length} ting å rydde i regnskapet
                <ChevronDown className="size-3.5 stroke-[1.5] transition-transform duration-300 group-data-[panel-open]:rotate-180" />
              </CollapsibleTrigger>
              <CollapsibleContent className="mt-3 grid max-w-[72ch] gap-2">
                {cleanup.map((c) => (
                  <p key={c.id}>
                    <span className="text-foreground font-medium">{c.label}</span> {c.headline}
                  </p>
                ))}
              </CollapsibleContent>
            </Collapsible>
          )}
          {!!attention.length && (
            <Collapsible>
              <CollapsibleTrigger className="group hover:text-foreground flex items-center gap-2">
                <Dot tone="quiet" />
                {attention.length === 1
                  ? "1 kjøring gikk ikke som planlagt"
                  : `${attention.length} kjøringer gikk ikke som planlagt`}
                <ChevronDown className="size-3.5 stroke-[1.5] transition-transform duration-300 group-data-[panel-open]:rotate-180" />
              </CollapsibleTrigger>
              <CollapsibleContent className="mt-3 grid max-w-[72ch] gap-2">
                {attention.map((j) => (
                  <p key={j.name} className="flex flex-wrap items-baseline gap-x-3">
                    <span>{j.attention}</span>
                    <Button
                      variant="link"
                      className="text-[13px]"
                      onClick={() => runNow(j.name)}
                      disabled={runningNow}
                    >
                      {runningNow ? "Kjører …" : "Kjør nå"}
                    </Button>
                  </p>
                ))}
              </CollapsibleContent>
            </Collapsible>
          )}
        </div>
      </footer>
    </div>
  )
}
