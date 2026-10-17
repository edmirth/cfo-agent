import { useEffect, useState } from "react"

import { PageHeader, SectionHead } from "@/components/brand"
import { DecisionRow, useDeck } from "@/components/decision"
import { Badge } from "@/components/ui/badge"
import { dateNo } from "@/lib/format"

export function Saker({
  onCount,
  focus,
}: {
  onCount?: (n: number) => void
  /** En sak å vise fram, fra en lenke i mandagsbrevet (#saker/K016). */
  focus?: string | null
}) {
  const state = useDeck(onCount)
  const { deck } = state
  const open = deck?.open || []
  const later = deck?.snoozed || []

  // Én sak er åpen om gangen: den lenken peker på, ellers den øverste. Er den
  // avgjort siden brevet ble skrevet, står den ikke blant de åpne, og da
  // åpnes den øverste i stedet.
  // «» betyr at brukeren har lukket alle; da åpnes ingen av seg selv.
  const [current, setCurrent] = useState<string | undefined>(undefined)
  const fallback = open.some((c) => c.id === focus) ? focus : (open[0]?.id ?? null)
  const shown =
    current === "" ? null : open.some((c) => c.id === current) ? current : fallback

  // Når saken lenken peker på er lastet, ruller siden dit.
  useEffect(() => {
    if (!focus || !deck) return
    document.getElementById(`sak-${focus}`)?.scrollIntoView({ behavior: "smooth", block: "center" })
  }, [focus, deck])

  return (
    <div className="space-y-14">
      <PageHeader
        eyebrow="Klart til deg"
        title={
          !deck
            ? "Henter sakene …"
            : open.length
              ? `${open.length} sak${open.length === 1 ? "" : "er"} venter på deg.`
              : "Ingenting venter på deg nå."
        }
        lead={
          open.length
            ? "Sakene er forberedt og tallene er hentet. Du trenger bare å bestemme."
            : deck
              ? "Dukker det opp noe, havner det her."
              : undefined
        }
      />

      {!!open.length && (
        <div className="grid gap-3">
          {open.map((c, i) => (
            <div key={c.id} className="arv-rise" style={{ "--i": i } as React.CSSProperties}>
              <DecisionRow
                c={c}
                state={state}
                open={shown === c.id}
                onOpenChange={(o) => setCurrent(o ? c.id : "")}
                highlight={focus === c.id}
              />
            </div>
          ))}
        </div>
      )}

      {!!later.length && (
        <section>
          <SectionHead
            title="Utsatt"
            aside={`${later.length} sak${later.length === 1 ? "" : "er"}`}
          />
          <ul className="divide-border divide-y border-y">
            {later.map((c) => (
              <li key={c.id} className="flex items-center justify-between gap-6 py-3 text-sm">
                <span className="text-pretty">{c.title}</span>
                <Badge variant="secondary" className="shrink-0">
                  Tilbake {c.snooze_until ? dateNo(c.snooze_until) : "snart"}
                </Badge>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
