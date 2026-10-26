/* Måling: om produktet virker, målt slik spilleboka sier. For produkteieren,
 * ikke for kunden — siden står ikke i menyen. Alt er lest fra det produktet
 * allerede tar vare på; ingenting er anslått. */
import { useEffect, useState, type ReactNode } from "react"

import { PageHeader, SectionHead } from "@/components/brand"
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
    <th className="label pr-6 pb-3 text-left whitespace-nowrap">
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
    <div className="space-y-14">
      <PageHeader
        eyebrow="Måling · for produkteieren"
        title="Virker det?"
        lead="Målt slik spilleboka sier: tid hos daglig leder, hvor mye av det forberedte arbeidet som godkjennes uten endringer, fall i banken varslet i forkant, og hva agenten koster. Kunden ser ikke denne siden."
      />

      {data === undefined ? (
        <Skeleton className="h-48 w-full" />
      ) : !data ? (
        <p className="text-destructive text-sm">{failed || "Målingene kunne ikke hentes."}</p>
      ) : (
        <>
          <section>
            <SectionHead title="Uke for uke" />
            <p className="text-muted-foreground -mt-2 mb-6 max-w-[72ch] text-[15px] leading-6">
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
                          <td className="py-3 pr-6">
                            <span className="font-medium">{w.week.split("-W")[1].replace(/^0/, "")}</span>
                            <span className="text-muted-foreground ml-2 text-xs">
                              fra {dateNo(w.from)}
                            </span>
                          </td>
                          <td className={`py-3 pr-6 ${over ? "text-warn-text" : ""}`}>
                            {w.minutes} min
                          </td>
                          <td className="py-3 pr-6">{d?.decided ?? 0}</td>
                          <td className="py-3 pr-6">{d?.approved ?? 0}</td>
                          <td className="py-3 pr-6">
                            {d?.unedited_pct != null ? `${d.unedited_pct.toLocaleString("nb-NO")} %` : "–"}
                          </td>
                          <td className="py-3 pr-6">{hours(d?.median_hours_to_decide)}</td>
                          <td className="py-3 pr-6" title={w.cost ? Object.entries(w.cost.by_job)
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
            <SectionHead title="Fall i banken, og hvor tidlig de ble varslet" />
            <p className="text-muted-foreground -mt-2 mb-6 max-w-[72ch] text-[15px] leading-6">
              Et fall er en uke banken stengte under gulvet på {kr(data.floor.kr)} kr (
              {data.floor.said}). Varselet er hvor mange uker før den første lagrede prognosen viste
              det samme.
            </p>
            {data.dips.length ? (
              <ul className="divide-border divide-y border-y text-sm">
                {data.dips.map((d) => (
                  <li key={d.week} className="flex flex-wrap justify-between gap-x-6 gap-y-1 py-3.5">
                    <span>
                      Uke {d.week.split("-W")[1].replace(/^0/, "")}: {kr(d.balance)} kr den{" "}
                      {dateNo(d.on)}
                    </span>
                    <span className={d.weeks_ahead == null ? "text-bad-text" : ""}>
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
