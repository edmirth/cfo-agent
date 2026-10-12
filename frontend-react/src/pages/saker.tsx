import { useEffect, useState } from "react"
import { Copy } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Textarea } from "@/components/ui/textarea"
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
  // Utkastet slik det står i boksen, når det er endret. Sendes med valget, så
  // det huskes at teksten ble endret før den ble godkjent.
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const draftOf = (c: DeckCard) => drafts[c.id] ?? c.draft?.text ?? ""

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

  // Why the last choice on a card did not go through, shown on that card. A
  // refused choice used to look exactly like one that had not been made yet.
  const [failed, setFailed] = useState<{ id: string; msg: string } | null>(null)

  const decide = async (cardId: string, option: string) => {
    const card = deck?.open.find((x) => x.id === cardId)
    setBusy(cardId)
    setFailed(null)
    try {
      const res = await authFetch(`/api/cards/${cardId}/decide`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          option,
          ...(card?.draft ? { draft_text: draftOf(card) } : {}),
        }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => null)
        setFailed({
          id: cardId,
          msg: typeof body?.detail === "string" ? body.detail : "Valget ble ikke lagret.",
        })
      }
    } catch {
      setFailed({ id: cardId, msg: "Fikk ikke kontakt med serveren. Valget ble ikke lagret." })
    } finally {
      // Reloaded either way: a card closed in the meantime should go, not
      // stay on the page with buttons that are refused.
      await load()
      setBusy(null)
    }
  }

  const copy = (c: DeckCard) => {
    navigator.clipboard?.writeText(draftOf(c)).then(() => {
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
                      {e.value.startsWith("https://") ? (
                        <a href={e.value} target="_blank" rel="noreferrer"
                           className="font-medium underline underline-offset-4">
                          Åpne
                        </a>
                      ) : (
                        <b className="font-mono font-medium tabular-nums">{e.value}</b>
                      )}
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
                    <Textarea
                      value={draftOf(c)}
                      onChange={(e) => setDrafts((d) => ({ ...d, [c.id]: e.target.value }))}
                      rows={Math.min(14, Math.max(4, draftOf(c).split("\n").length + 1))}
                      className="bg-background text-sm"
                      aria-label="Utkastet, kan endres før du sender"
                    />
                    <div className="mt-3 flex flex-wrap items-center gap-3">
                      <Button variant="outline" size="sm" onClick={() => copy(c)}>
                        <Copy /> {copied === c.id ? "Kopiert" : "Kopier teksten"}
                      </Button>
                      {drafts[c.id] !== undefined && drafts[c.id] !== c.draft.text && (
                        <>
                          <span className="text-muted-foreground text-xs">Endret av deg</span>
                          <Button
                            variant="link"
                            size="sm"
                            className="h-auto p-0 text-xs"
                            onClick={() =>
                              setDrafts((d) => {
                                const rest = { ...d }
                                delete rest[c.id]
                                return rest
                              })
                            }
                          >
                            Tilbake til CFO-ens tekst
                          </Button>
                        </>
                      )}
                    </div>
                  </CollapsibleContent>
                </Collapsible>
              )}

              {failed?.id === c.id && (
                <p className="text-destructive text-sm" role="alert">{failed.msg}</p>
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
