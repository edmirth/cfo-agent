/* En sak som venter på daglig leder: forberedt, med tallene hentet og
 * knappene klare. Brukes på Saker og øverst i Brief («Trenger deg»), så et
 * valg tatt det ene stedet er det samme valget som det andre.
 *
 * Én sak er åpen om gangen med én hovedknapp; resten står som rolige rader.
 * Rødt bare når det faktisk haster — fargen sier ikke mer enn ordet ved siden
 * av. */
import { useCallback, useEffect, useState } from "react"
import { ChevronDown, Copy } from "lucide-react"

import { Dot } from "@/components/brand"
import { Button } from "@/components/ui/button"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import { Textarea } from "@/components/ui/textarea"
import { get } from "@/lib/api"
import { authFetch } from "@/lib/auth"
import { datesNo, fact, kr } from "@/lib/format"

export type Option = { id: string; label: string; effect: string; days?: number }

export type DeckCard = {
  id: string
  key: string
  kind: string
  urgency: "high" | "medium" | "low" | string
  title: string
  body: string
  amount?: number
  evidence?: { label: string; value: string }[]
  // `original` is the CFO's text, kept once the CEO has changed it.
  draft?: { kind: string; subject?: string; text: string; original?: string }
  options?: Option[]
  snooze_until?: string
}

export type Deck = { as_of: string; open: DeckCard[]; snoozed: DeckCard[]; recent: DeckCard[] }

/** Sakene, og det som skal til for å bestemme over dem. Hentes hver gang: en
 *  sak kan ha løst seg siden sist man så på den. */
export function useDeck(onCount?: (n: number) => void) {
  const [deck, setDeck] = useState<Deck | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  // Why the last choice on a card did not go through, shown on that card. A
  // refused choice used to look exactly like one that had not been made yet.
  const [failed, setFailed] = useState<{ id: string; msg: string } | null>(null)
  // Utkastet slik det står i boksen, når det er endret. Sendes med valget, så
  // det huskes at teksten ble endret før den ble godkjent.
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const draftOf = (c: DeckCard) => drafts[c.id] ?? c.draft?.text ?? ""
  const setDraft = (id: string, text: string) => setDrafts((d) => ({ ...d, [id]: text }))

  const load = useCallback(
    () =>
      get<Deck>("/api/cards")
        .then((d) => {
          setDeck(d)
          onCount?.(d.open.length)
        })
        .catch(() => {}),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  )

  useEffect(() => {
    load()
  }, [load])

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

  return { deck, load, decide, busy, failed, draftOf, setDraft }
}

export type DeckState = ReturnType<typeof useDeck>

const URGENCY: Record<string, { word: string; tone: "bad" | "warn" | "quiet" }> = {
  high: { word: "Haster", tone: "bad" },
  medium: { word: "Snart", tone: "warn" },
  low: { word: "Kan vente", tone: "quiet" },
}
const urgency = (u: string) => URGENCY[u] ?? URGENCY.low

// Most card titles say their amount already. Compared without spaces: the
// backend groups digits with plain spaces, `kr` with non-breaking ones.
const said = (title: string, amount: number) =>
  title.replace(/\s/g, "").includes(kr(amount).replace(/\s/g, ""))

/** Fakta på saken som en tabell med hårstreker; regelen den er målt mot står
 *  for seg under, som en fotnote, ikke som et tall. */
function Facts({ evidence }: { evidence: NonNullable<DeckCard["evidence"]> }) {
  const rules = evidence.filter((e) => /^regel$/i.test(e.label.trim()))
  const rows = evidence.filter((e) => !/^regel$/i.test(e.label.trim()))
  return (
    <div>
      {rows.length > 0 && (
        <dl className="border-border divide-border divide-y border-y text-sm">
          {rows.map((e, i) => {
            const f = fact(e.label, e.value)
            return (
              <div key={i} className="flex items-baseline justify-between gap-6 py-2.5">
                <dt className="text-muted-foreground">{f.label}</dt>
                <dd className="text-right tabular-nums">
                  {e.value.startsWith("https://") ? (
                    <a
                      href={e.value}
                      target="_blank"
                      rel="noreferrer"
                      className="text-good-text font-medium hover:underline"
                    >
                      Åpne i Tripletex →
                    </a>
                  ) : (
                    f.value
                  )}
                </dd>
              </div>
            )
          })}
        </dl>
      )}
      {rules.map((r, i) => (
        <p key={i} className="text-muted-foreground mt-2.5 text-[13px] leading-5">
          Målt mot: {datesNo(r.value)}
        </p>
      ))}
    </div>
  )
}

