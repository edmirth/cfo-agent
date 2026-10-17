/* Helsesjekken: hvor selskapet står, og hva regnskapsføreren må rydde.
 * Lages på knappen og en gang i måneden. Siden er laget for å skrives ut —
 * nettleserens «Skriv ut → Lagre som PDF» gir dokumentet som kan sendes videre. */
import { useEffect, useState } from "react"
import { Copy, Printer } from "lucide-react"

import { PageHeader, Wordmark } from "@/components/brand"
import { Button } from "@/components/ui/button"
import { Separator } from "@/components/ui/separator"
import { Skeleton } from "@/components/ui/skeleton"
import { get } from "@/lib/api"
import { authFetch } from "@/lib/auth"
import { dateNo, datesNo } from "@/lib/format"

type Health = {
  made_on: string
  written_at: string
  written_by: "model" | "engine"
  summary: string
  sections: { key: string; title: string; text: string }[]
  cleanup: { id: string; text: string }[]
  cleanup_intro: string
  cleanup_text: string
  unverified: string[]
  problem?: string
}

export function Helsesjekk() {
  const [data, setData] = useState<Health | null | undefined>(undefined)
  const [making, setMaking] = useState(false)
  const [failed, setFailed] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  const load = () =>
    get<{ health: Health | null }>("/api/helsesjekk")
      .then((r) => setData(r.health))
      .catch(() => setData(null))

  useEffect(() => {
    load()
  }, [])

  // Lager en ny helsesjekk. Tar et minutt eller to: den henter alt fra
  // Tripletex og skriver begge dokumentene.
  const make = () => {
    setMaking(true)
    setFailed(null)
    authFetch("/api/schedule/health_check/run", { method: "POST" })
      .then(async (r) => {
        const run = await r.json().catch(() => null)
        const step = run?.steps?.[0]
        if (step?.status === "failed") setFailed(step.cause || "Helsesjekken ble ikke laget.")
      })
      .catch(() => setFailed("Fikk ikke kontakt med serveren."))
      .finally(() => {
        setMaking(false)
        load()
      })
  }

  const copy = () => {
    if (!data?.cleanup_text) return
    navigator.clipboard?.writeText(data.cleanup_text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  return (
    <div className="space-y-12 print:space-y-8">
      <div className="print:hidden">
        <PageHeader
          eyebrow={`Helsesjekk${data ? ` · ${dateNo(data.made_on)}` : ""}`}
          title="Hvor selskapet står."
          aside={
            <>
              {data && (
                <Button variant="outline" onClick={() => window.print()}>
                  <Printer /> Lagre som PDF
                </Button>
              )}
              <Button variant={data ? "secondary" : "default"} onClick={make} disabled={making}>
                {making ? "Lager … (et minutt eller to)" : data ? "Lag ny" : "Lag helsesjekken"}
              </Button>
            </>
          }
        />
      </div>
      {/* Papiret: ordmerket og datoen øverst, slik månedsrapporten i
          porteføljen står. Vises bare på utskrift. */}
      <div className="border-border hidden items-baseline justify-between border-b pb-4 print:flex">
        <Wordmark className="text-[22px]" />
        <span className="text-muted-foreground text-xs">
          Helsesjekk{data ? ` · ${dateNo(data.made_on)}` : ""}
        </span>
      </div>

      {failed && <p className="text-bad-text text-sm print:hidden">{failed}</p>}

      {data === undefined || making ? (
        <div className="grid max-w-3xl gap-3">
          <Skeleton className="h-5 w-2/3" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-[90%]" />
          <Skeleton className="h-4 w-[95%]" />
        </div>
      ) : !data ? (
        <p className="text-muted-foreground max-w-[60ch] text-[15px]">
          Ingen helsesjekk er laget ennå. Den lages også av seg selv på den 6. virkedagen i
          hver måned.
        </p>
      ) : (
        <article className="max-w-[680px] space-y-10">
          <p className="font-heading text-[28px] leading-[1.2] tracking-[-0.015em] text-pretty print:text-[22px]">
            {data.summary}
          </p>

          {data.sections.map((s) => (
            <section key={s.key} className="break-inside-avoid">
              <h2 className="font-heading mb-3 text-[24px] leading-tight tracking-[-0.01em] print:text-[18px]">
                {s.title}
              </h2>
              <p className="text-[var(--gray-700)] dark:text-[var(--gray-300)] text-[17px] leading-[28px] text-pretty print:text-[11pt] print:leading-[1.5]">
                {datesNo(s.text)}
              </p>
            </section>
          ))}

          <Separator />

          <section className="break-before-page">
            <div className="mb-4 flex flex-wrap items-baseline justify-between gap-3">
              <h2 className="font-heading text-[24px] leading-tight tracking-[-0.01em]">
                Til regnskapsføreren
              </h2>
              {data.cleanup_text && (
                <Button variant="outline" size="sm" onClick={copy} className="print:hidden">
                  <Copy /> {copied ? "Kopiert" : "Kopier teksten"}
                </Button>
              )}
            </div>
            {data.cleanup.length ? (
              <>
                <p className="text-muted-foreground mb-5 text-[15px]">{data.cleanup_intro}</p>
                <ol className="divide-border border-border divide-y border-y">
                  {data.cleanup.map((c, i) => (
                    <li key={c.id} className="flex gap-4 py-3.5 text-[15px] leading-6">
                      <span className="text-muted-foreground w-5 shrink-0 text-right">{i + 1}</span>
                      <span className="text-pretty">{datesNo(c.text)}</span>
                    </li>
                  ))}
                </ol>
              </>
            ) : (
              <p className="text-[15px]">Ingenting å rydde: kontrollene fant ikke noe.</p>
            )}
          </section>

          <p className="text-muted-foreground text-[13px]">
            Laget {dateNo(data.made_on)} fra tallene i Tripletex
            {data.written_by === "engine" &&
              " — skrevet ut fra tallene alene denne gangen, uten Arvakas egne ord"}
            .
          </p>
        </article>
      )}
    </div>
  )
}
