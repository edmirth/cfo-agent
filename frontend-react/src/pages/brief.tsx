import { useEffect, useMemo, useState } from "react"
import { CartesianGrid, Line, LineChart, ReferenceLine, XAxis, YAxis } from "recharts"

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
import { Separator } from "@/components/ui/separator"
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
  Summary,
} from "@/lib/api"
import { dateNo, dateShortNo, dayNo, kr, mill, pct, stop, unit } from "@/lib/format"
import { rank } from "@/lib/signals"
import type { Signal } from "@/lib/signals"
import { useConversations } from "@/store/conversations"

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

function metrics({ ov }: Data): CardSpec[] {
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

  const wageTarget = k.lonnsandel_budsjett_pct
  const wageNote = k.lonnsandel_pct
    ? `${pct(k.lonnsandel_pct, 0)} av omsetningen` +
      (wageTarget ? `, mot ${pct(wageTarget, 0)} i budsjettet` : "")
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
function buildSignals({ cash, com, ov, dash }: Data): Signal[] {
  const out: Signal[] = []

  if (cash) {
    const floor = cash.assumptions?.monthly_wages || 0
    if (cash.goes_negative) {
      const week = cash.weeks.find((w) => w.start === cash.goes_negative?.start)
      out.push({
        id: "cash_negative",
        sev: "crit",
        tag: "Kontanter",
        title: `Kontoen går i minus i ${cash.goes_negative.label.toLowerCase()}`,
        body: `Med det som allerede er fakturert inn og ut, er kontoen tom i uka fra ${dateNo(cash.goes_negative.start)}.`,
        ask: "Gå gjennom kontantstrømmen uke for uke fram til uka vi går i minus. Hva er de største utbetalingene, og hva kan flyttes?",
        amount: week ? Math.abs(week.committed_close) : undefined,
        due: cash.goes_negative.start,
      })
    } else {
      const dip = cash.weeks.find((w) => w.committed_close < floor)
      if (dip && floor) {
        out.push({
          id: "cash_floor:" + dip.label,
          sev: "warn",
          tag: "Kontanter",
          title: `Under gulvet i ${dip.label.toLowerCase()}`,
          body: `Den sikre kontantstrømmen faller til ${kr(dip.committed_close)} kr i uka fra ${dateNo(dip.start)} — under én månedslønn (${kr(floor)} kr).`,
          ask: `Hvorfor faller kontantstrømmen under én månedslønn i ${dip.label}? Vis ukene rundt, og hvilke innbetalinger som må komme inn for å unngå det.`,
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
    (k) => k.value != null && (k.status === "bad" || k.status === "warn"),
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
function headline({ cash, ov }: Data, list: Signal[]) {
  if (cash) {
    const floor = cash.assumptions?.monthly_wages || 0
    const dip = cash.weeks.findIndex((w) => w.committed_close < floor)
    const debtor = ov?.top_debtor?.name
    if (cash.goes_negative) {
      return `Kontoen er tom i ${cash.goes_negative.label.toLowerCase()} hvis ingenting endres.`
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
      return `Kontantstrømmen holder seg over én månedslønn alle de neste 13 ukene. Tynnest i ${cash.low_committed.label.toLowerCase()}, med ${kr(cash.low_committed.amount)} kr.`
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

function CashChart({ cash }: { cash: Cashflow }) {
  const floor = cash.assumptions?.monthly_wages || 0
  const data = cash.weeks.map((w) => ({ ...w, week: w.label.replace("Uke ", "") }))
  return (
    <ChartContainer config={chartConfig} className="h-[280px] w-full">
      <LineChart data={data} margin={{ left: 8, right: 16, top: 16, bottom: 8 }}>
        <CartesianGrid vertical={false} />
        <XAxis
          dataKey="week"
          tickLine={false}
          axisLine={false}
          tickMargin={10}
          // Alle tretten, nå kurven har hele bredden å stå på.
          interval={0}
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
            stroke="var(--destructive)"
            strokeDasharray="2 5"
            label={{
              value: `gulv · én månedslønn ${mill(floor)}`,
              position: "insideBottomLeft",
              fill: "var(--destructive)",
              fontSize: 11,
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
                  <span className="font-mono font-medium tabular-nums">
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
              className={`text-muted-foreground h-8 font-mono text-[10px] tracking-[0.12em] uppercase ${
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
              className={thin ? "bg-muted/60 hover:bg-muted/60" : undefined}
            >
              <TableCell className="py-2 font-medium">
                {w.label}
                {thin && (
                  <span className="text-muted-foreground ml-2 font-mono text-[10px] tracking-[0.12em] uppercase">
                    tynnest
                  </span>
                )}
                {w.index === 0 && !thin && (
                  <span className="text-muted-foreground/70 ml-2 font-mono text-[10px] tracking-[0.12em] uppercase">
                    nå
                  </span>
                )}
              </TableCell>
              <TableCell className="text-muted-foreground py-2 font-mono text-xs">
                {dateShortNo(w.start)}
              </TableCell>
              {/* En uke uten bevegelse er et faktum, ikke et hull, så nullen
                  blir stående — men dempet, så øyet går til ukene der det
                  faktisk skjer noe. */}
              <TableCell
                className={`py-2 text-right font-mono tabular-nums ${
                  w.in + w.expected_in ? "" : "text-muted-foreground/40"
                }`}
              >
                {kr(w.in + w.expected_in)}
              </TableCell>
              <TableCell
                className={`py-2 text-right font-mono tabular-nums ${
                  w.out + w.expected_out ? "text-muted-foreground" : "text-muted-foreground/40"
                }`}
              >
                {kr(-(w.out + w.expected_out))}
              </TableCell>
              <TableCell
                className={`py-2 text-right font-mono font-medium tabular-nums ${
                  w.committed_close < 0 ? "text-destructive" : ""
                }`}
              >
                {kr(w.committed_close)}
              </TableCell>
              <TableCell
                className={`py-2 text-right font-mono tabular-nums ${
                  w.expected_close < 0 ? "text-destructive" : "text-muted-foreground"
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

/* ── siden ────────────────────────────────────────────────────── */
export function Brief() {
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
      api.cashflow().then((cash) => setD((s) => ({ ...s, cash }))),
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
  }

  useEffect(loadAll, [])

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

  // «Grav i dette» åpner en ny samtale med spørsmålet allerede stilt.
  const { ask: askCfo } = useConversations()
  const ask = (q: string, title: string) => askCfo(q, title, true)

  return (
    <div className="space-y-10">
      <header className="pt-6">
        <div className="text-muted-foreground mb-3 flex items-baseline gap-3 font-mono text-[11px] tracking-[0.16em] uppercase">
          <span>
            Brief · {dayNo(asOf)} {dateNo(asOf)}
          </span>
          <Button
            variant="link"
            size="sm"
            className="h-auto p-0 text-[11px] tracking-normal normal-case"
            onClick={loadAll}
            disabled={loading}
          >
            Oppdater
          </Button>
        </div>
        {loading && !d.cash ? (
          <Skeleton className="h-16 w-full max-w-2xl" />
        ) : failed ? (
          <h1 className="text-xl font-semibold">
            Får ikke tak i regnskapet akkurat nå. Spørsmålsfeltet virker fortsatt.
          </h1>
        ) : (
          <h1 className="font-heading text-[30px] leading-tight font-semibold tracking-tight text-pretty">
            {headline(d, signals)}
          </h1>
        )}
      </header>

      {/* Slik driften har sett ut de siste månedene. */}
      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
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
      </section>

      {/* Under de fire kortene og over CFO-ens ord: de tretten ukene i full
          bredde. Dette er svaret på «klarer jeg det», og det satt i en tredjedel
          av en rad ved siden av prosa — 180 piksler kurve, annenhver ukenummer,
          ingen tall å følge. Nå kurven over tabellen, og tabellen er den man
          leser med fingeren. */}
      <section>
        <div className="mb-5 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
          <h2 className="text-[17px] font-semibold">De neste 13 ukene</h2>
          {d.cash && (
            <span className="text-muted-foreground font-mono text-xs">
              {kr(d.cash.opening)} kr nå · tynnest{" "}
              {d.cash.low_committed.label.toLowerCase()} fra{" "}
              {dateNo(d.cash.low_committed.start)}
            </span>
          )}
        </div>
        <Card>
          {/* grid-cols-[minmax(0,1fr)], ikke bare «grid»: en rute er som
              standard minst like bred som innholdet, og tabellen med seks
              kolonner presset kortet forbi skjermkanten på mobil — der ble
              Bundet og Forventet liggende utenfor, uten noe å rulle i. Nå
              krymper ruta, og tabellen ruller inni sin egen boks. */}
          <CardContent className="grid grid-cols-[minmax(0,1fr)] gap-6">
            {d.cash ? (
              <>
                <CashChart cash={d.cash} />
                <CashTable cash={d.cash} />
                <p className="text-muted-foreground text-xs leading-relaxed">
                  Tynnest i{" "}
                  <b className="text-foreground font-mono">
                    {d.cash.low_committed.label.toLowerCase()}
                  </b>
                  : {kr(d.cash.low_committed.amount)} kr bundet
                  {d.cash.goes_negative
                    ? `, og den forventede linjen går i minus i ${d.cash.goes_negative.label.toLowerCase()}.`
                    : ". Kontoen går ikke i minus i perioden."}{" "}
                  Bundet er bare det som alt er fakturert inn og ut, lønn og
                  skattedatoer. Forventet legger vanlig drift på toppen, og er
                  et anslag.
                </p>
              </>
            ) : (
              <Skeleton className="h-[280px] w-full" />
            )}
          </CardContent>
        </Card>
      </section>

      {/* CFO-ens egne ord, i full bredde nå kurven har flyttet opp. */}
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
          <Separator className="mb-6" />
          <div className="mb-4 flex items-baseline justify-between gap-4">
            <h2 className="text-[17px] font-semibold">Krever handling</h2>
            <span className="text-muted-foreground font-mono text-xs">
              {fresh ? `${fresh} nytt siden sist du var her` : "Ingenting nytt siden sist"}
            </span>
          </div>
          <SignalList
            signals={signals}
            seen={had}
            onAsk={(s: Signal) => ask(s.ask, s.title)}
          />
        </section>
      )}

      {d.dash?.kpis?.length ? (
        <section>
          <Separator className="mb-6" />
          <div className="mb-5 flex items-baseline justify-between gap-4">
            <h2 className="text-[17px] font-semibold">Nøkkeltall</h2>
            <span className="text-muted-foreground font-mono text-xs">
              {d.dash.industry ? `Målt mot ${d.dash.industry.toLowerCase()}` : ""}
            </span>
          </div>
          <div className="grid gap-x-10 gap-y-6 sm:grid-cols-2 lg:grid-cols-3">
            {d.dash.kpis.map((k) => {
              // Backend melder «unknown» når tallet ikke lar seg regne ut nå.
              // Da er en tom søyle verre enn ingen søyle.
              const missing = k.value == null || k.status === "unknown"
              const scale = Math.max(k.value ?? 0, k.target, k.alert) * 1.15 || 1
              const tone = missing
                ? "text-muted-foreground"
                : k.status === "bad"
                  ? "text-destructive"
                  : k.status === "warn"
                    ? "text-amber-600 dark:text-amber-500"
                    : "text-emerald-700 dark:text-emerald-500"
              const bar =
                k.status === "bad"
                  ? "bg-destructive"
                  : k.status === "warn"
                    ? "bg-amber-500"
                    : "bg-emerald-600"
              return (
                <div key={k.id}>
                  <div className="flex items-baseline justify-between gap-3">
                    <span className="min-w-0 text-sm font-medium">{k.label}</span>
                    <span
                      className={`shrink-0 font-mono text-base font-semibold whitespace-nowrap tabular-nums ${tone}`}
                    >
                      {unit(k.value, k.unit)}
                    </span>
                  </div>
                  {missing ? (
                    <p className="text-muted-foreground my-2 text-xs italic">
                      Ikke tilgjengelig nå
                    </p>
                  ) : (
                    <div className="bg-muted relative my-2 h-1.5 rounded-full">
                      <span
                        className={`block h-full rounded-full ${bar}`}
                        style={{ width: `${Math.min(100, ((k.value ?? 0) / scale) * 100)}%` }}
                      />
                      <i
                        className="bg-foreground absolute -top-1 -bottom-1 w-0.5"
                        style={{ left: `${Math.min(100, (k.target / scale) * 100)}%` }}
                      />
                    </div>
                  )}
                  <p className="text-muted-foreground text-xs leading-relaxed">
                    {k.plain}. Mål {unit(k.target, k.unit, 0)}.
                  </p>
                </div>
              )
            })}
          </div>
        </section>
      ) : null}

      {d.pre?.checks?.some((c) => c.status !== "ok") && (
        <Collapsible className="pt-2">
          <CollapsibleTrigger className="text-muted-foreground hover:text-foreground flex items-center gap-2 text-sm">
            <span className="bg-amber-500 size-1.5 rounded-full" />
            {d.pre.checks.filter((c) => c.status !== "ok").length} ting å rydde i regnskapet ▾
          </CollapsibleTrigger>
          <CollapsibleContent className="mt-3 grid gap-2">
            {d.pre.checks
              .filter((c) => c.status !== "ok")
              .map((c) => (
                <div key={c.id} className="border-border border-l-2 pl-3 text-sm">
                  <b className="font-medium">{c.label}</b>{" "}
                  <span className="text-muted-foreground">{c.headline}</span>
                </div>
              ))}
          </CollapsibleContent>
        </Collapsible>
      )}
    </div>
  )
}
