/* Måling: om produktet virker, målt slik spilleboka sier. For produkteieren,
 * ikke for kunden — siden står ikke i menyen. Alt er lest fra det produktet
 * allerede tar vare på; ingenting er anslått. */
import { useEffect, useState, type ReactNode } from "react"

import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { get } from "@/lib/api"
import { dateNo, kr } from "@/lib/format"

type Week = {
  week: string
  from: string
  minutes: number
  decisions: {
    decided: number
    approved: number
    approved_unedited: number
    approved_edited: number
    unedited_pct: number | null
    median_hours_to_decide: number | null
  } | null
  cost: { usd: number; runs: number; unpriced: number; by_job: Record<string, number> } | null
}
type Dip = {
  week: string
  on: string
  balance: number
  floor: number
  first_flagged: string | null
  weeks_ahead: number | null
}
type Report = {
  weeks: Week[]
  target_minutes: number
  dips: Dip[]
  floor: { kr: number; said: string }
  bank_history_since: string | null
}

const JOBS: Record<string, string> = {
  chat: "Chat",
  oppsummering: "Oppsummering",
  mandagsbrev: "Mandagsbrev",
  vakt: "Morgenvakt",
  helsesjekk: "Helsesjekk",
  bransje: "Bransje",
}

function hours(h: number | null | undefined) {
  if (h == null) return "–"
  return h < 24 ? `${h.toLocaleString("nb-NO")} t` : `${(h / 24).toFixed(1).replace(".", ",")} d`
}

function Head({ children }: { children: ReactNode }) {
  return (
    <th className="text-muted-foreground py-2 pr-4 text-left font-mono text-[10px] font-normal tracking-[0.1em] uppercase">
      {children}
    </th>
  )
}

export function Maling() {
  const [data, setData] = useState<Report | null | undefined>(undefined)
  const [failed, setFailed] = useState<string | null>(null)

  useEffect(() => {
    get<Report>("/api/metrics")
      .then(setData)
      .catch((e: unknown) => {
        setData(null)
        setFailed(e instanceof Error ? e.message : String(e))
      })
  }, [])

  return (
    <div className="space-y-8 pt-6">
      <header>
        <p className="text-muted-foreground mb-3 font-mono text-[11px] tracking-[0.16em] uppercase">
          Måling · for produkteieren
        </p>
        <h1 className="font-heading text-[30px] leading-tight font-semibold tracking-tight">
          Virker det?
        </h1>
        <p className="text-muted-foreground mt-2.5 max-w-[62ch] text-sm">
          Målt slik spilleboka sier: tid hos daglig leder, hvor mye av det forberedte arbeidet som
          godkjennes uten endringer, fall i banken varslet i forkant, og hva agenten koster.
          Kunden ser ikke denne siden.
        </p>
      </header>

      {data === undefined ? (
        <Skeleton className="h-48 w-full" />
      ) : !data ? (
        <p className="text-destructive text-sm">{failed || "Målingene kunne ikke hentes."}</p>
      ) : (
        <>
          <section>
            <h2 className="mb-1 text-[17px] font-semibold">Uke for uke</h2>
            <p className="text-muted-foreground mb-4 text-sm">
              Tid i appen er minutter den var åpen og i fokus. Målet er under{" "}
              {data.target_minutes} minutter i uka.
            </p>
            <Card>
              <CardContent className="overflow-x-auto">
                <table className="w-full text-sm tabular-nums">
                  <thead>
                    <tr>
                      <Head>Uke</Head>
                      <Head>Tid i appen</Head>
                      <Head>Beslutninger</Head>
                      <Head>Godkjent</Head>
                      <Head>Uten endringer</Head>
                      <Head>Tid til beslutning</Head>
                      <Head>Agentkostnad</Head>
                    </tr>
                  </thead>
                  <tbody className="divide-border divide-y">
                    {data.weeks.map((w) => {
                      const d = w.decisions
                      const over = w.minutes > data.target_minutes
                      return (
                        <tr key={w.week}>
                          <td className="py-2 pr-4">
                            <span className="font-medium">{w.week.split("-W")[1].replace(/^0/, "")}</span>
                            <span className="text-muted-foreground ml-2 text-xs">
                              fra {dateNo(w.from)}
                            </span>
                          </td>
                          <td className={`py-2 pr-4 ${over ? "text-amber-600 dark:text-amber-500" : ""}`}>
                            {w.minutes} min
                          </td>
                          <td className="py-2 pr-4">{d?.decided ?? 0}</td>
                          <td className="py-2 pr-4">{d?.approved ?? 0}</td>
                          <td className="py-2 pr-4">
                            {d?.unedited_pct != null ? `${d.unedited_pct.toLocaleString("nb-NO")} %` : "–"}
                          </td>
                          <td className="py-2 pr-4">{hours(d?.median_hours_to_decide)}</td>
                          <td className="py-2 pr-4" title={w.cost ? Object.entries(w.cost.by_job)
                            .map(([j, u]) => `${JOBS[j] ?? j}: $${u.toFixed(2)}`).join("\n") : ""}>
                            {w.cost ? `$${w.cost.usd.toFixed(2)}` : "–"}
                            {w.cost?.unpriced ? (
                              <span className="text-muted-foreground ml-1 text-xs">
                                (+{w.cost.unpriced} uten pris)
                              </span>
                            ) : null}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </CardContent>
            </Card>
            <p className="text-muted-foreground mt-2 text-xs">
              Hold musen over agentkostnaden for å se den per jobb.
            </p>
          </section>

          <section>
            <h2 className="mb-1 text-[17px] font-semibold">Fall i banken, og hvor tidlig de ble varslet</h2>
            <p className="text-muted-foreground mb-4 text-sm">
              Et fall er en uke banken stengte under gulvet på {kr(data.floor.kr)} kr (
              {data.floor.said}). Varselet er hvor mange uker før den første lagrede prognosen viste
              det samme.
            </p>
            {data.dips.length ? (
              <ul className="divide-border divide-y border-y text-sm">
                {data.dips.map((d) => (
                  <li key={d.week} className="flex flex-wrap justify-between gap-x-6 gap-y-1 py-2.5">
                    <span>
                      Uke {d.week.split("-W")[1].replace(/^0/, "")}: {kr(d.balance)} kr den{" "}
                      {dateNo(d.on)}
                    </span>
                    <span className={d.weeks_ahead == null ? "text-destructive" : ""}>
                      {d.weeks_ahead == null
                        ? "Ikke varslet på forhånd"
                        : d.weeks_ahead === 0
                          ? "Varslet samme uke"
                          : `Varslet ${d.weeks_ahead} uke${d.weeks_ahead === 1 ? "" : "r"} før`}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm">
                Ingen fall under gulvet{" "}
                {data.bank_history_since
                  ? `siden ${dateNo(data.bank_history_since)}, da bankens saldo begynte å bli lagret.`
                  : "ennå. Bankens saldo er ikke lagret noen dager ennå."}
              </p>
            )}
          </section>

          <p className="text-muted-foreground text-xs">
            E-post åpnet og lenker trykket på måles ikke ennå: det krever eget domene og at appen er
            på nett. Til da er tid i appen målet på daglig leders tid.
          </p>
        </>
      )}
    </div>
  )
}
