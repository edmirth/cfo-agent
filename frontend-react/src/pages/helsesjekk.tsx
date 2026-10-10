/* Helsesjekken: hvor selskapet står, og hva regnskapsføreren må rydde.
 * Lages på knappen og en gang i måneden. Siden er laget for å skrives ut —
 * nettleserens «Skriv ut → Lagre som PDF» gir dokumentet som kan sendes videre. */
import { useEffect, useState } from "react"
import { Copy, Printer } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Separator } from "@/components/ui/separator"
import { Skeleton } from "@/components/ui/skeleton"
import { get } from "@/lib/api"
import { authFetch } from "@/lib/auth"
import { dateNo } from "@/lib/format"

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
    <div className="space-y-8 pt-6 print:pt-0">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-muted-foreground mb-3 font-mono text-[11px] tracking-[0.16em] uppercase">
            Helsesjekk{data ? ` · ${dateNo(data.made_on)}` : ""}
          </p>
          <h1 className="font-heading text-[30px] leading-tight font-semibold tracking-tight">
            Hvor selskapet står
          </h1>
        </div>
        <div className="flex gap-2 print:hidden">
          {data && (
            <Button variant="outline" size="sm" onClick={() => window.print()}>
              <Printer /> Skriv ut / lagre som PDF
            </Button>
          )}
          <Button size="sm" onClick={make} disabled={making}>
            {making ? "Lager … (et minutt eller to)" : data ? "Lag ny" : "Lag helsesjekken"}
          </Button>
        </div>
      </header>

      {failed && <p className="text-destructive text-sm print:hidden">{failed}</p>}

      {data === undefined || making ? (
        <div className="grid max-w-3xl gap-3">
          <Skeleton className="h-5 w-2/3" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-[90%]" />
          <Skeleton className="h-4 w-[95%]" />
        </div>
      ) : !data ? (
        <p className="text-muted-foreground max-w-[60ch] text-sm">
          Ingen helsesjekk er laget ennå. Den lages også av seg selv på den 6. virkedagen i
          hver måned.
        </p>
      ) : (
        <article className="max-w-3xl space-y-7">
          <p className="text-[17px] leading-relaxed font-medium text-pretty">{data.summary}</p>

          {data.sections.map((s) => (
            <section key={s.key} className="break-inside-avoid">
              <h2 className="mb-2 text-[17px] font-semibold">{s.title}</h2>
              <p className="text-[15px] leading-relaxed text-pretty">{s.text}</p>
            </section>
          ))}

          <Separator />

          <section className="break-before-page">
            <div className="mb-3 flex flex-wrap items-baseline justify-between gap-3">
              <h2 className="text-[17px] font-semibold">Til regnskapsføreren</h2>
              {data.cleanup_text && (
                <Button variant="outline" size="sm" onClick={copy} className="print:hidden">
                  <Copy /> {copied ? "Kopiert" : "Kopier teksten"}
                </Button>
              )}
            </div>
            {data.cleanup.length ? (
              <>
                <p className="text-muted-foreground mb-3 text-sm">{data.cleanup_intro}</p>
                <ol className="list-decimal space-y-2 pl-5 text-[15px] leading-relaxed">
                  {data.cleanup.map((c) => (
                    <li key={c.id}>{c.text}</li>
                  ))}
                </ol>
              </>
            ) : (
              <p className="text-sm">Ingenting å rydde: kontrollene fant ikke noe.</p>
            )}
          </section>

          <p className="text-muted-foreground text-xs">
            Laget {dateNo(data.made_on)} fra tallene i Tripletex
            {data.written_by === "engine" &&
              " — skrevet ut fra tallene alene denne gangen, uten CFO-ens egne ord"}
            .
          </p>
        </article>
      )}
    </div>
  )
}