function Draft({ c, state }: { c: DeckCard; state: DeckState }) {
  const [copied, setCopied] = useState(false)
  const text = state.draftOf(c)
  const original = c.draft?.original ?? c.draft?.text ?? ""
  const copy = () =>
    navigator.clipboard?.writeText(text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  return (
    <Collapsible>
      <CollapsibleTrigger className="group text-good-text flex items-center gap-1.5 text-sm font-medium">
        Se utkastet
        <ChevronDown className="size-4 stroke-[1.5] transition-transform duration-300 group-data-[panel-open]:rotate-180" />
      </CollapsibleTrigger>
      <CollapsibleContent className="mt-3">
        {c.draft?.subject && <p className="mb-2 text-sm font-medium">{c.draft.subject}</p>}
        <Textarea
          value={text}
          onChange={(e) => state.setDraft(c.id, e.target.value)}
          rows={Math.min(14, Math.max(4, text.split("\n").length + 1))}
          className="text-sm leading-6"
          aria-label="Utkastet, kan endres før du sender"
        />
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <Button variant="outline" size="sm" onClick={copy}>
            <Copy /> {copied ? "Kopiert" : "Kopier teksten"}
          </Button>
          {text !== original && (
            <>
              <span className="text-muted-foreground text-[13px]">Endret av deg</span>
              <Button variant="link" size="sm" onClick={() => state.setDraft(c.id, original)}>
                Tilbake til Arvakas tekst
              </Button>
            </>
          )}
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}

/** Den åpne saken: hva, hvorfor, tallene, og knappene. Første valg er
 *  hovedknappen; de andre er sekundære. */
export function DecisionBody({
  c,
  state,
  facts = true,
}: {
  c: DeckCard
  state: DeckState
  facts?: boolean
}) {
  const u = urgency(c.urgency)
  return (
    <div className="grid gap-5">
      <div className="grid gap-2">
        <span className="label flex items-center gap-2">
          <Dot tone={u.tone} />
          {u.word}
          {c.amount && !said(c.title, c.amount) ? ` · ${kr(c.amount)} kr` : ""}
        </span>
        <h3 className="text-[20px] leading-[28px] font-medium tracking-[-0.005em] text-pretty">
          {c.title}
        </h3>
        <p className="text-[var(--gray-700)] dark:text-[var(--gray-300)] max-w-[68ch] text-[15px] leading-6 text-pretty">
          {datesNo(c.body)}
        </p>
      </div>

      {facts && !!c.evidence?.length && <Facts evidence={c.evidence} />}
      {c.draft && <Draft c={c} state={state} />}

      {state.failed?.id === c.id && (
        <p className="text-bad-text text-sm" role="alert">
          {state.failed.msg}
        </p>
      )}

      {!!c.options?.length && (
        <div className="flex flex-wrap gap-2">
          {c.options.map((o, i) => (
            <Button
              key={o.id}
              variant={i === 0 ? "default" : "secondary"}
              disabled={state.busy === c.id}
              onClick={() => state.decide(c.id, o.id)}
              title={o.effect}
            >
              {o.label}
            </Button>
          ))}
        </div>
      )}
    </div>
  )
}

/** En sak i lista: lukket er den én rolig rad, åpen er den hele saken. */
export function DecisionRow({
  c,
  state,
  open,
  onOpenChange,
  highlight,
}: {
  c: DeckCard
  state: DeckState
  open: boolean
  onOpenChange: (open: boolean) => void
  highlight?: boolean
}) {
  const u = urgency(c.urgency)
  return (
    <Collapsible
      open={open}
      onOpenChange={onOpenChange}
      id={`sak-${c.id}`}
      className={`bg-card rounded-md border transition-colors duration-300 ${
        highlight ? "border-ring" : "border-border"
      }`}
    >
      {!open && (
        <CollapsibleTrigger className="hover:bg-tint flex w-full items-center gap-4 rounded-md px-6 py-4 text-left transition-colors duration-150">
          <Dot tone={u.tone} />
          <span className="min-w-0 flex-1 text-[15px] font-medium text-pretty">{c.title}</span>
          <span className="label hidden shrink-0 sm:inline">{u.word}</span>
          <ChevronDown className="text-muted-foreground size-4 shrink-0 stroke-[1.5]" />
        </CollapsibleTrigger>
      )}
      <CollapsibleContent className="px-6 pt-6 pb-7">
        <DecisionBody c={c} state={state} />
      </CollapsibleContent>
    </Collapsible>
  )
}
