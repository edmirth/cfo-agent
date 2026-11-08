import { useEffect, useState } from "react"

import { PageHeader, SectionHead } from "@/components/brand"
import { DecisionRow, useDeck, type CollectionRow } from "@/components/decision"
import { Badge } from "@/components/ui/badge"
import { dateNo, kr } from "@/lib/format"

const HABIT: Record<CollectionRow["habit"], string> = {
  uvanlig: "Uvanlig sen",
  fast: "Fast sen betaler",
  ny: "Ukjent vane",
}

/** Dagens innkreving (kort 20): hver kunde som er på etterskudd, med det som
 *  skal gjøres i dag øverst. En rad med en åpen sak åpner den saken. */
function Innkreving({
  rows,
  today,
  onOpen,
}: {
  rows: CollectionRow[]
  today: number
  onOpen: (id: string) => void
}) {
  return (
    <section>
      <SectionHead
        title="Innkreving i dag"
        aside={today ? `${today} å gjøre i dag` : "Ingenting å sende i dag"}
      />
      <ul className="divide-border divide-y border-y">
        {rows.map((r) => {
          const habit =
            r.habit_days !== null && r.habit !== "ny"
              ? `${HABIT[r.habit]} · betaler vanligvis ${r.habit_days} d etter forfall`
              : HABIT[r.habit]
          const body = (
            <>
              <span className="min-w-0 flex-1">
                <span className="block text-[15px] font-medium text-pretty">{r.customer}</span>
                <span className="text-muted-foreground block text-[13px]">
                  {kr(r.amount)} kr · {r.late} dager på etterskudd · {habit}
                </span>
              </span>
              <span className="shrink-0 text-right">
                {r.today ? (
                  <Badge variant={r.step === 3 || r.habit === "uvanlig" ? "destructive" : "default"}>
                    {r.action}
                  </Badge>
                ) : (
                  <span className="text-muted-foreground text-[13px]">
                    {r.action}
                    {r.until ? ` til ${dateNo(r.until)}` : ""}
                  </span>
                )}
              </span>
            </>
          )
          return (
            <li key={r.customer}>
              {r.today && r.card ? (
                <button
                  type="button"
                  onClick={() => onOpen(r.card!)}
                  className="hover:bg-tint flex w-full items-center gap-6 py-3 text-left transition-colors duration-150"
                >
                  {body}
                </button>
              ) : (
                <div className="flex items-center gap-6 py-3">{body}</div>
              )}
            </li>
          )
        })}
      </ul>
    </section>
  )
}

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

      {!!deck?.collections?.rows.length && (
        <Innkreving
          rows={deck.collections.rows}
          today={deck.collections.today}
          onOpen={(id) => {
            setCurrent(id)
            document.getElementById(`sak-${id}`)?.scrollIntoView({ behavior: "smooth", block: "center" })
          }}
        />
      )}

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
