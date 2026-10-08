import { useEffect, useState } from "react"
import { Copy } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import { get } from "@/lib/api"
import { dateNo } from "@/lib/format"
import { authFetch } from "@/lib/auth"

type Option = { id: string; label: string; effect: string; days?: number }

type DeckCard = {
  id: string
  key: string
  kind: string
  urgency: "high" | "medium" | "low" | string
  title: string
  body: string
  amount?: number
  evidence?: { label: string; value: string }[]
  draft?: { kind: string; subject?: string; text: string }
  options?: Option[]
  snooze_until?: string
}

type Deck = { as_of: string; open: DeckCard[]; snoozed: DeckCard[]; recent: DeckCard[] }

const edge = (u: string) =>
  u === "high" ? "var(--destructive)" : u === "medium" ? "var(--chart-expected)" : "var(--border)"

export function Saker({
  onCount,
  focus,
}: {
  onCount?: (n: number) => void
  /** En sak å vise fram, fra en lenke i mandagsbrevet (#saker/K016). */
  focus?: string | null
}) {
  const [deck, setDeck] = useState<Deck | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [copied, setCopied] = useState<string | null>(null)

  // Hentes hver gang: en sak kan ha løst seg siden sist man så på den.
  const load = () =>
    get<Deck>("/api/cards")
      .then((d) => {
        setDeck(d)
        onCount?.(d.open.length)
      })
      .catch(() => {})

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const decide = async (cardId: string, option: string) => {
    setBusy(cardId)
    try {
      await authFetch(`/api/cards/${cardId}/decide`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ option }),
      })
      await load()
    } finally {
      setBusy(null)
    }
  }

  const copy = (c: DeckCard) => {
    navigator.clipboard?.writeText(c.draft?.text || "").then(() => {
      setCopied(c.id)
      setTimeout(() => setCopied(null), 2000)
    })
  }

  // Når saken lenken peker på er lastet, ruller siden dit. Er den avgjort
  // siden brevet ble skrevet, står den ikke blant de åpne, og ingenting skjer.
  useEffect(() => {
    if (!focus || !deck) return
    document.getElementById(`sak-${focus}`)?.scrollIntoView({ behavior: "smooth", block: "center" })
  }, [focus, deck])

  const open = deck?.open || []
  const later = deck?.snoozed || []

  return (
    <div className="space-y-10 pt-6">
      <header>
        <p className="text-muted-foreground mb-3 font-mono text-[11px] tracking-[0.16em] uppercase">
          Klart til deg
        </p>
        <h1 className="font-heading text-[30px] leading-tight font-semibold tracking-tight text-pretty">
          {open.length
            ? `${open.length} sak${open.length === 1 ? "" : "er"} venter på deg`
            : "Ingenting venter på deg nå"}
        </h1>
        <p className="text-muted-foreground mt-2.5 max-w-[54ch] text-sm">
          Sakene er forberedt og tallene er hentet. Du trenger bare å bestemme.
        </p>
      </header>

      <div className="grid gap-4">
        {open.map((c) => (
          <Card
            key={c.id}
            id={`sak-${c.id}`}
            className={`border-l-4 gap-3 ${focus === c.id ? "ring-ring ring-2" : ""}`}
            style={{ borderLeftColor: edge(c.urgency) }}
          >
            <CardHeader className="gap-1">
              <CardTitle className="text-base">{c.title}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <p className="text-muted-foreground text-sm">{c.body}</p>

              {!!c.evidence?.length && (
                <ul className="divide-border divide-y border-y text-sm">
                  {c.evidence.map((e, i) => (
                    <li key={i} className="flex justify-between gap-6 py-2">
                      <span className="text-muted-foreground">{e.label}</span>
                      <b className="font-mono font-medium tabular-nums">{e.value}</b>
                    </li>
                  ))}
                </ul>
              )}

              {c.draft && (
                <Collapsible>
                  <CollapsibleTrigger className="text-muted-foreground hover:text-foreground text-sm">
                    Se utkastet ▾
                  </CollapsibleTrigger>
                  <CollapsibleContent className="bg-muted/50 mt-2 rounded-md border p-4">
                    {c.draft.subject && (
                      <p className="mb-2 text-sm font-medium">{c.draft.subject}</p>
                    )}
                    <pre className="text-muted-foreground font-sans text-sm whitespace-pre-wrap">
                      {c.draft.text}
                    </pre>
                    <Button
                      variant="outline"
                      size="sm"
                      className="mt-3"
                      onClick={() => copy(c)}
                    >
                      <Copy /> {copied === c.id ? "Kopiert" : "Kopier teksten"}
                    </Button>
                  </CollapsibleContent>
                </Collapsible>
              )}

              <div className="flex flex-wrap gap-2">
                {(c.options || []).map((o, i) => (
                  <Button
                    key={o.id}
                    variant={i === 0 ? "default" : "outline"}
                    size="sm"
                    disabled={busy === c.id}
                    onClick={() => decide(c.id, o.id)}
                  >
                    {o.label}
                  </Button>
                ))}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {!open.length && !later.length && deck && (
        <p className="text-muted-foreground max-w-[48ch]">
          Ingenting venter på deg nå. Dukker det opp noe, havner det her.
        </p>
      )}

      {!!later.length && (
        <section>
          <div className="mb-3 flex items-baseline justify-between">
            <h2 className="text-[17px] font-semibold">Utsatt</h2>
            <span className="text-muted-foreground font-mono text-xs">
              {later.length} sak{later.length === 1 ? "" : "er"}
            </span>
          </div>
          <ul className="divide-border divide-y border-t">
            {later.map((c) => (
              <li key={c.id} className="flex items-center justify-between gap-6 py-2.5 text-sm">
                <span>{c.title}</span>
                <Badge variant="secondary" className="font-mono">
                  tilbake {c.snooze_until ? dateNo(c.snooze_until) : "snart"}
                </Badge>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
